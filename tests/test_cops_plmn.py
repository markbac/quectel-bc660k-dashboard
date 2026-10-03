"""Numeric AT+COPS? answers (#85). The reply shape is that of a real BC660K-GL."""
import pytest

REAL = '\r\n+COPS: 1,2,"23415",9\r\n\r\nOK\r\n'


def test_numeric_operator_becomes_a_plmn_with_mcc_and_mnc(manager):
    manager._parse_cops_query(REAL)
    cell = manager.state["serving_cell"]
    assert cell["operator"] == "Vodafone UK"
    assert (cell["mcc"], cell["mnc"]) == ("234", "15")


def test_three_digit_mnc(manager):
    manager._parse_cops_query('\r\n+COPS: 0,2,"310260",7\r\n\r\nOK\r\n')
    cell = manager.state["serving_cell"]
    assert (cell["mcc"], cell["mnc"]) == ("310", "260")


def test_alphanumeric_operator_is_shown_as_is_and_leaves_mcc_alone(manager):
    manager._parse_cops_query('\r\n+COPS: 0,0,"Vodafone UK",9\r\n\r\nOK\r\n')
    cell = manager.state["serving_cell"]
    assert cell["operator"] == "Vodafone UK"
    assert (cell["mcc"], cell["mnc"]) == ("--", "--")


@pytest.mark.parametrize("resp", ["\r\n+COPS: 2\r\n\r\nOK\r\n", "\r\nERROR\r\n"])
def test_deregistered_or_error_keeps_the_previous_values(manager, resp):
    manager._parse_cops_query(REAL)
    manager._parse_cops_query(resp)
    assert manager.state["serving_cell"]["operator"] == "Vodafone UK"


def test_the_decimal_ids_needed_for_a_cell_lookup_are_available(manager):
    """With COPS plus QENG=0 every field the OpenCellID lookup needs is known."""
    manager._parse_cops_query(REAL)
    manager._parse_cell('\r\n+QENG: 0,6254,12,299,"0000ABCD",-100,-7,-93,11,20,"0001",0,-128,2\r\n\r\nOK\r\n')
    cell = manager.state["serving_cell"]
    assert (cell["mcc"], cell["mnc"], cell["tac_dec"], cell["cell_id_dec"]) == ("234", "15", 1, 0xABCD)
