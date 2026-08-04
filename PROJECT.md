# Classic Fabric Visualiser & VXLAN Fabric Builder — Project Documentation

Consolidated reference covering architecture, capabilities, and implementation details for both modules.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Tab 1: Classic Fabric Visualiser](#tab-1-classic-fabric-visualiser)
3. [Tab 2: VXLAN Fabric Builder](#tab-2-vxlan-fabric-builder)
4. [Architecture](#architecture)
5. [API Reference](#api-reference)
6. [Dependencies](#dependencies)
7. [Running](#running)

---

## Project Overview

**Purpose**: A dual-mode network engineering tool that:
1. **Visualises** existing traditional Ethernet fabrics from device command outputs (CDP/LLDP/BGP/OSPF) and plans VXLAN migrations.
2. **Designs and builds** new VXLAN EVPN fabrics from hardware Bills of Material, with interactive topology editing, traffic simulation, and full configuration generation.

**Primary Platform Target**: Cisco Nexus 9000 series, with multi-vendor support for visualisation.

**Stack**: Python 3.10+ (FastAPI backend) + Vanilla JS frontend (Cytoscape.js for interactive graph rendering).

---

## Tab 1: Classic Fabric Visualiser

### Phase 1 — Physical Topology

**Core Capabilities**:
- Upload multiple files (`.txt`, `.log`, `.cfg`, `.zip`, `.xlsx`, folders)
- Parse standard network device command outputs
- Build a physical topology visualisation with link speeds, statuses, and port-channel groupings
- Interactive canvas with zoom, pan, multi-select, and device detail pane

**Parsing Logic**:

1. **CDP/LLDP (Primary)**: Extracts from `show cdp neighbors detail` / `show lldp neighbors detail`
   - Only extracts: Device ID, SysName, IPv4 address, Platform, Capabilities, Interface, Port ID
   - Multi-vendor: NX-OS, IOS-XE, Arista, Juniper

2. **Interface Description Fallback**: When CDP/LLDP disabled, looks at `show interface description` and matches device names against known hostnames

3. **Running Config**: Extracts hostname, VLANs, port-channels, VPC, SVIs, routing config

4. **Platform/Version**: Detects vendor, model, serial, software version, uptime

**Topology Construction**:
- `TopologyBuilder` aggregates all parsed data into nodes and edges
- Nodes get roles: spine, core, leaf, access, router, firewall, loadbalancer, WLC, wan_cloud
- Edges carry: local/remote interface, speed, protocol (CDP/LLDP/inferred), link status, port-channel info

**Frontend Features**:
- **Layouts**: Hierarchical (default), Force-Directed, Cola, Circle, Grid, Concentric
- **Views**: Connected Devices, Isolated Devices, All Devices
- **Device Detail Pane**: Info/Interfaces/Config tabs with clickable neighbors
- **Export**: PNG screenshot or Draw.io XML

### Phase 2 — Logical Topology (BGP + OSPF)

- **BGP Topology**: Shows confirmed BGP peerings between uploaded devices (iBGP/eBGP, state, prefixes)
- **OSPF Topology**: Area grouping, adjacency states, interface costs
- **View Switching**: Physical / BGP / OSPF / Migration with position persistence

### Phase 3 — VXLAN Migration Planning

**Migration Classifier** — Weighted scoring for device role assignment:

| Factor | Spine | Leaf | Border | Service |
|--------|-------|------|--------|---------|
| High fanout (4+) | +3.0 | | | |
| No access ports | +2.0 | | | |
| Many access ports (>40%) | | +3.0 | | |
| WAN connected | | | +4.0 | |
| FW/LB attached | | | | +2.0 |

**Hardware Capability Check**: Full VXLAN (Nexus 9K, Cat 9300-9500, Arista 7K, QFX), Limited (7K, Cat 9200), Unsupported (2K/3K/5K, legacy)

**Underlay Designer**:

| | OSPF Underlay | eBGP Underlay |
|---|---|---|
| Overlay | iBGP with route-reflectors (spines) | eBGP multihop over loopbacks |
| ASN model | Single ASN (overlay) | Spine ASN + unique per-leaf ASN |

**Migration Phases** (auto-generated): Build Underlay → Border Migration → Service Leaf → Leaf Migration → Cleanup

---

## Tab 2: VXLAN Fabric Builder

### Overview

A complete VXLAN EVPN fabric design and configuration tool. Upload a hardware BOM or start from a demo topology, interactively design the fabric, simulate traffic flows, and export production-ready NX-OS configurations.

### Core Capabilities

#### 1. Hardware BOM Ingestion
- Upload CSV/Excel Bill of Material with Nexus 9K platform PIDs, SFPs, and cables
- **Auto-column detection** — flexible BOM formats, no rigid template required
- **PID recognition** — maps all Nexus 9000 series (93xx, 9336, 9364, 9408, 9508, 9516) to roles
- **Editable quantities** — adjust device counts directly in the UI before building
- **Role assignment** — auto-inferred from PID (spine/leaf/super-spine) with manual override
- **Template export** — download a reference BOM template

#### 2. Multi-Site Fabric Design
- Split hardware inventory across 2–4 sites with independent naming and IP schemes
- Per-site configurable prefixes (spine, leaf, border leaf, BGW), management subnets, loopback subnets, VTEP subnets
- **DCI link generation** — automatically creates BGP IPv4 Unicast peering between border gateway devices across sites
- **Super-spine detection** — automatically identifies 5-stage Clos topologies from high-radix/400G PIDs

#### 3. Interactive Topology Canvas
- **3-panel layout**: Left sidebar (fabric summary + events), center canvas, right inspector/tools
- **Cytoscape.js** powered interactive graph with pan, zoom (pinch/scroll/buttons), and grab-to-move
- **Site boundaries** — visual dashed rectangles encapsulating each site's devices
- **DCI links** — amber dashed lines with directional arrows showing inter-site connectivity
- **Device icons** — color-coded by role (spine=indigo, leaf=teal, BGW=amber, super-spine=purple)
- **Endpoint icons** — distinct shapes per type (servers, load balancers, firewalls, WAN, storage, cloud gateways)
- **Right-click context menus** — edit, delete, connect, configure, simulate failure
- **Double-click rename** — inline hostname editing
- **Drag-to-connect** — create new links between devices
- **Link inspector** — click any link to see port, speed, type, and BGP peering details (for DCI)

#### 4. Endpoint Management
- Add network-attached endpoints: Servers, VM Hosts, Load Balancers, Firewalls, WAN/Edge Routers, Storage Arrays, Backup Appliances, Cloud Gateways (DCI/EVPN-to-cloud), SD-WAN Edges
- Define custom endpoint types with custom icons
- Configure: IP, VLAN, VRF, connection mode (single-homed or dual-homed vPC), LACP, port-channel
- Connect to leaf switches with explicit port mappings

#### 5. Traffic Simulation & Validation
- **Full-path animated flow** — packet dot traverses source endpoint → ingress leaf → spine (ECMP) → egress leaf → destination endpoint
- **L2/L3 VXLAN path computation**:
  - L2 Local (same leaf, same VLAN)
  - L2 VXLAN (cross-leaf bridging with L2 VNI)
  - L3 VXLAN Symmetric IRB (cross-leaf routing with L3 VNI)
  - Inter-VRF detection (fails without route leaking)
- **VNI/VRF validation** — verifies VLANs, VRFs, and anycast gateways are configured on relevant devices
- **Detailed results panel** — shows: source/destination IPs, VLANs, VRFs, L2 VNI, L3 VNI, ingress/egress VTEP IPs, ECMP path count, and hop-by-hop routing path with per-hop action (encap/decap/route) and encapsulation state
- **Color-coded hops**: cyan=VXLAN encap, amber=decap, purple=routing

#### 6. Failover Simulation
- Inject device/link failures via right-click context menu or the simulation panel
- **Port-channel and vPC** awareness — reconverges via surviving member links
- Shows original path vs. failover path with visual diff
- Reports convergence status and affected endpoints
- Supports restoring failures for iterative testing

#### 7. Configuration Generation (Day-0/Day-1/Day-2)

Full NX-OS configuration generation using Jinja2 templates:

| Stage | What's Generated |
|-------|-----------------|
| **Day-0** | Hostname, management interface, NTP, DNS, boot variables, POAP-ready |
| **Day-1** | OSPF/eBGP underlay, BGP EVPN overlay, VXLAN NVE, VLANs, VRFs, SVIs, anycast gateways, vPC, port-channels, fabric interfaces |
| **Day-2** | SNMP, syslog, AAA/TACACS+, CoPP, NTP monitoring, SPAN sessions |

**Multi-site additions**: BGP address-family IPv4 unicast between border gateways, EVPN multi-site configuration, DCI interfaces.

#### 8. Configuration Export

Two export formats:

| Format | Description |
|--------|-------------|
| **NX-OS CLI (ZIP)** | Per-device `.cfg` files packaged in a ZIP archive, ready for direct application |
| **YAML (DDA Format)** | Structured `data.tech-vxlan.yaml` and `data.tech-shared.yaml` for Digitised Document Architecture pipelines |

#### 9. Terminal Interface ("Config Terminal")
- Multiple floating/dockable terminal windows (one per device)
- Simulates NX-OS `configure terminal` to modify the in-memory fabric model
- Changes reflected immediately in the topology canvas and configuration output
- Tab management for multi-device editing

#### 10. Fabric Summary & Monitoring (Left Panel)
- **Stat grid**: total devices, links, endpoints, VLANs, VRFs, sites
- **vPC health indicators**: pair status, peer-link state
- **Overlay utilization**: VNI usage, VTEP count
- **Live event log**: tracks all user interactions (selections, traffic traces, failures)

### Advantages

| Advantage | Description |
|-----------|-------------|
| **Zero-dependency design** | No DCNM/NDFC/Terraform required — standalone in-browser tool |
| **BOM-to-config in minutes** | Upload hardware list → get production-ready VXLAN config |
| **Multi-site from day one** | Design 2–4 site fabrics with proper DCI (BGP IPv4 unicast) |
| **Validate before deploy** | Traffic simulation catches misconfigurations (missing VNIs, VRFs, gateways) before touching production |
| **Failover confidence** | Simulate device/link failures and verify reconvergence paths |
| **Interactive exploration** | Drag, edit, rename, connect — treat the topology as a living document |
| **Standard compliance** | Configurations follow Cisco NX-OS best practices and IEEE 802.1Q/VXLAN (RFC 7348) standards |
| **Portable output** | Export as NX-OS CLI configs or YAML for automation pipelines |
| **Super-spine awareness** | Automatically handles 5-stage Clos for large-scale fabrics |
| **Endpoint-aware design** | Model servers, load balancers, firewalls, and WAN devices with proper connectivity |

---

## Architecture

```
Classic-Fabric-Visualiser/
├── backend/
│   ├── main.py                          # FastAPI app — all API endpoints
│   ├── requirements.txt                 # Python dependencies
│   ├── parsers/                         # Phase 1-3: Command output parsers
│   │   ├── cdp_parser.py               # CDP neighbor parsing
│   │   ├── lldp_parser.py              # LLDP neighbor parsing
│   │   ├── interface_parser.py         # Interface brief/status/description
│   │   ├── platform_parser.py          # Device model/vendor detection
│   │   ├── config_parser.py            # Running config parsing
│   │   ├── bgp_parser.py              # BGP summary/neighbors
│   │   └── ospf_parser.py             # OSPF overview/neighbors
│   ├── topology/                        # Topology construction
│   │   ├── builder.py                  # Physical topology
│   │   └── routing_builder.py          # BGP/OSPF logical topology
│   ├── migration/                       # Phase 3: Migration planning
│   │   ├── classifier.py              # Device role classification
│   │   └── underlay_designer.py       # Underlay/overlay design engine
│   └── fabric_builder/                  # Phase 4: VXLAN Fabric Builder
│       ├── __init__.py
│       ├── fabric_model.py             # Core data model (devices, links, overlay)
│       ├── bom_parser.py               # BOM parsing + hardware-to-fabric generation
│       ├── config_engine.py            # Jinja2-based NX-OS config generation
│       ├── endpoint_model.py           # Endpoint types and connections
│       ├── traffic_engine.py           # L2/L3 VXLAN path computation
│       ├── failover_sim.py             # Failure injection and reconvergence
│       ├── nxos_exporter.py            # NX-OS CLI ZIP export
│       ├── yaml_exporter.py            # DDA YAML export
│       └── templates/                   # Jinja2 configuration templates
│           ├── base.j2                 # Day-0 (hostname, mgmt, boot)
│           ├── ospf_underlay.j2        # OSPF underlay config
│           ├── bgp_overlay.j2          # BGP EVPN overlay config
│           ├── interfaces.j2           # Interface configs
│           ├── vxlan.j2                # NVE, VNI, VLAN configs
│           ├── vpc.j2                  # vPC domain and peer-link
│           ├── multisite.j2            # Multi-site BGW configs
│           └── day2.j2                 # SNMP, syslog, AAA, CoPP
├── frontend/
│   ├── index.html                       # Main HTML (both tabs)
│   ├── app.js                          # Tab 1: Visualiser logic
│   ├── fabric-builder.js               # Tab 2: Fabric Builder logic
│   ├── styles.css                      # Unified dark-theme stylesheet
│   └── favicon.png                     # App icon
├── run.sh                               # One-command startup script
├── README.md                            # User-facing documentation
└── PROJECT.md                           # This file — full technical reference
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, FastAPI, Uvicorn, Jinja2 |
| Frontend | Vanilla JS, Cytoscape.js, HTML5/CSS3 |
| Streaming | Server-Sent Events (SSE) for real-time parsing |
| Layout | Cytoscape preset/breadthfirst/cose algorithms |
| Config Templates | Jinja2 with NX-OS CLI syntax |
| Export | ZIP (per-device configs), YAML (DDA format) |

---

## API Reference

### Tab 1 — Visualiser APIs

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/upload` | Upload device output files (SSE streaming response) |
| GET | `/topology` | Get constructed topology (nodes + edges) |
| POST | `/api/redesign-underlay` | Redesign underlay with new parameters |

### Tab 2 — Fabric Builder APIs

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/fabric/upload-bom` | Parse BOM file (hardware or fabric type) |
| POST | `/api/fabric/build-from-hardware` | Generate fabric from hardware inventory + site config |
| POST | `/api/fabric/load-demo` | Load pre-built demo topology |
| GET | `/api/fabric/model` | Get current fabric model |
| PUT | `/api/fabric/model` | Update full fabric model |
| PUT | `/api/fabric/device/{id}` | Update a single device |
| POST | `/api/fabric/cli` | Process CLI commands on the fabric model |
| GET | `/api/fabric/config/generate` | Generate all device configurations |
| GET | `/api/fabric/export/nxos` | Export NX-OS CLI configs (ZIP) |
| GET | `/api/fabric/export/yaml` | Export DDA YAML format |
| GET | `/api/fabric/endpoints` | List all endpoints |
| POST | `/api/fabric/endpoints` | Add an endpoint |
| PUT | `/api/fabric/endpoints/{id}` | Update an endpoint |
| DELETE | `/api/fabric/endpoints/{id}` | Delete an endpoint |
| POST | `/api/fabric/traffic/trace` | Trace traffic path between endpoints |
| POST | `/api/fabric/traffic/failover` | Simulate failure + compute failover path |
| POST | `/api/fabric/traffic/failure` | Inject a failure |
| POST | `/api/fabric/traffic/restore` | Restore a failed element |
| GET | `/api/fabric/bom-template` | Download BOM template |

---

## Dependencies

**Python (backend)**:
```
fastapi>=0.100.0
uvicorn[standard]>=0.22.0
python-multipart>=0.0.6
openpyxl>=3.1.0
jinja2>=3.1.0
pyyaml>=6.0
```

**Frontend (CDN, no npm)**:
- Cytoscape.js 3.30.4
- Cytoscape-Cola 2.5.1
- WebCola 3.4.0

---

## Running

```bash
./run.sh
# → http://localhost:8765
```

Or manually:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8765 --reload
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Vanilla JS (no framework) | Minimal dependencies, fast load, easy to embed |
| Cytoscape.js for both tabs | Consistent interaction model, proven graph library |
| Server-Sent Events for parsing | Real-time feedback without WebSocket complexity |
| In-memory fabric model | Fast iteration; no DB overhead for design-time tool |
| Jinja2 templates for config | Readable, maintainable NX-OS config generation |
| DCI via border gateway leaves (not spines) | Correct VXLAN multi-site architecture per Cisco best practices |
| BGP IPv4 unicast for DCI | Standard inter-site peering for VXLAN multi-site |
| Hardware BOM auto-detection | Flexible input; doesn't enforce rigid column naming |
| Super-spine from PID analysis | Avoid manual 5-stage configuration; auto-infer from hardware |
| Traffic simulation with full overlay validation | Catch config errors before deployment |
| Preset layout (not force-directed) | Predictable spine-leaf visual hierarchy |
| Site boundaries as background nodes | Visual separation without affecting interaction |
