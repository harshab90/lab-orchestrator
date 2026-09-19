"""
Implements exactly the manual veth-pair procedure we walked through by
hand: for each link in the topology, create a veth pair, move one end
into each container's network namespace, rename it to the ethN cEOS
expects, and bring it up.

IMPORTANT — where this must run:
On native Linux, this can run directly on the host (needs root / CAP_
SYS_ADMIN for `ip netns` and `ip link set netns`). On Docker Desktop
for Mac, containers live inside a hidden Linux VM you don't have a
host shell on, so this module is designed to be executed *inside* the
privileged helper container built from scripts/Dockerfile.wiring (see
`make wire`) — that helper shares the Docker VM's PID namespace
(--pid=host) so /proc/<pid>/ns/net resolves to the real container
namespaces.
"""
import os
import subprocess

from .topology import Topology

NETNS_DIR = "/var/run/netns"


def _run(cmd: list[str]):
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def _container_pid(name: str) -> str:
    out = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Pid}}", name],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def _ensure_netns_symlink(name: str):
    os.makedirs(NETNS_DIR, exist_ok=True)
    pid = _container_pid(name)
    link_path = os.path.join(NETNS_DIR, name)
    target = f"/proc/{pid}/ns/net"
    if os.path.islink(link_path):
        os.remove(link_path)
    os.symlink(target, link_path)


def wire_link(a: str, a_ifnum: int, b: str, b_ifnum: int):
    veth_a, veth_b = f"{a}-e{a_ifnum}", f"{b}-e{b_ifnum}"

    _ensure_netns_symlink(a)
    _ensure_netns_symlink(b)

    _run(["ip", "link", "add", veth_a, "type", "veth", "peer", "name", veth_b])

    for netns_name, veth, ifnum in [(a, veth_a, a_ifnum), (b, veth_b, b_ifnum)]:
        _run(["ip", "link", "set", veth, "netns", netns_name])
        _run(["ip", "netns", "exec", netns_name, "ip", "link", "set", veth, "name", f"eth{ifnum}"])
        _run(["ip", "netns", "exec", netns_name, "ip", "link", "set", f"eth{ifnum}", "up"])


def wire_all(topo: Topology):
    bundle_member_count = sum(b.members for b in topo.bundles)
    total = len(topo.single_links) + bundle_member_count
    print(
        f"Wiring {len(topo.single_links)} single links + "
        f"{len(topo.bundles)} port-channels ({bundle_member_count} member links) "
        f"= {total} physical links..."
    )

    for link in topo.single_links:
        a_ifnum = topo.nodes[link.a].interfaces[link.b]
        b_ifnum = topo.nodes[link.b].interfaces[link.a]
        wire_link(link.a, a_ifnum, link.b, b_ifnum)

    for bundle in topo.bundles:
        for a_ifnum, b_ifnum in zip(bundle.members_a, bundle.members_b):
            wire_link(bundle.a, a_ifnum, bundle.b, b_ifnum)
