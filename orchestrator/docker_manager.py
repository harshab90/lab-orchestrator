"""
Wraps the `docker` CLI (kept as subprocess calls, not the Python SDK,
so this has zero extra dependencies beyond Docker itself being
installed) to start/stop cEOS containers with the environment cEOS
needs to boot into a working EOS CLI instead of a bare Linux shell.

Containers start with --network=none: no interfaces are attached at
all until wiring.py adds them. This is deliberate — it means the only
interfaces EOS ever sees are the ones you explicitly wired.
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


def start_node(topo: Topology, node_name: str):
    node = topo.nodes[node_name]
    config_dir = os.path.abspath(os.path.join(GENERATED_DIR, node_name))
    if not os.path.exists(os.path.join(config_dir, "startup-config")):
        raise FileNotFoundError(
            f"No rendered config for {node_name} — run `configs` before `up`"
        )

    cmd = ["docker", "run", "-d", "--name", node_name, "--privileged", "--network=none"]
    for e in CEOS_ENV:
        cmd += ["-e", e]
    cmd += ["-v", f"{config_dir}:/mnt/flash", topo.image]

    result = _run(cmd, check=False)
    if result.returncode != 0:
        if "already in use" in result.stderr:
            print(f"  {node_name} already running, skipping")
        else:
            raise RuntimeError(f"Failed to start {node_name}: {result.stderr}")


def stop_node(node_name: str):
    _run(["docker", "rm", "-f", node_name], check=False)


def up(topo: Topology):
    print(f"Starting {len(topo.nodes)} nodes...")
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
