"""Tests for the modem state machine (#32)."""
import pytest

import serial_manager
from serial_manager import (
    MODEM_AWAKE, MODEM_DEEP_SLEEP, MODEM_DISCONNECTED, MODEM_PROBING, MODEM_PSM, MODEM_UNRESPONSIVE,
)
from tests.fake_serial import FakeSerial
from tests.test_startup_profile import full_modem


def _states(manager):
    return [e["text"] for e in manager.state["logs"] if e["text"].startswith("[MODEM STATE]")]


@pytest.fixture
def connected(manager, monkeypatch):
    """A manager that has opened its port and is probing."""
    monkeypatch.setattr(manager, "PROBE_TIMEOUT", 0.1)
    manager.state["modem_state"] = MODEM_PROBING
    manager.running = True
    return manager


def test_initial_state_is_disconnected(manager):
    assert manager.state["modem_state"] == MODEM_DISCONNECTED


def test_first_answer_moves_probing_to_awake(connected):
    connected.ser = FakeSerial({})
    connected._send_at_cmd_raw("AT")
    assert connected.state["modem_state"] == MODEM_AWAKE


def test_silence_after_working_is_unresponsive(connected):
    connected.ser = FakeSerial({"AT": ["\r\nOK\r\n", ""]})
    connected._send_at_cmd_raw("AT", timeout_sec=0.1)
    connected._send_at_cmd_raw("AT", timeout_sec=0.1)
    assert connected.state["modem_state"] == MODEM_UNRESPONSIVE


def test_never_answering_stays_probing(connected):
    connected.ser = FakeSerial({"AT": ""})
    connected._send_at_cmd_raw("AT", timeout_sec=0.1)
    assert connected.state["modem_state"] == MODEM_PROBING


@pytest.mark.parametrize("event,expected", [
    ("ENTER PSM", MODEM_PSM),
    ("ENTER DEEPSLEEP", MODEM_DEEP_SLEEP),
])
def test_qnbiotevent_urc_sets_the_sleep_state(connected, event, expected):
    connected._handle_urc(f'+QNBIOTEVENT: "{event}"')
    assert connected.state["modem_state"] == expected
    assert connected._hardware_info_loaded is False


def test_exit_events_return_to_awake(connected):
    connected._handle_urc('+QNBIOTEVENT: "ENTER PSM"')
    connected._handle_urc('+QNBIOTEVENT: "EXIT PSM"')
    assert connected.state["modem_state"] == MODEM_AWAKE
    connected._handle_urc('+QNBIOTEVENT: "ENTER DEEPSLEEP"')
    connected._handle_urc('+QNBIOTEVENT: "EXIT DEEPSLEEP"')
    assert connected.state["modem_state"] == MODEM_AWAKE


def test_unknown_events_and_other_urcs_are_ignored(connected):
    connected._handle_urc('+QNBIOTEVENT: "SOMETHING ELSE"')
    connected._handle_urc("+CSCON: 1")
    assert connected.state["modem_state"] == MODEM_PROBING


def test_urc_after_the_answer_wins_because_the_module_then_goes_quiet(connected):
    connected.ser = FakeSerial({"AT+CSQ": '\r\n+QNBIOTEVENT: "ENTER PSM"\r\n+CSQ: 14,0\r\n\r\nOK\r\n'})
    resp = connected._send_at_cmd_raw("AT+CSQ")
    assert "+CSQ: 14,0" in resp
    # The module answered and then announced PSM, so it is about to go quiet.
    assert connected.state["modem_state"] == MODEM_PSM


def test_idle_urc_between_polls_is_noticed(connected):
    connected._hardware_info_loaded = True
    connected.state["modem_state"] = MODEM_AWAKE
    connected.ser = FakeSerial({"AT": ""})
    connected.ser._buffer = b'\r\n+QNBIOTEVENT: "ENTER PSM"\r\n'

    connected._poll_once()

    assert connected.state["modem_state"] == MODEM_PSM
    assert connected.ser.sent == ["AT"]  # only a probe, no polling into a sleeping module


def test_waking_up_reruns_the_startup_profile(connected):
    connected.ser = full_modem()
    connected._hardware_info_loaded = True
    connected.state["modem_state"] = MODEM_AWAKE
    connected._handle_urc('+QNBIOTEVENT: "ENTER DEEPSLEEP"')

    connected._poll_once()  # the module answers the probe

    assert connected.state["modem_state"] == MODEM_AWAKE
    assert connected._hardware_info_loaded is True
    assert "ATE0" in connected.ser.sent
    assert "AT+CSQ" in connected.ser.sent


def test_startup_profile_enables_sleep_events(manager):
    manager.ser = full_modem()
    manager._poll_hardware_info()
    assert "AT+QNBIOTEVENT=1,1" in manager.ser.sent
    assert 'AT+QCFG="dsevent",1' in manager.ser.sent
    assert manager.state["sleep_events"] is True


def test_sleep_events_flag_is_false_when_unsupported(manager):
    manager.ser = FakeSerial({"AT+QNBIOTEVENT=1,1": "\r\nERROR\r\n"})
    manager._poll_hardware_info()
    assert manager.state["sleep_events"] is False


def test_enabling_psm_logs_a_warning(manager):
    manager.ser = FakeSerial({"AT+CPSMS?": '\r\n+CPSMS: 1,,,"01000010","00000010"\r\n\r\nOK\r\n'})
    manager.set_psm_config(True)
    assert any("[PSM WARNING]" in e["text"] for e in manager.state["logs"])


def test_state_change_is_logged_once(connected):
    connected._set_modem_state(MODEM_AWAKE)
    connected._set_modem_state(MODEM_AWAKE)
    assert _states(connected) == [f"[MODEM STATE] {MODEM_PROBING} -> {MODEM_AWAKE}"]
