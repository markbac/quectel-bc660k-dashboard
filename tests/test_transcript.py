"""Tests for transcript recording and replay (#37)."""
import os
import time

import pytest

from modem_replay import TranscriptModem
from transcript import TranscriptRecorder, load_transcript, redact

SAMPLE = os.path.join(os.path.dirname(__file__), "transcripts", "synthetic_attached.jsonl")


@pytest.mark.parametrize("text,expected", [
    ("+QCCID: 89441000123456789012", "+QCCID: 89000000000000000001"),
    ("+QCCID: 8944100012345678901", "+QCCID: 8900000000000000001"),
    ("234150123456789", "001010000000001"),
    ("+CGSN: 860123456789012", "+CGSN: 001010000000001"),
    ("+CSQ: 14,99", "+CSQ: 14,99"),
    ('+CEREG: 4,1,"5F3A","01A2B3C4",9', '+CEREG: 4,1,"5F3A","01A2B3C4",9'),
    ("+QENG: 0,6300,0,321,-95", "+QENG: 0,6300,0,321,-95"),
])
def test_redact(text, expected):
    assert redact(text) == expected


def test_redacted_iccid_keeps_its_length():
    for digits in (19, 20):
        original = "89" + "1" * (digits - 2)
        assert len(redact(original)) == digits


def test_recorder_round_trips_and_redacts(tmp_path):
    path = str(tmp_path / "t.jsonl")
    recorder = TranscriptRecorder(path)
    recorder.record("AT+CIMI\r\n", "\r\n234150123456789\r\n\r\nOK\r\n", 0.0123)
    recorder.close()
    recorder.record("AT", "OK", 0.0)  # ignored once closed

    assert load_transcript(path) == [
        {"cmd": "AT+CIMI", "reply": "\r\n001010000000001\r\n\r\nOK\r\n", "delay": 0.012}]


def test_replies_follow_the_recording_then_repeat():
    modem = TranscriptModem([
        {"cmd": "AT+CSQ", "reply": "first", "delay": 0.0},
        {"cmd": "AT+CSQ", "reply": "second", "delay": 0.0},
    ])
    assert modem._chunks_for("AT+CSQ") == [(0.0, "first")]
    assert modem._chunks_for("AT+CSQ") == [(0.0, "second")]
    assert modem._chunks_for("AT+CSQ") == [(0.0, "second")]


def test_unrecorded_commands_get_error():
    assert TranscriptModem([])._chunks_for("AT+XYZ") == [(0.0, "\r\nERROR\r\n")]


def test_speed_scales_delays():
    modem = TranscriptModem([{"cmd": "AT", "reply": "x", "delay": 2.0}], speed=0.5)
    assert modem._chunks_for("AT") == [(1.0, "x")]


def wait_for(predicate, seconds=10.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_manager_runs_a_whole_session_from_a_transcript(manager):
    """The start-up profile and polling work against the replayed modem."""
    modem = TranscriptModem(load_transcript(SAMPLE), speed=0.0)
    modem.start().close()
    try:
        assert manager.connect(modem.slave_name, 115200)
        assert wait_for(lambda: manager.state["signal"]["rsrp"] == -95)
        assert manager.state["sim_info"]["iccid"] == "89000000000000000001"
        assert manager.state["system_info"]["firmware"] == "BC660KGLAAR01A05"
        assert manager.state["psm_info"]["enabled"] is True
        assert manager.state["serving_cell"]["pci"] == 321
    finally:
        manager.disconnect()
        modem.close()


def test_manager_records_what_it_sends(manager, tmp_path):
    path = str(tmp_path / "rec.jsonl")
    manager.recorder = TranscriptRecorder(path)
    modem = TranscriptModem(load_transcript(SAMPLE), speed=0.0)
    modem.start().close()
    try:
        assert manager.connect(modem.slave_name, 115200)
        assert wait_for(lambda: manager.state["signal"]["rsrp"] == -95)
    finally:
        manager.disconnect()
        modem.close()
        manager.recorder.close()

    commands = [entry["cmd"] for entry in load_transcript(path)]
    assert "AT+QCCID" in commands and "AT+QENG=0" in commands
