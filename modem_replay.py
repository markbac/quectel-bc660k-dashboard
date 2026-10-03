"""Fake modems on a pseudo-terminal, for tests and for ``--replay``.

``PtyModem`` answers from a fixed script. ``TranscriptModem`` replays a
recorded AT transcript (see ``transcript.py``): each command gets its recorded
replies in order, repeating the last one, so a whole session can be played back
through the real serial code path.
"""
import os
import threading
import time
from typing import Dict, Iterable, List, Tuple, Union

import serial

# command -> (delay in seconds, reply text), or a list of such chunks sent in
# order, each delay counted from the previous chunk
Chunk = Tuple[float, str]
Script = Dict[str, Union[Chunk, List[Chunk]]]


class PtyModem:
    """Answers AT commands read from a pty, with optional per-command delay."""

    def __init__(self, script: Script):
        self.script = script
        self.master, slave = os.openpty()
        self.slave_name = os.ttyname(slave)
        self._slave = slave
        self.received: List[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> serial.Serial:
        """Start the modem thread and return an open client port."""
        self._thread.start()
        return serial.Serial(self.slave_name, 115200, timeout=0.2)

    def inject(self, text: str) -> None:
        """Write unsolicited output (a URC) from the modem side."""
        os.write(self.master, text.encode("ascii"))

    def _run(self) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = os.read(self.master, 256)
            except OSError:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode("ascii").strip()
                if not cmd:
                    continue
                self.received.append(cmd)
                threading.Thread(target=self._reply, args=(self._chunks_for(cmd),), daemon=True).start()

    def _chunks_for(self, cmd: str) -> List[Chunk]:
        """Reply chunks for ``cmd``; unknown commands get a plain ``OK``."""
        chunks = self.script.get(cmd, (0.0, "\r\nOK\r\n"))
        return [chunks] if isinstance(chunks, tuple) else chunks

    def _reply(self, chunks: List[Chunk]) -> None:
        for delay, text in chunks:
            time.sleep(delay)
            try:
                os.write(self.master, text.encode("ascii"))
            except OSError:
                return

    def close(self) -> None:
        self._stop.set()
        for fd in (self.master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass


class TranscriptModem(PtyModem):
    """Replays recorded exchanges (``{"cmd", "reply", "delay"}`` dicts).

    The n-th request for a command gets its n-th recorded reply; once the
    recording runs out the last reply is repeated. Commands that were never
    recorded get ``ERROR``. ``speed`` scales the recorded delays (0 removes them).
    """

    def __init__(self, exchanges: Iterable[dict], speed: float = 1.0):
        super().__init__({})
        self.speed = speed
        self._replies: Dict[str, List[Chunk]] = {}
        self._counts: Dict[str, int] = {}
        for entry in exchanges:
            self._replies.setdefault(entry["cmd"], []).append(
                (float(entry.get("delay", 0.0)) * speed, entry["reply"]))

    def _chunks_for(self, cmd: str) -> List[Chunk]:
        recorded = self._replies.get(cmd)
        if not recorded:
            return [(0.0, "\r\nERROR\r\n")]
        index = self._counts.get(cmd, 0)
        self._counts[cmd] = index + 1
        return [recorded[min(index, len(recorded) - 1)]]
