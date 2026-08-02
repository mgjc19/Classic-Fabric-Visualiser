"""
Parser for LLDP neighbor output.
Handles 'show lldp neighbors' and 'show lldp neighbors detail' formats.
Multi-vendor: Cisco, Arista, Juniper, and any device outputting standard LLDP.

Only extracts: System Name/Chassis ID (as device name), local interface,
remote interface (Port ID/Port Description) per neighbor entry.
"""
import re
from typing import Optional


def parse_lldp_neighbors(raw_text: str, local_hostname: Optional[str] = None) -> list[dict]:
    """
    Parse LLDP neighbor information from command output.
    Returns a list of neighbor entries with local/remote device and interface info.
    """
    if re.search(r"Device ID:", raw_text, re.IGNORECASE) and not re.search(r"Chassis\s*[Ii][Dd]", raw_text, re.IGNORECASE):
        return []

    if re.search(r"Local Intf.*Chassis\s*[Ii]d|Chassis\s*[Ii][Dd]\s*:", raw_text, re.IGNORECASE):
        detail_entries = _parse_lldp_detail(raw_text, local_hostname)
        if detail_entries:
            return detail_entries

    juniper_neighbors = _parse_lldp_juniper(raw_text, local_hostname)
    if juniper_neighbors:
        return juniper_neighbors

    return _parse_lldp_brief(raw_text, local_hostname)


def _parse_lldp_detail(raw_text: str, local_hostname: Optional[str]) -> list[dict]:
    """
    Parse 'show lldp neighbors detail' output (Cisco/Arista/generic).
    Splits on separator lines or 'Local Intf:' markers.
    Each valid entry must have: a remote device name + at least one interface.
    """
    neighbors = []

    blocks = re.split(r"^-{10,}\s*$|^={10,}\s*$", raw_text, flags=re.MULTILINE)

    if len(blocks) < 2:
        blocks = re.split(r"(?=^Local Intf:)", raw_text, flags=re.MULTILINE | re.IGNORECASE)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        sys_name_match = re.search(
            r"System Name:\s*(\S+)", block, re.IGNORECASE
        )
        chassis_match = re.search(
            r"Chassis\s*[Ii][Dd]\s*:\s*(\S+)", block, re.IGNORECASE
        )

        remote_device = ""
        if sys_name_match:
            candidate = sys_name_match.group(1).strip()
            if candidate and candidate.lower() not in ("", "not", "n/a", "--"):
                remote_device = candidate
        if not remote_device and chassis_match:
            chassis_val = chassis_match.group(1).strip()
            if not re.match(r"^[0-9a-f]{2}([:.][0-9a-f]{2}){2,}", chassis_val, re.IGNORECASE):
                remote_device = chassis_val

        if not remote_device or len(remote_device) < 2:
            continue

        remote_device = re.split(r"[.(]", remote_device)[0].strip()

        local_intf_match = re.search(
            r"Local (?:Intf|Port\s*[Ii][Dd]|Interface)\s*:\s*(\S+)", block, re.IGNORECASE
        )

        remote_intf = ""
        port_id_match = re.search(r"Port id:\s*(\S+)", block, re.IGNORECASE)
        port_desc_match = re.search(r"Port Description:\s*(.+?)(?:\n|$)", block, re.IGNORECASE)

        if port_desc_match:
            pd = port_desc_match.group(1).strip()
            if pd and pd != "--" and pd.lower() != "not advertised" and len(pd) < 60:
                if re.match(r"(?:Eth|Gi|Te|Fo|Hu|Fa|Po|Vlan|mgmt|xe-|ge-|et-|ae)", pd, re.IGNORECASE):
                    remote_intf = pd

        if not remote_intf and port_id_match:
            rp = port_id_match.group(1).strip()
            if not re.match(r"^[0-9a-f]{2}([:.][0-9a-f]{2}){2,}", rp, re.IGNORECASE):
                remote_intf = rp

        if not local_intf_match and not remote_intf:
            continue

        capabilities_match = re.search(
            r"(?:System Capabilities|Enabled Capabilities)\s*:\s*(.+?)(?:\n|$)",
            block, re.IGNORECASE
        )
        mgmt_match = re.search(
            r"Management\s+[Aa]ddress(?:es)?\s*:?\s*\n?\s*(?:IP:?\s*)?(\d+\.\d+\.\d+\.\d+)",
            block, re.IGNORECASE
        )

        platform_match = re.search(
            r"System Description:\s*\n?\s*(.+?)(?:\n|$)", block, re.IGNORECASE
        )
        platform_str = ""
        if platform_match:
            raw_desc = platform_match.group(1).strip()
            if len(raw_desc) < 100:
                platform_str = raw_desc

        neighbor = {
            "remote_device": remote_device,
            "local_interface": local_intf_match.group(1).strip() if local_intf_match else "",
            "remote_interface": remote_intf,
            "platform": platform_str,
            "capabilities": capabilities_match.group(1).strip() if capabilities_match else "",
            "mgmt_ip": mgmt_match.group(1) if mgmt_match else "",
            "protocol": "LLDP",
        }

        if local_hostname:
            neighbor["local_device"] = local_hostname

        neighbors.append(neighbor)

    return neighbors


def _parse_lldp_juniper(raw_text: str, local_hostname: Optional[str]) -> list[dict]:
    """
    Parse Juniper-style 'show lldp neighbors' table:
    Local Interface   Parent Interface  Chassis Id          Port info  System Name
    """
    neighbors = []
    lines = raw_text.strip().splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        if re.match(r"Local\s+Interface\s+.*System\s*Name", line, re.IGNORECASE):
            header_idx = i
            break

    if header_idx is None:
        return []

    for line in lines[header_idx + 1:]:
        if not line.strip() or line.startswith("{"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue

        local_intf = parts[0]
        remote_device = parts[-1]
        remote_intf = parts[-2] if len(parts) >= 5 else ""

        if re.match(r"^[0-9a-f]{2}([:.][0-9a-f]{2}){2,}", remote_device, re.IGNORECASE):
            continue

        if not remote_device or len(remote_device) < 2:
            continue

        neighbor = {
            "remote_device": re.split(r"[.(]", remote_device)[0].strip(),
            "local_interface": local_intf,
            "remote_interface": remote_intf,
            "platform": "",
            "capabilities": "",
            "mgmt_ip": "",
            "protocol": "LLDP",
        }
        if local_hostname:
            neighbor["local_device"] = local_hostname
        neighbors.append(neighbor)

    return neighbors


def _parse_lldp_brief(raw_text: str, local_hostname: Optional[str]) -> list[dict]:
    """Parse 'show lldp neighbors' brief table output (Cisco/Arista)."""
    neighbors = []
    lines = raw_text.strip().splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        if re.match(r"Device\s+ID|Chassis\s+[Ii]d|System\s*Name|Neighbor", line, re.IGNORECASE):
            header_idx = i
            break

    if header_idx is None:
        return neighbors

    for line in lines[header_idx + 1:]:
        if not line.strip() or line.startswith("Total"):
            continue

        parts = line.split()
        if len(parts) < 3:
            continue

        remote_device = re.split(r"[.(]", parts[0])[0].strip()
        if re.match(r"^[0-9a-f]{2}([:.][0-9a-f]{2}){2,}", remote_device, re.IGNORECASE):
            continue
        if not remote_device or len(remote_device) < 2:
            continue

        local_intf = parts[1] if len(parts) > 1 else ""
        remote_intf = parts[-1] if len(parts) > 3 else ""

        neighbor = {
            "remote_device": remote_device,
            "local_interface": local_intf,
            "remote_interface": remote_intf,
            "platform": "",
            "capabilities": "",
            "mgmt_ip": "",
            "protocol": "LLDP",
        }

        if local_hostname:
            neighbor["local_device"] = local_hostname

        neighbors.append(neighbor)

    return neighbors
