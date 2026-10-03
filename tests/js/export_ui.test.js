"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { loadDashboard } = require("./harness");

const tick = () => new Promise((resolve) => setTimeout(resolve, 20));

test("the export dialog is filled from the server settings", async () => {
    const h = loadDashboard({ exportConfig: { enabled: true, interval: 120, mqtt_host: "b.test", mqtt_port: 1883 } });
    h.window.HTMLDialogElement.prototype.showModal = function () {};
    h.document.getElementById("exportBtn").click();
    await tick();
    assert.strictEqual(h.document.getElementById("exportEnabled").checked, true);
    assert.strictEqual(h.document.getElementById("exportInterval").value, "120");
    assert.strictEqual(h.document.getElementById("exportMqttHost").value, "b.test");
});

test("sending a test saves the form first and shows each result", async () => {
    const h = loadDashboard({ exportResults: [{ sink: "webhook", ok: true }, { sink: "mqtt", ok: false, error: "broker down" }] });
    h.document.getElementById("exportWebhook").value = "https://example.test/hook";
    h.document.getElementById("exportInterval").value = "30";
    h.document.getElementById("exportTest").click();
    await tick();
    const calls = h.fetches.filter((u) => u.includes("/api/export"));
    assert.deepStrictEqual(calls.slice(-2), ["/api/export", "/api/export/test"]);
    assert.match(h.text("exportStatus"), /webhook: ok; mqtt: failed \(broker down\)/);
});

test("the saved body carries typed values", async () => {
    const h = loadDashboard();
    h.document.getElementById("exportInterval").value = "45";
    h.document.getElementById("exportEnabled").checked = true;
    h.document.getElementById("exportForm").dispatchEvent(new h.window.Event("submit"));
    await tick();
    assert.strictEqual(h.lastBody.interval, 45);
    assert.strictEqual(h.lastBody.enabled, true);
});
