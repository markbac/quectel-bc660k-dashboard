"""Tests that each AT command receives only its own response."""
import time

import pytest

from tests.pty_modem import PtyModem


@pytest.fixture
def modem(manager):
    created = []

    def make(script):
        m = PtyModem(script)
        manager.ser = m.start()
        created.append(m)
        return m

    yield make
    for m in created:
        m.close()


def test_late_reply_does_not_leak_into_next_command(manager, modem):
    """Regression test for #27: a reply slower than the timeout used to be
    read as the response to the following command."""
    modem({"AT+CSQ": (0.6, "\r\n+CSQ: 14,0\r\n\r\nOK\r\n"),
           "AT+CESQ": (0.0, "\r\n+CESQ: 99,99,255,255,20,60\r\n\r\nOK\r\n")})

    first = manager._send_at_cmd_raw("AT+CSQ", timeout_sec=0.3)
    second = manager._send_at_cmd_raw("AT+CESQ", timeout_sec=2.0)

    assert first == "ERROR: Timeout"
    assert "+CSQ" not in second
    assert "+CESQ: 99,99,255,255,20,60" in second


def test_stale_bytes_before_a_command_are_discarded(manager, modem):
    m = modem({"AT+CSQ": (0.0, "\r\n+CSQ: 20,0\r\n\r\nOK\r\n")})
    m.inject("\r\n+CSQ: 1,1\r\n\r\nOK\r\n")
    time.sleep(0.1)

    resp = manager._send_at_cmd_raw("AT+CSQ")

    assert "+CSQ: 20,0" in resp
    assert "+CSQ: 1,1" not in resp


def test_urc_inside_a_response_is_split_off(manager, modem):
    modem({"AT+CSQ": (0.0, "\r\n+CSCON: 1\r\n+CSQ: 14,0\r\n\r\nOK\r\n")})

    resp = manager._send_at_cmd_raw("AT+CSQ")

    assert "+CSQ: 14,0" in resp
    assert "+CSCON" not in resp
    assert any("URC< +CSCON: 1" in e["text"] or "+CSCON: 1" in e["text"] for e in manager.state["logs"])


def test_own_prefix_is_not_treated_as_urc(manager, modem):
    modem({"AT+CEREG?": (0.0, '\r\n+CEREG: 2,1,"5F4E","1D2F401",9\r\n\r\nOK\r\n')})

    resp = manager._send_at_cmd_raw("AT+CEREG?")

    assert '+CEREG: 2,1,"5F4E"' in resp


def test_cme_error_ends_the_wait_early(manager, modem):
    modem({"AT+CPIN?": (0.0, "\r\n+CME ERROR: 10\r\n")})
    start = time.time()

    resp = manager._send_at_cmd_raw("AT+CPIN?", timeout_sec=5.0)

    assert "+CME ERROR: 10" in resp
    assert time.time() - start < 2.0
