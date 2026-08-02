"""
Migration Role Classifier — analyzes the physical topology and assigns
proposed VXLAN migration roles to each device using weighted scoring.
"""
import re
from typing import Optional


VXLAN_CAPABLE_PATTERNS = [
    (r"nexus\s*9[0-9]{3}", "full"),
    (r"n9k", "full"),
    (r"nexus\s*7[0-9]{3}", "limited"),
    (r"n7k", "limited"),
    (r"c9[3-5]00", "full"),
    (r"catalyst\s*9[3-5]00", "full"),
    (r"c9200", "limited"),
    (r"dcs-7[0-9]{3}", "full"),
    (r"arista", "full"),
    (r"qfx5[0-9]{3}", "full"),
    (r"qfx10[0-9]{3}", "full"),
    (r"ex4[36]00", "full"),
]

UNSUPPORTED_PATTERNS = [
    r"ws-c29", r"ws-c37", r"ws-c38",
    r"catalyst\s*[23][0-9]{3}",
    r"c3[5-7][56]0",
    r"nexus\s*[235][0-9]{3}",
    r"n[235]k", r"6500", r"6800", r"4500",
]


class MigrationClassifier:
    def __init__(self, topology_result: dict):
        self._nodes = {n["data"]["id"]: n["data"] for n in topology_result.get("nodes", [])}
        self._edges = topology_result.get("edges", [])
        self._device_details = topology_result.get("device_details", {})
        self._vlan_data = topology_result.get("vlan_data", {})

        self._adjacency: dict[str, list[dict]] = {}
        for edge in self._edges:
            src = edge["data"]["source"]
            tgt = edge["data"]["target"]
            self._adjacency.setdefault(src, []).append(edge["data"])
            self._adjacency.setdefault(tgt, []).append(edge["data"])

    def classify_all(self) -> dict[str, dict]:
        return {dev_id: self._classify_device(dev_id, dev_data) for dev_id, dev_data in self._nodes.items()}

    def _classify_device(self, dev_id: str, dev_data: dict) -> dict:
        current_role = dev_data.get("role", "switch")

        if current_role == "wan_cloud":
            return {"proposed_role": "wan_cloud", "confidence": 1.0, "reasoning": ["External WAN/MPLS cloud"], "capability": "n/a", "capability_note": "External to fabric", "current_role": current_role}
        if current_role == "firewall":
            return {"proposed_role": "service_node", "confidence": 0.9, "reasoning": ["Firewall — service insertion"], "capability": "n/a", "capability_note": "No VTEP needed", "current_role": current_role}
        if current_role == "loadbalancer":
            return {"proposed_role": "service_node", "confidence": 0.9, "reasoning": ["Load balancer — service insertion"], "capability": "n/a", "capability_note": "No VTEP needed", "current_role": current_role}

        scores = {"spine": 0.0, "leaf": 0.0, "border_leaf": 0.0, "service_leaf": 0.0}
        reasoning = []

        neighbors = self._adjacency.get(dev_id, [])
        neighbor_roles = []
        for edge in neighbors:
            peer_id = edge["target"] if edge["source"] == dev_id else edge["source"]
            peer_data = self._nodes.get(peer_id, {})
            neighbor_roles.append(peer_data.get("role", "switch"))

        downstream = sum(1 for r in neighbor_roles if r in ("switch", "leaf", "access"))
        upstream = sum(1 for r in neighbor_roles if r in ("spine", "core", "router"))
        wan_conn = sum(1 for r in neighbor_roles if r in ("wan", "wan_cloud"))
        fw_conn = sum(1 for r in neighbor_roles if r == "firewall")
        lb_conn = sum(1 for r in neighbor_roles if r == "loadbalancer")

        details = self._device_details.get(dev_id, {})
        interfaces = details.get("interfaces", [])
        access_ports = sum(1 for i in interfaces if i.get("vlan", "") not in ("trunk", "--", "", None))
        total_ports = len(interfaces) or 1

        if downstream >= 4:
            scores["spine"] += 3.0; reasoning.append(f"High fanout ({downstream} switches)")
        elif downstream >= 2:
            scores["spine"] += 1.5
        if access_ports == 0 and total_ports > 4:
            scores["spine"] += 2.0; reasoning.append("No access ports")
        if current_role in ("spine", "core"):
            scores["spine"] += 2.0

        if access_ports > total_ports * 0.4 and total_ports > 4:
            scores["leaf"] += 3.0; reasoning.append(f"Many access ports ({access_ports}/{total_ports})")
        if upstream >= 1 and downstream == 0:
            scores["leaf"] += 2.0
        if current_role in ("leaf", "access", "switch"):
            scores["leaf"] += 1.0

        if wan_conn >= 1:
            scores["border_leaf"] += 4.0; reasoning.append(f"WAN connected ({wan_conn} links)")
        if current_role == "router":
            scores["border_leaf"] += 2.0

        if fw_conn >= 1 or lb_conn >= 1:
            scores["service_leaf"] += 2.0; reasoning.append("Service device attached")

        best_role = max(scores, key=scores.get)
        best_score = scores[best_role]
        total_score = sum(scores.values()) or 1
        confidence = min(0.95, best_score / total_score) if best_score > 0 else 0.3
        if best_score == 0:
            best_role = "leaf"; confidence = 0.3; reasoning.append("Default to leaf")

        cap, cap_note = self._check_capability(dev_data)
        return {"proposed_role": best_role, "confidence": round(confidence, 2), "reasoning": reasoning, "capability": cap, "capability_note": cap_note, "current_role": current_role}

    def _check_capability(self, dev_data: dict) -> tuple[str, str]:
        model = (dev_data.get("model", "") + " " + dev_data.get("platform", "")).lower()
        if not model.strip():
            return "unknown", "No hardware model detected"
        for pattern, level in VXLAN_CAPABLE_PATTERNS:
            if re.search(pattern, model, re.IGNORECASE):
                return ("supported", "Full VXLAN/EVPN support") if level == "full" else ("limited", "VXLAN with limitations")
        for pattern in UNSUPPORTED_PATTERNS:
            if re.search(pattern, model, re.IGNORECASE):
                return "unsupported", "Hardware does not support VXLAN"
        if "arista" in dev_data.get("vendor", "").lower():
            return "supported", "Arista EOS — full VXLAN support"
        return "unknown", "Unable to determine VXLAN capability"

    def suggest_phases(self, classifications: dict[str, dict]) -> list[dict]:
        phases = [
            {"id": "underlay", "name": "Phase A: Build Underlay", "description": "Configure OSPF/BGP underlay on spines", "devices": []},
            {"id": "border", "name": "Phase B: Border Migration", "description": "Migrate border leafs", "devices": []},
            {"id": "service", "name": "Phase C: Service Leaf", "description": "Migrate service leafs (FW/LB)", "devices": []},
            {"id": "leaf", "name": "Phase D: Leaf Migration", "description": "Migrate access leafs", "devices": []},
            {"id": "cleanup", "name": "Phase E: Cleanup", "description": "Remove STP, legacy trunks", "devices": []},
        ]
        leaf_devices = []
        for dev_id, info in classifications.items():
            role = info["proposed_role"]
            if role == "spine": phases[0]["devices"].append(dev_id)
            elif role == "border_leaf": phases[1]["devices"].append(dev_id)
            elif role == "service_leaf": phases[2]["devices"].append(dev_id)
            elif role == "leaf": leaf_devices.append((dev_id, len(self._adjacency.get(dev_id, []))))
        leaf_devices.sort(key=lambda x: x[1])
        phases[3]["devices"] = [d[0] for d in leaf_devices]
        return phases

    def generate_vni_mapping(self, base_offset: int = 10000) -> list[dict]:
        vlans = self._vlan_data.get("vlans", {})
        mappings = []
        for vid_str, info in sorted(vlans.items(), key=lambda x: int(x[0])):
            vid = int(vid_str)
            if vid in (1, 1002, 1003, 1004, 1005):
                continue
            gateways = [g["device"] for g in info.get("gateways", []) if not g.get("shutdown")]
            mappings.append({"vlan_id": vid, "vlan_name": info.get("name", ""), "vni": vid + base_offset, "device_count": info.get("device_count", 0), "devices": info.get("devices", []), "gateways": gateways, "l3_vni": False})
        return mappings
