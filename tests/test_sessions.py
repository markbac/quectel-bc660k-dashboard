"""Tests for recording sessions (#36)."""
import sqlite3

import pytest

import db_manager
from db_manager import DBManager
from tests.test_history_scoping import ICCID_A, ICCID_B, state


@pytest.fixture
def db(tmp_path):
    return DBManager(str(tmp_path / "t.db"))


def test_rows_reference_their_session(db):
    sid = db.start_session(ICCID_A, "860000000000000", "BC660KGLAAR01A05")
    db.log_record(state(ICCID_A), sid)
    db.log_record(state(ICCID_A), sid)

    (session,) = db.get_sessions(ICCID_A)
    assert session["id"] == sid
    assert session["records"] == 2
    assert session["imei"] == "860000000000000"
    assert session["firmware"] == "BC660KGLAAR01A05"
    assert session["ended_at"] is None
    assert [r["session_id"] for r in db.get_history(ICCID_A)] == [sid, sid]


def test_end_session_sets_the_end_time_once(db):
    sid = db.start_session(ICCID_A)
    db.end_session(sid)
    first = db.get_sessions(ICCID_A)[0]["ended_at"]
    assert first is not None
    db.end_session(sid)
    db.end_session(None)
    assert db.get_sessions(ICCID_A)[0]["ended_at"] == first


def test_placeholder_identifiers_are_stored_as_null(db):
    db.start_session(ICCID_A, "--", "--")
    session = db.get_sessions(ICCID_A)[0]
    assert session["imei"] is None and session["firmware"] is None


def test_sessions_are_listed_per_sim(db):
    db.start_session(ICCID_A)
    db.start_session(ICCID_B)
    assert len(db.get_sessions(ICCID_A)) == 1
    assert db.get_sessions(None) == []
    assert db.get_sessions("--") == []


def test_migration_groups_existing_rows_into_one_session_per_iccid(tmp_path):
    path = str(tmp_path / "t.db")
    with sqlite3.connect(path) as conn:
        db_manager._migration_1_create_history(conn)
        conn.executemany(
            "INSERT INTO signal_history (unix_time, rsrp, iccid) VALUES (?, ?, ?)",
            [(10, -90, ICCID_A), (20, -91, ICCID_A), (30, -100, ICCID_B)],
        )
        conn.execute("PRAGMA user_version = 3")

    db = DBManager(path)

    (a,) = db.get_sessions(ICCID_A)
    assert (a["started_at"], a["ended_at"], a["records"]) == (10, 20, 2)
    (b,) = db.get_sessions(ICCID_B)
    assert b["records"] == 1
    assert all(r["session_id"] is not None for r in db.get_history(ICCID_A))


# --- manager lifecycle -------------------------------------------------------

def test_manager_starts_a_session_when_the_sim_becomes_known(manager):
    manager.state["sim_info"]["iccid"] = ICCID_A
    manager.state["system_info"].update({"imei": "860000000000000", "firmware": "FW1"})
    manager.state["hardware_communicated"] = True
    manager.state["signal"]["rsrp"] = -90

    manager._log_history()
    manager._log_history()

    (session,) = manager.db.get_sessions(ICCID_A)
    assert session["records"] == 2
    assert session["imei"] == "860000000000000"


def test_manager_changes_session_when_the_sim_changes(manager):
    manager.state.update({"hardware_communicated": True})
    manager.state["signal"]["rsrp"] = -90
    manager.state["sim_info"]["iccid"] = ICCID_A
    manager._log_history()
    manager.state["sim_info"]["iccid"] = ICCID_B
    manager._log_history()

    old = manager.db.get_sessions(ICCID_A)[0]
    new = manager.db.get_sessions(ICCID_B)[0]
    assert old["ended_at"] is not None
    assert new["ended_at"] is None
    assert old["records"] == 1 and new["records"] == 1


def test_disconnect_ends_the_session(manager):
    manager.state.update({"hardware_communicated": True})
    manager.state["signal"]["rsrp"] = -90
    manager.state["sim_info"]["iccid"] = ICCID_A
    manager._log_history()

    manager.disconnect()

    assert manager.db.get_sessions(ICCID_A)[0]["ended_at"] is not None
    assert manager._session_id is None


def test_no_session_without_an_iccid(manager):
    manager._log_history()
    assert manager._session_id is None
    assert manager.db.get_sessions(ICCID_A) == []
