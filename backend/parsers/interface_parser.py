"""
Parser for interface-related commands.
Handles 'show interface brief', 'show interface description', 'show interface status'.
Used as fallback when CDP/LLDP is disabled.
"""
import re
from typing import Optional


def parse_interface_brief(raw_text: str, local_hostname: Optional[str] = None) -> list[dict]:
    """
    Parse 'show ip interface brief' or 'show interface brief' output.
    Returns list of interface entries with IP, status, and protocol.
    """
    interfaces = []
    lines = raw_text.strip().splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        if re.match(r"Interface\s+IP-Address|Interface\s+Status", line, re.IGNORECASE):
            header_idx = i
            break

    if header_idx is None:
        return interfaces

    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue

        parts = line.split()
        if len(parts) < 4:
            continue

        intf_name = parts[0]
        ip_addr = parts[1] if len(parts) > 1 else ""

        status = "unknown"
        protocol = "unknown"

        if len(parts) >= 6:
            status = parts[4]
            protocol = parts[5]
        elif len(parts) >= 4:
            status = parts[2]
            protocol = parts[3]

        entry = {
            "interface": intf_name,
            "ip_address": ip_addr if ip_addr != "unassigned" else "",
            "status": status.lower(),
            "protocol": protocol.lower(),
        }

        if local_hostname:
            entry["device"] = local_hostname

        interfaces.append(entry)

    return interfaces


def parse_interface_description(raw_text: str, local_hostname: Optional[str] = None) -> list[dict]:
    """
    Parse 'show interface description' output.
    Returns list of interfaces with their descriptions.
    Descriptions often contain peer device/interface hints.
    """
    interfaces = []
    lines = raw_text.strip().splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        if re.match(r"Interface\s+Status\s+Protocol\s+Description", line, re.IGNORECASE):
            header_idx = i
            break
        if re.match(r"Port\s+Type\s+", line, re.IGNORECASE):
            header_idx = i
            break

    if header_idx is None:
        for i, line in enumerate(lines):
            if "Interface" in line and "Description" in line:
                header_idx = i
                break

    if header_idx is None:
        return interfaces

    header_line = lines[header_idx]
    desc_col = header_line.lower().find("description")
    if desc_col == -1:
        desc_col = 48

    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue

        parts = line.split()
        if not parts:
            continue

        intf_name = parts[0]
        description = ""

        if len(line) > desc_col:
            description = line[desc_col:].strip()
        elif len(parts) > 3:
            description = " ".join(parts[3:])

        status = parts[1].lower() if len(parts) > 1 else "unknown"
        protocol = parts[2].lower() if len(parts) > 2 else "unknown"

        entry = {
            "interface": intf_name,
            "status": status,
            "protocol": protocol,
            "description": description,
        }

        if local_hostname:
            entry["device"] = local_hostname

        interfaces.append(entry)

    return interfaces


def parse_interface_status(raw_text: str, local_hostname: Optional[str] = None) -> list[dict]:
    """
    Parse 'show interface status' output (typically NX-OS or IOS).
    Returns interface name, description, status, VLAN, duplex, speed, type.
    """
    interfaces = []
    lines = raw_text.strip().splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        if re.match(r"Port\s+Name\s+Status", line, re.IGNORECASE):
            header_idx = i
            break

    if header_idx is None:
        return interfaces

    for line in lines[header_idx + 1:]:
        if not line.strip() or line.startswith("-"):
            continue

        parts = line.split()
        if len(parts) < 4:
            continue

        intf_name = parts[0]

        status_keywords = ["connected", "notconnect", "disabled", "err-disabled",
                           "up", "down", "sfpAbsent", "xcvrAbsen"]
        status_idx = None
        for idx, part in enumerate(parts):
            if part.lower() in [s.lower() for s in status_keywords]:
                status_idx = idx
                break

        if status_idx is None:
            status_idx = 2

        name_parts = parts[1:status_idx] if status_idx > 1 else []
        description = " ".join(name_parts)
        status = parts[status_idx] if status_idx < len(parts) else "unknown"
        vlan = parts[status_idx + 1] if status_idx + 1 < len(parts) else ""

        entry = {
            "interface": intf_name,
            "description": description,
            "status": status.lower(),
            "vlan": vlan,
        }

        if local_hostname:
            entry["device"] = local_hostname

        interfaces.append(entry)

    return interfaces


def infer_neighbors_from_descriptions(descriptions: list[dict]) -> list[dict]:
    """
    Attempt to infer neighbor relationships from interface descriptions.
    Common patterns: 'To_SWITCH-A_Gi0/1', 'Link to Core-SW1 Eth1/1', 'UPLINK-SPINE01-E1/48'
    """
    inferred = []

    patterns = [
        re.compile(r"(?:to|link\s*to|uplink|downlink|connect(?:ed)?\s*to)\s*[-_]?\s*([\w][\w.-]+[\w])\s+([A-Za-z]+\d+[/\d.]*)", re.IGNORECASE),
        re.compile(r"(?:to|link\s*to|uplink|downlink|connect(?:ed)?\s*to)\s*[-_]?\s*([\w][\w.-]+[\w])", re.IGNORECASE),
        re.compile(r"([\w][\w-]*[\w])\s+([A-Za-z]{2,4}\d+[/\d.]*)\s*$", re.IGNORECASE),
        re.compile(r"[Uu]plink[-_\s]+([\w][\w.-]+[\w])[-_\s]+([A-Za-z]+\d+[/\d.]*)", re.IGNORECASE),
    ]

    for desc_entry in descriptions:
        description = desc_entry.get("description", "")
        if not description:
            continue

        status = desc_entry.get("status", "")
        if status in ["down", "disabled", "err-disabled"]:
            continue

        for pattern in patterns:
            match = pattern.search(description)
            if match:
                remote_device = match.group(1).strip().rstrip("-_")
                remote_intf = match.group(2).strip() if match.lastindex >= 2 else ""

                if len(remote_device) < 2:
                    continue

                neighbor = {
                    "remote_device": remote_device,
                    "local_interface": desc_entry.get("interface", ""),
                    "remote_interface": remote_intf,
                    "platform": "",
                    "capabilities": "",
                    "mgmt_ip": "",
                    "protocol": "INFERRED",
                    "confidence": "low",
                }

                if "device" in desc_entry:
                    neighbor["local_device"] = desc_entry["device"]

                inferred.append(neighbor)
                break

    return inferred
