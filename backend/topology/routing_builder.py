"""
Routing Topology Builder - constructs logical topology graphs from
BGP and OSPF peering information for Phase 2 visualization.
"""
import re
from typing import Optional


class RoutingTopologyBuilder:
    """
    Builds separate BGP and OSPF logical topologies from parsed data.
    Cross-references with physical topology devices where possible.
    """

    def __init__(self):
        self._bgp_peers: list[dict] = []
        self._bgp_config: list[dict] = []
        self._bgp_devices: dict[str, dict] = {}

        self._ospf_neighbors: list[dict] = []
        self._ospf_configs: list[dict] = []
        self._ospf_interfaces: list[dict] = []
        self._ospf_overviews: list[dict] = []
        self._ospf_devices: dict[str, dict] = {}

        self._physical_devices: dict[str, dict] = {}
        self._ip_to_device: dict[str, str] = {}

    def set_physical_devices(self, devices: dict[str, dict]):
        """Import physical topology device data for cross-referencing."""
        self._physical_devices = devices
        for dev_id, dev_data in devices.items():
            mgmt_ip = dev_data.get("mgmt_ip", "")
            if mgmt_ip:
                self._ip_to_device[mgmt_ip] = dev_id

            for intf in dev_data.get("interfaces", []):
                ip = intf.get("ip_address", "")
                if ip and ip != "unassigned":
                    clean_ip = ip.split("/")[0]
                    self._ip_to_device[clean_ip] = dev_id

            config = dev_data.get("config", {})
            if config:
                for ci in config.get("interfaces", []):
                    ip = ci.get("ip_address", "")
                    if ip and ip != "unassigned":
                        clean_ip = ip.split("/")[0]
                        self._ip_to_device[clean_ip] = dev_id
                mgmt = config.get("management", {})
                if mgmt and mgmt.get("ip"):
                    self._ip_to_device[mgmt["ip"]] = dev_id

    def add_bgp_summary(self, hostname: str, summary: dict):
        """Add parsed BGP summary data for a device."""
        hostname_norm = self._norm(hostname)
        if not hostname_norm:
            return

        self._bgp_devices[hostname_norm] = {
            "id": hostname_norm,
            "label": hostname,
            "local_asn": summary.get("local_asn", ""),
            "router_id": summary.get("router_id", ""),
        }

        if summary.get("router_id"):
            self._ip_to_device[summary["router_id"]] = hostname_norm

        for peer in summary.get("peers", []):
            self._bgp_peers.append({
                "local_device": hostname_norm,
                "local_asn": summary.get("local_asn", ""),
                **peer,
            })

    def add_bgp_neighbor_detail(self, hostname: str, peers: list[dict]):
        """Add parsed BGP neighbor detail data."""
        hostname_norm = self._norm(hostname)
        for peer in peers:
            for existing in self._bgp_peers:
                if (existing["local_device"] == hostname_norm and
                        existing["neighbor_ip"] == peer["neighbor_ip"]):
                    existing.update({
                        k: v for k, v in peer.items()
                        if v and k not in ("neighbor_ip",)
                    })
                    break
            else:
                self._bgp_peers.append({
                    "local_device": hostname_norm,
                    "local_asn": "",
                    **peer,
                })

    def add_bgp_config(self, hostname: str, config: dict):
        """Add parsed BGP config data."""
        hostname_norm = self._norm(hostname)
        if not hostname_norm:
            return

        if config.get("local_asn"):
            if hostname_norm not in self._bgp_devices:
                self._bgp_devices[hostname_norm] = {
                    "id": hostname_norm,
                    "label": hostname,
                    "local_asn": "",
                    "router_id": "",
                }
            self._bgp_devices[hostname_norm]["local_asn"] = config["local_asn"]
            if config.get("router_id"):
                self._bgp_devices[hostname_norm]["router_id"] = config["router_id"]

        for nbr in config.get("neighbors", []):
            found = False
            for existing in self._bgp_peers:
                if (existing["local_device"] == hostname_norm and
                        existing["neighbor_ip"] == nbr["neighbor_ip"]):
                    if not existing.get("remote_asn"):
                        existing["remote_asn"] = nbr["remote_asn"]
                    if not existing.get("description") and nbr.get("description"):
                        existing["description"] = nbr["description"]
                    if not existing.get("peering_type") and nbr.get("peering_type"):
                        existing["peering_type"] = nbr["peering_type"]
                    found = True
                    break
            if not found:
                self._bgp_peers.append({
                    "local_device": hostname_norm,
                    "local_asn": config["local_asn"],
                    "neighbor_ip": nbr["neighbor_ip"],
                    "remote_asn": nbr["remote_asn"],
                    "state": "",
                    "prefixes_received": 0,
                    "description": nbr.get("description", ""),
                    "peering_type": nbr.get("peering_type", ""),
                    "uptime": "",
                })

    def add_ospf_overview(self, hostname: str, overview: dict):
        """Add parsed OSPF overview data."""
        hostname_norm = self._norm(hostname)
        if not hostname_norm:
            return
        self._ospf_devices[hostname_norm] = {
            "id": hostname_norm,
            "label": hostname,
            "process_id": overview.get("process_id", ""),
            "router_id": overview.get("router_id", ""),
            "areas": overview.get("areas", []),
        }
        if overview.get("router_id"):
            self._ip_to_device[overview["router_id"]] = hostname_norm
        self._ospf_overviews.append({"hostname": hostname_norm, **overview})

    def add_ospf_neighbors(self, hostname: str, neighbors: list[dict]):
        """Add parsed OSPF neighbor data."""
        hostname_norm = self._norm(hostname)
        for nbr in neighbors:
            self._ospf_neighbors.append({
                "local_device": hostname_norm,
                **nbr,
            })
            if nbr.get("router_id"):
                self._ip_to_device.setdefault(nbr["router_id"], nbr["router_id"])

    def add_ospf_interfaces(self, hostname: str, interfaces: list[dict]):
        """Add parsed OSPF interface data."""
        hostname_norm = self._norm(hostname)
        for intf in interfaces:
            self._ospf_interfaces.append({
                "device": hostname_norm,
                **intf,
            })

    def add_ospf_config(self, hostname: str, config: dict):
        """Add parsed OSPF config data."""
        hostname_norm = self._norm(hostname)
        if not hostname_norm:
            return

        if config.get("process_id"):
            if hostname_norm not in self._ospf_devices:
                self._ospf_devices[hostname_norm] = {
                    "id": hostname_norm,
                    "label": hostname,
                    "process_id": config["process_id"],
                    "router_id": config.get("router_id", ""),
                    "areas": [],
                }
            elif config.get("router_id"):
                self._ospf_devices[hostname_norm]["router_id"] = config["router_id"]

    def build_bgp_topology(self) -> dict:
        """
        Produce the BGP logical topology for visualization.
        Only includes peers where both endpoints are known devices
        (either from BGP summary/config or from physical topology).
        Returns nodes and edges suitable for Cytoscape.js.
        """
        nodes = []
        edges = []
        node_ids = set()
        edge_set = set()
        asn_map = {}

        for dev_id, dev_data in self._bgp_devices.items():
            asn_map[dev_id] = dev_data.get("local_asn", "")

        valid_peers = []
        for peer in self._bgp_peers:
            local_dev = peer["local_device"]
            remote_ip = peer.get("neighbor_ip", "")
            remote_dev = self._resolve_device(remote_ip)

            if not remote_dev:
                continue

            if local_dev == remote_dev:
                continue

            valid_peers.append((peer, local_dev, remote_dev))

        for dev_id, dev_data in self._bgp_devices.items():
            has_valid_peer = any(
                ldev == dev_id or rdev == dev_id
                for _, ldev, rdev in valid_peers
            )
            if not has_valid_peer:
                continue

            node_ids.add(dev_id)
            phys = self._physical_devices.get(dev_id, {})
            nodes.append({
                "data": {
                    "id": dev_id,
                    "label": dev_data.get("label", dev_id),
                    "local_asn": dev_data.get("local_asn", ""),
                    "router_id": dev_data.get("router_id", ""),
                    "role": phys.get("role", "router"),
                    "vendor": phys.get("vendor", ""),
                    "model": phys.get("model", ""),
                }
            })

        for peer, local_dev, remote_dev in valid_peers:
            if local_dev not in node_ids:
                node_ids.add(local_dev)
                phys = self._physical_devices.get(local_dev, {})
                ld = self._bgp_devices.get(local_dev, {})
                nodes.append({
                    "data": {
                        "id": local_dev,
                        "label": ld.get("label", local_dev),
                        "local_asn": ld.get("local_asn", peer.get("local_asn", "")),
                        "router_id": ld.get("router_id", ""),
                        "role": phys.get("role", "router"),
                        "vendor": phys.get("vendor", ""),
                        "model": phys.get("model", ""),
                    }
                })

            if remote_dev not in node_ids:
                node_ids.add(remote_dev)
                phys = self._physical_devices.get(remote_dev, {})
                rd = self._bgp_devices.get(remote_dev, {})
                nodes.append({
                    "data": {
                        "id": remote_dev,
                        "label": rd.get("label", remote_dev),
                        "local_asn": peer.get("remote_asn", rd.get("local_asn", "")),
                        "router_id": rd.get("router_id", peer.get("neighbor_ip", "")),
                        "role": phys.get("role", "router"),
                        "vendor": phys.get("vendor", ""),
                        "model": phys.get("model", ""),
                    }
                })

            key = tuple(sorted([local_dev, remote_dev]))
            if key in edge_set:
                continue
            edge_set.add(key)

            local_asn = peer.get("local_asn", "") or asn_map.get(local_dev, "")
            remote_asn = peer.get("remote_asn", "")
            peering_type = peer.get("peering_type", "")
            if not peering_type:
                peering_type = "iBGP" if local_asn == remote_asn and local_asn else "eBGP"

            state = peer.get("state", "")
            state_norm = "established" if state.lower() in ("established", "") and peer.get("prefixes_received", 0) > 0 else state.lower()

            edge_label = peering_type
            if local_asn and remote_asn and local_asn != remote_asn:
                edge_label = f"AS{local_asn} ↔ AS{remote_asn}"

            edges.append({
                "data": {
                    "id": f"bgp-{local_dev}--{remote_dev}",
                    "source": local_dev,
                    "target": remote_dev,
                    "label": edge_label,
                    "peering_type": peering_type,
                    "state": state_norm,
                    "local_asn": local_asn,
                    "remote_asn": remote_asn,
                    "neighbor_ip": peer.get("neighbor_ip", ""),
                    "prefixes": peer.get("prefixes_received", 0),
                    "description": peer.get("description", ""),
                    "uptime": peer.get("uptime", ""),
                }
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_devices": len(nodes),
                "total_peers": len(edges),
                "asn_count": len(set(
                    n["data"].get("local_asn", "") for n in nodes if n["data"].get("local_asn")
                )),
            },
        }

    def build_ospf_topology(self) -> dict:
        """
        Produce the OSPF logical topology for visualization.
        Returns nodes and edges, with area grouping info.
        """
        nodes = []
        edges = []
        node_ids = set()
        edge_set = set()
        device_areas: dict[str, set] = {}

        for dev_id, dev_data in self._ospf_devices.items():
            node_ids.add(dev_id)
            areas = set()
            for a in dev_data.get("areas", []):
                areas.add(a.get("area_id", "0"))
            device_areas[dev_id] = areas

            phys = self._physical_devices.get(dev_id, {})
            nodes.append({
                "data": {
                    "id": dev_id,
                    "label": dev_data.get("label", dev_id),
                    "router_id": dev_data.get("router_id", ""),
                    "process_id": dev_data.get("process_id", ""),
                    "areas": list(areas),
                    "role": phys.get("role", "router"),
                    "vendor": phys.get("vendor", ""),
                    "model": phys.get("model", ""),
                }
            })

        for intf_data in self._ospf_interfaces:
            dev = intf_data.get("device", "")
            area = intf_data.get("area", "0")
            if dev and dev in device_areas:
                device_areas[dev].add(area)

        for nbr in self._ospf_neighbors:
            local_dev = nbr["local_device"]
            remote_rid = nbr.get("router_id", "")
            remote_dev = self._resolve_device(remote_rid)

            if not remote_dev:
                remote_dev = self._ip_label(remote_rid)

            if remote_dev not in node_ids:
                node_ids.add(remote_dev)
                phys = self._physical_devices.get(remote_dev, {})
                rd = self._ospf_devices.get(remote_dev, {})
                remote_areas = set()
                if nbr.get("area"):
                    remote_areas.add(nbr["area"])

                nodes.append({
                    "data": {
                        "id": remote_dev,
                        "label": rd.get("label", remote_dev),
                        "router_id": remote_rid,
                        "process_id": rd.get("process_id", ""),
                        "areas": list(remote_areas),
                        "role": phys.get("role", "router"),
                        "vendor": phys.get("vendor", ""),
                        "model": phys.get("model", ""),
                    }
                })
                device_areas[remote_dev] = remote_areas

            key = tuple(sorted([local_dev, remote_dev]))
            if key in edge_set:
                continue
            edge_set.add(key)

            state = nbr.get("state", "").upper()
            state_simple = "FULL" if "FULL" in state else state.split("/")[0] if "/" in state else state

            area = nbr.get("area", "")
            if not area and local_dev in device_areas and device_areas[local_dev]:
                area = next(iter(device_areas[local_dev]))

            cost = ""
            for oi in self._ospf_interfaces:
                if oi.get("device") == local_dev and oi.get("interface") == nbr.get("interface"):
                    cost = oi.get("cost", "")
                    if not area:
                        area = oi.get("area", "")
                    break

            edge_label = f"Area {area}" if area else "OSPF"
            if cost:
                edge_label += f" (cost {cost})"

            edges.append({
                "data": {
                    "id": f"ospf-{local_dev}--{remote_dev}",
                    "source": local_dev,
                    "target": remote_dev,
                    "label": edge_label,
                    "area": area,
                    "state": state_simple,
                    "cost": cost,
                    "interface": nbr.get("interface", ""),
                    "neighbor_address": nbr.get("address", ""),
                }
            })

        all_areas = {}
        for dev_id, areas in device_areas.items():
            for a in areas:
                if a not in all_areas:
                    atype = "backbone" if a in ("0", "0.0.0.0") else "normal"
                    for ov in self._ospf_overviews:
                        for oa in ov.get("areas", []):
                            if oa["area_id"] == a:
                                atype = oa.get("type", atype)
                    all_areas[a] = {"area_id": a, "type": atype, "devices": []}
                all_areas[a]["devices"].append(dev_id)

        return {
            "nodes": nodes,
            "edges": edges,
            "areas": list(all_areas.values()),
            "stats": {
                "total_devices": len(nodes),
                "total_adjacencies": len(edges),
                "area_count": len(all_areas),
            },
        }

    def _resolve_device(self, ip_or_rid: str) -> str:
        """Try to resolve an IP or router-ID to a known device hostname."""
        if not ip_or_rid:
            return ""
        if ip_or_rid in self._ip_to_device:
            return self._ip_to_device[ip_or_rid]
        norm = self._norm(ip_or_rid)
        if norm in self._physical_devices or norm in self._bgp_devices or norm in self._ospf_devices:
            return norm
        return ""

    def _ip_label(self, ip: str) -> str:
        """Create a node ID from an IP when device can't be resolved."""
        return ip if ip else "unknown"

    def _norm(self, name: str) -> str:
        """Normalize hostname."""
        if not name:
            return ""
        n = name.strip().lower()
        n = re.split(r"\.", n)[0]
        n = re.sub(r"[^a-z0-9_-]", "", n)
        return n
