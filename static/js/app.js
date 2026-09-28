document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const portSelect = document.getElementById("portSelect");
    const baudSelect = document.getElementById("baudSelect");
    const refreshPortsBtn = document.getElementById("refreshPortsBtn");
    const connectBtn = document.getElementById("connectBtn");
    const connectionStatus = document.getElementById("connectionStatus");
    const statusText = document.getElementById("statusText");
    const connectivityStatusVal = document.getElementById("connectivityStatusVal");

    const telemetryIntervalSelect = document.getElementById("telemetryIntervalSelect");
    const copsIntervalSelect = document.getElementById("copsIntervalSelect");

    // APN Elements
    const apnInput = document.getElementById("apnInput");
    const saveApnBtn = document.getElementById("saveApnBtn");
    const currentApnVal = document.getElementById("currentApnVal");
    const pdpTypeVal = document.getElementById("pdpTypeVal");
    const apnAttachBadge = document.getElementById("apnAttachBadge");

    // Metrics
    const rsrpVal = document.getElementById("rsrpVal");
    const rsrpBar = document.getElementById("rsrpBar");
    const rsrpQuality = document.getElementById("rsrpQuality");

    const rsrqVal = document.getElementById("rsrqVal");
    const rsrqBar = document.getElementById("rsrqBar");

    const rssiVal = document.getElementById("rssiVal");
    const csqVal = document.getElementById("csqVal");
    const rssiBar = document.getElementById("rssiBar");

    const sinrVal = document.getElementById("sinrVal");
    const sinrBar = document.getElementById("sinrBar");

    // SIM & Hardware Elements
    const iccidVal = document.getElementById("iccidVal");
    const imsiVal = document.getElementById("imsiVal");
    const simStateVal = document.getElementById("simStateVal");
    const simStatusBadge = document.getElementById("simStatusBadge");
    const ipVal = document.getElementById("ipVal");

    const imeiVal = document.getElementById("imeiVal");
    const voltageVal = document.getElementById("voltageVal");
    const tempVal = document.getElementById("tempVal");
    const mapLink = document.getElementById("mapLink");

    // Serving Cell
    const ratBadge = document.getElementById("ratBadge");
    const operatorVal = document.getElementById("operatorVal");
    const plmnVal = document.getElementById("plmnVal");
    const cellIdVal = document.getElementById("cellIdVal");
    const cellIdDec = document.getElementById("cellIdDec");
    const tacVal = document.getElementById("tacVal");
    const tacDec = document.getElementById("tacDec");
    const pciVal = document.getElementById("pciVal");
    const bandVal = document.getElementById("bandVal");

    // SQLite History Elements
    const dbTotalRecords = document.getElementById("dbTotalRecords");
    const statMinRsrp = document.getElementById("statMinRsrp");
    const statMaxRsrp = document.getElementById("statMaxRsrp");
    const statAvgRsrp = document.getElementById("statAvgRsrp");
    const statAvgRsrq = document.getElementById("statAvgRsrq");
    const statUniqueCells = document.getElementById("statUniqueCells");
    const historyTableBody = document.getElementById("historyTableBody");
    const clearDbBtn = document.getElementById("clearDbBtn");

    // Tables
    const neighbourTableBody = document.getElementById("neighbourTableBody");
    const neighbourCount = document.getElementById("neighbourCount");
    const scanBtn = document.getElementById("scanBtn");
    const scanLoading = document.getElementById("scanLoading");
    const networksTableBody = document.getElementById("networksTableBody");

    // Terminal & Disk Log Toggle
    const logConsole = document.getElementById("logConsole");
    const atInput = document.getElementById("atInput");
    const sendAtBtn = document.getElementById("sendAtBtn");
    const clearLogBtn = document.getElementById("clearLogBtn");
    const toggleFileLogBtn = document.getElementById("toggleFileLogBtn");
    let fileLoggingEnabled = true;

    let socket = null;
    let chart = null;
    let chartData = {
        labels: [],
        rsrp: [],
        rsrq: []
    };

    // Initialize Signal Trend Chart
    function initChart() {
        const ctx = document.getElementById("signalChart").getContext("2d");
        chart = new Chart(ctx, {
            type: "line",
            data: {
                labels: chartData.labels,
                datasets: [
                    {
                        label: "RSRP (dBm)",
                        data: chartData.rsrp,
                        borderColor: "#3b82f6",
                        backgroundColor: "rgba(59, 130, 246, 0.1)",
                        borderWidth: 2,
                        tension: 0.3,
                        fill: true,
                        yAxisID: "y"
                    },
                    {
                        label: "RSRQ (dB)",
                        data: chartData.rsrq,
                        borderColor: "#06b6d4",
                        backgroundColor: "transparent",
                        borderWidth: 2,
                        borderDash: [4, 4],
                        tension: 0.3,
                        yAxisID: "y1"
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                scales: {
                    x: {
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: { color: "#8c9cb8", font: { size: 10 } }
                    },
                    y: {
                        type: "linear",
                        display: true,
                        position: "left",
                        title: { display: true, text: "RSRP (dBm)", color: "#3b82f6" },
                        min: -140,
                        max: -50,
                        grid: { color: "rgba(255, 255, 255, 0.08)" },
                        ticks: { color: "#8c9cb8" }
                    },
                    y1: {
                        type: "linear",
                        display: true,
                        position: "right",
                        title: { display: true, text: "RSRQ (dB)", color: "#06b6d4" },
                        min: -25,
                        max: 0,
                        grid: { drawOnChartArea: false },
                        ticks: { color: "#8c9cb8" }
                    }
                },
                plugins: {
                    legend: { labels: { color: "#f0f4fc" } }
                }
            }
        });
    }

    // Connect WebSocket
    function connectWebSocket() {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        socket = new WebSocket(wsUrl);

        socket.onopen = () => {
            console.log("WebSocket Connected");
        };

        socket.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === "state") {
                updateUIState(msg.data);
            } else if (msg.type === "log") {
                appendLog(msg.data);
            }
        };

        socket.onclose = () => {
            console.log("WebSocket Disconnected. Reconnecting in 3s...");
            setTimeout(connectWebSocket, 3000);
        };
    }

    // Fetch System Serial Ports
    async function loadPorts() {
        try {
            const res = await fetch("/api/ports");
            const data = await res.json();
            portSelect.innerHTML = "";

            if (data.ports.length === 0) {
                portSelect.innerHTML = `<option value="">No Ports Detected</option>`;
            } else {
                data.ports.forEach(p => {
                    const opt = document.createElement("option");
                    opt.value = p.device;
                    opt.textContent = `${p.device} (${p.description})`;
                    if (p.device === "COM3") opt.selected = true;
                    portSelect.appendChild(opt);
                });
            }
        } catch (err) {
            console.error("Failed to load ports:", err);
        }
    }

    // Fetch SQLite History & Stats
    async function loadHistory() {
        try {
            const res = await fetch("/api/history?limit=100");
            const data = await res.json();
            
            const stats = data.stats;
            dbTotalRecords.textContent = `${stats.total_records} Records`;
            statMinRsrp.textContent = stats.total_records > 0 ? `${stats.min_rsrp} dBm` : "- dBm";
            statMaxRsrp.textContent = stats.total_records > 0 ? `${stats.max_rsrp} dBm` : "- dBm";
            statAvgRsrp.textContent = stats.total_records > 0 ? `${stats.avg_rsrp} dBm` : "- dBm";
            statAvgRsrq.textContent = stats.total_records > 0 ? `${stats.avg_rsrq} dB` : "- dB";
            statUniqueCells.textContent = stats.total_cells || 0;

            const history = data.history || [];
            if (history.length === 0) {
                historyTableBody.innerHTML = `<tr><td colspan="10" class="empty-state">No historical telemetry records in SQLite database yet.</td></tr>`;
            } else {
                const rev = [...history].reverse();
                historyTableBody.innerHTML = rev.slice(0, 50).map(row => `
                    <tr>
                        <td><small>${row.timestamp}</small></td>
                        <td><strong>${row.rsrp} dBm</strong></td>
                        <td>${row.rsrq} dB</td>
                        <td>${row.rssi} dBm</td>
                        <td>${row.sinr} dB</td>
                        <td><span class="badge badge-${(row.quality_label||'good').toLowerCase()}">${row.quality_label}</span></td>
                        <td>${row.operator || '-'}</td>
                        <td><code>${row.cell_id}</code></td>
                        <td>${row.temperature}°C</td>
                        <td>${row.voltage} mV</td>
                    </tr>
                `).join("");
            }
        } catch (err) {
            console.error("Error loading SQLite history:", err);
        }
    }

    clearDbBtn.addEventListener("click", async () => {
        if (confirm("Clear SQLite database and start fresh with a clean telemetry history?")) {
            await fetch("/api/history/clear", { method: "POST" });
            chartData.labels = [];
            chartData.rsrp = [];
            chartData.rsrq = [];
            if (chart) chart.update();
            loadHistory();
        }
    });

    // Save & Attach APN
    if (saveApnBtn) {
        saveApnBtn.addEventListener("click", async () => {
            const apn = apnInput.value.trim();
            if (!apn) {
                alert("Please enter a valid APN name.");
                return;
            }

            try {
                const res = await fetch("/api/apn", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ apn, pdp_type: "IP", cid: 1 })
                });
                const data = await res.json();
                if (res.ok) {
                    alert(`APN '${apn}' configured successfully!\nResponse:\n${data.response}`);
                } else {
                    alert(`Failed to set APN: ${data.detail}`);
                }
            } catch (err) {
                alert(`Error setting APN: ${err.message}`);
            }
        });
    }

    // Interval Settings Handlers
    async function updateIntervalSettings() {
        const telemetry_interval = parseInt(telemetryIntervalSelect.value);
        const cops_scan_interval = parseInt(copsIntervalSelect.value);

        try {
            await fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ telemetry_interval, cops_scan_interval })
            });
        } catch (err) {
            console.error("Error updating intervals:", err);
        }
    }

    telemetryIntervalSelect.addEventListener("change", updateIntervalSettings);
    copsIntervalSelect.addEventListener("change", updateIntervalSettings);

    // Toggle Py-LogKit Disk Logging
    if (toggleFileLogBtn) {
        toggleFileLogBtn.addEventListener("click", async () => {
            const targetState = !fileLoggingEnabled;
            try {
                const res = await fetch("/api/file_logging", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ enabled: targetState })
                });
                const data = await res.json();
                fileLoggingEnabled = data.file_logging_enabled;
                updateFileLogButtonUI(fileLoggingEnabled);
            } catch (err) {
                console.error("Error toggling file logging:", err);
            }
        });
    }

    function updateFileLogButtonUI(enabled) {
        if (enabled) {
            toggleFileLogBtn.className = "btn btn-sm btn-secondary";
            toggleFileLogBtn.innerHTML = `<i class="fa-solid fa-file-lines"></i> Py-LogKit: ON`;
        } else {
            toggleFileLogBtn.className = "btn btn-sm btn-outline";
            toggleFileLogBtn.innerHTML = `<i class="fa-solid fa-file-excel"></i> Py-LogKit: OFF`;
        }
    }

    // Connect to Selected Port
    connectBtn.addEventListener("click", async () => {
        if (connectBtn.dataset.state === "connected") {
            await fetch("/api/disconnect", { method: "POST" });
            return;
        }

        const port = portSelect.value;
        const baudrate = parseInt(baudSelect.value);

        if (!port) {
            alert("Please select a serial port.");
            return;
        }

        try {
            const res = await fetch("/api/connect", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ port, baudrate })
            });
            const data = await res.json();
            if (!res.ok) {
                alert(`Connection failed: ${data.detail}`);
            }
        } catch (err) {
            alert(`Error connecting: ${err.message}`);
        }
    });

    // Web Exit Trigger
    const exitBtn = document.getElementById("exitBtn");
    if (exitBtn) {
        exitBtn.addEventListener("click", async () => {
            if (confirm("Are you sure you want to stop the dashboard server and close serial connections?")) {
                try {
                    await fetch("/api/shutdown", { method: "POST" });
                    document.body.innerHTML = `
                        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;background:#0b0f19;color:#ef4444;font-family:'Inter',sans-serif;text-align:center;padding:2rem;">
                            <i class="fa-solid fa-power-off" style="font-size:4rem;margin-bottom:1.5rem;color:#ef4444;"></i>
                            <h1 style="font-size:2rem;margin-bottom:0.5rem;color:#fff;">Dashboard Server Stopped</h1>
                            <p style="color:#8c9cb8;font-size:1rem;max-width:500px;">The Python dashboard server and serial port connections have been safely shut down.</p>
                            <p style="color:#5c6b89;font-size:0.85rem;margin-top:1.5rem;">You can close this browser window.</p>
                        </div>
                    `;
                } catch (err) {
                    console.error("Shutdown error:", err);
                }
            }
        });
    }

    refreshPortsBtn.addEventListener("click", loadPorts);

    // Update Dashboard UI with state object
    function updateUIState(state) {
        if (state.connected) {
            if (state.mode === "DEMO") {
                connectionStatus.className = "status-badge demo";
                statusText.textContent = "Demo Mode (--demo)";
            } else {
                connectionStatus.className = "status-badge connected";
                statusText.textContent = `Connected (${state.port})`;
            }
            connectBtn.innerHTML = `<i class="fa-solid fa-unlink"></i> Disconnect`;
            connectBtn.dataset.state = "connected";
            connectBtn.className = "btn btn-outline";
        } else {
            connectionStatus.className = "status-badge disconnected";
            statusText.textContent = "Disconnected";
            connectBtn.innerHTML = `<i class="fa-solid fa-link"></i> Connect`;
            connectBtn.dataset.state = "disconnected";
            connectBtn.className = "btn btn-primary";
        }

        connectivityStatusVal.textContent = state.connectivity_status || "Disconnected";

        if (typeof state.file_logging_enabled === "boolean") {
            fileLoggingEnabled = state.file_logging_enabled;
            updateFileLogButtonUI(fileLoggingEnabled);
        }

        if (state.telemetry_interval) telemetryIntervalSelect.value = state.telemetry_interval;
        if (typeof state.cops_scan_interval === "number") copsIntervalSelect.value = state.cops_scan_interval;

        // APN Info Update
        const apnInfo = state.apn_info || {};
        currentApnVal.textContent = apnInfo.apn || "Default / Blank";
        pdpTypeVal.textContent = `${apnInfo.pdp_type || 'IP'} (CID: ${apnInfo.pdp_cid || 1})`;
        if (apnInfo.attached) {
            apnAttachBadge.className = "badge badge-good";
            apnAttachBadge.textContent = "Attached";
        } else {
            apnAttachBadge.className = "badge badge-fair";
            apnAttachBadge.textContent = "Detached";
        }

        // Signal Metrics
        const sig = state.signal;
        rsrpVal.textContent = sig.rsrp;
        rsrqVal.textContent = sig.rsrq;
        rssiVal.textContent = sig.rssi;
        csqVal.textContent = `(CSQ: ${sig.csq}/31)`;
        sinrVal.textContent = sig.sinr;

        let rsrpPct = Math.max(0, Math.min(100, ((sig.rsrp + 140) / 90) * 100));
        rsrpBar.style.width = `${rsrpPct}%`;

        rsrpQuality.textContent = sig.quality_label;
        rsrpQuality.className = `badge badge-${sig.quality_label.toLowerCase()}`;

        let rsrqPct = Math.max(0, Math.min(100, ((sig.rsrq + 20) / 20) * 100));
        rsrqBar.style.width = `${rsrqPct}%`;

        let rssiPct = Math.max(0, Math.min(100, ((sig.rssi + 113) / 62) * 100));
        rssiBar.style.width = `${rssiPct}%`;

        let sinrPct = Math.max(0, Math.min(100, ((sig.sinr + 10) / 40) * 100));
        sinrBar.style.width = `${sinrPct}%`;

        // SIM Card Info
        const sim = state.sim_info || {};
        iccidVal.textContent = sim.iccid || "N/A";
        imsiVal.textContent = sim.imsi || "N/A";
        simStateVal.textContent = sim.sim_status || "UNKNOWN";
        simStatusBadge.textContent = sim.sim_status || "UNKNOWN";

        // System Diagnostics
        const sys = state.system_info || {};
        imeiVal.textContent = sys.imei || "N/A";
        ipVal.textContent = sys.ip_address || "Not Connected";
        voltageVal.innerHTML = `${sys.voltage || 0} mV <small>(${((sys.voltage || 0)/1000).toFixed(2)} V)</small>`;
        tempVal.textContent = sys.firmware || "BC660KGLAAR01A05";

        const loc = state.location || { lat: 51.5074, lon: -0.1278 };
        mapLink.href = `https://www.openstreetmap.org/#map=13/${loc.lat}/${loc.lon}`;
        mapLink.innerHTML = `<i class="fa-solid fa-map-pin"></i> ${loc.lat}, ${loc.lon}`;

        // Serving Cell Details
        const sc = state.serving_cell;
        ratBadge.textContent = sc.rat || "NB-IoT";
        operatorVal.textContent = sc.operator || "Searching...";
        plmnVal.textContent = `${sc.mcc}-${sc.mnc}`;
        cellIdVal.childNodes[0].nodeValue = `${sc.cell_id} `;
        cellIdDec.textContent = `(${sc.cell_id_dec})`;
        tacVal.childNodes[0].nodeValue = `${sc.tac} `;
        tacDec.textContent = `(${sc.tac_dec})`;
        pciVal.textContent = sc.pci;
        bandVal.textContent = `EARFCN ${sc.earfcn} (Band ${sc.band})`;

        // Neighbour Cells Table
        const neighbours = state.neighbour_cells || [];
        neighbourCount.textContent = `${neighbours.length} Detected`;
        if (neighbours.length === 0) {
            neighbourTableBody.innerHTML = `<tr><td colspan="5" class="empty-state">No neighbor cells detected yet</td></tr>`;
        } else {
            neighbourTableBody.innerHTML = neighbours.map(n => {
                const delta = n.rsrp - sig.rsrp;
                const relLabel = delta >= 0 ? `+${delta} dB` : `${delta} dB`;
                const relClass = delta >= -6 ? "style='color:#10b981;font-weight:600;'" : "style='color:#8c9cb8;'";
                return `
                    <tr>
                        <td><strong>${n.pci}</strong></td>
                        <td>${n.earfcn}</td>
                        <td>${n.rsrp} dBm</td>
                        <td>${n.rsrq} dB</td>
                        <td ${relClass}>${relLabel}</td>
                    </tr>
                `;
            }).join("");
        }

        // Spectrum Scanner State
        if (state.is_scanning) {
            scanLoading.classList.remove("hidden");
            scanBtn.disabled = true;
        } else {
            scanLoading.classList.add("hidden");
            scanBtn.disabled = false;
        }

        if (state.networks_scan && state.networks_scan.length > 0) {
            networksTableBody.innerHTML = state.networks_scan.map(net => {
                let badgeClass = "badge-fair";
                if (net.status === "Current") badgeClass = "badge-excellent";
                else if (net.status === "Available") badgeClass = "badge-good";
                else if (net.status === "Forbidden") badgeClass = "badge-poor";

                return `
                    <tr>
                        <td><span class="badge ${badgeClass}">${net.status}</span></td>
                        <td><strong>${net.long_name}</strong> (${net.short_name})</td>
                        <td>${net.plmn}</td>
                        <td>${net.act}</td>
                    </tr>
                `;
            }).join("");
        }

        // Push data to Live Trend Chart
        const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        if (chartData.labels.length >= 25) {
            chartData.labels.shift();
            chartData.rsrp.shift();
            chartData.rsrq.shift();
        }
        chartData.labels.push(timeStr);
        chartData.rsrp.push(sig.rsrp);
        chartData.rsrq.push(sig.rsrq);

        if (chart) {
            chart.update();
        }

        loadHistory();
    }

    // Network Scan Trigger
    scanBtn.addEventListener("click", async () => {
        try {
            await fetch("/api/scan", { method: "POST" });
        } catch (err) {
            console.error("Scan error:", err);
        }
    });

    // Console Logging
    function appendLog(entry) {
        const div = document.createElement("div");
        div.className = `log-line log-${entry.direction.toLowerCase()}`;
        div.innerHTML = `<span class="timestamp">[${entry.timestamp}]</span><span class="dir">[${entry.direction}]</span> ${escapeHtml(entry.text)}`;
        logConsole.appendChild(div);
        logConsole.scrollTop = logConsole.scrollHeight;
    }

    function escapeHtml(text) {
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    // Quick Command Buttons & Custom Input
    document.querySelectorAll(".cmd-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const cmd = btn.dataset.cmd;
            sendATCommand(cmd);
        });
    });

    sendAtBtn.addEventListener("click", () => {
        const cmd = atInput.value.trim();
        if (cmd) {
            sendATCommand(cmd);
            atInput.value = "";
        }
    });

    atInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            const cmd = atInput.value.trim();
            if (cmd) {
                sendATCommand(cmd);
                atInput.value = "";
            }
        }
    });

    clearLogBtn.addEventListener("click", () => {
        logConsole.innerHTML = "";
    });

    async function sendATCommand(command) {
        try {
            await fetch("/api/send_at", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ command })
            });
        } catch (err) {
            console.error("Error sending AT command:", err);
        }
    }

    // Initialize
    initChart();
    loadPorts();
    loadHistory();
    connectWebSocket();
});
