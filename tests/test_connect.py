"""Tests for SerialManager.connect()."""
import threading


def test_connect_to_missing_port_returns_false_without_deadlock(manager):
    """Regression test for #11: a failed open must not deadlock on the lock."""
    result = {}

    def target():
        result["ok"] = manager.connect("/dev/does-not-exist", 115200)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=5)

    assert not thread.is_alive(), "connect() deadlocked"
    assert result["ok"] is False
    assert manager.is_connected is False
    assert manager.state["connected"] is False
    assert manager.state["mode"] == "DISCONNECTED"


def test_lock_is_released_after_failed_connect(manager):
    """The lock must be free so later operations (e.g. demo mode) can run."""
    manager.connect("/dev/does-not-exist", 115200)
    assert manager.lock.acquire(timeout=1)
    manager.lock.release()
