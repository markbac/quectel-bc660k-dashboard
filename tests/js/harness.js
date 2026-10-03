"use strict";
/** Load static/index.html and static/js/app.js into jsdom with stubs. */
const fs = require("node:fs");
const path = require("node:path");
const { after } = require("node:test");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "..", "..");

// Close every window when the test file ends so page timers cannot keep Node alive.
const windows = [];
after(() => windows.forEach((w) => w.close()));

function loadDashboard(options = {}) {
    const html = fs
        .readFileSync(path.join(root, "static", "index.html"), "utf8")
        .replace(/<script[^>]*src="https?:[^>]*><\/script>/g, "");
    const dom = new JSDOM(html, {
        runScripts: "outside-only",
        pretendToBeVisual: true,
        url: "http://localhost:8080/",
    });
    const w = dom.window;
    windows.push(w);
    const harness = { window: w, document: w.document, socket: null, fetches: [] };

    w.WebSocket = class {
        constructor() {
            harness.socket = this;
        }
        send() {}
        close() {}
    };
    w.fetch = async (url, init) => {
        harness.fetches.push(String(url));
        harness.lastBody = init && init.body ? JSON.parse(init.body) : null;
        if (String(url).includes("/api/cell_location") && options.cellLocation) {
            return { ok: options.cellLocation.ok, json: async () => options.cellLocation.body };
        }
        return {
            ok: true,
            json: async () => ({
                ports: [],
                history: options.history || [],
                stats: { total_records: (options.history || []).length },
                series: options.series || [],
                config: options.exportConfig || {},
                sent: 0,
                results: options.exportResults || [],
                awaiting_identity: Boolean(options.awaitingIdentity),
            }),
        };
    };
    w.Chart = class {
        constructor(ctx, config) {
            harness.chartConfig = config;
        }
        update() {}
    };
    w.HTMLCanvasElement.prototype.getContext = () => ({});
    w.alert = () => {};
    for (const [key, value] of Object.entries(options.localStorage || {})) {
        w.localStorage.setItem(key, value);
    }
    w.confirm = () => true;

    // Run the page's DOMContentLoaded handler exactly once, synchronously,
    // instead of also letting jsdom fire the real event later (which would
    // start a second copy of the dashboard).
    let onReady = null;
    w.document.addEventListener = (type, handler) => {
        if (type === "DOMContentLoaded") {
            onReady = handler;
        }
    };
    for (const script of ["alerts.js", "app.js"]) {
        w.eval(fs.readFileSync(path.join(root, "static", "js", script), "utf8"));
    }
    onReady();

    harness.push = (state) =>
        harness.socket.onmessage({ data: JSON.stringify({ type: "state", data: state }) });
    harness.chartRsrp = () => harness.chartConfig.data.datasets[0].data;
    harness.text = (id) => w.document.getElementById(id).textContent;
    return harness;
}

module.exports = { loadDashboard };
