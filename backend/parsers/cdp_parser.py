"""
Parser for Cisco CDP neighbor output.
Handles 'show cdp neighbors' and 'show cdp neighbors detail' formats.
Covers IOS, IOS-XE, and NX-OS variations.

Only extracts: Device ID, local interface, remote interface (Port ID),
platform, capabilities, and management IP per neighbor entry.
"""
import re
from typing import Optional


def parse_cdp_neighbors(raw_text: str, local_hostname: Optional[str] = None) -> list[dict]:
    """
    Parse CDP neighbor information from command output.
    Returns a list of neighbor entries with local/remote device and interface info.
    """
    if re.search(r"Device ID:", raw_text, re.IGNORECASE):
        detail_entries = _parse_cdp_detail(raw_text, local_hostname)
        if detail_entries:
            return detail_entries

    return _parse_cdp_brief(raw_text, local_hostname)


def _parse_cdp_detail(raw_text: str, local_hostname: Optional[str]) -> list[dict]:
    """
    Parse 'show cdp neighbors detail' output.
    Splits on separator lines (---) or on repeated 'Device ID:' lines.
    Each block must have Device ID + Interface + Port ID to be valid.
    """
    neighbors = []

    blocks = re.split(r"^-{10,}\s*$", raw_text, flags=re.MULTILINE)

    if len(blocks) < 2:
        blocks = re.split(r"(?=^Device ID:)", raw_text, flags=re.MULTILINE)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        device_match = re.search(r"Device ID:\s*(\S+)", block, re.IGNORECASE)
        if not device_match:
            continue

        remote_device = device_match.group(1).strip()
        remote_device = re.split(r"[.(]", remote_device)[0].strip()
        if not remote_device or len(remote_device) < 2:
            continue

        local_intf_match = re.search(
            r"Interface:\s*(\S+?)(?:\s*,|\s*$|\n)", block, re.IGNORECASE | re.MULTILINE
        )
        remote_intf_match = re.search(
            r"Port ID\s*\(outgoing port\):\s*(\S+)", block, re.IGNORECASE
        )

        if not local_intf_match and not remote_intf_match:
            continue

        platform_match = re.search(
            r"Platform:\s*(.+?)(?:,\s*Capabilities|$)", block, re.IGNORECASE
        )
        capabilities_match = re.search(
            r"Capabilities:\s*(.+?)(?:\n|$)", block, re.IGNORECASE
        )
        ip_match = re.search(
            r"(?:IP(?:v4)?\s*[Aa]ddress|Entry address)\S*\s*:?\s*(\d+\.\d+\.\d+\.\d+)",
            block, re.IGNORECASE
        )

        neighbor = {
            "remote_device": remote_device,
            "local_interface": local_intf_match.group(1).strip() if local_intf_match else "",
            "remote_interface": remote_intf_match.group(1).strip() if remote_intf_match else "",
            "platform": platform_match.group(1).strip() if platform_match else "",
            "capabilities": capabilities_match.group(1).strip() if capabilities_match else "",
            "mgmt_ip": ip_match.group(1) if ip_match else "",
            "protocol": "CDP",
        }

        if local_hostname:
            neighbor["local_device"] = local_hostname

        neighbors.append(neighbor)

    return neighbors


def _parse_cdp_brief(raw_text: str, local_hostname: Optional[str]) -> list[dict]:
    """Parse 'show cdp neighbors' brief output (table format)."""
    neighbors = []
    lines = raw_text.strip().splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        if re.match(r"Device\s+ID", line, re.IGNORECASE):
            header_idx = i
            break

    if header_idx is None:
        return neighbors

    for line in lines[header_idx + 1:]:
        if not line.strip() or line.startswith("Total"):
            continue

        parts = line.split()
        if len(parts) < 6:
            continue

        remote_device = re.split(r"[.(]", parts[0])[0].strip()
        if not remote_device or len(remote_device) < 2:
            continue

        local_intf = _reconstruct_interface(parts[1], parts[2] if len(parts) > 2 else "")
        remote_intf = _reconstruct_interface(parts[-2], parts[-1])

        neighbor = {
            "remote_device": remote_device,
            "local_interface": local_intf,
            "remote_interface": remote_intf,
            "platform": "",
            "capabilities": "",
            "mgmt_ip": "",
            "protocol": "CDP",
        }

        if local_hostname:
            neighbor["local_device"] = local_hostname

        neighbors.append(neighbor)

    return neighbors


def _reconstruct_interface(type_part: str, number_part: str) -> str:
    """Reconstruct interface name from split columns."""
    intf_prefixes = [
        "Gig", "Ten", "Fas", "Eth", "Ser", "Twe", "Hun", "For",
        "mgmt", "Mgmt", "Vla", "Por", "Po", "Loo",
    ]
    if any(type_part.startswith(p) for p in intf_prefixes):
        if number_part and number_part[0].isdigit():
            return f"{type_part}{number_part}"
        return type_part
    return f"{type_part}{number_part}" if number_part else type_part
