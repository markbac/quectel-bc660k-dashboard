"use strict";
// Regression tests for the problems found in the October 2026 code review (#122 to #125).
const test = require("node:test");
const assert = require("node:assert");
const { loadDashboard } = require("./harness");

const tick = () => new Promise((resolve) => setTimeout(resolve, 20));
const base = {
    connected: true,
    mode: "REAL",
    port: "COM3",
    hardware_communicated: true,
    signal: { rsrp: -95, rsrq: -11, rssi: -85, sinr: 12, csq: 14, quality_label: "Good" },
    sim_info: { iccid: "89000000000000000001" },
};
const rsrpData = (h) => Array.from(h.chartConfig.data.datasets[0].data);

test("RSRQ and RSSI bars are empty, not full, when the module reports no value (#122)", () => {
    const h = loadDashboard();
    h.push({ ...base, signal: { ...base.signal, rsrq: null, rssi: null, csq: null } });
    assert.strictEqual(h.document.getElementById("rsrqBar").style.width, "0%");
    assert.strictEqual(h.document.getElementById("rssiBar").style.width, "0%");
    h.push(base);
    assert.notStrictEqual(h.document.getElementById("rssiBar").style.width, "0%");
});

test("PCI 0 and EARFCN 0 are shown as numbers (#123)", () => {
    const h = loadDashboard();
    h.push({ ...base, serving_cell: { rat: "NB-IoT", pci: 0, earfcn: 0, band: "8", cell_id: "1A", tac: "5F" } });
    assert.strictEqual(h.text("pciVal"), "0");
    assert.match(h.text("bandVal"), /EARFCN 0 /);
});

test("an unknown PCI still shows the placeholder (#123)", () => {
    const h = loadDashboard();
    h.push({ ...base, serving_cell: { rat: "NB-IoT", pci: "--", earfcn: "--" } });
    assert.strictEqual(h.text("pciVal"), "--");
    assert.strictEqual(h.text("bandVal"), "--");
});

test("the log console keeps only the newest 500 lines (#124)", () => {
    const h = loadDashboard();
    for (let i = 0; i < 520; i++) {
        h.socket.onmessage({ data: JSON.stringify({ type: "log", data: { timestamp: "00:00:00", direction: "INFO", text: `line ${i}` } }) });
    }
    const lines = h.document.getElementById("logConsole").children;
    assert.strictEqual(lines.length, 500);
    assert.match(lines[0].textContent, /line 20$/);
    assert.match(lines[499].textContent, /line 519$/);
});

test("a state push that is not a new poll adds no live point (#125)", async () => {
    const h = loadDashboard();
    h.push({ ...base, last_update: 99 });  // the first state for a SIM resets the chart
    await tick();
    h.push({ ...base, last_update: 100 });
    h.push({ ...base, last_update: 100 });
    h.push({ ...base, last_update: 100, is_scanning: true });
    h.push({ ...base, last_update: 103 });
    await tick();
    assert.strictEqual(rsrpData(h).length, 2);
});

test("no live point is added while the module is silent", async () => {
    const h = loadDashboard();
    h.push({ ...base, last_update: 0 });  // the first state for a SIM resets the chart
    await tick();
    h.push({ ...base, last_update: 1 });
    await tick();
    for (const modem_state of ["unresponsive", "psm", "deep_sleep"]) {
        h.push({ ...base, last_update: 3, modem_state });
    }
    assert.strictEqual(rsrpData(h).length, 1);
    h.push({ ...base, last_update: 4, modem_state: "awake" });
    assert.strictEqual(rsrpData(h).length, 2);
});
