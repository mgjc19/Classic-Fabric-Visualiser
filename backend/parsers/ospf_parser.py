"""
OSPF Parser - extracts OSPF topology information from:
  - show ip ospf / show ospf overview
  - show ip ospf neighbor / show ospf neighbor
  - show ip ospf interface / show ospf interface brief
  - show running-config (router ospf section)
Supports Cisco IOS/IOS-XE, NX-OS, Arista, Juniper, and generic formats.
"""
import re
from typing import Optional


def parse_ospf_overview(raw_text: str, local_hostname: Optional[str] = None) -> dict:
    """
    Parse 'show ip ospf' or 'show ospf overview' output.
    Returns process ID, router-id, areas, and SPF stats.
    """
    result = {
        "process_id": "",
        "router_id": "",
        "local_hostname": local_hostname or "",
        "areas": [],
        "reference_bandwidth": "",
        "spf_delay": "",
        "spf_hold": "",
    }

    proc_m = re.search(
        r"(?:Routing Process|OSPF process)\s+[\"']?ospf[\"']?\s+(\d+)|"
        r"Routing Process\s+(\d+)|"
        r"OSPF Router with ID\s+\S+\s+\(Process ID\s+(\d+)\)",
        raw_text, re.IGNORECASE
    )
    if proc_m:
        result["process_id"] = proc_m.group(1) or proc_m.group(2) or proc_m.group(3)

    rid_m = re.search(
        r"Router\s+ID\s+(\d+\.\d+\.\d+\.\d+)|"
        r"OSPF Router with ID\s+(\d+\.\d+\.\d+\.\d+)",
        raw_text, re.IGNORECASE
    )
    if rid_m:
        result["router_id"] = rid_m.group(1) or rid_m.group(2)

    area_matches = re.finditer(
        r"Area\s+(?:BACKBONE\()?(\d+(?:\.\d+\.\d+\.\d+)?)\)?\s+"
        r"(?:.*?Number of interfaces[^:]*:\s*(\d+))?",
        raw_text, re.IGNORECASE | re.DOTALL
    )
    seen_areas = set()
    for am in area_matches:
        area_id = am.group(1)
        if area_id in seen_areas:
            continue
        seen_areas.add(area_id)
        intf_count = am.group(2) if am.group(2) else ""
        area_type = "backbone" if area_id in ("0", "0.0.0.0") else "normal"

        stub_m = re.search(
            r"Area\s+" + re.escape(area_id) + r".*?(?:is a\s+)?(stub|nssa|totally\s+stub)",
            raw_text, re.IGNORECASE | re.DOTALL
        )
        if stub_m:
            area_type = stub_m.group(1).lower().replace(" ", "_")

        result["areas"].append({
            "area_id": area_id,
            "type": area_type,
            "interface_count": intf_count,
        })

    if not result["areas"]:
        simple_areas = re.findall(r"Area\s+(\d+(?:\.\d+\.\d+\.\d+)?)", raw_text)
        for a in set(simple_areas):
            result["areas"].append({
                "area_id": a,
                "type": "backbone" if a in ("0", "0.0.0.0") else "normal",
                "interface_count": "",
            })

    bw_m = re.search(r"Reference bandwidth\s+(?:is\s+)?(\d+)\s*(\w+)?", raw_text, re.IGNORECASE)
    if bw_m:
        result["reference_bandwidth"] = bw_m.group(1) + (" " + bw_m.group(2) if bw_m.group(2) else "")

    return result


def parse_ospf_neighbors(raw_text: str, local_hostname: Optional[str] = None) -> list[dict]:
    """
    Parse 'show ip ospf neighbor' output.
    Returns list of OSPF neighbors with state, priority, interface, etc.
    """
    neighbors = []

    header_m = re.search(
        r"Neighbor\s+ID\s+.*?(?:Interface|Address)",
        raw_text, re.IGNORECASE
    )

    if header_m:
        lines_after = raw_text[header_m.end():].strip().split("\n")
        for line in lines_after:
            line = line.strip()
            if not line or line.startswith(("Total", "---", "Number")):
                continue

            parts = line.split()
            if len(parts) < 4:
                continue

            neighbor_rid = parts[0]
            if not re.match(r"\d+\.\d+\.\d+\.\d+", neighbor_rid):
                continue

            neighbor = {
                "router_id": neighbor_rid,
                "state": "",
                "priority": "",
                "address": "",
                "interface": "",
                "dead_time": "",
                "area": "",
            }

            for p in parts[1:]:
                p_upper = p.upper().rstrip(",").rstrip("/")
                if p_upper in ("FULL", "2WAY", "INIT", "DOWN", "ATTEMPT",
                               "EXSTART", "EXCHANGE", "LOADING"):
                    neighbor["state"] = p_upper
                    break
                if "/" in p_upper and any(st in p_upper for st in
                    ["FULL", "2WAY", "INIT", "DOWN", "EXSTART", "EXCHANGE", "LOADING"]):
                    neighbor["state"] = p_upper
                    break

            for p in parts:
                if re.match(r"^\d+\.\d+\.\d+\.\d+$", p) and p != neighbor_rid:
                    if not neighbor["address"]:
                        neighbor["address"] = p

            for p in parts:
                if re.match(r"(?:Eth|Gi|Te|Fo|Hu|Vlan|Lo|Po|mgmt|xe-|ge-|et-|ae)", p, re.IGNORECASE):
                    neighbor["interface"] = p
                    break

            neighbors.append(neighbor)

    if not neighbors:
        neighbors = _parse_ospf_neighbors_nxos(raw_text)

    return neighbors


def _parse_ospf_neighbors_nxos(raw_text: str) -> list[dict]:
    """Parse NX-OS style OSPF neighbor output."""
    neighbors = []
    lines = raw_text.split("\n")
    current_area = ""

    for line in lines:
        area_m = re.match(r"\s*OSPF Process.*Area\s+(\S+)", line, re.IGNORECASE)
        if area_m:
            current_area = area_m.group(1)
            continue

        parts = line.strip().split()
        if len(parts) < 4:
            continue
        if not re.match(r"\d+\.\d+\.\d+\.\d+", parts[0]):
            continue

        neighbor = {
            "router_id": parts[0],
            "state": "",
            "priority": "",
            "address": "",
            "interface": "",
            "dead_time": "",
            "area": current_area,
        }

        for p in parts[1:]:
            p_upper = p.upper().rstrip(",").split("/")[0]
            if p_upper in ("FULL", "2WAY", "INIT", "DOWN", "EXSTART", "EXCHANGE", "LOADING"):
                neighbor["state"] = p.upper()
                break

        for p in parts:
            if re.match(r"(?:Eth|Gi|Te|Fo|Hu|Vlan|Lo|Po|xe-|ge-|et-)", p, re.IGNORECASE):
                neighbor["interface"] = p
                break

        for p in parts:
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", p) and p != parts[0]:
                if not neighbor["address"]:
                    neighbor["address"] = p

        neighbors.append(neighbor)

    return neighbors


def parse_ospf_interfaces(raw_text: str, local_hostname: Optional[str] = None) -> list[dict]:
    """
    Parse 'show ip ospf interface' or 'show ip ospf interface brief' output.
    Returns interface-to-area mappings with cost and network type.
    """
    interfaces = []

    brief_header = re.search(
        r"Interface\s+.*?Area\s+.*?Cost\s+.*?(?:State|Type)",
        raw_text, re.IGNORECASE
    )

    if brief_header:
        lines = raw_text[brief_header.end():].strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue

            intf = {
                "interface": parts[0],
                "area": "",
                "cost": "",
                "state": "",
                "network_type": "",
                "neighbors": 0,
            }

            for p in parts[1:]:
                if re.match(r"^\d+\.\d+\.\d+\.\d+$|^\d+$", p) and not intf["area"]:
                    intf["area"] = p
                elif p.isdigit() and not intf["cost"]:
                    intf["cost"] = p
                elif p.upper() in ("DR", "BDR", "DROTHER", "P2P", "LOOP", "DOWN", "WAITING"):
                    intf["state"] = p.upper()

            interfaces.append(intf)
    else:
        detail_blocks = re.split(r"(?=^\S+\s+is\s+(?:up|down))", raw_text, flags=re.MULTILINE)
        for block in detail_blocks:
            if not block.strip():
                continue

            intf_m = re.match(r"^(\S+)\s+is\s+(up|down)", block, re.IGNORECASE)
            if not intf_m:
                continue

            intf = {
                "interface": intf_m.group(1),
                "area": "",
                "cost": "",
                "state": intf_m.group(2).upper(),
                "network_type": "",
                "neighbors": 0,
            }

            area_m = re.search(r"Area\s+(\d+(?:\.\d+\.\d+\.\d+)?)", block, re.IGNORECASE)
            if area_m:
                intf["area"] = area_m.group(1)

            cost_m = re.search(r"Cost:\s*(\d+)", block, re.IGNORECASE)
            if cost_m:
                intf["cost"] = cost_m.group(1)

            net_m = re.search(r"Network Type\s+(\S+)", block, re.IGNORECASE)
            if net_m:
                intf["network_type"] = net_m.group(1)

            nbr_m = re.search(r"(?:Neighbor Count|Adjacent neighbor count).*?(\d+)", block, re.IGNORECASE)
            if nbr_m:
                intf["neighbors"] = int(nbr_m.group(1))

            interfaces.append(intf)

    return interfaces


def parse_ospf_from_config(raw_text: str) -> dict:
    """
    Extract OSPF configuration from running config.
    Pulls process-id, router-id, network statements, and area config.
    """
    result = {
        "process_id": "",
        "router_id": "",
        "networks": [],
        "passive_interfaces": [],
        "areas": [],
        "default_info": False,
    }

    ospf_block_match = re.search(
        r"^router ospf\s+(\S+)\n((?:(?!\nrouter\s|\n!).*\n)*)",
        raw_text, re.MULTILINE
    )
    if not ospf_block_match:
        return result

    result["process_id"] = ospf_block_match.group(1)
    ospf_config = ospf_block_match.group(2)

    rid_m = re.search(r"router-id\s+(\d+\.\d+\.\d+\.\d+)", ospf_config, re.IGNORECASE)
    if rid_m:
        result["router_id"] = rid_m.group(1)

    networks = re.findall(
        r"network\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+area\s+(\S+)",
        ospf_config, re.IGNORECASE
    )
    for net, wildcard, area in networks:
        result["networks"].append({
            "network": net,
            "wildcard": wildcard,
            "area": area,
        })

    passive = re.findall(r"passive-interface\s+(\S+)", ospf_config, re.IGNORECASE)
    result["passive_interfaces"] = passive

    if re.search(r"default-information originate", ospf_config, re.IGNORECASE):
        result["default_info"] = True

    area_configs = re.findall(
        r"area\s+(\S+)\s+(stub|nssa|authentication|range\s+\S+)",
        ospf_config, re.IGNORECASE
    )
    for area_id, area_prop in area_configs:
        result["areas"].append({"area_id": area_id, "property": area_prop.strip()})

    return result
