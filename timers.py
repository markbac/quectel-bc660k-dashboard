"""Decoding of the 3GPP timer values used by PSM and eDRX.

Timers are 8-bit strings: the top three bits select a unit, the low five bits
are the value (3GPP TS 24.008, sections 10.5.7.3 and 10.5.7.4a).
"""
from typing import Optional

# GPRS timer 3 (T3412 extended value, periodic TAU): unit bits -> seconds per step.
_TIMER3_UNITS = {
    "000": 600,         # 10 minutes
    "001": 3600,        # 1 hour
    "010": 36000,       # 10 hours
    "011": 2,           # 2 seconds
    "100": 30,          # 30 seconds
    "101": 60,          # 1 minute
    "110": 1152000,     # 320 hours
}

# GPRS timer 2 (T3324, active time): unit bits -> seconds per step.
_TIMER2_UNITS = {
    "000": 2,           # 2 seconds
    "001": 60,          # 1 minute
    "010": 360,         # 6 minutes
}

# eDRX cycle length (4-bit value) -> seconds, for E-UTRAN NB-S1 mode.
_EDRX_CYCLES = {
    "0000": 5.12, "0001": 10.24, "0010": 20.48, "0011": 40.96, "0100": 61.44,
    "0101": 81.92, "0110": 102.4, "0111": 122.88, "1000": 143.36, "1001": 163.84,
    "1010": 327.68, "1011": 655.36, "1100": 1310.72, "1101": 2621.44,
}


def _decode(bits: str, units: dict) -> Optional[int]:
    """Return the timer in seconds, or None when invalid or deactivated."""
    if len(bits) != 8 or set(bits) - {"0", "1"}:
        return None
    step = units.get(bits[:3])
    if step is None:
        return None
    return int(bits[3:], 2) * step


def decode_t3412(bits: str) -> Optional[int]:
    """Periodic TAU timer (GPRS timer 3) in seconds."""
    return _decode(bits, _TIMER3_UNITS)


def decode_t3324(bits: str) -> Optional[int]:
    """Active timer (GPRS timer 2) in seconds."""
    return _decode(bits, _TIMER2_UNITS)


def decode_edrx_cycle(bits: str) -> Optional[float]:
    """eDRX cycle length in seconds, from the 4-bit value."""
    return _EDRX_CYCLES.get(bits)


def format_duration(seconds: Optional[float]) -> str:
    """Human readable duration such as ``5 min`` or ``2 h 30 min``."""
    if seconds is None:
        return "off"
    if seconds != int(seconds):
        return f"{seconds:g} s"
    seconds = int(seconds)
    if seconds == 0:
        return "0 s"
    parts = []
    for unit, size in (("h", 3600), ("min", 60), ("s", 1)):
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount} {unit}")
    return " ".join(parts)
