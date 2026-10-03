"""Tests for set_apn() and the CGPADDR parser."""
from tests.fake_serial import FakeSerial


def test_set_apn_updates_state_from_modem(manager):
    """Regression test for #12: set_apn() used an undefined parser."""
    manager.ser = FakeSerial({
        "AT+CGPADDR=2": '\r\n+CGPADDR: 2,"10.20.30.40"\r\n\r\nOK\r\n',
        "AT+CGDCONT?": '\r\n+CGDCONT: 2,"IP","iot.example","0.0.0.0",0,0,0,0\r\n\r\nOK\r\n',
        "AT+CGATT?": "\r\n+CGATT: 1\r\n\r\nOK\r\n",
    })

    manager.set_apn("iot.example", "IP", 2)

    assert manager.state["system_info"]["ip_address"] == "10.20.30.40"
    assert manager.state["apn_info"]["apn"] == "iot.example"
    assert manager.state["apn_info"]["pdp_cid"] == 2
    assert manager.state["apn_info"]["attached"] is True
    assert 'AT+CGDCONT=2,"IP","iot.example"' in manager.ser.sent


def test_parse_cgpaddr_ignores_missing_address(manager):
    manager._parse_cgpaddr("\r\n+CGPADDR: 1\r\n\r\nOK\r\n")
    assert manager.state["system_info"]["ip_address"] == "--"


REAL_CGDCONT = '\r\n+CGDCONT: 0,"IP","test.apn","10.0.0.7"\r\n\r\nOK\r\n'


def test_real_board_context_zero_is_used_for_the_ip_address(manager):
    """Regression test for #84: AT+CGPADDR=1 answered without an address on a real board."""
    manager.ser = FakeSerial({
        "AT+CGDCONT?": REAL_CGDCONT,
        "AT+CGPADDR=0": '\r\n+CGPADDR: 0,"10.0.0.7"\r\n\r\nOK\r\n',
        "AT+CGPADDR=1": "\r\n+CGPADDR: 1\r\n\r\nOK\r\n",
    })
    manager._poll_hardware_info()

    assert "AT+CGPADDR=0" in manager.ser.sent
    assert "AT+CGPADDR=1" not in manager.ser.sent
    assert manager.state["apn_info"]["pdp_cid"] == 0
    assert manager.state["system_info"]["ip_address"] == "10.0.0.7"


def test_cgdcont_address_is_a_fallback_for_the_ip(manager):
    manager._parse_cgdcont(REAL_CGDCONT)
    assert manager.state["system_info"]["ip_address"] == "10.0.0.7"
    assert manager.state["apn_info"]["apn"] == "test.apn"


def test_unassigned_cgdcont_address_is_ignored(manager):
    manager._parse_cgdcont('\r\n+CGDCONT: 1,"IP","iot","0.0.0.0",0,0,0,0\r\n\r\nOK\r\n')
    assert manager.state["system_info"]["ip_address"] == "--"
