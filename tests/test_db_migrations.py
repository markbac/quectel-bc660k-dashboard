"""Tests for versioned schema migrations."""
import glob
import sqlite3

import pytest

import db_manager
from db_manager import DBManager, SchemaTooNewError, latest_schema_version


def _version(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def _indexes(path):
    with sqlite3.connect(path) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}


def _make_legacy(path, version=None):
    """A database as created by the code before versioning (table, no version)."""
    with sqlite3.connect(path) as conn:
        db_manager._migration_1_create_history(conn)
        conn.execute("INSERT INTO signal_history (unix_time, rsrp, iccid) VALUES (1.0, -90, 'X')")
        if version is not None:
            conn.execute(f"PRAGMA user_version = {version}")


def test_fresh_database_is_created_at_the_latest_version(tmp_path):
    path = str(tmp_path / "t.db")
    DBManager(path)
    assert _version(path) == latest_schema_version()
    assert "idx_iccid_time" in _indexes(path)
    assert not glob.glob(path + ".bak-*"), "no backup for a brand new database"


@pytest.mark.parametrize("start_version", [None, 1])
def test_older_databases_migrate_and_keep_their_rows(tmp_path, start_version):
    path = str(tmp_path / "t.db")
    _make_legacy(path, start_version)

    db = DBManager(path)

    assert _version(path) == latest_schema_version()
    assert "idx_iccid_time" in _indexes(path)
    assert db.get_stats("X")["total_records"] == 1


def test_a_backup_is_taken_before_migrating(tmp_path):
    path = str(tmp_path / "t.db")
    _make_legacy(path)

    DBManager(path)

    backups = glob.glob(path + ".bak-v*")
    assert backups == [path + ".bak-v1"]
    assert _version(backups[0]) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM signal_history").fetchone()[0] == 1


def test_running_migrations_twice_changes_nothing(tmp_path):
    path = str(tmp_path / "t.db")
    _make_legacy(path)
    DBManager(path)
    before = sorted(glob.glob(path + "*"))

    db = DBManager(path)

    assert sorted(glob.glob(path + "*")) == before  # no second backup
    assert db.get_stats("X")["total_records"] == 1
    assert _version(path) == latest_schema_version()


def test_failed_migration_leaves_the_original_intact(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    _make_legacy(path)

    def broken(conn):
        conn.execute("CREATE TABLE half_done (x)")
        raise RuntimeError("boom")

    monkeypatch.setattr(db_manager, "MIGRATIONS", db_manager.MIGRATIONS + [broken])

    with pytest.raises(RuntimeError, match="boom"):
        DBManager(path)

    assert _version(path) == latest_schema_version() - 1  # earlier migrations stay applied
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "half_done" not in tables
        assert conn.execute("SELECT COUNT(*) FROM signal_history").fetchone()[0] == 1


def test_database_from_a_newer_version_is_refused(tmp_path):
    path = str(tmp_path / "t.db")
    _make_legacy(path, latest_schema_version() + 1)

    with pytest.raises(SchemaTooNewError, match="schema version"):
        DBManager(path)

    assert _version(path) == latest_schema_version() + 1  # untouched
    assert not glob.glob(path + ".bak-*")
