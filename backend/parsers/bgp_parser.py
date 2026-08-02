"""
BGP Parser - extracts BGP peering information from:
  - show ip bgp summary / show bgp summary
  - show ip bgp neighbors / show bgp neighbors
  - show running-config (router bgp section)
Supports Cisco IOS/IOS-XE, NX-OS, Arista, Juniper, and generic formats.
"""
import re
from typing import Optional


def parse_bgp_summary(raw_text: str, local_hostname: Optional[str] = None) -> dict:
    """
    Parse 'show ip bgp summary' or 'show bgp summary' output.
    Returns local ASN, router-id, and list of peers with state info.
    """
    result = {
        "local_asn": "",
        "router_id": "",
        "local_hostname": local_hostname or "",
        "peers": [],
    }

    asn_match = re.search(
        r"(?:local\s+AS\s+number|BGP\s+router\s+identifier\s+\S+,\s+local\s+AS\s+number)\s+(\d+)",
        raw_text, re.IGNORECASE
    )
    if not asn_match:
        asn_match = re.search(r"router bgp\s+(\d+)", raw_text, re.IGNORECASE)
    if asn_match:
        result["local_asn"] = asn_match.group(1)

    rid_match = re.search(
        r"BGP\s+router\s+identifier\s+(\d+\.\d+\.\d+\.\d+)", raw_text, re.IGNORECASE
    )
    if rid_match:
        result["router_id"] = rid_match.group(1)

    header_match = re.search(
        r"Neighbor\s+V\s+AS\s+.*?(?:St/PfxRcd|State/PfxRcd|State|PfxRcd)",
        raw_text, re.IGNORECASE
    )

    if header_match:
        lines_after = raw_text[header_match.end():].strip().split("\n")
        for line in lines_after:
            line = line.strip()
            if not line or line.startswith(("Total", "For address", "---")):
                continue

            parts = line.split()
            if len(parts) < 3:
                continue

            neighbor_ip = parts[0]
            if not re.match(r"\d+\.\d+\.\d+\.\d+|[\da-fA-F:]+", neighbor_ip):
                continue

            peer = {
                "neighbor_ip": neighbor_ip,
                "remote_asn": "",
                "state": "",
                "prefixes_received": 0,
                "uptime": "",
                "description": "",
            }

            for i, p in enumerate(parts[1:], 1):
                if p.isdigit() and not peer["remote_asn"] and i <= 4:
                    if i >= 2:
                        peer["remote_asn"] = p
                        break

            if not peer["remote_asn"]:
                for p in parts[1:5]:
                    if p.isdigit() and int(p) > 0:
                        peer["remote_asn"] = p
                        break

            last_col = parts[-1] if parts else ""
            if last_col.isdigit():
                peer["prefixes_received"] = int(last_col)
                peer["state"] = "Established"
            elif last_col in ("Idle", "Connect", "Active", "OpenSent", "OpenConfirm",
                              "Idle(Admin)", "Idle(NoIf)", "Idle(PfxCt)"):
                peer["state"] = last_col
            elif re.match(r"^\d+$", last_col):
                peer["prefixes_received"] = int(last_col)
                peer["state"] = "Established"
            else:
                peer["state"] = last_col

            if len(parts) >= 9:
                peer["uptime"] = parts[-2] if not parts[-2].isdigit() else ""

            result["peers"].append(peer)

    if not result["peers"]:
        result["peers"] = _parse_bgp_summary_nxos(raw_text)

    return result


def _parse_bgp_summary_nxos(raw_text: str) -> list[dict]:
    """Parse NX-OS style BGP summary with different column layout."""
    peers = []
    lines = raw_text.split("\n")
    in_peer_section = False

    for line in lines:
        if re.match(r"Neighbor\s+V\s+AS", line, re.IGNORECASE):
            in_peer_section = True
            continue
        if in_peer_section:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            if not re.match(r"\d+\.\d+\.\d+\.\d+", parts[0]):
                continue

            peer = {
                "neighbor_ip": parts[0],
                "remote_asn": "",
                "state": "",
                "prefixes_received": 0,
                "uptime": "",
                "description": "",
            }

            for p in parts[1:5]:
                if p.isdigit() and int(p) > 0:
                    peer["remote_asn"] = p
                    break

            last = parts[-1]
            if last.isdigit():
                peer["prefixes_received"] = int(last)
                peer["state"] = "Established"
            else:
                peer["state"] = last

            peers.append(peer)

    return peers


def parse_bgp_neighbors_detail(raw_text: str, local_hostname: Optional[str] = None) -> list[dict]:
    """
    Parse 'show ip bgp neighbors' or 'show bgp neighbors' detail output.
    Returns enriched peer information.
    """
    peers = []

    blocks = re.split(
        r"BGP\s+neighbor\s+is\s+(\d+\.\d+\.\d+\.\d+)",
        raw_text, flags=re.IGNORECASE
    )

    for i in range(1, len(blocks), 2):
        neighbor_ip = blocks[i]
        block = blocks[i + 1] if i + 1 < len(blocks) else ""

        peer = {
            "neighbor_ip": neighbor_ip,
            "remote_asn": "",
            "state": "",
            "router_id": "",
            "description": "",
            "uptime": "",
            "prefixes_received": 0,
            "local_interface": "",
            "peering_type": "",
            "hold_time": "",
            "keepalive": "",
            "address_families": [],
        }

        asn_m = re.search(r"remote AS\s+(\d+)", block, re.IGNORECASE)
        if asn_m:
            peer["remote_asn"] = asn_m.group(1)

        state_m = re.search(r"BGP\s+state\s*=\s*(\w+)", block, re.IGNORECASE)
        if state_m:
            peer["state"] = state_m.group(1)

        rid_m = re.search(r"remote router ID\s+(\d+\.\d+\.\d+\.\d+)", block, re.IGNORECASE)
        if rid_m:
            peer["router_id"] = rid_m.group(1)

        desc_m = re.search(r"Description:\s*(.+)", block, re.IGNORECASE)
        if desc_m:
            peer["description"] = desc_m.group(1).strip()

        uptime_m = re.search(r"(?:up for|uptime)\s+(.+?)(?:\n|$)", block, re.IGNORECASE)
        if uptime_m:
            peer["uptime"] = uptime_m.group(1).strip()

        intf_m = re.search(r"(?:update source|source interface)\s+(\S+)", block, re.IGNORECASE)
        if intf_m:
            peer["local_interface"] = intf_m.group(1)

        if re.search(r"external link|EBGP|eBGP", block, re.IGNORECASE):
            peer["peering_type"] = "eBGP"
        elif re.search(r"internal link|IBGP|iBGP", block, re.IGNORECASE):
            peer["peering_type"] = "iBGP"

        hold_m = re.search(r"hold time\s+(?:is\s+)?(\d+)", block, re.IGNORECASE)
        if hold_m:
            peer["hold_time"] = hold_m.group(1)
        ka_m = re.search(r"keepalive\s+(?:interval\s+(?:is\s+)?)?(\d+)", block, re.IGNORECASE)
        if ka_m:
            peer["keepalive"] = ka_m.group(1)

        pfx_m = re.search(r"(\d+)\s+(?:accepted\s+)?prefixes", block, re.IGNORECASE)
        if pfx_m:
            peer["prefixes_received"] = int(pfx_m.group(1))

        af_matches = re.findall(
            r"(?:For address family|Address family):\s*(.+?)(?:\n|$)", block, re.IGNORECASE
        )
        peer["address_families"] = [af.strip() for af in af_matches]

        peers.append(peer)

    return peers


def parse_bgp_from_config(raw_text: str) -> dict:
    """
    Extract BGP configuration from running config.
    Pulls ASN, router-id, neighbors, networks, and address families.
    """
    result = {
        "local_asn": "",
        "router_id": "",
        "neighbors": [],
        "networks": [],
        "address_families": [],
    }

    bgp_block_match = re.search(
        r"^router bgp\s+(\d+)\n((?:(?!\nrouter\s|\n!).*\n)*)",
        raw_text, re.MULTILINE
    )
    if not bgp_block_match:
        return result

    result["local_asn"] = bgp_block_match.group(1)
    bgp_config = bgp_block_match.group(2)

    rid_m = re.search(r"router-id\s+(\d+\.\d+\.\d+\.\d+)", bgp_config, re.IGNORECASE)
    if rid_m:
        result["router_id"] = rid_m.group(1)

    neighbor_lines = re.findall(
        r"neighbor\s+(\d+\.\d+\.\d+\.\d+)\s+remote-as\s+(\d+)", bgp_config, re.IGNORECASE
    )
    seen = set()
    for ip, asn in neighbor_lines:
        if ip not in seen:
            seen.add(ip)
            desc_m = re.search(
                r"neighbor\s+" + re.escape(ip) + r"\s+description\s+(.+)",
                bgp_config, re.IGNORECASE
            )
            update_m = re.search(
                r"neighbor\s+" + re.escape(ip) + r"\s+update-source\s+(\S+)",
                bgp_config, re.IGNORECASE
            )
            result["neighbors"].append({
                "neighbor_ip": ip,
                "remote_asn": asn,
                "description": desc_m.group(1).strip() if desc_m else "",
                "update_source": update_m.group(1) if update_m else "",
                "peering_type": "iBGP" if asn == result["local_asn"] else "eBGP",
            })

    networks = re.findall(
        r"network\s+(\d+\.\d+\.\d+\.\d+)(?:\s+mask\s+(\S+)|/(\d+))?",
        bgp_config, re.IGNORECASE
    )
    for net, mask, prefix in networks:
        result["networks"].append({
            "network": net,
            "mask": mask or ("/" + prefix if prefix else ""),
        })

    af_blocks = re.findall(
        r"address-family\s+(\S+(?:\s+\S+)?)\n((?:(?!\n\s*exit-address-family|\n!).*\n)*)",
        bgp_config, re.IGNORECASE
    )
    for af_name, af_config in af_blocks:
        af_neighbors = re.findall(
            r"neighbor\s+(\d+\.\d+\.\d+\.\d+)\s+activate", af_config, re.IGNORECASE
        )
        result["address_families"].append({
            "name": af_name.strip(),
            "activated_neighbors": af_neighbors,
        })

    return result
