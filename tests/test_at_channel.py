"""Direct tests of ATChannel, independent of SerialManager."""
import re

import pytest

from at_channel import ATChannel, TIMEOUT_RESPONSE
from tests.fake_serial import FakeSerial


class Recorder:
    """Collects everything the channel reports."""

    def __init__(self):
        self.logs, self.urcs, self.responses, self.timeouts = [], [], 0, 0

    def log(self, text, direction):
        self.logs.append((direction, text))

    def channel(self, port):
        return ATChannel(
            get_port=lambda: port,
            log=self.log,
            on_urc=self.urcs.append,
            on_response=lambda: setattr(self, "responses", self.responses + 1),
            on_timeout=lambda: setattr(self, "timeouts", self.timeouts + 1),
        )


@pytest.fixture
def rec():
    return Recorder()


def test_response_is_returned_and_reported(rec):
    ch = rec.channel(FakeSerial({"AT+CSQ": "\r\n+CSQ: 14,0\r\n\r\nOK\r\n"}))
    assert "+CSQ: 14,0" in ch.send("AT+CSQ")
    assert rec.responses == 1 and rec.timeouts == 0
    assert ("TX", "TX> AT+CSQ") in rec.logs


def test_no_port_is_reported_without_touching_callbacks(rec):
    ch = ATChannel(get_port=lambda: None, log=rec.log, on_response=lambda: pytest.fail("called"))
    assert ch.send("AT") == "ERROR: Port not open"


def test_closed_port_is_treated_as_no_port(rec):
    port = FakeSerial({})
    port.close()
    assert rec.channel(port).send("AT") == "ERROR: Port not open"


def test_timeout_is_reported_once(rec):
    ch = rec.channel(FakeSerial({"AT": ""}))
    assert ch.send("AT", timeout_sec=0.1) == TIMEOUT_RESPONSE
    assert rec.timeouts == 1 and rec.responses == 0


def test_retries_happen_only_after_a_timeout(rec):
    port = FakeSerial({"AT": ["", "", "\r\nOK\r\n"]})
    ch = rec.channel(port)

    assert ATChannel.is_ok(ch.send("AT", timeout_sec=0.1, retries=2))

    assert port.sent == ["AT", "AT", "AT"]
    assert rec.timeouts == 2


def test_an_error_response_is_not_retried(rec):
    port = FakeSerial({"AT+X": "\r\nERROR\r\n"})
    resp = rec.channel(port).send("AT+X", retries=3)
    assert "ERROR" in resp
    assert port.sent == ["AT+X"]


def test_retries_give_up_with_a_timeout(rec):
    port = FakeSerial({"AT": ""})
    assert rec.channel(port).send("AT", timeout_sec=0.05, retries=1) == TIMEOUT_RESPONSE
    assert port.sent == ["AT", "AT"]


def test_wait_for_holds_the_response_until_the_pattern_appears(rec):
    port = FakeSerial({"AT+QPING": ["\r\nOK\r\n"]})
    resp = rec.channel(port).send("AT+QPING", timeout_sec=0.2, wait_for=re.compile(r"\+QPING: done"))
    # Only OK arrived, so the partial response comes back after the timeout.
    assert resp.strip() == "OK"


def test_urc_lines_are_split_off_and_reported(rec):
    ch = rec.channel(FakeSerial({"AT+CSQ": "\r\n+CSCON: 1\r\n+CSQ: 14,0\r\n\r\nOK\r\n"}))
    resp = ch.send("AT+CSQ")
    assert "+CSCON" not in resp and "+CSQ: 14,0" in resp
    assert rec.urcs == ["+CSCON: 1"]


def test_stale_input_is_dispatched_as_urcs(rec):
    port = FakeSerial({})
    port._buffer = b'\r\n+QNBIOTEVENT: "ENTER PSM"\r\n'
    rec.channel(port).send("AT")
    assert '+QNBIOTEVENT: "ENTER PSM"' in rec.urcs


def test_read_idle_reports_what_arrived_between_commands(rec):
    port = FakeSerial({})
    port._buffer = b"\r\n+CSCON: 0\r\n"
    ch = rec.channel(port)
    assert "+CSCON: 0" in ch.read_idle()
    assert rec.urcs == ["+CSCON: 0"]
    assert ch.read_idle() == ""


def test_serial_errors_become_error_responses(rec):
    class Broken(FakeSerial):
        def write(self, data):
            raise OSError("device unplugged")

    resp = rec.channel(Broken({})).send("AT")
    assert resp == "ERROR: device unplugged"
    assert any(d == "ERROR" and "device unplugged" in t for d, t in rec.logs)
