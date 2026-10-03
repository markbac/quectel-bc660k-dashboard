"""API tests for remote export settings (#1)."""
import importlib
import json
import os
import sys

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["server.py", "--no-file-log"])
    monkeypatch.setenv("QUECTEL_DASHBOARD_DB", str(tmp_path / "api.db"))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="http://localhost:8080") as client:
        yield server, client, tmp_path


def test_defaults_are_off(api):
    _, client, _ = api
    body = client.get("/api/export").json()
    assert body["config"]["enabled"] is False
    assert body["sent"] == 0


def test_settings_are_validated_applied_and_saved(api):
    server, client, tmp_path = api
    body = client.post("/api/export", json={
        "enabled": True, "interval": 5, "webhook_url": "file:///etc/passwd",
        "mqtt_host": "broker.test", "mqtt_topic": "a/b",
    }).json()

    assert body["config"]["interval"] == 10             # clamped
    assert body["config"]["webhook_url"] == ""          # not http(s)
    assert server.exporter.config.mqtt_host == "broker.test"
    saved = json.loads((tmp_path / "export_settings.json").read_text())
    assert saved["mqtt_topic"] == "a/b"
    assert "password" not in json.dumps(saved).lower()


def test_test_endpoint_needs_a_destination(api):
    _, client, _ = api
    assert client.post("/api/export/test").status_code == 400


def test_test_endpoint_reports_per_sink(api):
    server, client, _ = api
    sent = []
    server.exporter._webhook = lambda url, payload, token=None: sent.append(payload)
    client.post("/api/export", json={"enabled": True, "webhook_url": "https://example.test/h"})
    body = client.post("/api/export/test").json()
    assert body["results"] == [{"sink": "webhook", "ok": True, "error": None}]
    assert sent[0]["type"] == "test"


def test_settings_are_loaded_at_start(tmp_path, monkeypatch):
    (tmp_path / "export_settings.json").write_text(json.dumps({"enabled": True, "mqtt_host": "b.test"}))
    monkeypatch.setattr(sys, "argv", ["server.py", "--no-file-log"])
    monkeypatch.setenv("QUECTEL_DASHBOARD_DB", str(tmp_path / "x.db"))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    assert server.exporter.config.enabled and server.exporter.config.mqtt_host == "b.test"
    assert os.path.exists(server.export_settings_path)
