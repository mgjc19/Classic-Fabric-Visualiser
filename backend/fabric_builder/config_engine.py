"""
NX-OS Config Engine - Generates Day-0, Day-1, and Day-2 configurations
using Jinja2 templates. Follows Cisco Validated Designs (CVD) and IEEE 802.1Q/RFC 7348.
"""
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .fabric_model import FabricModel, FabricDevice


TEMPLATE_DIR = Path(__file__).parent / "templates"


class ConfigEngine:
    """Generates NX-OS configuration for each device in the fabric."""

    def __init__(self, model: FabricModel):
        self.model = model
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=select_autoescape([]),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        self._generated: dict[str, str] = {}

    def generate_all(self) -> dict[str, str]:
        """Generate config for every device. Returns {hostname: config_text}."""
        self._generated = {}
        for device in self.model.devices:
            config = self.generate_device_config(device)
            self._generated[device.hostname] = config
        return self._generated

    def generate_device_config(self, device: FabricDevice) -> str:
        """Generate complete NX-OS config for a single device."""
        sections = []
        ctx = self._build_context(device)

        sections.append(self._render("base.j2", ctx))
        sections.append(self._render("interfaces.j2", ctx))

        if self.model.global_config["underlay_protocol"] == "ospf":
            sections.append(self._render("ospf_underlay.j2", ctx))
        
        sections.append(self._render("bgp_overlay.j2", ctx))

        if device.role in ("leaf", "border_leaf", "service_leaf", "border_gateway"):
            sections.append(self._render("vxlan.j2", ctx))

        if device.vpc_domain:
            sections.append(self._render("vpc.j2", ctx))

        if device.role == "border_gateway" and self.model.multisite:
            sections.append(self._render("multisite.j2", ctx))

        sections.append(self._render("day2.j2", ctx))

        return "\n".join(s for s in sections if s.strip())

    def get_device_config(self, device_id: str) -> str:
        """Get generated config for a device (regenerate if needed)."""
        device = self.model.get_device(device_id)
        if not device:
            return ""
        if device.hostname not in self._generated:
            self._generated[device.hostname] = self.generate_device_config(device)
        return self._generated[device.hostname]

    def _build_context(self, device: FabricDevice) -> dict[str, Any]:
        """Build template context for a device."""
        spines = self.model.get_devices_by_role("spine")
        leaves = [d for d in self.model.devices if d.role in ("leaf", "border_leaf", "service_leaf")]
        bgws = self.model.get_devices_by_role("border_gateway")

        fabric_links = [
            l for l in self.model.links
            if l.from_device == device.hostname or l.to_device == device.hostname
        ]

        peer_device = None
        if device.vpc_peer:
            peer_device = self.model.get_device(device.vpc_peer)

        bgp_neighbors = self._get_bgp_neighbors(device, spines, leaves, bgws)

        dci_peers = []
        site_id = 1
        if device.role == "border_gateway" and self.model.multisite:
            site_id = self._get_site_id(device)
            dci_peers = self._get_dci_peers(device, bgws)

        return {
            "device": device,
            "model": self.model,
            "global_config": self.model.global_config,
            "day2": self.model.day2_config,
            "overlay": self.model.overlay,
            "fabric_links": fabric_links,
            "spines": spines,
            "leaves": leaves,
            "bgws": bgws,
            "peer_device": peer_device,
            "bgp_neighbors": bgp_neighbors,
            "dci_peers": dci_peers,
            "site_id": site_id,
            "is_spine": device.role == "spine",
            "is_leaf": device.role in ("leaf", "border_leaf", "service_leaf"),
            "is_bgw": device.role == "border_gateway",
        }

    def _get_bgp_neighbors(self, device: FabricDevice, spines, leaves, bgws) -> list[dict]:
        """Determine BGP neighbors based on role and fabric topology."""
        neighbors = []

        if device.role == "spine":
            for leaf in leaves + bgws:
                if leaf.site == device.site and leaf.loopback0:
                    neighbors.append({
                        "ip": leaf.loopback0.split("/")[0],
                        "remote_asn": leaf.asn,
                        "description": leaf.hostname,
                    })
        elif device.role in ("leaf", "border_leaf", "service_leaf", "border_gateway"):
            for spine in spines:
                if spine.site == device.site and spine.loopback0:
                    neighbors.append({
                        "ip": spine.loopback0.split("/")[0],
                        "remote_asn": spine.asn,
                        "description": spine.hostname,
                    })

        return neighbors

    def _get_site_id(self, device: FabricDevice) -> int:
        """Derive a numeric site ID from device site name."""
        site = device.site or ""
        digits = "".join(c for c in site if c.isdigit())
        if digits:
            return int(digits)
        all_sites = sorted(set(d.site for d in self.model.devices if d.site))
        if site in all_sites:
            return all_sites.index(site) + 1
        return 1

    def _get_dci_peers(self, device: FabricDevice, bgws: list) -> list[dict]:
        """
        Build DCI peer list for a BGW device.
        Each peer has: hostname, remote_asn, loopback_ip (for EVPN peering),
        transport_ip (for IPv4 unicast DCI transport), and same_asn flag.
        """
        peers = []
        for bgw in bgws:
            if bgw.hostname == device.hostname:
                continue
            if bgw.site == device.site:
                continue

            loopback_ip = bgw.loopback0.split("/")[0] if bgw.loopback0 else ""

            transport_ip = ""
            for link in self.model.links:
                if link.cable_type == "DCI":
                    if link.from_device == device.hostname and link.to_device == bgw.hostname:
                        transport_ip = loopback_ip
                        break
                    elif link.to_device == device.hostname and link.from_device == bgw.hostname:
                        transport_ip = loopback_ip
                        break
            if not transport_ip:
                transport_ip = loopback_ip

            peers.append({
                "hostname": bgw.hostname,
                "remote_asn": bgw.asn or device.asn,
                "loopback_ip": loopback_ip,
                "transport_ip": transport_ip,
                "same_asn": bgw.asn == device.asn,
            })
        return peers

    def _render(self, template_name: str, context: dict) -> str:
        try:
            tmpl = self.env.get_template(template_name)
            return tmpl.render(**context)
        except Exception:
            return ""
