"""Tests for the per-command timeout table and its users."""
import pytest

import serial_manager
from serial_manager import timeout_for
from tests.fake_serial import FakeSerial
from tests.pty_modem import PtyModem


@pytest.mark.parametrize("cmd,expected", [
    ("AT+CSQ", 5.0),
    ("at+cesq", 5.0),
    ("AT+CGPADDR=1", 5.0),
    ("ATI", 5.0),
    ("AT+CGMR", 5.0),
    ("AT+CGSN=1", 5.0),
    ('AT+QENG="servingcell"', 15.0),
    ("AT+QENG=0", 15.0),
    ("AT+CGATT=1", 70.0),
    ("AT+COPS=?", 35.0),
    ("AT+CGATT?", serial_manager.DEFAULT_AT_TIMEOUT),
    ("AT+UNKNOWN", serial_manager.DEFAULT_AT_TIMEOUT),
])
def test_timeout_table(cmd, expected):
    assert timeout_for(cmd) == expected


def test_none_of_the_documented_commands_is_below_its_maximum():
    """Regression test for #26: everything used a flat 2 s."""
    assert min(seconds for _, seconds in serial_manager.AT_TIMEOUTS) >= 5.0


def test_default_timeout_comes_from_the_table(manager, monkeypatch):
    monkeypatch.setattr(serial_manager, "AT_TIMEOUTS", (("AT+CSQ", 1.5),))
    modem = PtyModem({"AT+CSQ": (0.8, "\r\n+CSQ: 14,0\r\n\r\nOK\r\n")})
    manager.ser = modem.start()
    try:
        assert "+CSQ: 14,0" in manager._send_at_cmd_raw("AT+CSQ")
    finally:
        modem.close()


def test_console_commands_get_a_generous_default(monkeypatch, manager):
    seen = {}

    def fake_raw(cmd, timeout_sec=None):
        seen["timeout"] = timeout_sec
        return "OK"

    monkeypatch.setattr(manager, "_send_at_cmd_raw", fake_raw)
    manager.send_at_command("AT+SOMETHINGNEW")
    assert seen["timeout"] == 30.0


def test_poll_cycle_stops_at_first_timeout(manager, monkeypatch):
    monkeypatch.setattr(serial_manager, "AT_TIMEOUTS", (("AT+CSQ", 0.2),))
    manager.running = True
    manager._hardware_info_loaded = True
    manager.ser = FakeSerial({"AT+CSQ": ""})

    manager._poll_once()

    assert manager.ser.sent == ["AT+CSQ"]


def test_set_apn_waits_for_attach(manager, monkeypatch):
    monkeypatch.setattr(manager, "ATTACH_CHECK_INTERVAL", 0)
    manager.ser = FakeSerial({
        "AT+CGATT?": ["\r\n+CGATT: 0\r\n\r\nOK\r\n", "\r\n+CGATT: 0\r\n\r\nOK\r\n", "\r\n+CGATT: 1\r\n\r\nOK\r\n"],
    })

    manager.set_apn("iot.example", "IP", 1)

    assert manager.state["apn_info"]["attached"] is True
    assert manager.ser.sent.count("AT+CGATT?") == 3
