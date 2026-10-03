"""A network scan keeps the module quiet; that must not look like a dead modem (#83)."""
import time

import at_channel
from tests.fake_serial import FakeSerial


def wait_until(predicate, seconds=10.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_scan_timeouts_allow_three_minutes():
    assert at_channel.timeout_for("AT+COPS=?") == 180.0


def test_silence_during_our_own_scan_is_not_an_unresponsive_modem(manager, monkeypatch):
    monkeypatch.setattr(at_channel, "AT_TIMEOUTS", (("AT+COPS=?", 0.3),))
    manager.state["modem_state"] = "awake"
    manager.ser = FakeSerial({"AT+COPS=?": ""})
    manager.running = True

    manager.trigger_async_cops_scan()
    assert wait_until(lambda: not manager.state["is_scanning"] and manager.state["networks_scan"] == [])

    assert manager.state["modem_state"] == "awake"
    assert manager._wake_hint_shown is False
    texts = [entry["text"] for entry in manager.state["logs"]]
    assert any("SCAN FAILED" in t for t in texts)
    assert not any("HINT" in t for t in texts)


def test_other_silence_still_marks_the_modem_unresponsive(manager):
    manager.state["modem_state"] = "awake"
    manager._on_channel_timeout()
    assert manager.state["modem_state"] == "unresponsive"
    assert manager._wake_hint_shown is True
