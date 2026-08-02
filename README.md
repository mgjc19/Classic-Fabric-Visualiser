# Classic Fabric Visualiser

Interactive network topology visualisation tool for traditional Ethernet fabrics. Upload device command outputs and instantly see your physical and logical network topology.

Built to support VXLAN migration planning by providing clear visibility into existing classical fabric architectures.

## Features

### Phase 1 — Physical Topology
- **Multi-vendor support**: Cisco IOS/IOS-XE/NX-OS, Arista, Juniper, Palo Alto, F5, Fortinet, Check Point, A10, Citrix
- **CDP/LLDP parsing**: Extracts neighbor relationships from `show cdp neighbors detail` and `show lldp neighbors detail`
- **Interface description fallback**: When CDP/LLDP is disabled, infers connections from interface descriptions matched against known devices
- **Port-Channel grouping**: Aggregates member links into a single visual "pipe" with member count labels
- **Link status indicators**: Green (up), red (down), amber (admin up/oper down)
- **Device role detection**: Automatically classifies switches, routers, firewalls, load balancers, WLCs, and border devices
- **Interactive canvas**: Click devices/links for detailed right-pane info, zoom (pinch), pan (scroll), multi-select (Ctrl+click or lasso)
- **Neighbor drill-down**: Click any neighbor in the Info tab to highlight the connected link/device on the canvas and expand peer details
- **Export**: PNG screenshot or Draw.io XML export for documentation
- **Hierarchical default layout**: Breadthfirst layout for clear spine/leaf visualization

### Phase 2 — Logical Topology
- **BGP visualisation**: Shows only confirmed BGP peerings between known devices (no stale/unresolvable entries)
- **OSPF visualisation**: Area grouping, adjacency states, interface costs
- **View switching**: Toggle between Physical, BGP, OSPF, and Migration views with position persistence

### Phase 3 — VXLAN Migration Planning
- **Device role classification**: Auto-assigns spine, leaf, border-leaf, service-leaf roles with confidence scoring
- **Hardware capability detection**: Identifies VXLAN-capable platforms (Nexus 9K, Catalyst 9K, Arista, QFX, etc.)
- **Underlay design engine**: Generates OSPF or eBGP underlay recommendations per device
- **Overlay design engine**: iBGP (with route-reflectors) or eBGP multihop EVPN overlay configuration
- **BGP address family selection**: L2VPN EVPN (required), IPv4 Unicast, IPv6 Unicast — user-configurable
- **VNI mapping**: Auto-generates VLAN-to-VNI mappings with full manual customisation
- **Migration phasing**: Auto-suggests migration phases (underlay → border → service → leaf → cleanup)
- **Live redesign**: Change underlay protocol or parameters and instantly see updated per-device recommendations

## Installation

### Prerequisites
- **Python 3.10+** (verify with `python3 --version`)
- **pip** (usually bundled with Python)
- **Git** (to clone the repository)
- A modern web browser (Chrome, Firefox, Safari, Edge)

### Option 1: Quick Start (Recommended)

```bash
# Clone the repository
git clone https://github.com/mgjc19/Classic-Fabric-Visualiser.git
cd Classic-Fabric-Visualiser

# Make the startup script executable
chmod +x run.sh

# Run (auto-creates venv and installs dependencies on first run)
./run.sh
```

The script will:
1. Create a Python virtual environment (`.venv/`)
2. Install all required packages from `backend/requirements.txt`
3. Start the server on **http://localhost:8765**

### Option 2: Manual Installation

```bash
# Clone the repository
git clone https://github.com/mgjc19/Classic-Fabric-Visualiser.git
cd Classic-Fabric-Visualiser

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r backend/requirements.txt

# Start the server
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8765 --reload
```

### Verify Installation

Once the server is running, open [http://localhost:8765](http://localhost:8765) in your browser. You should see the upload interface with guidelines for recommended file uploads.

### Stopping the Server

Press `Ctrl+C` in the terminal where the server is running.

## Usage

1. Open [http://localhost:8765](http://localhost:8765)
2. Upload device output files (drag & drop or click to browse)
3. The parsing animation shows real-time progress
4. Interact with the topology:
   - **Scroll** to pan the canvas
   - **Pinch** (trackpad) to zoom
   - **Click** a device to see details in the right pane
   - **Click a neighbor** in the Info tab to highlight the link on canvas
   - **Ctrl/Cmd + Click** to multi-select devices
   - **Drag** to lasso-select multiple devices
   - Use the **view dropdown** to toggle Connected/Isolated/All devices
   - Use the **topology mode** selector to switch between Physical/BGP/OSPF/Migration

### Migration Plan View

1. Switch to "Migration Plan" in the topology mode dropdown
2. The **Underlay Design** tab shows:
   - Protocol selector (OSPF or eBGP)
   - BGP address family checkboxes
   - Configurable ASN and OSPF area parameters
   - Per-device design recommendations (click to expand)
3. **VNI Mapping** tab shows auto-generated VLAN → VNI mappings
4. **Migration Phases** tab shows suggested rollout order
5. **Device Roles** tab shows classification with confidence scores

## Supported Command Outputs

Upload any combination of these — the more you provide, the richer the topology:

| Command | Purpose |
|---------|---------|
| `show cdp neighbors detail` | Physical connections (Cisco) |
| `show lldp neighbors detail` | Physical connections (multi-vendor) |
| `show ip interface brief` | Interface inventory and status |
| `show interface status` | Port operational state |
| `show interface description` | Fallback connection inference |
| `show version` / `show inventory` | Device model and vendor |
| `show running-config` | Port-channels, VPCs, routing config |
| `show vlan brief` | VLAN database for VNI mapping |
| `show ip bgp summary` | BGP peer relationships |
| `show bgp neighbors` | BGP peer details |
| `show ip ospf neighbor` | OSPF adjacencies |
| `show ip ospf` / `show ip ospf interface` | OSPF process and costs |
| `show port-channel summary` | Port-channel members (NX-OS) |
| `show vpc` / `show vpc brief` | VPC peer-link info |
| `show nve peers` | Existing VXLAN NVE peers |

### File Upload Formats

- **Individual files**: `.txt`, `.log`, `.cfg`
- **ZIP archives**: Upload a zip containing multiple device outputs
- **Excel files**: `.xlsx` with command outputs in cells
- **Folder upload**: Drag and drop entire folders

**Tip**: Name files with the device hostname for automatic detection (e.g., `N9K-SPINE-01_show_cdp.txt`). For Juniper, `show configuration | display set` works as running-config.

## Architecture

```
Classic-Fabric-Visualiser/
├── backend/
│   ├── main.py                 # FastAPI app, SSE streaming, file processing
│   ├── requirements.txt        # Python dependencies
│   ├── parsers/
│   │   ├── __init__.py         # Parser exports
│   │   ├── cdp_parser.py       # CDP neighbor parsing
│   │   ├── lldp_parser.py      # LLDP neighbor parsing
│   │   ├── interface_parser.py # Interface brief/status/description
│   │   ├── platform_parser.py  # Device model/vendor detection
│   │   ├── config_parser.py    # Running config parsing
│   │   ├── bgp_parser.py       # BGP summary/neighbors/config
│   │   └── ospf_parser.py      # OSPF overview/neighbors/interfaces
│   ├── topology/
│   │   ├── __init__.py         # Topology builder exports
│   │   ├── builder.py          # Physical topology construction
│   │   └── routing_builder.py  # BGP/OSPF logical topology
│   └── migration/
│       ├── __init__.py         # Migration module exports
│       ├── classifier.py       # Device role classification engine
│       └── underlay_designer.py # Underlay/overlay design engine
├── frontend/
│   ├── index.html              # Main UI (split layout: upload + prereqs)
│   ├── app.js                  # Cytoscape.js visualisation + migration panels
│   └── styles.css              # Dark theme styling
├── run.sh                      # One-command startup script
├── README.md                   # This file
└── PROJECT.md                  # Full project documentation
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Frontend | Vanilla JS, Cytoscape.js, HTML5/CSS3 |
| Streaming | Server-Sent Events (SSE) for real-time parsing progress |
| Layout | Cytoscape breadthfirst/cose/cola/grid algorithms |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 8765 already in use | Kill existing process: `lsof -ti:8765 \| xargs kill` then restart |
| Blank topology after upload | Hard refresh browser (Cmd+Shift+R), check browser console for errors |
| Devices showing as filenames | Ensure files contain a hostname prompt or `hostname` config line |
| Too many nodes in topology | Use the "Connected Devices" view filter dropdown |
| BGP view shows too many entries | Only peers resolvable to uploaded devices are shown |
| Migration panel empty | Ensure enough devices are uploaded for role classification |

## Roadmap

- [x] Phase 1: Physical topology visualisation
- [x] Phase 2: BGP and OSPF logical topology
- [x] Phase 3: VXLAN migration planning (underlay/overlay design engine)
- [ ] MPLS cloud icons in physical view
- [ ] Config generation (NX-OS CLI snippets)
- [ ] Docker deployment

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## License

MIT
