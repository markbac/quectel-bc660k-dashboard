"""A fake modem on a pseudo-terminal, for testing the real serial code path."""
import os
import threading
import time
from typing import Callable, Dict, List, Tuple, Union

import serial

# command -> (delay in seconds, reply text)
Script = Dict[str, Tuple[float, str]]


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
                delay, reply = self.script.get(cmd, (0.0, "\r\nOK\r\n"))
                threading.Thread(target=self._reply, args=(delay, reply), daemon=True).start()

    def _reply(self, delay: float, reply: str) -> None:
        time.sleep(delay)
        try:
            os.write(self.master, reply.encode("ascii"))
        except OSError:
            pass

    def close(self) -> None:
        self._stop.set()
        for fd in (self.master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass
