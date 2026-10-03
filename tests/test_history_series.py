"""Tests for the downsampled history series (#39)."""
import sqlite3

import pytest

from db_manager import DBManager

ICCID = "89000000000000000001"


@pytest.fixture
def db(tmp_path):
    return DBManager(str(tmp_path / "t.db"))


def add_rows(db, count, start=1_000_000.0, step=10.0, iccid=ICCID, session_id=None, rsrp=lambda i: -90):
    with sqlite3.connect(db.db_path) as conn:
        for i in range(count):
            conn.execute(
                "INSERT INTO signal_history (unix_time, rsrp, rsrq, sinr, iccid, session_id) VALUES (?,?,?,?,?,?)",
                (start + i * step, rsrp(i), -10, 5, iccid, session_id),
            )


def test_short_history_is_returned_unchanged(db):
    add_rows(db, 5)
    series = db.get_series(ICCID, max_points=300)
    assert [r["rsrp"] for r in series] == [-90] * 5
    assert [r["unix_time"] for r in series] == sorted(r["unix_time"] for r in series)


def test_long_history_is_downsampled_to_the_limit(db):
    add_rows(db, 1000)
    series = db.get_series(ICCID, max_points=50)
    assert 40 <= len(series) <= 50
    times = [r["unix_time"] for r in series]
    assert times == sorted(times)


def test_buckets_are_averaged(db):
    add_rows(db, 100, rsrp=lambda i: -100 if i < 50 else -80)
    series = db.get_series(ICCID, max_points=2)
    assert [round(r["rsrp"]) for r in series] == [-100, -80]


def test_start_and_end_bound_the_series(db):
    add_rows(db, 100, step=10.0)
    series = db.get_series(ICCID, start_time=1_000_500.0, end_time=1_000_700.0)
    assert len(series) == 21
    assert min(r["unix_time"] for r in series) >= 1_000_500.0


def test_series_is_scoped_to_the_sim(db):
    add_rows(db, 3, iccid=ICCID)
    add_rows(db, 4, iccid="89000000000000000002")
    assert len(db.get_series(ICCID)) == 3


def test_series_can_be_limited_to_a_session(db):
    sid = db.start_session(ICCID, None, None)
    add_rows(db, 3, session_id=sid)
    add_rows(db, 4, start=2_000_000.0, session_id=None)
    assert len(db.get_series(ICCID, session_id=sid)) == 3


@pytest.mark.parametrize("iccid", [None, "", "--"])
def test_no_iccid_gives_empty_series(db, iccid):
    assert db.get_series(iccid) == []


def test_empty_database(db):
    assert db.get_series(ICCID) == []


@pytest.fixture
def api(tmp_path, monkeypatch):
    import importlib
    import sys

    from starlette.testclient import TestClient

    monkeypatch.setattr(sys, "argv", ["server.py", "--no-file-log"])
    monkeypatch.setenv("QUECTEL_DASHBOARD_DB", str(tmp_path / "api.db"))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="http://localhost:8080") as client:
        yield server, client


def test_endpoint_awaits_identity(api):
    _, client = api
    body = client.get("/api/history/series?window=1h").json()
    assert body == {"series": [], "window": "1h", "awaiting_identity": True}


def test_endpoint_windows(api):
    import time

    server, client = api
    server.manager.state["sim_info"]["iccid"] = ICCID
    now = time.time()
    add_rows(server.manager.db, 3, start=now - 100, step=10)
    add_rows(server.manager.db, 2, start=now - 2 * 86400, step=10)

    assert len(client.get("/api/history/series?window=1h").json()["series"]) == 3
    assert len(client.get("/api/history/series?window=24h").json()["series"]) == 3
    assert len(client.get("/api/history/series?window=7d").json()["series"]) == 5
    assert len(client.get("/api/history/series?window=all").json()["series"]) == 5
    assert client.get("/api/history/series?window=session").json()["series"] == []


def test_endpoint_rejects_unknown_window(api):
    _, client = api
    assert client.get("/api/history/series?window=1y").status_code == 422


def test_custom_range_uses_start_and_end(api):
    server, client = api
    server.manager.state["sim_info"]["iccid"] = ICCID
    add_rows(server.manager.db, 100, start=1_000_000.0, step=10.0)

    body = client.get("/api/history/series?window=custom&start=1000500&end=1000700").json()

    assert len(body["series"]) == 21
    assert body["window"] == "custom"


def test_custom_range_may_be_open_ended(api):
    server, client = api
    server.manager.state["sim_info"]["iccid"] = ICCID
    add_rows(server.manager.db, 10, start=1_000_000.0, step=10.0)
    assert len(client.get("/api/history/series?window=custom&start=1000050").json()["series"]) == 5
    assert len(client.get("/api/history/series?window=custom&end=1000050").json()["series"]) == 6


def test_custom_range_rejects_reversed_bounds(api):
    _, client = api
    assert client.get("/api/history/series?window=custom&start=10&end=5").status_code == 422


def test_history_interval_setting(api):
    server, client = api
    assert client.post("/api/settings", json={"history_interval": 30}).status_code == 200
    assert server.manager.history_interval == 30
    assert server.manager.state["history_interval"] == 30
    client.post("/api/settings", json={"history_interval": 0})  # ignored: out of range
    assert server.manager.history_interval == 30
