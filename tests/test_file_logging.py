"""Tests for the runtime file-logging toggle."""
import os


def _log_text(manager):
    if not os.path.exists(manager.log_file_path):
        return ""
    with open(manager.log_file_path, encoding="utf-8") as fh:
        return fh.read()


def test_toggle_on_then_off_controls_the_file(manager):
    """Regression test for #13: the toggle used to change only a flag."""
    manager.log("before enabling", "INFO")
    assert "before enabling" not in _log_text(manager)

    manager.set_file_logging(True)
    manager.log("while enabled", "INFO")
    assert "while enabled" in _log_text(manager)

    manager.set_file_logging(False)
    manager.log("after disabling", "INFO")
    assert "after disabling" not in _log_text(manager)


def test_enabling_twice_does_not_duplicate_lines(manager):
    manager.set_file_logging(True)
    manager.set_file_logging(True)
    manager.log("only once", "INFO")
    assert _log_text(manager).count("only once") == 1
