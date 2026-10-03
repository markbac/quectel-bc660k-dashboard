"""Send a fixed set of identification and status commands to a board.

Usage: python tools/validate_board.py PORT [--baud 115200]
"""
import argparse
import time

import serial

COMMANDS = [
    ("AT", "Ping Check"),
    ("ATI", "Module Information"),
    ("AT+GMR", "Firmware Revision"),
    ("AT+CPIN?", "SIM PIN Status"),
    ("AT+QCCID", "SIM Card ICCID"),
    ("AT+CIMI", "SIM IMSI Subscriber ID"),
    ("AT+CSQ", "Signal Quality (CSQ)"),
    ("AT+CBC", "Supply Voltage (mV)"),
    ("AT+QTEMP", "Module Temperature (°C)"),
    ('AT+QENG="servingcell"', "Serving Cell Parameters"),
    ("AT+COPS?", "Current Registered Operator"),
    ("AT+CEREG?", "Network Registration Status"),
]


def main() -> None:
    """Run every command in ``COMMANDS`` on the given port and print the replies."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port", help="serial port, e.g. COM3 or /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    try:
        with serial.Serial(args.port, args.baud, timeout=2.0) as ser:
            print(f"Connected to {args.port} @ {args.baud} baud\n")
            for cmd, desc in COMMANDS:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                print(f"--- Sending {cmd} ({desc}) ---")
                ser.write(f"{cmd}\r\n".encode("ascii"))
                time.sleep(0.4)
                print(ser.read_all().decode("ascii", errors="replace").strip())
                print("-" * 50)
                time.sleep(0.2)
    except serial.SerialException as exc:
        raise SystemExit(f"Error opening {args.port}: {exc}")
    print("\nValidation complete.")


if __name__ == "__main__":
    main()
