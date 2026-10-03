"""Tests for the AT+QENG=0 parser (format from the BC660K-GL AT manual V1.3).

The sample responses are built from the documented field list, with invented
values; they are not captures from a board.
"""
from tests.fake_serial import FakeSerial

SERVING = '+QENG: 0,6300,0,320,"01D2F401",-95,-11,-85,12,8,"5F4E",0,23,0'
NEIGHBOUR = "+QENG: 1,6300,321,-100,-12"


def _resp(*lines):
    return "\r\n" + "\r\n".join(lines) + "\r\n\r\nOK\r\n"


def test_serving_cell_fields_are_parsed(manager):
    manager._parse_qeng(_resp(SERVING))

    sc = manager.state["serving_cell"]
    assert sc["earfcn"] == 6300
    assert sc["pci"] == 320
    assert sc["cell_id"] == "01D2F401"
    assert sc["cell_id_dec"] == 0x01D2F401
    assert sc["band"] == "8"
    assert sc["tac"] == "5F4E"
    assert sc["tac_dec"] == 0x5F4E
    assert sc["operation_mode"] == "0"
    sig = manager.state["signal"]
    assert (sig["rsrp"], sig["rsrq"], sig["rssi"], sig["sinr"]) == (-95, -11, -85, 12)
    assert sig["quality_label"] == "Fair"


def test_empty_optional_fields_do_not_overwrite_values(manager):
    manager.state["signal"]["rsrp"] = -90
    manager._parse_qeng(_resp('+QENG: 0,6300,0,320,"01D2F401",,,,,8,"5F4E",,,0'))

    assert manager.state["signal"]["rsrp"] == -90
    assert manager.state["serving_cell"]["pci"] == 320


def test_neighbours_are_replaced_each_time(manager):
    manager._parse_qeng(_resp(SERVING, NEIGHBOUR, "+QENG: 1,6400,12,-105,-14"))
    assert [n["pci"] for n in manager.state["neighbour_cells"]] == [321, 12]

    manager._parse_qeng(_resp(SERVING))
    assert manager.state["neighbour_cells"] == []


def test_error_response_keeps_previous_state(manager):
    manager._parse_qeng(_resp(SERVING, NEIGHBOUR))
    manager._parse_qeng("\r\nERROR\r\n")
    assert len(manager.state["neighbour_cells"]) == 1
    assert manager.state["serving_cell"]["pci"] == 320


def test_cesq_sets_the_quality_label(manager):
    """Previously the label was only ever set by the QENG parser."""
    manager._parse_cesq("\r\n+CESQ: 99,99,255,255,12,50\r\n\r\nOK\r\n")
    assert manager.state["signal"]["rsrp"] == -91
    assert manager.state["signal"]["quality_label"] == "Good"


def test_poll_uses_the_documented_command_only(manager):
    manager.running = True
    manager.ser = FakeSerial({"AT+QENG=0": _resp(SERVING, NEIGHBOUR)})

    manager._poll_once()

    assert "AT+QENG=0" in manager.ser.sent
    assert not any("servingcell" in c or "neighbourcell" in c or "NUESTATS" in c for c in manager.ser.sent)
    assert manager.state["serving_cell"]["pci"] == 320


def test_simulator_emits_the_documented_format(manager):
    manager.state["serving_cell"].update({"earfcn": 6300, "pci": 320, "cell_id": "1A", "band": "8", "tac": "5F"})
    manager.state["signal"].update({"rsrp": -95, "rsrq": -11, "rssi": -85, "sinr": 12})

    resp = manager._simulated_at_response("AT+QENG=0")
    manager._parse_qeng(resp)

    assert manager.state["serving_cell"]["pci"] == 320
    assert len(manager.state["neighbour_cells"]) == 1
