"""Tests for the per-module serving-cell drivers (#3).

The Quectel LTE and SIMCom samples are built from the vendors' documented
field lists with invented values; they are not captures from hardware.
"""
import pytest

import drivers
from drivers import Bc660kDriver, QuectelServingCellDriver, SimcomCpsiDriver, detect_driver
from tests.fake_serial import FakeSerial

EC25_ATI = "\r\nQuectel\r\nEC25\r\nRevision: EC25EFAR06A01M4G\r\n\r\nOK\r\n"
BG95_ATI = "\r\nQuectel\r\nBG95-M3\r\nRevision: BG95M3LAR02A03\r\n\r\nOK\r\n"
BC660_ATI = "\r\nQuectel_Ltd\r\nQuectel_BC660K-GL\r\nRevision: BC660KGLAAR01A05\r\n\r\nOK\r\n"
SIM7000_ATI = "\r\nSIMCOM_Ltd\r\nSIMCOM_SIM7000E\r\nRevision: 1351B01SIM7000E\r\n\r\nOK\r\n"
SIM7600_ATI = "\r\nManufacturer: SIMCOM INCORPORATED\r\nModel: SIMCOM_SIM7600E-H\r\nOK\r\n"

EC25_CELL = ('\r\n+QENG: "servingcell","NOCONN","LTE","FDD",234,15,2549F0B,420,1300,3,5,5,2D0D,-93,-12,-67,15,-\r\n'
             '+QENG: "neighbourcell intra","LTE",1300,421,-14,-101,-72,8,0,0,0\r\n'
             '+QENG: "neighbourcell inter","LTE",6400,77,-16,-108,-80,5,0,0,0,0,0\r\n\r\nOK\r\n')
CPSI = "\r\n+CPSI: LTE,Online,234-15,0x182D,121004303,153,EUTRAN-BAND3,1850,5,5,-117,-1166,-796,15\r\n\r\nOK\r\n"


@pytest.mark.parametrize("ati,driver_type,model", [
    (BC660_ATI, Bc660kDriver, "BC660K-GL"),
    (EC25_ATI, QuectelServingCellDriver, "EC25"),
    (BG95_ATI, QuectelServingCellDriver, "BG95-M3"),
    (SIM7000_ATI, SimcomCpsiDriver, "SIM7000E"),
    (SIM7600_ATI, SimcomCpsiDriver, "SIM7600E"),
])
def test_driver_is_chosen_from_ati(ati, driver_type, model):
    driver = detect_driver(ati)
    assert isinstance(driver, driver_type)
    assert driver.model_name(ati) == model


@pytest.mark.parametrize("ati", ["", "OK", "\r\nQuectel\r\nUnknownModule\r\nOK\r\n", "ERROR"])
def test_unknown_models_get_no_driver(ati):
    assert detect_driver(ati) is None


def test_quectel_servingcell_fields():
    info = QuectelServingCellDriver().parse_cell(EC25_CELL)
    assert (info.rat, info.mcc, info.mnc) == ("LTE", "234", "15")
    assert (info.cell_id, info.pci, info.earfcn, info.band, info.tac) == ("2549F0B", 420, 1300, "3", "2D0D")
    assert (info.rsrp, info.rsrq, info.rssi, info.sinr) == (-93, -12, -67, 15)
    assert [(n["pci"], n["rsrp"], n["rsrq"]) for n in info.neighbours] == [(421, -101, -14), (77, -108, -16)]


def test_quectel_ignores_non_lte_cells_and_errors():
    gsm = '\r\n+QENG: "servingcell","NOCONN","GSM",460,00,2D0D,1F2E,45,2,0,0,0,0,0,0\r\n\r\nOK\r\n'
    driver = QuectelServingCellDriver()
    assert driver.parse_cell(gsm) is None
    assert driver.parse_cell("\r\nERROR\r\n") is None
    assert driver.parse_cell("\r\n+CME ERROR: 4\r\n") is None


def test_simcom_cpsi_units_are_converted():
    info = SimcomCpsiDriver().parse_cell(CPSI)
    assert (info.rat, info.mcc, info.mnc, info.tac) == ("LTE", "234", "15", "182D")
    assert int(info.cell_id, 16) == 121004303
    assert (info.pci, info.earfcn, info.band) == (153, 1850, "3")
    assert (info.rsrq, info.rsrp, info.rssi, info.sinr) == (-12, -117, -80, 15)


@pytest.mark.parametrize("resp", [
    "\r\n+CPSI: NO SERVICE,Online\r\n\r\nOK\r\n",
    "\r\n+CPSI: GSM,Online,234-15,0x182D,1234,12,GSM 900,40,0,0\r\n\r\nOK\r\n",
    "\r\nERROR\r\n",
])
def test_simcom_without_an_lte_cell(resp):
    assert SimcomCpsiDriver().parse_cell(resp) is None


def test_simcom_cat_m_mode_names_are_accepted():
    cpsi = CPSI.replace("LTE,Online", "LTE CAT-M1,Online")
    assert SimcomCpsiDriver().parse_cell(cpsi).rat == "LTE CAT-M1"


def test_commands_are_distinct_per_family():
    assert [d.cell_command for d in drivers.DRIVERS] == ["AT+QENG=0", 'AT+QENG="servingcell"', "AT+CPSI?"]


# --- integration with the manager --------------------------------------------

def test_manager_switches_driver_and_polls_its_command(manager):
    manager.running = True
    manager.ser = FakeSerial({"ATI": EC25_ATI, 'AT+QENG="servingcell"': EC25_CELL})
    manager._parse_ati(EC25_ATI)
    assert manager.state["system_info"]["module"] == "EC25"
    assert manager.state["system_info"]["firmware"] == "EC25EFAR06A01M4G"

    manager._hardware_info_loaded = True
    manager._poll_once()

    assert 'AT+QENG="servingcell"' in manager.ser.sent
    assert "AT+QENG=0" not in manager.ser.sent
    cell = manager.state["serving_cell"]
    assert (cell["pci"], cell["cell_id"], cell["tac"], cell["mcc"], cell["mnc"]) == (420, "2549F0B", "2D0D", "234", "15")
    assert cell["tac_dec"] == 0x2D0D
    assert manager.state["signal"]["rsrp"] == -93
    assert manager.state["signal"]["quality_label"] == "Good"
    assert len(manager.state["neighbour_cells"]) == 2


def test_manager_handles_simcom(manager):
    manager._parse_ati(SIM7000_ATI)
    manager._parse_cell(CPSI)
    assert manager.state["signal"]["rsrp"] == -117
    assert manager.state["serving_cell"]["band"] == "3"
    assert manager.state["serving_cell"]["cell_id_dec"] == 121004303


def test_unrecognised_module_keeps_bc660k_commands_and_warns(manager):
    manager._parse_ati("\r\nAcme\r\nZ9000\r\nOK\r\n")
    manager._parse_ati("\r\nAcme\r\nZ9000\r\nOK\r\n")
    assert manager.driver is drivers.BC660K
    assert manager.state["system_info"]["module"] == "--"
    warnings = [e for e in manager.state["logs"] if "not recognised" in e["text"]]
    assert len(warnings) == 2  # once per start-up profile, never per poll


def test_disconnect_returns_to_the_default_driver(manager):
    manager._parse_ati(EC25_ATI)
    manager.disconnect()
    assert manager.driver is drivers.BC660K
    assert manager.state["system_info"]["module"] == "--"
