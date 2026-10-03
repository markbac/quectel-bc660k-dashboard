"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { loadDashboard } = require("./harness");

const tick = () => new Promise((resolve) => setTimeout(resolve, 20));
const state = (rsrp, extra = {}) => ({
    connected: true,
    mode: "REAL",
    port: "COM3",
    hardware_communicated: true,
    modem_state: "awake",
    signal: { rsrp, rsrq: -8, rssi: -85, sinr: 12, csq: 14, quality_label: "Good" },
    serving_cell: { pci: 1, cell_id: "1A" },
    sim_info: { iccid: "89000000000000000001" },
    ...extra,
});

function alertLines(h) {
    return [...h.document.querySelectorAll("#logConsole .log-alert, #logConsole .log-critical, #logConsole .log-recovery")]
        .map((el) => `${el.className.replace("log-line ", "")}|${el.textContent}`);
}

test("a weak signal adds a highlighted alert line, once", async () => {
    const h = loadDashboard();
    h.push(state(-90));
    h.push(state(-120));
    h.push(state(-121));
    await tick();
    const lines = alertLines(h);
    assert.strictEqual(lines.length, 1);
    assert.match(lines[0], /^log-alert\|.*RSRP -120 dBm is below -110 dBm/);
});

test("losing the modem is a critical line", async () => {
    const h = loadDashboard();
    h.push(state(-90));
    h.push(state(-90, { modem_state: "unresponsive" }));
    await tick();
    assert.match(alertLines(h)[0], /^log-critical\|.*Lost contact/);
});

test("saved settings change the threshold and persist in localStorage", async () => {
    const h = loadDashboard();
    const doc = h.document;
    doc.getElementById("alertEnabled").checked = true;
    doc.getElementById("alertRsrpMin").value = "-80";
    doc.getElementById("alertRsrqMin").value = "-15";
    doc.getElementById("alertsForm").dispatchEvent(new h.window.Event("submit"));
    assert.strictEqual(JSON.parse(h.window.localStorage.getItem("quectel-dashboard-alerts")).rsrpMin, -80);
    h.push(state(-70));
    h.push(state(-85));
    await tick();
    assert.match(alertLines(h)[0], /below -80 dBm/);
});

test("corrupt stored settings fall back to the defaults", async () => {
    const h = loadDashboard({ localStorage: { "quectel-dashboard-alerts": "{not json" } });
    h.push(state(-90));
    h.push(state(-120));
    await tick();
    assert.match(alertLines(h)[0], /below -110 dBm/);
});

test("switching alerts off silences them", async () => {
    const h = loadDashboard({ localStorage: { "quectel-dashboard-alerts": JSON.stringify({ enabled: false }) } });
    h.push(state(-90));
    h.push(state(-130));
    await tick();
    assert.deepStrictEqual(alertLines(h), []);
});
