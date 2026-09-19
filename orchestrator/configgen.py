"""
Renders one EOS startup-config per node into configs/generated/<node>/,
where docker_manager.py mounts it as /mnt/flash so cEOS boots straight
into the intended config — no manual CLI typing required after `up`.

Template choice is by role: edge nodes (dc/pe) get pe.conf.j2 (BGP +
customer prefixes), core nodes (midpoint/p) get p.conf.j2 (pure IS-IS
+ Segment Routing, no BGP).
"""
import os

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
        if topo.underlay == "bgp-lu":
            template_name = "bgplu_pe.conf.j2" if node.is_edge() else "bgplu_p.conf.j2"
        else:
            template_name = "pe.conf.j2" if node.is_edge() else "p.conf.j2"
        template = env.get_template(template_name)
        rendered = template.render(
            node=node,
            edge_peers=[n for n in topo.edges() if n.name != node.name],
        )

        node_dir = os.path.join(GENERATED_DIR, node.name)
        os.makedirs(node_dir, exist_ok=True)
        out_path = os.path.join(node_dir, "startup-config")
        with open(out_path, "w") as f:
            f.write(rendered)
        print(f"  wrote {out_path}")
