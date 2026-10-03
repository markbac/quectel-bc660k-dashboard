"""Tests for requested versus network-granted PSM/eDRX values (#35)."""
import pytest

import timers
from tests.fake_serial import FakeSerial


@pytest.mark.parametrize("bits,seconds", [
    ("10100101", 300),      # unit 1 minute, value 5
    ("00100001", 3600),     # 1 hour x 1
    ("00000001", 600),      # 10 minutes x 1
    ("01100101", 10),       # 2 seconds x 5
    ("10000100", 120),      # 30 seconds x 4
    ("11000001", 1152000),  # 320 hours x 1
    ("11100000", None),     # deactivated
    ("1010010", None),      # wrong length
    ("1010010x", None),     # not binary
])
def test_decode_t3412(bits, seconds):
    assert timers.decode_t3412(bits) == seconds


@pytest.mark.parametrize("bits,seconds", [
    ("00100100", 240),      # unit 1 minute, value 4
    ("00000011", 6),        # 2 seconds x 3
    ("01000010", 720),      # 6 minutes x 2
    ("11100000", None),     # deactivated
])
def test_decode_t3324(bits, seconds):
    assert timers.decode_t3324(bits) == seconds


@pytest.mark.parametrize("seconds,text", [
    (None, "off"), (0, "0 s"), (45, "45 s"), (300, "5 min"), (3600, "1 h"),
    (9000, "2 h 30 min"), (20.48, "20.48 s"),
])
def test_format_duration(seconds, text):
    assert timers.format_duration(seconds) == text


def test_edrx_cycle_lookup():
    assert timers.decode_edrx_cycle("0010") == 20.48
    assert timers.decode_edrx_cycle("1111") is None


def _enable_psm(manager, t3412="10100101", t3324="00100100"):
    manager.state["psm_info"].update({"enabled": True, "t3412": t3412, "t3324": t3324})
    manager._update_psm_text()


def test_extended_cereg_supplies_the_granted_timers(manager):
    _enable_psm(manager)

    manager._parse_cereg_query('\r\n+CEREG: 4,1,"5F4E","01D2F401",9,,,"00100100","10100101"\r\n\r\nOK\r\n')

    info = manager.state["psm_info"]
    assert info["granted"] == {"t3324": "00100100", "t3412": "10100101"}
    assert info["granted_text"] == "T3412 5 min, T3324 4 min"
    assert info["requested_text"] == "T3412 5 min, T3324 4 min"
    assert info["mismatch"] is False


def test_a_different_grant_is_flagged(manager):
    _enable_psm(manager)

    manager._parse_cereg_query('\r\n+CEREG: 4,1,"5F4E","01D2F401",9,,,"00000011","00100001"\r\n\r\nOK\r\n')

    info = manager.state["psm_info"]
    assert info["granted_text"] == "T3412 1 h, T3324 6 s"
    assert info["mismatch"] is True


def test_cell_id_made_of_zeros_and_ones_is_not_mistaken_for_a_timer(manager):
    manager._parse_cereg_query('\r\n+CEREG: 2,1,"5F4E","01000010",9\r\n\r\nOK\r\n')
    assert manager.state["psm_info"]["granted"] == {"t3412": None, "t3324": None}


def test_no_grant_reported_is_not_a_mismatch(manager):
    _enable_psm(manager)
    manager._parse_cereg_query('\r\n+CEREG: 2,1,"5F4E","01D2F401",9\r\n\r\nOK\r\n')
    assert manager.state["psm_info"]["granted_text"] == "Not reported"
    assert manager.state["psm_info"]["mismatch"] is False


def test_requested_text_follows_the_module_readback(manager):
    manager._parse_cpsms('\r\n+CPSMS: 1,,,"00100001","00100010"\r\n\r\nOK\r\n')
    assert manager.state["psm_info"]["requested_text"] == "T3412 1 h, T3324 2 min"
    manager._parse_cpsms('\r\n+CPSMS: 0\r\n\r\nOK\r\n')
    assert manager.state["psm_info"]["requested_text"] == "PSM off"


def test_edrx_granted_value_is_decoded_and_compared(manager):
    manager._parse_cedrxrdp('\r\n+CEDRXRDP: 5,"0010","0011","0101"\r\n\r\nOK\r\n')
    info = manager.state["edrx_info"]
    assert info["requested_text"] == "20.48 s cycle"
    assert info["granted_text"] == "40.96 s cycle"
    assert info["mismatch"] is True


def test_edrx_not_in_use_is_not_reported(manager):
    manager._parse_cedrxrdp("\r\n+CEDRXRDP: 0\r\n\r\nOK\r\n")
    assert manager.state["edrx_info"]["granted_text"] == "Not reported"


def test_profile_enables_extended_cereg_and_reads_edrx(manager):
    manager.ser = FakeSerial({})
    manager._poll_hardware_info()
    assert "AT+CEREG=4" in manager.ser.sent
    assert "AT+CEDRXRDP" in manager.ser.sent


def test_demo_psm_update_keeps_the_text_fields(manager):
    manager.enable_demo_mode()
    try:
        manager.set_psm_config(True, "10100101", "00100100")
        assert manager.state["psm_info"]["requested_text"] == "T3412 5 min, T3324 4 min"
    finally:
        manager.disconnect()
