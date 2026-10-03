"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { loadDashboard } = require("./harness");

const PAYLOAD = "<img src=x onerror=alert(1)>";

const state = {
    connected: true,
    mode: "REAL",
    port: "COM3",
    hardware_communicated: true,
    signal: { rsrp: -95, rsrq: -11, rssi: -85, sinr: 12, csq: 14, quality_label: "Good" },
    neighbour_cells: [{ pci: PAYLOAD, earfcn: PAYLOAD, rsrp: -100, rsrq: -12 }],
    networks_scan: [
        { status: PAYLOAD, long_name: PAYLOAD, short_name: PAYLOAD, plmn: PAYLOAD, act: PAYLOAD },
    ],
};

const tick = () => new Promise((resolve) => setTimeout(resolve, 20));

test("hostile operator names in the scan table are rendered as text", () => {
    const h = loadDashboard();
    h.push(state);
    const body = h.document.getElementById("networksTableBody");
    assert.strictEqual(body.querySelector("img"), null);
    assert.ok(body.textContent.includes(PAYLOAD));
});

test("hostile values in the neighbour table are rendered as text", () => {
    const h = loadDashboard();
    h.push(state);
    const body = h.document.getElementById("neighbourTableBody");
    assert.strictEqual(body.querySelector("img"), null);
    assert.ok(body.textContent.includes(PAYLOAD));
});

test("hostile values in the history table are rendered as text", async () => {
    const row = {
        timestamp: PAYLOAD, rsrp: -90, rsrq: -10, rssi: -80, sinr: 5,
        quality_label: PAYLOAD, operator: PAYLOAD, cell_id: PAYLOAD, temperature: null, voltage: 3600,
    };
    const h = loadDashboard({ history: [row] });
    h.push(state);
    await tick();
    const body = h.document.getElementById("historyTableBody");
    assert.strictEqual(body.querySelector("img"), null);
    assert.ok(body.textContent.includes(PAYLOAD));
});

test("quality labels map to a fixed set of classes", async () => {
    const h = loadDashboard();
    h.push({ ...state, signal: { ...state.signal, quality_label: "Awaiting Data" } });
    assert.strictEqual(h.document.getElementById("rsrpQuality").className, "badge badge-secondary");
    h.push({ ...state, signal: { ...state.signal, quality_label: 'x" onmouseover="alert(1)' } });
    assert.strictEqual(h.document.getElementById("rsrpQuality").className, "badge badge-secondary");
    h.push({ ...state, signal: { ...state.signal, quality_label: "Excellent" } });
    assert.strictEqual(h.document.getElementById("rsrpQuality").className, "badge badge-excellent");
});
