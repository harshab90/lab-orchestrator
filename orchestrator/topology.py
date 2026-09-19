"""
Loads a topology YAML file into plain Python objects that the rest of
the orchestrator (config generation, container startup, wiring) reads
from. Keeping this as one small module means every other file trusts
a single, validated in-memory shape instead of re-parsing YAML.

Supports two kinds of connections between nodes:
  - single_links: one plain point-to-point Ethernet link
  - bundles: a group of N member Ethernet links between the same pair
    of nodes. Multiple bundle entries between the same pair of nodes
    produce multiple independent groups.

Supports two platforms, set per-topology via top-level `platform:`
(defaults to "ceos"):
  - "ceos" — Arista EOS. Bundle members are aggregated into a real
    Port-Channel (LAG) interface per bundle, one BGP-LU session per
    Port-Channel.
  - "frr" — FRRouting on plain Linux. Linux doesn't do LAG-style
    bonding through routing config the way EOS does, so each bundle
    member is instead treated as its own independent routed link with
    its own auto-derived /31 subnet (offset from the bundle's base
    subnet) — one BGP-LU session per physical member instead of per
    bundle. Same ECMP/redundancy behavior, just N separate sessions
    instead of 1 bonded one.

Supports two underlay modes, set per-topology via top-level `underlay:`:
  - "isis-sr" (default) — IS-IS + Segment Routing underlay, P routers
    never run BGP. (ceos platform only, currently.)
  - "bgp-lu" — no IGP at all. Every node runs BGP. Core (P) nodes are
    BGP Route Reflectors, peering hop-by-hop over each directly
    connected interface in address-family ipv4 labeled-unicast
    (RFC 8277) and reflecting between clients — this is what actually
    makes "iBGP instead of an IGP" possible, since a literal loopback-
    to-loopback full mesh can't bootstrap (loopbacks aren't reachable
    until the underlay exists). Loopbacks AND customer prefixes are
    both advertised directly into these same direct-link sessions —
    single-tenant network, no separate VPN/VRF overlay needed.

Backward compatible with the older flat schema (top-level `links:`,
per-node `loopback1:`) used by earlier topology files.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

import yaml

# Roles that run BGP and originate customer prefixes ("PE" in the
# newer diagrams, "dc" in the original 3-node lab).
EDGE_ROLES = {"dc", "pe"}
# Roles that are pure transit nodes — IS-IS/SR only (isis-sr mode) or
# BGP Route Reflectors (bgp-lu mode), never customer-facing.
CORE_ROLES = {"midpoint", "p"}


@dataclass
class Node:
    name: str
    role: str
    loopback0: str
    isis_net: str | None = None
    isis_sid_index: int | None = None
    bgp_as: int | None = None
    route_reflector: bool = False
    customer_prefixes: list = field(default_factory=list)
    # peer_name -> Ethernet ifnum, for plain point-to-point single_links
    interfaces: dict = field(default_factory=dict)
    # ceos platform only: one entry per port-channel this node is in:
    # {"id": int, "peer": str, "ip": str, "peer_ip": str, "members": [ifnum, ...]}
    port_channels: list = field(default_factory=list)
    # frr platform only: one entry per PHYSICAL link (single_links as-is,
    # bundles expanded to one entry per member with its own subnet):
    # {"ifnum": int, "peer": str, "local_ip": "x.x.x.x/31", "peer_ip": "x.x.x.x"}
    frr_links: list = field(default_factory=list)
    # bgp-lu mode only: one entry per BGP-LU session — granularity
    # depends on platform (per-Port-Channel for ceos, per-physical-
    # member for frr, see module docstring):
    # {"peer": str, "peer_ip": str (bare address, no prefix), "is_client": bool}
    underlay_neighbors: list = field(default_factory=list)

    def is_edge(self) -> bool:
        return self.role in EDGE_ROLES

    def is_core(self) -> bool:
        return self.role in CORE_ROLES


def _ip_for(subnet: str, node_name: str, a: str, b: str) -> str:
    net = ipaddress.ip_network(subnet, strict=False)
    hosts = list(net.hosts())
    if node_name == a:
        return f"{hosts[0]}/{net.prefixlen}"
    if node_name == b:
        return f"{hosts[1]}/{net.prefixlen}"
    raise ValueError(f"{node_name} is not part of link {a}-{b}")


def _addr_only(cidr: str) -> str:
    return cidr.split("/")[0]


@dataclass
class PointToPoint:
    a: str
    b: str
    subnet: str

    def ip_for(self, node_name: str) -> str:
        return _ip_for(self.subnet, node_name, self.a, self.b)


@dataclass
class Bundle:
    a: str
    b: str
    subnet: str
    members: int
    # populated by Topology._assign_interfaces:
    id_a: int = None
    id_b: int = None
    members_a: list = field(default_factory=list)  # this side's Ethernet ifnums
    members_b: list = field(default_factory=list)

    def ip_for(self, node_name: str) -> str:
        """Shared Port-Channel-level address (ceos platform)."""
        return _ip_for(self.subnet, node_name, self.a, self.b)

    def member_ip_for(self, node_name: str, member_index: int) -> str:
        """Per-member address (frr platform): the base subnet shifted
        forward by member_index full subnet-widths, so each member
        gets its own non-overlapping /31 (or whatever width was given)."""
        base = ipaddress.ip_network(self.subnet, strict=False)
        shift = member_index * base.num_addresses
        shifted_addr = ipaddress.ip_address(int(base.network_address) + shift)
        member_net = ipaddress.ip_network(f"{shifted_addr}/{base.prefixlen}", strict=False)
        return _ip_for(str(member_net), node_name, self.a, self.b)


class Topology:
    def __init__(self, path: str):
        with open(path) as f:
            raw = yaml.safe_load(f)

        self.name: str = raw["name"]
        self.image: str = raw["image"]
        self.platform: str = raw.get("platform", "ceos")
        if self.platform not in ("ceos", "frr"):
            raise ValueError(f"Unknown platform: {self.platform!r}")
        self.underlay: str = raw.get("underlay", "isis-sr")
        if self.underlay not in ("isis-sr", "bgp-lu"):
            raise ValueError(f"Unknown underlay mode: {self.underlay!r}")
        if self.platform == "frr" and self.underlay != "bgp-lu":
            raise ValueError("frr platform currently only implements the bgp-lu underlay")

        self.nodes: dict[str, Node] = {}
        for name, spec in raw["nodes"].items():
            spec = dict(spec)
            if "loopback1" in spec:  # legacy single-prefix field
                spec["customer_prefixes"] = [spec.pop("loopback1")]
            self.nodes[name] = Node(name=name, **spec)

        self.single_links: list[PointToPoint] = [
            PointToPoint(**spec) for spec in raw.get("single_links", raw.get("links", []))
        ]
        self.bundles: list[Bundle] = [Bundle(**spec) for spec in raw.get("bundles", [])]

        self._assign_interfaces()
        if self.underlay == "bgp-lu":
            self._assign_underlay_neighbors()
        self._validate()

    def _assign_interfaces(self):
        eth_counter = {name: 0 for name in self.nodes}
        po_counter = {name: 0 for name in self.nodes}

        def next_eth(name):
            eth_counter[name] += 1
            return eth_counter[name]

        for link in self.single_links:
            ifnum_a = next_eth(link.a)
            ifnum_b = next_eth(link.b)
            self.nodes[link.a].interfaces[link.b] = ifnum_a
            self.nodes[link.b].interfaces[link.a] = ifnum_b
            self.nodes[link.a].frr_links.append({
                "ifnum": ifnum_a, "peer": link.b,
                "local_ip": link.ip_for(link.a), "peer_ip": _addr_only(link.ip_for(link.b)),
            })
            self.nodes[link.b].frr_links.append({
                "ifnum": ifnum_b, "peer": link.a,
                "local_ip": link.ip_for(link.b), "peer_ip": _addr_only(link.ip_for(link.a)),
            })

        for bundle in self.bundles:
            for side, other in [(bundle.a, bundle.b), (bundle.b, bundle.a)]:
                po_counter[side] += 1
                pc_id = po_counter[side]
                members = [next_eth(side) for _ in range(bundle.members)]
                if side == bundle.a:
                    bundle.id_a, bundle.members_a = pc_id, members
                else:
                    bundle.id_b, bundle.members_b = pc_id, members
                self.nodes[side].port_channels.append({
                    "id": pc_id,
                    "peer": other,
                    "ip": bundle.ip_for(side),
                    "peer_ip": bundle.ip_for(other),
                    "members": members,
                })
                for idx, ifnum in enumerate(members):
                    self.nodes[side].frr_links.append({
                        "ifnum": ifnum,
                        "peer": other,
                        "local_ip": bundle.member_ip_for(side, idx),
                        "peer_ip": _addr_only(bundle.member_ip_for(other, idx)),
                    })

    def _assign_underlay_neighbors(self):
        """BGP-LU sessions. For ceos: one per single_link, one per
        bundle (Port-Channel-level address). For frr: one per
        PHYSICAL link (single_links as-is, bundles at member
        granularity), since there's no bonded logical interface to
        peer over. RR-client is set only when this node is itself an
        RR and the neighbor is not — a session between two RRs
        (Dallas-Singapore) stays a plain peer relationship so routes
        still propagate correctly per standard route-reflection rules."""
        def is_client(local_name, peer_name):
            local, peer = self.nodes[local_name], self.nodes[peer_name]
            return local.route_reflector and not peer.route_reflector

        if self.platform == "frr":
            for node in self.nodes.values():
                for link in node.frr_links:
                    node.underlay_neighbors.append({
                        "peer": link["peer"],
                        "peer_ip": link["peer_ip"],
                        "is_client": is_client(node.name, link["peer"]),
                    })
            return

        for link in self.single_links:
            for side, other in [(link.a, link.b), (link.b, link.a)]:
                self.nodes[side].underlay_neighbors.append({
                    "peer": other,
                    "peer_ip": _addr_only(link.ip_for(other)),
                    "is_client": is_client(side, other),
                })

        for bundle in self.bundles:
            for side, other in [(bundle.a, bundle.b), (bundle.b, bundle.a)]:
                self.nodes[side].underlay_neighbors.append({
                    "peer": other,
                    "peer_ip": _addr_only(bundle.ip_for(other)),
                    "is_client": is_client(side, other),
                })

    def _validate(self):
        names = set(self.nodes)
        for link in list(self.single_links) + list(self.bundles):
            if link.a not in names or link.b not in names:
                raise ValueError(f"Link references unknown node: {link}")
        edge_ases = {n.bgp_as for n in self.nodes.values() if n.is_edge()}
        if len(edge_ases) > 1:
            raise ValueError("All edge (PE/dc) nodes must share one iBGP AS for this lab")
        if self.underlay == "bgp-lu":
            missing_as = [n.name for n in self.nodes.values() if n.bgp_as is None]
            if missing_as:
                raise ValueError(f"bgp-lu mode requires bgp_as on every node, missing: {missing_as}")

    def edges(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.is_edge()]

    def cores(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.is_core()]

    # kept for backward compatibility with the original 3-node lab naming
    def dcs(self) -> list[Node]:
        return self.edges()

    def midpoints(self) -> list[Node]:
        return self.cores()

    def links_for(self, node_name: str) -> list[PointToPoint]:
        return [l for l in self.single_links if node_name in (l.a, l.b)]
