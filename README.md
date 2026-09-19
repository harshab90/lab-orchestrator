# lab-orchestrator

A minimal, self-built network lab: spins up Arista cEOS-lab containers,
wires them together with real veth pairs (no Containerlab/GNS3), and
pushes generated EOS configs — reproducing a BGP-free MPLS core
(IS-IS + Segment Routing underlay, iBGP-only-at-the-DC-edge overlay)
at small scale.

## Why this exists

Practicing the production backbone design (28 DCs, 50 midpoints,
IS-IS/SR underlay, iBGP overlay, Gold/Silver/Bronze CBTS) without
depending on someone else's lab tool — full control over the wiring
and automation layer, in a form that's reproducible with one command
instead of a checklist to remember.

## Prerequisites

1. **Docker Desktop** (Apple Silicon-native is fine — cEOS runs under
   emulation, see notes below).
2. **An imported cEOS-lab image.** Arista's cEOS ships as a `.tar.xz`
   you import yourself — it isn't pulled from a public registry:
   ```
   docker image import cEOS64-lab-4.32.0F.tar ceos:4.32.0F
   ```
   The tag here must match `image:` in whichever topology YAML you use.
3. Python 3.10+ with `pip install -r requirements.txt` (only needed
   for `make configs` / `make up` — `make wire` runs inside a
   container and needs nothing installed locally).

## Topologies

- `topologies/global-pe-p-backbone.yaml` (default) — 4 PE routers
  (Seattle, Raleigh, India, London) + 2 P routers (Dallas, Singapore).
  Every major hop is 3 independent 5-member port-channels; Seattle-
  Raleigh and Raleigh-London are direct single/bundled shortcuts that
  bypass the core — kept specifically so a later Gold/Silver/Bronze
  CBTS layer has real alternate paths to steer between.
  91 physical links total (1 single + 90 port-channel members).
- `topologies/3dc-2mid.yaml` — the original smaller 3-DC/2-midpoint
  lab, kept as a lighter-weight sanity check (6 physical links).

Switch between them with `make TOPO=topologies/<file>.yaml <target>`.

## Underlay modes

Set per-topology via the top-level `underlay:` field (defaults to
`isis-sr` if omitted):

- **`isis-sr`** — IS-IS + Segment Routing. P routers never run BGP.
  This is the default and what both topology files originally used.
- **`bgp-lu`** — no IGP at all (RFC 8277, "IGP-free core"). Every
  node runs BGP, on direct physical links only — a session exists
  between two nodes if and only if a link exists between them in the
  topology YAML. The P routers (Dallas, Singapore) are **BGP Route
  Reflectors**, relaying everything end-to-end between non-adjacent
  nodes. Since every site in this lab belongs to one company (no
  per-customer VPN/VRF separation needed), there's no separate
  overlay layer either — loopbacks *and* customer prefixes are both
  advertised directly into the same direct-link sessions, in the same
  `address-family ipv4 labeled-unicast`. One flat mesh, reflected by
  the two RRs.

  **Caveat:** this mode hasn't been validated against a running cEOS
  instance in this environment (no Docker access here) — the
  `route-reflector-client` / `address-family ipv4 labeled-unicast`
  syntax matches documented Arista EOS BGP-LU patterns, but is more
  niche than plain BGP/IS-IS, so treat the first `make full` run on
  this topology as the actual verification step, and check
  `show bgp neighbors` / `show mpls route` if sessions don't come up
  as expected.

`topologies/global-pe-p-backbone.yaml` currently uses `bgp-lu`;
`topologies/3dc-2mid.yaml` still uses the `isis-sr` default.

## Quickstart — reproduce the whole lab

```
make full          # renders configs, starts containers, wires links
make status         # confirm all 5 nodes are Up
docker exec -it dc1 Cli
```

Inside the EOS CLI:
```
show isis segment-routing tunnel
show ip bgp summary
show ip route 172.16.0.3/32
```

Tear down and start clean:
```
make clean
```

## Repo layout

```
topologies/3dc-2mid.yaml     - the topology: nodes, roles, loopbacks, links
                                (edit this to change the lab; everything
                                else derives from it)
orchestrator/
  topology.py                 - loads + validates the YAML
  configgen.py                 - renders EOS startup-configs from templates
  docker_manager.py           - starts/stops cEOS containers
  wiring.py                    - creates veth pairs, grafts into netns
  cli.py                        - single entrypoint (configs/up/wire/down/status)
configs/templates/            - Jinja2 templates: dc.conf.j2, midpoint.conf.j2
configs/generated/            - rendered per-node startup-configs (gitignored,
                                reproducible from templates + topology)
scripts/Dockerfile.wiring     - privileged helper image used only for wiring
Makefile                       - the actual commands you run
```

## Why wiring runs inside a container (`make wire`)

On Docker Desktop for Mac, containers live inside a hidden Linux VM —
there's no host shell to run `ip netns` against directly. `make wire`
builds a small privileged helper image (iproute2 + docker CLI) and
runs it with `--pid=host`, so `/proc/<pid>/ns/net` resolves to the
real container namespaces inside Docker's VM. The wiring logic itself
(`orchestrator/wiring.py`) is identical either way — this is purely
about *where* it executes.

## Apple Silicon note

cEOS-lab's mature image is x86_64-only; Docker runs it under Rosetta/
QEMU emulation on M-series Macs. This works, but scale expectations
should stay modest locally (a handful of nodes, not the full 28-DC
design) — that's the whole reason this lab uses a representative
5-node slice instead of the real topology size.

## Adding a new topology

Copy `topologies/3dc-2mid.yaml`, change nodes/links, then:
```
make TOPO=topologies/my-new-lab.yaml full
```
No other files need to change — config generation, container startup,
and wiring all read from whatever `TOPO` points at.

## Known limitations / next steps

- `wiring.py` doesn't yet clean up veth pairs on `make down` — they
  disappear when their container namespace is destroyed, so it's
  harmless, but `ip link` on the helper won't show a live "no
  stragglers" confirmation.
- No CBTS / SR-TE policy generation yet — the templates only build the
  base IS-IS + BGP layer this conversation validated first.
- No automated verification step (`show isis segment-routing tunnel`
  parsing) — checking convergence is manual via `docker exec` for now.
