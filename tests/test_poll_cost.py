"""Tests for the poll cycle cost (#31)."""
import pytest

from tests.fake_serial import FakeSerial

QENG = '\r\n+QENG: 0,6300,0,320,"01D2F401",-95,-11,-85,12,8,"5F4E",0,23,0\r\n\r\nOK\r\n'


@pytest.fixture
def polling(manager):
    manager.running = True
    manager._hardware_info_loaded = True
    manager.ser = FakeSerial({"AT+QENG=0": QENG})
    return manager


def test_first_cycle_reads_everything_then_only_the_fast_items(polling):
    polling._poll_once()
    assert set(polling.ser.sent) >= {"AT+CSQ", "AT+QENG=0", "AT+COPS?", "AT+CEREG?", "AT+CBC"}

    polling.ser.sent.clear()
    polling._poll_once()

    assert polling.ser.sent == ["AT+CSQ", "AT+QENG=0"]


def test_slow_items_come_back_when_their_interval_has_passed(polling):
    polling._poll_once()
    polling.ser.sent.clear()
    for cmd in ("AT+COPS?", "AT+CBC"):
        polling._last_slow_run[cmd] -= 31

    polling._poll_once()

    assert "AT+COPS?" in polling.ser.sent and "AT+CBC" in polling.ser.sent
    assert "AT+CEREG?" not in polling.ser.sent  # its interval is 60 s


def test_cesq_is_only_a_fallback_for_a_missing_rsrp(polling):
    polling._poll_once()
    assert "AT+CESQ" not in polling.ser.sent  # QENG supplied the RSRP

    polling.ser.sent.clear()
    polling.state["signal"]["rsrp"] = None
    polling.ser.responses["AT+QENG=0"] = "\r\nOK\r\n"
    polling.ser.responses["AT+CESQ"] = "\r\n+CESQ: 99,99,255,255,12,50\r\n\r\nOK\r\n"
    polling._poll_once()

    assert "AT+CESQ" in polling.ser.sent
    assert polling.state["signal"]["rsrp"] == -91


def test_steady_state_cycle_is_two_commands_not_nine(polling):
    polling._poll_once()
    polling.ser.sent.clear()
    polling._poll_once()
    assert len(polling.ser.sent) == 2


def test_a_timed_out_slow_item_is_retried_next_cycle(polling):
    polling.ser.responses["AT+COPS?"] = ""
    polling._poll_once()  # COPS times out and ends the cycle
    assert "AT+COPS?" not in polling._last_slow_run


# --- CEREG URCs ----------------------------------------------------------------

def test_cereg_urc_updates_registration_without_polling(manager):
    manager._handle_urc('+CEREG: 1,"5F4E","01D2F401",9')
    assert manager.state["connectivity_status"] == "Network: Registered, home network"
    assert manager.state["serving_cell"]["tac"] == "5F4E"
    assert manager.state["serving_cell"]["cell_id_dec"] == 0x01D2F401


def test_cereg_urc_with_only_a_status(manager):
    manager._handle_urc("+CEREG: 2")
    assert manager.state["connectivity_status"] == "Network: Not registered, searching..."


def test_cereg_urc_carries_the_granted_timers(manager):
    manager.state["psm_info"].update({"enabled": True})
    manager._handle_urc('+CEREG: 5,"5F4E","01D2F401",9,,,"00100100","10100101"')
    assert manager.state["psm_info"]["granted"] == {"t3324": "00100100", "t3412": "10100101"}


def test_cereg_query_reply_is_not_mistaken_for_a_urc(manager):
    manager._handle_urc('+CEREG: 2,1,"5F4E","01D2F401",9')
    assert manager.state["connectivity_status"] != "Network: Registered, home network"


def test_cereg_urc_in_idle_input_is_applied_by_the_next_poll(polling):
    polling.ser._buffer = b'\r\n+CEREG: 5,"5F4E","01D2F401",9\r\n'
    polling._poll_once()
    assert polling.state["connectivity_status"] == "Network: Registered, roaming"
