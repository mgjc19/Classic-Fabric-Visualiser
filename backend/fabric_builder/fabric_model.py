"""
Fabric Data Model - Central in-memory representation of a VXLAN spine-leaf fabric.
Supports single-site and multi-site topologies.
"""
import uuid
from typing import Any, Optional


class FabricDevice:
    """Represents a single fabric device."""

    def __init__(self, data: dict):
        self.id: str = data.get("id") or str(uuid.uuid4())
        self.hostname: str = data.get("hostname", "")
        self.role: str = data.get("role", "leaf")
        self.model: str = data.get("model", "")
        self.serial: str = data.get("serial", "")
        self.mgmt_ip: str = data.get("mgmt_ip", "")
        self.loopback0: str = data.get("loopback0", "")
        self.loopback1: str = data.get("loopback1", "")
        self.loopback2: str = data.get("loopback2", "")
        self.site: str = data.get("site", "site-1")
        self.vpc_domain: str = data.get("vpc_domain", "")
        self.vpc_peer: str = data.get("vpc_peer", "")
        self.asn: str = data.get("asn", "")
        self.interfaces: list[dict] = data.get("interfaces", [])
        self.config: dict = data.get("config", {})

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "hostname": self.hostname,
            "role": self.role,
            "model": self.model,
            "serial": self.serial,
            "mgmt_ip": self.mgmt_ip,
            "loopback0": self.loopback0,
            "loopback1": self.loopback1,
            "loopback2": self.loopback2,
            "site": self.site,
            "vpc_domain": self.vpc_domain,
            "vpc_peer": self.vpc_peer,
            "asn": self.asn,
            "interfaces": self.interfaces,
            "config": self.config,
        }


class FabricLink:
    """Represents a fabric interconnection."""

    def __init__(self, data: dict):
        self.id: str = data.get("id") or str(uuid.uuid4())
        self.from_device: str = data.get("from_device", "")
        self.from_port: str = data.get("from_port", "")
        self.to_device: str = data.get("to_device", "")
        self.to_port: str = data.get("to_port", "")
        self.sfp: str = data.get("sfp", "")
        self.cable_type: str = data.get("cable_type", "")
        self.speed: str = data.get("speed", "")
        self.protocol: str = data.get("protocol", "")
        self.bgp_address_family: str = data.get("bgp_address_family", "")
        self.from_asn: str = data.get("from_asn", "")
        self.to_asn: str = data.get("to_asn", "")

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "from_device": self.from_device,
            "from_port": self.from_port,
            "to_device": self.to_device,
            "to_port": self.to_port,
            "sfp": self.sfp,
            "cable_type": self.cable_type,
            "speed": self.speed,
        }
        if self.protocol:
            d["protocol"] = self.protocol
            d["bgp_address_family"] = self.bgp_address_family
            d["from_asn"] = self.from_asn
            d["to_asn"] = self.to_asn
        return d


class FabricOverlay:
    """Overlay network configuration (VRFs, VLANs, VNIs)."""

    def __init__(self):
        self.vrfs: list[dict] = []
        self.vlans: list[dict] = []
        self.vnis: list[dict] = []

    def add_vrf(self, name: str, vni: int, rd: str = "", rt_import: str = "", rt_export: str = ""):
        self.vrfs.append({
            "name": name,
            "vni": vni,
            "rd": rd,
            "rt_import": rt_import,
            "rt_export": rt_export,
        })

    def add_vlan(self, vlan_id: int, name: str = "", vni: int = 0, vrf: str = "",
                 svi_ip: str = "", anycast_gw: str = ""):
        self.vlans.append({
            "vlan_id": vlan_id,
            "name": name,
            "vni": vni,
            "vrf": vrf,
            "svi_ip": svi_ip,
            "anycast_gw": anycast_gw,
        })

    def add_vni(self, vni: int, vlan_id: int = 0, vrf: str = "", mcast_group: str = "",
                is_l3vni: bool = False):
        self.vnis.append({
            "vni": vni,
            "vlan_id": vlan_id,
            "vrf": vrf,
            "mcast_group": mcast_group,
            "is_l3vni": is_l3vni,
        })

    def to_dict(self) -> dict:
        return {
            "vrfs": self.vrfs,
            "vlans": self.vlans,
            "vnis": self.vnis,
        }


class FabricModel:
    """
    Central fabric model. Holds all devices, links, overlay config, and multi-site state.
    Every field is editable via API.
    """

    def __init__(self):
        self.devices: list[FabricDevice] = []
        self.links: list[FabricLink] = []
        self.overlay: FabricOverlay = FabricOverlay()
        self.sites: list[str] = ["site-1"]
        self.multisite: bool = False
        self.global_config: dict = {
            "nxos_version": "10.3(4a)",
            "underlay_protocol": "ospf",
            "ospf_area": "0.0.0.0",
            "bgp_asn_scheme": "unique_per_leaf",
            "spine_asn": 65000,
            "leaf_asn_start": 65001,
            "anycast_gw_mac": "0000.2222.3333",
            "nve_source": "loopback1",
            "vpc_keepalive_vrf": "management",
            "multisite_anycast_gw": "",
        }
        self.day2_config: dict = {
            "ntp_servers": ["10.1.100.1", "10.1.100.2"],
            "dns_servers": ["10.1.100.10"],
            "dns_domain": "dc.local",
            "syslog_servers": ["10.1.100.20"],
            "snmp_community": "",
            "snmp_user": "snmpadmin",
            "snmp_auth": "SHA",
            "snmp_priv": "AES-128",
            "tacacs_servers": ["10.1.100.30"],
            "tacacs_key": "",
            "aaa_group": "TACACS-SERVERS",
        }

    def load_from_bom(self, bom_data: dict):
        """Load devices and links from parsed BOM data."""
        self.devices = [FabricDevice(d) for d in bom_data.get("devices", [])]
        self.links = [FabricLink(l) for l in bom_data.get("links", [])]

        meta = bom_data.get("metadata", {})
        self.sites = meta.get("sites", ["site-1"])
        self.multisite = meta.get("multisite", False)

        self._assign_asns()
        self._assign_loopbacks()
        self._build_interfaces_from_links()

    def _assign_asns(self):
        """Auto-assign BGP ASNs based on role and configured scheme."""
        spine_asn = self.global_config["spine_asn"]
        leaf_asn_start = self.global_config["leaf_asn_start"]
        leaf_idx = 0

        for device in self.devices:
            if device.asn:
                continue
            if device.role == "spine":
                device.asn = str(spine_asn)
            elif device.role in ("leaf", "border_leaf", "service_leaf", "border_gateway"):
                device.asn = str(leaf_asn_start + leaf_idx)
                leaf_idx += 1

    def _assign_loopbacks(self):
        """Auto-assign loopback IPs if not provided in BOM."""
        spine_idx = 1
        leaf_idx = 1

        for device in self.devices:
            if not device.loopback0:
                if device.role == "spine":
                    device.loopback0 = f"10.{self._site_octet(device.site)}.255.{spine_idx}/32"
                    spine_idx += 1
                else:
                    device.loopback0 = f"10.{self._site_octet(device.site)}.255.{10 + leaf_idx}/32"
                    leaf_idx += 1

            if not device.loopback1 and device.role in ("leaf", "border_leaf", "service_leaf", "border_gateway"):
                base = device.loopback0.split("/")[0].rsplit(".", 1)
                if len(base) == 2:
                    device.loopback1 = f"10.{self._site_octet(device.site)}.254.{base[1]}/32"

            if not device.loopback2 and device.role == "border_gateway":
                base = device.loopback0.split("/")[0].rsplit(".", 1)
                if len(base) == 2:
                    device.loopback2 = f"192.168.{self._site_octet(device.site)}.{base[1]}/32"

    def _site_octet(self, site: str) -> int:
        """Map site name to second octet."""
        try:
            idx = self.sites.index(site)
        except ValueError:
            idx = 0
        return idx + 1

    def _build_interfaces_from_links(self):
        """Populate device interfaces list from link data."""
        device_map = {d.hostname: d for d in self.devices}
        for link in self.links:
            if link.from_device in device_map:
                dev = device_map[link.from_device]
                dev.interfaces.append({
                    "name": link.from_port,
                    "description": f"To {link.to_device} {link.to_port}",
                    "speed": link.speed,
                    "sfp": link.sfp,
                    "type": "fabric",
                })
            if link.to_device in device_map:
                dev = device_map[link.to_device]
                dev.interfaces.append({
                    "name": link.to_port,
                    "description": f"To {link.from_device} {link.from_port}",
                    "speed": link.speed,
                    "sfp": link.sfp,
                    "type": "fabric",
                })

    def get_device(self, device_id: str) -> Optional[FabricDevice]:
        for d in self.devices:
            if d.id == device_id or d.hostname == device_id:
                return d
        return None

    def get_link(self, link_id: str) -> Optional[FabricLink]:
        for l in self.links:
            if l.id == link_id:
                return l
        return None

    def update_device(self, device_id: str, updates: dict) -> Optional[dict]:
        device = self.get_device(device_id)
        if not device:
            return None
        for key, value in updates.items():
            if hasattr(device, key) and key != "id":
                setattr(device, key, value)
        return device.to_dict()

    def update_link(self, link_id: str, updates: dict) -> Optional[dict]:
        link = self.get_link(link_id)
        if not link:
            return None
        for key, value in updates.items():
            if hasattr(link, key) and key != "id":
                setattr(link, key, value)
        return link.to_dict()

    def update_overlay(self, overlay_data: dict):
        """Bulk update overlay config."""
        if "vrfs" in overlay_data:
            self.overlay.vrfs = overlay_data["vrfs"]
        if "vlans" in overlay_data:
            self.overlay.vlans = overlay_data["vlans"]
        if "vnis" in overlay_data:
            self.overlay.vnis = overlay_data["vnis"]

    def add_default_overlay(self):
        """Add a default overlay with sample VRFs and VLANs."""
        self.overlay.add_vrf("TENANT-1", vni=50001, rd="auto", rt_import="auto", rt_export="auto")
        self.overlay.add_vlan(10, name="Web-Servers", vni=10010, vrf="TENANT-1",
                             svi_ip="10.10.10.1/24", anycast_gw="10.10.10.1/24")
        self.overlay.add_vlan(20, name="App-Servers", vni=10020, vrf="TENANT-1",
                             svi_ip="10.10.20.1/24", anycast_gw="10.10.20.1/24")
        self.overlay.add_vlan(30, name="DB-Servers", vni=10030, vrf="TENANT-1",
                             svi_ip="10.10.30.1/24", anycast_gw="10.10.30.1/24")
        self.overlay.add_vni(10010, vlan_id=10, vrf="TENANT-1", mcast_group="239.1.1.10")
        self.overlay.add_vni(10020, vlan_id=20, vrf="TENANT-1", mcast_group="239.1.1.20")
        self.overlay.add_vni(10030, vlan_id=30, vrf="TENANT-1", mcast_group="239.1.1.30")
        self.overlay.add_vni(50001, vlan_id=0, vrf="TENANT-1", is_l3vni=True)

    def get_devices_by_role(self, role: str) -> list[FabricDevice]:
        return [d for d in self.devices if d.role == role]

    def get_devices_by_site(self, site: str) -> list[FabricDevice]:
        return [d for d in self.devices if d.site == site]

    def to_dict(self) -> dict:
        return {
            "devices": [d.to_dict() for d in self.devices],
            "links": [l.to_dict() for l in self.links],
            "overlay": self.overlay.to_dict(),
            "sites": self.sites,
            "multisite": self.multisite,
            "global_config": self.global_config,
            "day2_config": self.day2_config,
        }
