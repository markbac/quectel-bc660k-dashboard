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
