"""
Topology Builder - constructs a network graph from parsed device data.
Produces nodes (devices) and edges (links) suitable for visualization.
"""
import re
from typing import Optional


class TopologyBuilder:
    """
    Aggregates parsed data from multiple devices and constructs
    a unified physical topology graph.
    """

    def __init__(self):
        self.devices: dict[str, dict] = {}
        self.links: list[dict] = []
        self._link_set: set[tuple] = set()
        self._interface_speeds: dict[str, dict[str, str]] = {}
        self._interface_status: dict[str, dict[str, str]] = {}  # device -> {interface -> "up"/"down"}

    def add_device(self, hostname: str, device_info: Optional[dict] = None):
        """Register a device node."""
        if not hostname or not hostname.strip():
            return

        if not self._is_valid_device_name(hostname):
            return

        hostname_norm = self._normalize_hostname(hostname)
        if not hostname_norm:
            return

        if hostname_norm not in self.devices:
            self.devices[hostname_norm] = {
                "id": hostname_norm,
                "label": hostname,
                "model": "",
                "serial": "",
                "platform": "",
                "software_version": "",
                "vendor": "",
                "uptime": "",
                "role": "switch",
                "mgmt_ip": "",
                "interfaces": [],
                "config": {},
            }

        if device_info:
            dev = self.devices[hostname_norm]
            if device_info.get("model"):
                dev["model"] = device_info["model"]
            if device_info.get("serial"):
                dev["serial"] = device_info["serial"]
            if device_info.get("platform"):
                dev["platform"] = device_info["platform"]
            if device_info.get("software_version"):
                dev["software_version"] = device_info["software_version"]
            if device_info.get("vendor"):
                dev["vendor"] = device_info["vendor"]
            if device_info.get("uptime"):
                dev["uptime"] = device_info["uptime"]
            if device_info.get("device_role"):
                dev["role"] = device_info["device_role"]
            if device_info.get("mgmt_ip"):
                dev["mgmt_ip"] = device_info["mgmt_ip"]
            if device_info.get("config"):
                dev["config"] = device_info["config"]

    def add_neighbors(self, neighbors: list[dict]):
        """Add neighbor relationships (from CDP/LLDP/inferred)."""
        for neighbor in neighbors:
            local_device = neighbor.get("local_device", "")
            remote_device = neighbor.get("remote_device", "")

            if not local_device or not remote_device:
                continue

            if not self._is_valid_device_name(remote_device):
                continue

            local_intf = neighbor.get("local_interface", "")
            remote_intf = neighbor.get("remote_interface", "")

            if not local_intf and not remote_intf:
                continue

            local_norm = self._normalize_hostname(local_device)
            remote_norm = self._normalize_hostname(remote_device)

            if not local_norm or not remote_norm:
                continue

            if local_norm == remote_norm:
                continue

            self.add_device(local_device)
            self.add_device(remote_device)

            if neighbor.get("mgmt_ip"):
                self.devices[remote_norm]["mgmt_ip"] = neighbor["mgmt_ip"]
            if neighbor.get("platform"):
                self.devices[remote_norm]["platform"] = neighbor["platform"]
            if neighbor.get("capabilities"):
                role = self._role_from_capabilities(neighbor["capabilities"])
                if role != "switch":
                    self.devices[remote_norm]["role"] = role

            self._add_link(
                local_device=local_norm,
                local_interface=self._normalize_interface(neighbor.get("local_interface", "")),
                remote_device=remote_norm,
                remote_interface=self._normalize_interface(neighbor.get("remote_interface", "")),
                protocol=neighbor.get("protocol", ""),
                confidence=neighbor.get("confidence", "high"),
                speed=self._infer_link_speed(
                    local_norm,
                    self._normalize_interface(neighbor.get("local_interface", "")),
                    self._normalize_interface(neighbor.get("remote_interface", "")),
                ),
            )

    def add_interfaces(self, hostname: str, interfaces: list[dict]):
        """Add interface inventory to a device node."""
        hostname_norm = self._normalize_hostname(hostname)
        if hostname_norm in self.devices:
            self.devices[hostname_norm]["interfaces"] = interfaces
        for intf in interfaces:
            intf_name = self._normalize_interface(intf.get("interface", ""))
            speed = intf.get("speed", "")
            status = intf.get("status", "")
            protocol = intf.get("protocol", "")

            if intf_name:
                if hostname_norm not in self._interface_speeds:
                    self._interface_speeds[hostname_norm] = {}
                if speed:
                    self._interface_speeds[hostname_norm][intf_name] = speed

                if hostname_norm not in self._interface_status:
                    self._interface_status[hostname_norm] = {}

                if status == "up" and protocol in ("down", ""):
                    self._interface_status[hostname_norm][intf_name] = "up/down"
                elif status == "up":
                    self._interface_status[hostname_norm][intf_name] = "up"
                elif status in ("down", "administratively"):
                    self._interface_status[hostname_norm][intf_name] = "down"
                elif status in ("connected",):
                    self._interface_status[hostname_norm][intf_name] = "up"
                elif status in ("notconnect", "disabled", "err-disabled", "sfpabsent", "xcvrabsen"):
                    self._interface_status[hostname_norm][intf_name] = "down"
                elif status:
                    self._interface_status[hostname_norm][intf_name] = status

    def build(self) -> dict:
        """
        Produce the final topology structure for visualization.
        Returns nodes and edges suitable for Cytoscape.js.
        Groups port-channel member links into aggregated edges.
        Only includes nodes that are networking infrastructure
        (switch, router, firewall, loadbalancer, WAN, border, wlc).
        """
        INFRA_ROLES = {"switch", "router", "firewall", "loadbalancer", "border", "wlc", "wan", "spine", "leaf"}

        infra_devices = set()
        for dev_id, dev_data in self.devices.items():
            if not dev_id:
                continue
            role = dev_data.get("role", "switch").lower()
            if role in INFRA_ROLES:
                infra_devices.add(dev_id)

        connected_devices = set()
        for link in self.links:
            src = link.get("local_device", "")
            dst = link.get("remote_device", "")
            if src and dst:
                if src in infra_devices or dst in infra_devices:
                    connected_devices.add(src)
                    connected_devices.add(dst)

        valid_devices = infra_devices | connected_devices

        nodes = []
        device_details = {}

        for dev_id, dev_data in self.devices.items():
            if not dev_id:
                continue
            if dev_id not in valid_devices:
                continue
            nodes.append({
                "data": {
                    "id": dev_id,
                    "label": dev_data.get("label", dev_id),
                    "vendor": dev_data.get("vendor", ""),
                    "model": dev_data.get("model", ""),
                    "serial": dev_data.get("serial", ""),
                    "platform": dev_data.get("platform", ""),
                    "software_version": dev_data.get("software_version", ""),
                    "uptime": dev_data.get("uptime", ""),
                    "role": dev_data.get("role", "switch"),
                    "mgmt_ip": dev_data.get("mgmt_ip", ""),
                    "interface_count": len(dev_data.get("interfaces", [])),
                }
            })

            device_details[dev_id] = {
                "interfaces": dev_data.get("interfaces", []),
                "config": dev_data.get("config", {}),
            }

        pc_member_map = self._build_member_to_po_map()

        po_groups: dict[str, list[dict]] = {}
        regular_links = []

        node_ids = {n["data"]["id"] for n in nodes}

        for link in self.links:
            if not link["local_device"] or not link["remote_device"]:
                continue
            if link["local_device"] not in node_ids or link["remote_device"] not in node_ids:
                continue

            local_key = f"{link['local_device']}:{link['local_interface']}"
            po_id = pc_member_map.get(local_key)

            if po_id:
                group_key = f"{link['local_device']}--{link['remote_device']}--{po_id}"
                if group_key not in po_groups:
                    po_groups[group_key] = []
                po_groups[group_key].append(link)
            else:
                regular_links.append(link)

        edges = []

        for group_key, members in po_groups.items():
            first = members[0]
            member_intfs = [m["local_interface"] + " ↔ " + m["remote_interface"] for m in members if m["local_interface"]]
            parts = group_key.split("--")
            po_name = parts[2] if len(parts) > 2 else "Po"

            edge_label = f"{po_name} ({len(members)} members)"
            edge_id = group_key

            link_status = self._get_link_status(
                first["local_device"], first["local_interface"],
                first["remote_device"], first["remote_interface"]
            )

            edges.append({
                "data": {
                    "id": edge_id,
                    "source": first["local_device"],
                    "target": first["remote_device"],
                    "local_interface": po_name,
                    "remote_interface": po_name,
                    "label": edge_label,
                    "speed": "Po",
                    "speed_label": f"Po ({len(members)}x)",
                    "protocol": first["protocol"],
                    "confidence": "high",
                    "link_status": link_status,
                    "is_port_channel": True,
                    "member_count": len(members),
                    "members": member_intfs,
                }
            })

        for idx, link in enumerate(regular_links):
            edge_label = ""
            if link["local_interface"] and link["remote_interface"]:
                edge_label = f"{link['local_interface']} \u2194 {link['remote_interface']}"
            elif link["local_interface"]:
                edge_label = link["local_interface"]

            speed = link.get("speed", "")
            edge_id = f"{link['local_device']}--{link['remote_device']}--{link['local_interface'] or idx}"

            link_status = self._get_link_status(
                link["local_device"], link["local_interface"],
                link["remote_device"], link["remote_interface"]
            )

            edges.append({
                "data": {
                    "id": edge_id,
                    "source": link["local_device"],
                    "target": link["remote_device"],
                    "local_interface": link["local_interface"],
                    "remote_interface": link["remote_interface"],
                    "label": edge_label,
                    "speed": speed,
                    "speed_label": speed,
                    "protocol": link["protocol"],
                    "confidence": link["confidence"],
                    "link_status": link_status,
                }
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "device_details": device_details,
            "port_channels": self._build_port_channel_map(),
            "stats": {
                "total_devices": len(nodes),
                "total_links": len(edges),
                "protocols_used": list(set(l["protocol"] for l in self.links if l["protocol"])),
            },
        }

    def _build_port_channel_map(self) -> dict:
        """Build a map of port-channel details keyed by device:interface."""
        pc_map = {}
        for dev_id, dev_data in self.devices.items():
            config = dev_data.get("config", {})
            if not config:
                continue
            pcs = config.get("port_channels", [])
            for pc in pcs:
                key = dev_id + ":Po" + str(pc.get("id", ""))
                pc_map[key] = {
                    "members": pc.get("members", []),
                    "protocol": pc.get("protocol", ""),
                }
        return pc_map

    def _build_member_to_po_map(self) -> dict:
        """
        Build reverse map: device:member_interface -> Po name.
        Used to group member links into port-channel aggregates.
        """
        member_map = {}
        for dev_id, dev_data in self.devices.items():
            config = dev_data.get("config", {})
            if not config:
                continue
            pcs = config.get("port_channels", [])
            for pc in pcs:
                po_name = "Po" + str(pc.get("id", ""))
                for member in pc.get("members", []):
                    member_norm = self._normalize_interface(member)
                    key = f"{dev_id}:{member_norm}"
                    member_map[key] = po_name

            for intf in config.get("interfaces", []):
                if intf.get("channel_group"):
                    intf_name = self._normalize_interface(intf.get("name", ""))
                    if intf_name:
                        po_name = "Po" + str(intf["channel_group"])
                        key = f"{dev_id}:{intf_name}"
                        member_map[key] = po_name

        return member_map

    def _get_link_status(self, local_dev: str, local_intf: str,
                         remote_dev: str, remote_intf: str) -> str:
        """
        Determine overall link status from interface operational state.
        Returns: "up", "down", "up/down", or "" (unknown).
        """
        local_st = ""
        remote_st = ""

        if local_dev in self._interface_status and local_intf:
            local_st = self._interface_status[local_dev].get(local_intf, "")
        if remote_dev in self._interface_status and remote_intf:
            remote_st = self._interface_status[remote_dev].get(remote_intf, "")

        if not local_st and not remote_st:
            return ""

        if local_st == "down" or remote_st == "down":
            return "down"
        if local_st == "up/down" or remote_st == "up/down":
            return "up/down"
        if local_st == "up" or remote_st == "up":
            return "up"

        return local_st or remote_st

    def _add_link(self, local_device: str, local_interface: str,
                  remote_device: str, remote_interface: str,
                  protocol: str = "", confidence: str = "high",
                  speed: str = ""):
        """Add a link, avoiding duplicates (A->B == B->A)."""
        if not local_device or not remote_device:
            return

        key_fwd = (local_device, local_interface, remote_device, remote_interface)
        key_rev = (remote_device, remote_interface, local_device, local_interface)

        if key_fwd in self._link_set or key_rev in self._link_set:
            return

        self._link_set.add(key_fwd)
        self.links.append({
            "local_device": local_device,
            "local_interface": local_interface,
            "remote_device": remote_device,
            "remote_interface": remote_interface,
            "protocol": protocol,
            "confidence": confidence,
            "speed": speed,
        })

    def _normalize_hostname(self, hostname: str) -> str:
        """Normalize hostname for consistent matching."""
        name = hostname.strip().lower()
        name = re.split(r"\.", name)[0]
        name = re.sub(r"[^a-z0-9_-]", "", name)
        return name

    def _normalize_interface(self, intf: str) -> str:
        """Normalize interface names for consistent display across vendors."""
        if not intf:
            return ""

        replacements = [
            # Cisco IOS/IOS-XE
            (r"^GigabitEthernet", "Gi"),
            (r"^TenGigabitEthernet", "Te"),
            (r"^TwentyFiveGigE", "Twe"),
            (r"^FortyGigabitEthernet", "Fo"),
            (r"^HundredGigE", "Hu"),
            (r"^FastEthernet", "Fa"),
            (r"^Port-channel", "Po"),
            (r"^port-channel", "Po"),
            (r"^Loopback", "Lo"),
            (r"^Vlan", "Vlan"),
            (r"^mgmt", "mgmt"),
            # Cisco NX-OS
            (r"^Ethernet", "Eth"),
            # Arista
            (r"^Management", "Mgmt"),
            # Juniper
            (r"^xe-", "xe-"),
            (r"^ge-", "ge-"),
            (r"^et-", "et-"),
            (r"^ae", "ae"),
            # Palo Alto
            (r"^ethernet", "eth"),
            # F5
            (r"^tmm", "tmm"),
        ]

        for pattern, replacement in replacements:
            intf = re.sub(pattern, replacement, intf, flags=re.IGNORECASE)

        return intf.strip()

    def _infer_link_speed(self, local_device: str, local_intf: str, remote_intf: str) -> str:
        """Infer link speed from interface name prefix or stored speed data."""
        if local_device in self._interface_speeds:
            stored = self._interface_speeds[local_device].get(local_intf, "")
            if stored:
                return stored

        intf = local_intf or remote_intf
        if not intf:
            return ""

        intf_lower = intf.lower()

        if intf_lower.startswith("hu") or "hundredgig" in intf_lower:
            return "100G"
        if intf_lower.startswith(("fo", "et-")) or "fortygig" in intf_lower:
            return "40G"
        if intf_lower.startswith("twe") or "twentyfive" in intf_lower:
            return "25G"
        if intf_lower.startswith(("te", "xe-")) or "tengig" in intf_lower:
            return "10G"
        if intf_lower.startswith(("gi", "ge-")) or "gigabit" in intf_lower:
            return "1G"
        if intf_lower.startswith("fa") or "fasteth" in intf_lower:
            return "100M"
        if intf_lower.startswith("eth"):
            return "1G"
        if intf_lower.startswith(("po", "ae")):
            return "Po"

        return ""

    def _role_from_capabilities(self, capabilities: str) -> str:
        """Infer device role from CDP/LLDP capabilities string."""
        caps_lower = capabilities.lower()

        if any(k in caps_lower for k in ["firewall", "security"]):
            return "firewall"
        if "router" in caps_lower and "switch" not in caps_lower:
            return "router"
        if "router" in caps_lower and "switch" in caps_lower:
            return "router"
        if "switch" in caps_lower and "host" not in caps_lower:
            return "switch"
        if "phone" in caps_lower or "host" in caps_lower:
            return "endpoint"
        if "bridge" in caps_lower:
            return "switch"
        if any(k in caps_lower for k in ["wlan", "ap", "access point"]):
            return "wlc"
        if "station" in caps_lower:
            return "endpoint"

        return "switch"

    def _is_valid_device_name(self, name: str) -> bool:
        """
        Validate that a string looks like an actual device hostname,
        not a garbage value from a mis-parsed line.
        """
        if not name or len(name) < 2:
            return False
        if len(name) > 80:
            return False

        clean = name.strip().rstrip(":.,;")
        if len(clean) < 2:
            return False

        garbage_keywords = [
            "cisco", "version", "copyright", "compiled", "ios",
            "advertisement", "protocol", "hello", "oui", "payload",
            "address", "platform", "capabilities", "holdtime", "duplex",
            "value", "device", "sysname", "port", "interface",
            "ipv4", "ipv6", "management", "native", "vtp",
            "software", "system", "description", "enabled",
            "total", "entries", "output", "power", "chassis",
        ]
        clean_lower = clean.lower()
        if clean_lower in garbage_keywords:
            return False

        if re.match(r"^\d+\.\d+\.\d+\.\d+$", clean):
            return False
        if re.match(r"^[0-9a-f]{2}([:.][0-9a-f]{2}){2,}$", clean, re.IGNORECASE):
            return False
        if re.match(r"^[0-9]+$", clean):
            return False
        if " " in clean:
            return False

        return True
