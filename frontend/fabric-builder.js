/**
 * Fabric Builder - Interactive Fabric Designer with Traffic Simulation
 * 3-Panel layout: Left (summary), Center (canvas), Right (inspector/tools)
 */
(function () {
    "use strict";

    var API_BASE = "";
    var fabricModel = null;
    var fabricCy = null;
    var currentFbStep = "overview";
    var currentFbTab = "properties";
    var selectedFbDevice = null;
    var deviceConfigs = {};
    var fabricEndpoints = [];
    var fabricFlows = [];
    var fabricEvents = [];

    var ROLE_COLORS = {
        super_spine: "#ec4899",
        spine: "#6366f1",
        leaf: "#10b981",
        border_leaf: "#8b5cf6",
        border_gateway: "#f59e0b",
        service_leaf: "#06b6d4",
        oob_switch: "#64748b"
    };

    var ENDPOINT_TYPES = {
        server: { shape: "ellipse", color: "#db61a2", label: "Server" },
        vm_host: { shape: "ellipse", color: "#c084fc", label: "VM Host" },
        load_balancer: { shape: "diamond", color: "#22d3ee", label: "Load Balancer" },
        firewall: { shape: "hexagon", color: "#f87171", label: "Firewall" },
        wan_router: { shape: "round-rectangle", color: "#fb923c", label: "WAN Router" },
        edge_router: { shape: "round-rectangle", color: "#a3e635", label: "Edge Router" },
        storage: { shape: "barrel", color: "#d29922", label: "Storage" },
        backup: { shape: "barrel", color: "#78716c", label: "Backup" },
        cloud_gw: { shape: "round-pentagon", color: "#60a5fa", label: "Cloud Gateway" },
        dci_gw: { shape: "round-pentagon", color: "#818cf8", label: "DCI Gateway" },
        sdwan_edge: { shape: "round-triangle", color: "#34d399", label: "SD-WAN Edge" }
    };

    function $(id) { return document.getElementById(id); }

    function initFabricBuilder() {
        var mainTabs = document.querySelectorAll(".main-tab-btn");
        mainTabs.forEach(function (btn) {
            btn.addEventListener("click", function () {
                mainTabs.forEach(function (b) { b.classList.remove("active"); });
                btn.classList.add("active");
                switchMainTab(btn.getAttribute("data-maintab"));
            });
        });

        var dropZone = $("fb-drop-zone");
        var fileInput = $("fb-file-input");

        dropZone.addEventListener("click", function () { fileInput.click(); });
        $("fb-btn-browse").addEventListener("click", function (e) {
            e.stopPropagation();
            fileInput.click();
        });
        $("fb-btn-template").addEventListener("click", downloadTemplate);
        $("fb-btn-quickstart").addEventListener("click", showQuickStart);

        fileInput.addEventListener("change", function (e) {
            if (e.target.files.length > 0) uploadBom(e.target.files[0]);
            e.target.value = "";
        });

        dropZone.addEventListener("dragover", function (e) {
            e.preventDefault();
            dropZone.classList.add("drag-over");
        });
        dropZone.addEventListener("dragleave", function () {
            dropZone.classList.remove("drag-over");
        });
        dropZone.addEventListener("drop", function (e) {
            e.preventDefault();
            dropZone.classList.remove("drag-over");
            if (e.dataTransfer.files.length > 0) uploadBom(e.dataTransfer.files[0]);
        });

        $("fb-btn-new-bom").addEventListener("click", resetFabricBuilder);
        $("fb-btn-upload-bom").addEventListener("click", function () {
            $("fb-file-input").click();
        });

        // Auto-load demo topology on first visit
        loadDemoTopology();

        document.querySelectorAll(".fb-step-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                document.querySelectorAll(".fb-step-btn").forEach(function (b) { b.classList.remove("active"); });
                btn.classList.add("active");
                switchFbStep(btn.getAttribute("data-fbstep"));
            });
        });

        // Zoom controls
        $("fb-zoom-in").addEventListener("click", function () {
            if (fabricCy) fabricCy.zoom({ level: fabricCy.zoom() * 1.25, renderedPosition: { x: fabricCy.width() / 2, y: fabricCy.height() / 2 } });
        });
        $("fb-zoom-out").addEventListener("click", function () {
            if (fabricCy) fabricCy.zoom({ level: fabricCy.zoom() * 0.8, renderedPosition: { x: fabricCy.width() / 2, y: fabricCy.height() / 2 } });
        });
        $("fb-zoom-fit").addEventListener("click", function () {
            if (fabricCy) fabricCy.fit(undefined, 40);
        });

        document.querySelectorAll("[data-fbtab]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var parent = btn.parentElement;
                parent.querySelectorAll(".tab-btn").forEach(function (b) { b.classList.remove("active"); });
                btn.classList.add("active");
                currentFbTab = btn.getAttribute("data-fbtab");
                renderFbDetail();
            });
        });

        $("fb-export-nxos").addEventListener("click", function () {
            window.location.href = API_BASE + "/api/fabric/export/nxos";
        });
        $("fb-export-yaml").addEventListener("click", function () {
            window.location.href = API_BASE + "/api/fabric/export/yaml";
        });

        initRightPanel();
        initResizeHandle();
        initTerminalDockResize();
    }

    /* ========== RIGHT PANEL INITIALIZATION ========== */

    function initRightPanel() {
        document.querySelectorAll(".fb-section-toggle").forEach(function (toggle) {
            toggle.addEventListener("click", function () {
                var sectionId = toggle.getAttribute("data-section");
                if (!sectionId) return;
                var body = $(sectionId);
                if (body) body.hidden = !body.hidden;
            });
        });

        document.querySelectorAll(".fb-ls-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                document.querySelectorAll(".fb-ls-btn").forEach(function (b) { b.classList.remove("active"); });
                btn.classList.add("active");
                var curve = btn.getAttribute("data-curve");
                if (fabricCy) {
                    fabricCy.edges().style("curve-style", curve);
                }
            });
        });

        $("fb-submit-add-switch").addEventListener("click", addSwitch);
        $("fb-submit-add-link").addEventListener("click", addLink);
        $("fb-submit-add-ep").addEventListener("click", addEndpoint);
        $("fb-traffic-trace").addEventListener("click", traceTraffic);
        $("fb-traffic-clear").addEventListener("click", clearTrafficFlows);
    }

    function initResizeHandle() {
        var handle = $("fb-resize-handle");
        var rightPanel = $("fb-panel-right");
        var dragging = false;
        var startX = 0;
        var startWidth = 0;

        handle.addEventListener("mousedown", function (e) {
            dragging = true;
            startX = e.clientX;
            startWidth = rightPanel.offsetWidth;
            handle.classList.add("active");
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";
            e.preventDefault();
        });

        document.addEventListener("mousemove", function (e) {
            if (!dragging) return;
            var diff = startX - e.clientX;
            var newWidth = Math.max(220, Math.min(500, startWidth + diff));
            rightPanel.style.width = newWidth + "px";
        });

        document.addEventListener("mouseup", function () {
            if (!dragging) return;
            dragging = false;
            handle.classList.remove("active");
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
        });
    }

    /* ========== MAIN TAB SWITCHING ========== */

    function switchMainTab(tab) {
        var mainContent = document.querySelector(".main-content");
        var builderTab = $("fabric-builder-tab");
        var legend = $("legend");

        if (tab === "visualiser") {
            mainContent.hidden = false;
            builderTab.hidden = true;
            if (legend) legend.hidden = !document.querySelector("#topology-panel:not([hidden])");
        } else {
            mainContent.hidden = true;
            builderTab.hidden = false;
            if (legend) legend.hidden = true;
            if (fabricCy) {
                setTimeout(function () {
                    fabricCy.resize();
                    fabricCy.fit(undefined, 50);
                }, 100);
            } else if (fabricModel) {
                setTimeout(function () { renderFabricOverview(); }, 50);
            }
        }
    }

    function downloadTemplate() {
        window.location.href = API_BASE + "/api/fabric/template";
    }

    /* ========== BOM UPLOAD ========== */

    function uploadBom(file) {
        $("fb-loading").hidden = false;
        var dropZone = $("fb-drop-zone");
        dropZone.style.display = "none";
        var formData = new FormData();
        formData.append("file", file);

        fetch(API_BASE + "/api/fabric/upload-bom", { method: "POST", body: formData })
            .then(function (r) {
                if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "Upload failed"); });
                return r.json();
            })
            .then(function (data) {
                $("fb-loading").hidden = true;
                if (data.type === "hardware") {
                    showHardwareDesignScreen(data);
                } else {
                    fabricModel = data;
                    $("fb-upload-panel").hidden = true;
                    $("fb-main-panel").hidden = false;
                    renderFabricOverview();
                }
            })
            .catch(function (err) {
                $("fb-loading").hidden = true;
                dropZone.style.display = "";
                alert("BOM Upload Error: " + err.message);
            });
    }

    function resetFabricBuilder() {
        fabricModel = null;
        deviceConfigs = {};
        selectedFbDevice = null;
        fabricEndpoints = [];
        fabricFlows = [];
        if (fabricCy) { fabricCy.destroy(); fabricCy = null; }
        $("fb-upload-panel").hidden = false;
        $("fb-main-panel").hidden = true;
        var hw = $("fb-hardware-panel");
        if (hw) hw.hidden = true;
    }

    /* ========== HARDWARE DESIGN SCREEN ========== */

    var hardwareData = null;
    var _siteConfigs = [];

    function showHardwareDesignScreen(data) {
        hardwareData = data.hardware;
        $("fb-upload-panel").hidden = true;

        var panel = $("fb-hardware-panel");
        if (!panel) {
            panel = document.createElement("div");
            panel.id = "fb-hardware-panel";
            panel.className = "fb-hardware-panel";
            $("fabric-builder-tab").appendChild(panel);
        }
        panel.hidden = false;

        var switches = hardwareData.switches || [];
        var sfps = hardwareData.sfps || [];
        var cables = hardwareData.cables || [];
        var summary = hardwareData.summary || {};
        var totalSwitchQty = switches.reduce(function (s, sw) { return s + (sw.quantity || 0); }, 0);
        var suggestedSites = totalSwitchQty > 12 ? 2 : 1;

        var switchRows = switches.map(function (s, idx) {
            var model = s.model_info || {};
            return '<tr><td>' + s.pid + '</td><td>' + (model.description || s.description || '-') + '</td>' +
                '<td><input type="number" class="hw-qty-input" data-idx="' + idx + '" data-type="switch" value="' + s.quantity + '" min="0" max="99" style="width:52px"></td>' +
                '<td><select class="hw-role-select" data-idx="' + idx + '">' +
                '<option value="super_spine"' + (s.inferred_role === 'super_spine' ? ' selected' : '') + '>Super-Spine</option>' +
                '<option value="spine"' + (s.inferred_role === 'spine' ? ' selected' : '') + '>Spine</option>' +
                '<option value="leaf"' + (s.inferred_role === 'leaf' ? ' selected' : '') + '>Leaf</option>' +
                '<option value="border_leaf"' + (s.inferred_role === 'border_leaf' ? ' selected' : '') + '>Border Leaf</option>' +
                '<option value="border_gateway"' + (s.inferred_role === 'border_gateway' ? ' selected' : '') + '>Border Gateway</option>' +
                '</select></td></tr>';
        }).join("");

        var sfpRows = sfps.map(function (s, idx) {
            var info = s.sfp_info || {};
            return '<tr><td>' + s.pid + '</td><td>' + (info.speed || '') + ' ' + (info.type || '') + '</td>' +
                '<td><input type="number" class="hw-qty-input" data-idx="' + idx + '" data-type="sfp" value="' + s.quantity + '" min="0" max="9999" style="width:64px"></td></tr>';
        }).join("");

        var cableRows = cables.map(function (c, idx) {
            return '<tr><td>' + c.pid + '</td><td>' + (c.description || '-') + '</td>' +
                '<td><input type="number" class="hw-qty-input" data-idx="' + idx + '" data-type="cable" value="' + c.quantity + '" min="0" max="9999" style="width:64px"></td></tr>';
        }).join("");

        panel.innerHTML =
            '<div class="hw-design-header">' +
            '<h2>Hardware BOM Detected \u2014 Fabric Design</h2>' +
            '<p>Your BOM contains <strong>' + summary.total_switches + ' switches</strong>, ' +
            '<strong>' + summary.total_sfps + ' SFPs</strong>, ' +
            '<strong>' + summary.total_cables + ' cables</strong>. Configure sites and roles below, then build.</p></div>' +
            '<div class="hw-design-body">' +
            '<div class="hw-section"><h3>Switches & Roles</h3>' +
            '<table class="fb-table"><thead><tr><th>PID</th><th>Description</th><th>Qty</th><th>Role</th></tr></thead><tbody>' + switchRows + '</tbody></table></div>' +
            (sfpRows ? '<div class="hw-section"><h3>Transceivers</h3><table class="fb-table"><thead><tr><th>PID</th><th>Type</th><th>Qty</th></tr></thead><tbody>' + sfpRows + '</tbody></table></div>' : '') +
            (cableRows ? '<div class="hw-section"><h3>Cables</h3><table class="fb-table"><thead><tr><th>PID</th><th>Description</th><th>Qty</th></tr></thead><tbody>' + cableRows + '</tbody></table></div>' : '') +
            '<div class="hw-section"><h3>Site Configuration</h3>' +
            '<div class="hw-site-controls"><label>Number of Sites <select id="hw-num-sites">' +
            '<option value="1"' + (suggestedSites === 1 ? ' selected' : '') + '>1 (Single-Site)</option>' +
            '<option value="2"' + (suggestedSites === 2 ? ' selected' : '') + '>2 (Multi-Site)</option>' +
            '<option value="3">3</option><option value="4">4</option></select></label></div>' +
            '<div id="hw-sites-container"></div></div>' +
            '<div class="hw-actions"><button class="btn btn-primary" id="hw-build-btn">Build Fabric</button>' +
            '<button class="btn btn-secondary" id="hw-back-btn">Back</button></div></div>';

        document.getElementById("hw-num-sites").addEventListener("change", renderSiteConfigs);
        document.getElementById("hw-build-btn").addEventListener("click", buildFromHardware);
        document.getElementById("hw-back-btn").addEventListener("click", function () {
            panel.hidden = true;
            $("fb-upload-panel").hidden = false;
        });
        renderSiteConfigs();
    }

    function renderSiteConfigs() {
        var numSites = parseInt(document.getElementById("hw-num-sites").value) || 1;
        var container = document.getElementById("hw-sites-container");
        var siteNames = ["DC1", "DC2", "DC3", "DC4"];
        var mgmtBases = ["10.1.0", "10.2.0", "10.3.0", "10.4.0"];
        var loBases = ["10.1.255", "10.2.255", "10.3.255", "10.4.255"];
        var vtepBases = ["10.1.254", "10.2.254", "10.3.254", "10.4.254"];

        _siteConfigs = [];
        for (var i = 0; i < numSites; i++) {
            _siteConfigs.push({
                site: siteNames[i], sspine_prefix: siteNames[i] + "-SSPINE",
                spine_prefix: siteNames[i] + "-SPINE", leaf_prefix: siteNames[i] + "-LEAF",
                bleaf_prefix: siteNames[i] + "-BLEAF", bgw_prefix: siteNames[i] + "-BGW",
                mgmt_subnet: mgmtBases[i], loopback_subnet: loBases[i], vtep_subnet: vtepBases[i]
            });
        }

        var html = '<div class="hw-sites-grid">';
        for (var i = 0; i < numSites; i++) {
            var sn = siteNames[i];
            html += '<div class="hw-site-card"><h4>Site ' + (i + 1) + '</h4><div class="hw-params-grid">' +
                '<label>Site Name<input type="text" class="hw-site-name" data-site="' + i + '" value="' + sn + '"></label>' +
                '<label>Super-Spine Prefix<input type="text" class="hw-site-sspine-prefix" data-site="' + i + '" value="' + sn + '-SSPINE"></label>' +
                '<label>Spine Prefix<input type="text" class="hw-site-spine-prefix" data-site="' + i + '" value="' + sn + '-SPINE"></label>' +
                '<label>Leaf Prefix<input type="text" class="hw-site-leaf-prefix" data-site="' + i + '" value="' + sn + '-LEAF"></label>' +
                '<label>Border Leaf Prefix<input type="text" class="hw-site-bleaf-prefix" data-site="' + i + '" value="' + sn + '-BLEAF"></label>' +
                '<label>BGW Prefix<input type="text" class="hw-site-bgw-prefix" data-site="' + i + '" value="' + sn + '-BGW"></label>' +
                '<label>Mgmt Subnet<input type="text" class="hw-site-mgmt" data-site="' + i + '" value="' + mgmtBases[i] + '"></label>' +
                '<label>Loopback Subnet<input type="text" class="hw-site-lo" data-site="' + i + '" value="' + loBases[i] + '"></label>' +
                '<label>VTEP Subnet<input type="text" class="hw-site-vtep" data-site="' + i + '" value="' + vtepBases[i] + '"></label>' +
                '</div></div>';
        }
        html += '</div>';
        if (numSites > 1) html += '<p class="hw-multisite-note">Multi-site: inventory will be split evenly across sites.</p>';
        container.innerHTML = html;
    }

    function buildFromHardware() {
        // Read edited roles and quantities from the UI (before filtering)
        var roleSelects = document.querySelectorAll(".hw-role-select");
        roleSelects.forEach(function (sel) {
            var idx = parseInt(sel.dataset.idx);
            if (hardwareData.switches[idx]) {
                hardwareData.switches[idx].role_hint = sel.value;
                hardwareData.switches[idx].inferred_role = sel.value;
            }
        });
        document.querySelectorAll('.hw-qty-input').forEach(function (inp) {
            var idx = parseInt(inp.dataset.idx);
            var type = inp.dataset.type;
            var val = parseInt(inp.value) || 0;
            if (type === "switch" && hardwareData.switches[idx]) {
                hardwareData.switches[idx].quantity = val;
            } else if (type === "sfp" && hardwareData.sfps && hardwareData.sfps[idx]) {
                hardwareData.sfps[idx].quantity = val;
            } else if (type === "cable" && hardwareData.cables && hardwareData.cables[idx]) {
                hardwareData.cables[idx].quantity = val;
            }
        });
        // Remove rows with 0 quantity
        hardwareData.switches = hardwareData.switches.filter(function (s) { return s.quantity > 0; });
        if (hardwareData.sfps) hardwareData.sfps = hardwareData.sfps.filter(function (s) { return s.quantity > 0; });
        if (hardwareData.cables) hardwareData.cables = hardwareData.cables.filter(function (c) { return c.quantity > 0; });

        var numSites = parseInt((document.getElementById("hw-num-sites") || {}).value) || 1;
        var sites = [];
        for (var i = 0; i < numSites; i++) {
            var defaults = _siteConfigs[i] || { site: "DC" + (i + 1) };
            var nameEl = document.querySelector('.hw-site-name[data-site="' + i + '"]');
            var sspineEl = document.querySelector('.hw-site-sspine-prefix[data-site="' + i + '"]');
            var spineEl = document.querySelector('.hw-site-spine-prefix[data-site="' + i + '"]');
            var leafEl = document.querySelector('.hw-site-leaf-prefix[data-site="' + i + '"]');
            var bleafEl = document.querySelector('.hw-site-bleaf-prefix[data-site="' + i + '"]');
            var bgwEl = document.querySelector('.hw-site-bgw-prefix[data-site="' + i + '"]');
            var mgmtEl = document.querySelector('.hw-site-mgmt[data-site="' + i + '"]');
            var loEl = document.querySelector('.hw-site-lo[data-site="' + i + '"]');
            var vtepEl = document.querySelector('.hw-site-vtep[data-site="' + i + '"]');
            sites.push({
                site: (nameEl && nameEl.value) || defaults.site,
                sspine_prefix: (sspineEl && sspineEl.value) || defaults.sspine_prefix,
                spine_prefix: (spineEl && spineEl.value) || defaults.spine_prefix,
                leaf_prefix: (leafEl && leafEl.value) || defaults.leaf_prefix,
                bleaf_prefix: (bleafEl && bleafEl.value) || defaults.bleaf_prefix,
                bgw_prefix: (bgwEl && bgwEl.value) || defaults.bgw_prefix,
                mgmt_subnet: (mgmtEl && mgmtEl.value) || defaults.mgmt_subnet,
                loopback_subnet: (loEl && loEl.value) || defaults.loopback_subnet,
                vtep_subnet: (vtepEl && vtepEl.value) || defaults.vtep_subnet
            });
        }

        $("fb-loading").hidden = false;
        fetch(API_BASE + "/api/fabric/build-from-hardware", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ hardware: hardwareData, sites: sites })
        })
            .then(function (r) {
                if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "Build failed"); });
                return r.json();
            })
            .then(function (data) {
                $("fb-loading").hidden = true;
                fabricModel = data;
                $("fb-hardware-panel").hidden = true;
                $("fb-main-panel").hidden = false;
                renderFabricOverview();
                addEvent("Fabric built from hardware BOM");
            })
            .catch(function (err) {
                $("fb-loading").hidden = true;
                alert("Build Error: " + err.message);
            });
    }

    function showQuickStart() {
        loadDemoTopology();
    }

    function loadDemoTopology() {
        var demoFabric = {
            devices: [
                { id: "sp1", hostname: "DC1-SPINE-01", role: "spine", model: "N9K-C9336C-FX2", site: "DC1", mgmt_ip: "10.1.0.1/24", loopback0: "10.1.255.1/32", loopback1: "", asn: "65000", vpc_domain: "", vpc_peer: "", interfaces: [] },
                { id: "sp2", hostname: "DC1-SPINE-02", role: "spine", model: "N9K-C9336C-FX2", site: "DC1", mgmt_ip: "10.1.0.2/24", loopback0: "10.1.255.2/32", loopback1: "", asn: "65000", vpc_domain: "", vpc_peer: "", interfaces: [] },
                { id: "lf1", hostname: "DC1-LEAF-01", role: "leaf", model: "N9K-C93180YC-FX", site: "DC1", mgmt_ip: "10.1.0.11/24", loopback0: "10.1.255.11/32", loopback1: "10.1.254.11/32", asn: "65001", vpc_domain: "1", vpc_peer: "DC1-LEAF-02", interfaces: [] },
                { id: "lf2", hostname: "DC1-LEAF-02", role: "leaf", model: "N9K-C93180YC-FX", site: "DC1", mgmt_ip: "10.1.0.12/24", loopback0: "10.1.255.12/32", loopback1: "10.1.254.12/32", asn: "65002", vpc_domain: "1", vpc_peer: "DC1-LEAF-01", interfaces: [] },
                { id: "lf3", hostname: "DC1-LEAF-03", role: "leaf", model: "N9K-C93180YC-FX", site: "DC1", mgmt_ip: "10.1.0.13/24", loopback0: "10.1.255.13/32", loopback1: "10.1.254.13/32", asn: "65003", vpc_domain: "2", vpc_peer: "DC1-LEAF-04", interfaces: [] },
                { id: "lf4", hostname: "DC1-LEAF-04", role: "leaf", model: "N9K-C93180YC-FX", site: "DC1", mgmt_ip: "10.1.0.14/24", loopback0: "10.1.255.14/32", loopback1: "10.1.254.14/32", asn: "65004", vpc_domain: "2", vpc_peer: "DC1-LEAF-03", interfaces: [] },
                { id: "bgw1", hostname: "DC1-BGW-01", role: "border_gateway", model: "N9K-C9364C-GX", site: "DC1", mgmt_ip: "10.1.0.31/24", loopback0: "10.1.255.31/32", loopback1: "10.1.254.31/32", loopback2: "192.168.1.31/32", asn: "65005", vpc_domain: "", vpc_peer: "", interfaces: [] },
                { id: "sp3", hostname: "DC2-SPINE-01", role: "spine", model: "N9K-C9336C-FX2", site: "DC2", mgmt_ip: "10.2.0.1/24", loopback0: "10.2.255.1/32", loopback1: "", asn: "65100", vpc_domain: "", vpc_peer: "", interfaces: [] },
                { id: "sp4", hostname: "DC2-SPINE-02", role: "spine", model: "N9K-C9336C-FX2", site: "DC2", mgmt_ip: "10.2.0.2/24", loopback0: "10.2.255.2/32", loopback1: "", asn: "65100", vpc_domain: "", vpc_peer: "", interfaces: [] },
                { id: "lf5", hostname: "DC2-LEAF-01", role: "leaf", model: "N9K-C93180YC-FX", site: "DC2", mgmt_ip: "10.2.0.11/24", loopback0: "10.2.255.11/32", loopback1: "10.2.254.11/32", asn: "65101", vpc_domain: "1", vpc_peer: "DC2-LEAF-02", interfaces: [] },
                { id: "lf6", hostname: "DC2-LEAF-02", role: "leaf", model: "N9K-C93180YC-FX", site: "DC2", mgmt_ip: "10.2.0.12/24", loopback0: "10.2.255.12/32", loopback1: "10.2.254.12/32", asn: "65102", vpc_domain: "1", vpc_peer: "DC2-LEAF-01", interfaces: [] },
                { id: "lf7", hostname: "DC2-LEAF-03", role: "leaf", model: "N9K-C93180YC-FX", site: "DC2", mgmt_ip: "10.2.0.13/24", loopback0: "10.2.255.13/32", loopback1: "10.2.254.13/32", asn: "65103", vpc_domain: "2", vpc_peer: "DC2-LEAF-04", interfaces: [] },
                { id: "lf8", hostname: "DC2-LEAF-04", role: "leaf", model: "N9K-C93180YC-FX", site: "DC2", mgmt_ip: "10.2.0.14/24", loopback0: "10.2.255.14/32", loopback1: "10.2.254.14/32", asn: "65104", vpc_domain: "2", vpc_peer: "DC2-LEAF-03", interfaces: [] },
                { id: "bgw2", hostname: "DC2-BGW-01", role: "border_gateway", model: "N9K-C9364C-GX", site: "DC2", mgmt_ip: "10.2.0.31/24", loopback0: "10.2.255.31/32", loopback1: "10.2.254.31/32", loopback2: "192.168.2.31/32", asn: "65105", vpc_domain: "", vpc_peer: "", interfaces: [] }
            ],
            links: [
                { id: "l1", from_device: "DC1-SPINE-01", from_port: "Eth1/1", to_device: "DC1-LEAF-01", to_port: "Eth1/49", speed: "100G", cable_type: "" },
                { id: "l2", from_device: "DC1-SPINE-01", from_port: "Eth1/2", to_device: "DC1-LEAF-02", to_port: "Eth1/49", speed: "100G", cable_type: "" },
                { id: "l3", from_device: "DC1-SPINE-01", from_port: "Eth1/3", to_device: "DC1-LEAF-03", to_port: "Eth1/49", speed: "100G", cable_type: "" },
                { id: "l4", from_device: "DC1-SPINE-01", from_port: "Eth1/4", to_device: "DC1-LEAF-04", to_port: "Eth1/49", speed: "100G", cable_type: "" },
                { id: "l5", from_device: "DC1-SPINE-01", from_port: "Eth1/5", to_device: "DC1-BGW-01", to_port: "Eth1/49", speed: "100G", cable_type: "" },
                { id: "l6", from_device: "DC1-SPINE-02", from_port: "Eth1/1", to_device: "DC1-LEAF-01", to_port: "Eth1/50", speed: "100G", cable_type: "" },
                { id: "l7", from_device: "DC1-SPINE-02", from_port: "Eth1/2", to_device: "DC1-LEAF-02", to_port: "Eth1/50", speed: "100G", cable_type: "" },
                { id: "l8", from_device: "DC1-SPINE-02", from_port: "Eth1/3", to_device: "DC1-LEAF-03", to_port: "Eth1/50", speed: "100G", cable_type: "" },
                { id: "l9", from_device: "DC1-SPINE-02", from_port: "Eth1/4", to_device: "DC1-LEAF-04", to_port: "Eth1/50", speed: "100G", cable_type: "" },
                { id: "l10", from_device: "DC1-SPINE-02", from_port: "Eth1/5", to_device: "DC1-BGW-01", to_port: "Eth1/50", speed: "100G", cable_type: "" },
                { id: "l11", from_device: "DC2-SPINE-01", from_port: "Eth1/1", to_device: "DC2-LEAF-01", to_port: "Eth1/49", speed: "100G", cable_type: "" },
                { id: "l12", from_device: "DC2-SPINE-01", from_port: "Eth1/2", to_device: "DC2-LEAF-02", to_port: "Eth1/49", speed: "100G", cable_type: "" },
                { id: "l13", from_device: "DC2-SPINE-01", from_port: "Eth1/3", to_device: "DC2-LEAF-03", to_port: "Eth1/49", speed: "100G", cable_type: "" },
                { id: "l14", from_device: "DC2-SPINE-01", from_port: "Eth1/4", to_device: "DC2-LEAF-04", to_port: "Eth1/49", speed: "100G", cable_type: "" },
                { id: "l15", from_device: "DC2-SPINE-01", from_port: "Eth1/5", to_device: "DC2-BGW-01", to_port: "Eth1/49", speed: "100G", cable_type: "" },
                { id: "l16", from_device: "DC2-SPINE-02", from_port: "Eth1/1", to_device: "DC2-LEAF-01", to_port: "Eth1/50", speed: "100G", cable_type: "" },
                { id: "l17", from_device: "DC2-SPINE-02", from_port: "Eth1/2", to_device: "DC2-LEAF-02", to_port: "Eth1/50", speed: "100G", cable_type: "" },
                { id: "l18", from_device: "DC2-SPINE-02", from_port: "Eth1/3", to_device: "DC2-LEAF-03", to_port: "Eth1/50", speed: "100G", cable_type: "" },
                { id: "l19", from_device: "DC2-SPINE-02", from_port: "Eth1/4", to_device: "DC2-LEAF-04", to_port: "Eth1/50", speed: "100G", cable_type: "" },
                { id: "l20", from_device: "DC2-SPINE-02", from_port: "Eth1/5", to_device: "DC2-BGW-01", to_port: "Eth1/50", speed: "100G", cable_type: "" },
                { id: "dci1", from_device: "DC1-BGW-01", from_port: "Eth1/48", to_device: "DC2-BGW-01", to_port: "Eth1/48", speed: "100G", cable_type: "DCI", protocol: "BGP", bgp_address_family: "ipv4 unicast", from_asn: "65500", to_asn: "65501" }
            ],
            overlay: {
                vrfs: [
                    { name: "TENANT-1", vni: 50001, rd: "auto", rt_import: "auto", rt_export: "auto" }
                ],
                vlans: [
                    { vlan_id: 10, name: "Web-Servers", vni: 10010, vrf: "TENANT-1", svi_ip: "10.10.10.1/24", anycast_gw: "10.10.10.1/24" },
                    { vlan_id: 20, name: "App-Servers", vni: 10020, vrf: "TENANT-1", svi_ip: "10.10.20.1/24", anycast_gw: "10.10.20.1/24" },
                    { vlan_id: 30, name: "DB-Servers", vni: 10030, vrf: "TENANT-1", svi_ip: "10.10.30.1/24", anycast_gw: "10.10.30.1/24" }
                ],
                vnis: [
                    { vni: 10010, vlan_id: 10, vrf: "TENANT-1", mcast_group: "239.1.1.10", is_l3vni: false },
                    { vni: 10020, vlan_id: 20, vrf: "TENANT-1", mcast_group: "239.1.1.20", is_l3vni: false },
                    { vni: 10030, vlan_id: 30, vrf: "TENANT-1", mcast_group: "239.1.1.30", is_l3vni: false },
                    { vni: 50001, vlan_id: 0, vrf: "TENANT-1", mcast_group: "", is_l3vni: true }
                ]
            },
            sites: ["DC1", "DC2"],
            multisite: true,
            global_config: {
                nxos_version: "10.3(4a)", underlay_protocol: "ospf", ospf_area: "0.0.0.0",
                bgp_asn_scheme: "unique_per_leaf", spine_asn: 65000, leaf_asn_start: 65001,
                anycast_gw_mac: "0000.2222.3333", nve_source: "loopback1",
                vpc_keepalive_vrf: "management", multisite_anycast_gw: ""
            },
            day2_config: {
                ntp_servers: ["10.1.100.1", "10.1.100.2"], dns_servers: ["10.1.100.10"],
                dns_domain: "dc.local", syslog_servers: ["10.1.100.20"],
                snmp_community: "", snmp_user: "snmpadmin", snmp_auth: "SHA", snmp_priv: "AES-128",
                tacacs_servers: ["10.1.100.30"], tacacs_key: "", aaa_group: "TACACS-SERVERS"
            }
        };

        // Pre-load demo endpoints
        fabricEndpoints = [
            { id: "srv1", type: "server", name: "Web-Server-01", ip: "10.10.10.10/24", vlan: "10", vrf: "TENANT-1", mode: "vpc", connected_to: [{ device: "DC1-LEAF-01", port: "Eth1/1" }, { device: "DC1-LEAF-02", port: "Eth1/1" }], site: "DC1" },
            { id: "srv2", type: "server", name: "Web-Server-02", ip: "10.10.10.11/24", vlan: "10", vrf: "TENANT-1", mode: "single", connected_to: [{ device: "DC1-LEAF-01", port: "Eth1/2" }], site: "DC1" },
            { id: "app1", type: "server", name: "App-Server-01", ip: "10.10.20.10/24", vlan: "20", vrf: "TENANT-1", mode: "vpc", connected_to: [{ device: "DC1-LEAF-03", port: "Eth1/1" }, { device: "DC1-LEAF-04", port: "Eth1/1" }], site: "DC1" },
            { id: "lb1", type: "load_balancer", name: "LB-01", ip: "10.10.10.100/24", vlan: "10", vrf: "TENANT-1", mode: "vpc", connected_to: [{ device: "DC1-LEAF-01", port: "Eth1/5" }, { device: "DC1-LEAF-02", port: "Eth1/5" }], site: "DC1" },
            { id: "fw1", type: "firewall", name: "FW-01", ip: "10.10.10.254/24", vlan: "10", vrf: "TENANT-1", mode: "vpc", connected_to: [{ device: "DC1-LEAF-03", port: "Eth1/5" }, { device: "DC1-LEAF-04", port: "Eth1/5" }], site: "DC1" },
            { id: "stor1", type: "storage", name: "NAS-01", ip: "10.10.30.50/24", vlan: "30", vrf: "TENANT-1", mode: "vpc", connected_to: [{ device: "DC2-LEAF-01", port: "Eth1/1" }, { device: "DC2-LEAF-02", port: "Eth1/1" }], site: "DC2" },
            { id: "db1", type: "server", name: "DB-Server-01", ip: "10.10.30.10/24", vlan: "30", vrf: "TENANT-1", mode: "single", connected_to: [{ device: "DC2-LEAF-03", port: "Eth1/1" }], site: "DC2" },
            { id: "wan1", type: "wan_router", name: "WAN-Edge-01", ip: "172.16.0.1/30", vlan: "", vrf: "", mode: "single", connected_to: [{ device: "DC1-BGW-01", port: "Eth1/1" }], site: "DC1" }
        ];

        fabricModel = demoFabric;
        $("fb-upload-panel").hidden = true;
        $("fb-main-panel").hidden = false;

        renderFabricOverview();
        addEvent("Demo multi-site fabric loaded (DC1 + DC2)");
        addEvent("DCI link active: DC1-BGW-01 \u2194 DC2-BGW-01");
        addEvent("8 endpoints pre-configured");

        // Sync demo state to backend for traffic/failover simulation
        fetch("/api/fabric/load-demo", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                devices: demoFabric.devices,
                links: demoFabric.links,
                overlay: demoFabric.overlay,
                global_config: demoFabric.global_config,
                day2_config: demoFabric.day2_config,
                sites: demoFabric.sites,
                multisite: demoFabric.multisite,
                endpoints: fabricEndpoints
            })
        }).catch(function () {});
    }

    /* ========== STEP SWITCHING ========== */

    function switchFbStep(step) {
        currentFbStep = step;
        var panelCenter = document.querySelector(".fb-panel-center");
        if (panelCenter) {
            $("fb-canvas").hidden = (step === "export");
            $("fb-overlay-panel").hidden = (step !== "overlay");
            $("fb-export-panel").hidden = (step !== "export");
        }
        if (step === "overview" || step === "config") {
            renderFabricCanvas();
        } else if (step === "overlay") {
            renderOverlayEditor();
        }
    }

    /* ========== FABRIC OVERVIEW + LEFT PANEL ========== */

    function renderFabricOverview() {
        var stats = $("fb-stats");
        if (fabricModel) {
            var devCount = fabricModel.devices.length;
            var linkCount = fabricModel.links.length;
            var siteList = fabricModel.sites || [];
            var siteCount = siteList.length;
            var siteInfo = siteCount > 1 ? ", " + siteCount + " sites (" + siteList.join(", ") + ")" : "";
            stats.textContent = devCount + " devices, " + linkCount + " links" + siteInfo;
        }
        renderLeftPanel();
        renderFabricCanvas();
        populateSelectors();
    }

    function renderLeftPanel() {
        if (!fabricModel) return;
        var devices = fabricModel.devices || [];
        var links = fabricModel.links || [];
        var endpoints = fabricEndpoints || [];

        var spines = devices.filter(function (d) { return d.role === "spine" || d.role === "super_spine"; }).length;
        var leaves = devices.filter(function (d) { return d.role === "leaf" || d.role === "border_leaf"; }).length;
        var vrfs = (fabricModel.overlay && fabricModel.overlay.vrfs) ? fabricModel.overlay.vrfs.length : 0;
        var vlans = (fabricModel.overlay && fabricModel.overlay.vlans) ? fabricModel.overlay.vlans.length : 0;
        var siteCount = (fabricModel.sites || []).length || 1;

        var statGrid = $("fb-stat-grid");
        statGrid.innerHTML =
            '<div class="fb-stat-card"><div class="fb-stat-val">' + devices.length + '</div><div class="fb-stat-label">Switches</div></div>' +
            '<div class="fb-stat-card"><div class="fb-stat-val">' + links.length + '</div><div class="fb-stat-label">Links</div></div>' +
            '<div class="fb-stat-card"><div class="fb-stat-val">' + endpoints.length + '</div><div class="fb-stat-label">Endpoints</div></div>' +
            '<div class="fb-stat-card"><div class="fb-stat-val">' + vrfs + '</div><div class="fb-stat-label">VRFs</div></div>' +
            '<div class="fb-stat-card"><div class="fb-stat-val">' + spines + '</div><div class="fb-stat-label">Spines</div></div>' +
            '<div class="fb-stat-card"><div class="fb-stat-val">' + leaves + '</div><div class="fb-stat-label">Leaves</div></div>' +
            '<div class="fb-stat-card"><div class="fb-stat-val">' + siteCount + '</div><div class="fb-stat-label">Sites</div></div>' +
            '<div class="fb-stat-card"><div class="fb-stat-val">' + vlans + '</div><div class="fb-stat-label">VLANs</div></div>';

        var vpcList = $("fb-vpc-list");
        var vpcDomains = {};
        devices.forEach(function (d) {
            if (d.vpc_domain) {
                if (!vpcDomains[d.vpc_domain]) vpcDomains[d.vpc_domain] = [];
                vpcDomains[d.vpc_domain].push(d.hostname);
            }
        });
        var vpcHtml = "";
        Object.keys(vpcDomains).forEach(function (dom) {
            vpcHtml += '<div class="fb-list-item"><span>Domain ' + dom + '</span><span>' + vpcDomains[dom].join(", ") + '</span></div>';
        });
        vpcList.innerHTML = vpcHtml || '<div class="fb-hint">No vPC domains</div>';

        var overlaySummary = $("fb-overlay-summary");
        var overlayHtml = '<div class="fb-list-item"><span>VRFs</span><span>' + vrfs + '</span></div>' +
            '<div class="fb-list-item"><span>L2 VNIs</span><span>' + vlans + '</span></div>';
        overlaySummary.innerHTML = overlayHtml;

        renderEventsLog();
    }

    function renderEventsLog() {
        var log = $("fb-events-log");
        if (!log) return;
        var html = "";
        fabricEvents.slice(-20).reverse().forEach(function (ev) {
            html += '<div class="fb-event"><span class="ev-time">' + ev.time + '</span><span class="ev-msg">' + escHtml(ev.msg) + '</span></div>';
        });
        log.innerHTML = html || '<div class="fb-hint">No events yet</div>';
    }

    function addEvent(msg) {
        var now = new Date();
        var t = String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
        fabricEvents.push({ time: t, msg: msg });
        renderEventsLog();
    }

    /* ========== FABRIC CANVAS ========== */

    var _fbWheelHandler = null;
    function renderFabricCanvas() {
        if (!fabricModel) return;
        var container = $("fb-canvas");
        container.hidden = false;

        if (_fbWheelHandler) {
            container.removeEventListener("wheel", _fbWheelHandler);
            _fbWheelHandler = null;
        }
        if (fabricCy) fabricCy.destroy();

        var elements = buildFabricElements();

        fabricCy = cytoscape({
            container: container,
            elements: elements,
            style: [
                {
                    selector: "node[nodeType='switch']",
                    style: {
                        "label": "data(label)",
                        "text-valign": "bottom",
                        "text-margin-y": 8,
                        "font-size": "10px",
                        "font-family": "'Inter', sans-serif",
                        "color": "#e2e8f0",
                        "background-color": "data(color)",
                        "shape": "round-rectangle",
                        "width": 90,
                        "height": 36,
                        "text-wrap": "ellipsis",
                        "text-max-width": "85px",
                        "border-width": 2,
                        "border-color": "#334155"
                    }
                },
                {
                    selector: "node[nodeType='endpoint']",
                    style: {
                        "label": "data(label)",
                        "text-valign": "bottom",
                        "text-margin-y": 6,
                        "font-size": "9px",
                        "font-family": "'Inter', sans-serif",
                        "color": "#cbd5e1",
                        "background-color": "data(color)",
                        "shape": "data(shape)",
                        "width": 32,
                        "height": 32,
                        "border-width": 1,
                        "border-color": "#475569"
                    }
                },
                {
                    selector: "node:selected",
                    style: {
                        "border-color": "#38bdf8",
                        "border-width": 3,
                        "background-color": "#1e3a5f"
                    }
                },
                {
                    selector: "node:grabbed",
                    style: {
                        "border-color": "#facc15",
                        "border-width": 3,
                        "overlay-opacity": 0.08,
                        "overlay-color": "#facc15"
                    }
                },
                {
                    selector: "node:active",
                    style: {
                        "overlay-opacity": 0.05,
                        "overlay-color": "#38bdf8"
                    }
                },
                {
                    selector: "edge",
                    style: {
                        "width": 2,
                        "line-color": "#475569",
                        "curve-style": "bezier",
                        "target-arrow-shape": "none"
                    }
                },
                {
                    selector: "edge.flow-active",
                    style: {
                        "line-color": "#22d3ee",
                        "width": 3,
                        "line-style": "dashed",
                        "line-dash-pattern": [6, 3]
                    }
                },
                {
                    selector: "edge.flow-failed",
                    style: {
                        "line-color": "#ef4444",
                        "width": 3,
                        "line-style": "dashed"
                    }
                },
                {
                    selector: "edge.link-down",
                    style: {
                        "line-color": "#ef4444",
                        "line-style": "dashed",
                        "opacity": 0.5
                    }
                },
                {
                    selector: "node.flow-active",
                    style: {
                        "border-color": "#22d3ee",
                        "border-width": 3
                    }
                },
                {
                    selector: "node.flow-src",
                    style: {
                        "border-color": "#10b981",
                        "border-width": 4,
                        "border-style": "double"
                    }
                },
                {
                    selector: "node.flow-dst",
                    style: {
                        "border-color": "#f59e0b",
                        "border-width": 4,
                        "border-style": "double"
                    }
                },
                {
                    selector: "node.flow-packet",
                    style: {
                        "width": 14,
                        "height": 14,
                        "shape": "ellipse",
                        "background-color": "#22d3ee",
                        "border-color": "#fff",
                        "border-width": 2,
                        "z-index": 9999,
                        "label": "",
                        "events": "no"
                    }
                },
                {
                    selector: "node[nodeType='site_boundary']",
                    style: {
                        "shape": "round-rectangle",
                        "width": "data(boundW)",
                        "height": "data(boundH)",
                        "background-color": "#1e293b",
                        "background-opacity": 0.3,
                        "border-width": 2,
                        "border-color": "#334155",
                        "border-style": "dashed",
                        "label": "data(label)",
                        "text-valign": "top",
                        "text-halign": "center",
                        "text-margin-y": 15,
                        "font-size": "18px",
                        "font-weight": "bold",
                        "color": "#94a3b8",
                        "z-index": 0,
                        "events": "no"
                    }
                },
                {
                    selector: "edge[cable_type='DCI']",
                    style: {
                        "line-color": "#f59e0b",
                        "width": 4,
                        "line-style": "dashed",
                        "line-dash-pattern": [10, 5],
                        "curve-style": "unbundled-bezier",
                        "target-arrow-shape": "triangle",
                        "target-arrow-color": "#f59e0b",
                        "source-arrow-shape": "triangle",
                        "source-arrow-color": "#f59e0b",
                        "z-index": 100
                    }
                }
            ],
            layout: { name: "preset" },
            minZoom: 0.1,
            maxZoom: 5,
            userZoomingEnabled: false,
            userPanningEnabled: true,
            panningEnabled: true,
            zoomingEnabled: true,
            boxSelectionEnabled: false,
            autoungrabify: false,
            autolock: false
        });

        positionNodes();

        // Ensure all switch/endpoint nodes are grabbable (movable)
        fabricCy.nodes().forEach(function (n) {
            var nt = n.data("nodeType");
            if (nt === "site_boundary") {
                n.ungrabify();
                n.unselectify();
                n.lock();
            } else {
                n.grabbable(true);
                n.selectable(true);
            }
        });

        // Custom wheel: scroll=pan, ctrl/cmd+scroll=zoom
        _fbWheelHandler = function (e) {
            e.preventDefault();
            if (e.ctrlKey || e.metaKey) {
                var zoomFactor = e.deltaY > 0 ? 0.97 : 1.03;
                var rect = container.getBoundingClientRect();
                var pos = { x: e.clientX - rect.left, y: e.clientY - rect.top };
                fabricCy.zoom({ level: fabricCy.zoom() * zoomFactor, renderedPosition: pos });
            } else {
                fabricCy.panBy({ x: -e.deltaX - (e.shiftKey ? e.deltaY : 0), y: e.shiftKey ? 0 : -e.deltaY });
            }
        };
        container.addEventListener("wheel", _fbWheelHandler, { passive: false });

        fabricCy.on("tap", "node", function (evt) {
            var data = evt.target.data();
            if (data.nodeType === "switch") {
                selectedFbDevice = data.deviceId;
                openFbDetail(selectedFbDevice);
                addEvent("Selected: " + data.label);
            } else if (data.nodeType === "endpoint") {
                showEndpointInspector(data.endpointId);
                addEvent("Selected: " + data.label);
            }
        });

        fabricCy.on("tap", "edge", function (evt) {
            var d = evt.target.data();
            showLinkInspector(d);
            addEvent("Link: " + d.from_device + " ↔ " + d.to_device);
        });

        fabricCy.on("tap", function (evt) {
            if (evt.target === fabricCy) {
                closeFbDetail();
            }
        });

        fabricCy.on("cxttap", "node", function (evt) {
            showContextMenu(evt.originalEvent, "node", evt.target.data());
        });
        fabricCy.on("cxttap", "edge", function (evt) {
            showContextMenu(evt.originalEvent, "edge", evt.target.data());
        });
        fabricCy.on("cxttap", function (evt) {
            if (evt.target === fabricCy) {
                showContextMenu(evt.originalEvent, "canvas", null);
            }
        });

        // Double-tap to inline rename
        fabricCy.on("dbltap", "node", function (evt) {
            var node = evt.target;
            var data = node.data();
            if (data.nodeType === "switch") {
                inlineEditLabel(node, data.deviceId);
            }
        });

        // Cursor feedback for grabbable nodes
        fabricCy.on("mouseover", "node[nodeType='switch'], node[nodeType='endpoint']", function () {
            container.style.cursor = "grab";
        });
        fabricCy.on("mouseout", "node[nodeType='switch'], node[nodeType='endpoint']", function () {
            container.style.cursor = "";
        });
        fabricCy.on("grab", "node", function () {
            container.style.cursor = "grabbing";
        });
        fabricCy.on("free", "node", function () {
            container.style.cursor = "";
        });

        // Force resize after delays to ensure canvas hit detection works
        // (container may have been hidden at initial render)
        [200, 500, 1000].forEach(function (delay) {
            setTimeout(function () {
                if (fabricCy) {
                    fabricCy.resize();
                    fabricCy.nodes().forEach(function (n) {
                        if (n.data("nodeType") !== "site_boundary") {
                            n.grabbable(true);
                        }
                    });
                }
            }, delay);
        });

        // ResizeObserver: auto-resize Cytoscape whenever the container dimensions change
        if (window.ResizeObserver) {
            var ro = new ResizeObserver(function () {
                if (fabricCy) fabricCy.resize();
            });
            ro.observe(container);
        }
    }

    function positionNodes() {
        if (!fabricCy || !fabricModel) return;
        var sites = fabricModel.sites || ["site-1"];
        var numSites = sites.length;
        var siteWidth = 1200;
        var siteGap = 400;
        var tierYMap = { 0: 0, 1: 200, 2: 400, 3: 400, 4: 400, 5: 600, 6: 800, 7: 950 };
        var siteNodeCounts = {};

        fabricCy.nodes().forEach(function (node) {
            var site = node.data("site") || sites[0];
            var tier = node.data("tier");
            var siteIdx = sites.indexOf(site);
            if (siteIdx < 0) siteIdx = 0;
            var key = siteIdx + "-" + tier;
            if (!siteNodeCounts[key]) siteNodeCounts[key] = { count: 0, current: 0 };
            siteNodeCounts[key].count++;
        });

        fabricCy.nodes().forEach(function (node) {
            var site = node.data("site") || sites[0];
            var tier = node.data("tier");
            var siteIdx = sites.indexOf(site);
            if (siteIdx < 0) siteIdx = 0;
            var key = siteIdx + "-" + tier;
            var info = siteNodeCounts[key];
            var xOffset = siteIdx * (siteWidth + siteGap);
            var spacing = siteWidth / (info.count + 1);
            info.current++;
            var x = xOffset + spacing * info.current;
            var y = tierYMap[tier] !== undefined ? tierYMap[tier] : 600;
            node.position({ x: x, y: y });
        });

        // Add site boundary boxes and labels for multi-site
        fabricCy.nodes("[nodeType='site_boundary']").remove();
        if (numSites > 1) {
            for (var s = 0; s < numSites; s++) {
                var xOff = s * (siteWidth + siteGap);
                // Calculate bounding box from actual node positions in this site
                var siteNodes = fabricCy.nodes().filter(function (n) {
                    return n.data("site") === sites[s] && n.data("nodeType") !== "site_boundary";
                });
                var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
                siteNodes.forEach(function (n) {
                    var pos = n.position();
                    minX = Math.min(minX, pos.x);
                    maxX = Math.max(maxX, pos.x);
                    minY = Math.min(minY, pos.y);
                    maxY = Math.max(maxY, pos.y);
                });
                var pad = 80;
                var bw = Math.max(400, maxX - minX + pad * 2);
                var bh = Math.max(300, maxY - minY + pad * 2);
                var cx = (minX + maxX) / 2;
                var cy = (minY + maxY) / 2;

                fabricCy.add({
                    group: "nodes",
                    data: {
                        id: "site-bg-" + s,
                        label: sites[s],
                        nodeType: "site_boundary",
                        site: sites[s],
                        boundW: bw,
                        boundH: bh
                    },
                    position: { x: cx, y: cy },
                    selectable: false,
                    grabbable: false
                });
            }
        }

        fabricCy.fit(undefined, 50);
    }

    function buildFabricElements() {
        var nodes = [];
        var edges = [];
        if (!fabricModel) return { nodes: nodes, edges: edges };

        var tierOrder = { super_spine: 0, spine: 1, border_gateway: 2, border_leaf: 3, service_leaf: 4, leaf: 5, oob_switch: 6 };

        fabricModel.devices.forEach(function (dev) {
            nodes.push({
                data: {
                    id: dev.id,
                    label: dev.hostname,
                    deviceId: dev.id,
                    nodeType: "switch",
                    color: ROLE_COLORS[dev.role] || "#64748b",
                    tier: tierOrder[dev.role] !== undefined ? tierOrder[dev.role] : 5,
                    site: dev.site || ""
                }
            });
        });

        fabricEndpoints.forEach(function (ep) {
            var epType = ENDPOINT_TYPES[ep.type] || ENDPOINT_TYPES.server;
            nodes.push({
                data: {
                    id: "ep-" + ep.id,
                    label: ep.name,
                    endpointId: ep.id,
                    nodeType: "endpoint",
                    color: epType.color,
                    shape: epType.shape,
                    tier: 7,
                    site: ep.site || ""
                }
            });
            if (ep.connected_to) {
                ep.connected_to.forEach(function (conn) {
                    var targetDev = fabricModel.devices.find(function (d) { return d.hostname === conn.device || d.id === conn.device; });
                    if (targetDev) {
                        edges.push({
                            data: {
                                id: "ep-link-" + ep.id + "-" + targetDev.id,
                                source: "ep-" + ep.id,
                                target: targetDev.id
                            }
                        });
                    }
                });
            }
        });

        fabricModel.links.forEach(function (link) {
            var fromDev = fabricModel.devices.find(function (d) { return d.hostname === link.from_device; });
            var toDev = fabricModel.devices.find(function (d) { return d.hostname === link.to_device; });
            if (fromDev && toDev) {
                edges.push({
                    data: {
                        id: link.id,
                        source: fromDev.id,
                        target: toDev.id,
                        cable_type: link.cable_type || "",
                        speed: link.speed || "",
                        protocol: link.protocol || "",
                        bgp_address_family: link.bgp_address_family || "",
                        from_asn: link.from_asn || "",
                        to_asn: link.to_asn || "",
                        from_port: link.from_port || "",
                        to_port: link.to_port || "",
                        from_device: link.from_device || "",
                        to_device: link.to_device || ""
                    }
                });
            }
        });

        return { nodes: nodes, edges: edges };
    }

    /* ========== POPULATE SELECTORS ========== */

    function populateSelectors() {
        if (!fabricModel) return;
        var devices = fabricModel.devices || [];
        var leaves = devices.filter(function (d) { return d.role === "leaf" || d.role === "border_leaf" || d.role === "service_leaf"; });

        var linkFromSel = $("fb-add-link-from");
        var linkToSel = $("fb-add-link-to");
        var epLeafSel = $("fb-add-ep-leaf");

        var devOptions = '<option value="">Select...</option>' + devices.map(function (d) {
            return '<option value="' + d.id + '">' + escHtml(d.hostname) + '</option>';
        }).join("");

        if (linkFromSel) linkFromSel.innerHTML = devOptions;
        if (linkToSel) linkToSel.innerHTML = devOptions;

        var leafOptions = '<option value="">Select leaf...</option>' + leaves.map(function (d) {
            return '<option value="' + d.id + '">' + escHtml(d.hostname) + '</option>';
        }).join("");
        if (epLeafSel) epLeafSel.innerHTML = leafOptions;

        var trafficSrc = $("fb-traffic-src");
        var trafficDst = $("fb-traffic-dst");
        var epOptions = '<option value="">Select endpoint...</option>' + fabricEndpoints.map(function (ep) {
            return '<option value="' + ep.id + '">' + escHtml(ep.name) + '</option>';
        }).join("");
        if (trafficSrc) trafficSrc.innerHTML = epOptions;
        if (trafficDst) trafficDst.innerHTML = epOptions;
    }

    /* ========== CONTEXT MENU ========== */

    function showContextMenu(event, target, data) {
        hideContextMenu();
        event.preventDefault();

        var menu = document.createElement("div");
        menu.className = "fb-context-menu";
        menu.id = "fb-context-menu";

        var items = [];
        if (target === "node" && data.nodeType === "switch") {
            items = [
                { label: "Inspect", action: function () { openFbDetail(data.deviceId); } },
                { label: "Open Terminal", action: function () { openTerminalWindow(data.deviceId); } },
                { label: "Rename", action: function () { promptRenameDevice(data.deviceId); } },
                { label: "Simulate Failure", action: function () { simulateDeviceFailure(data.deviceId); } },
                { sep: true },
                { label: "Remove", action: function () { removeDevice(data.deviceId); }, danger: true }
            ];
        } else if (target === "node" && data.nodeType === "endpoint") {
            items = [
                { label: "Inspect", action: function () { showEndpointInspector(data.endpointId); } },
                { label: "Trace Traffic", action: function () { presetTrafficSource(data.endpointId); } },
                { label: "Simulate Link Failure", action: function () { simulateEndpointLinkFailure(data.endpointId); } },
                { sep: true },
                { label: "Remove", action: function () { removeEndpoint(data.endpointId); }, danger: true }
            ];
        } else if (target === "edge") {
            items = [
                { label: "Inspect", action: function () { /* show edge detail */ } },
                { label: "Simulate Failure", action: function () { simulateLinkFailure(data.id); } }
            ];
        } else {
            items = [
                { label: "Add Switch", action: function () { toggleSection("fb-add-switch-body"); } },
                { label: "Add Endpoint", action: function () { toggleSection("fb-add-ep-body"); } },
                { label: "Fit All", action: function () { if (fabricCy) fabricCy.fit(undefined, 50); } }
            ];
        }

        items.forEach(function (item) {
            if (item.sep) {
                menu.innerHTML += '<div class="ctx-separator"></div>';
            } else {
                var el = document.createElement("div");
                el.className = "ctx-item";
                if (item.danger) el.style.color = "#ef4444";
                el.textContent = item.label;
                el.addEventListener("click", function () { hideContextMenu(); item.action(); });
                menu.appendChild(el);
            }
        });

        menu.style.left = event.clientX + "px";
        menu.style.top = event.clientY + "px";
        document.body.appendChild(menu);

        setTimeout(function () {
            document.addEventListener("click", hideContextMenu, { once: true });
        }, 10);
    }

    function hideContextMenu() {
        var m = $("fb-context-menu");
        if (m) m.remove();
    }

    function toggleSection(id) {
        var el = $(id);
        if (el) el.hidden = !el.hidden;
    }

    /* ========== INLINE LABEL EDIT ========== */

    function inlineEditLabel(node, deviceId) {
        if (!fabricCy) return;
        var container = $("fb-canvas");
        var rendPos = node.renderedPosition();
        var zoom = fabricCy.zoom();

        var input = document.createElement("input");
        input.type = "text";
        input.value = node.data("label");
        input.className = "fb-inline-edit";
        input.style.position = "absolute";
        input.style.left = (rendPos.x - 50) + "px";
        input.style.top = (rendPos.y - 12) + "px";
        input.style.width = "100px";
        input.style.zIndex = "100";
        input.style.fontSize = (10 * zoom) + "px";
        input.style.padding = "2px 4px";
        input.style.background = "#1e293b";
        input.style.color = "#e2e8f0";
        input.style.border = "1px solid #6366f1";
        input.style.borderRadius = "3px";
        input.style.textAlign = "center";
        input.style.outline = "none";
        container.appendChild(input);
        input.focus();
        input.select();

        function commit() {
            var newName = input.value.trim();
            if (newName && newName !== node.data("label")) {
                node.data("label", newName);
                saveDeviceProps(deviceId, { hostname: newName });
                addEvent("Renamed to " + newName);
            }
            if (input.parentElement) input.parentElement.removeChild(input);
        }
        input.addEventListener("keydown", function (e) {
            if (e.key === "Enter") { e.preventDefault(); commit(); }
            if (e.key === "Escape") { if (input.parentElement) input.parentElement.removeChild(input); }
        });
        input.addEventListener("blur", commit);
    }

    /* ========== DEVICE INSPECTOR ========== */

    function openFbDetail(deviceId) {
        var device = fabricModel.devices.find(function (d) { return d.id === deviceId; });
        if (!device) return;
        selectedFbDevice = deviceId;
        $("fb-detail").hidden = false;
        $("fb-inspector-hint").hidden = true;
        $("fb-detail-hostname").textContent = device.hostname;
        renderFbDetail();
    }

    function closeFbDetail() {
        $("fb-detail").hidden = true;
        $("fb-inspector-hint").hidden = false;
        selectedFbDevice = null;
    }

    function showLinkInspector(d) {
        var content = $("fb-detail-content");
        $("fb-detail").hidden = false;
        $("fb-inspector-hint").hidden = true;
        var isDCI = d.cable_type === "DCI";
        $("fb-detail-hostname").textContent = isDCI ? "DCI Link" : "Link";

        var html = '<div class="fb-props">' +
            '<div class="fb-prop-row"><label>From</label><span>' + escHtml(d.from_device || '-') + ' (' + escHtml(d.from_port || '-') + ')</span></div>' +
            '<div class="fb-prop-row"><label>To</label><span>' + escHtml(d.to_device || '-') + ' (' + escHtml(d.to_port || '-') + ')</span></div>' +
            '<div class="fb-prop-row"><label>Speed</label><span>' + escHtml(d.speed || '-') + '</span></div>' +
            '<div class="fb-prop-row"><label>Type</label><span style="color:' + (isDCI ? '#f59e0b' : '#94a3b8') + '">' + escHtml(d.cable_type || 'Fabric') + '</span></div>';
        if (isDCI) {
            html +=
                '<div class="fb-prop-row" style="margin-top:8px;border-top:1px solid #334155;padding-top:8px"><label style="color:#f59e0b">Protocol</label><span>' + escHtml(d.protocol || 'BGP') + '</span></div>' +
                '<div class="fb-prop-row"><label style="color:#f59e0b">Address Family</label><span>' + escHtml(d.bgp_address_family || 'ipv4 unicast') + '</span></div>' +
                '<div class="fb-prop-row"><label>Local ASN</label><span>' + escHtml(d.from_asn || '-') + '</span></div>' +
                '<div class="fb-prop-row"><label>Remote ASN</label><span>' + escHtml(d.to_asn || '-') + '</span></div>';
        }
        html += '</div>';
        content.innerHTML = html;
    }

    function showEndpointInspector(epId) {
        var ep = fabricEndpoints.find(function (e) { return e.id === epId; });
        if (!ep) return;
        var content = $("fb-detail-content");
        $("fb-detail").hidden = false;
        $("fb-inspector-hint").hidden = true;
        $("fb-detail-hostname").textContent = ep.name;

        var epType = ENDPOINT_TYPES[ep.type] || {};
        var html = '<div class="fb-props">' +
            '<div class="fb-prop-row"><label>Type</label><span style="color:' + (epType.color || '#fff') + '">' + (epType.label || ep.type) + '</span></div>' +
            '<div class="fb-prop-row"><label>IP</label><span>' + escHtml(ep.ip || '-') + '</span></div>' +
            '<div class="fb-prop-row"><label>VLAN</label><span>' + (ep.vlan || '-') + '</span></div>' +
            '<div class="fb-prop-row"><label>VRF</label><span>' + escHtml(ep.vrf || '-') + '</span></div>' +
            '<div class="fb-prop-row"><label>Mode</label><span>' + (ep.mode === 'vpc' ? 'Dual-Homed (vPC)' : 'Single-Homed') + '</span></div>' +
            '</div>';
        content.innerHTML = html;
    }

    function renderFbDetail() {
        var content = $("fb-detail-content");
        if (!selectedFbDevice || !fabricModel) { content.innerHTML = ""; return; }
        var device = fabricModel.devices.find(function (d) { return d.id === selectedFbDevice; });
        if (!device) { content.innerHTML = ""; return; }

        if (currentFbTab === "properties") {
            renderPropertiesTab(content, device);
        } else if (currentFbTab === "config") {
            renderConfigTab(content, device);
        } else if (currentFbTab === "terminal") {
            renderTerminalTab(content, device);
        }
    }

    function renderPropertiesTab(container, device) {
        var html = '<div class="fb-props">';
        var fields = [
            { label: "Hostname", key: "hostname" }, { label: "Role", key: "role" },
            { label: "Model", key: "model" }, { label: "Site", key: "site" },
            { label: "Mgmt IP", key: "mgmt_ip" }, { label: "Loopback0", key: "loopback0" },
            { label: "Loopback1 (VTEP)", key: "loopback1" }, { label: "ASN", key: "asn" },
            { label: "vPC Domain", key: "vpc_domain" }, { label: "vPC Peer", key: "vpc_peer" }
        ];
        fields.forEach(function (f) {
            html += '<div class="fb-prop-row"><label>' + f.label + '</label><input type="text" class="fb-prop-input" data-field="' + f.key + '" value="' + escHtml(device[f.key] || "") + '"></div>';
        });
        html += '<button class="btn btn-sm btn-primary fb-save-props" style="margin-top:8px;width:100%">Save Changes</button></div>';

        if (device.interfaces && device.interfaces.length > 0) {
            html += '<h5 style="margin-top:12px;color:#94a3b8;font-size:11px">Interfaces (' + device.interfaces.length + ')</h5>';
            html += '<div class="fb-intf-list">';
            device.interfaces.forEach(function (intf) {
                html += '<div class="fb-intf-item"><strong>' + escHtml(intf.name) + '</strong>';
                if (intf.description) html += ' <span class="fb-intf-desc">' + escHtml(intf.description) + '</span>';
                if (intf.speed) html += ' <span class="fb-intf-speed">' + intf.speed + '</span>';
                html += '</div>';
            });
            html += '</div>';
        }
        container.innerHTML = html;
        container.querySelector(".fb-save-props").addEventListener("click", function () {
            var inputs = container.querySelectorAll(".fb-prop-input");
            var updates = {};
            inputs.forEach(function (inp) { updates[inp.getAttribute("data-field")] = inp.value; });
            saveDeviceProps(device.id, updates);
        });
    }

    function renderConfigTab(container, device) {
        container.innerHTML = '<div class="fb-config-loading">Generating config...</div>';
        fetch(API_BASE + "/api/fabric/config/" + device.id)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var config = data.config || "No config generated yet.";
                container.innerHTML = '<pre class="fb-config-view">' + escHtml(config) + '</pre>';
                deviceConfigs[device.id] = config;
            })
            .catch(function () { container.innerHTML = '<p style="color:#94a3b8;font-size:11px">Failed to load config.</p>'; });
    }

    function renderTerminalTab(container, device) {
        var html = '<div style="padding:12px;text-align:center">' +
            '<p style="color:#8b949e;font-size:11px;margin:0 0 8px">Terminal sessions open in the dock below</p>' +
            '<button class="btn btn-sm btn-primary" id="fb-open-term-btn">Open Terminal for ' + escHtml(device.hostname) + '</button></div>';
        container.innerHTML = html;
        $("fb-open-term-btn").addEventListener("click", function () {
            openTerminalWindow(device.id);
        });
    }

    function executeCliCommand(deviceId, command) {
        var output = $("fb-term-output");
        var device = fabricModel.devices.find(function (d) { return d.id === deviceId; });
        var prompt = device ? device.hostname + "(config)# " : "switch(config)# ";
        output.innerHTML += '<div class="fb-term-line"><span class="fb-term-cmd">' + prompt + escHtml(command) + '</span></div>';

        fetch(API_BASE + "/api/fabric/cli-command", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device_id: deviceId, command: command })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                output.innerHTML += '<div class="fb-term-line fb-term-result">' + escHtml(data.result) + '</div>';
                output.scrollTop = output.scrollHeight;
                if (data.model) {
                    var idx = fabricModel.devices.findIndex(function (d) { return d.id === deviceId; });
                    if (idx >= 0) fabricModel.devices[idx] = data.model;
                }
            })
            .catch(function (err) {
                output.innerHTML += '<div class="fb-term-line fb-term-error">Error: ' + err.message + '</div>';
            });
    }

    /* ========== FLOATING TERMINAL WINDOWS ========== */

    var terminalWindows = {};
    var activeTerminalId = null;

    function openTerminalWindow(deviceId) {
        if (!fabricModel) return;
        var device = fabricModel.devices.find(function (d) { return d.id === deviceId; });
        if (!device) return;

        var dock = $("fb-terminals-dock");
        dock.hidden = false;

        if (terminalWindows[deviceId]) {
            switchTerminalTab(deviceId);
            return;
        }

        terminalWindows[deviceId] = {
            hostname: device.hostname,
            history: []
        };

        var body = $("fb-terminals-body");
        var win = document.createElement("div");
        win.className = "fb-term-window";
        win.id = "fb-term-win-" + deviceId;
        win.innerHTML =
            '<div class="fb-terminal-output" id="fb-term-out-' + deviceId + '">' +
            '<span class="fb-term-line" style="color:#58a6ff">' + escHtml(device.hostname) + '# Welcome to config terminal</span>' +
            '</div>' +
            '<div class="fb-terminal-input-row">' +
            '<span class="fb-term-prompt">' + escHtml(device.hostname) + '(config)# </span>' +
            '<input type="text" class="fb-term-input" data-device="' + deviceId + '" placeholder="Enter NX-OS command...">' +
            '</div>';
        body.appendChild(win);

        win.querySelector(".fb-term-input").addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                var cmd = e.target.value.trim();
                if (!cmd) return;
                executeTerminalCmd(deviceId, cmd);
                e.target.value = "";
            }
        });

        renderTerminalTabs();
        switchTerminalTab(deviceId);
    }

    function switchTerminalTab(deviceId) {
        activeTerminalId = deviceId;
        document.querySelectorAll(".fb-term-window").forEach(function (w) { w.classList.remove("active"); });
        var win = $("fb-term-win-" + deviceId);
        if (win) {
            win.classList.add("active");
            var input = win.querySelector(".fb-term-input");
            if (input) input.focus();
        }
        renderTerminalTabs();
    }

    function closeTerminalWindow(deviceId) {
        var win = $("fb-term-win-" + deviceId);
        if (win) win.remove();
        delete terminalWindows[deviceId];

        var remaining = Object.keys(terminalWindows);
        if (remaining.length === 0) {
            $("fb-terminals-dock").hidden = true;
            activeTerminalId = null;
        } else {
            if (activeTerminalId === deviceId) {
                switchTerminalTab(remaining[remaining.length - 1]);
            }
        }
        renderTerminalTabs();
    }

    function renderTerminalTabs() {
        var tabBar = $("fb-terminals-tabs");
        var html = '';
        Object.keys(terminalWindows).forEach(function (devId) {
            var t = terminalWindows[devId];
            var isActive = devId === activeTerminalId;
            html += '<div class="fb-term-tab' + (isActive ? ' active' : '') + '" data-term-id="' + devId + '">' +
                '<span>' + escHtml(t.hostname) + '</span>' +
                '<span class="term-tab-close" data-term-close="' + devId + '">&times;</span></div>';
        });
        html += '<div class="fb-term-tab-add" id="fb-term-add-btn" title="Open terminal for device">+</div>';
        tabBar.innerHTML = html;

        tabBar.querySelectorAll(".fb-term-tab").forEach(function (tab) {
            tab.addEventListener("click", function (e) {
                if (e.target.classList.contains("term-tab-close")) return;
                switchTerminalTab(tab.getAttribute("data-term-id"));
            });
        });
        tabBar.querySelectorAll(".term-tab-close").forEach(function (btn) {
            btn.addEventListener("click", function (e) {
                e.stopPropagation();
                closeTerminalWindow(btn.getAttribute("data-term-close"));
            });
        });

        var addBtn = $("fb-term-add-btn");
        if (addBtn) {
            addBtn.addEventListener("click", showTerminalDevicePicker);
        }
    }

    function showTerminalDevicePicker() {
        if (!fabricModel) return;
        var devices = fabricModel.devices || [];
        var choices = devices.filter(function (d) { return !terminalWindows[d.id]; });
        if (choices.length === 0) { alert("All devices already have terminals open"); return; }

        var pick = prompt("Open terminal for:\n" + choices.map(function (d, i) { return (i + 1) + ". " + d.hostname; }).join("\n") + "\n\nEnter number:");
        var idx = parseInt(pick) - 1;
        if (idx >= 0 && idx < choices.length) {
            openTerminalWindow(choices[idx].id);
        }
    }

    function executeTerminalCmd(deviceId, command) {
        var output = $("fb-term-out-" + deviceId);
        if (!output) return;
        var device = fabricModel.devices.find(function (d) { return d.id === deviceId; });
        var prompt = device ? device.hostname + "(config)# " : "switch(config)# ";
        output.innerHTML += '<div class="fb-term-line"><span class="fb-term-cmd">' + prompt + escHtml(command) + '</span></div>';

        fetch(API_BASE + "/api/fabric/cli-command", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device_id: deviceId, command: command })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                output.innerHTML += '<div class="fb-term-line fb-term-result">' + escHtml(data.result) + '</div>';
                output.scrollTop = output.scrollHeight;
                if (data.model) {
                    var idx = fabricModel.devices.findIndex(function (d) { return d.id === deviceId; });
                    if (idx >= 0) {
                        var oldHostname = fabricModel.devices[idx].hostname;
                        fabricModel.devices[idx] = data.model;

                        // Update Cytoscape node label and color if changed
                        if (fabricCy) {
                            var cyNode = fabricCy.getElementById(deviceId);
                            if (cyNode.length) {
                                cyNode.data("label", data.model.hostname);
                                var newColor = ROLE_COLORS[data.model.role] || "#64748b";
                                cyNode.data("color", newColor);
                            }
                        }

                        // Update link references if hostname changed
                        if (oldHostname !== data.model.hostname) {
                            fabricModel.links.forEach(function (link) {
                                if (link.from_device === oldHostname) link.from_device = data.model.hostname;
                                if (link.to_device === oldHostname) link.to_device = data.model.hostname;
                            });
                            // Update terminal prompt
                            var termWin = terminalWindows[deviceId];
                            if (termWin) termWin.hostname = data.model.hostname;
                            addEvent("Hostname changed: " + oldHostname + " → " + data.model.hostname);
                        }

                        // Refresh right-pane inspector if this device is selected
                        if (selectedFbDevice === deviceId) {
                            $("fb-detail-hostname").textContent = data.model.hostname;
                            renderFbDetail();
                        }

                        // Refresh left panel stats
                        renderLeftPanel();
                    }
                }
                // Update prompt if backend returned a new context-aware prompt
                if (data.prompt) {
                    var promptEl = output.parentElement.querySelector(".fb-term-prompt");
                    if (promptEl) promptEl.textContent = data.prompt;
                }
            })
            .catch(function (err) {
                output.innerHTML += '<div class="fb-term-line fb-term-error">Error: ' + err.message + '</div>';
                output.scrollTop = output.scrollHeight;
            });
    }

    function initTerminalDockResize() {
        var dock = $("fb-terminals-dock");
        if (!dock) return;
        var resizer = document.createElement("div");
        resizer.className = "fb-terminals-resize";
        dock.prepend(resizer);

        var dragging = false;
        var startY = 0;
        var startH = 0;

        resizer.addEventListener("mousedown", function (e) {
            dragging = true;
            startY = e.clientY;
            startH = dock.offsetHeight;
            document.body.style.cursor = "row-resize";
            document.body.style.userSelect = "none";
            e.preventDefault();
        });
        document.addEventListener("mousemove", function (e) {
            if (!dragging) return;
            var diff = startY - e.clientY;
            var newH = Math.max(120, Math.min(window.innerHeight * 0.5, startH + diff));
            dock.style.height = newH + "px";
        });
        document.addEventListener("mouseup", function () {
            if (!dragging) return;
            dragging = false;
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
        });
    }

    function saveDeviceProps(deviceId, updates) {
        fetch(API_BASE + "/api/fabric/device/" + deviceId, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(updates)
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var idx = fabricModel.devices.findIndex(function (d) { return d.id === deviceId; });
                if (idx >= 0) fabricModel.devices[idx] = data;
                renderFabricCanvas();
                openFbDetail(deviceId);
                addEvent("Updated " + (data.hostname || deviceId));
            })
            .catch(function (err) { alert("Save failed: " + err.message); });
    }

    /* ========== ADD SWITCH / LINK / ENDPOINT ========== */

    function addSwitch() {
        var name = $("fb-add-sw-name").value.trim();
        var role = $("fb-add-sw-role").value;
        var model = $("fb-add-sw-model").value.trim();
        if (!name) { alert("Hostname is required"); return; }

        fetch(API_BASE + "/api/fabric/devices", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ hostname: name, role: role, model: model })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.device) {
                    fabricModel.devices.push(data.device);
                    renderFabricOverview();
                    addEvent("Added switch " + name);
                    $("fb-add-sw-name").value = "";
                    $("fb-add-sw-model").value = "";
                }
            })
            .catch(function (err) { alert("Add failed: " + err.message); });
    }

    function addLink() {
        var fromId = $("fb-add-link-from").value;
        var toId = $("fb-add-link-to").value;
        var fromPort = $("fb-add-link-from-port").value.trim();
        var toPort = $("fb-add-link-to-port").value.trim();
        var speed = $("fb-add-link-speed").value.trim();
        if (!fromId || !toId) { alert("Select both endpoints"); return; }

        fetch(API_BASE + "/api/fabric/links", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ from_device: fromId, to_device: toId, from_port: fromPort, to_port: toPort, speed: speed })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.link) {
                    fabricModel.links.push(data.link);
                    renderFabricOverview();
                    addEvent("Added link " + fromPort + " → " + toPort);
                }
            })
            .catch(function (err) { alert("Add failed: " + err.message); });
    }

    function addEndpoint() {
        var epType = $("fb-add-ep-type").value;
        var name = $("fb-add-ep-name").value.trim();
        var ip = $("fb-add-ep-ip").value.trim();
        var vlan = $("fb-add-ep-vlan").value.trim();
        var vrf = $("fb-add-ep-vrf").value.trim();
        var leafId = $("fb-add-ep-leaf").value;
        var port = $("fb-add-ep-port").value.trim();
        var mode = $("fb-add-ep-mode").value;
        if (!name) { alert("Name is required"); return; }

        var ep = {
            id: "ep-" + Date.now(),
            type: epType,
            name: name,
            ip: ip,
            vlan: vlan,
            vrf: vrf,
            mode: mode,
            connected_to: [],
            site: ""
        };

        if (leafId) {
            var leafDev = fabricModel.devices.find(function (d) { return d.id === leafId; });
            if (leafDev) {
                ep.connected_to.push({ device: leafDev.hostname, port: port });
                ep.site = leafDev.site || "";
            }
        }

        fetch(API_BASE + "/api/fabric/endpoints", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(ep)
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                fabricEndpoints.push(data.endpoint || ep);
                renderFabricOverview();
                addEvent(name + " connected on " + (ep.connected_to[0] ? ep.connected_to[0].device + " " + port : "fabric"));
                $("fb-add-ep-name").value = "";
                $("fb-add-ep-ip").value = "";
                $("fb-add-ep-vlan").value = "";
                $("fb-add-ep-vrf").value = "";
                $("fb-add-ep-port").value = "";
            })
            .catch(function () {
                fabricEndpoints.push(ep);
                renderFabricOverview();
                addEvent(name + " added (local)");
            });
    }

    /* ========== TRAFFIC SIMULATION ========== */

    function traceTraffic() {
        var srcId = $("fb-traffic-src").value;
        var dstId = $("fb-traffic-dst").value;
        if (!srcId || !dstId) { alert("Select source and destination endpoints"); return; }

        var srcEp = fabricEndpoints.find(function (e) { return e.id === srcId; });
        var dstEp = fabricEndpoints.find(function (e) { return e.id === dstId; });
        if (!srcEp || !dstEp) return;

        fetch(API_BASE + "/api/fabric/traffic/trace", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ src_endpoint_id: srcId, dst_endpoint_id: dstId })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var flow = {
                    id: "flow-" + Date.now(),
                    src: srcEp.name,
                    dst: dstEp.name,
                    srcId: srcId,
                    dstId: dstId,
                    success: data.success,
                    hops: data.hops || [],
                    path_type: data.path_type || "unknown",
                    ecmp_paths: data.ecmp_paths || 1,
                    failure_reason: data.failure_reason || null,
                    src_endpoint: data.src_endpoint || null,
                    dst_endpoint: data.dst_endpoint || null,
                    overlay: data.overlay || null
                };
                fabricFlows.push(flow);
                renderTrafficFlows();
                highlightFlowPath(flow);
                showTrafficResult(flow);
                addEvent("Traffic trace: " + srcEp.name + " → " + dstEp.name + " [" + (flow.success ? "PASS" : "FAIL") + "]");
            })
            .catch(function () {
                var flow = {
                    id: "flow-" + Date.now(),
                    src: srcEp.name,
                    dst: dstEp.name,
                    success: false,
                    hops: [],
                    path_type: "unknown",
                    failure_reason: "Backend traffic engine not available"
                };
                fabricFlows.push(flow);
                renderTrafficFlows();
                showTrafficResult(flow);
            });
    }

    function renderTrafficFlows() {
        var container = $("fb-traffic-flows");
        var html = "";
        fabricFlows.forEach(function (flow) {
            html += '<div class="fb-flow-chip" data-flow="' + flow.id + '">' +
                '<div class="flow-status ' + (flow.success ? 'pass' : 'fail') + '"></div>' +
                '<span class="flow-label">' + escHtml(flow.src) + ' → ' + escHtml(flow.dst) + '</span>' +
                '<span class="flow-remove" data-flowid="' + flow.id + '">&times;</span></div>';
        });
        container.innerHTML = html;
        container.querySelectorAll(".flow-remove").forEach(function (btn) {
            btn.addEventListener("click", function (e) {
                e.stopPropagation();
                removeFlow(btn.getAttribute("data-flowid"));
            });
        });
    }

    function showTrafficResult(flow) {
        var result = $("fb-traffic-result");
        result.hidden = false;
        result.className = "fb-traffic-result " + (flow.success ? "success" : "failure");

        var pathTypeLabels = {
            l2_local: "L2 Local Switching",
            l2_vxlan: "L2 VXLAN (Bridged)",
            l3_vxlan: "L3 VXLAN (Symmetric IRB)",
            inter_vrf: "Inter-VRF Routing",
            unknown: "Unknown"
        };
        var ptLabel = pathTypeLabels[flow.path_type] || flow.path_type;

        var html = '<div class="tr-title">' + (flow.success ? "&#10003; Path Validated" : "&#10007; Path Failed") + '</div>';

        if (!flow.success) {
            html += '<div class="tr-error">' + escHtml(flow.failure_reason || "Unknown failure") + '</div>';
            result.innerHTML = html;
            return;
        }

        // Endpoint summary
        var srcEp = flow.src_endpoint;
        var dstEp = flow.dst_endpoint;
        var ov = flow.overlay || {};

        html += '<div class="tr-section"><div class="tr-section-title">Endpoints</div>';
        html += '<table class="tr-table"><tbody>';
        html += '<tr><td class="tr-label">Source</td><td>' + escHtml(flow.src) + (srcEp ? ' <span class="tr-dim">(' + escHtml(srcEp.ip || '-') + ')</span>' : '') + '</td></tr>';
        html += '<tr><td class="tr-label">Destination</td><td>' + escHtml(flow.dst) + (dstEp ? ' <span class="tr-dim">(' + escHtml(dstEp.ip || '-') + ')</span>' : '') + '</td></tr>';
        html += '</tbody></table></div>';

        // Overlay / VXLAN details
        html += '<div class="tr-section"><div class="tr-section-title">Overlay Details</div>';
        html += '<table class="tr-table"><tbody>';
        html += '<tr><td class="tr-label">Path Type</td><td>' + escHtml(ptLabel) + '</td></tr>';
        html += '<tr><td class="tr-label">ECMP Paths</td><td>' + (flow.ecmp_paths || 1) + 'x</td></tr>';
        if (ov.src_vlan) html += '<tr><td class="tr-label">Src VLAN</td><td>' + escHtml(ov.src_vlan) + '</td></tr>';
        if (ov.dst_vlan) html += '<tr><td class="tr-label">Dst VLAN</td><td>' + escHtml(ov.dst_vlan) + '</td></tr>';
        if (ov.src_vrf) html += '<tr><td class="tr-label">VRF</td><td>' + escHtml(ov.src_vrf) + '</td></tr>';
        if (ov.l2vni) html += '<tr><td class="tr-label">L2 VNI</td><td>' + ov.l2vni + '</td></tr>';
        if (ov.l3vni) html += '<tr><td class="tr-label">L3 VNI</td><td>' + ov.l3vni + '</td></tr>';
        if (ov.ingress_vtep) html += '<tr><td class="tr-label">Ingress VTEP</td><td>' + escHtml(ov.ingress_vtep) + '</td></tr>';
        if (ov.egress_vtep) html += '<tr><td class="tr-label">Egress VTEP</td><td>' + escHtml(ov.egress_vtep) + '</td></tr>';
        html += '</tbody></table></div>';

        // Hop-by-hop path
        html += '<div class="tr-section"><div class="tr-section-title">Routing Path (' + flow.hops.length + ' hops)</div>';
        html += '<div class="tr-path">';
        if (srcEp) {
            html += '<div class="tr-hop tr-hop-ep"><span class="tr-hop-icon" style="color:#10b981">&#9679;</span>' +
                '<span class="tr-hop-name">' + escHtml(flow.src) + '</span>' +
                '<span class="tr-hop-detail">' + escHtml(srcEp.ip || '') + ' | VLAN ' + escHtml(ov.src_vlan || '-') + '</span></div>';
            html += '<div class="tr-hop-arrow">&#8595;</div>';
        }
        flow.hops.forEach(function (hop, idx) {
            var actionColor = '#94a3b8';
            if (hop.action && hop.action.indexOf('encap') >= 0) actionColor = '#22d3ee';
            if (hop.action && hop.action.indexOf('decap') >= 0) actionColor = '#f59e0b';
            if (hop.action && hop.action.indexOf('route') >= 0) actionColor = '#a78bfa';
            html += '<div class="tr-hop"><span class="tr-hop-icon" style="color:' + actionColor + '">&#9632;</span>' +
                '<span class="tr-hop-name">' + escHtml(hop.device || '') + '</span>' +
                '<span class="tr-hop-detail">' + escHtml(hop.ingress_port || '') + ' &#8594; ' + escHtml(hop.egress_port || '') + '</span>' +
                '<span class="tr-hop-action" style="color:' + actionColor + '">' + escHtml(hop.action || '') + '</span>' +
                (hop.encap && hop.encap !== 'none' ? '<span class="tr-hop-encap">' + escHtml(hop.encap) + '</span>' : '') +
                '</div>';
            if (idx < flow.hops.length - 1) html += '<div class="tr-hop-arrow">&#8595;</div>';
        });
        if (dstEp) {
            html += '<div class="tr-hop-arrow">&#8595;</div>';
            html += '<div class="tr-hop tr-hop-ep"><span class="tr-hop-icon" style="color:#f59e0b">&#9679;</span>' +
                '<span class="tr-hop-name">' + escHtml(flow.dst) + '</span>' +
                '<span class="tr-hop-detail">' + escHtml(dstEp.ip || '') + ' | VLAN ' + escHtml(ov.dst_vlan || '-') + '</span></div>';
        }
        html += '</div></div>';

        result.innerHTML = html;
    }

    function highlightFlowPath(flow) {
        if (!fabricCy) return;
        fabricCy.edges().removeClass("flow-active flow-failed flow-animated");
        fabricCy.nodes().removeClass("flow-active flow-src flow-dst");

        if (!flow.hops || flow.hops.length === 0) return;

        var pathNodeIds = [];

        // Source endpoint node
        if (flow.srcId) {
            var srcCyId = "ep-" + flow.srcId;
            var srcNode = fabricCy.getElementById(srcCyId);
            if (srcNode.length) {
                srcNode.addClass("flow-active flow-src");
                pathNodeIds.push(srcCyId);
            }
        }

        // Switch hops from the trace
        flow.hops.forEach(function (hop) {
            if (hop.device) {
                var dev = fabricModel.devices.find(function (d) { return d.hostname === hop.device; });
                if (dev) {
                    pathNodeIds.push(dev.id);
                    var node = fabricCy.getElementById(dev.id);
                    if (node.length) node.addClass("flow-active");
                }
            }
        });

        // Destination endpoint node
        if (flow.dstId) {
            var dstCyId = "ep-" + flow.dstId;
            var dstNode = fabricCy.getElementById(dstCyId);
            if (dstNode.length) {
                dstNode.addClass("flow-active flow-dst");
                pathNodeIds.push(dstCyId);
            }
        }

        // Highlight edges along the full path (endpoint → leaf → spine → leaf → endpoint)
        var flowClass = flow.success ? "flow-active" : "flow-failed";
        for (var i = 0; i < pathNodeIds.length - 1; i++) {
            var nSrc = pathNodeIds[i];
            var nTgt = pathNodeIds[i + 1];
            fabricCy.edges().forEach(function (edge) {
                var eSrc = edge.source().id();
                var eTgt = edge.target().id();
                if ((eSrc === nSrc && eTgt === nTgt) || (eSrc === nTgt && eTgt === nSrc)) {
                    edge.addClass(flowClass);
                }
            });
        }

        // Animated packet traversal along the path
        animatePacket(pathNodeIds, flow.success);
    }

    function animatePacket(pathNodeIds, success) {
        if (!fabricCy || pathNodeIds.length < 2) return;

        // Remove previous packet overlay
        fabricCy.nodes(".flow-packet").forEach(function (n) { fabricCy.remove(n); });

        var startPos = fabricCy.getElementById(pathNodeIds[0]).position();
        var packet = fabricCy.add({
            group: "nodes",
            data: { id: "_flow_packet_", label: "", nodeType: "packet" },
            position: { x: startPos.x, y: startPos.y },
            classes: "flow-packet"
        });
        packet.ungrabify();
        packet.unselectify();

        var step = 0;
        function moveNext() {
            step++;
            if (step >= pathNodeIds.length) {
                setTimeout(function () { fabricCy.remove(packet); }, 600);
                return;
            }
            var targetNode = fabricCy.getElementById(pathNodeIds[step]);
            if (!targetNode.length) { fabricCy.remove(packet); return; }
            var tPos = targetNode.position();
            packet.animate({
                position: { x: tPos.x, y: tPos.y },
                duration: 400,
                easing: "ease-in-out-sine",
                complete: moveNext
            });
        }
        moveNext();
    }

    function removeFlow(flowId) {
        fabricFlows = fabricFlows.filter(function (f) { return f.id !== flowId; });
        renderTrafficFlows();
        if (fabricCy) {
            fabricCy.edges().removeClass("flow-active flow-failed");
            fabricCy.nodes().removeClass("flow-active flow-src flow-dst");
            fabricCy.nodes(".flow-packet").forEach(function (n) { fabricCy.remove(n); });
        }
        $("fb-traffic-result").hidden = true;
    }

    function clearTrafficFlows() {
        fabricFlows = [];
        renderTrafficFlows();
        if (fabricCy) {
            fabricCy.edges().removeClass("flow-active flow-failed");
            fabricCy.nodes().removeClass("flow-active flow-src flow-dst");
            fabricCy.nodes(".flow-packet").forEach(function (n) { fabricCy.remove(n); });
        }
        $("fb-traffic-result").hidden = true;
    }

    /* ========== FAILOVER / SIMULATION ========== */

    function simulateDeviceFailure(deviceId) {
        var device = fabricModel.devices.find(function (d) { return d.id === deviceId; });
        if (!device) return;

        fetch(API_BASE + "/api/fabric/traffic/failover", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ failure: { type: "device", target_id: deviceId } })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                addEvent("Simulated failure: " + device.hostname + " — " + (data.converged ? "converged" : "traffic lost"));
                if (fabricCy) {
                    var node = fabricCy.getElementById(deviceId);
                    if (node) {
                        node.connectedEdges().addClass("link-down");
                        node.style("opacity", 0.3);
                    }
                }
            })
            .catch(function () {
                addEvent("Simulated failure: " + device.hostname);
                if (fabricCy) {
                    var node = fabricCy.getElementById(deviceId);
                    if (node) {
                        node.connectedEdges().addClass("link-down");
                        node.style("opacity", 0.3);
                    }
                }
            });
    }

    function simulateLinkFailure(linkId) {
        if (!fabricCy) return;
        var edge = fabricCy.getElementById(linkId);
        if (edge) {
            edge.addClass("link-down");
            addEvent("Link failure simulated: " + linkId);
        }
    }

    function simulateEndpointLinkFailure(epId) {
        if (!fabricCy) return;
        var epNode = fabricCy.getElementById("ep-" + epId);
        if (epNode) {
            epNode.connectedEdges().addClass("link-down");
            addEvent("Endpoint link failure simulated");
        }
    }

    function removeDevice(deviceId) {
        if (!confirm("Remove this device from the fabric?")) return;
        fabricModel.devices = fabricModel.devices.filter(function (d) { return d.id !== deviceId; });
        fabricModel.links = fabricModel.links.filter(function (l) {
            var fromDev = fabricModel.devices.find(function (d) { return d.hostname === l.from_device; });
            var toDev = fabricModel.devices.find(function (d) { return d.hostname === l.to_device; });
            return fromDev && toDev;
        });
        renderFabricOverview();
        closeFbDetail();
        addEvent("Removed device " + deviceId);
    }

    function removeEndpoint(epId) {
        fabricEndpoints = fabricEndpoints.filter(function (e) { return e.id !== epId; });
        renderFabricOverview();
        closeFbDetail();
        addEvent("Removed endpoint " + epId);
    }

    function promptRenameDevice(deviceId) {
        var device = fabricModel.devices.find(function (d) { return d.id === deviceId; });
        if (!device) return;
        var newName = prompt("Enter new hostname:", device.hostname);
        if (newName && newName !== device.hostname) {
            saveDeviceProps(deviceId, { hostname: newName });
        }
    }

    function presetTrafficSource(epId) {
        var src = $("fb-traffic-src");
        if (src) src.value = epId;
    }

    /* ========== OVERLAY EDITOR ========== */

    function renderOverlayEditor() {
        var content = $("fb-overlay-content");
        if (!fabricModel) { content.innerHTML = ""; return; }
        var overlay = fabricModel.overlay;

        var html = '<div class="fb-overlay-section">';
        html += '<h4>VRFs</h4>';
        html += '<table class="fb-table"><thead><tr><th>Name</th><th>VNI</th><th>RD</th><th>RT Import</th><th>RT Export</th></tr></thead><tbody>';
        (overlay.vrfs || []).forEach(function (vrf) {
            html += '<tr><td>' + escHtml(vrf.name) + '</td><td>' + vrf.vni + '</td><td>' + escHtml(vrf.rd) + '</td><td>' + escHtml(vrf.rt_import) + '</td><td>' + escHtml(vrf.rt_export) + '</td></tr>';
        });
        html += '</tbody></table>';

        html += '<h4>VLANs / VNIs</h4>';
        html += '<table class="fb-table"><thead><tr><th>VLAN</th><th>Name</th><th>VNI</th><th>VRF</th><th>SVI IP</th><th>Anycast GW</th></tr></thead><tbody>';
        (overlay.vlans || []).forEach(function (vlan) {
            html += '<tr><td>' + vlan.vlan_id + '</td><td>' + escHtml(vlan.name) + '</td><td>' + vlan.vni + '</td><td>' + escHtml(vlan.vrf) + '</td><td>' + escHtml(vlan.svi_ip) + '</td><td>' + escHtml(vlan.anycast_gw) + '</td></tr>';
        });
        html += '</tbody></table>';

        html += '<h4>Global Fabric Settings</h4>';
        var gc = fabricModel.global_config || {};
        html += '<div class="fb-props">';
        [{ label: "NX-OS Version", key: "nxos_version" }, { label: "Underlay Protocol", key: "underlay_protocol" },
        { label: "OSPF Area", key: "ospf_area" }, { label: "Spine ASN", key: "spine_asn" },
        { label: "Leaf ASN Start", key: "leaf_asn_start" }, { label: "Anycast GW MAC", key: "anycast_gw_mac" }].forEach(function (f) {
            html += '<div class="fb-prop-row"><label>' + f.label + '</label><input type="text" class="fb-gc-input" data-field="' + f.key + '" value="' + escHtml(String(gc[f.key] || "")) + '"></div>';
        });
        html += '<button class="btn btn-primary fb-save-gc" style="margin-top:8px;width:100%">Save Global Config</button></div></div>';
        content.innerHTML = html;

        content.querySelector(".fb-save-gc").addEventListener("click", function () {
            var inputs = content.querySelectorAll(".fb-gc-input");
            var updates = {};
            inputs.forEach(function (inp) {
                var key = inp.getAttribute("data-field");
                var val = inp.value;
                if (key === "spine_asn" || key === "leaf_asn_start") val = parseInt(val) || val;
                updates[key] = val;
            });
            saveGlobalConfig(updates);
        });
    }

    function saveGlobalConfig(updates) {
        fetch(API_BASE + "/api/fabric/global-config", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(updates)
        })
            .then(function (r) { return r.json(); })
            .then(function (data) { fabricModel.global_config = data; addEvent("Global config updated"); })
            .catch(function (err) { alert("Save failed: " + err.message); });
    }

    /* ========== UTILITIES ========== */

    function escHtml(str) {
        var div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    document.addEventListener("DOMContentLoaded", initFabricBuilder);
})();
