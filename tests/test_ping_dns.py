"""Tests for AT+QPING and AT+QIDNSGIP handling."""
import time

import pytest

from tests.pty_modem import PtyModem

PING_OK = (
    '\r\n+QPING: 0,"8.8.8.8",32,310,255\r\n'
    '\r\n+QPING: 0,"8.8.8.8",32,298,255\r\n'
    "\r\n+QPING: 0,2,2,0,298,310,304\r\n"
)


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


def test_ping_reads_the_result_that_arrives_after_ok(manager, modem):
    """Regression test for #20: the code used to stop at the first OK."""
    m = modem({'AT+QPING=0,"8.8.8.8",4,2': [(0.0, "\r\nOK\r\n"), (0.4, PING_OK)]})

    res = manager.run_ping_benchmark("8.8.8.8", 2)

    assert res["status"] == "Success"
    assert (res["sent"], res["received"], res["lost"]) == (2, 2, 0)
    assert (res["min_rtt"], res["max_rtt"], res["avg_rtt"]) == (298, 310, 304)
    assert res["loss_pct"] == 0.0
    assert m.received == ['AT+QPING=0,"8.8.8.8",4,2']


def test_ping_without_a_result_is_a_timeout_not_total_loss(manager, monkeypatch):
    monkeypatch.setattr(manager, "_send_at_cmd_raw",
                        lambda cmd, timeout_sec=None, wait_for=None: "\r\nOK\r\n")

    res = manager.run_ping_benchmark("8.8.8.8", 1)

    assert res["status"] == "Timed out waiting for result"
    assert res["loss_pct"] is None
    assert res["avg_rtt"] is None


def test_ping_count_is_clamped_to_the_documented_range(manager, monkeypatch):
    seen = []
    monkeypatch.setattr(manager, "_send_at_cmd_raw",
                        lambda cmd, timeout_sec=None, wait_for=None: seen.append((cmd, timeout_sec)) or "")
    manager.run_ping_benchmark("example.com", 99)
    cmd, timeout = seen[0]
    assert cmd.endswith(",10")
    assert timeout == 10 * 4 + 5


def test_ping_error_code_is_reported(manager):
    res = manager._parse_ping("\r\nOK\r\n\r\n+QPING: 569\r\n", "x", 4)
    assert res["status"] == "Error 569"


def test_ping_summary_with_all_lost_has_no_rtts(manager):
    res = manager._parse_ping("\r\nOK\r\n\r\n+QPING: 0,4,0,4\r\n", "x", 4)
    assert res["status"] == "Failed"
    assert res["loss_pct"] == 100.0
    assert res["avg_rtt"] is None


def test_dns_reads_the_address_that_arrives_after_ok(manager, modem):
    modem({'AT+QIDNSGIP=0,"example.com"': [
        (0.0, "\r\nOK\r\n"),
        (0.3, "\r\n+QIDNSGIP: 0,1,300\r\n"),
        (0.1, "\r\n+QIDNSGIP: 93.184.216.34\r\n"),
    ]})

    res = manager.run_dns_query("example.com")

    assert res == {"domain": "example.com", "resolved_ip": "93.184.216.34", "status": "Success"}


def test_dns_error_code_ends_the_wait(manager, modem):
    modem({'AT+QIDNSGIP=0,"bad.invalid"': [(0.0, "\r\nOK\r\n"), (0.2, "\r\n+QIDNSGIP: 565\r\n")]})
    start = time.time()

    res = manager.run_dns_query("bad.invalid")

    assert res["status"] == "Error 565"
    assert res["resolved_ip"] is None
    assert time.time() - start < 5
