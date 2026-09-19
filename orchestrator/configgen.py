"""
Renders one config bundle per node into configs/generated/<node>/,
where docker_manager.py mounts it into the container so it boots
straight into the intended config — no manual CLI typing required
after `up`.

Template/output choice is by platform:
  - ceos: renders a single EOS `startup-config` file, mounted at
    /mnt/flash. Template choice within that is by role: edge nodes
    get pe.conf.j2/bgplu_pe.conf.j2 (BGP + customer prefixes), core
    nodes get p.conf.j2/bgplu_p.conf.j2 (pure transit).
  - frr: renders `frr.conf` (role-based: frr_pe.conf.j2/frr_p.conf.j2)
    plus a static `daemons` file, both mounted at /etc/frr.
"""
import os
import shutil

from jinja2 import Environment, FileSystemLoader

from .topology import Topology

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "configs", "templates")
GENERATED_DIR = os.path.join(os.path.dirname(__file__), "..", "configs", "generated")


def render_all(topo: Topology):
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), trim_blocks=True, lstrip_blocks=True)

    def link_ip(node_name, peer_name):
        for link in topo.links_for(node_name):
            if peer_name in (link.a, link.b):
                return link.ip_for(node_name)
        raise ValueError(f"No single link between {node_name} and {peer_name}")

    env.globals["link_ip"] = link_ip

    for node in topo.nodes.values():
        node_dir = os.path.join(GENERATED_DIR, node.name)
        os.makedirs(node_dir, exist_ok=True)

        if topo.platform == "frr":
            template_name = "frr_pe.conf.j2" if node.is_edge() else "frr_p.conf.j2"
            template = env.get_template(template_name)
            rendered = template.render(node=node)
            out_path = os.path.join(node_dir, "frr.conf")
            with open(out_path, "w") as f:
                f.write(rendered)
            print(f"  wrote {out_path}")

            daemons_src = os.path.join(TEMPLATES_DIR, "frr-daemons")
            daemons_dst = os.path.join(node_dir, "daemons")
            shutil.copyfile(daemons_src, daemons_dst)
            print(f"  wrote {daemons_dst}")

        else:  # ceos
            if topo.underlay == "bgp-lu":
                template_name = "bgplu_pe.conf.j2" if node.is_edge() else "bgplu_p.conf.j2"
            else:
                template_name = "pe.conf.j2" if node.is_edge() else "p.conf.j2"
            template = env.get_template(template_name)
            rendered = template.render(
                node=node,
                edge_peers=[n for n in topo.edges() if n.name != node.name],
            )
            out_path = os.path.join(node_dir, "startup-config")
            with open(out_path, "w") as f:
                f.write(rendered)
            print(f"  wrote {out_path}")
