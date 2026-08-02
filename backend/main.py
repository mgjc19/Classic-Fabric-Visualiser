"""
Classic Fabric Visualiser - Backend API
Handles file uploads, parsing, and topology construction.
"""
import io
import json
import os
import re
import zipfile
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.responses import Response, StreamingResponse, JSONResponse

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from parsers import (
    parse_cdp_neighbors,
    parse_lldp_neighbors,
    parse_interface_brief,
    parse_interface_description,
    parse_interface_status,
    parse_platform_detail,
    parse_running_config,
    extract_hostname,
    parse_bgp_summary,
    parse_bgp_neighbors_detail,
    parse_bgp_from_config,
    parse_ospf_overview,
    parse_ospf_neighbors,
    parse_ospf_interfaces,
    parse_ospf_from_config,
)
from parsers.interface_parser import infer_neighbors_from_descriptions
from topology import TopologyBuilder
from topology.routing_builder import RoutingTopologyBuilder
from migration import MigrationClassifier, UnderlayDesigner

app = FastAPI(
    title="Classic Fabric Visualiser",
    description="Visualise traditional ethernet fabric topologies",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
UPLOAD_MAX_SIZE = 100 * 1024 * 1024  # 100MB per file


@app.post("/api/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """
    Upload device output files and build topology.
    Accepts .txt, .log, .zip, .xlsx files.
    """
    all_texts: list[tuple[str, str]] = []

    for upload_file in files:
        if not upload_file.filename:
            continue

        content = await upload_file.read()
        if len(content) > UPLOAD_MAX_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File {upload_file.filename} exceeds 100MB limit"
            )

        filename_lower = upload_file.filename.lower()

        if filename_lower.endswith(".zip"):
            extracted = _extract_zip(content)
            all_texts.extend(extracted)
        elif filename_lower.endswith((".xlsx", ".xls")):
            extracted = _extract_excel(content)
            all_texts.extend(extracted)
        else:
            text = content.decode("utf-8", errors="replace")
            all_texts.append((upload_file.filename, text))

    if not all_texts:
        raise HTTPException(status_code=400, detail="No valid files found")

    topology = _process_files(all_texts)
    return topology


@app.post("/api/upload-stream")
async def upload_files_stream(files: list[UploadFile] = File(...)):
    """
    Upload files and stream parsing progress as Server-Sent Events.
    The final event contains the complete topology JSON.
    """
    all_texts: list[tuple[str, str]] = []

    for upload_file in files:
        if not upload_file.filename:
            continue

        content = await upload_file.read()
        if len(content) > UPLOAD_MAX_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File {upload_file.filename} exceeds 100MB limit"
            )

        filename_lower = upload_file.filename.lower()

        if filename_lower.endswith(".zip"):
            extracted = _extract_zip(content)
            all_texts.extend(extracted)
        elif filename_lower.endswith((".xlsx", ".xls")):
            extracted = _extract_excel(content)
            all_texts.extend(extracted)
        else:
            text = content.decode("utf-8", errors="replace")
            all_texts.append((upload_file.filename, text))

    if not all_texts:
        raise HTTPException(status_code=400, detail="No valid files found")

    async def event_generator():
        import asyncio

        def emit(action: str, message: str):
            payload = json.dumps({"action": action, "message": message})
            return f"data: {payload}\n\n"

        yield emit("upload", f"Processing {len(all_texts)} file(s) from upload...")

        builder = TopologyBuilder()
        device_files: dict[str, list[str]] = {}

        for filename, text in all_texts:
            yield emit("file", f"Reading {filename}")
            await asyncio.sleep(0)

            hostname = _detect_hostname(filename, text)
            if hostname:
                if hostname not in device_files:
                    device_files[hostname] = []
                    yield emit("device", f"Discovered device: {hostname}")
                device_files[hostname].append(text)
            else:
                sections = _split_multi_device_output(text)
                if sections:
                    for host, section_text in sections:
                        if host not in device_files:
                            device_files[host] = []
                            yield emit("device", f"Discovered device: {host}")
                        device_files[host].append(section_text)
                else:
                    fallback_name = Path(filename).stem
                    if fallback_name not in device_files:
                        device_files[fallback_name] = []
                        yield emit("device", f"Discovered device: {fallback_name}")
                    device_files[fallback_name].append(text)

        yield emit("parse", f"Found {len(device_files)} devices. Parsing command outputs...")
        await asyncio.sleep(0)

        routing_builder = RoutingTopologyBuilder()
        device_count = 0
        total_devices = len(device_files)
        known_hostnames = set(device_files.keys())

        for hostname, texts in device_files.items():
            device_count += 1
            yield emit("parse", f"[{device_count}/{total_devices}] Parsing {hostname}...")
            await asyncio.sleep(0)

            combined_text = "\n".join(texts)
            commands_found = _parse_device_output(builder, hostname, combined_text, routing_builder, known_hostnames)
            if commands_found:
                yield emit("commands", f"  Found: {', '.join(commands_found)}")
                await asyncio.sleep(0)

        yield emit("parse", "Building topology graphs...")
        await asyncio.sleep(0)

        topology = builder.build()
        topology["devices_parsed"] = list(device_files.keys())

        routing_builder.set_physical_devices(builder.devices)
        bgp_topology = routing_builder.build_bgp_topology()
        ospf_topology = routing_builder.build_ospf_topology()

        topology["bgp"] = bgp_topology
        topology["ospf"] = ospf_topology

        topology["migration"] = _build_migration_data(topology)

        stats = topology["stats"]
        bgp_count = bgp_topology["stats"]["total_peers"]
        ospf_count = ospf_topology["stats"]["total_adjacencies"]
        summary = f"Topology ready: {stats['total_devices']} devices, {stats['total_links']} links"
        if bgp_count > 0:
            summary += f", {bgp_count} BGP peers"
        if ospf_count > 0:
            summary += f", {ospf_count} OSPF adjacencies"
        yield emit("done", summary)

        yield f"event: topology\ndata: {json.dumps(topology)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


if FRONTEND_DIR.exists():
    from starlette.responses import Response

    @app.get("/")
    async def serve_index():
        content = (FRONTEND_DIR / "index.html").read_bytes()
        return Response(content, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/test")
    async def serve_test():
        content = (FRONTEND_DIR / "test.html").read_bytes()
        return Response(content, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/static/{filepath:path}")
    async def serve_static(filepath: str):
        file_path = FRONTEND_DIR / filepath
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404)
        content = file_path.read_bytes()
        media_types = {
            ".js": "application/javascript",
            ".css": "text/css",
            ".html": "text/html",
            ".png": "image/png",
            ".svg": "image/svg+xml",
        }
        ext = file_path.suffix.lower()
        mt = media_types.get(ext, "application/octet-stream")
        return Response(content, media_type=mt, headers={"Cache-Control": "no-store"})


def _extract_zip(content: bytes) -> list[tuple[str, str]]:
    """Extract text files from a ZIP archive."""
    texts = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.startswith("__MACOSX") or name.startswith("."):
                    continue
                name_lower = name.lower()
                if name_lower.endswith((".txt", ".log", ".cfg", ".conf", "")):
                    try:
                        data = zf.read(name)
                        if len(data) > UPLOAD_MAX_SIZE:
                            continue
                        text = data.decode("utf-8", errors="replace")
                        if text.strip():
                            texts.append((name, text))
                    except (KeyError, RuntimeError):
                        continue
    except zipfile.BadZipFile:
        pass
    return texts


def _extract_excel(content: bytes) -> list[tuple[str, str]]:
    """Extract text content from Excel files (each sheet as a separate device)."""
    texts = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            lines = []
            for row in ws.iter_rows(values_only=True):
                row_text = "\t".join(str(cell) if cell is not None else "" for cell in row)
                if row_text.strip():
                    lines.append(row_text)
            if lines:
                texts.append((sheet_name, "\n".join(lines)))
        wb.close()
    except Exception:
        pass
    return texts


def _process_files(file_texts: list[tuple[str, str]]) -> dict:
    """
    Process all uploaded file contents and build the topology.
    Auto-detects command outputs and parses accordingly.
    """
    builder = TopologyBuilder()
    device_files: dict[str, list[str]] = {}
    parse_log: list[dict] = []

    for filename, text in file_texts:
        parse_log.append({"action": "file", "message": f"Reading {filename}"})
        hostname = _detect_hostname(filename, text)
        if hostname:
            if hostname not in device_files:
                device_files[hostname] = []
                parse_log.append({"action": "device", "message": f"Discovered device: {hostname}"})
            device_files[hostname].append(text)
        else:
            sections = _split_multi_device_output(text)
            if sections:
                for host, section_text in sections:
                    if host not in device_files:
                        device_files[host] = []
                        parse_log.append({"action": "device", "message": f"Discovered device: {host}"})
                    device_files[host].append(section_text)
            else:
                fallback_name = Path(filename).stem
                if fallback_name not in device_files:
                    device_files[fallback_name] = []
                    parse_log.append({"action": "device", "message": f"Discovered device: {fallback_name}"})
                device_files[fallback_name].append(text)

    routing_builder2 = RoutingTopologyBuilder()
    known_hostnames = set(device_files.keys())
    for hostname, texts in device_files.items():
        parse_log.append({"action": "parse", "message": f"Parsing {hostname}..."})
        combined_text = "\n".join(texts)
        commands_found = _parse_device_output(builder, hostname, combined_text, routing_builder2, known_hostnames)
        if commands_found:
            parse_log.append({"action": "commands", "message": f"  Found: {', '.join(commands_found)}"})

    topology = builder.build()
    topology["devices_parsed"] = list(device_files.keys())
    topology["parse_log"] = parse_log

    routing_builder2.set_physical_devices(builder.devices)
    topology["bgp"] = routing_builder2.build_bgp_topology()
    topology["ospf"] = routing_builder2.build_ospf_topology()

    topology["migration"] = _build_migration_data(topology)

    parse_log.append({"action": "done", "message": f"Built topology: {topology['stats']['total_devices']} devices, {topology['stats']['total_links']} links"})

    return topology


def _build_migration_data(topology: dict) -> dict:
    """Run migration classification and initial underlay design."""
    try:
        classifier = MigrationClassifier(topology)
        classifications = classifier.classify_all()
        phases = classifier.suggest_phases(classifications)
        vni_mapping = classifier.generate_vni_mapping()

        nodes_map = {n["data"]["id"]: n["data"] for n in topology.get("nodes", [])}
        adjacency: dict[str, list[dict]] = {}
        for edge in topology.get("edges", []):
            src = edge["data"]["source"]
            tgt = edge["data"]["target"]
            adjacency.setdefault(src, []).append(edge["data"])
            adjacency.setdefault(tgt, []).append(edge["data"])

        designer = UnderlayDesigner(classifications, nodes_map, adjacency)
        underlay_design = designer.design(
            underlay_protocol="ospf",
            bgp_afs=["l2vpn_evpn"],
        )

        return {
            "classifications": classifications,
            "phases": phases,
            "vni_mapping": vni_mapping,
            "underlay_design": underlay_design,
        }
    except Exception:
        return {"classifications": {}, "phases": [], "vni_mapping": [], "underlay_design": {}}


_last_topology: dict = {}


@app.post("/api/redesign-underlay")
async def redesign_underlay(request: Request):
    """Re-compute underlay/overlay design with user-selected parameters."""
    body = await request.json()

    underlay_protocol = body.get("underlay_protocol", "ospf")
    bgp_afs = body.get("bgp_afs", ["l2vpn_evpn"])
    ospf_area = body.get("ospf_area", "0.0.0.0")
    spine_asn = int(body.get("spine_asn", 65000))
    leaf_asn_start = int(body.get("leaf_asn_start", 65001))
    overlay_asn = body.get("overlay_asn")
    if overlay_asn is not None:
        overlay_asn = int(overlay_asn)

    classifications = body.get("classifications", {})
    nodes = body.get("nodes", {})
    adjacency = body.get("adjacency", {})

    if not classifications:
        return JSONResponse({"error": "No classification data provided"}, status_code=400)

    designer = UnderlayDesigner(classifications, nodes, adjacency)
    result = designer.design(
        underlay_protocol=underlay_protocol,
        bgp_afs=bgp_afs,
        ospf_area=ospf_area,
        spine_asn=spine_asn,
        leaf_asn_start=leaf_asn_start,
        overlay_asn=overlay_asn,
    )
    return result


def _detect_hostname(filename: str, text: str) -> str:
    """Detect hostname from file content or filename."""
    hostname = extract_hostname(text)
    if hostname:
        return hostname

    stem = Path(filename).stem
    noise_words = (
        r"show|config|output|commands?|backup|running|startup|"
        r"cdp|lldp|neighbors?|detail|brief|interfaces?|status|"
        r"version|inventory|platform|ip|route|bgp|ospf|vlan|"
        r"description|etherchannel|port-?channel|spanning-?tree|"
        r"log|tech-?support|diag"
    )
    stem_clean = re.sub(
        r"[-_.]?(" + noise_words + r")[-_.]?", " ", stem, flags=re.IGNORECASE
    )
    stem_clean = stem_clean.strip(" -_.")
    stem_clean = re.sub(r"\s+", " ", stem_clean).strip()
    if stem_clean and len(stem_clean) >= 2 and not stem_clean.isdigit():
        return stem_clean

    return ""


def _split_multi_device_output(text: str) -> list[tuple[str, str]]:
    """
    Detect if a file contains outputs from multiple devices
    (e.g. collected via jump host or automation tool).
    """
    device_markers = re.findall(
        r"^[!=]{3,}\s*(\S+)\s*[!=]{3,}$|^#{3,}\s*(\S+)\s*#{3,}$|^---\s*(\S+)\s*---$",
        text, re.MULTILINE
    )

    if not device_markers:
        return []

    sections = []
    pattern = r"(?:^[!=]{3,}\s*(\S+)\s*[!=]{3,}$|^#{3,}\s*(\S+)\s*#{3,}$|^---\s*(\S+)\s*---$)"
    splits = re.split(pattern, text, flags=re.MULTILINE)

    current_host = ""
    for part in splits:
        if part is None:
            continue
        part = part.strip()
        if not part:
            continue
        if len(part) < 50 and re.match(r"^[\w.-]+$", part):
            current_host = part
        elif current_host:
            sections.append((current_host, part))

    return sections


def _parse_device_output(builder: TopologyBuilder, hostname: str, text: str,
                         routing_builder: RoutingTopologyBuilder = None,
                         known_hostnames: set = None) -> list[str]:
    """Parse all recognizable command outputs for a device. Returns list of commands found."""
    builder.add_device(hostname)

    sections = _identify_command_sections(text)
    commands_found = []

    all_neighbors = []
    has_cdp_lldp = False

    for section_type, section_text in sections:
        if section_type == "cdp":
            neighbors = parse_cdp_neighbors(section_text, hostname)
            all_neighbors.extend(neighbors)
            has_cdp_lldp = True
            commands_found.append("CDP neighbors")

        elif section_type == "lldp":
            neighbors = parse_lldp_neighbors(section_text, hostname)
            all_neighbors.extend(neighbors)
            has_cdp_lldp = True
            commands_found.append("LLDP neighbors")

        elif section_type == "interface_brief":
            interfaces = parse_interface_brief(section_text, hostname)
            builder.add_interfaces(hostname, interfaces)
            commands_found.append("interface brief")

        elif section_type == "interface_description":
            descriptions = parse_interface_description(section_text, hostname)
            if not has_cdp_lldp:
                inferred = infer_neighbors_from_descriptions(descriptions)
                inferred = _filter_inferred_by_known(inferred, known_hostnames)
                all_neighbors.extend(inferred)
            commands_found.append("interface description")

        elif section_type == "interface_status":
            statuses = parse_interface_status(section_text, hostname)
            if not has_cdp_lldp:
                inferred = infer_neighbors_from_descriptions(statuses)
                inferred = _filter_inferred_by_known(inferred, known_hostnames)
                all_neighbors.extend(inferred)
            commands_found.append("interface status")

        elif section_type == "platform":
            device_info = parse_platform_detail(section_text, hostname)
            builder.add_device(hostname, device_info)
            commands_found.append("platform/version")

        elif section_type == "running_config":
            config = parse_running_config(section_text)
            if config.get("hostname"):
                builder.add_device(config["hostname"])
            device_info = {
                "hostname": config.get("hostname", hostname),
                "config": config,
            }
            builder.add_device(hostname, device_info)
            commands_found.append("running-config")

            if routing_builder:
                bgp_cfg = parse_bgp_from_config(section_text)
                if bgp_cfg.get("local_asn"):
                    routing_builder.add_bgp_config(hostname, bgp_cfg)
                    commands_found.append("BGP (from config)")
                ospf_cfg = parse_ospf_from_config(section_text)
                if ospf_cfg.get("process_id"):
                    routing_builder.add_ospf_config(hostname, ospf_cfg)
                    commands_found.append("OSPF (from config)")

        elif section_type == "bgp_summary":
            if routing_builder:
                summary = parse_bgp_summary(section_text, hostname)
                routing_builder.add_bgp_summary(hostname, summary)
                commands_found.append("BGP summary")

        elif section_type == "bgp_neighbors":
            if routing_builder:
                peers = parse_bgp_neighbors_detail(section_text, hostname)
                routing_builder.add_bgp_neighbor_detail(hostname, peers)
                commands_found.append("BGP neighbors detail")

        elif section_type == "ospf_overview":
            if routing_builder:
                overview = parse_ospf_overview(section_text, hostname)
                routing_builder.add_ospf_overview(hostname, overview)
                commands_found.append("OSPF overview")

        elif section_type == "ospf_neighbors":
            if routing_builder:
                nbrs = parse_ospf_neighbors(section_text, hostname)
                routing_builder.add_ospf_neighbors(hostname, nbrs)
                commands_found.append("OSPF neighbors")

        elif section_type == "ospf_interfaces":
            if routing_builder:
                intfs = parse_ospf_interfaces(section_text, hostname)
                routing_builder.add_ospf_interfaces(hostname, intfs)
                commands_found.append("OSPF interfaces")

    if not sections:
        neighbors = parse_cdp_neighbors(text, hostname)
        if neighbors:
            all_neighbors.extend(neighbors)
            has_cdp_lldp = True
            commands_found.append("CDP neighbors")

        neighbors = parse_lldp_neighbors(text, hostname)
        if neighbors:
            all_neighbors.extend(neighbors)
            has_cdp_lldp = True
            commands_found.append("LLDP neighbors")

        if not has_cdp_lldp:
            descriptions = parse_interface_description(text, hostname)
            if descriptions:
                inferred = infer_neighbors_from_descriptions(descriptions)
                inferred = _filter_inferred_by_known(inferred, known_hostnames)
                all_neighbors.extend(inferred)
                commands_found.append("interface description (inferred)")

        device_info = parse_platform_detail(text, hostname)
        if device_info.get("model"):
            builder.add_device(hostname, device_info)
            commands_found.append("platform/version")

    if all_neighbors:
        builder.add_neighbors(all_neighbors)

    return commands_found


def _filter_inferred_by_known(inferred: list[dict], known_hostnames: set = None) -> list[dict]:
    """
    Filter inferred neighbors to only include those whose remote_device
    matches a known hostname from the uploaded file bundle.
    """
    if not known_hostnames or not inferred:
        return inferred

    known_lower = {h.lower() for h in known_hostnames}
    filtered = []
    for n in inferred:
        remote = n.get("remote_device", "").lower()
        if remote in known_lower:
            filtered.append(n)
        else:
            for kh in known_lower:
                if remote in kh or kh in remote:
                    filtered.append(n)
                    break
    return filtered


def _identify_command_sections(text: str) -> list[tuple[str, str]]:
    """
    Identify different command output sections within a file.
    Looks for 'show' command prompts or markers.
    """
    sections = []

    show_pattern = re.compile(
        r"^(\S+)[#>]\s*(show\s+.+)$",
        re.MULTILINE | re.IGNORECASE
    )

    matches = list(show_pattern.finditer(text))

    if not matches:
        section_type = _classify_text_content(text)
        if section_type:
            return [(section_type, text)]
        return []

    for i, match in enumerate(matches):
        command = match.group(2).lower().strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end]

        section_type = _classify_command(command)
        if section_type:
            sections.append((section_type, section_text))

    return sections


def _classify_command(command: str) -> str:
    """Classify a show command into a parser category."""
    cmd = command.lower()

    if "cdp" in cmd and "neighbor" in cmd:
        return "cdp"
    if "lldp" in cmd and "neighbor" in cmd:
        return "lldp"
    if "interface" in cmd and "brief" in cmd:
        return "interface_brief"
    if "interface" in cmd and "description" in cmd:
        return "interface_description"
    if "interface" in cmd and "status" in cmd:
        return "interface_status"

    if "bgp" in cmd and "summary" in cmd:
        return "bgp_summary"
    if "bgp" in cmd and "neighbor" in cmd:
        return "bgp_neighbors"
    if "ospf" in cmd and "neighbor" in cmd:
        return "ospf_neighbors"
    if "ospf" in cmd and "interface" in cmd:
        return "ospf_interfaces"
    if "ospf" in cmd and ("overview" in cmd or cmd.strip().endswith("ospf")):
        return "ospf_overview"

    if any(k in cmd for k in ["platform", "inventory", "version", "module"]):
        return "platform"
    if any(k in cmd for k in ["running", "run", "startup"]):
        return "running_config"
    if "etherchannel" in cmd or "port-channel" in cmd or "lacp" in cmd:
        return "running_config"
    if "vpc" in cmd:
        return "running_config"
    if "cdp" in cmd:
        return "cdp"
    if "lldp" in cmd:
        return "lldp"
    if "bgp" in cmd:
        return "bgp_summary"
    if "ospf" in cmd:
        return "ospf_overview"

    return ""


def _classify_text_content(text: str) -> str:
    """Classify text content by looking for characteristic patterns across vendors."""
    text_lower = text[:3000].lower()

    # CDP detection
    if "device id" in text_lower and ("local intrfce" in text_lower or "interface" in text_lower):
        if "cdp" in text_lower or "holdtme" in text_lower or "port id" in text_lower:
            return "cdp"

    # LLDP detection (Cisco, Arista, Juniper)
    if any(k in text_lower for k in ["chassis id", "system name", "lldp neighbor"]):
        if any(k in text_lower for k in ["lldp", "port id", "port description", "system description"]):
            return "lldp"

    # BGP summary detection
    if re.search(r"bgp\s+router\s+identifier", text_lower):
        if re.search(r"neighbor\s+v\s+as", text_lower):
            return "bgp_summary"
    if "bgp state" in text_lower and "remote as" in text_lower:
        return "bgp_neighbors"

    # OSPF detection
    if re.search(r"ospf\s+router\s+with\s+id|ospf\s+process|routing process", text_lower):
        if re.search(r"neighbor\s+id", text_lower):
            return "ospf_neighbors"
        return "ospf_overview"
    if re.search(r"neighbor\s+id\s+.*?(?:state|pri)", text_lower) and "ospf" in text_lower:
        return "ospf_neighbors"

    # Interface brief (IOS/NX-OS/Arista)
    if re.search(r"interface\s+ip.address\s+ok\?", text_lower):
        return "interface_brief"
    if re.search(r"interface\s+ip\s+address\s+status", text_lower):
        return "interface_brief"

    # Interface description
    if "description" in text_lower and re.search(r"interface\s+status\s+protocol", text_lower):
        return "interface_description"

    # Interface status (NX-OS / IOS)
    if re.search(r"port\s+name\s+status\s+vlan", text_lower):
        return "interface_status"

    # Running config detection (multi-vendor)
    if "hostname" in text_lower and "interface" in text_lower and "!" in text:
        return "running_config"
    if "switchname" in text_lower and "interface" in text_lower:
        return "running_config"
    # Juniper set-style config
    if "set system host-name" in text_lower or "set interfaces" in text_lower:
        return "running_config"

    # Platform/version
    if any(k in text_lower for k in [
        "pid:", "serial number", "model number", "uptime is",
        "system version", "eos version", "junos", "pan-os",
        "fortigate", "big-ip", "software image version"
    ]):
        return "platform"

    return ""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
