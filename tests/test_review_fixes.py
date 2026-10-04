"""Regression tests for the problems found in the October 2026 code review (#116 to #121, #126)."""
import http.server
import importlib
import sys
import threading
import time

import pytest
import serial

import exporter
from tests.fake_serial import FakeSerial

ICCID = "89000000000000000001"


def wait_until(predicate, seconds=5.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# --- #116 reconnecting ---------------------------------------------------------

def test_reconnect_stops_the_old_poll_loop(manager, monkeypatch):
    monkeypatch.setattr(serial, "Serial", lambda *a, **k: FakeSerial({}))
    manager.telemetry_interval = 30  # the old loop would sleep through the reconnect
    manager.connect("PORT_A", 115200)
    old = manager.poll_thread
    manager.connect("PORT_B", 115200)
    old.join(timeout=5)
    try:
        assert not old.is_alive()
        assert manager.poll_thread.is_alive()
    finally:
        manager.disconnect()


def test_disconnect_stops_the_poll_loop_promptly(manager, monkeypatch):
    monkeypatch.setattr(serial, "Serial", lambda *a, **k: FakeSerial({}))
    manager.telemetry_interval = 30
    manager.connect("PORT_A", 115200)
    thread = manager.poll_thread
    manager.disconnect()
    thread.join(timeout=5)
    assert not thread.is_alive()


# --- #117 stale values ---------------------------------------------------------

@pytest.mark.parametrize("modem_state", ["unresponsive", "psm", "deep_sleep"])
def test_no_history_row_while_the_modem_is_silent(manager, modem_state):
    manager.state.update({"hardware_communicated": True, "modem_state": modem_state})
    manager.state["signal"]["rsrp"] = -90
    manager.state["sim_info"]["iccid"] = ICCID
    manager._log_history()
    assert manager.db.get_history(ICCID) == []
    manager.state["modem_state"] = "awake"
    manager._log_history()
    assert len(manager.db.get_history(ICCID)) == 1


# --- #118 AT parameters --------------------------------------------------------

BAD_TEXT = ['evil"', "a\r\nAT+CFUN=0", "line\nbreak", "café", "x" * 300]


@pytest.mark.parametrize("value", BAD_TEXT)
def test_apn_ping_and_dns_values_are_checked_before_anything_is_sent(manager, value):
    manager.ser = FakeSerial({})
    for call in (lambda: manager.set_apn(value), lambda: manager.set_apn("ok", value),
                 lambda: manager.run_ping_benchmark(value, 1), lambda: manager.run_dns_query(value)):
        with pytest.raises(ValueError):
            call()
    assert manager.ser.sent == []


@pytest.mark.parametrize("cid", [-1, 16, True, "1"])
def test_context_id_is_bounded(manager, cid):
    manager.ser = FakeSerial({})
    with pytest.raises(ValueError):
        manager.set_apn("internet", "IP", cid)
    assert manager.ser.sent == []


@pytest.mark.parametrize("t3412,t3324", [("1010010", "00100100"), ("10100101", '0010010"'), ("abcdefgh", "00100100")])
def test_psm_timers_must_be_eight_bits(manager, t3412, t3324):
    manager.ser = FakeSerial({})
    with pytest.raises(ValueError):
        manager.set_psm_config(True, t3412, t3324)
    assert manager.ser.sent == []


@pytest.mark.parametrize("value", ["001", "00100", '00"0', "abcd"])
def test_edrx_value_must_be_four_bits(manager, value):
    manager.ser = FakeSerial({})
    with pytest.raises(ValueError):
        manager.set_edrx_config(True, value)
    assert manager.ser.sent == []


def test_demo_ping_count_is_clamped(manager, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    manager.is_demo = True
    assert manager.run_ping_benchmark("8.8.8.8", 1_000_000)["sent"] == 10


def test_valid_values_still_work(manager):
    manager.ser = FakeSerial({})
    manager.set_apn("iot.example", "IP", 0)
    assert manager.ser.sent[0] == 'AT+CGDCONT=0,"IP","iot.example"'


# --- #119 eDRX -----------------------------------------------------------------

def test_edrx_rejected_by_the_module_is_not_reported_as_enabled(manager):
    manager.ser = FakeSerial({'AT+CEDRXS=1,5,"0010"': "\r\nERROR\r\n"})
    resp = manager.set_edrx_config(True, "0010")
    assert not manager.is_ok(resp)
    assert manager.state["edrx_info"]["enabled"] is False
    assert "failed" in manager.state["edrx_info"]["status"]


def test_edrx_success_keeps_the_granted_fields(manager):
    manager.state["edrx_info"]["granted_text"] = "20.48 s cycle"
    manager.ser = FakeSerial({})
    manager.set_edrx_config(True, "0011")
    info = manager.state["edrx_info"]
    assert info["enabled"] is True and info["value"] == "0011"
    assert info["granted_text"] == "20.48 s cycle"
    for key in ("granted", "requested_text", "mismatch"):
        assert key in info


# --- #120 scan -----------------------------------------------------------------

def test_two_quick_scan_requests_start_one_scan(manager, monkeypatch):
    sent, release = [], threading.Event()

    def slow_send(cmd, timeout_sec=None, wait_for=None, retries=0):
        sent.append(cmd)
        release.wait(5)
        return "\r\nOK\r\n"

    monkeypatch.setattr(manager, "_send_at_cmd_raw", slow_send)
    manager.trigger_async_cops_scan()
    manager.trigger_async_cops_scan()
    assert wait_until(lambda: sent)
    release.set()
    assert wait_until(lambda: not manager.state["is_scanning"])
    assert sent == ["AT+COPS=?"]


def test_a_failing_scan_does_not_stay_scanning(manager, monkeypatch):
    manager.ser = FakeSerial({})

    def boom(resp):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(manager, "_parse_cops_scan", boom)
    manager.trigger_async_cops_scan()
    assert wait_until(lambda: not manager.state["is_scanning"])
    assert "parser exploded" in manager.state["scan_error"]
    manager.trigger_async_cops_scan()  # and a later scan can still start
    assert wait_until(lambda: not manager.state["is_scanning"])


# --- #121 demo loop ------------------------------------------------------------

def test_demo_loop_survives_a_history_error(manager, monkeypatch):
    calls = []

    def flaky():
        calls.append(1)
        raise RuntimeError("database is locked")

    monkeypatch.setattr(manager, "_log_history", flaky)
    manager.telemetry_interval = 1
    manager.enable_demo_mode()
    try:
        assert wait_until(lambda: calls)
        assert manager.poll_thread.is_alive()
    finally:
        manager.disconnect()


# --- API: bad input is a 422 ---------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setattr(sys, "argv", ["server.py", "--no-file-log"])
    monkeypatch.setenv("QUECTEL_DASHBOARD_DB", str(tmp_path / "api.db"))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="http://localhost:8080") as client:
        yield server, client


def test_api_answers_422_for_values_that_could_break_a_command(api):
    _, client = api
    assert client.post("/api/ping", json={"host": 'a"b'}).status_code == 422
    assert client.post("/api/dns", json={"domain": "a\r\nAT"}).status_code == 422
    assert client.post("/api/psm", json={"enabled": True, "t3412": "1", "t3324": "00100100"}).status_code == 422
    assert client.post("/api/edrx", json={"enabled": True, "edrx_val": "9"}).status_code == 422


def test_api_reports_a_rejected_edrx_setting_as_502(api):
    server, client = api
    server.manager.ser = FakeSerial({'AT+CEDRXS=1,5,"0010"': "\r\nERROR\r\n"})
    assert client.post("/api/edrx", json={"enabled": True, "edrx_val": "0010"}).status_code == 502


# --- #126 webhook redirects ----------------------------------------------------

def test_webhook_does_not_follow_redirects_with_the_token():
    seen = {}

    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen["auth"] = self.headers.get("Authorization")
            self.send_response(200)
            self.end_headers()

        do_POST = do_GET

        def log_message(self, *args):
            pass

    target = http.server.HTTPServer(("127.0.0.1", 0), Target)

    class Redirect(Target):
        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/stolen")
            self.end_headers()

    redirect = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
    for srv in (target, redirect):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(OSError):
            exporter.send_webhook(f"http://127.0.0.1:{redirect.server_port}/hook", {"a": 1}, token="SECRET")
        assert "auth" not in seen
    finally:
        target.shutdown()
        redirect.shutdown()
