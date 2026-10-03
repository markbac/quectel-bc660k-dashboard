/**
 * Signal alert rules. Pure logic with no DOM access, so it can be tested in Node.
 *
 * An evaluator is fed every dashboard state and returns the alert events that
 * state caused. Alerts are edge triggered: one event when a condition starts,
 * one recovery event when it ends, nothing in between.
 */
(function (root) {
    "use strict";

    const DEFAULT_SETTINGS = Object.freeze({
        enabled: true,
        rsrpMin: -110,
        rsrqMin: -15,
        notifyPoor: true,
        notifyHandover: true,
        notifyDisconnect: true,
        desktop: false,
        beep: false,
    });

    // A reading must climb this far above its limit before the alert resets,
    // so a value hovering at the limit does not raise an alert every poll.
    const HYSTERESIS_DB = 3;

    function clampNumber(value, fallback, min, max) {
        const number = Number(value);
        return Number.isFinite(number) ? Math.min(max, Math.max(min, number)) : fallback;
    }

    /** Return a complete, in-range settings object from untrusted stored values. */
    function sanitizeSettings(raw) {
        const source = raw && typeof raw === "object" ? raw : {};
        const flag = (key) => (typeof source[key] === "boolean" ? source[key] : DEFAULT_SETTINGS[key]);
        return {
            enabled: flag("enabled"),
            rsrpMin: clampNumber(source.rsrpMin, DEFAULT_SETTINGS.rsrpMin, -140, -40),
            rsrqMin: clampNumber(source.rsrqMin, DEFAULT_SETTINGS.rsrqMin, -30, 0),
            notifyPoor: flag("notifyPoor"),
            notifyHandover: flag("notifyHandover"),
            notifyDisconnect: flag("notifyDisconnect"),
            desktop: flag("desktop"),
            beep: flag("beep"),
        };
    }

    function isNumber(value) {
        return typeof value === "number" && Number.isFinite(value);
    }

    function cellKey(cell) {
        if (!cell || !cell.cell_id || cell.cell_id === "--") return null;
        return `${cell.pci}:${cell.cell_id}`;
    }

    /**
     * Create an evaluator. ``evaluate(state, settings)`` returns an array of
     * ``{type, severity, message}`` where severity is ``warning``, ``critical``
     * or ``info`` (recoveries).
     */
    function createEvaluator() {
        const active = { rsrp: false, rsrq: false, poor: false, lost: false };
        let lastCell = null;
        let wasCommunicating = false;

        function threshold(events, flag, value, limit, type, label, unit) {
            if (!active[flag] && value < limit) {
                active[flag] = true;
                events.push({ type, severity: "warning", message: `${label} ${value} ${unit} is below ${limit} ${unit}` });
            } else if (active[flag] && value >= limit + HYSTERESIS_DB) {
                active[flag] = false;
                events.push({ type, severity: "info", message: `${label} recovered to ${value} ${unit}` });
            }
        }

        function evaluate(state, rawSettings) {
            const settings = sanitizeSettings(rawSettings);
            const events = [];
            if (!settings.enabled || !state) return events;

            const communicating = Boolean(state.hardware_communicated);
            const expectedSilence = state.modem_state === "psm" || state.modem_state === "deep_sleep";
            const down = wasCommunicating && !expectedSilence
                && (state.connected === false || state.modem_state === "unresponsive");

            if (settings.notifyDisconnect) {
                if (down && !active.lost) {
                    active.lost = true;
                    events.push({ type: "disconnect", severity: "critical", message: "Lost contact with the modem" });
                } else if (!down && active.lost && communicating && state.connected !== false
                           && state.modem_state !== "unresponsive") {
                    active.lost = false;
                    events.push({ type: "disconnect", severity: "info", message: "Modem is answering again" });
                }
            }
            if (communicating && !down) wasCommunicating = true;
            if (state.connected === false) {
                wasCommunicating = false;
                lastCell = null;
            }

            const signal = state.signal || {};
            const hasSignal = communicating && isNumber(signal.rsrp);
            if (!hasSignal) return events;

            threshold(events, "rsrp", signal.rsrp, settings.rsrpMin, "rsrp_low", "RSRP", "dBm");
            if (isNumber(signal.rsrq)) {
                threshold(events, "rsrq", signal.rsrq, settings.rsrqMin, "rsrq_low", "RSRQ", "dB");
            }

            if (settings.notifyPoor) {
                const poor = String(signal.quality_label || "").toLowerCase() === "poor";
                if (poor && !active.poor) {
                    active.poor = true;
                    events.push({ type: "poor", severity: "warning", message: "Signal quality dropped into the Poor zone" });
                } else if (!poor && active.poor) {
                    active.poor = false;
                    events.push({ type: "poor", severity: "info", message: `Signal quality is ${signal.quality_label || "back to normal"}` });
                }
            }

            const key = cellKey(state.serving_cell);
            if (key) {
                if (settings.notifyHandover && lastCell && key !== lastCell) {
                    events.push({ type: "handover", severity: "warning", message: `Serving cell changed from ${lastCell} to ${key} (PCI:cell)` });
                }
                lastCell = key;
            }
            return events;
        }

        return { evaluate };
    }

    const api = { DEFAULT_SETTINGS, HYSTERESIS_DB, sanitizeSettings, createEvaluator };
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    } else {
        root.AlertRules = api;
    }
})(typeof window !== "undefined" ? window : globalThis);
