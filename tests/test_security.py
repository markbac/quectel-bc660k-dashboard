"""Tests for Host and Origin validation."""
import importlib
import sys

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from security import hostname_of, origin_allowed


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """The real application, with its database and logs in a temp directory."""
    tmp = tmp_path_factory.mktemp("srv")
    mp = pytest.MonkeyPatch()
    mp.setenv("QUECTEL_DASHBOARD_DB", str(tmp / "t.db"))
    mp.setattr(sys, "argv", ["server.py", "--no-file-log"])
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="http://localhost:8080") as c:
        yield c
    mp.undo()


@pytest.mark.parametrize("value,expected", [
    ("localhost:8080", "localhost"),
    ("LOCALHOST", "localhost"),
    ("127.0.0.1:9", "127.0.0.1"),
    ("[::1]:8080", "[::1]"),
    ("evil.example:8080", "evil.example"),
])
def test_hostname_of(value, expected):
    assert hostname_of(value) == expected


@pytest.mark.parametrize("origin,ok", [
    ("http://localhost:8080", True),
    ("http://127.0.0.1:8080", True),
    ("http://[::1]:8080", True),
    ("https://evil.example", False),
    ("http://localhost.evil.example", False),
    ("null", False),
    ("file://", False),
])
def test_origin_allowed(origin, ok):
    assert origin_allowed(origin) is ok


def test_normal_ui_requests_still_work(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/state").status_code == 200
    r = client.post("/api/history/clear", headers={"Origin": "http://localhost:8080"})
    assert r.status_code == 200


def test_requests_without_origin_are_allowed(client):
    """curl and scripts send no Origin header."""
    assert client.post("/api/history/clear").status_code == 200


def test_foreign_host_is_refused(client):
    r = client.get("/api/state", headers={"Host": "evil.example:8080"})
    assert r.status_code == 403


def test_foreign_origin_is_refused_on_state_changing_calls(client):
    r = client.post("/api/shutdown", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_websocket_with_foreign_origin_is_refused(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"Origin": "https://evil.example"}):
            pass


def test_websocket_from_the_dashboard_origin_works(client):
    headers = {"Host": "localhost:8080", "Origin": "http://localhost:8080"}
    with client.websocket_connect("/ws", headers=headers) as ws:
        assert ws.receive_json()["type"] == "state"
