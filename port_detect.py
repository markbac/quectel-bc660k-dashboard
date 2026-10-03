"""Find the serial port that has a responding AT modem on it.

Multi-port boards such as the FT4232H evaluation board expose several serial
ports and only one of them carries the module's AT interface. ``detect_at_port``
probes each candidate with ``AT`` and returns the first one that answers ``OK``.
"""
import time
from typing import Callable, Iterable, List, Optional

import serial
import serial.tools.list_ports

# USB vendor IDs of interfaces commonly used with the module: FTDI and Quectel.
PREFERRED_VIDS = (0x0403, 0x2C7C)
PROBE_BAUDS = (115200,)
PROBE_WAIT_SECONDS = 0.6


def _is_preferred(port) -> bool:
    return getattr(port, "vid", None) in PREFERRED_VIDS


def candidate_ports(ports: Optional[Iterable] = None) -> List[str]:
    """Device names to probe, most likely AT ports first.

    :param ports: ``ListPortInfo``-like objects; defaults to the system's ports.
    """
    found = list(serial.tools.list_ports.comports() if ports is None else ports)
    found.sort(key=lambda p: (not _is_preferred(p), p.device))
    return [p.device for p in found]


def answers_at(device: str, baud: int, wait: float = PROBE_WAIT_SECONDS,
               opener: Callable = serial.Serial) -> bool:
    """True if ``device`` replies ``OK`` to ``AT`` at ``baud``.

    Ports that cannot be opened (busy, no permission) count as not answering.
    """
    try:
        with opener(device, baud, timeout=0.2, write_timeout=1.0) as link:
            link.reset_input_buffer()
            link.write(b"AT\r\n")
            deadline = time.monotonic() + wait
            reply = b""
            while time.monotonic() < deadline:
                reply += link.read(64)
                if b"OK" in reply:
                    return True
    except (serial.SerialException, OSError):
        return False
    return False


def detect_at_port(candidates: Optional[Iterable[str]] = None,
                   bauds: Iterable[int] = PROBE_BAUDS,
                   probe: Callable[[str, int], bool] = answers_at) -> Optional[tuple]:
    """Return ``(device, baud)`` of the first port that answers AT, or ``None``."""
    devices = candidate_ports() if candidates is None else list(candidates)
    for device in devices:
        for baud in bauds:
            if probe(device, baud):
                return device, baud
    return None
