"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { loadDashboard } = require("./harness");

const tick = () => new Promise((resolve) => setTimeout(resolve, 20));
const state = {
    connected: true,
    mode: "REAL",
    port: "COM3",
    hardware_communicated: true,
    signal: { rsrp: -95, rsrq: -11, rssi: -85, sinr: 12, csq: 14, quality_label: "Good" },
    sim_info: { iccid: "89000000000000000001" },
};

test("the history table says it is waiting for the SIM identity", async () => {
    const h = loadDashboard({ awaitingIdentity: true });
    h.push({ ...state, sim_info: { iccid: "--" } });
    await tick();
    assert.match(h.text("historyTableBody"), /Awaiting SIM identity/);
});

test("an empty history for a known SIM says so", async () => {
    const h = loadDashboard();
    h.push(state);
    await tick();
    assert.match(h.text("historyTableBody"), /No historical telemetry records for this SIM/);
});
