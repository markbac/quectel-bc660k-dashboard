"""Tests for the identity/status parsers and the connect-time hardware query."""
import pytest

from tests.fake_serial import FakeSerial


@pytest.mark.parametrize("resp,expected", [
    ("Quectel_Ltd\r\nQuectel_BC660K-GL\r\nRevision: BC660KGLAAR01A05\r\n\r\nOK\r\n", "BC660KGLAAR01A05"),
    ("OK\r\n", "--"),
])
def test_parse_ati_firmware(manager, resp, expected):
    manager._parse_ati(resp)
    assert manager.state["system_info"]["firmware"] == expected


@pytest.mark.parametrize("resp,expected", [
    ("\r\n+CPIN: READY\r\n\r\nOK\r\n", "READY"),
    ("\r\n+CPIN: SIM PIN\r\n\r\nOK\r\n", "SIM PIN"),
    ("\r\n+CME ERROR: 10\r\n", "NOT INSERTED"),
    ("ERROR: Timeout", "AWAITING MODEM"),
])
def test_parse_cpin(manager, resp, expected):
    manager._parse_cpin(resp)
    assert manager.state["sim_info"]["sim_status"] == expected


@pytest.mark.parametrize("resp", [
    '\r\n+CGSN: 860000000000000\r\n\r\nOK\r\n',
    "\r\n860000000000000\r\n\r\nOK\r\n",
])
def test_parse_imei(manager, resp):
    manager._parse_imei(resp)
    assert manager.state["system_info"]["imei"] == "860000000000000"


@pytest.mark.parametrize("resp,expected", [
    ("\r\n+QTEMP: 31\r\n\r\nOK\r\n", 31),
    ("\r\n+QTEMP: 0,-4\r\n\r\nOK\r\n", -4),
    ("\r\nERROR\r\n", None),
])
def test_parse_qtemp(manager, resp, expected):
    manager._parse_qtemp(resp)
    assert manager.state["system_info"]["temperature"] == expected


def test_poll_hardware_info_populates_fields(manager):
    manager.ser = FakeSerial({
        "ATI": "\r\nQuectel_Ltd\r\nQuectel_BC660K-GL\r\nRevision: BC660KGLAAR01A05\r\n\r\nOK\r\n",
        "AT+CPIN?": "\r\n+CPIN: READY\r\n\r\nOK\r\n",
        "AT+CGSN=1": "\r\n+CGSN: 860000000000000\r\n\r\nOK\r\n",
        "AT+QTEMP": "\r\n+QTEMP: 29\r\n\r\nOK\r\n",
        "AT+CGPADDR=1": '\r\n+CGPADDR: 1,"10.1.2.3"\r\n\r\nOK\r\n',
    })
    manager._poll_hardware_info()

    sys_info = manager.state["system_info"]
    assert sys_info["firmware"] == "BC660KGLAAR01A05"
    assert sys_info["imei"] == "860000000000000"
    assert sys_info["temperature"] == 29
    assert sys_info["ip_address"] == "10.1.2.3"
    assert manager.state["sim_info"]["sim_status"] == "READY"
    assert manager._temp_supported is True


def test_unsupported_qtemp_is_not_polled_again(manager):
    manager.ser = FakeSerial({"AT+QTEMP": "\r\nERROR\r\n"})
    manager._poll_hardware_info()
    assert manager._temp_supported is False
    assert manager.state["system_info"]["temperature"] is None
