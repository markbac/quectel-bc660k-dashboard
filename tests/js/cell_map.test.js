"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { loadDashboard } = require("./harness");

const tick = () => new Promise((resolve) => setTimeout(resolve, 20));

test("nothing third-party is requested until the button is pressed", async () => {
    const h = loadDashboard();
    await tick();
    assert.ok(!h.fetches.some((u) => u.includes("cell_location")));
    assert.strictEqual(h.document.querySelectorAll('script[src*="leaflet"]').length, 0);
    assert.strictEqual(h.document.getElementById("cellMap").hidden, true);
});

test("a failed lookup shows the server's explanation and no map", async () => {
    const h = loadDashboard({ cellLocation: { ok: false, body: { detail: "Set QUECTEL_OPENCELLID_KEY to an OpenCellID API key" } } });
    h.document.getElementById("locateCellBtn").click();
    await tick();
    assert.match(h.text("cellMapNote"), /QUECTEL_OPENCELLID_KEY/);
    assert.strictEqual(h.document.getElementById("cellMap").hidden, true);
    assert.strictEqual(h.document.getElementById("locateCellBtn").disabled, false);
    assert.strictEqual(h.document.querySelectorAll('script[src*="leaflet"]').length, 0);
});

test("a found cell loads a pinned, integrity-checked Leaflet and draws the marker", async () => {
    const h = loadDashboard({ cellLocation: { ok: true, body: { lat: 51.5, lon: -0.12, range: 1500 } } });
    const drawn = [];
    h.window.L = {
        map: () => ({ setView: (...a) => drawn.push(["view", ...a]), invalidateSize() {} }),
        tileLayer: () => ({ addTo() {} }),
        marker: (p) => ({ kind: "marker", p }),
        circle: (p, o) => ({ kind: "circle", p, o }),
        layerGroup: (layers) => ({ addLayer(l) { layers.push(l); drawn.push(["layer", l.kind]); }, addTo() {}, remove() {} }),
    };
    h.document.getElementById("locateCellBtn").click();
    await tick();
    assert.strictEqual(h.document.getElementById("cellMap").hidden, false);
    assert.strictEqual(JSON.stringify(drawn), JSON.stringify([["layer", "circle"], ["view", [51.5, -0.12], 14]]));
    assert.match(h.text("cellMapNote"), /accuracy about 1500 m/);
});

test("the Leaflet assets are pinned with integrity hashes", async () => {
    const h = loadDashboard({ cellLocation: { ok: true, body: { lat: 1, lon: 2, range: null } } });
    h.document.getElementById("locateCellBtn").click();
    await tick();
    const script = h.document.querySelector('script[src*="leaflet"]');
    const css = h.document.querySelector('link[href*="leaflet"]');
    assert.match(script.src, /leaflet@1\.9\.4\/dist\/leaflet\.js$/);
    assert.match(script.integrity, /^sha384-/);
    assert.match(css.integrity, /^sha384-/);
});
