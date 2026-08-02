/**
 * Classic Fabric Visualiser - Frontend Application
 */

(function () {
    "use strict";

    var API_BASE = "";
    var cy = null;
    var selectedFiles = [];
    var topologyData = null;
    var currentDetailNode = null;
    var currentTab = "info";
    var currentPartition = null;
    var currentView = "connected";
    var currentTopoMode = "physical";
    var positionCache = {};  // { mode: { positions: {id: {x,y}}, pan: {x,y}, zoom: number } }

    var ROLE_COLORS = {
        spine: "#6366f1",
        core: "#6366f1",
        leaf: "#10b981",
        access: "#10b981",
        router: "#f59e0b",
        firewall: "#ef4444",
        border: "#8b5cf6",
        loadbalancer: "#ec4899",
        wlc: "#06b6d4",
        endpoint: "#94a3b8",
        switch: "#64748b"
    };

    var SPEED_WIDTH = {
        "100G": 6,
        "40G": 5,
        "25G": 4,
        "10G": 3,
        "1G": 2,
        "100M": 1.5,
        "Po": 5
    };

    function $(id) { return document.getElementById(id); }

    function init() {
        var dropZone = $("drop-zone");
        var fileInput = $("file-input");
        var folderInput = $("folder-input");

        dropZone.addEventListener("click", function() { fileInput.click(); });

        $("btn-browse").addEventListener("click", function(e) {
            e.stopPropagation();
            fileInput.click();
        });

        $("btn-browse-folder").addEventListener("click", function(e) {
            e.stopPropagation();
            folderInput.click();
        });

        fileInput.addEventListener("change", function(e) {
            addFiles(Array.from(e.target.files));
            e.target.value = "";
        });

        folderInput.addEventListener("change", function(e) {
            addFiles(Array.from(e.target.files));
            e.target.value = "";
        });

        dropZone.addEventListener("dragover", function(e) {
            e.preventDefault();
            dropZone.classList.add("drag-over");
        });
        dropZone.addEventListener("dragleave", function() {
            dropZone.classList.remove("drag-over");
        });
        dropZone.addEventListener("drop", function(e) {
            e.preventDefault();
            dropZone.classList.remove("drag-over");
            handleDrop(e);
        });

        $("btn-add-more").addEventListener("click", function() { fileInput.click(); });
        $("btn-process").addEventListener("click", processFiles);
        $("btn-reset").addEventListener("click", resetAll);
        $("btn-export").addEventListener("click", exportPNG);
        $("btn-export-drawio").addEventListener("click", exportDrawio);
        $("btn-export-selected").addEventListener("click", exportDrawio);
        $("btn-clear-selection").addEventListener("click", clearSelection);
        $("btn-fit").addEventListener("click", function() { if (cy) cy.fit(null, 50); });
        $("btn-zoom-in").addEventListener("click", function() { if (cy) cy.zoom(cy.zoom() * 1.3); });
        $("btn-zoom-out").addEventListener("click", function() { if (cy) cy.zoom(cy.zoom() * 0.7); });
        $("layout-select").addEventListener("change", applyLayout);
        $("view-select").addEventListener("change", switchView);
        $("topo-mode-select").addEventListener("change", switchTopoMode);
        $("btn-new-upload").addEventListener("click", resetAll);
        $("btn-close-detail").addEventListener("click", closeDetail);
    }

    function handleDrop(e) {
        var items = e.dataTransfer.items;
        if (items && items.length > 0 && items[0].webkitGetAsEntry) {
            var entries = [];
            for (var i = 0; i < items.length; i++) {
                var entry = items[i].webkitGetAsEntry();
                if (entry) entries.push(entry);
            }
            readAllEntries(entries).then(function(files) {
                addFiles(files);
            });
        } else {
            addFiles(Array.from(e.dataTransfer.files));
        }
    }

    function readAllEntries(entries) {
        var allFiles = [];
        var promises = entries.map(function(entry) { return readEntry(entry); });
        return Promise.all(promises).then(function(results) {
            results.forEach(function(files) { allFiles = allFiles.concat(files); });
            return allFiles;
        });
    }

    function readEntry(entry) {
        return new Promise(function(resolve) {
            if (entry.isFile) {
                entry.file(function(file) { resolve([file]); });
            } else if (entry.isDirectory) {
                var reader = entry.createReader();
                var allFiles = [];
                var readBatch = function() {
                    reader.readEntries(function(entries) {
                        if (entries.length === 0) {
                            resolve(allFiles);
                            return;
                        }
                        var batchPromises = [];
                        for (var i = 0; i < entries.length; i++) {
                            batchPromises.push(readEntry(entries[i]));
                        }
                        Promise.all(batchPromises).then(function(results) {
                            results.forEach(function(f) { allFiles = allFiles.concat(f); });
                            readBatch();
                        });
                    });
                };
                readBatch();
            } else {
                resolve([]);
            }
        });
    }

    function addFiles(files) {
        var validExt = [".txt", ".log", ".cfg", ".conf", ".zip", ".xlsx", ".xls", ".bak"];
        for (var i = 0; i < files.length; i++) {
            var file = files[i];
            var name = file.name.toLowerCase();
            if (name.startsWith(".") || name.startsWith("__")) continue;
            var ext = "." + name.split(".").pop();
            var isValid = validExt.indexOf(ext) >= 0 || name.indexOf(".") === -1;
            var isFromFolder = file.webkitRelativePath && file.webkitRelativePath.length > 0;
            if (isValid || isFromFolder) {
                selectedFiles.push(file);
            }
        }
        renderFileList();
    }

    function renderFileList() {
        var fileList = $("file-list");
        var filesUl = $("files-ul");
        if (selectedFiles.length === 0) {
            fileList.hidden = true;
            return;
        }
        fileList.hidden = false;
        filesUl.innerHTML = "";
        for (var i = 0; i < selectedFiles.length; i++) {
            var file = selectedFiles[i];
            var displayName = file.webkitRelativePath || file.name;
            var li = document.createElement("li");
            li.innerHTML = '<span class="file-name"><svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M9 1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5L9 1z" stroke="currentColor" stroke-width="1.2"/><path d="M9 1v4h4" stroke="currentColor" stroke-width="1.2"/></svg> ' + escapeHtml(displayName) + '</span><span><span class="file-size">' + formatSize(file.size) + '</span> <span class="file-remove" data-idx="' + i + '">&times;</span></span>';
            filesUl.appendChild(li);
        }
        filesUl.querySelectorAll(".file-remove").forEach(function(btn) {
            btn.addEventListener("click", function(e) {
                selectedFiles.splice(parseInt(e.target.dataset.idx, 10), 1);
                renderFileList();
            });
        });
    }

    function processFiles() {
        if (selectedFiles.length === 0) return;

        $("processing-indicator").hidden = false;
        $("btn-process").disabled = true;
        $("file-list").hidden = true;
        $("drop-zone").hidden = true;

        var prereqPanel = document.querySelector(".prereq-panel");
        if (prereqPanel) prereqPanel.hidden = true;

        var logEl = $("parse-log");
        logEl.innerHTML = "";
        logEl.hidden = false;

        appendLog("upload", "Uploading " + selectedFiles.length + " file(s)...");

        var formData = new FormData();
        for (var i = 0; i < selectedFiles.length; i++) {
            formData.append("files", selectedFiles[i]);
        }

        fetch(API_BASE + "/api/upload-stream", { method: "POST", body: formData })
            .then(function(resp) {
                if (!resp.ok) {
                    return resp.text().then(function(t) {
                        throw new Error("Upload failed: " + resp.status + " " + t);
                    });
                }

                var reader = resp.body.getReader();
                var decoder = new TextDecoder();
                var buffer = "";

                function processChunk() {
                    return reader.read().then(function(result) {
                        if (result.done) {
                            processBuffer(buffer);
                            return;
                        }

                        buffer += decoder.decode(result.value, { stream: true });

                        var lines = buffer.split("\n\n");
                        buffer = lines.pop() || "";

                        for (var i = 0; i < lines.length; i++) {
                            processSSEBlock(lines[i]);
                        }

                        return processChunk();
                    });
                }

                return processChunk();
            })
            .then(function() {
                if (topologyData) {
                    setTimeout(function() { showTopology(topologyData); }, 300);
                }
            })
            .catch(function(error) {
                appendLog("error", "Error: " + error.message);
                setTimeout(function() {
                    $("processing-indicator").hidden = true;
                    $("btn-process").disabled = false;
                    $("file-list").hidden = false;
                    $("drop-zone").hidden = false;
                    if (prereqPanel) prereqPanel.hidden = false;
                    logEl.hidden = true;
                }, 3000);
            });
    }

    function processBuffer(buf) {
        if (!buf.trim()) return;
        var blocks = buf.split("\n\n");
        for (var i = 0; i < blocks.length; i++) {
            processSSEBlock(blocks[i]);
        }
    }

    function processSSEBlock(block) {
        if (!block.trim()) return;

        var lines = block.split("\n");
        var eventType = "";
        var dataLines = [];

        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (line.indexOf("event: ") === 0) {
                eventType = line.substring(7).trim();
            } else if (line.indexOf("data: ") === 0) {
                dataLines.push(line.substring(6));
            }
        }

        if (dataLines.length === 0) return;
        var dataStr = dataLines.join("\n");

        try {
            var data = JSON.parse(dataStr);
        } catch (e) {
            return;
        }

        if (eventType === "topology") {
            topologyData = data;
        } else if (data.action && data.message) {
            appendLog(data.action, data.message);
        }
    }

    function appendLog(type, message) {
        var logEl = $("parse-log");
        var icons = { upload: "\u2B06", file: "\uD83D\uDCC4", device: "\uD83D\uDDA5", parse: "\u2699", commands: "\uD83D\uDCCB", done: "\u2713", error: "\u2717" };
        var line = document.createElement("div");
        line.className = "log-line log-" + type;
        line.innerHTML = '<span class="log-icon">' + (icons[type] || "\u203A") + '</span><span class="log-text">' + escapeHtml(message) + '</span>';
        logEl.appendChild(line);
        logEl.scrollTop = logEl.scrollHeight;
    }

    function showTopology(data) {
        $("upload-panel").hidden = true;
        $("topology-panel").hidden = false;
        $("legend").hidden = false;
        $("btn-export").disabled = false;
        $("btn-export-drawio").disabled = false;
        var statsText = data.stats.total_devices + " devices \xB7 " + data.stats.total_links + " links \xB7 " + data.stats.protocols_used.join(", ");
        if (data.bgp && data.bgp.stats.total_peers > 0) {
            statsText += " \xB7 " + data.bgp.stats.total_peers + " BGP peers";
        }
        if (data.ospf && data.ospf.stats.total_adjacencies > 0) {
            statsText += " \xB7 " + data.ospf.stats.total_adjacencies + " OSPF adj.";
        }
        $("topo-stats").textContent = statsText;

        var modeSelect = $("topo-mode-select");
        var bgpOption = modeSelect.querySelector('option[value="bgp"]');
        var ospfOption = modeSelect.querySelector('option[value="ospf"]');
        if (bgpOption) bgpOption.disabled = !(data.bgp && data.bgp.nodes.length > 0);
        if (ospfOption) ospfOption.disabled = !(data.ospf && data.ospf.nodes.length > 0);

        requestAnimationFrame(function() {
            setTimeout(function() { initCytoscape(data); }, 50);
        });
    }

    /**
     * Partition nodes into connected (have edges) vs isolated (no edges).
     * Returns { connected: [...], isolated: [...] }
     */
    function partitionNodes(nodes, edges) {
        var connectedIds = {};
        edges.forEach(function(e) {
            connectedIds[e.data.source] = true;
            connectedIds[e.data.target] = true;
        });

        var connected = [];
        var isolated = [];
        nodes.forEach(function(n) {
            if (connectedIds[n.data.id]) {
                connected.push(n);
            } else {
                isolated.push(n);
            }
        });

        return { connected: connected, isolated: isolated };
    }

    function initCytoscape(data) {
        var container = $("cy");

        var validNodes = data.nodes.filter(function(n) {
            return n.data && n.data.id && n.data.id.trim() !== "";
        });
        var validEdges = data.edges.filter(function(e) {
            return e.data && e.data.source && e.data.target &&
                   e.data.source.trim() !== "" && e.data.target.trim() !== "";
        });

        currentPartition = partitionNodes(validNodes, validEdges);
        console.log("Topology: " + currentPartition.connected.length + " connected, " + currentPartition.isolated.length + " isolated, " + validEdges.length + " edges");

        var allElements = validNodes.concat(validEdges);

        cy = cytoscape({
            container: container,
            elements: allElements,
            style: [
                {
                    selector: "node",
                    style: {
                        "shape": "roundrectangle",
                        "label": "data(label)",
                        "text-valign": "bottom",
                        "text-halign": "center",
                        "font-size": "9px",
                        "color": "#e2e8f0",
                        "text-margin-y": 5,
                        "background-color": function(ele) { return ROLE_COLORS[ele.data("role")] || "#64748b"; },
                        "width": function(ele) {
                            var label = ele.data("label") || "";
                            return Math.max(40, Math.min(100, label.length * 6 + 16));
                        },
                        "height": 28,
                        "border-width": 1.5,
                        "border-color": function(ele) { return ROLE_COLORS[ele.data("role")] || "#64748b"; },
                        "border-opacity": 0.7,
                        "background-opacity": 0.9,
                        "text-background-color": "#0f1117",
                        "text-background-opacity": 0.7,
                        "text-background-padding": "2px",
                        "text-background-shape": "roundrectangle",
                        "text-wrap": "ellipsis",
                        "text-max-width": "100px"
                    }
                },
                {
                    selector: "node.isolated",
                    style: {
                        "background-opacity": 0.5,
                        "border-style": "dashed",
                        "border-opacity": 0.4
                    }
                },
                {
                    selector: "node:selected",
                    style: {
                        "border-width": 3,
                        "border-color": "#ffffff",
                        "background-opacity": 1,
                        "z-index": 999
                    }
                },
                {
                    selector: "edge",
                    style: {
                        "label": "data(speed_label)",
                        "font-size": "7px",
                        "color": "#94a3b8",
                        "text-rotation": "autorotate",
                        "text-background-color": "#0f1117",
                        "text-background-opacity": 0.8,
                        "text-background-padding": "1px",
                        "text-background-shape": "roundrectangle",
                        "width": function(ele) { return SPEED_WIDTH[ele.data("speed")] || 1.5; },
                        "line-color": "#475569",
                        "curve-style": "bezier",
                        "target-arrow-shape": "none",
                        "opacity": 0.6
                    }
                },
                {
                    selector: "edge[link_status = 'up']",
                    style: {
                        "line-color": "#22c55e",
                        "opacity": 0.7
                    }
                },
                {
                    selector: "edge[link_status = 'down']",
                    style: {
                        "line-color": "#ef4444",
                        "opacity": 0.85,
                        "line-style": "dashed",
                        "line-dash-pattern": [8, 4]
                    }
                },
                {
                    selector: "edge[link_status = 'up/down']",
                    style: {
                        "line-color": "#f59e0b",
                        "opacity": 0.8,
                        "line-style": "dashed",
                        "line-dash-pattern": [10, 3]
                    }
                },
                {
                    selector: "edge[confidence = 'low']",
                    style: {
                        "line-style": "dashed",
                        "line-dash-pattern": [6, 3],
                        "line-color": "#64748b",
                        "opacity": 0.35
                    }
                },
                {
                    selector: "edge.port-channel",
                    style: {
                        "line-color": "#06b6d4",
                        "width": 5,
                        "opacity": 0.85,
                        "line-style": "solid"
                    }
                },
                {
                    selector: "edge[?is_port_channel]",
                    style: {
                        "line-color": "#06b6d4",
                        "width": 5,
                        "opacity": 0.85,
                        "line-style": "solid"
                    }
                },
                {
                    selector: "edge:selected",
                    style: {
                        "width": function(ele) { return (SPEED_WIDTH[ele.data("speed")] || 2) + 2; },
                        "line-color": "#6366f1",
                        "opacity": 1,
                        "label": "data(label)",
                        "font-size": "9px",
                        "color": "#e2e8f0",
                        "z-index": 999
                    }
                },
                {
                    selector: "node.intf-highlighted",
                    style: {
                        "border-width": 3,
                        "border-color": "#f59e0b",
                        "background-color": "#f59e0b",
                        "opacity": 1,
                        "z-index": 999
                    }
                },
                {
                    selector: "edge.intf-highlighted",
                    style: {
                        "line-color": "#f59e0b",
                        "width": 4,
                        "opacity": 1,
                        "z-index": 999,
                        "label": "data(label)",
                        "font-size": "9px",
                        "color": "#f59e0b"
                    }
                },
                {
                    selector: "node.highlighted",
                    style: {
                        "border-width": 3,
                        "border-color": "#6366f1",
                        "opacity": 1,
                        "z-index": 999
                    }
                },
                {
                    selector: "edge.highlighted",
                    style: {
                        "line-color": "#6366f1",
                        "width": 4,
                        "opacity": 1,
                        "z-index": 999
                    }
                }
            ],
            minZoom: 0.02,
            maxZoom: 5,
            zoomingEnabled: true,
            userZoomingEnabled: false,
            panningEnabled: true,
            userPanningEnabled: true,
            boxSelectionEnabled: true,
            selectionType: "additive"
        });

        currentPartition.isolated.forEach(function(n) {
            var cyNode = cy.getElementById(n.data.id);
            if (cyNode.length) cyNode.addClass("isolated");
        });

        validEdges.forEach(function(e) {
            var localIntf = (e.data.local_interface || "").toLowerCase();
            var remoteIntf = (e.data.remote_interface || "").toLowerCase();
            if (localIntf.indexOf("po") === 0 || remoteIntf.indexOf("po") === 0 ||
                e.data.speed === "Po") {
                var cyEdge = cy.getElementById(e.data.id);
                if (cyEdge.length) cyEdge.addClass("port-channel");
            }
        });

        var viewSelect = $("view-select");
        if (currentPartition.connected.length === 0 && currentPartition.isolated.length > 0) {
            viewSelect.value = "isolated";
            currentView = "isolated";
        } else {
            viewSelect.value = "connected";
            currentView = "connected";
        }

        applyViewFilter();

        cy.on("tap", "node", function(evt) { showDeviceDetail(evt.target); });
        cy.on("tap", "edge", function(evt) { showEdgeDetail(evt.target); });
        cy.on("tap", function(evt) { if (evt.target === cy) closeDetail(); });

        var dragStartPositions = {};
        cy.on("grab", "node", function(evt) {
            var grabbed = evt.target;
            var selected = cy.nodes(":selected");
            if (selected.length > 1 && grabbed.selected()) {
                dragStartPositions = {};
                selected.forEach(function(n) {
                    dragStartPositions[n.id()] = { x: n.position("x"), y: n.position("y") };
                });
            } else {
                dragStartPositions = {};
            }
        });

        cy.on("drag", "node", function(evt) {
            var grabbed = evt.target;
            if (Object.keys(dragStartPositions).length < 2) return;
            var grabStart = dragStartPositions[grabbed.id()];
            if (!grabStart) return;
            var dx = grabbed.position("x") - grabStart.x;
            var dy = grabbed.position("y") - grabStart.y;
            cy.batch(function() {
                for (var nid in dragStartPositions) {
                    if (nid === grabbed.id()) continue;
                    var orig = dragStartPositions[nid];
                    cy.getElementById(nid).position({ x: orig.x + dx, y: orig.y + dy });
                }
            });
        });

        cy.on("free", "node", function() {
            dragStartPositions = {};
        });

        container.addEventListener("wheel", function(evt) {
            evt.preventDefault();
            if (evt.ctrlKey || evt.metaKey) {
                var zoomFactor = evt.deltaY > 0 ? 0.96 : 1.04;
                var rect = container.getBoundingClientRect();
                var pos = { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
                cy.zoom({ level: cy.zoom() * zoomFactor, renderedPosition: pos });
            } else {
                cy.panBy({ x: -evt.deltaX, y: -evt.deltaY });
            }
        }, { passive: false });

        cy.on("select unselect", "node", updateSelectionBar);
    }

    function switchView() {
        if (cy && currentTopoMode === "physical") {
            savePositions("physical_" + currentView);
        }
        currentView = $("view-select").value;
        applyViewFilter();
    }

    function switchTopoMode() {
        var mode = $("topo-mode-select").value;

        if (cy && currentTopoMode) {
            var saveKey = currentTopoMode === "physical" ? "physical_" + currentView : currentTopoMode;
            savePositions(saveKey);
        }

        currentTopoMode = mode;
        var migPanel = $("migration-panel");

        if (mode === "migration") {
            $("view-select").disabled = true;
            if (migPanel) migPanel.hidden = false;
            $("device-detail").hidden = true;
            renderMigrationPanel();
            if (!cy) {
                initCytoscape(topologyData);
            }
        } else {
            if (migPanel) migPanel.hidden = true;

            if (mode === "physical") {
                $("view-select").disabled = false;
                var restoreKey = "physical_" + currentView;
                if (positionCache[restoreKey]) {
                    initCytoscape(topologyData);
                    restorePositions(restoreKey);
                } else {
                    initCytoscape(topologyData);
                }
            } else if (mode === "bgp") {
                $("view-select").disabled = true;
                if (topologyData.bgp && topologyData.bgp.nodes.length > 0) {
                    initRoutingCytoscape(topologyData.bgp, "bgp");
                    restorePositions("bgp");
                } else {
                    if (cy) { cy.destroy(); cy = null; }
                    $("cy").innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);font-size:16px;">No BGP peering data found.<br>Upload "show ip bgp summary" or "show bgp neighbors" outputs.</div>';
                }
            } else if (mode === "ospf") {
                $("view-select").disabled = true;
                if (topologyData.ospf && topologyData.ospf.nodes.length > 0) {
                    initRoutingCytoscape(topologyData.ospf, "ospf");
                    restorePositions("ospf");
                } else {
                    if (cy) { cy.destroy(); cy = null; }
                    $("cy").innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);font-size:16px;">No OSPF adjacency data found.<br>Upload "show ip ospf neighbor" or "show ip ospf" outputs.</div>';
                }
            }
        }
    }

    function savePositions(mode) {
        if (!cy) return;
        var positions = {};
        cy.nodes().forEach(function(node) {
            var pos = node.position();
            positions[node.id()] = { x: pos.x, y: pos.y };
        });
        positionCache[mode] = {
            positions: positions,
            pan: cy.pan(),
            zoom: cy.zoom()
        };
    }

    function restorePositions(mode) {
        if (!cy || !positionCache[mode]) return;
        var cache = positionCache[mode];
        var hasPositions = Object.keys(cache.positions).length > 0;
        if (!hasPositions) return;

        cy.batch(function() {
            cy.nodes().forEach(function(node) {
                var saved = cache.positions[node.id()];
                if (saved) {
                    node.position(saved);
                }
            });
        });
        cy.viewport({ zoom: cache.zoom, pan: cache.pan });
    }

    var BGP_STATE_COLORS = {
        "established": "#22c55e",
        "idle": "#ef4444",
        "active": "#f59e0b",
        "connect": "#f59e0b",
        "opensent": "#3b82f6",
        "openconfirm": "#3b82f6",
    };

    var OSPF_STATE_COLORS = {
        "FULL": "#22c55e",
        "2WAY": "#3b82f6",
        "INIT": "#f59e0b",
        "DOWN": "#ef4444",
        "EXSTART": "#f59e0b",
        "EXCHANGE": "#3b82f6",
        "LOADING": "#3b82f6",
    };

    function initRoutingCytoscape(data, mode) {
        var container = $("cy");
        container.innerHTML = "";

        if (cy) { cy.destroy(); cy = null; }

        var validNodes = data.nodes.filter(function(n) {
            return n.data && n.data.id && n.data.id.trim() !== "";
        });
        var validEdges = data.edges.filter(function(e) {
            return e.data && e.data.source && e.data.target &&
                   e.data.source.trim() !== "" && e.data.target.trim() !== "";
        });

        if (validNodes.length === 0) return;

        var isBgp = mode === "bgp";

        cy = cytoscape({
            container: container,
            elements: validNodes.concat(validEdges),
            style: [
                {
                    selector: "node",
                    style: {
                        "shape": "roundrectangle",
                        "label": function(ele) {
                            var label = ele.data("label") || ele.data("id");
                            if (isBgp && ele.data("local_asn")) {
                                label += "\nAS " + ele.data("local_asn");
                            }
                            if (!isBgp && ele.data("router_id")) {
                                label += "\nRID: " + ele.data("router_id");
                            }
                            return label;
                        },
                        "text-valign": "center",
                        "text-halign": "center",
                        "font-size": "9px",
                        "text-wrap": "wrap",
                        "color": "#ffffff",
                        "background-color": isBgp ? "#3b82f6" : "#10b981",
                        "width": function(ele) {
                            var label = ele.data("label") || "";
                            return Math.max(60, Math.min(130, label.length * 6 + 30));
                        },
                        "height": isBgp ? 44 : 40,
                        "border-width": 2,
                        "border-color": isBgp ? "#2563eb" : "#059669",
                        "background-opacity": 0.9,
                    }
                },
                {
                    selector: "node:selected",
                    style: {
                        "border-width": 3,
                        "border-color": "#ffffff",
                        "background-opacity": 1,
                        "z-index": 999
                    }
                },
                {
                    selector: "edge",
                    style: {
                        "label": "data(label)",
                        "font-size": "8px",
                        "color": "#94a3b8",
                        "text-rotation": "autorotate",
                        "text-background-color": "#0f1117",
                        "text-background-opacity": 0.85,
                        "text-background-padding": "2px",
                        "text-background-shape": "roundrectangle",
                        "width": 2.5,
                        "line-color": function(ele) {
                            if (isBgp) {
                                var st = (ele.data("state") || "").toLowerCase();
                                return BGP_STATE_COLORS[st] || "#475569";
                            } else {
                                var ost = (ele.data("state") || "").toUpperCase();
                                return OSPF_STATE_COLORS[ost] || "#475569";
                            }
                        },
                        "curve-style": "bezier",
                        "target-arrow-shape": "none",
                        "opacity": 0.75,
                        "line-style": function(ele) {
                            if (isBgp && ele.data("peering_type") === "eBGP") return "solid";
                            if (isBgp && ele.data("peering_type") === "iBGP") return "dashed";
                            return "solid";
                        }
                    }
                },
                {
                    selector: "edge:selected",
                    style: {
                        "width": 4,
                        "line-color": "#6366f1",
                        "opacity": 1,
                        "z-index": 999
                    }
                }
            ],
            minZoom: 0.02,
            maxZoom: 5,
            zoomingEnabled: true,
            userZoomingEnabled: false,
            panningEnabled: true,
            userPanningEnabled: true,
            boxSelectionEnabled: true,
            selectionType: "additive"
        });

        var count = validNodes.length;
        var repulsion = count > 50 ? 100000 : count > 20 ? 60000 : 40000;
        var edgeLen = count > 50 ? 300 : count > 20 ? 220 : 160;

        cy.elements().layout({
            name: "cose",
            animate: false,
            fit: true,
            padding: 80,
            nodeRepulsion: function() { return repulsion; },
            idealEdgeLength: function() { return edgeLen; },
            nodeOverlap: 50,
            gravity: 0.1,
            numIter: 2000,
            randomize: true
        }).run();

        cy.on("tap", "node", function(evt) { showRoutingNodeDetail(evt.target, mode); });
        cy.on("tap", "edge", function(evt) { showRoutingEdgeDetail(evt.target, mode); });
        cy.on("tap", function(evt) { if (evt.target === cy) closeDetail(); });
        cy.on("select unselect", "node", updateSelectionBar);

        container.addEventListener("wheel", function(evt) {
            evt.preventDefault();
            if (evt.ctrlKey || evt.metaKey) {
                var zoomFactor = evt.deltaY > 0 ? 0.96 : 1.04;
                var rect = container.getBoundingClientRect();
                var pos = { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
                cy.zoom({ level: cy.zoom() * zoomFactor, renderedPosition: pos });
            } else {
                cy.panBy({ x: -evt.deltaX, y: -evt.deltaY });
            }
        }, { passive: false });
    }

    function showRoutingNodeDetail(node, mode) {
        currentDetailNode = null;
        var d = node.data();
        $("device-detail").hidden = false;
        $("detail-hostname").textContent = d.label || d.id;
        document.querySelector(".detail-tabs").hidden = true;

        var html = "";
        var isBgp = mode === "bgp";

        if (isBgp) {
            html += '<div class="device-type-banner" style="background:linear-gradient(135deg,#3b82f6,#2563eb)">BGP Router — AS ' + escapeHtml(d.local_asn || "?") + '</div>';
        } else {
            html += '<div class="device-type-banner" style="background:linear-gradient(135deg,#10b981,#059669)">OSPF Router — RID ' + escapeHtml(d.router_id || "?") + '</div>';
        }

        var fields = [];
        if (isBgp) {
            fields = [
                ["ASN", d.local_asn],
                ["Router ID", d.router_id],
                ["Vendor", d.vendor],
                ["Model", d.model],
                ["Role", d.role],
            ];
        } else {
            fields = [
                ["Router ID", d.router_id],
                ["Process ID", d.process_id],
                ["Areas", (d.areas || []).join(", ")],
                ["Vendor", d.vendor],
                ["Model", d.model],
                ["Role", d.role],
            ];
        }

        fields.forEach(function(f) {
            if (f[1]) html += '<div class="detail-row"><span class="label">' + f[0] + '</span><span class="value">' + escapeHtml(String(f[1])) + '</span></div>';
        });

        var edges = node.connectedEdges();
        if (edges.length > 0) {
            html += '<div class="detail-section"><h4>Peers (' + edges.length + ')</h4>';
            edges.forEach(function(edge) {
                var ed = edge.data();
                var nId = ed.source === d.id ? ed.target : ed.source;
                var nLabel = cy.getElementById(nId).data("label") || nId;
                var stateColor = isBgp
                    ? (BGP_STATE_COLORS[(ed.state || "").toLowerCase()] || "#64748b")
                    : (OSPF_STATE_COLORS[(ed.state || "").toUpperCase()] || "#64748b");

                html += '<div class="detail-neighbor">';
                html += '<div class="neighbor-device">' + escapeHtml(nLabel);
                if (isBgp && ed.remote_asn) html += ' <span class="po-tag">AS' + ed.remote_asn + '</span>';
                if (isBgp && ed.peering_type) html += ' <span class="po-tag">' + ed.peering_type + '</span>';
                html += ' <span style="color:' + stateColor + ';font-weight:600;">' + escapeHtml(ed.state || "") + '</span>';
                html += '</div>';
                if (isBgp) {
                    html += '<div class="neighbor-ports">' + escapeHtml(ed.neighbor_ip || "") + (ed.prefixes ? ' (' + ed.prefixes + ' prefixes)' : '') + '</div>';
                } else {
                    html += '<div class="neighbor-ports">Area ' + escapeHtml(ed.area || "?") + (ed.cost ? ' cost ' + ed.cost : '') + (ed.interface ? ' via ' + escapeHtml(ed.interface) : '') + '</div>';
                }
                if (ed.description) html += '<div class="neighbor-ports" style="color:var(--text-muted);font-style:italic;">' + escapeHtml(ed.description) + '</div>';
                html += '</div>';
            });
            html += '</div>';
        }

        $("detail-content").innerHTML = html;
    }

    function showRoutingEdgeDetail(edge, mode) {
        currentDetailNode = null;
        var d = edge.data();
        $("device-detail").hidden = false;
        $("detail-hostname").textContent = mode === "bgp" ? "BGP Peering" : "OSPF Adjacency";
        document.querySelector(".detail-tabs").hidden = true;

        var srcLabel = cy.getElementById(d.source).data("label") || d.source;
        var tgtLabel = cy.getElementById(d.target).data("label") || d.target;
        var isBgp = mode === "bgp";

        var html = '<div class="link-detail-header"><span class="link-device-badge">' + escapeHtml(srcLabel) + '</span><span class="link-arrow">\u2194</span><span class="link-device-badge">' + escapeHtml(tgtLabel) + '</span></div>';

        var fields = [];
        if (isBgp) {
            fields = [
                ["Peering Type", d.peering_type],
                ["State", d.state],
                ["Local ASN", d.local_asn],
                ["Remote ASN", d.remote_asn],
                ["Neighbor IP", d.neighbor_ip],
                ["Prefixes Received", d.prefixes],
                ["Description", d.description],
                ["Uptime", d.uptime],
            ];
        } else {
            fields = [
                ["Area", d.area],
                ["State", d.state],
                ["Cost", d.cost],
                ["Interface", d.interface],
                ["Neighbor Address", d.neighbor_address],
            ];
        }

        fields.forEach(function(f) {
            if (f[1] !== undefined && f[1] !== "") html += '<div class="detail-row"><span class="label">' + f[0] + '</span><span class="value">' + escapeHtml(String(f[1])) + '</span></div>';
        });

        $("detail-content").innerHTML = html;
    }

    function applyViewFilter() {
        if (!cy || !currentPartition) return;

        var cacheKey = "physical_" + currentView;
        var hasCachedPositions = positionCache[cacheKey] && Object.keys(positionCache[cacheKey].positions).length > 0;

        var connectedIds = {};
        currentPartition.connected.forEach(function(n) { connectedIds[n.data.id] = true; });
        var isolatedIds = {};
        currentPartition.isolated.forEach(function(n) { isolatedIds[n.data.id] = true; });

        cy.batch(function() {
            cy.nodes().forEach(function(n) {
                var id = n.data("id");
                if (currentView === "connected") {
                    n.style("display", connectedIds[id] ? "element" : "none");
                } else if (currentView === "isolated") {
                    n.style("display", isolatedIds[id] ? "element" : "none");
                } else {
                    n.style("display", "element");
                }
            });
            cy.edges().forEach(function(e) {
                if (currentView === "isolated") {
                    e.style("display", "none");
                } else {
                    var srcVisible = cy.getElementById(e.data("source")).style("display") !== "none";
                    var tgtVisible = cy.getElementById(e.data("target")).style("display") !== "none";
                    e.style("display", (srcVisible && tgtVisible) ? "element" : "none");
                }
            });
        });

        if (hasCachedPositions) {
            restorePositions(cacheKey);
        } else {
            runCurrentLayout();
        }
    }

    function runCurrentLayout() {
        if (!cy) return;
        var visible = cy.elements().filter(function(e) { return e.style("display") !== "none"; });
        var visibleNodes = visible.nodes();
        var visibleEdges = visible.edges();

        if (visibleNodes.length === 0) {
            cy.fit(null, 50);
            return;
        }

        var layoutName = $("layout-select").value || "breadthfirst";

        if (currentView === "isolated" || visibleEdges.length === 0) {
            var cols = Math.max(4, Math.ceil(Math.sqrt(visibleNodes.length * 1.8)));
            visibleNodes.layout({
                name: "grid",
                animate: false,
                fit: true,
                padding: 60,
                cols: cols,
                avoidOverlap: true,
                avoidOverlapPadding: 30
            }).run();
            return;
        }

        if (layoutName === "cose") {
            var count = visibleNodes.length;
            var repulsion = count > 100 ? 120000 : count > 40 ? 80000 : 50000;
            var edgeLen = count > 100 ? 350 : count > 40 ? 280 : 200;
            var grav = count > 100 ? 0.05 : count > 40 ? 0.08 : 0.12;
            var iters = count > 100 ? 3000 : 2000;

            visible.layout({
                name: "cose",
                animate: false,
                fit: true,
                padding: 80,
                nodeRepulsion: function() { return repulsion; },
                idealEdgeLength: function() { return edgeLen; },
                nodeOverlap: 60,
                gravity: grav,
                numIter: iters,
                randomize: true
            }).run();
        } else if (layoutName === "cola") {
            visible.layout({
                name: "cola",
                animate: false,
                fit: true,
                padding: 80,
                nodeSpacing: function() { return 60; },
                edgeLength: function() { return 250; },
                randomize: true,
                maxSimulationTime: 5000
            }).run();
        } else {
            visible.layout({
                name: layoutName,
                animate: false,
                fit: true,
                padding: 60,
                avoidOverlap: true,
                spacingFactor: 1.8
            }).run();
        }
    }

    function showDeviceDetail(node) {
        currentDetailNode = node;
        currentTab = "info";
        $("device-detail").hidden = false;
        $("detail-hostname").textContent = node.data("label");
        document.querySelector(".detail-tabs").hidden = false;
        setupTabs();
        renderTab("info");
    }

    function showEdgeDetail(edge) {
        currentDetailNode = null;
        var d = edge.data();
        $("device-detail").hidden = false;
        $("detail-hostname").textContent = "Link Detail";
        document.querySelector(".detail-tabs").hidden = true;

        var srcLabel = cy.getElementById(d.source).data("label") || d.source;
        var tgtLabel = cy.getElementById(d.target).data("label") || d.target;

        var html = '<div class="link-detail-header"><span class="link-device-badge">' + escapeHtml(srcLabel) + '</span><span class="link-arrow">\u2194</span><span class="link-device-badge">' + escapeHtml(tgtLabel) + '</span></div>';

        var isPo = (d.local_interface || "").toLowerCase().indexOf("po") === 0 ||
                   (d.remote_interface || "").toLowerCase().indexOf("po") === 0;

        if (isPo) {
            html += '<div class="po-badge">Port-Channel / VPC Link</div>';
        }

        var linkStatus = d.link_status || "";
        if (linkStatus) {
            var statusClass = "link-status-" + linkStatus.replace("/", "-");
            var statusLabel = linkStatus === "up/down" ? "Admin Up / Oper Down" :
                              linkStatus === "down" ? "Down" :
                              linkStatus === "up" ? "Up" : linkStatus;
            html += '<div class="link-status-badge ' + statusClass + '">' + statusLabel + '</div>';
        }

        var fields = [
            ["Speed", d.speed],
            ["Protocol", d.protocol],
            ["Confidence", d.confidence],
            ["Local Interface", d.local_interface],
            ["Remote Interface", d.remote_interface]
        ];
        fields.forEach(function(f) {
            if (f[1]) html += '<div class="detail-row"><span class="label">' + f[0] + '</span><span class="value">' + escapeHtml(String(f[1])) + '</span></div>';
        });

        if (isPo && topologyData && topologyData.port_channels) {
            var srcId = d.source;
            var poIntf = d.local_interface || d.remote_interface || "";
            var pcKey = srcId + ":" + poIntf;
            var pcInfo = topologyData.port_channels[pcKey];
            if (pcInfo) {
                html += '<div class="detail-section"><h4>Port-Channel Members</h4>';
                (pcInfo.members || []).forEach(function(m) {
                    html += '<div class="detail-neighbor"><div class="neighbor-device">' + escapeHtml(m) + '</div></div>';
                });
                if (pcInfo.protocol) {
                    html += '<div class="detail-row"><span class="label">Protocol</span><span class="value">' + escapeHtml(pcInfo.protocol) + '</span></div>';
                }
                html += '</div>';
            }
        }

        if (d.members && d.members.length > 0) {
            html += '<div class="detail-section"><h4>Member Links (' + d.member_count + ')</h4>';
            d.members.forEach(function(m) {
                html += '<div class="detail-neighbor"><div class="neighbor-ports">' + escapeHtml(m) + '</div></div>';
            });
            html += '</div>';
        }

        $("detail-content").innerHTML = html;
    }

    function setupTabs() {
        var btns = document.querySelectorAll(".tab-btn");
        btns.forEach(function(btn) {
            btn.classList.toggle("active", btn.dataset.tab === currentTab);
            btn.onclick = function() {
                currentTab = btn.dataset.tab;
                btns.forEach(function(b) { b.classList.toggle("active", b.dataset.tab === currentTab); });
                renderTab(currentTab);
            };
        });
    }

    function renderTab(tab) {
        if (!currentDetailNode) return;
        clearIntfHighlight();
        var data = currentDetailNode.data();
        var deviceId = data.id;
        var details = topologyData.device_details ? topologyData.device_details[deviceId] : null;

        if (tab === "info") renderInfoTab(data, currentDetailNode);
        else if (tab === "interfaces") renderInterfacesTab(details);
        else if (tab === "config") renderConfigTab(details);
    }

    function renderInfoTab(data, node) {
        var html = "";

        var vendor = data.vendor || "";
        var model = data.model || "";
        var deviceType = "";
        if (vendor && model) {
            deviceType = vendor + " " + model;
        } else if (vendor) {
            deviceType = vendor;
        } else if (model) {
            deviceType = model;
        }

        if (deviceType) {
            html += '<div class="device-type-banner">' + escapeHtml(deviceType) + '</div>';
        }

        var fields = [
            ["Vendor", data.vendor],
            ["Model", data.model],
            ["Role", data.role ? data.role.charAt(0).toUpperCase() + data.role.slice(1) : ""],
            ["Platform", data.platform],
            ["Software", data.software_version],
            ["Serial", data.serial],
            ["Uptime", data.uptime],
            ["Mgmt IP", data.mgmt_ip],
            ["Interfaces", data.interface_count],
            ["Connections", node.degree()]
        ];
        fields.forEach(function(f) {
            if (f[1]) html += '<div class="detail-row"><span class="label">' + f[0] + '</span><span class="value">' + escapeHtml(String(f[1])) + '</span></div>';
        });

        if (node.degree() === 0) {
            html += '<div class="isolated-badge">Isolated Device (no discovered links)</div>';
        }

        var edges = node.connectedEdges();
        if (edges.length > 0) {
            html += '<div class="detail-section"><h4>Neighbors (' + edges.length + ')</h4>';
            edges.forEach(function(edge) {
                var ed = edge.data();
                var nId = ed.source === data.id ? ed.target : ed.source;
                var nNode = cy.getElementById(nId);
                var nLabel = nNode.data("label") || nId;
                var lp = ed.source === data.id ? ed.local_interface : ed.remote_interface;
                var rp = ed.source === data.id ? ed.remote_interface : ed.local_interface;
                var spd = ed.speed ? " [" + ed.speed + "]" : "";
                var poTag = (lp || "").toLowerCase().indexOf("po") === 0 ? ' <span class="po-tag">Po</span>' : "";

                var linkSt = ed.link_status || "";
                var stTag = "";
                if (linkSt === "down") {
                    stTag = ' <span class="link-st-tag down">DOWN</span>';
                } else if (linkSt === "up/down") {
                    stTag = ' <span class="link-st-tag warn">UP/DOWN</span>';
                }

                html += '<div class="neighbor-clickable" data-peer="' + nId + '"><span class="intf-expand-icon">\u25B6</span> <span class="neighbor-device">' + escapeHtml(nLabel) + spd + poTag + stTag + '</span><div class="neighbor-ports">' + escapeHtml(lp) + ' \u2192 ' + escapeHtml(rp) + ' (' + ed.protocol + ')</div></div>';

                var nData = nNode.data() || {};
                var peerHtml = '<div class="neighbor-detail-panel">';
                if (nData.vendor || nData.model) peerHtml += '<div><strong>' + escapeHtml((nData.vendor || '') + ' ' + (nData.model || '')) + '</strong></div>';
                if (nData.role) peerHtml += '<div>Role: ' + nData.role + '</div>';
                if (nData.mgmt_ip) peerHtml += '<div>Mgmt IP: ' + nData.mgmt_ip + '</div>';
                peerHtml += '<div>Connections: ' + nNode.degree() + '</div>';
                peerHtml += '</div>';
                html += peerHtml;
            });
            html += '</div>';
        }
        $("detail-content").innerHTML = html;
        currentSelectedNode = data.id;
        attachNeighborClickHandlers();
    }

    function renderInterfacesTab(details) {
        if (!details || !details.interfaces || details.interfaces.length === 0) {
            $("detail-content").innerHTML = '<p style="color:var(--text-muted);font-size:13px;padding:16px 0;">No interface data available.<br><br>Upload "show ip interface brief" or "show interface status" for this device.</p>';
            return;
        }

        var intfs = details.interfaces;
        var upCount = 0, downCount = 0, adminDownCount = 0;
        intfs.forEach(function(intf) {
            var st = (intf.status || "").toLowerCase();
            var proto = (intf.protocol || "").toLowerCase();
            if (st.indexOf("up") >= 0 && proto.indexOf("up") >= 0) upCount++;
            else if (st.indexOf("admin") >= 0 || st.indexOf("disabled") >= 0) adminDownCount++;
            else downCount++;
        });

        var html = '<div class="intf-summary">';
        html += '<span class="intf-stat up">' + upCount + ' Up</span>';
        html += '<span class="intf-stat down">' + downCount + ' Down</span>';
        if (adminDownCount > 0) html += '<span class="intf-stat admin-down">' + adminDownCount + ' Admin Down</span>';
        html += '<span class="intf-stat total">' + intfs.length + ' Total</span>';
        html += '</div>';

        html += '<table class="intf-table"><thead><tr><th>Interface</th><th>Status</th><th>Protocol</th><th>IP / VLAN</th><th>Description</th><th>Channel</th></tr></thead><tbody>';
        intfs.forEach(function(intf, idx) {
            var name = intf.interface || intf.name || "";
            var status = intf.status || "";
            var protocol = intf.protocol || "";
            var statusLower = status.toLowerCase() + " " + protocol.toLowerCase();
            var cls = "";
            if (statusLower.indexOf("admin") >= 0 || statusLower.indexOf("disabled") >= 0) {
                cls = "intf-status-admin-down";
            } else if (statusLower.indexOf("up") >= 0 && protocol.toLowerCase().indexOf("up") >= 0) {
                cls = "intf-status-up";
            } else {
                cls = "intf-status-down";
            }
            var ip = intf.ip_address || "";
            var vlan = intf.vlan ? "VLAN " + intf.vlan : "";
            var ipVlan = ip || vlan || "";
            var desc = intf.description || "";
            var chGroup = intf.channel_group || "";

            html += '<tr class="' + cls + '-row intf-row-clickable" data-intf-name="' + escapeHtml(name) + '" data-intf-idx="' + idx + '">';
            html += '<td class="intf-name">' + escapeHtml(name) + ' <span class="intf-expand-icon">&#9662;</span></td>';
            html += '<td class="' + cls + '">' + escapeHtml(status) + '</td>';
            html += '<td class="' + cls + '">' + escapeHtml(protocol) + '</td>';
            html += '<td>' + escapeHtml(ipVlan) + '</td>';
            html += '<td class="intf-desc">' + escapeHtml(desc) + '</td>';
            html += '<td>' + escapeHtml(chGroup) + '</td></tr>';
            html += '<tr class="intf-detail-row" id="intf-detail-' + idx + '" style="display:none;"><td colspan="6"><div class="intf-detail-content">Loading...</div></td></tr>';
        });
        html += '</tbody></table>';
        $("detail-content").innerHTML = html;

        var rows = document.querySelectorAll(".intf-row-clickable");
        rows.forEach(function(row) {
            row.addEventListener("click", function() {
                var intfName = row.getAttribute("data-intf-name");
                var idx = row.getAttribute("data-intf-idx");
                var detailRow = document.getElementById("intf-detail-" + idx);

                if (detailRow.style.display === "none") {
                    document.querySelectorAll(".intf-detail-row").forEach(function(r) { r.style.display = "none"; });
                    document.querySelectorAll(".intf-row-clickable").forEach(function(r) { r.classList.remove("intf-row-active"); });
                    row.classList.add("intf-row-active");
                    detailRow.style.display = "table-row";
                    populateIntfDetail(intfName, detailRow.querySelector(".intf-detail-content"));
                    highlightIntfOnCanvas(intfName);
                } else {
                    detailRow.style.display = "none";
                    row.classList.remove("intf-row-active");
                    clearIntfHighlight();
                }
            });
        });
    }

    function populateIntfDetail(intfName, container) {
        if (!cy || !currentDetailNode) {
            container.innerHTML = '<span class="intf-detail-none">No connection data</span>';
            return;
        }

        var nodeId = currentDetailNode.id();
        var connectedEdge = null;
        var connectedNode = null;
        var intfNorm = normalizeIntfName(intfName);

        cy.edges().forEach(function(edge) {
            var d = edge.data();
            var localNorm = normalizeIntfName(d.local_interface || "");
            var remoteNorm = normalizeIntfName(d.remote_interface || "");

            if (d.source === nodeId && localNorm === intfNorm) {
                connectedEdge = edge;
                connectedNode = cy.getElementById(d.target);
            } else if (d.target === nodeId && remoteNorm === intfNorm) {
                connectedEdge = edge;
                connectedNode = cy.getElementById(d.source);
            }
        });

        if (!connectedNode || connectedNode.empty()) {
            container.innerHTML = '<span class="intf-detail-none">No connected device found for this interface</span>';
            return;
        }

        var nd = connectedNode.data();
        var ed = connectedEdge ? connectedEdge.data() : {};
        var roleColor = ROLE_COLORS[nd.role] || "#64748b";

        var html = '<div class="intf-connected-device">';
        html += '<div class="intf-conn-header">';
        html += '<span class="intf-conn-badge" style="background:' + roleColor + '">' + escapeHtml(nd.role || "switch") + '</span>';
        html += '<span class="intf-conn-name">' + escapeHtml(nd.label || nd.id) + '</span>';
        html += '</div>';

        html += '<div class="intf-conn-details">';
        if (nd.vendor) html += '<div class="intf-conn-row"><span>Vendor:</span><span>' + escapeHtml(nd.vendor) + '</span></div>';
        if (nd.model) html += '<div class="intf-conn-row"><span>Model:</span><span>' + escapeHtml(nd.model) + '</span></div>';
        if (nd.mgmt_ip) html += '<div class="intf-conn-row"><span>Mgmt IP:</span><span>' + escapeHtml(nd.mgmt_ip) + '</span></div>';
        if (ed.remote_interface) html += '<div class="intf-conn-row"><span>Remote Port:</span><span>' + escapeHtml(ed.remote_interface) + '</span></div>';
        if (ed.speed) html += '<div class="intf-conn-row"><span>Speed:</span><span>' + escapeHtml(ed.speed) + '</span></div>';
        if (ed.link_status) {
            var stColor = ed.link_status === "up" ? "#22c55e" : ed.link_status === "down" ? "#ef4444" : "#f59e0b";
            html += '<div class="intf-conn-row"><span>Link Status:</span><span style="color:' + stColor + '">' + escapeHtml(ed.link_status) + '</span></div>';
        }
        if (ed.protocol) html += '<div class="intf-conn-row"><span>Discovery:</span><span>' + escapeHtml(ed.protocol) + '</span></div>';
        html += '</div></div>';

        container.innerHTML = html;
    }

    function normalizeIntfName(name) {
        if (!name) return "";
        var n = name.toLowerCase().replace(/\s+/g, "");
        n = n.replace(/^gigabitethernet/, "gi");
        n = n.replace(/^tengigabitethernet/, "te");
        n = n.replace(/^twentyfivegige?/, "twe");
        n = n.replace(/^fortygigabitethernet/, "fo");
        n = n.replace(/^hundredgige?/, "hu");
        n = n.replace(/^fastethernet/, "fa");
        n = n.replace(/^port-channel/, "po");
        n = n.replace(/^ethernet/, "eth");
        n = n.replace(/^loopback/, "lo");
        n = n.replace(/^management/, "mgmt");
        n = n.replace(/^mgmteth/, "mgmteth");
        return n;
    }

    function highlightIntfOnCanvas(intfName) {
        if (!cy || !currentDetailNode) return;

        cy.elements().removeClass("intf-highlighted");

        var nodeId = currentDetailNode.id();
        var intfNorm = normalizeIntfName(intfName);

        cy.edges().forEach(function(edge) {
            var d = edge.data();
            var localNorm = normalizeIntfName(d.local_interface || "");
            var remoteNorm = normalizeIntfName(d.remote_interface || "");

            if ((d.source === nodeId && localNorm === intfNorm) ||
                (d.target === nodeId && remoteNorm === intfNorm)) {
                edge.addClass("intf-highlighted");
                var peerId = d.source === nodeId ? d.target : d.source;
                cy.getElementById(peerId).addClass("intf-highlighted");
            }
        });
    }

    function clearIntfHighlight() {
        if (!cy) return;
        cy.elements().removeClass("intf-highlighted");
    }

    function renderConfigTab(details) {
        if (!details || !details.config || Object.keys(details.config).length === 0) {
            $("detail-content").innerHTML = '<p style="color:var(--text-muted);font-size:13px;padding:16px 0;">No running config available.<br><br>Upload "show running-config" for this device.</p>';
            return;
        }
        var config = details.config;
        var html = "";

        if (config.port_channels && config.port_channels.length > 0) {
            html += '<div class="config-section-title">Port-Channels (' + config.port_channels.length + ')</div><div class="config-block">';
            config.port_channels.forEach(function(pc) {
                html += "Port-channel" + pc.id;
                if (pc.protocol) html += " (" + pc.protocol + ")";
                html += "\n";
                if (pc.members && pc.members.length > 0) {
                    pc.members.forEach(function(m) { html += "  member: " + m + "\n"; });
                }
            });
            html += '</div>';
        }

        if (config.vpc) {
            html += '<div class="config-section-title">VPC</div><div class="config-block">';
            if (config.vpc.domain) html += "vpc domain " + config.vpc.domain + "\n";
            if (config.vpc.role_priority) html += "  role priority " + config.vpc.role_priority + "\n";
            if (config.vpc.peer_keepalive) html += "  peer-keepalive " + config.vpc.peer_keepalive + "\n";
            if (config.vpc.peer_link) html += "  peer-link: " + config.vpc.peer_link + "\n";
            if (config.vpc.vpcs && config.vpc.vpcs.length > 0) {
                config.vpc.vpcs.forEach(function(v) {
                    html += "  vpc " + v.id + " -> " + v.interface + "\n";
                });
            }
            html += '</div>';
        }

        if (config.vlans && config.vlans.length > 0) {
            html += '<div class="config-section-title">VLANs (' + config.vlans.length + ')</div><div class="config-block">';
            config.vlans.forEach(function(v) { html += "vlan " + v.id + (v.name ? " - " + v.name : "") + "\n"; });
            html += '</div>';
        }

        if (config.routing) {
            var r = config.routing;
            if ((r.ospf && r.ospf.length) || (r.bgp && r.bgp.length) || (r.static && r.static.length)) {
                html += '<div class="config-section-title">Routing</div><div class="config-block">';
                (r.ospf || []).forEach(function(o) { html += "router ospf " + o.process_id + "\n"; });
                (r.bgp || []).forEach(function(b) { html += "router bgp " + b.asn + "\n"; });
                (r.static || []).forEach(function(s) { html += "ip route " + s.network + " " + s.mask + " " + s.next_hop + "\n"; });
                html += '</div>';
            }
        }

        if (config.interfaces && config.interfaces.length > 0) {
            html += '<div class="config-section-title">Interfaces (' + config.interfaces.length + ')</div><div class="config-block">';
            config.interfaces.forEach(function(intf) {
                html += "interface " + intf.name + "\n";
                if (intf.description) html += "  description " + intf.description + "\n";
                if (intf.ip_address) html += "  ip address " + intf.ip_address + " " + intf.subnet_mask + "\n";
                if (intf.switchport_mode) html += "  switchport mode " + intf.switchport_mode + "\n";
                if (intf.vlan) html += "  switchport access vlan " + intf.vlan + "\n";
                if (intf.channel_group) html += "  channel-group " + intf.channel_group + "\n";
                if (intf.vpc) html += "  vpc " + intf.vpc + "\n";
                if (intf.shutdown) html += "  shutdown\n";
                html += "!\n";
            });
            html += '</div>';
        }

        if (config.management && (config.management.ip || config.management.vrf)) {
            html += '<div class="config-section-title">Management</div><div class="config-block">';
            if (config.management.ip) html += "ip: " + config.management.ip + "\n";
            if (config.management.vrf) html += "vrf: " + config.management.vrf + "\n";
            if (config.management.domain) html += "domain: " + config.management.domain + "\n";
            html += '</div>';
        }

        if (!html) html = '<p style="color:var(--text-muted);font-size:13px;padding:16px 0;">Config parsed but no sections found.</p>';
        $("detail-content").innerHTML = html;
    }

    function closeDetail() {
        clearIntfHighlight();
        $("device-detail").hidden = true;
    }

    function applyLayout() {
        if (!cy) return;
        var cacheKey = currentTopoMode === "physical" ? "physical_" + currentView : currentTopoMode;
        delete positionCache[cacheKey];
        runCurrentLayout();
    }

    function exportPNG() {
        if (!cy) return;
        var png = cy.png({ output: "blob", bg: "#0f1117", scale: 2, full: true });
        var url = URL.createObjectURL(png);
        var a = document.createElement("a");
        a.href = url;
        a.download = "fabric-topology.png";
        a.click();
        URL.revokeObjectURL(url);
    }

    function updateSelectionBar() {
        if (!cy) return;
        var selected = cy.nodes(":selected");
        var count = selected.length;
        if (count > 0) {
            $("selection-bar").hidden = false;
            $("selection-count").textContent = count + " device" + (count > 1 ? "s" : "") + " selected";
            $("btn-export-drawio").disabled = false;
        } else {
            $("selection-bar").hidden = true;
            $("btn-export-drawio").disabled = true;
        }
    }

    function clearSelection() {
        if (cy) cy.nodes().unselect();
        $("selection-bar").hidden = true;
    }

    function exportDrawio() {
        if (!cy) return;
        var selected = cy.nodes(":selected");
        if (selected.length === 0) {
            selected = cy.nodes().filter(function(n) { return n.style("display") !== "none"; });
        }
        if (selected.length === 0) return;

        var nodeIds = {};
        selected.forEach(function(n) { nodeIds[n.data("id")] = true; });

        var edges = cy.edges().filter(function(e) {
            return nodeIds[e.data("source")] && nodeIds[e.data("target")];
        });

        var cellId = 2;
        var nodeIdMap = {};
        var cells = "";

        cells += '<mxCell id="0"/>\n';
        cells += '<mxCell id="1" parent="0"/>\n';

        var roleStyles = {
            "switch": "shape=mxgraph.cisco.switches.workgroup_switch;",
            "router": "shape=mxgraph.cisco.routers.router;",
            "firewall": "shape=mxgraph.cisco.firewalls.firewall;",
            "loadbalancer": "shape=mxgraph.cisco.servers.standard_server;",
            "spine": "shape=mxgraph.cisco.switches.layer_3_switch;",
            "leaf": "shape=mxgraph.cisco.switches.workgroup_switch;",
            "wlc": "shape=mxgraph.cisco.wireless.wireless_router;",
            "endpoint": "shape=mxgraph.cisco.computers_and_peripherals.pc;",
            "border": "shape=mxgraph.cisco.routers.router;"
        };

        selected.forEach(function(n) {
            var d = n.data();
            var pos = n.renderedPosition();
            var w = 80, h = 60;
            var style = roleStyles[d.role] || "rounded=1;whiteSpace=wrap;";
            style += "fillColor=" + (ROLE_COLORS[d.role] || "#64748b") + ";fontColor=#ffffff;strokeColor=#333333;";
            var label = d.label || d.id;
            var vendor = d.vendor || "";
            var model = d.model || "";
            var tooltip = "";
            if (vendor) tooltip += vendor;
            if (model) tooltip += (tooltip ? " " : "") + model;

            cells += '<mxCell id="' + cellId + '" value="' + escapeXml(label) + '" style="' + style + '" vertex="1" parent="1">\n';
            cells += '  <mxGeometry x="' + Math.round(pos.x) + '" y="' + Math.round(pos.y) + '" width="' + w + '" height="' + h + '" as="geometry"/>\n';
            if (tooltip) {
                cells += '  <Object label="' + escapeXml(label) + '" tooltip="' + escapeXml(tooltip) + '" as="UserObject"/>\n';
            }
            cells += '</mxCell>\n';
            nodeIdMap[d.id] = cellId;
            cellId++;
        });

        edges.forEach(function(e) {
            var ed = e.data();
            var srcId = nodeIdMap[ed.source];
            var tgtId = nodeIdMap[ed.target];
            if (!srcId || !tgtId) return;

            var label = "";
            if (ed.local_interface && ed.remote_interface) {
                label = ed.local_interface + " - " + ed.remote_interface;
            }
            if (ed.speed) label += (label ? " " : "") + "[" + ed.speed + "]";

            var style = "edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#666666;";
            if (ed.link_status === "down") style += "strokeColor=#ef4444;dashed=1;";
            else if (ed.link_status === "up") style += "strokeColor=#22c55e;";

            cells += '<mxCell id="' + cellId + '" value="' + escapeXml(label) + '" style="' + style + '" edge="1" parent="1" source="' + srcId + '" target="' + tgtId + '">\n';
            cells += '  <mxGeometry relative="1" as="geometry"/>\n';
            cells += '</mxCell>\n';
            cellId++;
        });

        var xml = '<?xml version="1.0" encoding="UTF-8"?>\n';
        xml += '<mxfile host="app.diagrams.net">\n';
        xml += '  <diagram name="Fabric Topology">\n';
        xml += '    <mxGraphModel>\n';
        xml += '      <root>\n';
        xml += cells;
        xml += '      </root>\n';
        xml += '    </mxGraphModel>\n';
        xml += '  </diagram>\n';
        xml += '</mxfile>';

        var blob = new Blob([xml], { type: "application/xml" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "fabric-topology.drawio";
        a.click();
        URL.revokeObjectURL(url);
    }

    function escapeXml(str) {
        if (!str) return "";
        return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
    }

    /* ===== Migration Panel ===== */
    var currentMigTab = "underlay";

    function renderMigrationPanel() {
        var container = $("migration-content");
        if (!container) return;

        var tabBtns = document.querySelectorAll(".mig-tab-btn");
        tabBtns.forEach(function (btn) {
            btn.classList.toggle("active", btn.dataset.migtab === currentMigTab);
            btn.onclick = function () {
                currentMigTab = btn.dataset.migtab;
                renderMigrationPanel();
            };
        });

        var mig = topologyData && topologyData.migration;
        if (!mig || !mig.classifications || Object.keys(mig.classifications).length === 0) {
            container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px 0;">No migration data available.<br>Upload more device outputs for migration analysis.</p>';
            return;
        }

        if (currentMigTab === "underlay") { renderUnderlayPanel(container, mig); }
        else if (currentMigTab === "vni") { renderVniPanel(container, mig); }
        else if (currentMigTab === "phases") { renderPhasesPanel(container, mig); }
        else if (currentMigTab === "roles") { renderRolesPanel(container, mig); }
    }

    function renderUnderlayPanel(container, mig) {
        var design = mig.underlay_design || {};
        var params = design.protocol_params || {};
        var summary = design.summary || {};
        var perDevice = design.per_device || {};

        var proto = params.underlay_protocol || "ospf";
        var afs = params.bgp_address_families || ["l2vpn_evpn"];
        var ospfArea = params.ospf_area || "0.0.0.0";
        var spineAsn = params.spine_asn || 65000;
        var leafAsnStart = params.leaf_asn_start || 65001;

        var html = '<div class="underlay-panel">';
        html += '<div class="underlay-controls">';

        html += '<div class="underlay-control-group"><label>Underlay Protocol</label><div class="ul-proto-btns">';
        html += '<button class="ul-proto-btn' + (proto === "ospf" ? " active" : "") + '" data-proto="ospf">OSPF</button>';
        html += '<button class="ul-proto-btn' + (proto === "ebgp" ? " active" : "") + '" data-proto="ebgp">eBGP</button>';
        html += '</div></div>';

        html += '<div class="underlay-control-group"><label>BGP Address Families</label><div class="af-checks">';
        html += '<label class="af-check"><input type="checkbox" value="l2vpn_evpn" checked disabled> L2VPN EVPN (required)</label>';
        html += '<label class="af-check"><input type="checkbox" value="ipv4_unicast"' + (afs.indexOf("ipv4_unicast") >= 0 ? " checked" : "") + '> IPv4 Unicast</label>';
        html += '<label class="af-check"><input type="checkbox" value="ipv6_unicast"' + (afs.indexOf("ipv6_unicast") >= 0 ? " checked" : "") + '> IPv6 Unicast</label>';
        html += '</div></div>';

        html += '<div class="ul-param-row">';
        html += '<div class="ul-param-input" id="ul-ospf-area-wrap"' + (proto !== "ospf" ? ' style="display:none"' : '') + '><label>OSPF Area</label><input type="text" id="ul-ospf-area" value="' + ospfArea + '"></div>';
        html += '<div class="ul-param-input"><label>Spine ASN</label><input type="number" id="ul-spine-asn" value="' + spineAsn + '"></div>';
        html += '<div class="ul-param-input" id="ul-leaf-asn-wrap"' + (proto !== "ebgp" ? ' style="display:none"' : '') + '><label>Leaf ASN Start</label><input type="number" id="ul-leaf-asn" value="' + leafAsnStart + '"></div>';
        html += '</div>';

        html += '<button class="ul-apply-btn" id="ul-apply">Apply Design</button>';
        html += '</div>';

        if (summary.underlay) {
            html += '<div class="underlay-summary">';
            html += '<div class="ul-summary-row"><span class="label">Underlay</span><span class="value">' + summary.underlay + '</span></div>';
            html += '<div class="ul-summary-row"><span class="label">Overlay</span><span class="value">' + summary.overlay + '</span></div>';
            html += '<div class="ul-summary-row"><span class="label">Fabric Devices</span><span class="value">' + (summary.total_fabric_devices || 0) + '</span></div>';
            if (summary.design_notes && summary.design_notes.length) {
                html += '<div class="ul-design-notes"><ul>';
                summary.design_notes.forEach(function (n) { html += '<li>' + n + '</li>'; });
                html += '</ul></div>';
            }
            html += '</div>';
        }

        var deviceIds = Object.keys(perDevice);
        if (deviceIds.length > 0) {
            html += '<div class="underlay-devices">';
            deviceIds.forEach(function (did) {
                var d = perDevice[did];
                var role = d.proposed_role || "leaf";
                html += '<div class="ul-device-card" data-devid="' + did + '">';
                html += '<div class="ul-device-header"><span class="ul-role-badge ' + role + '">' + role.replace("_", " ") + '</span><span class="ul-device-name">' + (d.label || did) + '</span></div>';
                html += '<div class="ul-device-body">';

                if (d.underlay && d.underlay.config_notes) {
                    html += '<div class="ul-section"><h5>Underlay (' + (d.underlay.protocol || "") + ')</h5><ul class="ul-notes">';
                    d.underlay.config_notes.forEach(function (n) { html += '<li>' + n + '</li>'; });
                    html += '</ul></div>';
                }
                if (d.overlay && d.overlay.address_families) {
                    html += '<div class="ul-section"><h5>Overlay (' + (d.overlay.protocol || "") + ')</h5><div class="ul-af-list">';
                    d.overlay.address_families.forEach(function (af) {
                        html += '<div class="ul-af-item"><span class="ul-af-name">' + (af.label || af.af) + '</span>';
                        if (af.notes) html += '<span class="ul-af-note">' + af.notes + '</span>';
                        html += '</div>';
                    });
                    html += '</div></div>';
                }

                html += '</div></div>';
            });
            html += '</div>';
        }

        html += '</div>';
        container.innerHTML = html;

        container.querySelectorAll(".ul-proto-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                container.querySelectorAll(".ul-proto-btn").forEach(function (b) { b.classList.remove("active"); });
                btn.classList.add("active");
                var selProto = btn.dataset.proto;
                var ospfWrap = document.getElementById("ul-ospf-area-wrap");
                var leafWrap = document.getElementById("ul-leaf-asn-wrap");
                if (ospfWrap) ospfWrap.style.display = selProto === "ospf" ? "" : "none";
                if (leafWrap) leafWrap.style.display = selProto === "ebgp" ? "" : "none";
            });
        });

        container.querySelectorAll(".ul-device-card").forEach(function (card) {
            card.querySelector(".ul-device-header").addEventListener("click", function () {
                card.classList.toggle("expanded");
                if (cy) {
                    var devId = card.dataset.devid;
                    cy.elements().removeClass("highlighted");
                    var node = cy.getElementById(devId);
                    if (node.length && card.classList.contains("expanded")) {
                        node.addClass("highlighted");
                        cy.animate({ center: { eles: node }, duration: 300 });
                    }
                }
            });
        });

        var applyBtn = document.getElementById("ul-apply");
        if (applyBtn) {
            applyBtn.addEventListener("click", function () {
                var selProto = container.querySelector(".ul-proto-btn.active");
                var proto = selProto ? selProto.dataset.proto : "ospf";
                var afChecks = container.querySelectorAll(".af-check input:checked");
                var selectedAfs = [];
                afChecks.forEach(function (cb) { selectedAfs.push(cb.value); });

                var ospfArea = (document.getElementById("ul-ospf-area") || {}).value || "0.0.0.0";
                var spineAsn = parseInt((document.getElementById("ul-spine-asn") || {}).value) || 65000;
                var leafAsnStart = parseInt((document.getElementById("ul-leaf-asn") || {}).value) || 65001;

                var mig = topologyData.migration;
                var nodesMap = {};
                (topologyData.nodes || []).forEach(function (n) { nodesMap[n.data.id] = n.data; });
                var adj = {};
                (topologyData.edges || []).forEach(function (e) {
                    var s = e.data.source, t = e.data.target;
                    if (!adj[s]) adj[s] = [];
                    if (!adj[t]) adj[t] = [];
                    adj[s].push(e.data);
                    adj[t].push(e.data);
                });

                applyBtn.textContent = "Applying...";
                applyBtn.disabled = true;

                fetch("/api/redesign-underlay", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        underlay_protocol: proto,
                        bgp_afs: selectedAfs,
                        ospf_area: ospfArea,
                        spine_asn: spineAsn,
                        leaf_asn_start: leafAsnStart,
                        classifications: mig.classifications,
                        nodes: nodesMap,
                        adjacency: adj,
                    }),
                })
                .then(function (r) { return r.json(); })
                .then(function (result) {
                    topologyData.migration.underlay_design = result;
                    renderUnderlayPanel(container, topologyData.migration);
                })
                .catch(function () {
                    applyBtn.textContent = "Apply Design";
                    applyBtn.disabled = false;
                });
            });
        }
    }

    function renderVniPanel(container, mig) {
        var mapping = mig.vni_mapping || [];
        if (!mapping.length) {
            container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px 0;">No VLAN data found for VNI mapping.</p>';
            return;
        }
        var html = '<table class="vni-table"><thead><tr><th>VLAN</th><th>Name</th><th>VNI</th><th>Devices</th><th>Gateways</th></tr></thead><tbody>';
        mapping.forEach(function (m) {
            html += '<tr><td>' + m.vlan_id + '</td><td>' + (m.vlan_name || '-') + '</td><td>' + m.vni + '</td><td>' + (m.device_count || 0) + '</td><td>' + (m.gateways || []).join(', ') + '</td></tr>';
        });
        html += '</tbody></table>';
        container.innerHTML = html;
    }

    function renderPhasesPanel(container, mig) {
        var phases = mig.phases || [];
        if (!phases.length) {
            container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px 0;">No phase data.</p>';
            return;
        }
        var html = '';
        phases.forEach(function (phase) {
            html += '<div class="phase-card"><h4>' + phase.name + '</h4><p>' + (phase.description || '') + '</p>';
            if (phase.devices && phase.devices.length) {
                html += '<div class="phase-devices">';
                phase.devices.forEach(function (d) { html += '<span class="phase-device-tag">' + d + '</span>'; });
                html += '</div>';
            } else {
                html += '<p style="font-size:10px;color:var(--text-muted);">No devices assigned</p>';
            }
            html += '</div>';
        });
        container.innerHTML = html;
    }

    function renderRolesPanel(container, mig) {
        var cls = mig.classifications || {};
        var ids = Object.keys(cls);
        if (!ids.length) {
            container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px 0;">No classifications.</p>';
            return;
        }
        var html = '<div style="display:flex;flex-direction:column;">';
        ids.forEach(function (id) {
            var info = cls[id];
            var role = info.proposed_role || "unknown";
            var conf = info.confidence || 0;
            html += '<div class="role-card">';
            html += '<span class="role-label">' + id + '</span>';
            html += '<span class="role-proposed ul-role-badge ' + role + '">' + role.replace("_", " ") + '</span>';
            html += '<span class="role-confidence">' + Math.round(conf * 100) + '%</span>';
            html += '</div>';
        });
        html += '</div>';
        container.innerHTML = html;
    }

    /* ===== Neighbor Click in Info Tab ===== */
    function attachNeighborClickHandlers() {
        var items = document.querySelectorAll(".neighbor-clickable");
        items.forEach(function (item) {
            item.addEventListener("click", function () {
                var wasActive = item.classList.contains("neighbor-active");
                document.querySelectorAll(".neighbor-clickable").forEach(function (el) { el.classList.remove("neighbor-active"); });
                document.querySelectorAll(".neighbor-detail-panel").forEach(function (el) { el.style.display = "none"; });

                if (!wasActive) {
                    item.classList.add("neighbor-active");
                    var detailEl = item.nextElementSibling;
                    if (detailEl && detailEl.classList.contains("neighbor-detail-panel")) {
                        detailEl.style.display = "block";
                    }
                    var peerId = item.dataset.peer;
                    if (peerId && cy) {
                        cy.elements().removeClass("highlighted");
                        var peerNode = cy.getElementById(peerId);
                        if (peerNode.length) {
                            peerNode.addClass("highlighted");
                            var selectedId = currentSelectedNode;
                            if (selectedId) {
                                var edges = cy.edges().filter(function (e) {
                                    return (e.data("source") === selectedId && e.data("target") === peerId) ||
                                           (e.data("source") === peerId && e.data("target") === selectedId);
                                });
                                edges.addClass("highlighted");
                            }
                        }
                    }
                } else {
                    if (cy) cy.elements().removeClass("highlighted");
                }
            });
        });
    }

    var currentSelectedNode = null;

    function resetAll() {
        selectedFiles = [];
        topologyData = null;
        currentPartition = null;
        currentView = "connected";
        positionCache = {};
        currentSelectedNode = null;
        if (cy) { cy.destroy(); cy = null; }
        $("view-select").value = "connected";
        $("view-select").disabled = false;
        $("topo-mode-select").value = "physical";
        currentTopoMode = "physical";
        $("layout-select").value = "breadthfirst";
        $("upload-panel").hidden = false;
        $("topology-panel").hidden = true;
        $("legend").hidden = true;
        $("file-list").hidden = true;
        $("processing-indicator").hidden = true;
        $("btn-process").disabled = false;
        $("btn-export").disabled = true;
        $("btn-export-drawio").disabled = true;
        $("selection-bar").hidden = true;
        $("files-ul").innerHTML = "";
        $("drop-zone").hidden = false;
        $("parse-log").hidden = true;
        $("parse-log").innerHTML = "";
        var prereqPanel = document.querySelector(".prereq-panel");
        if (prereqPanel) prereqPanel.hidden = false;
        var migPanel = $("migration-panel");
        if (migPanel) migPanel.hidden = true;
        closeDetail();
    }

    function formatSize(bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
        return (bytes / 1048576).toFixed(1) + " MB";
    }

    function escapeHtml(text) {
        var d = document.createElement("div");
        d.textContent = text;
        return d.innerHTML;
    }

    init();
})();
