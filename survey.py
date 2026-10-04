"""Try every visible network in turn, measure the signal on each, and pick the best.

The survey deregisters, scans with ``AT+COPS=?``, then for each network that is
not forbidden registers on it, waits for the module to attach, samples the
signal of the serving cell and of every neighbour cell the module reports, and
deregisters again. At the end it connects to the best network or
puts back the selection the module had before. It is written against a few
callables so it can run on a fake module in tests.
"""
import re
import time
from typing import Any, Callable, Dict, List, Optional

from at_channel import TIMEOUT_RESPONSE

REGISTERED = (1, 5)  # home or roaming
DENIED = 3
CEREG_STAT = re.compile(r"\+CEREG:\s*\d+,(\d+)")
COPS_QUERY = re.compile(r'\+COPS:\s*(\d+)(?:,(\d+),"([^"]*)"(?:,(\d+))?)?')
QSCLK = re.compile(r"\+QSCLK:\s*(\d)")
QLOCKF = re.compile(r"\+QLOCKF:\s*(\d+)((?:\s*,\s*\d*)*)")
MAX_PCI, MAX_EARFCN = 503, 262143  # BC660K-GL AT manual, AT+QLOCKF; EARFCN 0 means "remove lock"


def restore_command(cops_reply: str) -> str:
    """The ``AT+COPS=`` command that puts back the selection in an ``AT+COPS?`` reply."""
    match = COPS_QUERY.search(cops_reply)
    if not match or match.group(2) is None:
        return "AT+COPS=0"
    mode, fmt, oper, act = match.groups()
    return f'AT+COPS={mode},{fmt},"{oper}"' + (f",{act}" if act else "")


def lock_restore_command(qlockf_reply: str) -> str:
    """The ``AT+QLOCKF=`` command that puts back the lock in an ``AT+QLOCKF?`` reply.

    No lock in the reply gives ``AT+QLOCKF=0`` (unlock).
    """
    match = QLOCKF.search(qlockf_reply)
    if not match:
        return "AT+QLOCKF=0"
    mode = int(match.group(1))
    values = [v.strip() for v in match.group(2).split(",") if v.strip()]
    if mode == 1 and values:
        return "AT+QLOCKF=1," + ",".join(values[:2])
    if mode == 2 and values:
        return f"AT+QLOCKF=2,,{len(values)}," + ",".join(values)
    return "AT+QLOCKF=0"


def lockable_cell(row: Dict[str, Any]) -> Optional[tuple]:
    """``(earfcn, pci)`` of the strongest cell in a result row, or ``None`` if it cannot be locked to."""
    for cell in row.get("cells") or []:
        earfcn, pci = cell.get("earfcn"), cell.get("pci")
        if (cell.get("best") and isinstance(earfcn, int) and isinstance(pci, int)
                and 1 <= earfcn <= MAX_EARFCN and 0 <= pci <= MAX_PCI):
            return earfcn, pci
    return None


def cereg_stat(reply: str) -> Optional[int]:
    """The ``<stat>`` of an ``AT+CEREG?`` reply, or ``None``."""
    match = CEREG_STAT.search(reply)
    return int(match.group(1)) if match else None


def mean(values: List[Optional[float]]) -> Optional[float]:
    """Average of the values that are not ``None``, rounded to one decimal place."""
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 1) if present else None


def rank(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Registered networks, best first: RSRP, then SINR, then RSRQ (higher is better)."""
    def key(item):
        return tuple(-1e9 if item.get(f) is None else item[f] for f in ("rsrp", "sinr", "rsrq"))
    return sorted((r for r in results if r["status"] == "registered"), key=key, reverse=True)


def merge_cells(samples: List[Any]) -> List[Dict[str, Any]]:
    """Every cell seen in a few readings of one network, averaged per cell.

    Each reading has a serving cell and, where the module reports them, neighbour
    cells (``neighbours``: dictionaries with ``pci``, ``earfcn``, ``rsrp``, ``rsrq``).
    A cell is identified by its PCI and EARFCN. The serving cell comes first, then
    the neighbours strongest first, and the strongest cell of all is flagged
    ``best``.
    """
    serving: Dict[tuple, Dict[str, List[Any]]] = {}
    neighbours: Dict[tuple, Dict[str, List[Any]]] = {}

    def add(table, key, **values):
        entry = table.setdefault(key, {"rsrp": [], "rsrq": [], "sinr": [], "cell_id": []})
        for name, value in values.items():
            entry[name].append(value)

    for cell in samples:
        add(serving, (cell.pci, cell.earfcn), rsrp=cell.rsrp, rsrq=cell.rsrq,
            sinr=cell.sinr, cell_id=getattr(cell, "cell_id", None))
        for n in getattr(cell, "neighbours", None) or []:
            add(neighbours, (n.get("pci"), n.get("earfcn")), rsrp=n.get("rsrp"), rsrq=n.get("rsrq"))

    def build(kind, table):
        rows = []
        for (pci, earfcn), v in table.items():
            ids = [i for i in v["cell_id"] if i]
            rows.append({"kind": kind, "pci": pci, "earfcn": earfcn,
                         "cell_id": ids[-1] if ids else None,
                         "rsrp": mean(v["rsrp"]), "rsrq": mean(v["rsrq"]), "sinr": mean(v["sinr"]),
                         "best": False})
        return sorted(rows, key=lambda r: -1e9 if r["rsrp"] is None else -r["rsrp"])

    cells = build("serving", serving) + [
        c for c in build("neighbour", neighbours) if (c["pci"], c["earfcn"]) not in serving]
    measured = [c for c in cells if c["rsrp"] is not None]
    if measured:
        max(measured, key=lambda c: c["rsrp"])["best"] = True
    return cells


def initial_state() -> Dict[str, Any]:
    """The survey state as shown to the web UI."""
    return {"running": False, "phase": "", "results": [], "best": None,
            "selected": None, "locked": None, "error": None, "aborted": False}


class NetworkSurvey:
    """Run one survey. ``state`` is updated in place and ``publish`` is called after each change."""

    def __init__(
        self,
        send: Callable[..., str],
        parse_scan: Callable[[str], List[Dict[str, Any]]],
        parse_cell: Callable[[str], Any],
        cell_command: Callable[[], str],
        log: Callable[[str], None],
        publish: Callable[[], None],
        aborted: Callable[[], bool] = lambda: False,
        sleep: Callable[[float], None] = time.sleep,
        register_wait: float = 120.0,
        poll: float = 3.0,
        samples: int = 3,
        sample_gap: float = 2.0,
        settle: float = 3.0,
    ):
        """
        :param send: ``send(command, timeout=None)`` returns the module's reply.
        :param parse_scan: turns an ``AT+COPS=?`` reply into network dictionaries.
        :param parse_cell: turns a serving-cell reply into an object with
            ``rsrp``, ``rsrq``, ``sinr``, ``pci``, ``earfcn`` and ``cell_id``.
        :param cell_command: the serving-cell command for the module in use.
        :param log: receives one line per step.
        :param publish: called when ``state`` changed.
        :param aborted: returns ``True`` when the user asked to stop.
        """
        self.send, self.parse_scan, self.parse_cell = send, parse_scan, parse_cell
        self.cell_command, self.log, self.publish = cell_command, log, publish
        self.aborted, self.sleep = aborted, sleep
        self.register_wait, self.poll = register_wait, poll
        self.samples, self.sample_gap, self.settle = samples, sample_gap, settle
        self.state = initial_state()

    def _set(self, **changes: Any) -> None:
        self.state.update(changes)
        self.publish()

    def run(self, select_best: bool = True, lock_best_cell: bool = False) -> Dict[str, Any]:
        """Survey every network. Always leaves the module registered somewhere sensible.

        :param lock_best_cell: after joining the best network, lock the module to its
            strongest cell (``AT+QLOCKF``). If the module cannot attach to that cell the
            previous lock is put back. Only used together with ``select_best``.
        """
        # One update call with every key, so another thread never sees a half-built state.
        self.state.update(initial_state(), running=True, phase="Starting")
        self.publish()
        restore = "AT+COPS=0"
        qsclk_was: Optional[str] = None
        selected = False
        try:
            restore = restore_command(self.send("AT+COPS?"))
            match = QSCLK.search(self.send("AT+QSCLK?"))
            qsclk_was = match.group(1) if match else None
            if qsclk_was not in (None, "0"):
                self.log("[SURVEY] Turning the sleep clock off for the survey.")
                self.send("AT+QSCLK=0")

            self._set(phase="Deregistering")
            self.send("AT+COPS=2", 180.0)

            self._set(phase="Scanning for networks (this can take about 5 minutes)")
            reply = self.send("AT+COPS=?", 600.0)
            if reply == TIMEOUT_RESPONSE:
                self._set(error="The module gave no answer to the network scan.")
                return self.state
            networks = self._unique([n for n in self.parse_scan(reply) if n["status"] != "Forbidden"])
            if not networks:
                self._set(error="The scan found no networks to try.")
                return self.state
            self.log(f"[SURVEY] Trying {len(networks)} network(s).")

            for number, network in enumerate(networks, 1):
                if self.aborted():
                    self._set(aborted=True)
                    break
                self._set(phase=f"Network {number} of {len(networks)}: {network['long_name']}")
                self.state["results"].append(self._try(network))
                self.publish()

            ranked = rank(self.state["results"])
            if ranked:
                self._set(best=ranked[0]["plmn"])
            if select_best and ranked and not self.aborted():
                self._set(phase=f"Connecting to the best network: {ranked[0]['name']}")
                if self._register(ranked[0]) in REGISTERED:
                    selected = True
                    if lock_best_cell:
                        row = next(r for r in self.state["results"] if r["plmn"] == ranked[0]["plmn"])
                        self._set(phase="Locking to the strongest cell")
                        selected = self._lock_cell(ranked[0], row)
                    if selected:
                        self._set(selected=ranked[0]["plmn"])
        except Exception as exc:  # leave the module usable whatever went wrong
            self._set(error=f"Survey stopped: {exc}")
        finally:
            if not selected:
                self._set(phase="Restoring your original network selection")
                self.send(restore, 180.0)
                self._wait_registered()
            if qsclk_was not in (None, "0"):
                self.send(f"AT+QSCLK={qsclk_was}")
            self._set(running=False, phase="Finished")
        return self.state

    @staticmethod
    def _unique(networks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen, unique = set(), []
        for network in networks:
            key = (network["plmn"], network.get("act_code"))
            if key not in seen:
                seen.add(key)
                unique.append(network)
        return unique

    def _apply_lock(self, command: str) -> bool:
        """Run an ``AT+QLOCKF`` command, which the module only accepts with the radio off."""
        self.send("AT+CFUN=0", 30.0)
        try:
            reply = self.send(command, 10.0)
        finally:
            self.send("AT+CFUN=1", 30.0)
        return "ERROR" not in reply and reply != TIMEOUT_RESPONSE

    def _lock_cell(self, network: Dict[str, Any], row: Dict[str, Any]) -> bool:
        """Lock to the strongest cell of ``row``. True if the module is registered on ``network`` after."""
        cell = lockable_cell(row)
        if cell is None:
            self.log("[SURVEY] No cell with a usable EARFCN and PCI to lock to; left unlocked.")
            return True
        earfcn, pci = cell
        current = self.send("AT+QLOCKF?")
        if "ERROR" in current or current == TIMEOUT_RESPONSE:
            self.log("[SURVEY] The module does not answer AT+QLOCKF; left unlocked.")
            return True
        previous = lock_restore_command(current)
        if self._apply_lock(f"AT+QLOCKF=1,{earfcn},{pci}") and self._register(network) in REGISTERED:
            self._set(locked={"plmn": network["plmn"], "earfcn": earfcn, "pci": pci})
            self.log(f"[SURVEY] Locked to EARFCN {earfcn}, PCI {pci}. "
                     "Unlock with AT+CFUN=0, AT+QLOCKF=0, AT+CFUN=1.")
            return True
        self.log(f"[SURVEY] The module could not attach to EARFCN {earfcn}, PCI {pci}; putting the previous lock back.")
        self._apply_lock(previous)
        return self._register(network) in REGISTERED

    def _register(self, network: Dict[str, Any]) -> Optional[int]:
        """Register on ``network`` and return the final ``CEREG`` status, or ``None``."""
        act = network.get("act_code") or 9
        reply = self.send(f'AT+COPS=1,2,"{network["plmn"]}",{act}', 180.0)
        if "ERROR" in reply or reply == TIMEOUT_RESPONSE:
            return DENIED
        return self._wait_registered()

    def _wait_registered(self) -> Optional[int]:
        """Poll ``AT+CEREG?`` until registered or denied, up to ``register_wait`` seconds."""
        waited = 0.0
        while True:
            stat = cereg_stat(self.send("AT+CEREG?"))
            if stat in REGISTERED or stat == DENIED:
                return stat
            if waited >= self.register_wait or self.aborted():
                return None
            self.sleep(self.poll)
            waited += self.poll

    def _try(self, network: Dict[str, Any]) -> Dict[str, Any]:
        """Register on one network, sample it, deregister, and return its result row."""
        started = time.monotonic()
        row: Dict[str, Any] = {
            "plmn": network["plmn"], "name": network["long_name"], "act": network["act"],
            "status": "timeout", "rsrp": None, "rsrq": None, "sinr": None,
            "pci": None, "earfcn": None, "seconds": None, "cells": [],
        }
        stat = self._register(network)
        if stat in REGISTERED:
            row["status"] = "registered"
            self._sample(row)
        elif stat == DENIED:
            row["status"] = "denied"
        row["seconds"] = round(time.monotonic() - started)
        self.log(f"[SURVEY] {row['name']} ({row['plmn']}): {row['status']}"
                 + (f", RSRP {row['rsrp']} dBm" if row["rsrp"] is not None else ""))
        self.send("AT+COPS=2", 180.0)
        return row

    def _sample(self, row: Dict[str, Any]) -> None:
        """Read the serving cell a few times and store the averages in ``row``."""
        self.sleep(self.settle)
        cells = []
        for index in range(self.samples):
            if index:
                self.sleep(self.sample_gap)
            cell = self.parse_cell(self.send(self.cell_command()))
            if cell is not None:
                cells.append(cell)
        for field in ("rsrp", "rsrq", "sinr"):
            row[field] = mean([getattr(c, field) for c in cells])
        if cells:
            row["pci"], row["earfcn"] = cells[-1].pci, cells[-1].earfcn
            row["cells"] = merge_cells(cells)
