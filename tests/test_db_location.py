"""Tests for database creation and location."""
import os
import sqlite3
import subprocess

import pytest

import db_manager
from db_manager import DBManager, default_db_path


def test_database_and_directory_are_created_on_first_use(tmp_path):
    path = tmp_path / "nested" / "dir" / "telemetry.db"

    DBManager(str(path))

    assert path.exists()
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "signal_history" in tables


def test_existing_data_is_kept_when_reopened(tmp_path):
    path = str(tmp_path / "telemetry.db")
    DBManager(path).log_record({"signal": {"rsrp": -90}})

    assert DBManager(path).get_stats()["total_records"] == 1


def test_env_var_overrides_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv(db_manager.DB_ENV_VAR, str(tmp_path / "x.db"))
    assert default_db_path() == str(tmp_path / "x.db")


def test_default_is_outside_the_source_tree(monkeypatch):
    monkeypatch.delenv(db_manager.DB_ENV_VAR, raising=False)
    source_dir = os.path.dirname(os.path.abspath(db_manager.__file__))
    assert not os.path.abspath(default_db_path()).startswith(source_dir)


def test_default_follows_xdg_data_home_on_linux(monkeypatch, tmp_path):
    monkeypatch.delenv(db_manager.DB_ENV_VAR, raising=False)
    monkeypatch.setattr(db_manager.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_db_path() == str(tmp_path / "quectel-bc660k-dashboard" / "telemetry.db")


def test_no_database_file_is_tracked_by_git():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not running inside a git checkout")
    assert not [f for f in tracked.splitlines() if f.endswith((".db", ".sqlite", ".sqlite3"))]
