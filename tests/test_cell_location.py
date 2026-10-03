"""Tests for the OpenCellID lookup (#4)."""
import importlib
import sys
import urllib.parse

import pytest
from starlette.testclient import TestClient

import cell_location
from cell_location import CellLocator, CellNotFound, LookupFailed, NoApiKey

REPLY = {"lat": 51.5, "lon": -0.12, "range": 1500, "mcc": 234}


def locator(fetch, key="secret-key"):
    return CellLocator(fetch=fetch, key=lambda: key)


def test_lookup_builds_the_query_and_parses_the_reply():
    seen = []

    def fetch(url):
        seen.append(url)
        return REPLY

    result = locator(fetch).locate("234", "15", 24378, 26379000)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(seen[0]).query)
    assert result == {"lat": 51.5, "lon": -0.12, "range": 1500}
    assert (query["mcc"], query["mnc"], query["lac"], query["cellid"], query["radio"]) == (
        ["234"], ["15"], ["24378"], ["26379000"], ["LTE"])


def test_leading_zero_mnc_is_sent_as_a_number():
    seen = []
    locator(lambda url: seen.append(url) or REPLY).locate("001", "01", 1, 2)
    assert "mnc=1&" in seen[0] and "mcc=1&" in seen[0]


def test_answers_are_cached():
    calls = []
    loc = locator(lambda url: calls.append(url) or REPLY)
    loc.locate(234, 15, 1, 2)
    loc.locate(234, 15, 1, 2)
    assert len(calls) == 1


def test_missing_key_is_reported_before_any_request():
    calls = []
    with pytest.raises(NoApiKey, match="QUECTEL_OPENCELLID_KEY"):
        locator(lambda url: calls.append(url), key=None).locate(234, 15, 1, 2)
    assert calls == []


@pytest.mark.parametrize("args", [("--", "--", "--", "--"), (None, 1, 1, 1), (234, 15, "--", 5)])
def test_unknown_cell_values_are_not_looked_up(args):
    calls = []
    with pytest.raises(CellNotFound):
        locator(lambda url: calls.append(url)).locate(*args)
    assert calls == []


@pytest.mark.parametrize("reply", [{}, {"error": "x"}, {"lat": "n/a", "lon": 1}])
def test_replies_without_a_position_mean_not_found(reply):
    with pytest.raises(CellNotFound):
        locator(lambda url: reply).locate(234, 15, 1, 2)


def test_range_may_be_absent():
    assert locator(lambda url: {"lat": 1, "lon": 2}).locate(1, 1, 1, 1)["range"] is None


def test_network_errors_do_not_leak_the_key(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("name resolution failed")

    monkeypatch.setattr(cell_location.urllib.request, "urlopen", boom)
    with pytest.raises(LookupFailed) as info:
        CellLocator(key=lambda: "secret-key").locate(234, 15, 1, 2)
    assert "secret-key" not in str(info.value)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["server.py", "--no-file-log"])
    monkeypatch.setenv("QUECTEL_DASHBOARD_DB", str(tmp_path / "api.db"))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="http://localhost:8080") as client:
        yield server, client


def test_status_never_returns_the_key(api, monkeypatch):
    _, client = api
    monkeypatch.setenv("QUECTEL_OPENCELLID_KEY", "secret-key")
    body = client.get("/api/cell_location").json()
    assert body == {"configured": True}


def test_endpoint_uses_the_serving_cell(api):
    server, client = api
    server.cell_locator = locator(lambda url: REPLY)
    server.manager.state["serving_cell"].update(mcc="234", mnc="15", tac_dec=100, cell_id_dec=200)
    assert client.post("/api/cell_location").json() == {"lat": 51.5, "lon": -0.12, "range": 1500}


@pytest.mark.parametrize("error,status", [(NoApiKey("no key"), 400), (CellNotFound("nope"), 404),
                                          (LookupFailed("down"), 502)])
def test_endpoint_maps_errors_to_statuses(api, error, status):
    server, client = api

    class Failing:
        def locate(self, *args):
            raise error

    server.cell_locator = Failing()
    response = client.post("/api/cell_location")
    assert response.status_code == status
    assert response.json()["detail"] == str(error)
