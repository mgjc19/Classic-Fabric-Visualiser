# Classic Fabric Visualiser & VXLAN Fabric Builder

A dual-mode network engineering platform for Cisco Nexus data centre fabrics.

**Tab 1** — Upload device command outputs and instantly visualise your existing physical/logical topology with VXLAN migration planning.  
**Tab 2** — Design new VXLAN EVPN fabrics from a hardware BOM, simulate traffic flows, and export production-ready NX-OS configurations.

![Platform](https://img.shields.io/badge/Platform-Cisco%20Nexus%209K-blue)
![Python](https://img.shields.io/badge/Python-3.10+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Quick Start

```bash
git clone https://github.com/mgjc19/Classic-Fabric-Visualiser.git
cd Classic-Fabric-Visualiser
chmod +x run.sh
./run.sh
# → http://localhost:8765
```

The script auto-creates a virtual environment and installs dependencies on first run.

---

## Tab 1: Classic Fabric Visualiser

Upload network device outputs and get an interactive topology map with VXLAN migration recommendations.

### Features

- **Multi-vendor parsing**: Cisco IOS/IOS-XE/NX-OS, Arista, Juniper, Palo Alto, F5, Fortinet, Check Point
- **CDP/LLDP topology discovery** with interface description fallback
- **Port-Channel grouping** and link status indicators (up/down/admin)
- **BGP and OSPF logical views** with confirmed-peers-only filtering
- **VXLAN Migration Planner**: auto role classification, underlay/overlay design (OSPF or eBGP), VNI mapping, phased migration plan
- **Interactive canvas**: zoom, pan, multi-select, lasso, hierarchical/force/grid layouts
- **Export**: PNG or Draw.io XML

### Supported Commands

| Command | Purpose |
|---------|---------|
| `show cdp neighbors detail` | Physical connections (Cisco) |
| `show lldp neighbors detail` | Physical connections (multi-vendor) |
| `show ip interface brief` | Interface inventory |
| `show running-config` | Port-channels, VPCs, routing |
| `show ip bgp summary` | BGP peerings |
| `show ip ospf neighbor` | OSPF adjacencies |
| `show vlan brief` | VLAN database for VNI mapping |

Upload as `.txt`, `.log`, `.cfg`, `.zip`, `.xlsx`, or drag folders.

---

## Tab 2: VXLAN Fabric Builder

Design, validate, and export complete VXLAN EVPN fabrics — from a simple hardware BOM to production-ready configurations with traffic-validated correctness.

### Key Advantages

| | |
|---|---|
| **BOM-to-Config in Minutes** | Upload a hardware list → fully configured VXLAN fabric |
| **Zero External Dependencies** | No DCNM, NDFC, or Terraform needed — standalone browser tool |
| **Validate Before Deploy** | Traffic simulation catches missing VNIs, VRFs, and gateways |
| **Multi-Site from Day One** | 2–4 site designs with proper DCI (BGP IPv4 unicast between BGWs) |
| **Failover Confidence** | Simulate device/link failures and verify ECMP reconvergence |
| **Interactive Design** | Drag, rename, connect, right-click — topology as a living document |
| **Standards-Compliant** | NX-OS best practices, IEEE 802.1Q, RFC 7348 (VXLAN), RFC 8365 (EVPN) |
| **Portable Output** | NX-OS CLI configs (ZIP) or YAML for automation pipelines (DDA format) |
| **Super-Spine Aware** | Auto-detects 5-stage Clos from 400G/high-radix PIDs |

### Capabilities

#### Hardware BOM Ingestion
- Auto-column detection for flexible CSV/Excel formats
- Recognises all Nexus 9000 PIDs (93xx, 9336, 9364, 9408, 9508, 9516)
- **Editable quantities** — adjust device counts before building
- **Role override** — change auto-inferred roles (spine/leaf/BGW/border-leaf/super-spine)
- Download a reference BOM template

#### Multi-Site Design
- Split inventory across 2–4 sites with independent IP addressing
- Per-site configurable: hostname prefixes, management/loopback/VTEP subnets
- **Automatic DCI links** between border gateway devices using BGP address-family IPv4 unicast
- Per-site ASN assignment for inter-site eBGP peering

#### Interactive Topology Editor
- **3-panel layout**: fabric summary (left), canvas (center), inspector/tools (right)
- Cytoscape.js graph: pan, pinch-zoom, scroll-zoom, manual +/−/fit buttons
- Site boundaries (dashed rectangles), DCI links (amber dashed), role-colored devices
- Right-click context menus, double-click rename, drag-to-connect
- Click any link to see port details; DCI links show BGP peering info
- Add/edit/remove endpoints (servers, LBs, FWs, WAN, storage, cloud gateways, SD-WAN)

#### Traffic Simulation
- Animated packet traversal: source endpoint → leaf → spine → leaf → destination
- **Path computation**: L2 local, L2 VXLAN (bridged), L3 VXLAN (symmetric IRB), inter-VRF detection
- **Full validation**: VLAN existence, VNI mapping, VRF presence, anycast gateway config
- **Detailed results**: source/dest IPs, VLANs, VRFs, L2/L3 VNIs, VTEP IPs, ECMP count, hop-by-hop routing path with encap/decap actions
- Color-coded: green source, amber destination, cyan encap, purple routing

#### Failover Simulation
- Inject device or link failures
- Port-channel and vPC aware reconvergence
- Compare original vs. failover paths
- Reports affected endpoints and convergence status

#### Configuration Generation

| Day | What's Generated |
|-----|-----------------|
| **Day-0** | Hostname, management, NTP, DNS, boot config (POAP-ready) |
| **Day-1** | OSPF/eBGP underlay, BGP EVPN overlay, NVE, VLANs, VRFs, SVIs, anycast GWs, vPC, port-channels, fabric interfaces |
| **Day-2** | SNMP, syslog, AAA/TACACS+, CoPP, NTP monitoring |
| **Multi-site** | DCI interfaces, BGP IPv4 unicast peering, EVPN multi-site |

#### Export Formats

| Format | Output |
|--------|--------|
| **NX-OS CLI** | Per-device `.cfg` files in a ZIP archive |
| **YAML (DDA)** | `data.tech-vxlan.yaml` + `data.tech-shared.yaml` for automation |

#### Terminal Interface
- Floating terminal windows — one per device
- Simulates `configure terminal` on the in-memory fabric model
- Changes reflected immediately in topology and config output

---

## Installation

### Prerequisites
- **Python 3.10+** (`python3 --version`)
- **pip** (bundled with Python)
- A modern web browser (Chrome, Firefox, Safari, Edge)

### Option 1: Quick Start (Recommended)

```bash
git clone https://github.com/mgjc19/Classic-Fabric-Visualiser.git
cd Classic-Fabric-Visualiser
chmod +x run.sh
./run.sh
```

### Option 2: Manual

```bash
git clone https://github.com/mgjc19/Classic-Fabric-Visualiser.git
cd Classic-Fabric-Visualiser
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8765 --reload
```

Open [http://localhost:8765](http://localhost:8765).

---

## Usage

### Tab 1 — Visualiser
1. Upload device output files (drag & drop or browse)
2. Parsing animation shows real-time progress
3. Interact: scroll to pan, pinch to zoom, click devices for details
4. Switch views: Physical → BGP → OSPF → Migration Plan
5. In Migration Plan: configure underlay protocol, review per-device designs, generate VNI mappings

### Tab 2 — Fabric Builder
1. Click **"Load Demo Topology"** to explore a pre-built multi-site fabric, or **"Upload BOM"** to import hardware
2. Edit device quantities, roles, and site configuration
3. Click **"Build Fabric"** to generate the topology
4. Interact with the canvas: move devices, add endpoints, edit properties
5. Use **Traffic Simulator** (right panel) to validate forwarding paths
6. Use **Failover** tools to test resilience
7. **Export** → NX-OS CLI (ZIP) or YAML (DDA Format)

---

## Architecture

```
Classic-Fabric-Visualiser/
├── backend/
│   ├── main.py                     # FastAPI — all API endpoints
│   ├── requirements.txt            # Python dependencies
│   ├── parsers/                    # CDP/LLDP/BGP/OSPF/config parsers
│   ├── topology/                   # Physical + logical topology builders
│   ├── migration/                  # Role classifier + underlay designer
│   └── fabric_builder/             # VXLAN Fabric Builder module
│       ├── fabric_model.py         # Core data model
│       ├── bom_parser.py           # BOM parsing + fabric generation
│       ├── config_engine.py        # Jinja2 config generation
│       ├── endpoint_model.py       # Endpoint types and connections
│       ├── traffic_engine.py       # L2/L3 VXLAN path computation
│       ├── failover_sim.py         # Failure injection + reconvergence
│       ├── nxos_exporter.py        # NX-OS CLI ZIP export
│       ├── yaml_exporter.py        # DDA YAML export
│       └── templates/              # Jinja2 NX-OS templates (Day 0/1/2)
├── frontend/
│   ├── index.html                  # Main HTML (both tabs)
│   ├── app.js                      # Visualiser frontend
│   ├── fabric-builder.js           # Fabric Builder frontend
│   └── styles.css                  # Unified dark-theme stylesheet
├── run.sh                          # One-command startup
├── README.md                       # This file
└── PROJECT.md                      # Full technical documentation
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, FastAPI, Uvicorn, Jinja2 |
| Frontend | Vanilla JS, Cytoscape.js, HTML5/CSS3 |
| Streaming | Server-Sent Events (real-time parsing) |
| Config | Jinja2 templates (NX-OS CLI syntax) |
| Export | ZIP (per-device configs), YAML (DDA) |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 8765 in use | `lsof -ti:8765 \| xargs kill` then restart |
| Blank topology | Hard refresh (Cmd+Shift+R), check console |
| BOM upload error | Ensure CSV/Excel contains Nexus 9K PIDs with quantity column |
| Traffic trace fails | Verify endpoints have VLAN/VRF configured and are connected to leaf switches |
| Devices not movable | Ensure you're on the Fabric Builder tab (not the upload panel) |

---

## Roadmap

- [x] Phase 1: Physical topology visualisation
- [x] Phase 2: BGP and OSPF logical topology
- [x] Phase 3: VXLAN migration planning
- [x] Phase 4: VXLAN Fabric Builder (BOM → Config)
  - [x] Hardware BOM parsing with PID recognition
  - [x] Multi-site design with DCI
  - [x] Interactive topology editor
  - [x] Traffic simulation with VXLAN validation
  - [x] Failover simulation
  - [x] NX-OS and YAML export
- [ ] Phase 5: Integration (migrate Tab 1 topology into Tab 2 for redesign)
- [ ] Docker deployment
- [ ] Ansible playbook generation from configs

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## License

MIT
