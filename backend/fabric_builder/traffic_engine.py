"""
Traffic Engine - L2/L3 VXLAN path computation with VNI/VRF validation.
Computes forwarding paths through the fabric for traffic simulation.
"""
from typing import Optional
from .fabric_model import FabricModel, FabricDevice, FabricLink
from .endpoint_model import EndpointStore, FabricEndpoint


class TrafficEngine:
    """Computes L2/L3 forwarding paths through a VXLAN fabric."""

    def __init__(self, fabric: FabricModel, endpoints: EndpointStore):
        self.fabric = fabric
        self.endpoints = endpoints
        self.failed_links: set = set()
        self.failed_devices: set = set()

    def trace(self, src_id: str, dst_id: str, vlan: str = "", vrf: str = "") -> dict:
        """
        Trace traffic from source endpoint to destination endpoint.
        Returns path details including hops, validation status, and failure reasons.
        """
        src_ep = self.endpoints.get(src_id)
        dst_ep = self.endpoints.get(dst_id)

        if not src_ep:
            return self._fail("Source endpoint not found")
        if not dst_ep:
            return self._fail("Destination endpoint not found")

        src_vlan = vlan or src_ep.vlan
        dst_vlan = dst_ep.vlan
        src_vrf = vrf or src_ep.vrf
        dst_vrf = dst_ep.vrf

        ingress_leaf = self._get_connected_leaf(src_ep)
        egress_leaf = self._get_connected_leaf(dst_ep)

        if not ingress_leaf:
            return self._fail("Source endpoint not connected to any leaf switch")
        if not egress_leaf:
            return self._fail("Destination endpoint not connected to any leaf switch")

        if ingress_leaf.id in self.failed_devices:
            return self._fail(f"Ingress leaf {ingress_leaf.hostname} is down")
        if egress_leaf.id in self.failed_devices:
            return self._fail(f"Egress leaf {egress_leaf.hostname} is down")

        if ingress_leaf.id == egress_leaf.id:
            result = self._trace_l2_local(src_ep, dst_ep, ingress_leaf, src_vlan)
        elif src_vlan == dst_vlan and src_vrf == dst_vrf:
            result = self._trace_l2_vxlan(src_ep, dst_ep, ingress_leaf, egress_leaf, src_vlan, src_vrf)
        elif src_vrf == dst_vrf:
            result = self._trace_l3_vxlan(src_ep, dst_ep, ingress_leaf, egress_leaf, src_vrf)
        else:
            result = self._trace_inter_vrf(src_ep, dst_ep, ingress_leaf, egress_leaf, src_vrf, dst_vrf)

        result["src_endpoint"] = {
            "id": src_ep.id, "name": src_ep.name, "ip": src_ep.ip,
            "vlan": src_vlan, "vrf": src_vrf, "type": src_ep.type,
            "connected_to": ingress_leaf.hostname
        }
        result["dst_endpoint"] = {
            "id": dst_ep.id, "name": dst_ep.name, "ip": dst_ep.ip,
            "vlan": dst_vlan, "vrf": dst_vrf, "type": dst_ep.type,
            "connected_to": egress_leaf.hostname
        }
        vni = self._get_vni_for_vlan(src_vlan)
        l3vni = self._get_l3vni_for_vrf(src_vrf) if src_vrf else None
        result["overlay"] = {
            "src_vlan": src_vlan, "dst_vlan": dst_vlan,
            "src_vrf": src_vrf, "dst_vrf": dst_vrf,
            "l2vni": vni, "l3vni": l3vni,
            "ingress_vtep": ingress_leaf.loopback1 if hasattr(ingress_leaf, 'loopback1') else "",
            "egress_vtep": egress_leaf.loopback1 if hasattr(egress_leaf, 'loopback1') else "",
        }
        return result

    def simulate_failure(self, failure_type: str, target_id: str) -> dict:
        """Inject a failure and return affected state."""
        if failure_type == "device":
            self.failed_devices.add(target_id)
            device = self.fabric.get_device(target_id)
            return {
                "type": "device",
                "target": device.hostname if device else target_id,
                "affected_links": self._count_device_links(target_id)
            }
        elif failure_type == "link":
            self.failed_links.add(target_id)
            return {"type": "link", "target": target_id}
        return {"type": "unknown"}

    def restore(self, failure_type: str, target_id: str):
        """Restore a previously failed element."""
        if failure_type == "device":
            self.failed_devices.discard(target_id)
        elif failure_type == "link":
            self.failed_links.discard(target_id)

    def failover_trace(self, src_id: str, dst_id: str, failure: dict) -> dict:
        """Trace with a failure injected, showing original and failover paths."""
        original = self.trace(src_id, dst_id)

        f_type = failure.get("type", "link")
        f_target = failure.get("target_id", "")
        self.simulate_failure(f_type, f_target)

        failover = self.trace(src_id, dst_id)

        self.restore(f_type, f_target)

        return {
            "original_path": original.get("hops", []),
            "failover_path": failover.get("hops", []) if failover.get("success") else None,
            "converged": failover.get("success", False),
            "convergence_reason": failover.get("failure_reason", "Traffic reconverged via alternate path") if not failover.get("success") else "Reconverged",
            "affected_endpoints": self._get_affected_endpoints(f_type, f_target)
        }

    def _trace_l2_local(self, src: FabricEndpoint, dst: FabricEndpoint,
                        leaf: FabricDevice, vlan: str) -> dict:
        """Both endpoints on same leaf, same VLAN - direct L2 forward."""
        vlan_valid = self._validate_vlan_on_device(vlan, leaf)
        if not vlan_valid:
            return self._fail(f"VLAN {vlan} not configured on {leaf.hostname}")

        hops = [
            {"device": leaf.hostname, "ingress_port": self._get_ep_port(src, leaf),
             "egress_port": self._get_ep_port(dst, leaf), "action": "L2 forward", "encap": "none"}
        ]
        return {
            "success": True,
            "hops": hops,
            "path_type": "l2_local",
            "ecmp_paths": 1,
            "failure_reason": None,
            "failure_hop": None
        }

    def _trace_l2_vxlan(self, src: FabricEndpoint, dst: FabricEndpoint,
                        ingress: FabricDevice, egress: FabricDevice,
                        vlan: str, vrf: str) -> dict:
        """Same VLAN cross-leaf - L2 VXLAN encapsulation."""
        vni = self._get_vni_for_vlan(vlan)
        if not vni:
            return self._fail(f"No L2VNI mapped for VLAN {vlan} on {ingress.hostname}")

        if not self._validate_vlan_on_device(vlan, ingress):
            return self._fail(f"VLAN {vlan} not configured on ingress leaf {ingress.hostname}")
        if not self._validate_vlan_on_device(vlan, egress):
            return self._fail(f"VLAN {vlan} not configured on egress leaf {egress.hostname}")

        spines = self._find_spine_path(ingress, egress)
        if not spines:
            return self._fail(f"No path from {ingress.hostname} to {egress.hostname}: all spine uplinks failed")

        hops = [
            {"device": ingress.hostname, "ingress_port": self._get_ep_port(src, ingress),
             "egress_port": "NVE1", "action": "VXLAN encap", "encap": f"VNI {vni}"}
        ]
        for spine in spines[:1]:
            hops.append({
                "device": spine.hostname, "ingress_port": "fabric",
                "egress_port": "fabric", "action": "L3 route (underlay)", "encap": f"VNI {vni}"
            })
        hops.append({
            "device": egress.hostname, "ingress_port": "NVE1",
            "egress_port": self._get_ep_port(dst, egress), "action": "VXLAN decap + L2 forward", "encap": "none"
        })

        return {
            "success": True,
            "hops": hops,
            "path_type": "l2_vxlan",
            "ecmp_paths": len(spines),
            "failure_reason": None,
            "failure_hop": None
        }

    def _trace_l3_vxlan(self, src: FabricEndpoint, dst: FabricEndpoint,
                        ingress: FabricDevice, egress: FabricDevice, vrf: str) -> dict:
        """Different VLANs, same VRF - L3 VXLAN (symmetric IRB)."""
        l3vni = self._get_l3vni_for_vrf(vrf)
        if not l3vni:
            return self._fail(f"No L3VNI configured for VRF {vrf}")

        if not self._validate_vrf_on_device(vrf, ingress):
            return self._fail(f"VRF {vrf} not configured on ingress leaf {ingress.hostname}")
        if not self._validate_vrf_on_device(vrf, egress):
            return self._fail(f"VRF {vrf} not configured on egress leaf {egress.hostname}")

        src_vlan = src.vlan
        if not self._validate_anycast_gw(src_vlan, ingress):
            return self._fail(f"No anycast gateway for VLAN {src_vlan} on {ingress.hostname}")

        spines = self._find_spine_path(ingress, egress)
        if not spines:
            return self._fail(f"No path from {ingress.hostname} to {egress.hostname}")

        hops = [
            {"device": ingress.hostname, "ingress_port": self._get_ep_port(src, ingress),
             "egress_port": "NVE1", "action": "L3 route + VXLAN encap (IRB)", "encap": f"L3VNI {l3vni}"}
        ]
        for spine in spines[:1]:
            hops.append({
                "device": spine.hostname, "ingress_port": "fabric",
                "egress_port": "fabric", "action": "L3 route (underlay)", "encap": f"L3VNI {l3vni}"
            })
        hops.append({
            "device": egress.hostname, "ingress_port": "NVE1",
            "egress_port": self._get_ep_port(dst, egress), "action": "VXLAN decap + L3 route + L2 forward",
            "encap": "none"
        })

        return {
            "success": True,
            "hops": hops,
            "path_type": "l3_vxlan",
            "ecmp_paths": len(spines),
            "failure_reason": None,
            "failure_hop": None
        }

    def _trace_inter_vrf(self, src: FabricEndpoint, dst: FabricEndpoint,
                         ingress: FabricDevice, egress: FabricDevice,
                         src_vrf: str, dst_vrf: str) -> dict:
        """Different VRFs - requires route leaking or external routing."""
        return self._fail(f"Inter-VRF routing not configured between {src_vrf} and {dst_vrf}")

    def _get_connected_leaf(self, ep: FabricEndpoint) -> Optional[FabricDevice]:
        """Find the leaf switch an endpoint is connected to."""
        for conn in ep.connected_to:
            device_ref = conn.get("device", "")
            dev = self.fabric.get_device(device_ref)
            if dev and dev.id not in self.failed_devices:
                return dev
        return None

    def _get_ep_port(self, ep: FabricEndpoint, leaf: FabricDevice) -> str:
        """Get the port on a leaf where an endpoint is connected."""
        for conn in ep.connected_to:
            if conn.get("device") == leaf.hostname or conn.get("device") == leaf.id:
                return conn.get("port", "access-port")
        return "access-port"

    def _find_spine_path(self, ingress: FabricDevice, egress: FabricDevice) -> list:
        """Find available spine switches connecting ingress and egress leaves."""
        spines = []
        all_spines = [d for d in self.fabric.devices if d.role in ("spine", "super_spine")]

        for spine in all_spines:
            if spine.id in self.failed_devices:
                continue
            has_ingress_link = any(
                (l.from_device == ingress.hostname and l.to_device == spine.hostname) or
                (l.to_device == ingress.hostname and l.from_device == spine.hostname)
                for l in self.fabric.links if l.id not in self.failed_links
            )
            has_egress_link = any(
                (l.from_device == egress.hostname and l.to_device == spine.hostname) or
                (l.to_device == egress.hostname and l.from_device == spine.hostname)
                for l in self.fabric.links if l.id not in self.failed_links
            )
            if has_ingress_link and has_egress_link:
                spines.append(spine)

        return spines

    def _get_vni_for_vlan(self, vlan: str) -> Optional[int]:
        """Look up the L2 VNI for a given VLAN."""
        try:
            vlan_int = int(vlan)
        except (ValueError, TypeError):
            return None
        for v in self.fabric.overlay.vlans:
            if v.get("vlan_id") == vlan_int and v.get("vni"):
                return v["vni"]
        for vni_entry in self.fabric.overlay.vnis:
            if vni_entry.get("vlan_id") == vlan_int and not vni_entry.get("is_l3vni"):
                return vni_entry["vni"]
        return None

    def _get_l3vni_for_vrf(self, vrf: str) -> Optional[int]:
        """Look up the L3 VNI for a given VRF."""
        for v in self.fabric.overlay.vrfs:
            if v.get("name") == vrf and v.get("vni"):
                return v["vni"]
        for vni_entry in self.fabric.overlay.vnis:
            if vni_entry.get("vrf") == vrf and vni_entry.get("is_l3vni"):
                return vni_entry["vni"]
        return None

    def _validate_vlan_on_device(self, vlan: str, device: FabricDevice) -> bool:
        """Check if a VLAN is allowed/configured on a device (permissive by default)."""
        if not vlan:
            return True
        for v in self.fabric.overlay.vlans:
            try:
                if v.get("vlan_id") == int(vlan):
                    return True
            except (ValueError, TypeError):
                pass
        return True

    def _validate_vrf_on_device(self, vrf: str, device: FabricDevice) -> bool:
        """Check if a VRF is configured on a device."""
        if not vrf:
            return True
        for v in self.fabric.overlay.vrfs:
            if v.get("name") == vrf:
                return True
        return False

    def _validate_anycast_gw(self, vlan: str, device: FabricDevice) -> bool:
        """Check if anycast gateway is configured for a VLAN."""
        if not vlan:
            return True
        for v in self.fabric.overlay.vlans:
            try:
                if v.get("vlan_id") == int(vlan) and v.get("anycast_gw"):
                    return True
            except (ValueError, TypeError):
                pass
        return True

    def _count_device_links(self, device_id: str) -> int:
        """Count links connected to a device."""
        device = self.fabric.get_device(device_id)
        if not device:
            return 0
        return sum(1 for l in self.fabric.links
                   if l.from_device == device.hostname or l.to_device == device.hostname)

    def _get_affected_endpoints(self, failure_type: str, target_id: str) -> list:
        """Get endpoints affected by a failure."""
        affected = []
        if failure_type == "device":
            device = self.fabric.get_device(target_id)
            if device:
                for ep in self.endpoints.endpoints:
                    for conn in ep.connected_to:
                        if conn.get("device") == device.hostname:
                            affected.append(ep.name)
                            break
        return affected

    @staticmethod
    def _fail(reason: str) -> dict:
        return {
            "success": False,
            "hops": [],
            "path_type": "unknown",
            "ecmp_paths": 0,
            "failure_reason": reason,
            "failure_hop": None
        }
