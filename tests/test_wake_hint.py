"""Tests for the RESET reminder and the connect-time probe (#15)."""
import time

import pytest

import serial_manager
from tests.fake_serial import FakeSerial
from tests.pty_modem import PtyModem


def _hint_lines(manager):
    return [e for e in manager.state["logs"] if e["text"].startswith("[HINT]")]


@pytest.fixture
def silent_modem(manager, monkeypatch):
    """A modem that never answers, with short probe timeouts."""
    monkeypatch.setattr(manager, "PROBE_TIMEOUT", 0.1)
    modem = PtyModem({"AT": (0.0, "")})  # empty reply: silence
    manager.ser = modem.start()
    yield manager
    modem.close()


def test_hint_is_logged_once_when_the_modem_is_silent(silent_modem):
    silent_modem._send_at_cmd_raw("AT", timeout_sec=0.1)
    silent_modem._send_at_cmd_raw("AT", timeout_sec=0.1)

    hints = _hint_lines(silent_modem)
    assert len(hints) == 1
    assert "press the RESET button" in hints[0]["text"]
    assert silent_modem.state["modem_responding"] is False


def test_probe_fails_fast_on_a_silent_modem(silent_modem):
    start = time.time()
    assert silent_modem._probe_modem() is False
    assert time.time() - start < 3
    assert len(_hint_lines(silent_modem)) == 1


def test_probe_succeeds_when_the_first_try_is_lost(manager, monkeypatch):
    """A module waking from sleep can lose the first character."""
    monkeypatch.setattr(manager, "PROBE_TIMEOUT", 0.1)
    manager.ser = FakeSerial({"AT": ["", "\r\nOK\r\n"]})

    assert manager._probe_modem() is True
    assert manager.state["modem_responding"] is True


def test_connect_skips_the_long_startup_when_the_modem_is_silent(manager, monkeypatch):
    monkeypatch.setattr(manager, "PROBE_TIMEOUT", 0.1)
    modem = PtyModem({"AT": (0.0, "")})
    client = modem.start()
    monkeypatch.setattr(serial_manager.serial, "Serial", lambda *a, **k: client)
    try:
        start = time.time()
        assert manager.connect(modem.slave_name, 115200) is True
        assert time.time() - start < 3, "connect blocked on the full start-up sequence"
        assert set(modem.received) == {"AT"}
        assert manager._hardware_info_loaded is False
    finally:
        manager.disconnect()
        modem.close()


def test_polling_backs_off_to_a_probe_until_the_modem_answers(manager, monkeypatch):
    monkeypatch.setattr(manager, "PROBE_TIMEOUT", 0.1)
    manager.running = True
    manager.ser = FakeSerial({"AT": ["", "", "\r\nOK\r\n"]})

    manager._poll_once()
    manager._poll_once()
    assert manager.ser.sent == ["AT", "AT"]  # nothing else is sent while silent

    manager._poll_once()
    assert manager._hardware_info_loaded is True
    assert "ATI" in manager.ser.sent and "AT+CSQ" in manager.ser.sent


def test_hint_returns_after_the_modem_answers_and_goes_quiet_again(manager):
    manager.ser = FakeSerial({"AT": ["", "\r\nOK\r\n", ""]})
    manager._send_at_cmd_raw("AT", timeout_sec=0.1)
    manager._send_at_cmd_raw("AT", timeout_sec=0.1)
    manager._send_at_cmd_raw("AT", timeout_sec=0.1)
    assert len(_hint_lines(manager)) == 2
