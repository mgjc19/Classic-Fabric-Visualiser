"""
Failover Simulation - Models port-channel/vPC behavior, failure injection,
and reconvergence paths through the fabric.
"""
from typing import Optional
from .fabric_model import FabricModel, FabricDevice, FabricLink
from .endpoint_model import EndpointStore, FabricEndpoint
from .traffic_engine import TrafficEngine


class PortChannelGroup:
    """Represents a port-channel (LAG) group."""

    def __init__(self, pc_id: str, device: str, members: list[dict] = None,
                 vpc_id: str = "", lacp_mode: str = "active"):
        self.pc_id = pc_id
        self.device = device
        self.members: list[dict] = members or []
        self.vpc_id = vpc_id
        self.lacp_mode = lacp_mode

    def active_members(self, failed_links: set) -> list[dict]:
        """Return only members whose links are not failed."""
        return [m for m in self.members if m.get("link_id") not in failed_links]

    def is_up(self, failed_links: set) -> bool:
        """Port-channel is up if at least one member is active."""
        return len(self.active_members(failed_links)) > 0

    def to_dict(self) -> dict:
        return {
            "pc_id": self.pc_id,
            "device": self.device,
            "members": self.members,
            "vpc_id": self.vpc_id,
            "lacp_mode": self.lacp_mode,
        }


class VpcDomain:
    """Represents a vPC domain between two peer switches."""

    def __init__(self, domain_id: str, primary: str, secondary: str,
                 peer_link_id: str = "", keepalive_vrf: str = "management"):
        self.domain_id = domain_id
        self.primary = primary
        self.secondary = secondary
        self.peer_link_id = peer_link_id
        self.keepalive_vrf = keepalive_vrf

    def is_peer_link_up(self, failed_links: set) -> bool:
        return self.peer_link_id not in failed_links

    def active_peer(self, failed_devices: set) -> Optional[str]:
        """Return which peer(s) are available."""
        active = []
        if self.primary not in failed_devices:
            active.append(self.primary)
        if self.secondary not in failed_devices:
            active.append(self.secondary)
        return active[0] if active else None

    def to_dict(self) -> dict:
        return {
            "domain_id": self.domain_id,
            "primary": self.primary,
            "secondary": self.secondary,
            "peer_link_id": self.peer_link_id,
            "keepalive_vrf": self.keepalive_vrf,
        }


class FailoverSimulator:
    """Simulates failover scenarios in the VXLAN fabric."""

    def __init__(self, fabric: FabricModel, endpoints: EndpointStore,
                 traffic_engine: TrafficEngine):
        self.fabric = fabric
        self.endpoints = endpoints
        self.traffic = traffic_engine
        self.port_channels: list[PortChannelGroup] = []
        self.vpc_domains: list[VpcDomain] = []
        self._build_pc_and_vpc_from_model()

    def _build_pc_and_vpc_from_model(self):
        """Infer port-channels and vPC domains from fabric model."""
        vpc_peers = {}
        for device in self.fabric.devices:
            if device.vpc_domain and device.vpc_peer:
                key = tuple(sorted([device.hostname, device.vpc_peer]))
                if key not in vpc_peers:
                    vpc_peers[key] = {
                        "domain_id": device.vpc_domain,
                        "primary": key[0],
                        "secondary": key[1],
                    }

        for key, info in vpc_peers.items():
            self.vpc_domains.append(VpcDomain(
                domain_id=info["domain_id"],
                primary=info["primary"],
                secondary=info["secondary"]
            ))

    def simulate_failover(self, src_id: str, dst_id: str, failure: dict) -> dict:
        """
        Simulate a failure and compute failover path.
        Returns both original and failover paths with convergence status.
        """
        return self.traffic.failover_trace(src_id, dst_id, failure)

    def simulate_link_failure(self, link_id: str) -> dict:
        """Simulate a single link failure and return impact."""
        link = self.fabric.get_link(link_id)
        if not link:
            return {"error": "Link not found", "converged": False}

        self.traffic.simulate_failure("link", link_id)

        affected_eps = []
        for ep in self.endpoints.endpoints:
            for conn in ep.connected_to:
                if conn.get("device") == link.from_device or conn.get("device") == link.to_device:
                    affected_eps.append(ep.name)
                    break

        has_redundancy = self._check_redundancy_for_link(link)

        self.traffic.restore("link", link_id)

        return {
            "link": link.to_dict(),
            "affected_endpoints": affected_eps,
            "has_redundancy": has_redundancy,
            "converged": has_redundancy,
            "convergence_reason": "Redundant path available" if has_redundancy else "No redundant path"
        }

    def simulate_device_failure(self, device_id: str) -> dict:
        """Simulate a device failure and return impact."""
        device = self.fabric.get_device(device_id)
        if not device:
            return {"error": "Device not found", "converged": False}

        self.traffic.simulate_failure("device", device_id)

        affected_eps = []
        for ep in self.endpoints.endpoints:
            for conn in ep.connected_to:
                if conn.get("device") == device.hostname:
                    vpc_peer = self._find_vpc_peer(device.hostname)
                    if vpc_peer:
                        affected_eps.append({"endpoint": ep.name, "failover": vpc_peer, "status": "converged"})
                    else:
                        affected_eps.append({"endpoint": ep.name, "failover": None, "status": "isolated"})
                    break

        self.traffic.restore("device", device_id)

        converged_count = sum(1 for a in affected_eps if a.get("status") == "converged")
        total = len(affected_eps)

        return {
            "device": device.hostname,
            "affected_endpoints": affected_eps,
            "converged": converged_count == total and total > 0,
            "convergence_reason": f"{converged_count}/{total} endpoints reconverged"
        }

    def simulate_port_channel_member_failure(self, pc_id: str, member_link_id: str) -> dict:
        """Simulate a single port-channel member failure."""
        pc = next((p for p in self.port_channels if p.pc_id == pc_id), None)
        if not pc:
            return {"error": "Port-channel not found"}

        remaining = [m for m in pc.members if m.get("link_id") != member_link_id]
        return {
            "port_channel": pc_id,
            "remaining_members": len(remaining),
            "total_members": len(pc.members),
            "port_channel_up": len(remaining) > 0,
            "bandwidth_reduction": f"{100 - (len(remaining) * 100 // max(len(pc.members), 1))}%"
        }

    def _check_redundancy_for_link(self, link: FabricLink) -> bool:
        """Check if there's a redundant path when a link fails."""
        from_dev = self.fabric.get_device(link.from_device)
        to_dev = self.fabric.get_device(link.to_device)
        if not from_dev or not to_dev:
            return False

        other_links = [
            l for l in self.fabric.links
            if l.id != link.id and (
                (l.from_device == link.from_device and l.to_device == link.to_device) or
                (l.from_device == link.to_device and l.to_device == link.from_device)
            )
        ]
        if other_links:
            return True

        if from_dev.role in ("leaf", "border_leaf"):
            spine_links = [
                l for l in self.fabric.links
                if l.id != link.id and (
                    l.from_device == from_dev.hostname or l.to_device == from_dev.hostname
                )
            ]
            return len(spine_links) > 0

        return False

    def _find_vpc_peer(self, hostname: str) -> Optional[str]:
        """Find the vPC peer for a given device."""
        for vpc in self.vpc_domains:
            if vpc.primary == hostname:
                return vpc.secondary
            if vpc.secondary == hostname:
                return vpc.primary

        device = next((d for d in self.fabric.devices if d.hostname == hostname), None)
        if device and device.vpc_peer:
            return device.vpc_peer
        return None

    def get_vpc_health(self) -> list[dict]:
        """Return health status of all vPC domains."""
        results = []
        for vpc in self.vpc_domains:
            primary_up = vpc.primary not in self.traffic.failed_devices
            secondary_up = vpc.secondary not in self.traffic.failed_devices
            peer_link_up = vpc.is_peer_link_up(self.traffic.failed_links)
            results.append({
                "domain_id": vpc.domain_id,
                "primary": vpc.primary,
                "secondary": vpc.secondary,
                "primary_up": primary_up,
                "secondary_up": secondary_up,
                "peer_link_up": peer_link_up,
                "status": "healthy" if (primary_up and secondary_up and peer_link_up) else "degraded"
            })
        return results
