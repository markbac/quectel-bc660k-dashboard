"""Tests for the access-technology and registration-status label tables."""
import pytest

from serial_manager import CEREG_STAT_NAMES, COPS_ACT_NAMES


def test_cops_act_labels_match_the_manual():
    assert COPS_ACT_NAMES[7] == "LTE (E-UTRAN)"
    assert COPS_ACT_NAMES[9] == "NB-IoT (E-UTRAN NB-S1)"


@pytest.mark.parametrize("act,label", [
    (7, "LTE (E-UTRAN)"),
    (9, "NB-IoT (E-UTRAN NB-S1)"),
    (3, "AcT 3"),
])
def test_scan_results_use_the_labels(manager, act, label):
    resp = f'+COPS: (2,"Example Net","Ex","00101",{act})\r\n\r\nOK\r\n'
    assert manager._parse_cops_scan(resp)[0]["act"] == label


def test_scan_result_without_act_is_unknown(manager):
    resp = '+COPS: (1,"Example Net","Ex","00101")\r\n\r\nOK\r\n'
    assert manager._parse_cops_scan(resp)[0]["act"] == "Unknown"


def test_cereg_stat_zero_is_not_searching():
    assert CEREG_STAT_NAMES[0] == "Not registered, not searching"
    assert CEREG_STAT_NAMES[2] == "Not registered, searching..."


@pytest.mark.parametrize("stat", range(0, 11))
def test_every_documented_stat_has_a_label(stat):
    assert stat in CEREG_STAT_NAMES


def test_cereg_query_reports_the_label(manager):
    manager._parse_cereg_query("\r\n+CEREG: 2,0\r\n\r\nOK\r\n")
    assert manager.state["connectivity_status"] == "Network: Not registered, not searching"
    manager._parse_cereg_query("\r\n+CEREG: 2,12\r\n\r\nOK\r\n")
    assert manager.state["connectivity_status"] == "Network: Stat 12"
