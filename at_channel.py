"""AT command channel: one place that talks to the modem over a serial port.

The channel owns the details every AT command needs:

* a per-command timeout table taken from the BC660K-GL AT Commands Manual,
* discarding stale input before a command and late output after a timeout,
* waiting for the real end of a response, including results that arrive after
  ``OK`` (``AT+QPING``, ``AT+QIDNSGIP``) through ``wait_for``,
* splitting unsolicited result codes (URCs) from command responses,
* optional retries after a timeout, and
* logging.

It holds no modem state of its own. The owner supplies callbacks for the
events it cares about. Callers serialise access with their own lock.
"""
import re
import time
from typing import Callable, Optional, Pattern

# Maximum response times from the BC660K-GL AT Commands Manual V1.3, plus a
# margin. Matched by prefix, first match wins, on the upper-cased command.
AT_TIMEOUTS = (
    ("AT+CGATT=", 70.0),
    # The manual says 35 s, but a real BC660K-GL took about 300 s to answer a
    # scan (and stayed silent for 180 s while registered), so allow ten minutes.
    ("AT+COPS=?", 600.0),
    ("AT+QENG", 15.0),
    ("AT+CSQ", 5.0),
    ("AT+CESQ", 5.0),
    ("AT+CGPADDR", 5.0),
    ("AT+CGMR", 5.0),
    ("AT+CGSN", 5.0),
    ("ATI", 5.0),
)
DEFAULT_AT_TIMEOUT = 5.0

TIMEOUT_RESPONSE = "ERROR: Timeout"

# Lines that mark the end of a command response.
FINAL_RESULT = re.compile(r"(?m)^(?:OK|ERROR|\+CME ERROR:.*|\+CMS ERROR:.*)\s*$")

# Unsolicited result codes that may be interleaved with a response.
URC_PREFIXES = ("+CEREG", "+CSCON", "+QNBIOTEVENT", "+CGEV", "+CREG", "+CGREG", "+CPIN", "+PSM_EINT")


def timeout_for(cmd: str, default: float = DEFAULT_AT_TIMEOUT) -> float:
    """Return the response timeout in seconds for an AT command."""
    normalised = cmd.strip().upper().replace(" ", "")
    for prefix, seconds in AT_TIMEOUTS:
        if normalised.startswith(prefix):
            return seconds
    return default


def _ignore(*_args) -> None:
    """Default for callbacks the owner does not need."""


class ATChannel:
    """Sends AT commands on a serial port and returns their responses."""

    def __init__(
        self,
        get_port: Callable[[], object],
        log: Callable[[str, str], None],
        on_urc: Callable[[str], None] = _ignore,
        on_response: Callable[[], None] = _ignore,
        on_timeout: Callable[[], None] = _ignore,
        on_exchange: Callable[[str, str, float], None] = _ignore,
    ):
        """Create a channel.

        Args:
            get_port: Returns the open serial port, or None when there is none.
            log: ``log(text, direction)`` with direction ``TX``, ``RX``, ``INFO``,
                ``WARNING`` or ``ERROR``.
            on_urc: Called with every line of unsolicited output.
            on_response: Called when the modem answered a command.
            on_timeout: Called when it did not.
            on_exchange: Called with ``(command, response, seconds)`` for every
                answered command, for recording transcripts.
        """
        self._get_port = get_port
        self._log = log
        self._on_urc = on_urc
        self._on_response = on_response
        self._on_timeout = on_timeout
        self._on_exchange = on_exchange

    @staticmethod
    def is_ok(resp: str) -> bool:
        """True when a response contains a final ``OK`` line."""
        return bool(re.search(r"(?m)^OK\s*$", resp))

    def send(
        self,
        cmd: str,
        timeout_sec: Optional[float] = None,
        wait_for: Optional[Pattern[str]] = None,
        retries: int = 0,
    ) -> str:
        """Send one AT command and return its response.

        Args:
            cmd: The command, with or without a trailing CR LF.
            timeout_sec: Defaults to the documented maximum for the command
                (see ``AT_TIMEOUTS``).
            wait_for: A pattern that must also appear before the response is
                complete, for commands that answer ``OK`` first and deliver
                the result later. On timeout the partial response is returned.
            retries: Extra attempts after a timeout (not after an ``ERROR``).

        Returns:
            The response text, ``"ERROR: Timeout"`` if the modem stayed silent,
            or ``"ERROR: Port not open"``.
        """
        resp = self._send_once(cmd, timeout_sec, wait_for)
        for _ in range(retries):
            if resp != TIMEOUT_RESPONSE:
                break
            resp = self._send_once(cmd, timeout_sec, wait_for)
        return resp

    def read_idle(self) -> str:
        """Read unsolicited output that arrived between commands."""
        port = self._get_port()
        if not port or not port.is_open:
            return ""
        text = self._drain(port)
        if text.strip():
            self._log(f"URC< {text.strip()}", "RX")
            self._dispatch(text)
        return text

    # --- internals -----------------------------------------------------------

    def _dispatch(self, text: str) -> None:
        for line in text.splitlines():
            if line.strip():
                self._on_urc(line)

    @staticmethod
    def _drain(port, quiet_sec: float = 0.0, max_sec: float = 0.0) -> str:
        """Read and discard pending input.

        With ``quiet_sec`` set, keep reading until the line has been quiet for
        that long (or ``max_sec`` elapses), so a late reply cannot leak into
        the next command.
        """
        discarded = ""
        deadline = time.time() + max_sec
        last_data = time.time()
        while True:
            if port.in_waiting > 0:
                discarded += port.read(port.in_waiting).decode("ascii", errors="replace")
                last_data = time.time()
            elif quiet_sec <= 0 or time.time() - last_data >= quiet_sec or time.time() >= deadline:
                break
            else:
                time.sleep(0.02)
        return discarded

    def _split_urcs(self, cmd: str, response: str) -> str:
        """Remove unsolicited lines from a response and report them.

        A line is kept when it belongs to the command itself, for example the
        ``+CEREG:`` line returned for ``AT+CEREG?``.
        """
        own = re.match(r"AT(\+[A-Z0-9_]+)", cmd.upper())
        own_prefix = own.group(1) if own else ""
        kept = []
        for line in response.splitlines(keepends=True):
            stripped = line.strip()
            is_urc = stripped.startswith(URC_PREFIXES) and not (
                own_prefix and stripped.upper().startswith(own_prefix)
            )
            if is_urc:
                self._log(f"URC< {stripped}", "RX")
                self._on_urc(stripped)
            else:
                kept.append(line)
        return "".join(kept)

    def _send_once(self, cmd: str, timeout_sec: Optional[float], wait_for: Optional[Pattern[str]]) -> str:
        port = self._get_port()
        if not port or not port.is_open:
            return "ERROR: Port not open"

        if timeout_sec is None:
            timeout_sec = timeout_for(cmd)
        cmd_str = cmd if cmd.endswith("\r\n") else cmd + "\r\n"

        self._log(f"TX> {cmd_str.strip()}", "TX")
        try:
            stale = self._drain(port)
            if stale.strip():
                self._log(f"[STALE] Discarded unread output before '{cmd.strip()}': {stale.strip()!r}", "WARNING")
                self._dispatch(stale)

            port.write(cmd_str.encode("ascii", errors="ignore"))
            response = ""
            start = time.time()
            timed_out = True

            while time.time() - start < timeout_sec:
                if port.in_waiting > 0:
                    response += port.read(port.in_waiting).decode("ascii", errors="replace")
                    if FINAL_RESULT.search(response) and (wait_for is None or wait_for.search(response)):
                        timed_out = False
                        break
                else:
                    time.sleep(0.02)

            if timed_out:
                late = self._drain(port, quiet_sec=0.3, max_sec=1.0)
                if late.strip():
                    self._log(f"[LATE] Discarded late output after timeout: {late.strip()!r}", "WARNING")
                if not response:
                    self._log(f"[TIMEOUT] No response for '{cmd.strip()}' after {timeout_sec}s.", "ERROR")
                    self._on_timeout()
                    return TIMEOUT_RESPONSE

            self._on_response()
            response = self._split_urcs(cmd, response)
            self._log(f"RX< {response.strip()}", "RX")
            self._on_exchange(cmd, response, time.time() - start)
            return response
        except Exception as e:  # serial I/O can fail in many platform specific ways
            self._log(f"[SERIAL IO ERROR] TX/RX failure on {cmd.strip()}: {e}", "ERROR")
            return f"ERROR: {e}"
