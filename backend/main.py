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
from fabric_builder import BomParser, FabricModel, ConfigEngine, YamlExporter, NxosExporter, EndpointStore, TrafficEngine, FailoverSimulator

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


# =============================================================================
# Fabric Builder API (Phase 4)
# =============================================================================

_fabric_model: FabricModel | None = None
_fabric_configs: dict[str, str] = {}
_endpoint_store: EndpointStore = EndpointStore()
_traffic_engine: TrafficEngine | None = None
_failover_sim: FailoverSimulator | None = None


def _init_traffic_engine():
    """Initialize or reinitialize traffic engine when fabric model changes."""
    global _traffic_engine, _failover_sim
    if _fabric_model:
        _traffic_engine = TrafficEngine(_fabric_model, _endpoint_store)
        _failover_sim = FailoverSimulator(_fabric_model, _endpoint_store, _traffic_engine)


@app.post("/api/fabric/upload-bom")
async def upload_bom(file: UploadFile = File(...)):
    """Upload BOM (Excel/CSV) and parse into a fabric model.
    Supports hardware BOMs (PIDs/quantities) and fabric BOMs (hostnames/IPs).
    For hardware BOMs, returns the parsed inventory; call /api/fabric/build-from-hardware to generate devices.
    """
    global _fabric_model, _fabric_configs

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    content = await file.read()
    if len(content) > UPLOAD_MAX_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 100MB limit")

    parser = BomParser()
    try:
        bom_data = parser.parse(content, file.filename)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse BOM file: {str(e)}"
        )

    bom_type = bom_data.get("type", "hardware")

    if bom_type == "hardware":
        hardware = bom_data.get("hardware", {})
        if not hardware or not hardware.get("switches"):
            raise HTTPException(
                status_code=400,
                detail="No Nexus switches (N9K-*) found in BOM. Ensure your file contains Cisco PIDs."
            )
        return {
            "type": "hardware",
            "hardware": hardware,
            "metadata": bom_data["metadata"],
        }

    if not bom_data["devices"]:
        raise HTTPException(
            status_code=400,
            detail="No devices found in BOM file. Ensure your file has a column with device hostnames."
        )

    _fabric_model = FabricModel()
    _fabric_model.load_from_bom(bom_data)
    _fabric_model.add_default_overlay()
    _fabric_configs = {}
    _init_traffic_engine()

    return {"type": "fabric", **_fabric_model.to_dict()}


@app.post("/api/fabric/build-from-hardware")
async def build_from_hardware(request: Request):
    """Generate a fabric model from a parsed hardware BOM with user-specified naming/IP config.
    Supports multi-site: pass 'sites' array to split inventory across multiple sites.
    """
    global _fabric_model, _fabric_configs

    body = await request.json()
    hardware = body.get("hardware")
    sites = body.get("sites", [])
    config = body.get("config")

    print(f"[build-from-hardware] received {len(sites)} sites, config={'yes' if config else 'no'}")
    print(f"[build-from-hardware] site names = {[s.get('site','?') for s in sites]}")

    if not hardware or not hardware.get("switches"):
        raise HTTPException(status_code=400, detail="No hardware data provided")

    if not sites and config:
        sites = [config]

    if not sites:
        sites = [{"site": "DC1"}]

    print(f"[build-from-hardware] processing {len(sites)} sites after defaults")

    if len(sites) == 1:
        bom_data = BomParser.generate_devices_from_hardware(hardware, sites[0])
    else:
        all_devices = []
        all_links = []
        num_sites = len(sites)

        split_hardware_per_site = []
        for site_idx in range(num_sites):
            site_hw = {"switches": [], "sfps": hardware.get("sfps", []), "cables": hardware.get("cables", [])}
            for sw in hardware.get("switches", []):
                per_site_qty = sw["quantity"] // num_sites
                remainder = sw["quantity"] % num_sites
                qty = per_site_qty + (1 if site_idx < remainder else 0)
                if qty > 0:
                    site_sw = dict(sw)
                    site_sw["quantity"] = qty
                    site_hw["switches"].append(site_sw)
            split_hardware_per_site.append(site_hw)

        for site_idx, site_config in enumerate(sites):
            site_data = BomParser.generate_devices_from_hardware(
                split_hardware_per_site[site_idx], site_config
            )
            all_devices.extend(site_data["devices"])
            all_links.extend(site_data["links"])

        # Generate DCI/inter-site links between border gateways or border leaves
        # DCI peering uses BGP address-family IPv4 unicast between border gateway devices
        import uuid as _uuid
        dci_candidates_by_site: dict[str, list[dict]] = {}
        for dev in all_devices:
            site_name = dev.get("site", "")
            role = dev.get("role", "")
            if role in ("border_gateway", "border_leaf"):
                dci_candidates_by_site.setdefault(site_name, []).append(dev)

        # If no BGW/BLeaf exists, promote the last leaf device per site
        # to border_gateway role (IEEE standard: 1 BGW per site for multi-site VXLAN)
        if not any(dci_candidates_by_site.values()):
            leaves_by_site: dict[str, list[dict]] = {}
            for dev in all_devices:
                if dev.get("role") == "leaf":
                    leaves_by_site.setdefault(dev.get("site", ""), []).append(dev)
            for site_name, site_leaves in leaves_by_site.items():
                promoted = [site_leaves[-1]]
                for dev in promoted:
                    dev["role"] = "border_gateway"
                    old_hostname = dev["hostname"]
                    site_prefix = site_name or "DC1"
                    dev["hostname"] = f"{site_prefix}-BGW-01"
                    for lnk in all_links:
                        if lnk.get("from_device") == old_hostname:
                            lnk["from_device"] = dev["hostname"]
                        if lnk.get("to_device") == old_hostname:
                            lnk["to_device"] = dev["hostname"]
                dci_candidates_by_site[site_name] = promoted

        # Assign a shared DCI BGP ASN for border gateways
        dci_bgp_asn = 65500
        site_names = sorted(dci_candidates_by_site.keys())
        for idx, sn in enumerate(site_names):
            site_asn = dci_bgp_asn + idx
            for dev in dci_candidates_by_site[sn]:
                dev["asn"] = str(site_asn)

        for i in range(len(site_names)):
            for j in range(i + 1, len(site_names)):
                site_a_devs = dci_candidates_by_site[site_names[i]]
                site_b_devs = dci_candidates_by_site[site_names[j]]
                for a_dev in site_a_devs:
                    for b_dev in site_b_devs:
                        dci_link = {
                            "id": str(_uuid.uuid4()),
                            "from_device": a_dev["hostname"],
                            "from_port": "Ethernet1/48",
                            "to_device": b_dev["hostname"],
                            "to_port": "Ethernet1/48",
                            "sfp": "",
                            "cable_type": "DCI",
                            "speed": "100G",
                            "protocol": "BGP",
                            "bgp_address_family": "ipv4 unicast",
                            "from_asn": a_dev.get("asn", ""),
                            "to_asn": b_dev.get("asn", ""),
                        }
                        all_links.append(dci_link)

        all_sites = sorted(set(d.get("site", "") for d in all_devices if d.get("site")))
        bom_data = {
            "type": "fabric",
            "devices": all_devices,
            "links": all_links,
            "hardware": None,
            "metadata": {
                "total_devices": len(all_devices),
                "total_links": len(all_links),
                "sites": all_sites if all_sites else ["site-1"],
                "multisite": len(all_sites) > 1,
                "bom_type": "generated_from_hardware",
            }
        }

    _fabric_model = FabricModel()
    _fabric_model.load_from_bom(bom_data)
    _fabric_model.add_default_overlay()
    _fabric_configs = {}
    _init_traffic_engine()

    return _fabric_model.to_dict()


@app.get("/api/fabric/template")
async def download_bom_template():
    """Download a BOM Excel template."""
    template_bytes = BomParser.generate_template()
    return Response(
        content=template_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=fabric_bom_template.xlsx"}
    )


@app.get("/api/fabric/model")
async def get_fabric_model():
    """Get the current fabric model state."""
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded. Upload a BOM first.")
    return _fabric_model.to_dict()


@app.post("/api/fabric/load-demo")
async def load_demo_fabric(request: Request):
    """Load a pre-built demo multi-site VXLAN fabric for immediate use."""
    global _fabric_model, _fabric_configs
    body = await request.json()
    _fabric_model = FabricModel()
    _fabric_model.devices = []
    _fabric_model.links = []
    _fabric_model.sites = body.get("sites", [])
    _fabric_model.multisite = body.get("multisite", False)

    overlay_data = body.get("overlay", {})
    if overlay_data:
        _fabric_model.overlay.vrfs = overlay_data.get("vrfs", [])
        _fabric_model.overlay.vlans = overlay_data.get("vlans", [])
        _fabric_model.overlay.vnis = overlay_data.get("vnis", [])

    gc = body.get("global_config")
    if gc:
        _fabric_model.global_config.update(gc)
    d2 = body.get("day2_config")
    if d2:
        _fabric_model.day2_config.update(d2)

    from fabric_builder.fabric_model import FabricDevice, FabricLink
    for dev in body.get("devices", []):
        _fabric_model.devices.append(FabricDevice(dev))
    for link in body.get("links", []):
        _fabric_model.links.append(FabricLink(link))

    _fabric_configs.clear()
    _endpoint_store.endpoints = []

    for ep in body.get("endpoints", []):
        from fabric_builder.endpoint_model import FabricEndpoint
        _endpoint_store.endpoints.append(FabricEndpoint(ep))

    _init_traffic_engine()
    return {"status": "ok", "devices": len(_fabric_model.devices), "links": len(_fabric_model.links)}


@app.put("/api/fabric/device/{device_id}")
async def update_device(device_id: str, request: Request):
    """Edit device properties."""
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    body = await request.json()
    result = _fabric_model.update_device(device_id, body)
    if not result:
        raise HTTPException(status_code=404, detail="Device not found")
    _fabric_configs.clear()
    return result


@app.put("/api/fabric/link/{link_id}")
async def update_link(link_id: str, request: Request):
    """Edit link properties."""
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    body = await request.json()
    result = _fabric_model.update_link(link_id, body)
    if not result:
        raise HTTPException(status_code=404, detail="Link not found")
    _fabric_configs.clear()
    return result


@app.post("/api/fabric/overlay")
async def update_overlay(request: Request):
    """Add/edit VRFs, VLANs, VNIs."""
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    body = await request.json()
    _fabric_model.update_overlay(body)
    _fabric_configs.clear()
    return _fabric_model.overlay.to_dict()


@app.put("/api/fabric/global-config")
async def update_global_config(request: Request):
    """Update global fabric configuration."""
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    body = await request.json()
    for key, value in body.items():
        if key in _fabric_model.global_config:
            _fabric_model.global_config[key] = value
    _fabric_configs.clear()
    return _fabric_model.global_config


@app.put("/api/fabric/day2-config")
async def update_day2_config(request: Request):
    """Update Day-2 configuration (NTP, SNMP, etc.)."""
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    body = await request.json()
    for key, value in body.items():
        if key in _fabric_model.day2_config:
            _fabric_model.day2_config[key] = value
    _fabric_configs.clear()
    return _fabric_model.day2_config


@app.post("/api/fabric/generate-config")
async def generate_configs():
    """Generate all configs from the current model."""
    global _fabric_configs
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    engine = ConfigEngine(_fabric_model)
    _fabric_configs = engine.generate_all()
    return {"devices": list(_fabric_configs.keys()), "total": len(_fabric_configs)}


@app.get("/api/fabric/config/{device_id}")
async def get_device_config(device_id: str):
    """Get generated config for one device."""
    global _fabric_configs
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    if not _fabric_configs:
        engine = ConfigEngine(_fabric_model)
        _fabric_configs = engine.generate_all()
    device = _fabric_model.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    config = _fabric_configs.get(device.hostname, "")
    if not config:
        engine = ConfigEngine(_fabric_model)
        config = engine.get_device_config(device_id)
    return {"hostname": device.hostname, "config": config}


@app.post("/api/fabric/cli-command")
async def apply_cli_command(request: Request):
    """Apply a CLI-style command to the model (config terminal concept)."""
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    body = await request.json()
    device_id = body.get("device_id", "")
    command = body.get("command", "").strip()

    if not device_id or not command:
        raise HTTPException(status_code=400, detail="device_id and command are required")

    device = _fabric_model.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    old_hostname = device.hostname
    result = _apply_cli(device, command)
    _fabric_configs.clear()

    # Update link references if hostname changed
    if device.hostname != old_hostname:
        for link in _fabric_model.links:
            if link.from_device == old_hostname:
                link.from_device = device.hostname
            if link.to_device == old_hostname:
                link.to_device = device.hostname

    return {"device": device.hostname, "result": result, "model": device.to_dict()}


def _apply_cli(device, command: str) -> str:
    """Parse a simplified NX-OS CLI command and apply to the device model."""
    parts = command.split()
    if not parts:
        return "Empty command"

    cmd = parts[0].lower()

    if cmd == "hostname" and len(parts) > 1:
        device.hostname = parts[1]
        return f"Hostname set to {parts[1]}"

    if cmd == "interface" and len(parts) > 1:
        intf_name = " ".join(parts[1:])
        existing = next((i for i in device.interfaces if i["name"].lower() == intf_name.lower()), None)
        if not existing:
            device.interfaces.append({"name": intf_name, "description": "", "speed": "", "sfp": "", "type": "user"})
            return f"Interface {intf_name} created"
        return f"Interface {intf_name} selected"

    if cmd == "description" and len(parts) > 1:
        desc = " ".join(parts[1:])
        if device.interfaces:
            device.interfaces[-1]["description"] = desc
            return f"Description set: {desc}"
        return "No interface context"

    if cmd in ("no",) and len(parts) > 1:
        subcmd = parts[1].lower()
        if subcmd == "interface" and len(parts) > 2:
            intf_name = " ".join(parts[2:])
            device.interfaces = [i for i in device.interfaces if i["name"].lower() != intf_name.lower()]
            return f"Interface {intf_name} removed"
        return f"Unknown 'no' subcommand: {subcmd}"

    if cmd == "ip" and len(parts) >= 3 and parts[1].lower() == "address":
        device.config.setdefault("ip_addresses", []).append(" ".join(parts[2:]))
        return f"IP address added: {' '.join(parts[2:])}"

    if cmd == "role" and len(parts) > 1:
        valid_roles = ("spine", "leaf", "border_leaf", "border_gateway", "super_spine", "service_leaf")
        new_role = parts[1].lower()
        if new_role in valid_roles:
            device.role = new_role
            return f"Role changed to {new_role}"
        return f"Invalid role. Valid: {', '.join(valid_roles)}"

    if cmd == "router-id" and len(parts) > 1:
        device.loopback0 = parts[1] if "/" in parts[1] else parts[1] + "/32"
        return f"Router-ID (loopback0) set to {device.loopback0}"

    if cmd == "loopback0" and len(parts) > 1:
        device.loopback0 = parts[1] if "/" in parts[1] else parts[1] + "/32"
        return f"Loopback0 set to {device.loopback0}"

    if cmd == "loopback1" and len(parts) > 1:
        device.loopback1 = parts[1] if "/" in parts[1] else parts[1] + "/32"
        return f"Loopback1 (VTEP) set to {device.loopback1}"

    if cmd == "loopback2" and len(parts) > 1:
        device.loopback2 = parts[1] if "/" in parts[1] else parts[1] + "/32"
        return f"Loopback2 (Multi-site) set to {device.loopback2}"

    if cmd == "asn" and len(parts) > 1:
        device.asn = parts[1]
        return f"BGP ASN set to {parts[1]}"

    if cmd == "site" and len(parts) > 1:
        device.site = parts[1]
        return f"Site set to {parts[1]}"

    if cmd == "mgmt-ip" and len(parts) > 1:
        device.mgmt_ip = parts[1]
        return f"Management IP set to {parts[1]}"

    if cmd == "vpc" and len(parts) >= 3 and parts[1].lower() == "domain":
        device.vpc_domain = parts[2]
        return f"vPC domain set to {parts[2]}"

    if cmd == "vpc" and len(parts) >= 3 and parts[1].lower() == "peer":
        device.vpc_peer = parts[2]
        return f"vPC peer set to {parts[2]}"

    if cmd == "show" and len(parts) > 1:
        subcmd = parts[1].lower()
        if subcmd == "running-config" or subcmd == "run":
            lines = [f"hostname {device.hostname}", f"role {device.role}", f"asn {device.asn or 'not set'}"]
            lines.append(f"loopback0 {device.loopback0 or 'not set'}")
            lines.append(f"loopback1 {device.loopback1 or 'not set'}")
            if device.loopback2:
                lines.append(f"loopback2 {device.loopback2}")
            lines.append(f"mgmt-ip {device.mgmt_ip or 'not set'}")
            lines.append(f"site {device.site or 'not set'}")
            if device.vpc_domain:
                lines.append(f"vpc domain {device.vpc_domain}")
            if device.vpc_peer:
                lines.append(f"vpc peer {device.vpc_peer}")
            for intf in device.interfaces:
                lines.append(f"interface {intf['name']}")
                if intf.get("description"):
                    lines.append(f"  description {intf['description']}")
            return "\n".join(lines)
        if subcmd == "interfaces" or subcmd == "interface":
            if not device.interfaces:
                return "No interfaces configured"
            lines = []
            for intf in device.interfaces:
                lines.append(f"  {intf['name']}: {intf.get('description', '')}")
            return "\n".join(lines)
        if subcmd == "version":
            return f"{device.hostname} | Model: {device.model or 'N9K'} | Role: {device.role} | Site: {device.site}"
        return f"Unknown show command: {subcmd}"

    if cmd == "help" or cmd == "?":
        return ("Available commands:\n"
                "  hostname <name>       - Set hostname\n"
                "  role <role>           - Set role (spine/leaf/border_gateway/...)\n"
                "  asn <number>          - Set BGP ASN\n"
                "  site <name>           - Set site name\n"
                "  loopback0 <ip/mask>   - Set loopback0 IP\n"
                "  loopback1 <ip/mask>   - Set VTEP loopback IP\n"
                "  loopback2 <ip/mask>   - Set multi-site loopback IP\n"
                "  mgmt-ip <ip/mask>     - Set management IP\n"
                "  vpc domain <id>       - Set vPC domain\n"
                "  vpc peer <hostname>   - Set vPC peer\n"
                "  interface <name>      - Create/select interface\n"
                "  description <text>    - Set interface description\n"
                "  ip address <ip/mask>  - Add IP address\n"
                "  no interface <name>   - Remove interface\n"
                "  show run              - Show running config\n"
                "  show interfaces       - Show interfaces\n"
                "  show version          - Show device info")

    return f"Command applied: {command}"


@app.get("/api/fabric/export/nxos")
async def export_nxos():
    """Download NX-OS configs as ZIP."""
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    exporter = NxosExporter(_fabric_model)
    zip_bytes = exporter.export()
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=fabric_configs.zip"}
    )


@app.get("/api/fabric/export/yaml")
async def export_yaml():
    """Download YAML (tech-vxlan + tech-shared) as ZIP."""
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    exporter = YamlExporter(_fabric_model)
    yaml_files = exporter.export()

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in yaml_files.items():
            zf.writestr(filename, content)
    zip_buffer.seek(0)

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=fabric_yaml.zip"}
    )


# =============================================================================
# FABRIC BUILDER - ENDPOINTS API
# =============================================================================

@app.post("/api/fabric/endpoints")
async def add_endpoint(request: Request):
    """Add an endpoint to the fabric."""
    body = await request.json()
    ep = _endpoint_store.add(body)
    return {"endpoint": ep.to_dict()}


@app.get("/api/fabric/endpoints")
async def list_endpoints():
    """List all fabric endpoints."""
    return {"endpoints": _endpoint_store.list_all()}


@app.put("/api/fabric/endpoints/{ep_id}")
async def update_endpoint(ep_id: str, request: Request):
    """Update an endpoint."""
    body = await request.json()
    ep = _endpoint_store.update(ep_id, body)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return {"endpoint": ep.to_dict()}


@app.delete("/api/fabric/endpoints/{ep_id}")
async def delete_endpoint(ep_id: str):
    """Remove an endpoint."""
    removed = _endpoint_store.remove(ep_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return {"status": "removed"}


@app.post("/api/fabric/devices")
async def add_device(request: Request):
    """Add a new switch device to the fabric."""
    import uuid as _uuid
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    body = await request.json()
    body.setdefault("id", str(_uuid.uuid4()))
    from fabric_builder.fabric_model import FabricDevice
    device = FabricDevice(body)
    _fabric_model.devices.append(device)
    return {"device": device.to_dict()}


@app.post("/api/fabric/links")
async def add_link(request: Request):
    """Add a new link to the fabric."""
    import uuid as _uuid
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    body = await request.json()
    body.setdefault("id", str(_uuid.uuid4()))

    from_id = body.get("from_device", "")
    to_id = body.get("to_device", "")
    from_dev = _fabric_model.get_device(from_id)
    to_dev = _fabric_model.get_device(to_id)
    if from_dev:
        body["from_device"] = from_dev.hostname
    if to_dev:
        body["to_device"] = to_dev.hostname

    from fabric_builder.fabric_model import FabricLink
    link = FabricLink(body)
    _fabric_model.links.append(link)
    return {"link": link.to_dict()}


# =============================================================================
# FABRIC BUILDER - TRAFFIC SIMULATION API
# =============================================================================

@app.post("/api/fabric/traffic/trace")
async def trace_traffic(request: Request):
    """Trace traffic path between two endpoints."""
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    _init_traffic_engine()

    body = await request.json()
    src_id = body.get("src_endpoint_id", "")
    dst_id = body.get("dst_endpoint_id", "")
    vlan = body.get("vlan", "")
    vrf = body.get("vrf", "")

    result = _traffic_engine.trace(src_id, dst_id, vlan=vlan, vrf=vrf)
    return result


@app.post("/api/fabric/traffic/failover")
async def simulate_failover(request: Request):
    """Simulate a failure and compute failover path."""
    if not _fabric_model:
        raise HTTPException(status_code=404, detail="No fabric model loaded")
    _init_traffic_engine()

    body = await request.json()
    failure = body.get("failure", {})
    f_type = failure.get("type", "link")
    f_target = failure.get("target_id", "")

    if f_type == "device":
        result = _failover_sim.simulate_device_failure(f_target)
    elif f_type == "link":
        result = _failover_sim.simulate_link_failure(f_target)
    else:
        result = {"error": "Unknown failure type", "converged": False}

    return result


@app.post("/api/fabric/traffic/restore")
async def restore_failure(request: Request):
    """Restore a previously injected failure."""
    if not _traffic_engine:
        raise HTTPException(status_code=404, detail="No traffic engine initialized")

    body = await request.json()
    f_type = body.get("type", "link")
    f_target = body.get("target_id", "")
    _traffic_engine.restore(f_type, f_target)
    return {"status": "restored"}


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
