# Classic Fabric Visualiser & VXLAN Fabric Builder

A dual-purpose network engineering tool:
1. **Topology Visualiser** — Upload device command outputs and instantly see your physical and logical network topology
2. **VXLAN Fabric Builder** — Design, configure, and simulate VXLAN EVPN fabrics from a Bill of Materials or interactively from scratch

## Quick Start

```bash
git clone https://github.com/mgjc19/Classic-Fabric-Visualiser.git
cd Classic-Fabric-Visualiser
chmod +x run.sh && ./run.sh
```

Open [http://localhost:8765](http://localhost:8765) — switch between tabs using the header buttons.

---

## Tab 1: Topology Visualiser

Upload device command outputs to visualise existing fabric topologies.

### Features
- **Multi-vendor support**: Cisco IOS/IOS-XE/NX-OS, Arista, Juniper, Palo Alto, F5, Fortinet, Check Point, A10, Citrix
- **CDP/LLDP parsing**: Extracts neighbor relationships from `show cdp/lldp neighbors detail`
- **Interface description fallback**: Infers connections when CDP/LLDP is disabled
- **Port-Channel grouping**: Aggregates member links into a single visual "pipe"
- **BGP/OSPF visualisation**: Logical overlay views with area grouping and adjacency states
- **Interactive canvas**: Click, pan, zoom, multi-select, lasso, interface drill-down
- **Export**: PNG screenshot or Draw.io XML

### Supported Commands

| Command | Purpose |
|---------|---------|
| `show cdp neighbors detail` | Physical connections (Cisco) |
| `show lldp neighbors detail` | Physical connections (multi-vendor) |
| `show ip interface brief` | Interface inventory and status |
| `show running-config` | Port-channels, VPCs, routing config |
| `show ip bgp summary` | BGP peer relationships |
| `show ip ospf neighbor` | OSPF adjacencies |

---

## Tab 2: VXLAN Fabric Builder

Design and generate production-ready VXLAN EVPN fabric configurations following IEEE 802.1Q/RFC 7348 standards and Cisco Validated Designs.

### Key Capabilities

| Capability | Description |
|-----------|-------------|
| **BOM Upload** | Parse Nexus hardware BOMs (PIDs, SFPs, cables) and auto-generate a fabric topology |
| **Multi-Site Design** | Split hardware inventory across 2-4 sites with independent naming/IP schemes |
| **Interactive Designer** | 3-panel layout with drag-and-drop topology editing, right-click context menus |
| **Context-Aware CLI** | Full NX-OS-style terminal with nested sub-commands (interface, router bgp, vrf, nve, evpn, vpc) |
| **Real-Time Config Sync** | Terminal changes instantly reflect in generated config, topology canvas, and inspector |
| **Traffic Simulation** | L2/L3 VXLAN path tracing with VNI/VRF validation, ECMP paths, and hop-by-hop animation |
| **Failover Simulation** | Port-channel and vPC failure injection with reconvergence visualisation |
| **Multi-Format Export** | NX-OS CLI (.cfg ZIP), YAML (DDA Format), XML (NETCONF-style) |
| **Nexus Dashboard Push** | Authenticate to NDFC and push device-level or full-topology configs directly |

### Terminal CLI (NX-OS Style)

The terminal supports proper hierarchical command contexts with abbreviation expansion:

```
DC1-LEAF-01(config)# int eth1/48
DC1-LEAF-01(config-if:Ethernet1/48)# desc To Server-Rack-A
DC1-LEAF-01(config-if:Ethernet1/48)# switchport mode trunk
DC1-LEAF-01(config-if:Ethernet1/48)# switchport trunk allowed vlan 100-110
DC1-LEAF-01(config-if:Ethernet1/48)# exit
DC1-LEAF-01(config)# router bgp 65001
DC1-LEAF-01(config-router)# neighbor 10.0.0.1
DC1-LEAF-01(config-router-neighbor)# remote-as 65000
DC1-LEAF-01(config-router-neighbor)# address-family l2vpn evpn
DC1-LEAF-01(config-router-neighbor-af)# send-community both
DC1-LEAF-01(config-router-neighbor-af)# end
DC1-LEAF-01(config)# show run
```

**Supported contexts**: config → interface, router bgp (→ neighbor → address-family, vrf), vrf context, interface nve1 (→ member vni), evpn, vpc domain

**Abbreviations**: `int eth1/48`, `sh run`, `no shut`, `ro bgp 65000`, `sw mode trunk`, `desc ...`, `nei`, `lo0`, `po10`

### Configuration Generation

Generates complete Day-0, Day-1, and Day-2 NX-OS configurations:

- **Day-0**: Boot config, features, system settings, spanning-tree, MTU, anycast-gateway MAC
- **Day-1**: Loopbacks, fabric interfaces, OSPF underlay, BGP EVPN overlay, VXLAN/NVE, VRFs, VLANs, SVIs, vPC
- **Day-2**: NTP, DNS, syslog, SNMP, AAA/TACACS+, CoPP
- **Multi-site**: Border Gateway configuration with DCI peering (IPv4 unicast transport + L2VPN EVPN), `evpn multisite border-gateway`, `rewrite-evpn-rt-asn`
- **CLI additions**: Any interface, BGP neighbor, VRF, NVE member, or feature configured via terminal is merged into the generated config

### Export Formats

| Format | Contents |
|--------|----------|
| **NX-OS CLI** | Per-device `.cfg` files in a ZIP archive |
| **YAML (DDA)** | `data.tech-vxlan.yaml` + `data.tech-shared.yaml` |
| **XML (NETCONF)** | NETCONF-style XML per device (System, Interfaces, BGP, VRFs, NVE, vPC) |
| **Nexus Dashboard** | Direct push to NDFC via authenticated API |

### Traffic Simulation

- Select source and destination endpoints (servers, LBs, firewalls, storage, etc.)
- Validates VXLAN forwarding: VNI lookup, VRF routing, VTEP encap/decap
- Animated packet traversal showing the full path from source endpoint through leaf → spine → leaf to destination
- Detailed results: hop-by-hop routing path, ingress/egress VTEPs, L2/L3 VNIs, ECMP paths

### Endpoint Types

Servers, Load Balancers, Firewalls, WAN/Edge Routers, Storage Arrays, Backup Appliances, Cloud Gateways (DCI/EVPN-to-cloud), SD-WAN Edges, and custom types with distinct icons.

---

## Installation

### Prerequisites
- **Python 3.10+**
- **pip**
- A modern web browser (Chrome, Firefox, Safari, Edge)

### Quick Install

```bash
git clone https://github.com/mgjc19/Classic-Fabric-Visualiser.git
cd Classic-Fabric-Visualiser
chmod +x run.sh && ./run.sh
```

The script creates a virtual environment, installs dependencies, and starts the server on **http://localhost:8765**.

### Manual Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8765 --reload
```

---

## Architecture

```
Classic-Fabric-Visualiser/
├── backend/
│   ├── main.py                     # FastAPI app + Fabric Builder API (CLI, export, ND push)
│   ├── requirements.txt            # Python dependencies
│   ├── fabric_builder/
│   │   ├── bom_parser.py           # Hardware BOM parsing (PIDs, SFPs, cables)
│   │   ├── config_engine.py        # Jinja2-based NX-OS config generation
│   │   ├── fabric_model.py         # Central data model (devices, links, overlay)
│   │   ├── traffic_engine.py       # L2/L3 VXLAN path computation
│   │   ├── failover_sim.py         # vPC/port-channel failover simulation
│   │   ├── endpoint_model.py       # Endpoint management
│   │   ├── nxos_exporter.py        # NX-OS CLI ZIP export
│   │   ├── yaml_exporter.py        # DDA YAML export
│   │   └── templates/              # Jinja2 templates (base, interfaces, ospf, bgp, vxlan, vpc, multisite, day2)
│   └── migration/                  # Classic-to-VXLAN migration classifier
├── frontend/
│   ├── index.html                  # Dual-tab UI (Visualiser + Fabric Builder)
│   ├── app.js                      # Topology Visualiser logic
│   ├── fabric-builder.js           # Fabric Builder (canvas, terminals, traffic sim, ND)
│   └── styles.css                  # Dark theme
├── run.sh                          # One-command startup
└── README.md
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, FastAPI, Uvicorn, Jinja2, httpx |
| Frontend | Vanilla JS, Cytoscape.js, HTML5/CSS3 |
| Config Gen | Jinja2 templates following CVD/IEEE standards |
| Export | ZIP (NX-OS/YAML/XML), Nexus Dashboard REST API |

---

## API Reference (Fabric Builder)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/fabric/upload-bom` | POST | Upload BOM file (Excel/CSV) |
| `/api/fabric/build-from-hardware` | POST | Generate topology from hardware inventory |
| `/api/fabric/cli-command` | POST | Execute NX-OS CLI command on a device |
| `/api/fabric/config/{device_id}` | GET | Get generated config for a device |
| `/api/fabric/export/nxos` | GET | Download NX-OS configs (ZIP) |
| `/api/fabric/export/yaml` | GET | Download YAML (DDA format ZIP) |
| `/api/fabric/export/xml` | GET | Download XML configs (ZIP) |
| `/api/fabric/export/xml/{device_id}` | GET | Download single device XML |
| `/api/nd/authenticate` | POST | Authenticate to Nexus Dashboard |
| `/api/nd/push-config` | POST | Push config to NDFC |
| `/api/fabric/traffic/trace` | POST | Trace traffic path |
| `/api/fabric/failover/simulate` | POST | Simulate link failure |

---

## Roadmap

- [x] Phase 1: Physical topology visualisation
- [x] Phase 2: BGP and OSPF logical topology
- [x] Phase 3: VXLAN migration planning
- [x] Phase 4: VXLAN Fabric Builder (BOM, CLI, config gen, traffic sim, ND push)
- [ ] Phase 5: Integration — migrate visualised classic fabric directly into Fabric Builder

## License

MIT
