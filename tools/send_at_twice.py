"""Send ``AT`` twice to each given port and print the raw reply.

Usage: python tools/send_at_twice.py PORT [PORT ...] [--baud 115200]
"""
import argparse
import time

import serial


def main() -> None:
    """Probe each port and flag the ones that answer like a modem."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ports", nargs="+", help="serial ports, e.g. COM3 /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    for port in args.ports:
        print(f"\n--- Testing {port} @ {args.baud} baud ---")
        try:
            with serial.Serial(port, args.baud, timeout=1.5) as ser:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                ser.write(b"AT\r\n")
                time.sleep(0.15)
                ser.write(b"AT\r\n")
                time.sleep(0.5)
                reply = ser.read_all()
                print(f"Raw bytes ({len(reply)}): {reply!r}")
                if b"OK" in reply or b"ERROR" in reply:
                    print(f"*** {port} answers AT ***")
        except serial.SerialException as exc:
            print(f"ERROR: could not open {port}: {exc}")


if __name__ == "__main__":
    main()
