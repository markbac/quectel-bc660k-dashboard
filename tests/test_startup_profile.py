"""Tests for the start-up profile (#34)."""
import pytest

from tests.fake_serial import FakeSerial


def full_modem():
    return FakeSerial({
        "ATI": "\r\nQuectel_Ltd\r\nQuectel_BC660K-GL\r\nRevision: BC660KGLAAR01A05\r\n\r\nOK\r\n",
        "AT+CGSN=1": "\r\n+CGSN: 860000000000000\r\n\r\nOK\r\n",
        "AT+CPIN?": "\r\n+CPIN: READY\r\n\r\nOK\r\n",
        "AT+QCCID": "\r\n+QCCID: 89000000000000000001\r\n\r\nOK\r\n",
        "AT+CIMI": "\r\n001010000000001\r\n\r\nOK\r\n",
        "AT+CPSMS?": '\r\n+CPSMS: 1,,,"01000010","00000010"\r\n\r\nOK\r\n',
        "AT+CEDRXS?": '\r\n+CEDRXS: 5,"0010"\r\n\r\nOK\r\n',
        "AT+QSCLK?": "\r\n+QSCLK: 1\r\n\r\nOK\r\n",
    })


def test_profile_reads_the_real_modem_state(manager):
    manager.ser = full_modem()

    manager._poll_hardware_info()

    assert manager.ser.sent[0] == "ATE0"
    assert manager.state["psm_info"]["enabled"] is True
    assert manager.state["psm_info"]["t3412"] == "01000010"
    assert manager.state["psm_info"]["t3324"] == "00000010"
    assert manager.state["edrx_info"]["enabled"] is True
    assert manager.state["edrx_info"]["value"] == "0010"
    assert manager.state["system_info"]["sleep_clock"] == 1
    assert manager.state["sim_info"]["iccid"] == "89000000000000000001"
    assert manager.state["system_info"]["imei"] == "860000000000000"


def test_profile_does_not_assume_psm_is_off(manager):
    """The UI used to show 'PSM Disabled' whatever the module was set to."""
    manager.ser = full_modem()
    assert manager.state["psm_info"]["enabled"] is False  # the placeholder
    manager._poll_hardware_info()
    assert manager.state["psm_info"]["status"] == "PSM Enabled"


def test_unsupported_commands_leave_placeholders(manager):
    manager.ser = FakeSerial({
        "AT+CPSMS?": "\r\nERROR\r\n",
        "AT+CEDRXS?": "\r\nERROR\r\n",
        "AT+QSCLK?": "\r\nERROR\r\n",
    })

    manager._poll_hardware_info()

    assert manager.state["psm_info"]["enabled"] is False
    assert manager.state["edrx_info"]["enabled"] is False
    assert manager.state["system_info"]["sleep_clock"] is None


def test_cgmr_is_used_only_when_ati_has_no_revision(manager):
    manager.ser = FakeSerial({
        "ATI": "\r\nOK\r\n",
        "AT+CGMR": "\r\nBC660KGLAAR01A05\r\n\r\nOK\r\n",
    })
    manager._poll_hardware_info()
    assert manager.state["system_info"]["firmware"] == "BC660KGLAAR01A05"

    manager.state["system_info"]["firmware"] = "FROM-ATI"
    manager._parse_cgmr("\r\nOTHER\r\n\r\nOK\r\n")
    assert manager.state["system_info"]["firmware"] == "FROM-ATI"


@pytest.mark.parametrize("resp,enabled,value", [
    ('\r\n+CEDRXS: 5,"0101"\r\n\r\nOK\r\n', True, "0101"),
    ("\r\nOK\r\n", False, "0010"),
    ("\r\nERROR\r\n", False, "0010"),
])
def test_parse_cedrxs(manager, resp, enabled, value):
    manager._parse_cedrxs(resp)
    assert manager.state["edrx_info"]["enabled"] is enabled
    assert manager.state["edrx_info"]["value"] == value
