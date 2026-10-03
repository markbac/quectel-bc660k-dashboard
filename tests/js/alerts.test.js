"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { createEvaluator, sanitizeSettings, DEFAULT_SETTINGS } = require("../../static/js/alerts.js");

const base = {
    connected: true,
    hardware_communicated: true,
    modem_state: "awake",
    signal: { rsrp: -90, rsrq: -8, quality_label: "Good" },
    serving_cell: { pci: 10, cell_id: "1A" },
};
const withSignal = (patch) => ({ ...base, ...patch, signal: { ...base.signal, ...(patch.signal || {}) } });
const types = (events) => events.map((e) => `${e.type}:${e.severity}`);

test("defaults are used for missing or invalid settings", () => {
    assert.deepStrictEqual(sanitizeSettings(undefined), DEFAULT_SETTINGS);
    const s = sanitizeSettings({ rsrpMin: "abc", rsrqMin: 99, beep: "yes", desktop: true });
    assert.strictEqual(s.rsrpMin, DEFAULT_SETTINGS.rsrpMin);
    assert.strictEqual(s.rsrqMin, 0);
    assert.strictEqual(s.beep, false);
    assert.strictEqual(s.desktop, true);
});

test("an RSRP alert fires once and recovers with hysteresis", () => {
    const ev = createEvaluator();
    assert.deepStrictEqual(ev.evaluate(base), []);
    assert.deepStrictEqual(types(ev.evaluate(withSignal({ signal: { rsrp: -112 } }))), ["rsrp_low:warning"]);
    assert.deepStrictEqual(ev.evaluate(withSignal({ signal: { rsrp: -115 } })), []);
    assert.deepStrictEqual(ev.evaluate(withSignal({ signal: { rsrp: -109 } })), []);  // inside hysteresis
    assert.deepStrictEqual(types(ev.evaluate(withSignal({ signal: { rsrp: -105 } }))), ["rsrp_low:info"]);
});

test("the limit is configurable", () => {
    const ev = createEvaluator();
    const events = ev.evaluate(withSignal({ signal: { rsrp: -95 } }), { rsrpMin: -90 });
    assert.deepStrictEqual(types(events), ["rsrp_low:warning"]);
});

test("RSRQ and the Poor zone raise their own alerts", () => {
    const ev = createEvaluator();
    const events = ev.evaluate(withSignal({ signal: { rsrq: -20, quality_label: "Poor" } }));
    assert.deepStrictEqual(types(events).sort(), ["poor:warning", "rsrq_low:warning"]);
});

test("a cell change is reported as a handover, the first cell is not", () => {
    const ev = createEvaluator();
    assert.deepStrictEqual(ev.evaluate(base), []);
    assert.deepStrictEqual(ev.evaluate(base), []);
    const events = ev.evaluate(withSignal({ serving_cell: { pci: 11, cell_id: "2B" } }));
    assert.deepStrictEqual(types(events), ["handover:warning"]);
    assert.match(events[0].message, /10:1A to 11:2B/);
});

test("placeholder cell ids never count as a handover", () => {
    const ev = createEvaluator();
    ev.evaluate(base);
    assert.deepStrictEqual(ev.evaluate(withSignal({ serving_cell: { pci: "--", cell_id: "--" } })), []);
    assert.deepStrictEqual(ev.evaluate(base), []);
});

test("losing the modem is critical and recovery is reported", () => {
    const ev = createEvaluator();
    ev.evaluate(base);
    assert.deepStrictEqual(types(ev.evaluate(withSignal({ modem_state: "unresponsive" }))), ["disconnect:critical"]);
    assert.deepStrictEqual(ev.evaluate(withSignal({ modem_state: "unresponsive" })), []);
    assert.deepStrictEqual(types(ev.evaluate(base)), ["disconnect:info"]);
});

test("unplugging the port is a disconnect; PSM sleep is not", () => {
    const sleeping = createEvaluator();
    sleeping.evaluate(base);
    assert.deepStrictEqual(sleeping.evaluate(withSignal({ modem_state: "psm" })), []);
    assert.deepStrictEqual(sleeping.evaluate(withSignal({ modem_state: "deep_sleep" })), []);

    const unplugged = createEvaluator();
    unplugged.evaluate(base);
    assert.deepStrictEqual(types(unplugged.evaluate({ connected: false })), ["disconnect:critical"]);
});

test("nothing fires before the modem has ever answered", () => {
    const ev = createEvaluator();
    assert.deepStrictEqual(ev.evaluate({ connected: true, hardware_communicated: false, modem_state: "unresponsive" }), []);
});

test("switches turn individual alerts and the whole feature off", () => {
    const ev = createEvaluator();
    ev.evaluate(base, { notifyHandover: false });
    assert.deepStrictEqual(ev.evaluate(withSignal({ serving_cell: { pci: 11, cell_id: "2B" } }), { notifyHandover: false }), []);
    assert.deepStrictEqual(ev.evaluate(withSignal({ signal: { rsrp: -130 } }), { enabled: false }), []);
});
