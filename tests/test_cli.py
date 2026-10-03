"""Tests for command line parsing."""
import pytest

import cli


def test_defaults_are_local_and_do_not_connect():
    args = cli.parse_args([])
    assert args.host == "127.0.0.1"
    assert args.http_port == 8080
    assert args.port is None
    assert not args.no_browser


def test_flags_are_parsed():
    args = cli.parse_args(["--host", "::1", "--http-port", "9000", "--no-browser",
                           "--port", "/dev/ttyUSB0", "--db-path", "x.db"])
    assert (args.host, args.http_port, args.no_browser) == ("::1", 9000, True)
    assert (args.port, args.db_path) == ("/dev/ttyUSB0", "x.db")


def test_non_loopback_host_is_refused():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--host", "0.0.0.0"])


def test_unknown_options_are_ignored():
    assert cli.parse_args(["-q", "--no-browser"]).no_browser


@pytest.mark.parametrize("host,port,url", [
    ("127.0.0.1", 8080, "http://127.0.0.1:8080"),
    ("localhost", 9000, "http://localhost:9000"),
    ("::1", 8080, "http://[::1]:8080"),
])
def test_server_url(host, port, url):
    assert cli.server_url(host, port) == url
