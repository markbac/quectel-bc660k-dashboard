"""The COPS scan bench script restores what it changes and reports the outcome (#100)."""
import sys
from pathlib import Path

import pytest

from modem_replay import PtyModem

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import cops_scan_bench as bench  # noqa: E402


@pytest.mark.parametrize("reply,expected", [
    ('+COPS: 1,2,"23415",9', 'AT+COPS=1,2,"23415",9'),
    ('+COPS: 0,0,"Net"', 'AT+COPS=0,0,"Net"'),
    ("+COPS: 0", "AT+COPS=0"),
    ("ERROR", "AT+COPS=0"),
])
def test_restore_command_puts_back_the_original_selection(reply, expected):
    assert bench.restore_command(reply) == expected


def test_registered_means_home_or_roaming():
    assert bench.registered("+CEREG: 4,5,x")
    assert bench.registered("+CEREG: 0,1")
    assert not bench.registered("+CEREG: 4,2")
    assert not bench.registered("ERROR")


def _modem(scan_reply):
    return PtyModem({
        "AT": (0.0, "\r\nOK\r\n"),
        "ATE0": (0.0, "\r\nOK\r\n"),
        "AT+CFUN?": (0.0, "\r\n+CFUN: 1\r\n\r\nOK\r\n"),
        "AT+CEREG?": (0.0, "\r\n+CEREG: 4,5,\"E43A\",\"004EB815\",9\r\n\r\nOK\r\n"),
        "AT+COPS?": (0.0, '\r\n+COPS: 1,2,"23415",9\r\n\r\nOK\r\n'),
        "AT+QSCLK?": (0.0, "\r\n+QSCLK: 1\r\n\r\nOK\r\n"),
        "AT+QSCLK=0": (0.0, "\r\nOK\r\n"),
        "AT+QSCLK=1": (0.0, "\r\nOK\r\n"),
        "AT+COPS=2": (0.0, "\r\nOK\r\n"),
        'AT+COPS=1,2,"23415",9': (0.0, "\r\nOK\r\n"),
        "AT+COPS=?": scan_reply,
    })


def test_bench_reports_an_answer_and_restores(monkeypatch):
    monkeypatch.setattr(bench.time, "sleep", lambda s: None)
    modem = _modem((0.0, '\r\n+COPS: (2,"A","A","23415",9),,(0-4),(0-2)\r\n\r\nOK\r\n'))
    link = modem.start()
    try:
        summary = bench.run(link, timeout=2.0, also_registered=False)
    finally:
        link.close()
        modem.close()
    assert "Not registered: answered" in summary
    assert "Registered again: yes" in summary


def test_bench_reports_silence_and_still_restores(monkeypatch):
    monkeypatch.setattr(bench.time, "sleep", lambda s: None)
    modem = _modem((30.0, "\r\nOK\r\n"))
    link = modem.start()
    try:
        summary = bench.run(link, timeout=0.5, also_registered=False)
    finally:
        link.close()
        modem.close()
    assert "Not registered: no answer" in summary
    assert "Registered again: yes" in summary
