"""Register and deregister from the dashboard (#103)."""
import importlib
import sys

import pytest
from starlette.testclient import TestClient

from tests.fake_serial import FakeSerial


def _manager_with(manager, replies):
    manager.state["modem_state"] = "awake"
    manager.ser = FakeSerial(replies)
    manager.running = True
    return manager


COPS_Q = '\r\n+COPS: 1,2,"23415",9\r\n\r\nOK\r\n'
CEREG_Q = '\r\n+CEREG: 4,5,"E43A","004EB815",9\r\n\r\nOK\r\n'


@pytest.mark.parametrize("action,plmn,command", [
    ("deregister", None, "AT+COPS=2"),
    ("auto", None, "AT+COPS=0"),
    ("manual", "23415", 'AT+COPS=1,2,"23415",9'),
])
def test_commands_sent(manager, action, plmn, command):
    _manager_with(manager, {command: "\r\nOK\r\n", "AT+COPS?": COPS_Q, "AT+CEREG?": CEREG_Q})
    assert "OK" in manager.set_registration(action, plmn)
    assert command in manager.ser.sent


@pytest.mark.parametrize("action,plmn", [("explode", None), ("manual", None), ("manual", "ab"), ("manual", '1";AT')])
def test_bad_requests_are_refused_before_anything_is_sent(manager, action, plmn):
    _manager_with(manager, {})
    with pytest.raises(ValueError):
        manager.set_registration(action, plmn)
    assert manager.ser.sent == []


def test_refused_while_scanning(manager):
    _manager_with(manager, {})
    manager.state["is_scanning"] = True
    with pytest.raises(RuntimeError):
        manager.set_registration("deregister")


def test_cops_set_commands_get_a_long_timeout():
    import at_channel
    assert at_channel.timeout_for("AT+COPS=2") == 180.0
    assert at_channel.timeout_for('AT+COPS=1,2,"23415",9') == 180.0
    assert at_channel.timeout_for("AT+COPS=?") == 600.0


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("QUECTEL_DASHBOARD_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(sys, "argv", ["server.py", "--no-file-log"])
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="http://localhost:8080") as c:
        c.server = server
        yield c
    server.manager.set_file_logging(False)


def test_api_needs_a_connection(client):
    assert client.post("/api/register", json={"action": "auto"}).status_code == 400


def test_api_maps_errors_to_status_codes(client):
    manager = client.server.manager
    manager.is_connected = True
    assert client.post("/api/register", json={"action": "nope"}).status_code == 422
    manager.state["is_scanning"] = True
    assert client.post("/api/register", json={"action": "deregister"}).status_code == 409
    manager.state["is_scanning"] = False
    manager.is_demo = True
    reply = client.post("/api/register", json={"action": "deregister"})
    assert reply.status_code == 200 and reply.json()["status"] == "ok"
