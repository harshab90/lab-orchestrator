"""
Wraps the `docker` CLI (kept as subprocess calls, not the Python SDK,
so this has zero extra dependencies beyond Docker itself being
installed) to start/stop containers with the environment each
platform needs to boot into a working CLI instead of a bare shell.

Containers start with --network=none: no interfaces are attached at
all until wiring.py adds them. This is deliberate — it means the only
interfaces the router OS ever sees are the ones you explicitly wired.
"""
import os
import subprocess

from .topology import Topology

GENERATED_DIR = os.path.join(os.path.dirname(__file__), "..", "configs", "generated")

# Standard cEOS boot environment — same flags used by Containerlab/netlab
# under the hood, documented publicly by Arista for running cEOS-lab
# outside a purpose-built orchestrator.
CEOS_ENV = [
    "CEOS=1",
    "EOS_PLATFORM=ceoslab",
    "container=docker",
    "ETBA=1",
    "SKIP_ZEROTOUCH_BARRIER_IN_SYSDBINIT=1",
    "INTFTYPE=eth",
    "MAPETH0=1",
    "MGMT_INTF=eth0",
]


def _run(cmd: list[str], check=True):
    print("  $ " + " ".join(cmd))
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def _start_ceos(topo: Topology, node_name: str, config_dir: str):
    if not os.path.exists(os.path.join(config_dir, "startup-config")):
        raise FileNotFoundError(
            f"No rendered config for {node_name} — run `configs` before `up`"
        )
    cmd = ["docker", "run", "-d", "--name", node_name, "--privileged", "--network=none"]
    for e in CEOS_ENV:
        cmd += ["-e", e]
    cmd += ["-v", f"{config_dir}:/mnt/flash", topo.image]
    return cmd


def _start_frr(topo: Topology, node_name: str, config_dir: str):
    if not os.path.exists(os.path.join(config_dir, "frr.conf")):
        raise FileNotFoundError(
            f"No rendered config for {node_name} — run `configs` before `up`"
        )
    # FRR's official image reads /etc/frr/frr.conf + /etc/frr/daemons at
    # startup and launches whichever daemons the file enables. No env
    # vars needed — just the two files and the right capabilities.
    cmd = [
        "docker", "run", "-d", "--name", node_name, "--privileged", "--network=none",
        "--cap-add=NET_ADMIN", "--cap-add=NET_RAW", "--cap-add=SYS_ADMIN",
        "-v", f"{config_dir}/frr.conf:/etc/frr/frr.conf",
        "-v", f"{config_dir}/daemons:/etc/frr/daemons",
        topo.image,
    ]
    return cmd


def start_node(topo: Topology, node_name: str):
    config_dir = os.path.abspath(os.path.join(GENERATED_DIR, node_name))
    if topo.platform == "frr":
        cmd = _start_frr(topo, node_name, config_dir)
    else:
        cmd = _start_ceos(topo, node_name, config_dir)

    result = _run(cmd, check=False)
    if result.returncode != 0:
        if "already in use" in result.stderr:
            print(f"  {node_name} already running, skipping")
        else:
            raise RuntimeError(f"Failed to start {node_name}: {result.stderr}")


def stop_node(node_name: str):
    _run(["docker", "rm", "-f", node_name], check=False)


def up(topo: Topology):
    print(f"Starting {len(topo.nodes)} nodes ({topo.platform})...")
    for name in topo.nodes:
        start_node(topo, name)


def down(topo: Topology):
    print(f"Stopping {len(topo.nodes)} nodes...")
    for name in topo.nodes:
        stop_node(name)


def status(topo: Topology):
    names = list(topo.nodes)
    result = _run(
        ["docker", "ps", "-a", "--filter", f"name={'|'.join(names)}",
         "--format", "table {{.Names}}\t{{.Status}}"],
        check=False,
    )
    print(result.stdout)
