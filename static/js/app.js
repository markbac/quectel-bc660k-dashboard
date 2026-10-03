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
    const firmwareVal = document.getElementById("firmwareVal");
    const tempVal = document.getElementById("tempVal");
    const tempItem = document.getElementById("tempItem");

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
    let lastIccid = null;
    const HISTORY_REFRESH_MS = 30000;
    let chartData = {
        labels: [],
        rsrp: [],
        rsrq: []
    };

    // Chart window: "live" plots the last 25 polls as they arrive; the other
    // windows plot a downsampled series fetched from the database on demand.
    const chartWindowSelect = document.getElementById("chartWindow");
    let chartWindow = "live";

    function chartLabel(unixSeconds, windowName) {
        const d = new Date(unixSeconds * 1000);
        const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        return windowName === "1h" || windowName === "24h" || windowName === "session"
            ? time
            : `${d.toLocaleDateString([], { day: "2-digit", month: "short" })} ${time}`;
    }

    async function loadChartSeries() {
        if (chartWindow === "live") return;
        const requested = chartWindow;
        try {
            const res = await fetch(`/api/history/series?window=${encodeURIComponent(requested)}`);
            if (!res.ok) return;
            const data = await res.json();
            if (requested !== chartWindow) return;  // user switched while loading
            const series = data.series || [];
            chartData.labels.length = 0;
            chartData.rsrp.length = 0;
            chartData.rsrq.length = 0;
            series.forEach(row => {
                chartData.labels.push(chartLabel(row.unix_time, requested));
                chartData.rsrp.push(row.rsrp === null ? null : Math.round(row.rsrp * 10) / 10);
                chartData.rsrq.push(row.rsrq === null ? null : Math.round(row.rsrq * 10) / 10);
            });
            if (chart) chart.update();
        } catch (err) {
            console.error("Error loading history series:", err);
        }
    }

    function setChartWindow(value) {
        chartWindow = value;
        chartData.labels.length = 0;
        chartData.rsrp.length = 0;
        chartData.rsrq.length = 0;
        if (chart) chart.update();
        loadChartSeries();
    }

    if (chartWindowSelect) {
        chartWindowSelect.addEventListener("change", () => setChartWindow(chartWindowSelect.value));
    }

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
                const placeholder = document.createElement("option");
                placeholder.value = "";
                placeholder.textContent = "Select a port...";
                portSelect.appendChild(placeholder);
                data.ports.forEach(p => {
                    const opt = document.createElement("option");
                    opt.value = p.device;
                    opt.textContent = `${p.device} (${p.description})`;
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
            if (data.awaiting_identity) {
                historyTableBody.innerHTML = `<tr><td colspan="10" class="empty-state">Awaiting SIM identity. History is shown per SIM once the ICCID is known.</td></tr>`;
            } else if (history.length === 0) {
                historyTableBody.innerHTML = `<tr><td colspan="10" class="empty-state">No historical telemetry records for this SIM yet.</td></tr>`;
            } else {
                const rev = [...history].reverse();
                historyTableBody.innerHTML = rev.slice(0, 50).map(row => `
                    <tr>
                        <td><small>${escapeHtml(row.timestamp)}</small></td>
                        <td><strong>${escapeHtml(row.rsrp)} dBm</strong></td>
                        <td>${escapeHtml(row.rsrq)} dB</td>
                        <td>${escapeHtml(row.rssi)} dBm</td>
                        <td>${escapeHtml(row.sinr)} dB</td>
                        <td><span class="badge ${qualityBadgeClass(row.quality_label)}">${escapeHtml(row.quality_label)}</span></td>
                        <td>${escapeHtml(row.operator || '-')}</td>
                        <td><code>${escapeHtml(row.cell_id)}</code></td>
                        <td>${row.temperature === null || row.temperature === undefined ? "--" : escapeHtml(row.temperature) + "°C"}</td>
                        <td>${escapeHtml(row.voltage)} mV</td>
                    </tr>
                `).join("");
            }
        } catch (err) {
            console.error("Error loading SQLite history:", err);
        }
    }

    clearDbBtn.addEventListener("click", async () => {
        if (confirm("Delete the stored telemetry history for the connected SIM?")) {
            await fetch("/api/history/clear", { method: "POST" });
            chartData.labels.length = 0;
            chartData.rsrp.length = 0;
            chartData.rsrq.length = 0;
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

    // PSM & eDRX Handlers
    const enablePsmBtn = document.getElementById("enablePsmBtn");
    const disablePsmBtn = document.getElementById("disablePsmBtn");
    const t3412Input = document.getElementById("t3412Input");
    const t3324Input = document.getElementById("t3324Input");
    const psmStatusBadge = document.getElementById("psmStatusBadge");

    async function sendPsmConfig(enabled) {
        if (enabled && !confirm("Once PSM is active the module can stop responding on the UART after the T3324 active timer expires. Press RESET on the board to wake it. Enable PSM?")) {
            return;
        }
        try {
            const res = await fetch("/api/psm", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    enabled: enabled,
                    t3412: t3412Input ? t3412Input.value.trim() : "10100101",
                    t3324: t3324Input ? t3324Input.value.trim() : "00100100"
                })
            });
            const data = await res.json();
            if (res.ok) {
                alert(`PSM ${enabled ? "Enabled" : "Disabled"} successfully!\nResponse: ${data.response}`);
            } else {
                alert(`PSM config failed: ${data.detail}`);
            }
        } catch (err) {
            alert(`Error configuring PSM: ${err.message}`);
        }
    }

    if (enablePsmBtn) enablePsmBtn.addEventListener("click", () => sendPsmConfig(true));
    if (disablePsmBtn) disablePsmBtn.addEventListener("click", () => sendPsmConfig(false));

    // Ping & DNS Handlers
    const pingHostInput = document.getElementById("pingHostInput");
    const runPingBtn = document.getElementById("runPingBtn");
    const runDnsBtn = document.getElementById("runDnsBtn");
    const pingRttVal = document.getElementById("pingRttVal");
    const pingLossVal = document.getElementById("pingLossVal");
    const dnsResultVal = document.getElementById("dnsResultVal");
    const pingStatusBadge = document.getElementById("pingStatusBadge");

    if (runPingBtn) {
        runPingBtn.addEventListener("click", async () => {
            const host = pingHostInput ? pingHostInput.value.trim() : "8.8.8.8";
            if (pingStatusBadge) {
                pingStatusBadge.textContent = "Pinging...";
                pingStatusBadge.className = "badge badge-warning";
            }
            try {
                const res = await fetch("/api/ping", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ host: host, count: 4 })
                });
                const data = await res.json();
                if (res.ok && data.result) {
                    const r = data.result;
                    const hasResult = r.loss_pct !== null && r.loss_pct !== undefined;
                    if (pingRttVal) pingRttVal.textContent = r.avg_rtt !== null && r.avg_rtt !== undefined ? `${r.avg_rtt} ms` : "--";
                    if (pingLossVal) pingLossVal.textContent = hasResult ? `${r.loss_pct}%` : "--";
                    if (pingStatusBadge) {
                        pingStatusBadge.textContent = r.status || "Completed";
                        pingStatusBadge.className = hasResult && r.loss_pct < 50 ? "badge badge-good" : "badge badge-danger";
                    }
                } else {
                    alert(`Ping failed: ${data.detail}`);
                    if (pingStatusBadge) {
                        pingStatusBadge.textContent = "Failed";
                        pingStatusBadge.className = "badge badge-danger";
                    }
                }
            } catch (err) {
                alert(`Error running ping: ${err.message}`);
                if (pingStatusBadge) {
                    pingStatusBadge.textContent = "Error";
                    pingStatusBadge.className = "badge badge-danger";
                }
            }
        });
    }

    if (runDnsBtn) {
        runDnsBtn.addEventListener("click", async () => {
            const domain = pingHostInput ? pingHostInput.value.trim() : "leshan.eclipseprojects.io";
            if (dnsResultVal) dnsResultVal.textContent = "Resolving...";
            try {
                const res = await fetch("/api/dns", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ domain: domain })
                });
                const data = await res.json();
                if (res.ok && data.result) {
                    if (dnsResultVal) dnsResultVal.textContent = data.result.resolved_ip || "Unknown";
                } else {
                    if (dnsResultVal) dnsResultVal.textContent = "Resolve Error";
                }
            } catch (err) {
                if (dnsResultVal) dnsResultVal.textContent = "Error";
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

    // Probe every port for an AT modem and select the one that answers
    const detectPortBtn = document.getElementById("detectPortBtn");
    detectPortBtn.addEventListener("click", async () => {
        detectPortBtn.disabled = true;
        try {
            const res = await fetch("/api/detect", { method: "POST" });
            const data = await res.json();
            if (!res.ok) {
                alert(data.detail || "No modem found");
            } else {
                await loadPorts();
                portSelect.value = data.port;
                baudSelect.value = String(data.baudrate);
            }
        } catch (err) {
            alert(`Detection failed: ${err.message}`);
        } finally {
            detectPortBtn.disabled = false;
        }
    });

    // Update Dashboard UI with state object
    function updateUIState(state) {
        const isDemo = state.mode === "DEMO";
        const isCommunicated = isDemo || !!state.hardware_communicated;

        if (state.connected) {
            if (isDemo) {
                connectionStatus.className = "status-badge demo";
                statusText.textContent = "Demo Mode (--demo)";
            } else if (state.modem_state === "psm" || state.modem_state === "deep_sleep") {
                connectionStatus.className = "status-badge connecting";
                const kind = state.modem_state === "psm" ? "PSM" : "deep sleep";
                statusText.textContent = `Modem asleep, ${kind} (${state.port}) - press RESET to wake it`;
            } else if (isCommunicated && state.modem_responding === false) {
                connectionStatus.className = "status-badge connecting";
                statusText.textContent = `No response (${state.port}) - press RESET on the board`;
            } else if (isCommunicated) {
                connectionStatus.className = "status-badge connected";
                statusText.textContent = `Connected (${state.port})`;
            } else {
                connectionStatus.className = "status-badge connecting";
                statusText.textContent = `Connecting (${state.port}) - press RESET on the board if just powered`;
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
        currentApnVal.textContent = isCommunicated ? (apnInfo.apn || "Default / Blank") : "--";
        pdpTypeVal.textContent = isCommunicated ? `${apnInfo.pdp_type || 'IP'} (CID: ${apnInfo.pdp_cid || 1})` : "--";
        if (isCommunicated && apnInfo.attached) {
            apnAttachBadge.className = "badge badge-good";
            apnAttachBadge.textContent = "Attached";
        } else if (isCommunicated) {
            apnAttachBadge.className = "badge badge-fair";
            apnAttachBadge.textContent = "Detached";
        } else {
            apnAttachBadge.className = "badge badge-secondary";
            apnAttachBadge.textContent = "Awaiting Data";
        }

        // Signal Metrics
        const sig = state.signal || {};
        const hasSignalData = isCommunicated && sig.rsrp !== null && sig.rsrp !== undefined;

        rsrpVal.textContent = hasSignalData ? sig.rsrp : "--";
        rsrqVal.textContent = hasSignalData ? sig.rsrq : "--";
        rssiVal.textContent = hasSignalData ? sig.rssi : "--";
        csqVal.textContent = hasSignalData && sig.csq !== null ? `(CSQ: ${sig.csq}/31)` : "(CSQ: --)";
        sinrVal.textContent = hasSignalData && sig.sinr !== null ? sig.sinr : "--";

        let rsrpPct = hasSignalData ? Math.max(0, Math.min(100, ((sig.rsrp + 140) / 90) * 100)) : 0;
        rsrpBar.style.width = `${rsrpPct}%`;

        if (hasSignalData && sig.quality_label) {
            rsrpQuality.textContent = sig.quality_label;
            rsrpQuality.className = `badge ${qualityBadgeClass(sig.quality_label)}`;
        } else {
            rsrpQuality.textContent = isCommunicated ? "No Signal" : "Awaiting Modem Communication...";
            rsrpQuality.className = "badge badge-secondary";
        }

        let rsrqPct = hasSignalData ? Math.max(0, Math.min(100, ((sig.rsrq + 20) / 20) * 100)) : 0;
        rsrqBar.style.width = `${rsrqPct}%`;

        let rssiPct = hasSignalData ? Math.max(0, Math.min(100, ((sig.rssi + 113) / 62) * 100)) : 0;
        rssiBar.style.width = `${rssiPct}%`;

        let sinrPct = hasSignalData && sig.sinr !== null ? Math.max(0, Math.min(100, ((sig.sinr + 10) / 40) * 100)) : 0;
        sinrBar.style.width = `${sinrPct}%`;

        // SIM Card Info
        const sim = state.sim_info || {};
        iccidVal.textContent = isCommunicated ? (sim.iccid || "N/A") : "--";
        imsiVal.textContent = isCommunicated ? (sim.imsi || "N/A") : "--";
        simStateVal.textContent = isCommunicated ? (sim.sim_status || "UNKNOWN") : "AWAITING DATA";
        simStatusBadge.textContent = isCommunicated ? (sim.sim_status || "UNKNOWN") : "AWAITING DATA";

        // System Diagnostics
        const sys = state.system_info || {};
        imeiVal.textContent = isCommunicated ? (sys.imei || "N/A") : "--";
        ipVal.textContent = isCommunicated ? (sys.ip_address || "Not Connected") : "--";
        voltageVal.textContent = isCommunicated && sys.voltage ? `${sys.voltage} mV (${(sys.voltage / 1000).toFixed(2)} V)` : "--";
        firmwareVal.textContent = isCommunicated ? (sys.firmware || "N/A") : "--";
        // Temperature is only shown when the module reports it.
        const hasTemp = isCommunicated && typeof sys.temperature === "number";
        tempItem.classList.toggle("hidden", !hasTemp);
        tempVal.textContent = hasTemp ? `${sys.temperature} \u00b0C` : "--";

        // Power saving state, as reported by the module
        const psm = state.psm_info || {};
        if (psmStatusBadge) {
            psmStatusBadge.textContent = isCommunicated ? (psm.status || "PSM Disabled") : "Awaiting Modem";
            psmStatusBadge.className = isCommunicated && psm.enabled ? "badge badge-good" : "badge badge-warning";
        }

        const psmRequestedVal = document.getElementById("psmRequestedVal");
        const psmGrantedVal = document.getElementById("psmGrantedVal");
        const edrxGrantedVal = document.getElementById("edrxGrantedVal");
        const edrx = state.edrx_info || {};
        psmRequestedVal.textContent = isCommunicated ? (psm.requested_text || "--") : "--";
        psmGrantedVal.textContent = isCommunicated
            ? `${psm.granted_text || "--"}${psm.mismatch ? " (differs from request)" : ""}` : "--";
        psmGrantedVal.style.color = psm.mismatch ? "#f59e0b" : "";
        edrxGrantedVal.textContent = isCommunicated && edrx.enabled
            ? `${edrx.requested_text || "--"} / ${edrx.granted_text || "--"}${edrx.mismatch ? " (differs)" : ""}` : "--";

        // Serving Cell Details
        const sc = state.serving_cell || {};
        ratBadge.textContent = isCommunicated ? (sc.rat || "NB-IoT") : "--";
        operatorVal.textContent = isCommunicated ? (sc.operator || "Searching...") : "Awaiting Modem Communication...";
        plmnVal.textContent = isCommunicated && sc.mcc && sc.mcc !== "--" ? `${sc.mcc}-${sc.mnc}` : "--";

        cellIdVal.childNodes[0].nodeValue = isCommunicated ? `${sc.cell_id || '--'} ` : "-- ";
        cellIdDec.textContent = isCommunicated && sc.cell_id_dec && sc.cell_id_dec !== "--" ? `(${sc.cell_id_dec})` : "";

        tacVal.childNodes[0].nodeValue = isCommunicated ? `${sc.tac || '--'} ` : "-- ";
        tacDec.textContent = isCommunicated && sc.tac_dec && sc.tac_dec !== "--" ? `(${sc.tac_dec})` : "";

        pciVal.textContent = isCommunicated ? (sc.pci || "--") : "--";
        bandVal.textContent = isCommunicated && sc.earfcn && sc.earfcn !== "--" ? `EARFCN ${sc.earfcn} (Band ${sc.band})` : "--";

        // Neighbour Cells Table
        const neighbours = state.neighbour_cells || [];
        neighbourCount.textContent = isCommunicated ? `${neighbours.length} Detected` : "0 Detected";
        if (!isCommunicated || neighbours.length === 0) {
            neighbourTableBody.innerHTML = `<tr><td colspan="5" class="empty-state">${isCommunicated ? 'No neighbor cells detected yet' : 'Awaiting modem communication...'}</td></tr>`;
        } else {
            neighbourTableBody.innerHTML = neighbours.map(n => {
                const hasRsrp = typeof n.rsrp === "number" && typeof sig.rsrp === "number";
                const delta = hasRsrp ? n.rsrp - sig.rsrp : null;
                const relLabel = delta === null ? "--" : (delta >= 0 ? `+${delta} dB` : `${delta} dB`);
                const relClass = delta !== null && delta >= -6 ? "style='color:#10b981;font-weight:600;'" : "style='color:#8c9cb8;'";
                const rsrpText = typeof n.rsrp === "number" ? `${n.rsrp} dBm` : "--";
                const rsrqText = typeof n.rsrq === "number" ? `${n.rsrq} dB` : "--";
                return `
                    <tr>
                        <td><strong>${escapeHtml(n.pci)}</strong></td>
                        <td>${escapeHtml(n.earfcn)}</td>
                        <td>${rsrpText}</td>
                        <td>${rsrqText}</td>
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

        if (isCommunicated && state.networks_scan && state.networks_scan.length > 0) {
            networksTableBody.innerHTML = state.networks_scan.map(net => {
                let badgeClass = "badge-fair";
                if (net.status === "Current") badgeClass = "badge-excellent";
                else if (net.status === "Available") badgeClass = "badge-good";
                else if (net.status === "Forbidden") badgeClass = "badge-poor";

                return `
                    <tr>
                        <td><span class="badge ${badgeClass}">${escapeHtml(net.status)}</span></td>
                        <td><strong>${escapeHtml(net.long_name)}</strong> (${escapeHtml(net.short_name)})</td>
                        <td>${escapeHtml(net.plmn)}</td>
                        <td>${escapeHtml(net.act)}</td>
                    </tr>
                `;
            }).join("");
        } else if (!isCommunicated) {
            networksTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">Awaiting modem communication...</td></tr>`;
        }

        // Push data to Live Trend Chart only if signal data present
        if (hasSignalData && chartWindow === "live") {
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
        }

        // History follows the SIM: when the ICCID changes, drop the live
        // chart and reload the table for the new SIM.
        const iccidNow = (state.sim_info && state.sim_info.iccid) || "--";
        const iccidChanged = iccidNow !== lastIccid;
        if (iccidChanged) {
            lastIccid = iccidNow;
            chartData.labels.length = 0;
            chartData.rsrp.length = 0;
            chartData.rsrq.length = 0;
            if (chart) chart.update();
        }

        if (iccidChanged) {
            loadHistory();
            loadChartSeries();
        }
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
        div.className = `log-line log-${String(entry.direction).toLowerCase().replace(/[^a-z]/g, "")}`;
        div.innerHTML = `<span class="timestamp">[${escapeHtml(entry.timestamp)}]</span><span class="dir">[${escapeHtml(entry.direction)}]</span> ${escapeHtml(entry.text)}`;
        logConsole.appendChild(div);
        logConsole.scrollTop = logConsole.scrollHeight;
    }

    // Escape a value for use in HTML text or a quoted attribute.
    function escapeHtml(value) {
        return String(value === null || value === undefined ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    // Map a quality label to a fixed CSS class, never to arbitrary text.
    function qualityBadgeClass(label) {
        const classes = { excellent: "badge-excellent", good: "badge-good", fair: "badge-fair", poor: "badge-poor" };
        return classes[String(label || "").toLowerCase()] || "badge-secondary";
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
    // History changes slowly: refresh on a timer and when the SIM changes,
    // not on every state push.
    setInterval(loadHistory, HISTORY_REFRESH_MS);
    setInterval(loadChartSeries, HISTORY_REFRESH_MS);
    connectWebSocket();
});
