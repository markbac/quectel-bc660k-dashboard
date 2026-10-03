"""Replay of a capture from a real BC660K-GL (see tests/transcripts/README.md)."""
import os
import time

from modem_replay import TranscriptModem
from transcript import load_transcript

REAL = os.path.join(os.path.dirname(__file__), "transcripts", "bc660k_real_2026-10-03.jsonl")


def wait_for(predicate, seconds=15.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_whole_dashboard_state_from_the_real_replies(manager):
    modem = TranscriptModem(load_transcript(REAL), speed=0.0)
    modem.start().close()
    try:
        assert manager.connect(modem.slave_name, 115200)
        assert wait_for(lambda: manager.state["signal"]["rsrp"] is not None
                        and manager.state["serving_cell"]["operator"] == "Vodafone UK"
                        and manager.state["psm_info"]["granted"]["t3324"])
        state = manager.state
        cell, signal, system = state["serving_cell"], state["signal"], state["system_info"]

        assert system["module"] == "BC660K-GL" and system["firmware"] == "BC660KGLAAR01A05"
        assert state["modem_state"] == "awake" and state["hardware_communicated"] is True
        assert (cell["earfcn"], cell["pci"], cell["band"], cell["tac_dec"]) == (6254, 299, "20", 1)
        assert (cell["mcc"], cell["mnc"]) == ("234", "15")
        assert -105 <= signal["rsrp"] <= -99 and signal["quality_label"] == "Fair"
        assert system["voltage"] in (3460, 3470) and system["temperature"] is None
        assert system["ip_address"] == "10.0.0.7"          # from AT+CGDCONT?, context 0
        assert state["apn_info"]["pdp_cid"] == 0 and state["apn_info"]["apn"] == "test.apn"
        assert state["psm_info"]["enabled"] is True
        assert state["psm_info"]["t3412"] == "01000001" and state["psm_info"]["t3324"] == "00100011"
        assert state["psm_info"]["granted"]["t3324"] == "00100011"
        assert state["psm_info"]["granted"]["t3412"] == "00101010"
        assert state["edrx_info"]["value"] == "0011"
        assert system["sleep_clock"] == 1
    finally:
        manager.disconnect()
        modem.close()
