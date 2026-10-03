"""Tests for the performance and responsiveness changes (#19)."""
import importlib
import sqlite3
import sys
import threading
import time

import pytest
from starlette.testclient import TestClient

from db_manager import DBManager
from tests.fake_serial import FakeSerial
from tests.test_history_scoping import ICCID_A, state


@pytest.fixture
def db(tmp_path):
    return DBManager(str(tmp_path / "t.db"))


def _age_rows(db, days_old, iccid=ICCID_A):
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE signal_history SET unix_time = ? WHERE iccid = ?", (time.time() - days_old * 86400, iccid))


def test_prune_deletes_only_old_rows(db):
    db.log_record(state(ICCID_A))
    _age_rows(db, 100)
    db.log_record(state(ICCID_A))

    assert db.prune_older_than(30) == 1
    assert db.get_stats(ICCID_A)["total_records"] == 1


def test_prune_zero_disables_it(db):
    db.log_record(state(ICCID_A))
    _age_rows(db, 1000)
    assert db.prune_older_than(0) == 0
    assert db.get_stats(ICCID_A)["total_records"] == 1


def test_prune_removes_ended_sessions_that_have_no_rows(db):
    old = db.start_session(ICCID_A)
    db.log_record(state(ICCID_A), old)
    db.end_session(old)
    live = db.start_session(ICCID_A)
    _age_rows(db, 100)

    db.prune_older_than(30)

    assert [s["id"] for s in db.get_sessions(ICCID_A)] == [live]


def test_retention_runs_at_start_and_then_at_most_daily(manager, monkeypatch):
    manager.retention_days = 30
    calls = []
    monkeypatch.setattr(manager.db, "prune_older_than", lambda days: calls.append(days) or 0)

    manager._prune_if_due()
    manager._prune_if_due()

    assert calls == [30]


def test_retention_disabled_by_default(manager, monkeypatch):
    calls = []
    monkeypatch.setattr(manager.db, "prune_older_than", lambda days: calls.append(days) or 0)
    manager._prune_if_due()
    assert calls == []


def test_a_console_command_does_not_wait_for_the_whole_poll_cycle(manager):
    """Regression test for #19: the lock used to be held for the full cycle."""
    manager.running = True
    manager.ser = FakeSerial({}, write_delay=0.15)
    poller = threading.Thread(target=manager._poll_once, daemon=True)
    poller.start()
    time.sleep(0.2)  # the poll cycle is under way (a full cycle takes over a second)

    start = time.time()
    manager.send_at_command("AT")
    waited = time.time() - start
    poller.join(timeout=10)

    assert waited < 0.6, f"console command waited {waited:.2f}s"


def test_state_sent_to_browsers_has_no_log_lines(manager, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["server.py", "--no-file-log"])
    monkeypatch.setenv("QUECTEL_DASHBOARD_DB", str(tmp_path / "s.db"))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    server.manager.log("something happened", "INFO")
    assert server.manager.state["logs"]

    assert "logs" not in server.public_state(server.manager.state)
    with TestClient(server.app, base_url="http://localhost:8080") as client:
        with client.websocket_connect("/ws", headers={"Host": "localhost:8080"}) as ws:
            assert "logs" not in ws.receive_json()["data"]
