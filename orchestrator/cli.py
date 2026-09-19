"""
One entrypoint for the whole lab lifecycle:

    python -m orchestrator.cli configs  <topology.yaml>
    python -m orchestrator.cli up       <topology.yaml>
    python -m orchestrator.cli wire     <topology.yaml>
    python -m orchestrator.cli down     <topology.yaml>
    python -m orchestrator.cli status   <topology.yaml>

In practice you won't call this directly much — the Makefile wraps
each of these into `make up`, `make wire`, etc. so reproducing the lab
later is a couple of make targets, not a checklist to remember.
"""
import argparse
import sys

from . import configgen, docker_manager, wiring
from .topology import Topology


def main():
    parser = argparse.ArgumentParser(prog="orchestrator")
    parser.add_argument(
        "command", choices=["configs", "up", "wire", "down", "status"]
    )
    parser.add_argument("topology", help="Path to topology YAML file")
    args = parser.parse_args()

    topo = Topology(args.topology)
    n_bundle_members = sum(b.members for b in topo.bundles)
    print(
        f"Topology: {topo.name} ({len(topo.nodes)} nodes, "
        f"{len(topo.single_links)} single links, "
        f"{len(topo.bundles)} port-channels / {n_bundle_members} member links)"
    )

    if args.command == "configs":
        configgen.render_all(topo)
    elif args.command == "up":
        docker_manager.up(topo)
    elif args.command == "wire":
        wiring.wire_all(topo)
    elif args.command == "down":
        docker_manager.down(topo)
    elif args.command == "status":
        docker_manager.status(topo)


if __name__ == "__main__":
    sys.exit(main())
