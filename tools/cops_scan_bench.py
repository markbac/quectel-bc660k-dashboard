"""Check whether ``AT+COPS=?`` answers on a BC660K when it is not registered.

Close the dashboard first, because only one program can hold the port.

Usage: python tools/cops_scan_bench.py PORT [--baud 115200] [--timeout 300]
                                       [--also-registered]

What it does, in order:

1. Wakes the module and records its current ``CFUN``, ``CEREG``, ``COPS`` and
   ``QSCLK`` settings.
2. Optionally (``--also-registered``) tries ``AT+COPS=?`` as it is now.
3. Turns the module's sleep clock off (``AT+QSCLK=0``) if it was on.
4. Deregisters with ``AT+COPS=2`` and runs ``AT+COPS=?``, printing the raw
   reply and how long it took.
5. Always restores the original operator selection and ``QSCLK`` value, then
   waits for the module to register again.

The module is off the network while step 4 runs, so do not use it for anything
else at the same time.
"""
import argparse
import re
import sys
import time
from typing import List, Optional

import serial

FINAL = re.compile(r"(?m)^(OK|ERROR|\+CME ERROR:.*|\+CMS ERROR:.*)\s*$")
COPS_QUERY = re.compile(r'\+COPS:\s*(\d+)(?:,(\d+),"([^"]*)"(?:,(\d+))?)?')
REGISTERED = (1, 5)


def send(link: serial.Serial, command: str, timeout: float, progress: bool = False) -> str:
    """Send ``command`` and return everything received up to a final result code.

    :param link: open serial port.
    :param command: AT command without the line ending.
    :param timeout: seconds to wait for ``OK`` or an error.
    :param progress: print a dot every 10 s while waiting.
    :returns: the raw text received (possibly empty on a timeout).
    """
    link.reset_input_buffer()
    link.write(command.encode("ascii") + b"\r\n")
    started = time.monotonic()
    last_dot = started
    text = ""
    while time.monotonic() - started < timeout:
        text += link.read(256).decode("ascii", errors="replace")
        if FINAL.search(text):
            break
        if progress and time.monotonic() - last_dot >= 10:
            print(".", end="", flush=True)
            last_dot = time.monotonic()
    if progress:
        print()
    return text


def show(link: serial.Serial, command: str, timeout: float = 10.0, progress: bool = False) -> str:
    """Run ``command``, print the raw reply with its timing, and return the reply."""
    started = time.monotonic()
    reply = send(link, command, timeout, progress)
    took = time.monotonic() - started
    outcome = "no final result" if not FINAL.search(reply) else "done"
    print(f"{command:<16} {took:6.1f}s  {outcome:<15} {reply.strip()!r}")
    return reply


def wake(link: serial.Serial) -> bool:
    """Send ``AT`` until the module answers ``OK``; a sleeping one needs a second."""
    for _ in range(5):
        if "OK" in send(link, "AT", 3.0):
            return True
    return False


def restore_command(cops_reply: str) -> str:
    """The ``AT+COPS=`` command that puts back the selection in ``cops_reply``."""
    match = COPS_QUERY.search(cops_reply)
    if not match or match.group(2) is None:
        return "AT+COPS=0"
    mode, fmt, oper, act = match.groups()
    command = f'AT+COPS={mode},{fmt},"{oper}"'
    return command + (f",{act}" if act else "")


def registered(cereg_reply: str) -> bool:
    """True if an ``AT+CEREG?`` reply reports home (1) or roaming (5)."""
    match = re.search(r"\+CEREG:\s*\d+,(\d+)", cereg_reply)
    return bool(match) and int(match.group(1)) in REGISTERED


def wait_for_registration(link: serial.Serial, seconds: float = 180.0) -> bool:
    """Poll ``AT+CEREG?`` until registered or ``seconds`` pass."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if registered(send(link, "AT+CEREG?", 5.0)):
            return True
        time.sleep(5)
    return False


def run(link: serial.Serial, timeout: float, also_registered: bool) -> List[str]:
    """Run the bench on an open port and return a list of summary lines."""
    summary: List[str] = []
    if not wake(link):
        return ["The module did not answer AT."]
    send(link, "ATE0", 3.0)

    print("Starting state")
    show(link, "AT+CFUN?")
    show(link, "AT+CEREG?")
    original_cops = show(link, "AT+COPS?")
    qsclk_reply = show(link, "AT+QSCLK?")
    restore = restore_command(original_cops)
    qsclk_was = re.search(r"\+QSCLK:\s*(\d)", qsclk_reply)

    try:
        if also_registered:
            print(f"\nAT+COPS=? while registered (up to {timeout:.0f} s)")
            reply = show(link, "AT+COPS=?", timeout, progress=True)
            summary.append("Registered: " + ("answered" if "+COPS:" in reply else "no answer"))

        if qsclk_was and qsclk_was.group(1) != "0":
            print("\nTurning the sleep clock off")
            show(link, "AT+QSCLK=0")

        print("\nDeregistering")
        show(link, "AT+COPS=2", 60.0)
        show(link, "AT+CEREG?")

        print(f"\nAT+COPS=? while not registered (up to {timeout:.0f} s)")
        reply = show(link, "AT+COPS=?", timeout, progress=True)
        answered = "+COPS:" in reply
        summary.append("Not registered: " + ("answered" if answered else "no answer"))
    finally:
        print("\nRestoring")
        wake(link)
        show(link, restore, 60.0)
        if qsclk_was and qsclk_was.group(1) != "0":
            show(link, f"AT+QSCLK={qsclk_was.group(1)}")
        ok = wait_for_registration(link)
        summary.append("Registered again: " + ("yes" if ok else "NOT YET, check the module"))
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    """Open the port, run the bench and print a summary."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port", help="serial port, e.g. COM3 or /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=300.0,
                        help="seconds to wait for each AT+COPS=? (default 300)")
    parser.add_argument("--also-registered", action="store_true",
                        help="also try the scan before deregistering, as a control")
    args = parser.parse_args(argv)

    with serial.Serial(args.port, args.baud, timeout=0.2) as link:
        summary = run(link, args.timeout, args.also_registered)
    print("\nSummary")
    for line in summary:
        print(" ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
