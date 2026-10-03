"""Tests for stale-instance handling when the serial port is busy."""
import json
import os
import subprocess
import sys
import time

import pytest

import instance

SLEEPER = "import time; time.sleep(60)"


@pytest.fixture
def sleeper(tmp_path):
    """A child process that stays alive until the test ends."""
    script = tmp_path / "server.py"  # same file name as the dashboard on purpose
    script.write_text(SLEEPER)
    proc = subprocess.Popen([sys.executable, str(script)])
    yield proc
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def _write_pid(path, pid, directory=None):
    directory = directory or os.path.dirname(os.path.abspath(instance.__file__))
    path.write_text(json.dumps({"pid": pid, "dir": directory}))


def test_unrelated_server_py_is_left_running(manager, sleeper, tmp_path, monkeypatch):
    """Regression test for #23: other 'server.py' processes must survive."""
    monkeypatch.setattr(instance, "PID_FILE", str(tmp_path / "missing.pid"))

    manager._reclaim_port("COM3")

    time.sleep(0.2)
    assert sleeper.poll() is None


def test_stale_dashboard_instance_is_stopped(sleeper, tmp_path):
    pid_file = tmp_path / "dashboard.pid"
    _write_pid(pid_file, sleeper.pid)

    assert instance.terminate_stale_instance(str(pid_file)) == sleeper.pid
    assert sleeper.wait(timeout=5) is not None


def test_pid_file_from_another_install_is_ignored(sleeper, tmp_path):
    pid_file = tmp_path / "dashboard.pid"
    _write_pid(pid_file, sleeper.pid, directory="/some/other/checkout")

    assert instance.read_stale_pid(str(pid_file)) is None
    assert instance.terminate_stale_instance(str(pid_file)) is None
    assert sleeper.poll() is None


def test_own_pid_is_never_returned(tmp_path):
    pid_file = tmp_path / "dashboard.pid"
    instance.write_pid_file(str(pid_file))
    assert instance.read_stale_pid(str(pid_file)) is None
    assert instance.read_stale_pid(str(pid_file), include_self=True) == os.getpid()
    instance.remove_pid_file(str(pid_file))
    assert not pid_file.exists()


@pytest.mark.parametrize("content", ["", "not json", "{}", '{"pid": "x", "dir": "y"}'])
def test_malformed_pid_file_is_ignored(tmp_path, content):
    pid_file = tmp_path / "dashboard.pid"
    pid_file.write_text(content)
    assert instance.read_stale_pid(str(pid_file)) is None
