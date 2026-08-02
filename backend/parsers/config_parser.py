"""
Parser for running configuration and general config extraction.
Handles 'show running-config' and extracts hostname, interfaces, VLANs, etc.
Multi-vendor: Cisco IOS/IOS-XE/NX-OS, Arista EOS, Juniper JunOS,
Palo Alto PAN-OS, F5 BIG-IP, Fortinet FortiOS, and others.
"""
import re
from typing import Optional


def extract_hostname(raw_text: str) -> str:
    """
    Extract hostname from any command output across vendors.
    Priority: config directive > prompt pattern.
    """
    directives = [
        (r"^hostname\s+(\S+)", re.MULTILINE | re.IGNORECASE),
        (r"^switchname\s+(\S+)", re.MULTILINE | re.IGNORECASE),
        # Juniper: set system host-name <name>
        (r"host-name\s+(\S+);?", re.IGNORECASE),
        # Palo Alto: set deviceconfig system hostname <name>
        (r"deviceconfig\s+system\s+hostname\s+(\S+)", re.IGNORECASE),
        # Fortinet: set hostname <name> / config system global
        (r"set\s+hostname\s+[\"']?(\S+?)[\"']?\s*$", re.MULTILINE | re.IGNORECASE),
        # F5 BIG-IP: sys global-settings { hostname <name> }
        (r"hostname\s+(\S+\.?\S*)", re.IGNORECASE),
        # Arista: hostname <name>  (same as IOS, but also check sysname)
        (r"^sysname\s+(\S+)", re.MULTILINE | re.IGNORECASE),
    ]

    for pattern, flags in directives:
        m = re.search(pattern, raw_text, flags)
        if m:
            name = m.group(1).strip().strip('"').strip("'").rstrip(";")
            if len(name) >= 2 and not name.startswith("!"):
                return name

    prompt_patterns = [
        # Cisco/Arista: HOSTNAME# or HOSTNAME> or HOSTNAME(config)#
        r"^([\w][\w._-]+)(?:\([\w-]+\))?[#>]\s*(?:show|conf|term|en)",
        r"^([\w][\w._-]+)[#>]\s*$",
        # Juniper: user@HOSTNAME>
        r"^\w+@([\w][\w._-]+)[>%#]",
        # Palo Alto: admin@HOSTNAME>
        r"^\w+@([\w][\w._-]+)\([^)]*\)?[>%#]",
        # F5: root@(HOSTNAME)(cfg-sync ...)
        r"root@\(([\w][\w._-]+)\)",
    ]

    for pat in prompt_patterns:
        m = re.search(pat, raw_text, re.MULTILINE)
        if m:
            hostname = m.group(1).strip()
            hostname = re.sub(r"\(config.*?\)", "", hostname)
            if len(hostname) >= 2:
                return hostname

    return ""


def parse_running_config(raw_text: str) -> dict:
    """
    Parse running configuration to extract structured device information.
    Returns hostname, interfaces with config, VLANs, routing info, etc.
    """
    config = {
        "hostname": extract_hostname(raw_text),
        "interfaces": [],
        "vlans": [],
        "routing": {
            "ospf": [],
            "bgp": [],
            "static": [],
        },
        "management": {},
        "port_channels": [],
        "vpc": None,
    }

    config["interfaces"] = _parse_interface_configs(raw_text)
    config["vlans"] = _parse_vlans(raw_text)
    config["routing"] = _parse_routing(raw_text)
    config["management"] = _parse_management(raw_text)
    config["port_channels"] = _parse_port_channels(raw_text, config["interfaces"])
    config["vpc"] = _parse_vpc(raw_text, config["interfaces"])

    return config


def _parse_interface_configs(raw_text: str) -> list[dict]:
    """Extract interface configurations from running config."""
    interfaces = []

    intf_blocks = re.findall(
        r"^interface\s+(\S+)\n((?:(?!\ninterface\s|\n!|\n\S).*\n)*)",
        raw_text,
        re.MULTILINE
    )

    for intf_name, intf_config in intf_blocks:
        entry = {
            "name": intf_name,
            "description": "",
            "ip_address": "",
            "subnet_mask": "",
            "vlan": "",
            "switchport_mode": "",
            "channel_group": "",
            "shutdown": False,
        }

        desc_match = re.search(r"description\s+(.+)", intf_config, re.IGNORECASE)
        if desc_match:
            entry["description"] = desc_match.group(1).strip()

        ip_match = re.search(
            r"ip address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
            intf_config, re.IGNORECASE
        )
        if ip_match:
            entry["ip_address"] = ip_match.group(1)
            entry["subnet_mask"] = ip_match.group(2)

        # NX-OS style: ip address x.x.x.x/prefix
        ip_slash = re.search(
            r"ip address\s+(\d+\.\d+\.\d+\.\d+)/(\d+)",
            intf_config, re.IGNORECASE
        )
        if ip_slash and not entry["ip_address"]:
            entry["ip_address"] = ip_slash.group(1)
            entry["subnet_mask"] = "/" + ip_slash.group(2)

        access_vlan = re.search(r"switchport access vlan\s+(\d+)", intf_config, re.IGNORECASE)
        if access_vlan:
            entry["vlan"] = access_vlan.group(1)

        trunk_match = re.search(r"switchport mode\s+(\S+)", intf_config, re.IGNORECASE)
        if trunk_match:
            entry["switchport_mode"] = trunk_match.group(1)

        channel_match = re.search(r"channel-group\s+(\d+)", intf_config, re.IGNORECASE)
        if channel_match:
            entry["channel_group"] = channel_match.group(1)

        vpc_match = re.search(r"^\s*vpc\s+(\d+)", intf_config, re.MULTILINE)
        if vpc_match:
            entry["vpc"] = vpc_match.group(1)

        vpc_peer = re.search(r"^\s*vpc\s+peer-link", intf_config, re.MULTILINE)
        if vpc_peer:
            entry["vpc_peer_link"] = True

        if re.search(r"^\s*shutdown", intf_config, re.MULTILINE):
            entry["shutdown"] = True

        interfaces.append(entry)

    return interfaces


def _parse_vlans(raw_text: str) -> list[dict]:
    """Extract VLAN definitions."""
    vlans = []

    vlan_blocks = re.findall(
        r"^vlan\s+(\d+)\n((?:(?!\nvlan\s|\n!|\n\S).*\n)*)",
        raw_text,
        re.MULTILINE
    )

    for vlan_id, vlan_config in vlan_blocks:
        entry = {"id": int(vlan_id), "name": ""}
        name_match = re.search(r"name\s+(\S+)", vlan_config, re.IGNORECASE)
        if name_match:
            entry["name"] = name_match.group(1)
        vlans.append(entry)

    return vlans


def _parse_routing(raw_text: str) -> dict:
    """Extract basic routing protocol info."""
    routing = {"ospf": [], "bgp": [], "static": []}

    ospf_procs = re.findall(r"router ospf\s+(\S+)", raw_text, re.IGNORECASE)
    for proc in ospf_procs:
        routing["ospf"].append({"process_id": proc})

    bgp_match = re.search(r"router bgp\s+(\d+)", raw_text, re.IGNORECASE)
    if bgp_match:
        routing["bgp"].append({"asn": bgp_match.group(1)})

    statics = re.findall(
        r"ip route\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)",
        raw_text, re.IGNORECASE
    )
    for network, mask, next_hop in statics:
        routing["static"].append({
            "network": network,
            "mask": mask,
            "next_hop": next_hop,
        })

    return routing


def _parse_management(raw_text: str) -> dict:
    """Extract management interface/access info."""
    mgmt = {"ip": "", "vrf": "", "domain": ""}

    mgmt_intf = re.search(
        r"interface\s+(?:mgmt0|Management\d+|Vlan\d+)\n((?:(?!\ninterface|\n!).*\n)*)",
        raw_text, re.IGNORECASE
    )
    if mgmt_intf:
        ip_match = re.search(r"ip address\s+(\d+\.\d+\.\d+\.\d+)", mgmt_intf.group(1))
        if ip_match:
            mgmt["ip"] = ip_match.group(1)
        vrf_match = re.search(r"vrf (?:member|forwarding)\s+(\S+)", mgmt_intf.group(1), re.IGNORECASE)
        if vrf_match:
            mgmt["vrf"] = vrf_match.group(1)

    domain_match = re.search(r"ip domain[- ]name\s+(\S+)", raw_text, re.IGNORECASE)
    if domain_match:
        mgmt["domain"] = domain_match.group(1)

    return mgmt


def _parse_port_channels(raw_text: str, interfaces: list[dict]) -> list[dict]:
    """
    Extract port-channel information from running config and
    'show etherchannel summary' output.
    """
    port_channels = {}

    for intf in interfaces:
        ch_grp = intf.get("channel_group", "")
        if ch_grp:
            pc_id = ch_grp
            if pc_id not in port_channels:
                port_channels[pc_id] = {"id": pc_id, "members": [], "protocol": ""}
            port_channels[pc_id]["members"].append(intf["name"])

    ec_blocks = re.findall(
        r"(\d+)\s+(Po\d+)\S*\s+(\S+)\s+(\S+)\s+(.*)",
        raw_text
    )
    for group_id, po_name, proto_type, protocol, ports_str in ec_blocks:
        if group_id not in port_channels:
            port_channels[group_id] = {"id": group_id, "members": [], "protocol": ""}
        port_channels[group_id]["protocol"] = protocol
        member_ports = re.findall(r"([A-Za-z]+\d+[\d/]*)\([A-Za-z]+\)", ports_str)
        if member_ports:
            for mp in member_ports:
                if mp not in port_channels[group_id]["members"]:
                    port_channels[group_id]["members"].append(mp)

    lacp_match = re.findall(
        r"interface\s+(\S+).*?channel-group\s+(\d+)\s+mode\s+(\S+)",
        raw_text, re.DOTALL
    )
    for intf_name, ch_id, mode in lacp_match:
        if ch_id in port_channels:
            if mode in ("active", "passive"):
                port_channels[ch_id]["protocol"] = "LACP"
            elif mode in ("on", "desirable", "auto"):
                port_channels[ch_id]["protocol"] = "PAGP" if mode in ("desirable", "auto") else "Static"

    return list(port_channels.values())


def _parse_vpc(raw_text: str, interfaces: list[dict]) -> dict | None:
    """
    Extract VPC (Virtual Port-Channel) configuration for NX-OS devices.
    """
    vpc_domain = re.search(r"vpc\s+domain\s+(\d+)", raw_text, re.IGNORECASE)
    if not vpc_domain:
        return None

    vpc = {
        "domain": vpc_domain.group(1),
        "role_priority": "",
        "peer_keepalive": "",
        "peer_link": "",
        "vpcs": [],
    }

    role_match = re.search(r"role\s+priority\s+(\d+)", raw_text)
    if role_match:
        vpc["role_priority"] = role_match.group(1)

    keepalive = re.search(r"peer-keepalive\s+destination\s+(\S+)", raw_text)
    if keepalive:
        vpc["peer_keepalive"] = keepalive.group(1)

    for intf in interfaces:
        if intf.get("vpc_peer_link"):
            vpc["peer_link"] = intf["name"]
        if intf.get("vpc"):
            vpc["vpcs"].append({
                "id": intf["vpc"],
                "interface": intf["name"],
            })

    return vpc
