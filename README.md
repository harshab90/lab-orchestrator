# lab-orchestrator

A minimal, self-built network lab: spins up router containers, wires
them together with real veth pairs (no Containerlab/GNS3), and pushes
generated configs — reproducing a BGP-free MPLS core (BGP Labeled-
Unicast underlay with Route Reflectors, single flat mesh) at small
scale. Default platform is **FRRouting** — genuinely free, no vendor
account or license anywhere, native ARM64 (no emulation on Apple
Silicon). An equivalent Arista cEOS version is kept alongside it for
whenever a real cEOS image is available.

## Why this exists

Practicing the production backbone design (28 DCs, 50 midpoints,
BGP-LU underlay with Route Reflectors, Gold/Silver/Bronze CBTS)
without depending on someone else's lab tool — full control over the
wiring and automation layer, in a form that's reproducible with one
command instead of a checklist to remember. Started EOS-first, but
every vendor's free-tier router image (Arista, Cisco, Nokia) turned
out to be gated behind a corporate account, an entitlement check, or
a license file — see `docs/platform-notes.md` if that history matters
later. FRRouting sidesteps all of it: real, open-source, no gate.

## Prerequisites

1. **Docker Desktop.**
2. Python 3.10+ with `pip install -r requirements.txt` (only needed
   for `make configs` / `make up` — `make wire` runs inside a
   container and needs nothing installed locally).
3. **For the FRR topology (default): nothing else.** `docker pull
   frrouting/frr:latest` happens automatically on first `make up` —
   no account, no license, native ARM64 on Apple Silicon.
4. **For the cEOS topology only:** an imported cEOS-lab image (Arista
   ships this as a `.tar` you import yourself, not pulled from a
   public registry):
   ```
   docker image import cEOS64-lab-4.32.0F.tar ceos:4.32.0F
   ```
   The tag must match `image:` in `topologies/global-pe-p-backbone-ceos.yaml`.

## Topologies

- `topologies/global-pe-p-backbone.yaml` (default, **FRR**) — 4 PE
  routers (Seattle, Raleigh, India, London) + 2 P routers (Dallas,
  Singapore). Seattle-Raleigh and Raleigh-London are direct shortcuts
  that bypass the core — kept specifically so a later Gold/Silver/
  Bronze CBTS layer has real alternate paths to steer between. Every
  major hop is 3 bundles of 5 members; FRR has no Port-Channel config
  of its own, so each member is wired as its own independent routed
  link (see `topology.py` docstring) — 91 physical links, 91 BGP-LU
  sessions total.
- `topologies/global-pe-p-backbone-ceos.yaml` — the same physical
  design, for Arista cEOS: bundle members are aggregated into real
  Port-Channel interfaces (18 port-channels, one BGP-LU session each).
- `topologies/3dc-2mid.yaml` — the original smaller 3-DC/2-midpoint
  lab (cEOS, IS-IS+SR underlay), kept as a lighter-weight sanity check.

Switch between them with `make TOPO=topologies/<file>.yaml <target>`.

## Platforms

Set per-topology via the top-level `platform:` field (defaults to `ceos`):

- **`frr`** — FRRouting on plain Linux. No LAG/bonding config of its
  own, so bundle members become individual routed links (own /31
  each, auto-derived — see `topology.py`) rather than one bonded
  Port-Channel. Currently implements the `bgp-lu` underlay only.
- **`ceos`** — Arista EOS. Bundle members aggregate into a real
  Port-Channel per bundle. Supports both underlay modes below.

## Underlay modes

Set per-topology via the top-level `underlay:` field (defaults to
`isis-sr` if omitted):

- **`isis-sr`** (`ceos` only, currently) — IS-IS + Segment Routing. P
  routers never run BGP.
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

  **Caveat:** neither the FRR nor the cEOS rendering of this has been
  validated against a running instance in this environment (no Docker
  access here) — both follow documented syntax patterns for their
  platform, but treat the first `make full` run as the actual
  verification step. For FRR: `show bgp summary` and `show bgp ipv4
  labeled-unicast` in `vtysh`. For cEOS: `show bgp neighbors` and
  `show mpls route`.

## Quickstart — reproduce the whole lab

```
make full          # renders configs, starts containers, wires links
make status         # confirm all 6 nodes are Up
docker exec -it seattle vtysh
```

Inside the FRR CLI:
```
show bgp summary
show bgp ipv4 labeled-unicast
show ip route 172.16.0.3/32
```

(For the cEOS topology: `make TOPO=topologies/global-pe-p-backbone-ceos.yaml full`,
then `docker exec -it seattle Cli`.)

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
