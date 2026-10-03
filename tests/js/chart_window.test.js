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
const series = [
    { unix_time: 1700000000, rsrp: -100.04, rsrq: -12, sinr: 3 },
    { unix_time: 1700000600, rsrp: -90, rsrq: -9, sinr: 8 },
];

// The first state with a new ICCID resets the chart, so settle the SIM first.
async function settle(h) {
    h.push(state);
    await tick();
}

function choose(h, value) {
    const select = h.document.getElementById("chartWindow");
    select.value = value;
    select.dispatchEvent(new h.window.Event("change"));
}

test("live mode plots polls and does not fetch the series", async () => {
    const h = loadDashboard({ series });
    await settle(h);
    h.push(state);
    await tick();
    assert.deepStrictEqual(Array.from(h.chartRsrp()), [-95]);
    assert.ok(!h.fetches.some((u) => u.includes("/api/history/series")));
});

test("choosing a window plots the stored series", async () => {
    const h = loadDashboard({ series });
    choose(h, "24h");
    await tick();
    assert.ok(h.fetches.some((u) => u.includes("/api/history/series?window=24h")));
    assert.deepStrictEqual(Array.from(h.chartRsrp()), [-100, -90]);
});

test("live polls are not mixed into a stored window", async () => {
    const h = loadDashboard({ series });
    await settle(h);
    choose(h, "7d");
    await tick();
    h.push(state);
    await tick();
    assert.deepStrictEqual(Array.from(h.chartRsrp()), [-100, -90]);
});

test("going back to live starts a fresh live trace", async () => {
    const h = loadDashboard({ series });
    await settle(h);
    choose(h, "1h");
    await tick();
    choose(h, "live");
    await tick();
    assert.deepStrictEqual(Array.from(h.chartRsrp()), []);
    h.push(state);
    await tick();
    assert.deepStrictEqual(Array.from(h.chartRsrp()), [-95]);
});
