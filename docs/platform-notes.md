# Platform notes

Why this repo defaults to FRRouting instead of a vendor router OS,
and what was actually tried first.

## What was tried, in order

1. **Arista cEOS-lab** — the original plan, and what all the earlier
   templates (`pe.conf.j2`, `bgplu_pe.conf.j2`, etc.) are written for.
   Blocked at account registration: `arista.com`'s software-download
   portal rejects personal email domains outright ("Registration with
   this email domain is restricted"). Cloud-marketplace vEOS (AWS/
   Azure) hits the identical account wall, plus is a full VM rather
   than a container.

2. **Cisco Catalyst 8000V** — obtained a real `.qcow2` legitimately
   through Cisco's DevNet portal (`c8000v-universalk9_8G_serial`,
   17.16.01a). Built successfully via `vrnetlab` on Apple Silicon, but
   the container crashed on every launch: `qemu-system-x86_64: CPU
   model 'host' requires KVM or HVF`. C8000V ships x86_64-only, and
   Apple's Hypervisor.framework (HVF) doesn't accelerate cross-
   architecture VMs — so this is a hard architectural wall, not a
   config issue. Would technically run under full QEMU software
   emulation (TCG) with the launch script patched to drop `-cpu
   host`, but realistically tens of minutes to boot and sluggish
   afterward — not practical for iterative lab work.

3. **Nokia SR Linux** — genuinely free, native ARM64 image, pulls
   cleanly with zero registration. But the default chassis simulation
   (7220 IXR-D3L) is a fixed-function DC switch platform with **no
   MPLS/Segment Routing at all** — confirmed by walking the full CLI
   schema tree (`tree` command inside `sr_cli`): no `segment-routing`
   node anywhere, and BGP's `afi-safi` list has no
   `ipv4-labeled-unicast`. The chassis variants that do support MPLS/
   SR (`ixr6e`, `ixr10e`) require a Nokia license file — confirmed
   directly in Containerlab's own docs, not just a KNE-specific
   requirement.

4. **Juniper cRPD** — has real, documented IS-IS Segment Routing and
   BGP/MP-BGP support, official ARM64 build. Never actually got a
   working test: the downloaded file's internal structure
   (`virtioa.qcow2` inside the tgz) matched the generic repackaging
   pattern of an unofficial image-sharing site rather than Juniper's
   actual container distribution format (which should extract to a
   `.tar`, not a `.qcow2`) — so this was never confirmed as a
   legitimate download and wasn't pursued further. Worth retrying
   directly from `webdownload.juniper.net` if genuine portal access
   exists.

## Why FRRouting won

- Real open source, MIT-ish licensing, no account or license file —
  ever, on any machine.
- Native multi-arch Docker image (`frrouting/frr`) — genuine ARM64,
  no emulation on Apple Silicon.
- Full BGP (including Labeled-Unicast, RFC 3107) and IS-IS with
  Segment Routing, both actively maintained — not a stripped-down
  free tier of a commercial product.
- `zebra` installs real routes into the Linux kernel FIB, so the lab
  gets genuine hop-by-hop packet forwarding, not just control-plane
  simulation (a real gap in cRPD specifically, which is deliberately
  control-plane-only by design).

## The honest trade-off

FRR's `vtysh` CLI is Cisco-IOS-style, not Arista EOS syntax — so this
is a genuine platform pivot, not a drop-in swap. The `bgplu_pe.conf.j2`
/ `bgplu_p.conf.j2` templates (EOS) and `frr_pe.conf.j2` / `frr_p.conf.j2`
templates (FRR) implement the *same* logical design (flat BGP-LU mesh,
Route Reflectors at the P routers, no overlay) — just in each
platform's own syntax — so the underlying protocol design and the
`topology.py`/`wiring.py` orchestration layer carry over completely
unchanged. If real cEOS access ever comes through, switching back is
just `make TOPO=topologies/global-pe-p-backbone-ceos.yaml full`.
