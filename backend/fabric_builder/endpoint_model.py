"""
Endpoint Model - Represents network-attached endpoints (servers, LBs, FWs, etc.)
and their connections to the fabric.
"""
import uuid
from typing import Optional


ENDPOINT_TYPES = {
    "server": {"label": "Server", "shape": "ellipse", "color": "#db61a2"},
    "vm_host": {"label": "VM Host", "shape": "ellipse", "color": "#c084fc"},
    "load_balancer": {"label": "Load Balancer", "shape": "diamond", "color": "#22d3ee"},
    "firewall": {"label": "Firewall", "shape": "hexagon", "color": "#f87171"},
    "wan_router": {"label": "WAN Router", "shape": "round-rectangle", "color": "#fb923c"},
    "edge_router": {"label": "Edge Router", "shape": "round-rectangle", "color": "#a3e635"},
    "storage": {"label": "Storage", "shape": "barrel", "color": "#d29922"},
    "backup": {"label": "Backup", "shape": "barrel", "color": "#78716c"},
    "cloud_gw": {"label": "Cloud Gateway", "shape": "round-pentagon", "color": "#60a5fa"},
    "dci_gw": {"label": "DCI Gateway", "shape": "round-pentagon", "color": "#818cf8"},
    "sdwan_edge": {"label": "SD-WAN Edge", "shape": "round-triangle", "color": "#34d399"},
}


class FabricEndpoint:
    """Represents a network endpoint connected to the fabric."""

    def __init__(self, data: dict):
        self.id: str = data.get("id") or str(uuid.uuid4())
        self.type: str = data.get("type", "server")
        self.name: str = data.get("name", "")
        self.ip: str = data.get("ip", "")
        self.vlan: str = data.get("vlan", "")
        self.vrf: str = data.get("vrf", "")
        self.mode: str = data.get("mode", "single")  # single or vpc
        self.connected_to: list[dict] = data.get("connected_to", [])
        self.site: str = data.get("site", "")
        self.port_channel_id: str = data.get("port_channel_id", "")
        self.lacp_mode: str = data.get("lacp_mode", "active")
        self.mac_address: str = data.get("mac_address", "")
        self.description: str = data.get("description", "")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "ip": self.ip,
            "vlan": self.vlan,
            "vrf": self.vrf,
            "mode": self.mode,
            "connected_to": self.connected_to,
            "site": self.site,
            "port_channel_id": self.port_channel_id,
            "lacp_mode": self.lacp_mode,
            "mac_address": self.mac_address,
            "description": self.description,
        }


class EndpointStore:
    """In-memory store for fabric endpoints."""

    def __init__(self):
        self.endpoints: list[FabricEndpoint] = []

    def add(self, data: dict) -> FabricEndpoint:
        ep = FabricEndpoint(data)
        self.endpoints.append(ep)
        return ep

    def get(self, ep_id: str) -> Optional[FabricEndpoint]:
        for ep in self.endpoints:
            if ep.id == ep_id:
                return ep
        return None

    def update(self, ep_id: str, updates: dict) -> Optional[FabricEndpoint]:
        ep = self.get(ep_id)
        if not ep:
            return None
        for key, value in updates.items():
            if hasattr(ep, key) and key != "id":
                setattr(ep, key, value)
        return ep

    def remove(self, ep_id: str) -> bool:
        before = len(self.endpoints)
        self.endpoints = [e for e in self.endpoints if e.id != ep_id]
        return len(self.endpoints) < before

    def list_all(self) -> list[dict]:
        return [ep.to_dict() for ep in self.endpoints]

    def get_by_site(self, site: str) -> list[FabricEndpoint]:
        return [ep for ep in self.endpoints if ep.site == site]

    def get_by_vrf(self, vrf: str) -> list[FabricEndpoint]:
        return [ep for ep in self.endpoints if ep.vrf == vrf]

    def get_by_leaf(self, leaf_hostname: str) -> list[FabricEndpoint]:
        results = []
        for ep in self.endpoints:
            for conn in ep.connected_to:
                if conn.get("device") == leaf_hostname:
                    results.append(ep)
                    break
        return results
