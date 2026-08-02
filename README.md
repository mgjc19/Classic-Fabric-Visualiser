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
- **Interactive canvas**: Click devices/links for detailed right-pane info, zoom (Ctrl/Cmd+scroll), pan (scroll), multi-select (Ctrl+click or lasso)
- **Interface drill-down**: Click any interface in the detail pane to highlight the connected link and device on the canvas
- **Export**: PNG screenshot or Draw.io XML export for documentation

### Phase 2 — Logical Topology
- **BGP visualisation**: Shows only confirmed BGP peerings between known devices (no stale/unresolvable entries)
- **OSPF visualisation**: Area grouping, adjacency states, interface costs
- **View switching**: Toggle between Physical, BGP, and OSPF views with position persistence

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

### Option 3: Docker (coming soon)

```bash
docker build -t fabric-visualiser .
docker run -p 8765:8765 fabric-visualiser
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
   - **Ctrl/Cmd + Scroll** to zoom
   - **Click** a device to see details in the right pane
   - **Click an interface** in the Interfaces tab to highlight the link on canvas
   - **Ctrl/Cmd + Click** to multi-select devices
   - **Drag** to lasso-select multiple devices
   - Use the **view dropdown** to toggle Connected/Isolated/All devices
   - Use the **topology mode** selector to switch between Physical/BGP/OSPF

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
| `show ip bgp summary` | BGP peer relationships |
| `show ip bgp neighbors` | BGP peer details |
| `show ip ospf neighbor` | OSPF adjacencies |
| `show ip ospf interface` | OSPF interface costs |

### File Upload Formats

- **Individual files**: `.txt`, `.log`, `.cfg`
- **ZIP archives**: Upload a zip containing multiple device outputs
- **Excel files**: `.xlsx` with command outputs in cells
- **Folder upload**: Drag and drop entire folders

**Tip**: Name files with the device hostname for automatic detection (e.g., `spine-01_cdp_neighbors.txt`, `rdl1cr2_show_version.txt`).

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
│   └── topology/
│       ├── __init__.py         # Topology builder exports
│       ├── builder.py          # Physical topology construction
│       └── routing_builder.py  # BGP/OSPF logical topology
├── frontend/
│   ├── index.html              # Main UI
│   ├── app.js                  # Cytoscape.js visualisation logic
│   └── styles.css              # Dark theme styling
├── run.sh                      # One-command startup script
└── README.md
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Frontend | Vanilla JS, Cytoscape.js, HTML5/CSS3 |
| Streaming | Server-Sent Events (SSE) for real-time parsing progress |
| Layout | Cytoscape cose/cola/grid algorithms |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 8765 already in use | Kill existing process: `lsof -ti:8765 \| xargs kill` then restart |
| Blank topology after upload | Hard refresh browser (Cmd+Shift+R), check browser console for errors |
| Devices showing as filenames | Ensure files contain a hostname prompt or `hostname` config line |
| Too many nodes in topology | Use the "Connected Devices" view filter dropdown |
| BGP view shows too many entries | Only peers resolvable to uploaded devices are shown |

## Roadmap

- [x] Phase 1: Physical topology visualisation
- [x] Phase 2: BGP and OSPF logical topology
- [ ] Phase 3: VXLAN migration planning and overlay placement

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## License

MIT
