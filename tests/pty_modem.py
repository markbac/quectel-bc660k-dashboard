"""Compatibility import: the pty fake modem now lives in ``modem_replay``."""
from modem_replay import Chunk, PtyModem, Script

__all__ = ["Chunk", "PtyModem", "Script"]
