"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { loadDashboard } = require("./harness");

const fullState = {
    connected: true,
    mode: "REAL",
    port: "COM3",
    hardware_communicated: true,
    connectivity_status: "Network: Registered, home network",
    signal: { rsrp: -95, rsrq: -11, rssi: -85, sinr: 12, csq: 14, quality_label: "Good" },
    apn_info: { apn: "iot.example", pdp_type: "IP", pdp_cid: 1, attached: true },
    sim_info: { iccid: "8900000000000000000", imsi: "001010000000000", sim_status: "READY" },
    system_info: {
        imei: "860000000000000",
        ip_address: "10.0.0.1",
        voltage: 3600,
        temperature: 31,
        firmware: "BC660KGLAAR01A05",
    },
    location: { lat: null, lon: null },
    serving_cell: {
        rat: "NB-IoT", operator: "Example Net", mcc: "001", mnc: "01", cell_id: "1A",
        cell_id_dec: 26, tac: "5F", tac_dec: 95, pci: 320, earfcn: 6300, band: "8",
    },
    neighbour_cells: [{ pci: 321, earfcn: 6300, rsrp: -100, rsrq: -12 }],
    networks_scan: [],
    is_scanning: false,
};

test("a full state renders without throwing and reaches the later sections", () => {
    const h = loadDashboard();
    assert.doesNotThrow(() => h.push(fullState));
    assert.strictEqual(h.text("rsrpVal"), "-95");
    assert.strictEqual(h.text("imeiVal"), "860000000000000");
    assert.strictEqual(h.text("firmwareVal"), "BC660KGLAAR01A05");
    assert.strictEqual(h.text("tempVal"), "31 °C");
    assert.match(h.text("voltageVal"), /3600 mV/);
    // These sit after the old failure point in updateUIState().
    assert.strictEqual(h.text("operatorVal"), "Example Net");
    assert.strictEqual(h.text("pciVal"), "320");
});

test("a minimal state does not throw", () => {
    const h = loadDashboard();
    assert.doesNotThrow(() => h.push({ connected: false }));
});

test("every element id the script looks up exists in the page", () => {
    const fs = require("node:fs");
    const path = require("node:path");
    const js = fs.readFileSync(path.join(__dirname, "..", "..", "static", "js", "app.js"), "utf8");
    const { document } = loadDashboard();
    const ids = [...js.matchAll(/getElementById\("([^"]+)"\)/g)].map((m) => m[1]);
    const missing = ids.filter((id) => !document.getElementById(id));
    assert.deepStrictEqual(missing, []);
});

test("temperature tile is hidden unless the module reports a value", () => {
    const h = loadDashboard();
    h.push({ ...fullState, system_info: { ...fullState.system_info, temperature: null } });
    assert.ok(h.document.getElementById("tempItem").classList.contains("hidden"));
    h.push(fullState);
    assert.ok(!h.document.getElementById("tempItem").classList.contains("hidden"));
});

test("neighbours without RSRP render placeholders instead of NaN", () => {
    const h = loadDashboard();
    h.push({ ...fullState, neighbour_cells: [{ pci: 7, earfcn: 6300, rsrp: null, rsrq: null }] });
    const row = h.document.getElementById("neighbourTableBody").textContent;
    assert.doesNotMatch(row, /NaN|null/);
});

test("the status badge tells the user to press RESET when the modem is silent", () => {
    const h = loadDashboard();
    h.push({ connected: true, mode: "REAL", port: "COM3", hardware_communicated: false });
    assert.match(h.text("statusText"), /press RESET on the board if just powered/);
    h.push({ connected: true, mode: "REAL", port: "COM3", hardware_communicated: true, modem_responding: false });
    assert.match(h.text("statusText"), /No response \(COM3\) - press RESET/);
    h.push({ connected: true, mode: "REAL", port: "COM3", hardware_communicated: true, modem_responding: true });
    assert.strictEqual(h.text("statusText"), "Connected (COM3)");
});

test("the PSM badge follows the state reported by the module", () => {
    const h = loadDashboard();
    h.push({ ...fullState, psm_info: { enabled: true, status: "PSM Enabled" } });
    assert.strictEqual(h.text("psmStatusBadge"), "PSM Enabled");
    assert.ok(h.document.getElementById("psmStatusBadge").className.includes("badge-good"));
    h.push({ ...fullState, psm_info: { enabled: false, status: "PSM Disabled" } });
    assert.strictEqual(h.text("psmStatusBadge"), "PSM Disabled");
});

test("the status badge says when the modem is asleep", () => {
    const h = loadDashboard();
    h.push({ connected: true, mode: "REAL", port: "COM3", hardware_communicated: true, modem_state: "psm" });
    assert.match(h.text("statusText"), /Modem asleep, PSM \(COM3\) - press RESET to wake it/);
    h.push({ connected: true, mode: "REAL", port: "COM3", hardware_communicated: true, modem_state: "deep_sleep" });
    assert.match(h.text("statusText"), /deep sleep/);
});

test("enabling PSM asks for confirmation and warns about the UART", async () => {
    const h = loadDashboard();
    let message = "";
    h.window.confirm = (m) => { message = m; return false; };
    h.document.getElementById("enablePsmBtn").click();
    assert.match(message, /stop responding on the UART/);
    assert.ok(!h.fetches.some((u) => u.includes("/api/psm")), "declining must not call the API");
});

test("requested and granted PSM values are shown side by side, with a mismatch flag", () => {
    const h = loadDashboard();
    h.push({ ...fullState, psm_info: { enabled: true, status: "PSM Enabled", requested_text: "T3412 5 min, T3324 4 min",
        granted_text: "T3412 1 h, T3324 6 s", mismatch: true } });
    assert.strictEqual(h.text("psmRequestedVal"), "T3412 5 min, T3324 4 min");
    assert.match(h.text("psmGrantedVal"), /T3412 1 h, T3324 6 s \(differs from request\)/);
    h.push({ ...fullState, psm_info: { enabled: true, status: "PSM Enabled", requested_text: "a", granted_text: "a", mismatch: false } });
    assert.strictEqual(h.text("psmGrantedVal"), "a");
});

test("scan panel no longer promises 30 seconds and shows elapsed time (#93)", () => {
    const h = loadDashboard();
    h.push({ ...fullState, is_scanning: true });
    const loading = h.document.getElementById("scanLoading");
    assert.ok(!loading.classList.contains("hidden"));
    assert.doesNotMatch(loading.textContent, /30\s?s/);
    assert.match(loading.textContent, /5 minutes/);
    assert.match(h.text("scanElapsed"), /0:00 elapsed/);
    h.push({ ...fullState, is_scanning: false });
    assert.strictEqual(h.text("scanElapsed"), "");
});

test("a failed scan shows its reason and clears on the next state", () => {
    const h = loadDashboard();
    h.push({ ...fullState, scan_error: "The module gave no answer to AT+COPS=?" });
    const box = h.document.getElementById("scanError");
    assert.ok(!box.classList.contains("hidden"));
    assert.match(box.textContent, /no answer/);
    h.push({ ...fullState, scan_error: null });
    assert.ok(box.classList.contains("hidden"));
});

test("CID 0 is shown as 0, not replaced by 1 (#95)", () => {
    const h = loadDashboard();
    h.push({ ...fullState, apn_info: { ...fullState.apn_info, pdp_cid: 0 } });
    assert.match(h.text("pdpTypeVal"), /CID: 0\)/);
});

test("console lines do not repeat the direction prefix (#95)", () => {
    const h = loadDashboard();
    h.socket.onmessage({ data: JSON.stringify({ type: "log", data: { timestamp: "10:00:00", direction: "TX", text: "TX> AT+CSQ" } }) });
    const lines = h.document.querySelectorAll(".log-line");
    const line = lines[lines.length - 1].textContent;
    assert.match(line, /\[TX\] AT\+CSQ/);
    assert.doesNotMatch(line, /TX> /);
});

test("layout rules exist for the rows that had none (#95)", () => {
    const fs = require("node:fs");
    const path = require("node:path");
    const css = fs.readFileSync(path.join(__dirname, "..", "..", "static", "css", "style.css"), "utf8");
    for (const selector of [".apn-row", ".form-grid", ".form-grid input"]) {
        assert.ok(css.includes(selector + " {") || css.includes(selector + ",\n"), selector);
    }
});

test("history shows bare PLMN codes and labelled ones alike (#95)", async () => {
    const mk = (operator) => ({ timestamp: "t", rsrp: -90, rsrq: -10, rssi: -80, sinr: 5,
        quality_label: "Good", operator, cell_id: "1", temperature: null, voltage: 3600 });
    const h = loadDashboard({ history: [mk("23415"), mk("PLMN 23415"), mk("Example Net")] });
    h.push(fullState);
    await new Promise((resolve) => setTimeout(resolve, 20));
    const text = h.document.getElementById("historyTableBody").textContent;
    assert.strictEqual((text.match(/PLMN 23415/g) || []).length, 2);
    assert.ok(!/PLMN PLMN/.test(text));
});

test("the page does not name an operator it has not detected (#102)", () => {
    const h = loadDashboard();
    assert.strictEqual(h.document.getElementById("apnInput").value, "");
    assert.doesNotMatch(h.document.body.innerHTML, /vodafone/i);
});
