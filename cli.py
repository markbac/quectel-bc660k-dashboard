"""Command line interface of the dashboard server."""
import argparse
from typing import List, Optional

LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
DEFAULT_HTTP_PORT = 8080


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for ``server.py`` / ``quectel-dashboard``."""
    parser = argparse.ArgumentParser(description="Quectel BC660K Signal & Network Web Dashboard")
    parser.add_argument("--demo", "-d", action="store_true",
                        help="Start dashboard in hardware simulator demo mode")
    parser.add_argument("--port", "-p", type=str, default=None,
                        help="Serial port to connect to on startup, e.g. COM3 or /dev/ttyUSB0; "
                             "'auto' probes every port for an AT modem (default: do not connect)")
    parser.add_argument("--baud", "-b", type=int, default=115200,
                        help="Initial baud rate (default: 115200)")
    parser.add_argument("--host", choices=LOOPBACK_HOSTS, default="127.0.0.1",
                        help="Loopback address the web server listens on (default: 127.0.0.1)")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT, metavar="PORT",
                        help=f"TCP port of the web server (default: {DEFAULT_HTTP_PORT})")
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not open the dashboard in a web browser on startup")
    parser.add_argument("--db-path", type=str, default=None,
                        help="SQLite database file (default: per-user data directory, "
                             "or $QUECTEL_DASHBOARD_DB)")
    parser.add_argument("--retention-days", type=float, default=90,
                        help="Delete history older than this many days (0 keeps everything, default: 90)")
    parser.add_argument("--no-file-log", action="store_true",
                        help="Disable writing serial logs to disk file")
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse ``argv`` (default ``sys.argv[1:]``), ignoring unknown options.

    Unknown options are tolerated so that importing the server under another
    program, such as a test runner, does not fail on that program's flags.
    """
    args, _ = build_parser().parse_known_args(argv)
    return args


def server_url(host: str, port: int) -> str:
    """URL to open in a browser for a server bound to ``host`` and ``port``."""
    shown = f"[{host}]" if ":" in host else host
    return f"http://{shown}:{port}"
