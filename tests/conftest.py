"""Shared pytest fixtures."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serial_manager import SerialManager  # noqa: E402


@pytest.fixture
def manager(tmp_path):
    """A SerialManager using a temporary database and no log file."""
    return SerialManager(
        file_logging_enabled=False,
        db_path=str(tmp_path / "telemetry.db"),
        log_file_path=str(tmp_path / "serial.log"),
    )
