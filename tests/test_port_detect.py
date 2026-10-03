"""Tests for serial port auto-detection."""
from types import SimpleNamespace

import serial

import port_detect
from tests.pty_modem import PtyModem


def _port(device, vid=None):
    return SimpleNamespace(device=device, vid=vid)


def test_candidates_put_ftdi_and_quectel_first():
    ports = [_port("/dev/ttyS0"), _port("/dev/ttyUSB1", 0x0403), _port("/dev/ttyACM0", 0x2C7C),
             _port("/dev/ttyUSB0", 0x0403)]
    assert port_detect.candidate_ports(ports) == [
        "/dev/ttyACM0", "/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyS0"]


def test_detect_returns_first_responding_port():
    answers = {"A": False, "B": True, "C": True}
    found = port_detect.detect_at_port(["A", "B", "C"], bauds=(115200,),
                                       probe=lambda dev, baud: answers[dev])
    assert found == ("B", 115200)


def test_detect_returns_none_when_nothing_answers():
    assert port_detect.detect_at_port(["A"], probe=lambda d, b: False) is None


def test_detect_tries_each_baud():
    found = port_detect.detect_at_port(["A"], bauds=(9600, 115200), probe=lambda d, b: b == 115200)
    assert found == ("A", 115200)


def test_answers_at_on_pty_modem():
    modem = PtyModem({"AT": (0.0, "\r\nOK\r\n")})
    modem.start().close()
    assert port_detect.answers_at(modem.slave_name, 115200, wait=1.0)


def test_silent_port_does_not_answer():
    modem = PtyModem({"AT": (5.0, "\r\nOK\r\n")})
    modem.start().close()
    assert not port_detect.answers_at(modem.slave_name, 115200, wait=0.3)


def test_unopenable_port_does_not_answer():
    assert not port_detect.answers_at("/dev/does-not-exist", 115200, wait=0.1)


def test_open_error_is_swallowed():
    def opener(*args, **kwargs):
        raise serial.SerialException("busy")
    assert not port_detect.answers_at("x", 115200, opener=opener)
