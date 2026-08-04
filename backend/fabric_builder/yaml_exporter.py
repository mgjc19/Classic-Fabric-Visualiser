"""
YAML Exporter - Exports fabric model to MDS-style YAML format.
Produces data.tech-vxlan.yaml and data.tech-shared.yaml files.
"""
import yaml
from typing import Any

from .fabric_model import FabricModel


class YamlExporter:
    """Exports fabric model to data.tech-vxlan.yaml and data.tech-shared.yaml."""

    def __init__(self, model: FabricModel):
        self.model = model

    def export(self) -> dict[str, str]:
        """
        Export both YAML files.
        Returns: {"data.tech-vxlan.yaml": content, "data.tech-shared.yaml": content}
        """
        return {
            "data.tech-vxlan.yaml": self._export_vxlan_yaml(),
            "data.tech-shared.yaml": self._export_shared_yaml(),
        }

    def _export_vxlan_yaml(self) -> str:
        data: dict[str, Any] = {
            "docascode": {
                "tech": {
                    "vxlan": self._build_vxlan_structure()
                }
            }
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False, width=120)

    def _export_shared_yaml(self) -> str:
        data: dict[str, Any] = {
            "docascode": {
                "tech": {
                    "shared": self._build_shared_structure()
                }
            }
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False, width=120)

    def _build_vxlan_structure(self) -> dict:
        gc = self.model.global_config
        d2 = self.model.day2_config
        overlay = self.model.overlay

        fabrics = []
        for site in self.model.sites:
            site_devices = self.model.get_devices_by_site(site)
            spines = [d for d in site_devices if d.role == "spine"]
            leaves = [d for d in site_devices if d.role in ("leaf", "border_leaf", "service_leaf")]

            fabric_entry = {
                "name": site,
                "management": {
                    "subnet": self._infer_mgmt_subnet(site_devices),
                    "gateway": "",
                },
                "numbering": {
                    "loopback0_subnet": self._infer_loopback_subnet(site_devices, "loopback0"),
                    "loopback1_subnet": self._infer_loopback_subnet(site_devices, "loopback1"),
                    "spine_asn": gc["spine_asn"],
                    "leaf_asn_start": gc["leaf_asn_start"],
                },
                "spine_count": len(spines),
                "leaf_count": len(leaves),
                "connection_speed": self._get_predominant_speed(site),
            }
            fabrics.append(fabric_entry)

        networks = []
        for vlan in overlay.vlans:
            networks.append({
                "vlan_id": vlan["vlan_id"],
                "name": vlan["name"],
                "vni": vlan["vni"],
                "vrf": vlan["vrf"],
                "subnet": vlan["svi_ip"],
                "anycast_gateway": vlan["anycast_gw"],
            })

        vrfs = []
        for vrf in overlay.vrfs:
            vrfs.append({
                "name": vrf["name"],
                "vni": vrf["vni"],
                "rd": vrf["rd"],
                "rt_import": vrf["rt_import"],
                "rt_export": vrf["rt_export"],
            })

        return {
            "multisite": self.model.multisite,
            "nxos_version": gc["nxos_version"],
            "anycast_gw_mac": gc["anycast_gw_mac"],
            "underlay_protocol": gc["underlay_protocol"],
            "fabrics": fabrics,
            "services": {
                "ntp": d2["ntp_servers"],
                "dns": {
                    "servers": d2["dns_servers"],
                    "domain": d2["dns_domain"],
                },
                "syslog": d2["syslog_servers"],
                "snmp": {
                    "user": d2["snmp_user"],
                    "auth": d2["snmp_auth"],
                    "priv": d2["snmp_priv"],
                },
                "aaa": {
                    "tacacs_servers": d2["tacacs_servers"],
                    "group": d2["aaa_group"],
                },
            },
            "vrfs": vrfs,
            "networks": networks,
        }

    def _build_shared_structure(self) -> dict:
        hardware_groups = {}

        for device in self.model.devices:
            group_key = device.role
            if group_key not in hardware_groups:
                hardware_groups[group_key] = {
                    "role": group_key,
                    "devices": [],
                }
            hardware_groups[group_key]["devices"].append({
                "hostname": device.hostname,
                "model": device.model,
                "serial": device.serial,
                "mgmt_ip": device.mgmt_ip,
                "site": device.site,
            })

        cabling_groups = []
        for link in self.model.links:
            cabling_groups.append({
                "from_device": link.from_device,
                "from_port": link.from_port,
                "to_device": link.to_device,
                "to_port": link.to_port,
                "transceiver": link.sfp,
                "cable_type": link.cable_type,
                "connector_type": self._infer_connector(link.sfp, link.cable_type),
                "speed": link.speed,
            })

        return {
            "hardware_groups": list(hardware_groups.values()),
            "cabling_groups": cabling_groups,
        }

    def _infer_mgmt_subnet(self, devices: list) -> str:
        for d in devices:
            if d.mgmt_ip:
                parts = d.mgmt_ip.split("/")
                if len(parts) == 2:
                    octets = parts[0].split(".")
                    if len(octets) == 4:
                        return f"{octets[0]}.{octets[1]}.{octets[2]}.0/{parts[1]}"
        return ""

    def _infer_loopback_subnet(self, devices: list, attr: str) -> str:
        for d in devices:
            ip = getattr(d, attr, "")
            if ip:
                parts = ip.split("/")
                if len(parts) == 2:
                    octets = parts[0].split(".")
                    if len(octets) == 4:
                        return f"{octets[0]}.{octets[1]}.{octets[2]}.0/24"
        return ""

    def _get_predominant_speed(self, site: str) -> str:
        speeds: dict[str, int] = {}
        site_devices = {d.hostname for d in self.model.get_devices_by_site(site)}
        for link in self.model.links:
            if link.from_device in site_devices or link.to_device in site_devices:
                speed = link.speed or "unknown"
                speeds[speed] = speeds.get(speed, 0) + 1
        if speeds:
            return max(speeds, key=speeds.get)
        return "100G"

    def _infer_connector(self, sfp: str, cable_type: str) -> str:
        combined = f"{sfp} {cable_type}".lower()
        if "dac" in combined or "cu" in combined or "copper" in combined:
            return "DAC"
        if "smf" in combined or "lr" in combined or "er" in combined:
            return "LC-LC"
        if "mmf" in combined or "sr" in combined:
            return "MPO"
        return "LC-LC"
