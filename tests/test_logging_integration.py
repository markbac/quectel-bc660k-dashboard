"""Logging goes through the py-logkit package, not print() or a vendored copy."""
import importlib
import logging
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def server_module(tmp_path, monkeypatch):
    """Import ``server`` with the file log in a temp directory."""
    monkeypatch.setenv("QUECTEL_DASHBOARD_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(sys, "argv", ["server.py", "--no-file-log"])
    sys.modules.pop("server", None)
    module = importlib.import_module("server")
    yield module
    module.manager.set_file_logging(False)


def test_pylogkit_is_the_installed_package_not_a_vendored_copy():
    assert not (ROOT / "pylogkit").exists()
    import pylogkit
    assert "site-packages" in pylogkit.__file__ or "dist-packages" in pylogkit.__file__


def test_pylogkit_is_a_declared_dependency():
    for name in ("requirements.txt", "pyproject.toml"):
        assert "github.com/markbac/py-logkit" in (ROOT / name).read_text(), name


def test_server_has_no_print_calls():
    source = (ROOT / "server.py").read_text()
    assert not re.search(r"^\s*print\(", source, re.M)


def test_uvicorn_records_reach_the_manager_file(server_module, tmp_path):
    manager = server_module.manager
    manager.log_file_path = str(tmp_path / "serial.log")
    manager.set_file_logging(True)
    server_module.route_uvicorn_logs()

    logging.getLogger("uvicorn.error").info("uvicorn says hello")
    manager.set_file_logging(False)

    text = (tmp_path / "serial.log").read_text(encoding="utf-8")
    assert "uvicorn says hello" in text


def test_server_logger_shares_the_manager_handlers(server_module, tmp_path):
    manager = server_module.manager
    manager.log_file_path = str(tmp_path / "serial.log")
    manager.set_file_logging(True)

    server_module.log.info("server says hello")
    manager.set_file_logging(False)

    assert "server says hello" in (tmp_path / "serial.log").read_text(encoding="utf-8")
