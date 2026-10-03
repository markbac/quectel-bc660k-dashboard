"""Tests for per-ICCID history scoping (#17)."""
import sqlite3

import pytest
from starlette.testclient import TestClient

import db_manager
from db_manager import DBManager
from serial_manager import DEMO_ICCID
from tests.fake_serial import FakeSerial

ICCID_A = "89000000000000000001"
ICCID_B = "89000000000000000002"


def state(iccid, rsrp=-90, communicated=True, mode="REAL"):
    return {
        "mode": mode,
        "hardware_communicated": communicated,
        "signal": {"rsrp": rsrp, "rsrq": -10, "rssi": -80, "sinr": 5, "csq": 10, "ber": 0, "quality_label": "Fair"},
        "serving_cell": {"operator": "Net", "cell_id": "1A", "pci": 1, "earfcn": 6300, "band": "8", "tac": "5F"},
        "sim_info": {"iccid": iccid, "imsi": "001010000000001"},
        "system_info": {"voltage": 3600, "temperature": None, "ip_address": "--"},
    }


@pytest.fixture
def db(tmp_path):
    return DBManager(str(tmp_path / "t.db"))


def test_two_boards_never_see_each_others_history(db):
    db.log_record(state(ICCID_A, -80))
    db.log_record(state(ICCID_B, -100))
    db.log_record(state(ICCID_B, -105))

    assert [r["rsrp"] for r in db.get_history(ICCID_A)] == [-80]
    assert [r["rsrp"] for r in db.get_history(ICCID_B)] == [-100, -105]
    assert db.get_stats(ICCID_A)["total_records"] == 1
    assert db.get_stats(ICCID_B)["min_rsrp"] == -105


@pytest.mark.parametrize("iccid", [None, "", "--"])
def test_without_an_iccid_nothing_is_shown_or_written(db, iccid):
    assert db.log_record(state(iccid)) is False
    assert db.get_history(iccid) == []
    assert db.get_stats(iccid)["total_records"] == 0
    assert db.clear_history(iccid) == 0
    assert db.get_stats(ICCID_A)["total_records"] == 0


def test_rows_are_not_written_before_the_modem_has_answered(db):
    assert db.log_record(state(ICCID_A, communicated=False)) is False
    assert db.get_stats(ICCID_A)["total_records"] == 0


def test_rows_without_signal_values_are_not_written(db):
    s = state(ICCID_A)
    s["signal"]["rsrp"] = None
    assert db.log_record(s) is False


def test_imsi_is_not_stored(db):
    db.log_record(state(ICCID_A))
    assert db.get_history(ICCID_A)[0]["imsi"] is None


def test_demo_data_cannot_mix_with_real_data(db):
    db.log_record(state(DEMO_ICCID, mode="DEMO", communicated=False))
    db.log_record(state(ICCID_A))
    assert len(db.get_history(DEMO_ICCID)) == 1
    assert len(db.get_history(ICCID_A)) == 1


def test_clear_only_deletes_the_current_sims_rows(db):
    db.log_record(state(ICCID_A))
    db.log_record(state(ICCID_B))

    assert db.clear_history(ICCID_A) == 1

    assert db.get_stats(ICCID_A)["total_records"] == 0
    assert db.get_stats(ICCID_B)["total_records"] == 1
    assert db.clear_history(everything=True) == 1
    assert db.get_stats(ICCID_B)["total_records"] == 0


def test_migration_removes_rows_without_an_iccid_and_clears_imsi(tmp_path):
    path = str(tmp_path / "t.db")
    with sqlite3.connect(path) as conn:
        db_manager._migration_1_create_history(conn)
        conn.executemany(
            "INSERT INTO signal_history (unix_time, rsrp, iccid, imsi) VALUES (?, ?, ?, ?)",
            [(1, -90, ICCID_A, "001010000000001"), (2, None, "--", None), (3, None, None, None), (4, -1, "", None)],
        )
        conn.execute("PRAGMA user_version = 2")

    db = DBManager(path)

    assert [r["unix_time"] for r in db.get_history(ICCID_A)] == [1]
    assert db.get_history(ICCID_A)[0]["imsi"] is None
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM signal_history").fetchone()[0] == 1


# --- manager and API ---------------------------------------------------------

def test_iccid_change_mid_session_switches_the_history_view(manager):
    manager.ser = FakeSerial({"AT+QCCID": f"\r\n+QCCID: {ICCID_A}\r\n\r\nOK\r\n"})
    manager._refresh_identity()
    assert manager.current_iccid == ICCID_A
    manager.db.log_record(state(ICCID_A))

    manager.ser.responses["AT+QCCID"] = f"\r\n+QCCID: {ICCID_B}\r\n\r\nOK\r\n"
    manager._refresh_identity()

    assert manager.current_iccid == ICCID_B
    assert manager.db.get_history(manager.current_iccid) == []
    assert len(manager.db.get_history(ICCID_A)) == 1


def test_sim_removal_clears_the_identity(manager):
    manager.ser = FakeSerial({"AT+QCCID": f"\r\n+QCCID: {ICCID_A}\r\n\r\nOK\r\n"})
    manager._refresh_identity()
    manager.ser.responses["AT+QCCID"] = "\r\n+CME ERROR: 10\r\n"
    manager._refresh_identity()
    assert manager.current_iccid is None


def test_identity_is_rechecked_during_polling(manager, monkeypatch):
    manager.running = True
    manager.ser = FakeSerial({"AT+QCCID": f"\r\n+QCCID: {ICCID_A}\r\n\r\nOK\r\n"})
    manager._last_identity_check = 0.0
    manager._poll_once()
    assert "AT+QCCID" in manager.ser.sent
    sent_before = manager.ser.sent.count("AT+QCCID")
    manager._poll_once()
    assert manager.ser.sent.count("AT+QCCID") == sent_before  # not again within the interval


def test_demo_mode_uses_the_fixed_demo_iccid(manager):
    manager.enable_demo_mode()
    try:
        assert manager.current_iccid == DEMO_ICCID
    finally:
        manager.disconnect()


@pytest.fixture
def api(manager, monkeypatch):
    import sys
    import importlib
    monkeypatch.setattr(sys, "argv", ["server.py", "--no-file-log"])
    monkeypatch.setenv("QUECTEL_DASHBOARD_DB", manager.db.db_path)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="http://localhost:8080") as client:
        yield server, client


def test_api_reports_awaiting_identity_and_hides_everything(api):
    server, client = api
    server.manager.db.log_record(state(ICCID_A))

    body = client.get("/api/history").json()

    assert body["awaiting_identity"] is True
    assert body["history"] == []
    assert body["stats"]["total_records"] == 0
    assert "No data" in client.get("/api/history/export").text


def test_api_history_export_and_clear_are_scoped(api):
    server, client = api
    server.manager.db.log_record(state(ICCID_A, -80))
    server.manager.db.log_record(state(ICCID_B, -100))
    server.manager.state["sim_info"]["iccid"] = ICCID_A

    body = client.get("/api/history").json()
    assert body["awaiting_identity"] is False
    assert [r["rsrp"] for r in body["history"]] == [-80]
    csv_text = client.get("/api/history/export").text
    assert ICCID_A in csv_text and ICCID_B not in csv_text

    assert client.post("/api/history/clear").json()["deleted"] == 1
    assert server.manager.db.get_stats(ICCID_B)["total_records"] == 1
