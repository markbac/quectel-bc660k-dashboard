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

const dataset = (h, label) => h.chartConfig.data.datasets.find((d) => d.label.startsWith(label));
const box = (h, key) => h.document.querySelector(`#chartMetrics input[data-metric="${key}"]`);

function toggle(h, key, checked) {
    const input = box(h, key);
    input.checked = checked;
    input.dispatchEvent(new h.window.Event("change"));
}

test("the chart has a dataset and a checkbox for each metric", () => {
    const h = loadDashboard();
    const labels = h.chartConfig.data.datasets.map((d) => d.label.split(" ")[0]);
    assert.deepStrictEqual([...labels], ["RSRP", "RSRQ", "SINR", "RSSI", "CSQ"]);
    assert.strictEqual(h.document.querySelectorAll("#chartMetrics input[data-metric]").length, 5);
});

test("RSRP and RSRQ are shown by default and the other metrics are hidden", () => {
    const h = loadDashboard();
    assert.deepStrictEqual(
        [...h.chartConfig.data.datasets.map((d) => d.hidden)],
        [false, false, true, true, true]
    );
    assert.deepStrictEqual(
        ["rsrp", "rsrq", "sinr", "rssi", "csq"].map((k) => box(h, k).checked),
        [true, true, false, false, false]
    );
});

test("a live poll plots all five readings", async () => {
    const h = loadDashboard();
    h.push(state);
    await tick();
    h.push(state);
    await tick();
    assert.deepStrictEqual(Array.from(dataset(h, "RSRP").data), [-95]);
    assert.deepStrictEqual(Array.from(dataset(h, "RSRQ").data), [-11]);
    assert.deepStrictEqual(Array.from(dataset(h, "SINR").data), [12]);
    assert.deepStrictEqual(Array.from(dataset(h, "RSSI").data), [-85]);
    assert.deepStrictEqual(Array.from(dataset(h, "CSQ").data), [14]);
});

test("a reading the module did not report is plotted as a gap", async () => {
    const h = loadDashboard();
    h.push(state);
    await tick();
    h.push({ ...state, signal: { ...state.signal, sinr: null, csq: undefined } });
    await tick();
    assert.deepStrictEqual(Array.from(dataset(h, "SINR").data), [null]);
    assert.deepStrictEqual(Array.from(dataset(h, "CSQ").data), [null]);
});

test("ticking a checkbox shows its series and its axis, unticking hides them", () => {
    const h = loadDashboard();
    assert.strictEqual(h.chartConfig.options.scales.y2.display, false);
    toggle(h, "csq", true);
    assert.strictEqual(dataset(h, "CSQ").hidden, false);
    assert.strictEqual(h.chartConfig.options.scales.y2.display, true);
    toggle(h, "csq", false);
    assert.strictEqual(dataset(h, "CSQ").hidden, true);
    assert.strictEqual(h.chartConfig.options.scales.y2.display, false);
});

test("an axis stays while another metric on it is still shown", () => {
    const h = loadDashboard();
    toggle(h, "sinr", true);
    toggle(h, "rsrq", false);
    assert.strictEqual(h.chartConfig.options.scales.y1.display, true);
    toggle(h, "sinr", false);
    assert.strictEqual(h.chartConfig.options.scales.y1.display, false);
});

test("the choice is remembered", () => {
    const first = loadDashboard();
    toggle(first, "rssi", true);
    const saved = first.window.localStorage.getItem("quectel-dashboard-chart-metrics");
    const h = loadDashboard({ localStorage: { "quectel-dashboard-chart-metrics": saved } });
    assert.strictEqual(box(h, "rssi").checked, true);
    assert.strictEqual(dataset(h, "RSSI").hidden, false);
});

test("a corrupt saved choice falls back to the defaults", () => {
    const h = loadDashboard({ localStorage: { "quectel-dashboard-chart-metrics": "{not json" } });
    assert.deepStrictEqual(
        [...h.chartConfig.data.datasets.map((d) => d.hidden)],
        [false, false, true, true, true]
    );
});

test("a stored window plots RSSI and CSQ from the series", async () => {
    const series = [
        { unix_time: 1700000000, rsrp: -100, rsrq: -12, sinr: 3, rssi: -87.04, csq: 13 },
        { unix_time: 1700000600, rsrp: -90, rsrq: -9, sinr: 8, rssi: null, csq: null },
    ];
    const h = loadDashboard({ series });
    const select = h.document.getElementById("chartWindow");
    select.value = "24h";
    select.dispatchEvent(new h.window.Event("change"));
    await tick();
    assert.deepStrictEqual(Array.from(dataset(h, "RSSI").data), [-87, null]);
    assert.deepStrictEqual(Array.from(dataset(h, "CSQ").data), [13, null]);
    assert.deepStrictEqual(Array.from(dataset(h, "SINR").data), [3, 8]);
});
