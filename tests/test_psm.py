"""Tests for PSM configuration."""
from tests.fake_serial import FakeSerial

OK = "\r\nOK\r\n"
READ_5 = '\r\n+CPSMS: 1,,,"10100101","00100100"\r\n\r\nOK\r\n'


def test_five_field_form_is_tried_first(manager):
    manager.ser = FakeSerial({"AT+CPSMS?": READ_5})

    manager.set_psm_config(True, "10100101", "00100100")

    assert manager.ser.sent[0] == 'AT+CPSMS=1,,,"10100101","00100100"'
    assert manager.ser.sent[-1] == "AT+CPSMS?"
    assert manager.state["psm_info"]["enabled"] is True
    assert manager.state["psm_info"]["status"] == "PSM Enabled"


def test_falls_back_to_the_three_field_form(manager):
    manager.ser = FakeSerial({
        'AT+CPSMS=1,,,"10100101","00100100"': "\r\nERROR\r\n",
        "AT+CPSMS?": '\r\n+CPSMS: 1,"10100101","00100100"\r\n\r\nOK\r\n',
    })

    resp = manager.set_psm_config(True, "10100101", "00100100")

    assert manager.is_ok(resp)
    assert 'AT+CPSMS=1,"10100101","00100100"' in manager.ser.sent
    assert manager.state["psm_info"]["enabled"] is True


def test_rejected_command_does_not_claim_psm_is_enabled(manager):
    """Regression test for #30: the result used to be ignored."""
    manager.ser = FakeSerial({
        'AT+CPSMS=1,,,"10100101","00100100"': "\r\nERROR\r\n",
        'AT+CPSMS=1,"10100101","00100100"': "\r\nERROR\r\n",
    })

    resp = manager.set_psm_config(True, "10100101", "00100100")

    assert not manager.is_ok(resp)
    assert manager.state["psm_info"]["enabled"] is False
    assert manager.state["psm_info"]["status"].startswith("PSM command failed")


def test_state_reflects_the_module_readback_not_the_request(manager):
    manager.ser = FakeSerial({"AT+CPSMS?": '\r\n+CPSMS: 1,,,"01000010","00000010"\r\n\r\nOK\r\n'})

    manager.set_psm_config(True, "10100101", "00100100")

    assert manager.state["psm_info"]["t3412"] == "01000010"
    assert manager.state["psm_info"]["t3324"] == "00000010"


def test_disable_uses_a_single_field_and_reads_back(manager):
    manager.ser = FakeSerial({"AT+CPSMS?": "\r\n+CPSMS: 0,,,\"00000000\",\"00000000\"\r\n\r\nOK\r\n"})
    manager.state["psm_info"]["enabled"] = True

    manager.set_psm_config(False)

    assert manager.ser.sent[0] == "AT+CPSMS=0"
    assert manager.state["psm_info"]["enabled"] is False
    assert manager.state["psm_info"]["status"] == "PSM Disabled"


def test_unparseable_readback_falls_back_to_the_request(manager):
    manager.ser = FakeSerial({"AT+CPSMS?": OK})
    manager.set_psm_config(True, "10100101", "00100100")
    assert manager.state["psm_info"]["enabled"] is True
