"use strict";
/** Load static/index.html and static/js/app.js into jsdom with stubs. */
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "..", "..");

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
    const harness = { window: w, document: w.document, socket: null };

    w.WebSocket = class {
        constructor() {
            harness.socket = this;
        }
        send() {}
        close() {}
    };
    w.fetch = async () => ({
        ok: true,
        json: async () => ({
            ports: [],
            history: options.history || [],
            stats: { total_records: (options.history || []).length },
            awaiting_identity: Boolean(options.awaitingIdentity),
        }),
    });
    w.Chart = class {
        update() {}
    };
    w.HTMLCanvasElement.prototype.getContext = () => ({});
    w.alert = () => {};
    w.confirm = () => true;

    w.eval(fs.readFileSync(path.join(root, "static", "js", "app.js"), "utf8"));
    w.document.dispatchEvent(new w.Event("DOMContentLoaded"));

    harness.push = (state) =>
        harness.socket.onmessage({ data: JSON.stringify({ type: "state", data: state }) });
    harness.text = (id) => w.document.getElementById(id).textContent;
    return harness;
}

module.exports = { loadDashboard };
