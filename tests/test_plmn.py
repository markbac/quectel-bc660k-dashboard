"""PLMN codes become operator names (#102)."""
import pytest

import plmn

REAL_SCAN = '+COPS: (1,"","","23415",9),(0,"","","23410",9),,(0-4),(0-2)\r\n\r\nOK'


@pytest.mark.parametrize("value,expected", [
    ("23415", "Vodafone UK"),
    ("PLMN 23415", "Vodafone UK"),
    ("99999", "PLMN 99999"),
    ("Example Net", "Example Net"),
    ("", ""),
    (None, None),
])
def test_display_operator(value, expected):
    assert plmn.display_operator(value) == expected


def test_real_scan_reply_with_empty_names_is_parsed(manager):
    """The bench on a real board returned empty names, which the old pattern dropped."""
    results = manager._parse_cops_scan(REAL_SCAN)
    assert [(r["plmn"], r["long_name"], r["status"]) for r in results] == [
        ("23415", "Vodafone UK", "Available"),
        ("23410", "O2 UK", "Unknown"),
    ]
    assert results[0]["act"].startswith("NB-IoT")


def test_unknown_plmn_in_a_scan_is_labelled_as_a_plmn(manager):
    results = manager._parse_cops_scan('+COPS: (1,"","","99999",9),,(0-4)')
    assert results[0]["long_name"] == "PLMN 99999"
    assert results[0]["short_name"] == ""


def test_names_from_the_network_are_kept(manager):
    results = manager._parse_cops_scan('+COPS: (2,"Long Net","LN","23415",9)')
    assert (results[0]["long_name"], results[0]["short_name"]) == ("Long Net", "LN")
