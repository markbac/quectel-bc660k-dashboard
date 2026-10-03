"""A missing or hidden py-logkit gives a clear message, not a traceback (#107)."""
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

import startup_check

ROOT = Path(__file__).resolve().parent.parent


def test_not_installed_says_how_to_install(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    message = startup_check.pylogkit_help(ImportError("boom"))
    assert "pip install -r requirements.txt" in message
    assert "git+https://github.com/markbac/py-logkit" in message
    assert "run_dashboard.ps1" in message
    assert "boom" in message


def test_empty_folder_is_named_so_it_can_be_deleted(monkeypatch):
    spec = importlib.machinery.ModuleSpec("pylogkit", None, is_package=True)
    spec.submodule_search_locations = [r"D:\MyStuff\quectel-bc660k-dashboard\pylogkit"]
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: spec)
    message = startup_check.pylogkit_help()
    assert r"D:\MyStuff\quectel-bc660k-dashboard\pylogkit" in message
    assert "Delete that folder" in message


def test_importing_the_manager_without_pylogkit_exits_with_the_message():
    code = "import sys; sys.modules['pylogkit'] = None; import serial_manager"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 1
    assert "py-logkit logging package could not be imported" in result.stderr
    assert "Traceback" not in result.stderr


def test_launcher_script_covers_the_setup_steps():
    script = (ROOT / "run_dashboard.ps1").read_text(encoding="utf-8")
    for needle in ("3, 10", "git", "-m venv", "requirements.txt", "server.py", "pylogkit"):
        assert needle in script, needle


def test_launcher_does_not_stop_on_native_stderr():
    """Windows PowerShell treats redirected native stderr as an error under Stop (#109)."""
    script = (ROOT / "run_dashboard.ps1").read_text(encoding="utf-8")
    assert '$ErrorActionPreference = "Stop"' not in script
    assert "2>$null" not in script
