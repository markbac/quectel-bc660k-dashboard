"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { loadDashboard } = require("./harness");

const html = fs.readFileSync(path.join(__dirname, "..", "..", "static", "index.html"), "utf8");

test("the shipped page contains no SIM or device identifiers", () => {
    // ICCID (19-20 digits) and IMSI/IMEI (15 digits) must not be hard-coded.
    assert.doesNotMatch(html, /\b\d{15,20}\b/);
});

test("telemetry fields show placeholders before any modem data arrives", () => {
    const h = loadDashboard();
    for (const id of ["rsrpVal", "rsrqVal", "rssiVal", "sinrVal", "iccidVal", "imsiVal",
                      "currentApnVal", "pdpTypeVal", "plmnVal", "pciVal", "bandVal"]) {
        assert.strictEqual(h.text(id), "--", id);
    }
    assert.strictEqual(h.text("cellIdDec"), "");
    assert.strictEqual(h.text("tacDec"), "");
    assert.strictEqual(h.document.getElementById("rsrpBar").style.width, "0%");
});
