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

test("history is not refetched on every state push", async () => {
    const h = loadDashboard();
    await tick();
    const initial = h.fetches.filter((u) => u.includes("/api/history")).length;
    for (let i = 0; i < 5; i += 1) {
        h.push(state);
    }
    await tick();
    const afterPushes = h.fetches.filter((u) => u.includes("/api/history")).length;
    // One extra fetch for the SIM becoming known, not one per push.
    assert.ok(afterPushes - initial <= 1, `fetched ${afterPushes - initial} extra times`);
});

test("history is reloaded when the SIM changes", async () => {
    const h = loadDashboard();
    h.push(state);
    await tick();
    const before = h.fetches.filter((u) => u.includes("/api/history")).length;
    h.push({ ...state, sim_info: { iccid: "89000000000000000002" } });
    await tick();
    assert.strictEqual(h.fetches.filter((u) => u.includes("/api/history")).length, before + 1);
});
