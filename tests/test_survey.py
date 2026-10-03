"""Network survey: try every network, rank them, connect to the best (#112)."""
import importlib
import sys
import time
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from at_channel import TIMEOUT_RESPONSE
from survey import NetworkSurvey, cereg_stat, mean, rank, restore_command

SCAN = ('\r\n+COPS: (2,"","","23415",9),(1,"","","23410",9),(3,"","","23420",9),'
        '(1,"","","23430",9),,(0-4),(0-2)\r\n\r\nOK\r\n')


class FakeModule:
    """Answers the commands the survey sends. ``behaviour`` maps PLMN to a CEREG stat."""

    def __init__(self, behaviour, signal, scan=SCAN, original='+COPS: 1,2,"23415",9', qsclk="1"):
        self.behaviour, self.signal, self.scan = behaviour, signal, scan
        self.original, self.qsclk = original, qsclk
        self.sent, self.plmn = [], None

    def send(self, command, timeout=None):
        self.sent.append(command)
        if command == "AT+COPS?":
            return f"\r\n{self.original}\r\n\r\nOK\r\n"
        if command == "AT+QSCLK?":
            return f"\r\n+QSCLK: {self.qsclk}\r\n\r\nOK\r\n"
        if command == "AT+COPS=?":
            return self.scan
        if command.startswith("AT+COPS=1"):
            self.plmn = command.split('"')[1]
            return "\r\nERROR\r\n" if self.behaviour.get(self.plmn) == "error" else "\r\nOK\r\n"
        if command == "AT+COPS=2":
            self.plmn = None
            return "\r\nOK\r\n"
        if command == "AT+CEREG?":
            stat = self.behaviour.get(self.plmn, 0) if self.plmn else 0
            return f"\r\n+CEREG: 4,{0 if stat == 'error' else stat}\r\n\r\nOK\r\n"
        if command == "CELL":
            return self.plmn
        return "\r\nOK\r\n"

    def parse_cell(self, reply):
        if reply not in self.signal:
            return None
        rsrp, rsrq, sinr = self.signal[reply]
        return SimpleNamespace(rsrp=rsrp, rsrq=rsrq, sinr=sinr, pci=299, earfcn=6254, cell_id="1")


def run_survey(module, select_best=True, aborted=lambda: False, **kw):
    parse = importlib.import_module("serial_manager").SerialManager._parse_cops_scan
    published = []
    options = dict(register_wait=2, poll=1, samples=2, sample_gap=0, settle=0, sleep=lambda s: None)
    options.update(kw)
    run = NetworkSurvey(
        send=module.send,
        parse_scan=lambda reply: parse(None, reply),
        parse_cell=module.parse_cell,
        cell_command=lambda: "CELL",
        log=lambda text: None,
        publish=lambda: published.append(dict(run.state)),
        aborted=aborted,
        **options,
    )
    run.run(select_best)
    return run, published


GOOD = {"23415": 5, "23410": 5, "23430": 5}
SIGNAL = {"23415": (-100, -12, 4), "23410": (-90, -10, 8), "23430": (-95, -9, 12)}


def test_connects_to_the_network_with_the_strongest_rsrp():
    module = FakeModule(GOOD, SIGNAL)
    run, _ = run_survey(module)
    assert run.state["best"] == "23410"
    assert run.state["selected"] == "23410"
    assert 'AT+COPS=1,2,"23410",9' == [c for c in module.sent if c.startswith("AT+COPS=1")][-1]
    assert not run.state["running"] and run.state["error"] is None


def test_forbidden_networks_are_not_tried():
    module = FakeModule(GOOD, SIGNAL)
    run, _ = run_survey(module)
    assert not any('"23420"' in c for c in module.sent)
    assert [r["plmn"] for r in run.state["results"]] == ["23415", "23410", "23430"]


def test_denied_error_and_silent_networks_are_reported_and_not_ranked():
    module = FakeModule({"23415": 5, "23410": 3, "23430": 2}, SIGNAL)
    run, _ = run_survey(module)
    status = {r["plmn"]: r["status"] for r in run.state["results"]}
    assert status == {"23415": "registered", "23410": "denied", "23430": "timeout"}
    assert run.state["best"] == "23415"


def test_command_error_counts_as_denied():
    module = FakeModule({"23415": 5, "23410": "error", "23430": 5}, SIGNAL)
    run, _ = run_survey(module)
    assert {r["plmn"]: r["status"] for r in run.state["results"]}["23410"] == "denied"


def test_each_network_is_left_before_the_next_one():
    module = FakeModule(GOOD, SIGNAL)
    run_survey(module, select_best=False)
    commands = [c for c in module.sent if c.startswith("AT+COPS=") and c != "AT+COPS=?"]
    assert commands[0] == "AT+COPS=2"
    assert commands[1:7] == ['AT+COPS=1,2,"23415",9', "AT+COPS=2", 'AT+COPS=1,2,"23410",9',
                             "AT+COPS=2", 'AT+COPS=1,2,"23430",9', "AT+COPS=2"]


def test_without_select_best_the_original_selection_comes_back():
    module = FakeModule(GOOD, SIGNAL)
    run, _ = run_survey(module, select_best=False)
    assert 'AT+COPS=1,2,"23415",9' in module.sent[-3:]
    assert module.sent[-1] == "AT+QSCLK=1"
    assert run.state["selected"] is None


def test_nothing_registering_restores_the_original_selection():
    module = FakeModule({"23415": 3, "23410": 3, "23430": 3}, SIGNAL)
    run, _ = run_survey(module)
    assert run.state["best"] is None
    assert 'AT+COPS=1,2,"23415",9' in module.sent[-3:]


def test_signal_is_averaged_over_the_samples():
    class Varying(FakeModule):
        readings = iter([(-100, -10, 2), (-90, -12, 6)])

        def parse_cell(self, reply):
            rsrp, rsrq, sinr = next(self.readings)
            return SimpleNamespace(rsrp=rsrp, rsrq=rsrq, sinr=sinr, pci=1, earfcn=2, cell_id="x")

    run, _ = run_survey(Varying({"23415": 5}, {}, scan='+COPS: (1,"","","23415",9)'))
    row = run.state["results"][0]
    assert (row["rsrp"], row["rsrq"], row["sinr"]) == (-95.0, -11.0, 4.0)
    assert (row["pci"], row["earfcn"]) == (1, 2)


def test_a_silent_scan_is_an_error_and_restores():
    module = FakeModule(GOOD, SIGNAL, scan=TIMEOUT_RESPONSE)
    run, _ = run_survey(module)
    assert "no answer" in run.state["error"]
    assert 'AT+COPS=1,2,"23415",9' in module.sent[-3:]


def test_an_empty_scan_is_an_error():
    run, _ = run_survey(FakeModule(GOOD, SIGNAL, scan="\r\n+COPS: ,,(0-4),(0-2)\r\n\r\nOK\r\n"))
    assert "no networks" in run.state["error"]


def test_a_crash_still_restores_the_selection():
    module = FakeModule(GOOD, SIGNAL)
    original = module.send

    def boom(command, timeout=None):
        if command == "CELL":
            raise OSError("port vanished")
        return original(command, timeout)

    module.send = boom
    run, _ = run_survey(module)
    assert "port vanished" in run.state["error"]
    assert not run.state["running"]
    assert 'AT+COPS=1,2,"23415",9' in module.sent[-3:]


def test_stopping_part_way_restores_and_skips_the_rest():
    module = FakeModule(GOOD, SIGNAL)
    run, _ = run_survey(module, aborted=lambda: sum(c.startswith("AT+COPS=1") for c in module.sent) >= 1)
    assert run.state["aborted"]
    assert [r["plmn"] for r in run.state["results"]] == ["23415"]
    assert run.state["selected"] is None
    assert 'AT+COPS=1,2,"23415",9' == [c for c in module.sent if c.startswith("AT+COPS=1")][-1]


def test_sleep_clock_is_turned_off_and_put_back():
    module = FakeModule(GOOD, SIGNAL, qsclk="1")
    run_survey(module)
    assert "AT+QSCLK=0" in module.sent
    assert module.sent[-1] == "AT+QSCLK=1"
    quiet = FakeModule(GOOD, SIGNAL, qsclk="0")
    run_survey(quiet)
    assert not any(c.startswith("AT+QSCLK=") for c in quiet.sent)


def test_progress_is_published():
    _, published = run_survey(FakeModule(GOOD, SIGNAL))
    assert any(p["phase"].startswith("Scanning") for p in published)
    assert published[-1]["phase"] == "Finished"


def test_rank_orders_by_rsrp_then_sinr_then_rsrq():
    rows = [
        {"plmn": "a", "status": "registered", "rsrp": -90, "sinr": 1, "rsrq": -9},
        {"plmn": "b", "status": "registered", "rsrp": -90, "sinr": 5, "rsrq": -15},
        {"plmn": "c", "status": "registered", "rsrp": None, "sinr": 20, "rsrq": -1},
        {"plmn": "d", "status": "denied", "rsrp": -50, "sinr": 30, "rsrq": 0},
    ]
    assert [r["plmn"] for r in rank(rows)] == ["b", "a", "c"]


def test_helpers():
    assert restore_command('+COPS: 1,2,"23415",9') == 'AT+COPS=1,2,"23415",9'
    assert restore_command("+COPS: 0") == "AT+COPS=0"
    assert cereg_stat("+CEREG: 4,5,x") == 5 and cereg_stat("ERROR") is None
    assert mean([1, None, 2]) == 1.5 and mean([None]) is None


# --- through the manager and the API -----------------------------------------

def test_demo_survey_runs_end_to_end(manager):
    manager.is_demo = True
    manager.start_network_survey()
    deadline = time.time() + 10
    while manager.state["survey"]["running"] and time.time() < deadline:
        time.sleep(0.05)
    state = manager.state["survey"]
    assert not state["running"] and state["error"] is None
    assert state["best"] == "23430" and state["selected"] == "23430"
    assert len(state["results"]) == 3


def test_survey_is_refused_while_another_is_running(manager):
    manager.state["survey"]["running"] = True
    with pytest.raises(RuntimeError):
        manager.start_network_survey()
    with pytest.raises(RuntimeError):
        manager.set_registration("deregister")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("QUECTEL_DASHBOARD_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(sys, "argv", ["server.py", "--no-file-log"])
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="http://localhost:8080") as c:
        c.server = server
        yield c
    server.manager.set_file_logging(False)


def test_api_survey(client):
    assert client.post("/api/survey", json={}).status_code == 400
    manager = client.server.manager
    manager.is_connected = True
    manager.is_demo = True
    manager.state["survey"]["running"] = True
    assert client.post("/api/survey", json={}).status_code == 409
    manager.state["survey"]["running"] = False
    assert client.post("/api/survey", json={"select_best": False}).status_code == 200
    deadline = time.time() + 10
    while manager.state["survey"]["running"] and time.time() < deadline:
        time.sleep(0.05)
    assert manager.state["survey"]["selected"] is None
    assert client.post("/api/survey/stop").status_code == 200
