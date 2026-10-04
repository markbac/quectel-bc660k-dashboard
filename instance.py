"""Track the running dashboard instance so a stale one can be stopped safely.

The dashboard writes its process id to a PID file beside this module at
start-up. When the serial port is busy, only the process recorded in that file
is considered for termination, never an arbitrary Python process. The file
also records when that process started, so a recycled PID that now belongs to
an unrelated program is never terminated.
"""
import json
import os
import signal
from typing import Optional

import psutil

PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.pid")


def _start_time(pid: int) -> Optional[float]:
    """Return the start time of a process, or None if it is not running."""
    try:
        return psutil.Process(pid).create_time()
    except (psutil.Error, OSError):
        return None


def write_pid_file(path: Optional[str] = None) -> None:
    """Record this process id, its start time and the install directory."""
    path = path or PID_FILE
    data = {"pid": os.getpid(), "dir": os.path.dirname(os.path.abspath(__file__)),
            "start": _start_time(os.getpid())}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def remove_pid_file(path: Optional[str] = None) -> None:
    """Delete the PID file if it belongs to this process."""
    path = path or PID_FILE
    if read_stale_pid(path, include_self=True) == os.getpid():
        try:
            os.remove(path)
        except OSError:
            pass


def read_stale_pid(path: Optional[str] = None, include_self: bool = False) -> Optional[int]:
    """Return the PID of another instance of this dashboard, or None.

    The PID file is ignored when it is missing, malformed, written by a
    different install directory, or names the current process. A file without
    a start time (written by an older version) is also ignored, because the
    PID cannot be proven to still belong to the dashboard.
    """
    path = path or PID_FILE
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        pid = int(data["pid"])
        directory = data["dir"]
        start = None if data.get("start") is None else float(data["start"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if directory != os.path.dirname(os.path.abspath(__file__)):
        return None
    if pid == os.getpid() and not include_self:
        return None
    if start is None:
        return None
    current = _start_time(pid)
    if current is None or abs(current - start) > 1.0:
        return None
    return pid


def terminate_stale_instance(path: Optional[str] = None) -> Optional[int]:
    """Terminate the previous dashboard instance, if there is one.

    Returns the PID that was signalled, or None if nothing was done.
    """
    pid = read_stale_pid(path)
    if pid is None:
        return None
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return None
    return pid
