"""Tests for MQTT and webhook export (#1)."""
import json
import threading

import pytest

import exporter as exp
from exporter import ExportConfig, Exporter, build_payload

STATE = {
    "mode": "REAL",
    "hardware_communicated": True,
    "signal": {"rsrp": -95, "rsrq": -10, "rssi": -80, "sinr": 5, "csq": 14, "quality_label": "Fair"},
    "serving_cell": {"operator": "Net", "mcc": "001", "mnc": "01", "cell_id": "1A", "pci": 3,
                     "earfcn": 6300, "band": "8", "tac": "5F"},
    "sim_info": {"iccid": "89000000000000000001", "imsi": "001010000000001"},
    "system_info": {"imei": "860000000000000"},
}


def state(rsrp=-95):
    return {**STATE, "signal": {**STATE["signal"], "rsrp": rsrp}}


class Sinks:
    """Records what would be sent and lets tests wait for the worker thread."""

    def __init__(self, fail=None):
        self.webhooks, self.mqtt, self.fail = [], [], fail
        self.done = threading.Event()

    def webhook(self, url, payload, token=None):
        if self.fail == "webhook":
            raise OSError("connection refused")
        self.webhooks.append((url, payload, token))
        self.done.set()

    def publish(self, config, topic, payload):
        if self.fail == "mqtt":
            raise RuntimeError("broker down")
        self.mqtt.append((topic, payload))
        self.done.set()


def make(sinks, clock=None, **config):
    base = {"enabled": True, "interval": 60, "webhook_url": "https://example.test/hook",
            "mqtt_host": "broker.test"}
    base.update(config)
    ticks = clock if clock is not None else iter(range(0, 10_000, 100))
    return Exporter(ExportConfig.from_dict(base), webhook=sinks.webhook, mqtt=sinks.publish,
                    clock=lambda: next(ticks))


def drain(exporter):
    exporter.flush()


def test_payload_has_signal_cell_and_timestamp_but_no_identifiers():
    payload = build_payload(STATE, "bench")
    assert payload["device"] == "bench"
    assert payload["signal"]["rsrp"] == -95
    assert payload["cell"]["cell_id"] == "1A"
    assert payload["timestamp"].endswith("+00:00")
    text = json.dumps(payload)
    for secret in ("89000000000000000001", "001010000000001", "860000000000000"):
        assert secret not in text


def test_telemetry_goes_to_both_sinks():
    sinks = Sinks()
    exporter = make(sinks)
    exporter.on_event("state", state())
    drain(exporter)
    assert len(sinks.webhooks) == 1
    assert [t for t, _ in sinks.mqtt] == ["quectel/bc660k/telemetry"]
    assert exporter.sent == 2


def test_not_resent_inside_the_interval():
    sinks = Sinks()
    exporter = make(sinks, clock=iter([0, 10, 20, 30]), interval=60)
    for _ in range(4):
        exporter.on_event("state", state())
    drain(exporter)
    assert len(sinks.webhooks) == 1


def test_nothing_is_sent_when_disabled_or_modem_silent_or_no_rsrp():
    sinks = Sinks()
    make(sinks, enabled=False).on_event("state", state())
    silent = make(sinks)
    silent.on_event("state", {**STATE, "hardware_communicated": False})
    silent.on_event("state", state(rsrp=None))
    silent.on_event("log", {})
    drain(silent)
    assert sinks.webhooks == [] and sinks.mqtt == []


def test_degradation_sends_one_alert_and_one_recovery():
    sinks = Sinks()
    exporter = make(sinks, clock=iter([0, 1, 2, 3, 4, 5]), interval=3600, degradation_rsrp=-110)
    for rsrp in (-95, -115, -120, -108, -105):
        exporter.on_event("state", state(rsrp))
    drain(exporter)
    kinds = [p["type"] for _, p, _ in sinks.webhooks]
    assert kinds == ["telemetry", "signal_degraded", "signal_recovered"]
    assert ("quectel/bc660k/telemetry/alert") in [t for t, _ in sinks.mqtt]


def test_degradation_only_mode_skips_periodic_webhooks():
    sinks = Sinks()
    exporter = make(sinks, webhook_degradation_only=True, interval=3600, clock=iter([0, 1000]))
    exporter.on_event("state", state(-95))
    exporter.on_event("state", state(-120))
    drain(exporter)
    assert [p["type"] for _, p, _ in sinks.webhooks] == ["signal_degraded"]
    assert [t for t, _ in sinks.mqtt] == ["quectel/bc660k/telemetry", "quectel/bc660k/telemetry/alert"]


def test_webhook_token_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("QUECTEL_WEBHOOK_TOKEN", "s3cret")
    sinks = Sinks()
    exporter = make(sinks)
    exporter.on_event("state", state())
    drain(exporter)
    assert sinks.webhooks[0][2] == "s3cret"
    assert "s3cret" not in json.dumps(exporter.status())


def test_failures_are_recorded_not_raised():
    sinks = Sinks(fail="webhook")
    exporter = make(sinks)
    exporter.on_event("state", state())
    drain(exporter)
    assert "connection refused" in exporter.last_error
    assert exporter.status()["last_error"].startswith("webhook:")


def test_send_test_reports_each_sink():
    sinks = Sinks(fail="mqtt")
    exporter = make(sinks)
    results = exporter.send_test(STATE)
    assert [(s, ok) for s, ok, _ in results] == [("webhook", True), ("mqtt", False)]
    assert exporter.send_test(STATE) and sinks.webhooks[0][1]["type"] == "test"


def test_send_test_with_nothing_configured_is_empty():
    assert Exporter(ExportConfig()).send_test(STATE) == []


@pytest.mark.parametrize("raw,field,expected", [
    ({"interval": 1}, "interval", 10),
    ({"interval": 99999}, "interval", 3600),
    ({"interval": "abc"}, "interval", 60),
    ({"mqtt_port": 0}, "mqtt_port", 1),
    ({"degradation_rsrp": 5}, "degradation_rsrp", -40),
    ({"webhook_url": "file:///etc/passwd"}, "webhook_url", ""),
    ({"webhook_url": "ftp://x"}, "webhook_url", ""),
    ({"webhook_url": "https://ok.test/h"}, "webhook_url", "https://ok.test/h"),
    ({"mqtt_host": "evil/host"}, "mqtt_host", ""),
    ({"mqtt_topic": "a/#"}, "mqtt_topic", "quectel/bc660k/telemetry"),
    ({"enabled": "yes"}, "enabled", False),
    ({"enabled": True}, "enabled", True),
])
def test_config_validation(raw, field, expected):
    assert getattr(ExportConfig.from_dict(raw), field) == expected


def test_config_round_trips_and_survives_damage(tmp_path):
    path = str(tmp_path / "sub" / "export.json")
    config = ExportConfig.from_dict({"enabled": True, "mqtt_host": "b.test"})
    config.save(path)
    assert ExportConfig.load(path) == config
    with open(path, "w") as handle:
        handle.write("{broken")
    assert ExportConfig.load(path) == ExportConfig()
    assert ExportConfig.load(str(tmp_path / "missing.json")) == ExportConfig()


def test_webhook_rejects_non_http_urls():
    with pytest.raises(ValueError):
        exp.send_webhook("file:///etc/passwd", {})


def test_mqtt_without_the_package_explains_itself(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("paho"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="paho-mqtt"):
        exp.send_mqtt(ExportConfig(mqtt_host="b.test"), "t", {})


def test_webhook_posts_json_with_bearer_token_to_a_real_server():
    import http.server

    received = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            received["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received["auth"] = self.headers.get("Authorization")
            received["type"] = self.headers.get("Content-Type")
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        exp.send_webhook(f"http://127.0.0.1:{server.server_port}/hook", {"a": 1}, token="tok")
        thread.join(5)
    finally:
        server.server_close()
    assert received == {"body": {"a": 1}, "auth": "Bearer tok", "type": "application/json"}


def test_webhook_error_status_raises():
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(500)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    try:
        with pytest.raises(OSError):
            exp.send_webhook(f"http://127.0.0.1:{server.server_port}/", {})
    finally:
        server.server_close()
