# Classic Fabric Visualiser — Project Documentation

Consolidated reference for the entire build history, architecture decisions, and implementation details.

---

## Project Overview

**Purpose**: Visualize large traditional Ethernet fabrics (Cisco Nexus, Catalyst, Arista, Juniper, etc.) and build a migration roadmap to VXLAN/EVPN.

**Primary Platform Target**: Cisco Nexus 9000 series, with multi-vendor support.

**Stack**: Python 3.10+ (FastAPI backend) + Vanilla JS frontend (Cytoscape.js for graph rendering).

---

## Phase 1: Physical Topology

### Core Capabilities
- Upload multiple files (`.txt`, `.log`, `.cfg`, `.zip`, `.xlsx`, folders)
- Parse standard network device command outputs
- Build a physical topology visualisation with link speeds, statuses, and port-channel groupings
- Interactive canvas with zoom, pan, multi-select, and device detail pane

### Parsing Logic

1. **CDP/LLDP (Primary)**: Extracts from `show cdp neighbors detail` / `show lldp neighbors detail`
   - Only extracts: Device ID, SysName, IPv4 address, Platform, Capabilities, Interface, Port ID
   - Multi-vendor: NX-OS, IOS-XE, Arista, Juniper

2. **Interface Description Fallback**: When CDP/LLDP disabled, looks at `show interface description` and matches device names against known hostnames from the upload bundle (inferred connections)

3. **Running Config**: Extracts hostname, VLANs, port-channels, VPC, SVIs, routing config

4. **Platform/Version**: Detects vendor, model, serial, software version, uptime

### Topology Construction
- `TopologyBuilder` class aggregates all parsed data into nodes and edges
- Nodes get roles: spine, core, leaf, access, router, firewall, loadbalancer, WLC, wan_cloud
- Edges carry: local/remote interface, speed, protocol (CDP/LLDP/inferred), link status, port-channel info
- Isolated devices separated from connected topology

### Frontend Features
- **Layouts**: Hierarchical (default), Force-Directed, Cola, Circle, Grid, Concentric
- **Views**: Connected Devices, Isolated Devices, All Devices
- **Device Detail Pane** (right side):
  - Info tab: vendor, model, role, platform, serial, uptime, mgmt IP, clickable neighbor list
  - Interfaces tab: summary counts, color-coded table with Status/Protocol/IP/VLAN/Description/Channel
  - Config tab: raw running config display
- **Neighbor Click**: Clicking a neighbor in the Info tab highlights the link + peer on canvas and shows peer details
- **Multi-select**: Ctrl/Cmd+click or lasso drag
- **Export**: PNG or Draw.io XML (includes device roles, link status, migration roles)
- **Position Persistence**: Node positions saved per view mode, survive mode switches

### Device Role Detection
Weighted scoring based on:
- Hostname patterns (spine, core, leaf, fw, lb, wlc, etc.)
- Platform identification (Nexus = switch, ASA = firewall, F5 = loadbalancer)
- Interface characteristics (all trunks = spine, access ports = leaf)

---

## Phase 2: Logical Topology (BGP + OSPF)

### BGP Topology
- Parses: `show ip bgp summary`, `show bgp neighbors`, BGP config from running-config
- `RoutingTopologyBuilder` builds BGP graph:
  - Nodes: devices with ASN, router-id, state
  - Edges: peering sessions with type (iBGP/eBGP), state, prefixes
- Only shows confirmed peerings between known (uploaded) devices — no stale entries

### OSPF Topology
- Parses: `show ip ospf`, `show ip ospf neighbor`, `show ip ospf interface`, OSPF from running-config
- Builds OSPF graph:
  - Nodes: devices with router-id, areas
  - Edges: adjacencies with state, cost, area membership

### View Switching
- Dropdown: Physical / BGP / OSPF / Migration Plan
- Each view maintains independent node positions (cached on switch)

---

## Phase 3: VXLAN Migration Planning

### Migration Classifier (`backend/migration/classifier.py`)

**Role Assignment** — Weighted scoring for each device:

| Factor | Spine Signal | Leaf Signal | Border Signal | Service Signal |
|--------|-------------|-------------|---------------|----------------|
| High fanout (4+ downstream) | +3.0 | | | |
| No access ports | +2.0 | | | |
| Many access ports (>40%) | | +3.0 | | |
| WAN connected | | | +4.0 | |
| FW/LB attached | | | | +2.0 |
| Current role match | +2.0 | +1.0 | +2.0 | |

**Hardware Capability Check**:
- Full VXLAN: Nexus 9K, Catalyst 9300-9500, Arista 7000, QFX5K/10K
- Limited: Nexus 7K, Catalyst 9200
- Unsupported: WS-C29xx, WS-C37xx, Nexus 2K/3K/5K, 6500, 4500

**Migration Phases** (auto-suggested):
1. Phase A: Build Underlay (spines)
2. Phase B: Border Migration (border leafs)
3. Phase C: Service Leaf (FW/LB attached)
4. Phase D: Leaf Migration (access leafs, ordered by connectivity)
5. Phase E: Cleanup (remove STP, legacy trunks)

**VNI Mapping**: `VLAN ID + 10000 = VNI` (auto-generated, manually customisable)

### Underlay Designer (`backend/migration/underlay_designer.py`)

**Underlay Protocol Options**:

| | OSPF Underlay | eBGP Underlay |
|---|---|---|
| Overlay | iBGP with route-reflectors (spines) | eBGP multihop over loopbacks |
| Spine role | OSPF + RR | eBGP peer to all leaves + EVPN transit |
| Leaf role | OSPF uplinks + iBGP to RRs | eBGP uplinks + EVPN to spines |
| ASN model | Single ASN (overlay) | Spine ASN + unique per-leaf ASN |

**Per-Device Output** includes:
- Underlay: protocol, area/ASN, fabric interfaces, BFD, config notes
- Overlay: protocol, ASN, role (RR/client/transit/vtep), neighbors, address families with notes

**BGP Address Families** (user-selectable):
- L2VPN EVPN (always required)
- IPv4 Unicast (optional)
- IPv6 Unicast (optional)

### API Endpoint
- `POST /api/redesign-underlay` — accepts protocol choice, ASNs, AFs, area; returns new design

### Frontend Migration Panel
- Tabs: Underlay Design | VNI Mapping | Migration Phases | Device Roles
- Protocol toggle (OSPF/eBGP) with dynamic parameter fields
- "Apply Design" button triggers live redesign via API
- Per-device expandable cards with config notes and AF details
- Device cards highlight corresponding node on canvas when expanded

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Vanilla JS (no framework) | Minimal dependencies, fast load, easy to embed |
| Server-Sent Events for parsing | Real-time feedback without WebSocket complexity |
| Hierarchical default layout | Best matches spine-leaf mental model |
| Position caching per view | Users arrange topology once, persists across mode switches |
| Pinch-to-zoom / scroll-to-pan | Natural trackpad interaction |
| CDP/LLDP-only physical topology | Avoids false positives from routing tables or ARP |
| Interface description as fallback only | Inferred connections marked differently from confirmed |
| Only show known-device BGP peers | Prevents thousands of external peer entries |
| Split landing page (upload left, prereqs right) | Users see what's needed while uploading |

---

## File Reference

| File | Lines | Purpose |
|------|-------|---------|
| `backend/main.py` | ~780 | FastAPI app, routing, file processing, migration integration |
| `backend/parsers/cdp_parser.py` | ~150 | CDP neighbor detail parsing (multi-vendor) |
| `backend/parsers/lldp_parser.py` | ~150 | LLDP neighbor detail parsing |
| `backend/parsers/interface_parser.py` | ~200 | Interface brief/status/description + inference |
| `backend/parsers/platform_parser.py` | ~180 | Device model/vendor/serial detection |
| `backend/parsers/config_parser.py` | ~250 | Running config parser (hostname, VLANs, PO, VPC) |
| `backend/parsers/bgp_parser.py` | ~200 | BGP summary, neighbors, config extraction |
| `backend/parsers/ospf_parser.py` | ~180 | OSPF overview, neighbors, interfaces |
| `backend/topology/builder.py` | ~350 | Physical topology construction + VLAN/SVI data |
| `backend/topology/routing_builder.py` | ~300 | BGP/OSPF logical topology graphs |
| `backend/migration/classifier.py` | ~160 | Role classification + phase suggestion + VNI mapping |
| `backend/migration/underlay_designer.py` | ~320 | Underlay/overlay design engine |
| `frontend/index.html` | ~200 | HTML structure, split upload panel, migration panel |
| `frontend/app.js` | ~2000 | Cytoscape.js integration, all UI logic, migration rendering |
| `frontend/styles.css` | ~1300 | Dark theme, layout styles, migration panel styles |
| `run.sh` | ~12 | Startup script (venv + uvicorn) |

---

## Dependencies

```
fastapi>=0.100.0
uvicorn[standard]>=0.22.0
python-multipart>=0.0.6
openpyxl>=3.1.0
```

Frontend (CDN, no npm):
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
