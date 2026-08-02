"""
Underlay & Overlay Design Engine — generates routing design recommendations
for VXLAN fabric migration based on device roles, user-selected underlay
protocol (OSPF or eBGP), and BGP address-family selections.
"""
from __future__ import annotations

from typing import Optional


UNDERLAY_PROTOCOLS = ("ospf", "ebgp")

BGP_ADDRESS_FAMILIES = {
    "l2vpn_evpn": "L2VPN EVPN (VXLAN overlay — required)",
    "ipv4_unicast": "IPv4 Unicast",
    "ipv6_unicast": "IPv6 Unicast",
}


class UnderlayDesigner:
    """
    Produces per-device underlay and overlay routing design parameters
    based on the migration classification and user preferences.
    """

    def __init__(
        self,
        classifications: dict[str, dict],
        nodes: dict[str, dict],
        adjacency: dict[str, list[dict]],
    ):
        self._classifications = classifications
        self._nodes = nodes
        self._adjacency = adjacency

    def design(
        self,
        underlay_protocol: str = "ospf",
        bgp_afs: Optional[list[str]] = None,
        ospf_area: str = "0.0.0.0",
        spine_asn: int = 65000,
        leaf_asn_start: int = 65001,
        overlay_asn: Optional[int] = None,
    ) -> dict:
        underlay_protocol = underlay_protocol.lower()
        if underlay_protocol not in UNDERLAY_PROTOCOLS:
            underlay_protocol = "ospf"

        if bgp_afs is None:
            bgp_afs = ["l2vpn_evpn"]
        if "l2vpn_evpn" not in bgp_afs:
            bgp_afs.insert(0, "l2vpn_evpn")

        if overlay_asn is None:
            overlay_asn = spine_asn

        per_device = {}
        leaf_asn_counter = leaf_asn_start

        spines = []
        leaves = []
        border_leaves = []
        service_leaves = []

        for dev_id, cls_info in self._classifications.items():
            role = cls_info.get("proposed_role", "leaf")
            if role == "spine":
                spines.append(dev_id)
            elif role == "border_leaf":
                border_leaves.append(dev_id)
            elif role == "service_leaf":
                service_leaves.append(dev_id)
            elif role == "leaf":
                leaves.append(dev_id)

        all_fabric_devices = spines + border_leaves + service_leaves + leaves

        for dev_id in all_fabric_devices:
            cls_info = self._classifications.get(dev_id, {})
            role = cls_info.get("proposed_role", "leaf")
            node_data = self._nodes.get(dev_id, {})

            device_design = {
                "device_id": dev_id,
                "proposed_role": role,
                "label": node_data.get("label", dev_id),
                "underlay": {},
                "overlay": {},
            }

            if underlay_protocol == "ospf":
                device_design["underlay"] = self._design_ospf_underlay(dev_id, role, ospf_area)
                device_design["overlay"] = self._design_ibgp_overlay(dev_id, role, overlay_asn, bgp_afs, spines)
            else:
                assigned_asn = spine_asn if role == "spine" else leaf_asn_counter
                if role != "spine":
                    leaf_asn_counter += 1
                device_design["underlay"] = self._design_ebgp_underlay(dev_id, role, assigned_asn, spine_asn, leaf_asn_start)
                device_design["overlay"] = self._design_ebgp_overlay(dev_id, role, assigned_asn, spine_asn, bgp_afs, spines)

            per_device[dev_id] = device_design

        protocol_params = {
            "underlay_protocol": underlay_protocol,
            "bgp_address_families": bgp_afs,
            "ospf_area": ospf_area if underlay_protocol == "ospf" else None,
            "spine_asn": spine_asn,
            "leaf_asn_start": leaf_asn_start if underlay_protocol == "ebgp" else None,
            "overlay_asn": overlay_asn,
            "spine_count": len(spines),
            "leaf_count": len(leaves),
            "border_leaf_count": len(border_leaves),
            "service_leaf_count": len(service_leaves),
        }

        summary = self._build_summary(underlay_protocol, bgp_afs, protocol_params)

        return {
            "summary": summary,
            "per_device": per_device,
            "protocol_params": protocol_params,
        }

    def _design_ospf_underlay(self, dev_id: str, role: str, area: str) -> dict:
        neighbors = self._adjacency.get(dev_id, [])
        fabric_links = []
        for edge in neighbors:
            peer_id = edge["target"] if edge["source"] == dev_id else edge["source"]
            peer_cls = self._classifications.get(peer_id, {})
            peer_role = peer_cls.get("proposed_role", "")
            if peer_role in ("spine", "leaf", "border_leaf", "service_leaf"):
                intf = edge.get("local_interface", "") if edge["source"] == dev_id else edge.get("remote_interface", "")
                fabric_links.append({"interface": intf, "peer": peer_id, "peer_role": peer_role})

        config_notes = []
        if role == "spine":
            config_notes = [
                "OSPF router-id: use loopback0 IP",
                "Enable OSPF on all fabric-facing P2P interfaces",
                "Set all fabric links as point-to-point (no DR/BDR)",
                "BFD recommended on all OSPF adjacencies",
            ]
        else:
            config_notes = [
                "OSPF router-id: use loopback0 IP",
                "Enable OSPF on uplinks to spines only",
                "Set uplinks as point-to-point",
                "Advertise loopback0 (VTEP source) into OSPF",
                "BFD recommended on OSPF adjacencies",
            ]

        return {
            "protocol": "OSPF",
            "area": area,
            "network_type": "point-to-point",
            "fabric_interfaces": fabric_links,
            "bfd": True,
            "config_notes": config_notes,
            "authentication": "md5 (recommended)",
        }

    def _design_ibgp_overlay(self, dev_id: str, role: str, asn: int, afs: list[str], spines: list[str]) -> dict:
        config_notes = []
        neighbors = []

        if role == "spine":
            config_notes.append(f"iBGP overlay ASN: {asn}")
            config_notes.append("Act as route-reflector for all leaf clients")
            config_notes.append("Peer with all leaf loopback0 addresses")
            for leaf_id in self._get_fabric_peers(dev_id):
                leaf_cls = self._classifications.get(leaf_id, {})
                leaf_role = leaf_cls.get("proposed_role", "")
                if leaf_role in ("leaf", "border_leaf", "service_leaf"):
                    neighbors.append({"peer": leaf_id, "peer_role": leaf_role, "session_type": "route-reflector-client"})
        else:
            config_notes.append(f"iBGP overlay ASN: {asn}")
            config_notes.append("Peer with spine route-reflectors (loopback0)")
            for s in spines:
                neighbors.append({"peer": s, "peer_role": "spine", "session_type": "to-route-reflector"})

        af_config = []
        for af in afs:
            af_entry = {"af": af, "label": BGP_ADDRESS_FAMILIES.get(af, af)}
            if af == "l2vpn_evpn":
                af_entry["notes"] = "Required for VXLAN — advertise/receive VNI routes"
                af_entry["send_community"] = "both"
            elif af == "ipv4_unicast":
                af_entry["notes"] = "Underlay reachability via iBGP (optional with OSPF underlay)"
            elif af == "ipv6_unicast":
                af_entry["notes"] = "IPv6 overlay or dual-stack fabric"
            af_config.append(af_entry)

        return {
            "protocol": "iBGP",
            "asn": asn,
            "role_function": "route-reflector" if role == "spine" else "client",
            "neighbors": neighbors,
            "address_families": af_config,
            "config_notes": config_notes,
            "update_source": "loopback0",
            "multihop": role != "spine",
        }

    def _design_ebgp_underlay(self, dev_id: str, role: str, asn: int, spine_asn: int, leaf_asn_start: int) -> dict:
        neighbors = self._adjacency.get(dev_id, [])
        fabric_links = []
        for edge in neighbors:
            peer_id = edge["target"] if edge["source"] == dev_id else edge["source"]
            peer_cls = self._classifications.get(peer_id, {})
            peer_role = peer_cls.get("proposed_role", "")
            if peer_role in ("spine", "leaf", "border_leaf", "service_leaf"):
                intf = edge.get("local_interface", "") if edge["source"] == dev_id else edge.get("remote_interface", "")
                peer_asn = spine_asn if peer_role == "spine" else None
                fabric_links.append({"interface": intf, "peer": peer_id, "peer_role": peer_role, "peer_asn": peer_asn})

        config_notes = []
        if role == "spine":
            config_notes = [
                f"Spine ASN: {asn}",
                "Peer with all directly-connected leaf switches",
                "Use interface-level unnumbered or /31 P2P links",
                "BFD recommended",
            ]
        else:
            config_notes = [
                f"Leaf ASN: {asn}",
                "Peer with directly-connected spines",
                "Advertise loopback0 (VTEP source) via redistribute connected",
                "BFD recommended",
            ]

        return {
            "protocol": "eBGP",
            "asn": asn,
            "fabric_interfaces": fabric_links,
            "bfd": True,
            "config_notes": config_notes,
            "maximum_paths": max(2, len([l for l in fabric_links if l["peer_role"] == "spine"])),
        }

    def _design_ebgp_overlay(self, dev_id: str, role: str, asn: int, spine_asn: int, afs: list[str], spines: list[str]) -> dict:
        config_notes = []
        neighbors = []

        if role == "spine":
            config_notes.append(f"Overlay eBGP on spine ASN: {asn}")
            config_notes.append("Peer with leaf loopbacks for EVPN")
            config_notes.append("Set next-hop-unchanged for Type-2/5 routes")
            for peer_id in self._get_fabric_peers(dev_id):
                peer_cls = self._classifications.get(peer_id, {})
                peer_role = peer_cls.get("proposed_role", "")
                if peer_role in ("leaf", "border_leaf", "service_leaf"):
                    neighbors.append({"peer": peer_id, "peer_role": peer_role, "session_type": "ebgp-multihop"})
        else:
            config_notes.append(f"Overlay eBGP on leaf ASN: {asn}")
            config_notes.append("Peer with spine loopbacks for EVPN")
            for s in spines:
                neighbors.append({"peer": s, "peer_role": "spine", "session_type": "ebgp-multihop"})

        af_config = []
        for af in afs:
            af_entry = {"af": af, "label": BGP_ADDRESS_FAMILIES.get(af, af)}
            if af == "l2vpn_evpn":
                af_entry["notes"] = "EVPN overlay — send-community both, next-hop-self on leaf"
                af_entry["send_community"] = "both"
            elif af == "ipv4_unicast":
                af_entry["notes"] = "IPv4 prefix exchange (useful for external connectivity)"
            elif af == "ipv6_unicast":
                af_entry["notes"] = "IPv6 prefix exchange for dual-stack"
            af_config.append(af_entry)

        return {
            "protocol": "eBGP",
            "asn": asn,
            "role_function": "transit" if role == "spine" else "vtep",
            "neighbors": neighbors,
            "address_families": af_config,
            "config_notes": config_notes,
            "update_source": "loopback0",
            "ebgp_multihop": 2,
        }

    def _get_fabric_peers(self, dev_id: str) -> list[str]:
        neighbors = self._adjacency.get(dev_id, [])
        peers = set()
        for edge in neighbors:
            peer_id = edge["target"] if edge["source"] == dev_id else edge["source"]
            peer_cls = self._classifications.get(peer_id, {})
            peer_role = peer_cls.get("proposed_role", "")
            if peer_role in ("spine", "leaf", "border_leaf", "service_leaf"):
                peers.add(peer_id)
        return list(peers)

    def _build_summary(self, protocol: str, afs: list[str], params: dict) -> dict:
        if protocol == "ospf":
            underlay_desc = f"OSPF (single area {params['ospf_area']}) — all fabric P2P links"
            overlay_desc = f"iBGP AS {params['overlay_asn']} — spines as route-reflectors"
        else:
            underlay_desc = f"eBGP — spine AS {params['spine_asn']}, leaf ASNs from {params['leaf_asn_start']}"
            overlay_desc = "eBGP multihop — EVPN peering over loopbacks"

        af_labels = [BGP_ADDRESS_FAMILIES.get(af, af) for af in afs]

        return {
            "underlay": underlay_desc,
            "overlay": overlay_desc,
            "address_families": af_labels,
            "total_fabric_devices": (
                params["spine_count"] + params["leaf_count"] +
                params["border_leaf_count"] + params["service_leaf_count"]
            ),
            "design_notes": [
                "Loopback0 on every fabric device for VTEP/router-id",
                "BFD on all fabric adjacencies for sub-second convergence",
                "ECMP across all available spine paths",
                "L2VPN EVPN address-family required on all VTEP devices",
            ],
        }
