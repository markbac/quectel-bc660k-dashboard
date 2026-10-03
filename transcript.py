"""Record AT exchanges to a JSON Lines file, with identifiers redacted.

Each line is ``{"cmd": ..., "reply": ..., "delay": ...}``. Recordings can be
replayed with ``modem_replay.TranscriptModem`` (``server.py --replay FILE``).
Only the SIM and module identifiers listed below are redacted; check a
recording before sharing it, since cell identities and locations are kept.
"""
import json
import re
import threading
from typing import Dict, List

# Longest patterns first so a 20 digit ICCID is not mistaken for something shorter.
_ICCID = re.compile(r"(?<!\d)89\d{17,18}(?!\d)")
_IMSI_OR_IMEI = re.compile(r"(?<!\d)\d{15}(?!\d)")
_FAKE_IMSI_IMEI = "001010000000001"


def redact(text: str) -> str:
    """Replace ICCIDs, IMSIs and IMEIs with fixed fake values of the same length."""
    text = _ICCID.sub(lambda m: "89" + "0" * (len(m.group()) - 3) + "1", text)
    return _IMSI_OR_IMEI.sub(_FAKE_IMSI_IMEI, text)


class TranscriptRecorder:
    """Thread-safe appender of redacted AT exchanges."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._file = open(path, "a", encoding="utf-8")

    def record(self, cmd: str, reply: str, delay: float) -> None:
        """Append one exchange; ``delay`` is the modem's response time in seconds."""
        entry = {"cmd": redact(cmd.strip()), "reply": redact(reply), "delay": round(delay, 3)}
        with self._lock:
            if self._file.closed:
                return
            self._file.write(json.dumps(entry) + "\n")
            self._file.flush()

    def close(self) -> None:
        """Close the file; later ``record`` calls are ignored."""
        with self._lock:
            self._file.close()


def load_transcript(path: str) -> List[Dict]:
    """Read the exchanges of a recording, in order."""
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
