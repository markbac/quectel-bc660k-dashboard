import logging
import time
import re
import os
import threading
import random
from typing import Dict, Any, List, Optional
import serial
import serial.tools.list_ports

import instance
import timers
from at_channel import ATChannel, TIMEOUT_RESPONSE, timeout_for
from db_manager import DBManager
from drivers import DEFAULT_DRIVER, CellInfo, ModuleDriver, detect_driver
from pylogkit import setup_logging
from transcript import TranscriptRecorder

__version__ = "2.0.0"
LOGGER_NAME = "QuectelManager"
LOG_FILE_PATH = os.path.join(os.path.dirname(__file__), "dashboard_serial.log")

# Access technology values of +COPS (3GPP TS 27.007, as listed in the BC660K-GL manual).
COPS_ACT_NAMES = {
    0: "GSM",
    2: "UTRAN (3G)",
    7: "LTE (E-UTRAN)",
    9: "NB-IoT (E-UTRAN NB-S1)",
}

# <stat> values of +CEREG.
CEREG_STAT_NAMES = {
    0: "Not registered, not searching",
    1: "Registered, home network",
    2: "Not registered, searching...",
    3: "Registration denied",
    4: "Unknown / Out of coverage",
    5: "Registered, roaming",
    6: "Registered for SMS only, home network",
    7: "Registered for SMS only, roaming",
    8: "Attached for emergency bearer services only",
    9: "Registered (CSFB not preferred), home network",
    10: "Registered (CSFB not preferred), roaming",
}


# Fixed identity used in demo mode so simulated rows never mix with real data.
DEFAULT_HISTORY_INTERVAL = 5  # seconds between database rows
DEMO_ICCID = "DEMO-SIMULATED-SIM"


# Modem power/reachability states shown in the UI.
MODEM_DISCONNECTED = "disconnected"
MODEM_PROBING = "probing"
MODEM_AWAKE = "awake"
MODEM_PSM = "psm"
MODEM_DEEP_SLEEP = "deep_sleep"
MODEM_UNRESPONSIVE = "unresponsive"

# +QNBIOTEVENT payload -> state it implies.
NBIOT_EVENTS = {
    "ENTER PSM": MODEM_PSM,
    "EXIT PSM": MODEM_AWAKE,
    "ENTER DEEPSLEEP": MODEM_DEEP_SLEEP,
    "EXIT DEEPSLEEP": MODEM_AWAKE,
}


class SerialManager:
    VERSION = __version__
    IDENTITY_RECHECK_SECONDS = 60.0
    # How often slow-changing items are polled (registration changes also arrive as URCs).
    DEFAULT_SLOW_POLL_SECONDS = 30.0
    SLOW_POLL_SECONDS = {"AT+CEREG?": 60.0}
    PROBE_TRIES = 3
    PROBE_TIMEOUT = 1.5
    WAKE_HINT = (
        "[HINT] Modem is not responding. If the board was just powered, press the RESET "
        "button on the evaluation board to wake the modem. If PSM is enabled, the module "
        "may be asleep."
    )
    ATTACH_CHECKS = 5
    # Context ID used by the documented AT+QPING / AT+QIDNSGIP examples.
    PING_CONTEXT_ID = 0
    PING_REPLY_TIMEOUT = 4  # seconds per echo, the documented default
    DNS_TIMEOUT = 20.0
    ATTACH_CHECK_INTERVAL = 1.0

    def __init__(
        self,
        file_logging_enabled: bool = True,
        telemetry_interval: int = 3,
        cops_scan_interval: int = 0,
        db_path: Optional[str] = None,
        log_file_path: Optional[str] = None,
        retention_days: float = 0,
    ):
        """Create a manager.

        Args:
            file_logging_enabled: Write the serial log to disk.
            telemetry_interval: Seconds between poll cycles.
            cops_scan_interval: Seconds between operator scans (0 disables).
            db_path: SQLite file to use. Defaults to the per-user data directory
                (see ``db_manager.default_db_path``).
            log_file_path: Log file to use. Defaults to ``dashboard_serial.log``.
            retention_days: Delete history older than this many days at start-up
                and once a day (0 keeps everything).
        """
        self.ser: Optional[serial.Serial] = None
        self.port: Optional[str] = None
        self.baudrate: int = 115200
        self.is_connected: bool = False
        self.is_demo: bool = False

        self.lock = threading.Lock()
        self.channel = ATChannel(
            get_port=lambda: self.ser,
            log=self.log,
            on_urc=self._handle_urc,
            on_response=self._on_channel_response,
            on_timeout=self._on_channel_timeout,
            on_exchange=self._record_exchange,
        )
        self.recorder: Optional[TranscriptRecorder] = None
        self.scan_lock = threading.Lock()
        self.driver: ModuleDriver = DEFAULT_DRIVER
        self._scan_in_progress: bool = False

        self.poll_thread: Optional[threading.Thread] = None
        self.running: bool = False
        self.callbacks = []
        self.db = DBManager(db_path) if db_path else DBManager()
        self.retention_days = retention_days
        self._last_prune: Optional[float] = None

        self.telemetry_interval: int = telemetry_interval
        self.cops_scan_interval: int = cops_scan_interval
        self.history_interval: int = DEFAULT_HISTORY_INTERVAL
        self.last_cops_scan_time: float = 0

        self.file_logging_enabled: bool = file_logging_enabled
        self.log_file_path: str = log_file_path or LOG_FILE_PATH

        self.py_logger = self._configure_logging()
        self.py_logger.info(f"Quectel BC660K Serial Manager v{self.VERSION} Initialized.")

        self.last_cops_op: str = "Unknown"
        self.last_cereg_stat: str = "Unknown"
        self._temp_supported: bool = False
        self._last_identity_check: float = 0.0
        self._wake_hint_shown: bool = False
        self._last_slow_run: Dict[str, float] = {}
        self._hardware_info_loaded: bool = False
        self._session_id: Optional[int] = None
        self._session_iccid: Optional[str] = None

        # Current state cache
        self.state = self._get_initial_state()

    def _get_initial_state(self) -> Dict[str, Any]:
        return {
            "connected": False,
            "port": None,
            "baudrate": 115200,
            "mode": "DISCONNECTED",
            "hardware_communicated": False,
            "modem_responding": False,
            "modem_state": MODEM_DISCONNECTED,
            "sleep_events": False,
            "file_logging_enabled": self.file_logging_enabled,
            "telemetry_interval": self.telemetry_interval,
            "history_interval": self.history_interval,
            "cops_scan_interval": self.cops_scan_interval,
            "connectivity_status": "No Connection",
            "signal": {
                "rssi": None,
                "csq": None,
                "rsrp": None,
                "rsrq": None,
                "sinr": None,
                "ber": None,
                "quality_label": "Awaiting Data"
            },
            "apn_info": {
                "apn": "--",
                "pdp_type": "--",
                "attached": False,
                "pdp_cid": 1
            },
            "serving_cell": {
                "rat": "--",
                "state": "DISCONNECTED",
                "mcc": "--",
                "mnc": "--",
                "operator": "Awaiting Modem Communication...",
                "cell_id": "--",
                "cell_id_dec": "--",
                "pci": "--",
                "earfcn": "--",
                "band": "--",
                "tac": "--",
                "tac_dec": "--"
            },
            "sim_info": {
                "iccid": "--",
                "imsi": "--",
                "sim_status": "AWAITING MODEM",
                "number": "--"
            },
            "system_info": {
                "imei": "--",
                "ip_address": "--",
                "voltage": None,
                "temperature": None,
                "firmware": "--",
                "module": "--",
                "sleep_clock": None
            },
            "neighbour_cells": [],
            "networks_scan": [],
            "is_scanning": False,
            "psm_info": {
                "enabled": False,
                "t3412": "10100101",
                "t3324": "00100100",
                "status": "PSM Disabled",
                "granted": {"t3412": None, "t3324": None},
                "requested_text": "--",
                "granted_text": "--",
                "mismatch": False
            },
            "edrx_info": {
                "enabled": False,
                "value": "0010",
                "status": "eDRX Disabled",
                "granted": None,
                "requested_text": "--",
                "granted_text": "--",
                "mismatch": False
            },
            "last_ping_result": None,
            "last_dns_result": None,
            "last_update": time.time(),
            "logs": []
        }

    @property
    def current_iccid(self) -> Optional[str]:
        """ICCID of the connected SIM, or None until it is known."""
        iccid = self.state["sim_info"]["iccid"]
        return iccid if DBManager.is_valid_iccid(iccid) else None

    @property
    def session_id(self) -> Optional[int]:
        """Id of the current recording session, or None when not recording."""
        return self._session_id

    def _update_session(self):
        """Keep the database session in step with the connected SIM.

        A new session starts when a SIM becomes known or changes, and the
        previous one is closed.
        """
        iccid = self.current_iccid
        if iccid == self._session_iccid:
            return
        self.db.end_session(self._session_id)
        self._session_id = None
        self._session_iccid = iccid
        if iccid is not None:
            info = self.state["system_info"]
            self._session_id = self.db.start_session(iccid, info.get("imei"), info.get("firmware"))

    def _prune_if_due(self):
        """Apply the retention policy at most once a day."""
        if self.retention_days > 0 and (
            self._last_prune is None or time.monotonic() - self._last_prune >= 86400
        ):
            self._last_prune = time.monotonic()
            deleted = self.db.prune_older_than(self.retention_days)
            if deleted:
                self.log(f"[RETENTION] Deleted {deleted} history rows older than {self.retention_days} days.", "INFO")

    def _log_history(self):
        """Write one history row for the current state, if it qualifies."""
        self._prune_if_due()
        self._update_session()
        self.db.log_record(self.state, self._session_id)

    def update_settings(
        self,
        telemetry_interval: Optional[int] = None,
        cops_scan_interval: Optional[int] = None,
        history_interval: Optional[int] = None,
    ):
        """Change the poll, operator-scan and history-logging intervals (seconds).

        Values that are out of range are ignored. ``history_interval`` is how
        often a row is written to the database, independent of the poll rate.
        """
        if history_interval is not None and history_interval >= 1:
            self.history_interval = history_interval
            self.state["history_interval"] = history_interval

        if telemetry_interval is not None and telemetry_interval >= 1:
            self.telemetry_interval = telemetry_interval
            self.state["telemetry_interval"] = telemetry_interval

        if cops_scan_interval is not None and cops_scan_interval >= 0:
            self.cops_scan_interval = cops_scan_interval
            self.state["cops_scan_interval"] = cops_scan_interval

        self.log(
            f"[CONFIG] Updated intervals: Telemetry={self.telemetry_interval}s, "
            f"COPS Scan={self.cops_scan_interval}s, History={self.history_interval}s", "INFO")
        self._notify("state", self.state)

    def set_apn(self, apn: str, pdp_type: str = "IP", cid: int = 1) -> str:
        """
        Configure APN & PDP Context on Quectel BC660K module.
        Executes: AT+CGDCONT=<cid>,"<pdp_type>","<apn>"
        """
        self.log(f"[APN CONFIG] Setting Context {cid}: Type={pdp_type}, APN='{apn}'...", "INFO")
        
        if self.is_demo:
            self.state["apn_info"] = {
                "apn": apn,
                "pdp_type": pdp_type,
                "attached": True,
                "pdp_cid": cid
            }
            self.state["system_info"]["ip_address"] = "10.142.88.204"
            self.log(f"[APN CONFIG] Demo APN set to '{apn}'. PDP attached.", "INFO")
            self._notify("state", self.state)
            return "OK"

        with self.lock:
            # Set PDP Context APN
            cgdcont_cmd = f'AT+CGDCONT={cid},"{pdp_type}","{apn}"'
            resp1 = self._send_at_cmd_raw(cgdcont_cmd)
            
            # Trigger packet domain attach (documented maximum response time: 70 s)
            resp2 = self._send_at_cmd_raw("AT+CGATT=1")

            # Read back the attach state, allowing a few seconds to settle
            for attempt in range(self.ATTACH_CHECKS):
                self._parse_cgatt(self._send_at_cmd_raw("AT+CGATT?"))
                if self.state["apn_info"]["attached"] or attempt == self.ATTACH_CHECKS - 1:
                    break
                time.sleep(self.ATTACH_CHECK_INTERVAL)

            # Refresh assigned IP
            ip_resp = self._send_at_cmd_raw(f"AT+CGPADDR={cid}")
            self._parse_cgpaddr(ip_resp)
            self._parse_cgdcont(self._send_at_cmd_raw("AT+CGDCONT?"))
            
            self._notify("state", self.state)
            return f"{resp1}\n{resp2}"

    def set_file_logging(self, enabled: bool):
        """Turn the on-disk serial log on or off at runtime."""
        self.file_logging_enabled = enabled
        self.py_logger = self._configure_logging()
        self.state["file_logging_enabled"] = enabled
        status_msg = "ENABLED" if enabled else "DISABLED"
        self.log(f"[CONFIG] Disk file logging {status_msg} ({self.log_file_path})", "INFO")
        self._notify("state", self.state)

    def _configure_logging(self) -> logging.Logger:
        """Build the py-logkit logger, with or without the rotating file.

        Calling ``setup_logging`` again replaces the handlers and closes the
        old ones, so this also serves to switch the file on or off at runtime.
        """
        return setup_logging(
            name=LOGGER_NAME,
            to_console=True,
            to_file=self.file_logging_enabled,
            file_path=self.log_file_path,
            level="DEBUG",
        )

    def set_psm_config(self, enabled: bool, t3412: str = "10100101", t3324: str = "00100100") -> str:
        """Configure PSM (Power Saving Mode) on Quectel BC660K."""
        mode = 1 if enabled else 0
        self.log(f"[PSM CONFIG] Setting PSM Mode={mode}, T3412='{t3412}', T3324='{t3324}'...", "INFO")
        
        if self.is_demo:
            self.state["psm_info"] = {
                "enabled": enabled,
                "t3412": t3412,
                "t3324": t3324,
                "status": "PSM Enabled (Simulated)" if enabled else "PSM Disabled"
            }
            self._update_psm_text()
            self.log("[PSM OK] Simulated PSM updated.", "INFO")
            self._notify("state", self.state)
            return "OK"

        if enabled:
            self.log(
                "[PSM WARNING] Once PSM is active the module can stop responding on the UART after T3324 "
                "expires. Press RESET on the board (or use the PSM_EINT wake line) to wake it.",
                "WARNING",
            )

        with self.lock:
            if enabled:
                # 3GPP five-field form first; some firmware documents a
                # three-field form, so fall back to it if the module rejects it.
                resp = self._send_at_cmd_raw(f'AT+CPSMS=1,,,"{t3412}","{t3324}"')
                if not self.is_ok(resp) and "Timeout" not in resp:
                    self.log("[PSM CONFIG] Five-field form rejected, trying the three-field form.", "WARNING")
                    resp = self._send_at_cmd_raw(f'AT+CPSMS=1,"{t3412}","{t3324}"')
            else:
                resp = self._send_at_cmd_raw("AT+CPSMS=0")

            if not self.is_ok(resp):
                self.state["psm_info"]["status"] = f"PSM command failed: {resp.strip()}"
                self.log(f"[PSM ERROR] Module did not accept the PSM setting: {resp.strip()}", "ERROR")
                self._notify("state", self.state)
                return resp

            # Report what the module says, not what was requested.
            self._parse_cpsms(self._send_at_cmd_raw("AT+CPSMS?"), requested=(enabled, t3412, t3324))
            self._notify("state", self.state)
            return resp

    is_ok = staticmethod(ATChannel.is_ok)

    def _parse_cpsms(self, resp: str, requested=None):
        """Update ``psm_info`` from an ``AT+CPSMS?`` read-back.

        Handles ``+CPSMS: 1,,,"<T3412>","<T3324>"`` and the three-field form.
        If the read-back cannot be parsed, fall back to the requested values.
        """
        match = re.search(r"\+CPSMS:\s*(\d)", resp)
        timers = re.findall(r'"([01]{8})"', resp)
        if match:
            enabled = match.group(1) == "1"
            t3412, t3324 = (timers[-2], timers[-1]) if len(timers) >= 2 else (None, None)
        elif requested:
            enabled, t3412, t3324 = requested
        else:
            return
        info = self.state["psm_info"]
        info["enabled"] = enabled
        if t3412 and t3324:
            info["t3412"], info["t3324"] = t3412, t3324
        info["status"] = "PSM Enabled" if enabled else "PSM Disabled"
        self._update_psm_text()

    def set_edrx_config(self, enabled: bool, edrx_val: str = "0010") -> str:
        """Configure eDRX (Extended Discontinuous Reception) on Quectel BC660K."""
        mode = 1 if enabled else 0
        self.log(f"[eDRX CONFIG] Setting eDRX Mode={mode}, Value='{edrx_val}'...", "INFO")
        
        if self.is_demo:
            self.state["edrx_info"] = {
                "enabled": enabled,
                "value": edrx_val,
                "status": "eDRX Enabled (Simulated)" if enabled else "eDRX Disabled"
            }
            self.log("[eDRX OK] Simulated eDRX updated.", "INFO")
            self._notify("state", self.state)
            return "OK"

        with self.lock:
            cmd = f'AT+CEDRXS={mode},5,"{edrx_val}"'
            resp = self._send_at_cmd_raw(cmd)
            self.state["edrx_info"] = {
                "enabled": enabled,
                "value": edrx_val,
                "status": "eDRX Enabled" if enabled else "eDRX Disabled"
            }
            self._notify("state", self.state)
            return resp

    def run_ping_benchmark(self, host: str = "8.8.8.8", count: int = 4) -> Dict[str, Any]:
        """Executes ICMP Ping test over modem PDP context."""
        self.log(f"[PING TEST] Pinging '{host}' ({count} packets)...", "INFO")
        
        if self.is_demo:
            time.sleep(1.2)
            res = {
                "host": host,
                "sent": count,
                "received": count,
                "lost": 0,
                "loss_pct": 0.0,
                "min_rtt": 124,
                "max_rtt": 168,
                "avg_rtt": 142,
                "status": "Success (Simulated)"
            }
            self.state["last_ping_result"] = res
            self.log(f"[PING RESULT] {host}: Avg RTT {res['avg_rtt']} ms, 0% Loss", "INFO")
            self._notify("state", self.state)
            return res

        count = max(1, min(10, int(count)))
        with self.lock:
            cmd = f'AT+QPING={self.PING_CONTEXT_ID},"{host}",{self.PING_REPLY_TIMEOUT},{count}'
            resp = self._send_at_cmd_raw(
                cmd,
                timeout_sec=count * self.PING_REPLY_TIMEOUT + 5.0,
                wait_for=self._PING_DONE,
            )
            res = self._parse_ping(resp, host, count)
            self.state["last_ping_result"] = res
            self.log(f"[PING RESULT] {host}: {res['status']}", "INFO")
            self._notify("state", self.state)
            return res

    def run_dns_query(self, domain: str = "leshan.eclipseprojects.io") -> Dict[str, Any]:
        """Executes DNS domain lookup on modem."""
        self.log(f"[DNS QUERY] Resolving domain '{domain}'...", "INFO")

        if self.is_demo:
            time.sleep(0.8)
            res = {"domain": domain, "resolved_ip": "51.159.20.165", "status": "Success (Simulated)"}
            self.state["last_dns_result"] = res
            self.log(f"[DNS RESULT] {domain} -> {res['resolved_ip']}", "INFO")
            self._notify("state", self.state)
            return res

        with self.lock:
            cmd = f'AT+QIDNSGIP={self.PING_CONTEXT_ID},"{domain}"'
            resp = self._send_at_cmd_raw(cmd, timeout_sec=self.DNS_TIMEOUT, wait_for=self._DNS_DONE)
            res = self._parse_dns(resp, domain)
            self.state["last_dns_result"] = res
            self.log(f"[DNS RESULT] {domain} -> {res['resolved_ip']} ({res['status']})", "INFO")
            self._notify("state", self.state)
            return res

    # AT+QPING ends with a summary line, ``+QPING: <result>,<sent>,<rcvd>,<lost>
    # [,<min>,<max>,<avg>]``. A bare ``+QPING: <code>`` is the outcome of one
    # packet (a real board sent ``+QPING: 569`` four times before the summary),
    # so it must not end the wait.
    _PING_DONE = re.compile(r"\+QPING:\s*\d+,\d+,\d+,\d+(?:,\d+,\d+,\d+)?\s*$", re.M)
    _PING_SUMMARY = re.compile(r"\+QPING:\s*\d+,(\d+),(\d+),(\d+)(?:,(\d+),(\d+),(\d+))?\s*$", re.M)
    _PING_ERROR = re.compile(r"\+QPING:\s*(\d+)\s*$", re.M)
    # AT+QIDNSGIP answers "+QIDNSGIP: <err>,<count>,<ttl>" and then one line
    # per address. A non-zero error code ends the wait too.
    _DNS_DONE = re.compile(r'\+QIDNSGIP:\s*(?:"?\d{1,3}(?:\.\d{1,3}){3}"?|[1-9]\d*)\s*(?:,|$)', re.M)
    _DNS_ADDRESS = re.compile(r'\+QIDNSGIP:\s*"?(\d{1,3}(?:\.\d{1,3}){3})"?', re.M)
    _DNS_ERROR = re.compile(r"\+QIDNSGIP:\s*([1-9]\d*)\s*(?:,|$)", re.M)

    @classmethod
    def _parse_ping(cls, resp: str, host: str, count: int) -> Dict[str, Any]:
        """Turn an ``AT+QPING`` response into a result dictionary.

        A missing summary is reported as a timeout, not as 100% loss.
        """
        match = cls._PING_SUMMARY.search(resp)
        if match:
            sent, rcvd, lost = (int(x) for x in match.groups()[:3])
            rtts = [int(x) for x in match.groups()[3:] if x is not None]
            min_rtt, max_rtt, avg_rtt = rtts if len(rtts) == 3 and rcvd > 0 else (None, None, None)
            return {
                "host": host,
                "sent": sent,
                "received": rcvd,
                "lost": lost,
                "loss_pct": (lost / sent * 100) if sent > 0 else 100.0,
                "min_rtt": min_rtt,
                "max_rtt": max_rtt,
                "avg_rtt": avg_rtt,
                "status": "Success" if rcvd > 0 else "Failed",
            }
        error = cls._PING_ERROR.search(resp)
        if error:
            status = f"Error {error.group(1)}"
        elif "ERROR" in resp:
            status = f"Response: {resp.strip()}"
        else:
            status = "Timed out waiting for result"
        return {
            "host": host,
            "sent": count,
            "received": None,
            "lost": None,
            "loss_pct": None,
            "min_rtt": None,
            "max_rtt": None,
            "avg_rtt": None,
            "status": status,
        }

    @classmethod
    def _parse_dns(cls, resp: str, domain: str) -> Dict[str, Any]:
        """Turn an ``AT+QIDNSGIP`` response into a result dictionary."""
        match = cls._DNS_ADDRESS.search(resp)
        if match:
            return {"domain": domain, "resolved_ip": match.group(1), "status": "Success"}
        error = cls._DNS_ERROR.search(resp)
        if error:
            status = f"Error {error.group(1)}"
        elif "ERROR" in resp:
            status = f"Response: {resp.strip()}"
        else:
            status = "Timed out waiting for result"
        return {"domain": domain, "resolved_ip": None, "status": status}

    def register_callback(self, callback):
        self.callbacks.append(callback)

    def _notify(self, event_type: str, data: Any):
        for cb in self.callbacks:
            try:
                cb(event_type, data)
            except Exception:
                pass

    def log(self, text: str, direction: str = "INFO"):
        ascii_text = self._to_ascii_printable(text)
        timestamp = time.strftime("%H:%M:%S")
        entry = {
            "timestamp": timestamp,
            "direction": direction,
            "text": ascii_text
        }
        self.state["logs"].append(entry)
        if len(self.state["logs"]) > 300:
            self.state["logs"].pop(0)

        if direction == "ERROR":
            self.py_logger.error(ascii_text)
        elif direction == "TX":
            self.py_logger.debug(ascii_text)  # callers already add the "TX> " prefix
        elif direction == "RX":
            self.py_logger.debug(ascii_text)  # ... and the "RX< " prefix
        else:
            self.py_logger.info(ascii_text)

        self._notify("log", entry)

    @staticmethod
    def _to_ascii_printable(text: str) -> str:
        if not isinstance(text, str):
            text = str(text)
        clean_chars = []
        for ch in text:
            code = ord(ch)
            if code == 10 or code == 13 or code == 9:
                clean_chars.append(ch)
            elif 32 <= code <= 126:
                clean_chars.append(ch)
            else:
                clean_chars.append(f"\\x{code:02x}")
        return "".join(clean_chars)

    @staticmethod
    def get_ports() -> List[Dict[str, str]]:
        ports = serial.tools.list_ports.comports()
        result = []
        for p in ports:
            result.append({
                "device": p.device,
                "description": p.description,
                "hardware_id": p.hwid
            })
        return result

    def _reclaim_port(self, port: str):
        """Stop a previous instance of this dashboard that may hold the port.

        Only the process recorded in the dashboard's own PID file is touched.
        An unrelated process holding the port is left alone and reported.
        """
        self.log(f"[WARNING] Port {port} is locked by another process (Tool v{self.VERSION}).", "WARNING")
        pid = instance.terminate_stale_instance()
        if pid is None:
            self.log(
                f"[RECLAIM] No previous dashboard instance found. Close whichever program is using {port} and retry.",
                "WARNING",
            )
            return
        self.log(f"[RECLAIM] Stopped previous dashboard instance (PID {pid}).", "INFO")
        time.sleep(0.8)

    def connect(self, port: str, baudrate: int = 115200) -> bool:
        if self.is_connected and self.port == port and self.baudrate == baudrate:
            return True

        self.disconnect()

        with self.lock:
            try:
                self.log(f"[PORT ATTEMPT] Opening {port} @ {baudrate} baud...", "INFO")
                self._wake_hint_shown = False
                self._hardware_info_loaded = False
                try:
                    self.ser = serial.Serial(port, baudrate, timeout=1.5)
                except serial.SerialException as e:
                    if "PermissionError" in str(e) or "Access is denied" in str(e):
                        self._reclaim_port(port)
                        self.ser = serial.Serial(port, baudrate, timeout=1.5)
                    else:
                        raise e

                self.port = port
                self.baudrate = baudrate
                self.is_connected = True
                self.is_demo = False
                self.state["connected"] = True
                self.state["port"] = port
                self.state["baudrate"] = baudrate
                self.state["mode"] = "REAL"
                self.state["modem_state"] = MODEM_PROBING
                self.state["connectivity_status"] = "Connected - Serial Active"
                self.running = True
                self.log(f"[SUCCESS] Serial port {port} opened successfully @ {baudrate} baud.", "INFO")

                if self._probe_modem():
                    self._poll_hardware_info()
                    self._hardware_info_loaded = True
                else:
                    self.log("[CONNECT] No answer to AT yet; will keep checking in the background.", "WARNING")

                self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
                self.poll_thread.start()

                self._notify("state", self.state)
                return True
            except Exception as e:
                self.log(f"[PORT ERROR] Could not open serial port {port}: {e}", "ERROR")
                # The lock is not re-entrant, so release resources without
                # going through disconnect(), which would take it again.
                self._reset_locked()
                return False

    def enable_demo_mode(self):
        self.disconnect()
        with self.lock:
            self.is_connected = True
            self.is_demo = True
            self.state["connected"] = True
            self.state["port"] = "DEMO-PORT (Simulated Quectel BC660K)"
            self.state["baudrate"] = 115200
            self.state["mode"] = "DEMO"
            self.state["connectivity_status"] = "Simulated Hardware Mode (--demo)"
            self.running = True
            self.state["system_info"].update({
                "imei": "860000000000000",
                "firmware": "BC660KGLAAR01A05 (simulated)",
                "ip_address": "10.142.88.204",
                "temperature": 31,
            })
            self.state["sim_info"]["sim_status"] = "READY"
            self.state["sim_info"]["iccid"] = DEMO_ICCID
            self.log("[DEMO MODE] Started hardware simulator (CLI --demo flag)", "INFO")

            self.poll_thread = threading.Thread(target=self._demo_loop, daemon=True)
            self.poll_thread.start()
            self._notify("state", self.state)
            return True

    def disconnect(self):
        self.running = False
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=1.0)

        with self.lock:
            self._reset_locked()

    def _reset_locked(self):
        """Close the port and reset state. The caller must hold ``self.lock``."""
        self.running = False
        self.db.end_session(self._session_id)
        self._session_id = None
        self._session_iccid = None
        old_port = self.port
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
                self.log(f"[PORT CLOSED] Closed serial port {old_port}.", "INFO")
            except Exception as e:
                self.log(f"[PORT ERROR] Error closing {old_port}: {e}", "ERROR")

        logs = self.state.get("logs", [])
        self.ser = None
        self.is_connected = False
        self.is_demo = False
        self.driver = DEFAULT_DRIVER
        self.state = self._get_initial_state()
        self.state["logs"] = logs
        self.state["connected"] = False
        self.state["mode"] = "DISCONNECTED"
        self.state["connectivity_status"] = "Disconnected"
        self._notify("state", self.state)

    def _set_modem_state(self, new_state: str):
        """Move the modem state machine, logging changes.

        Leaving the awake state means the module may have restarted or lost
        its settings (RESET, deep sleep), so the start-up profile is re-run
        the next time it answers.
        """
        old = self.state.get("modem_state")
        if new_state == old:
            return
        self.state["modem_state"] = new_state
        self.log(f"[MODEM STATE] {old} -> {new_state}", "INFO")
        if new_state in (MODEM_PSM, MODEM_DEEP_SLEEP, MODEM_UNRESPONSIVE):
            self._hardware_info_loaded = False

    def _read_idle_urcs(self):
        """Read unsolicited output that arrived between commands (for example
        ``+QNBIOTEVENT`` when the module enters PSM). The caller holds the lock."""
        self.channel.read_idle()

    def _handle_urc(self, line: str):
        """React to an unsolicited result code (+QNBIOTEVENT and +CEREG)."""
        line = line.strip()
        match = re.match(r'\+QNBIOTEVENT:\s*"([^"]+)"', line)
        if match:
            implied = NBIOT_EVENTS.get(match.group(1).upper())
            if implied:
                self._set_modem_state(implied)
            return
        # Registration URC form: +CEREG: <stat>[,<tac>,<ci>,...] (no leading <n>)
        urc = re.match(r'\+CEREG:\s*(\d+)(?:,"([0-9A-Fa-f]+)","([0-9A-Fa-f]+)")?', line)
        if urc and not re.match(r'\+CEREG:\s*\d+,\d+', line):
            self._apply_cereg(int(urc.group(1)), urc.group(2), urc.group(3))
            self._parse_cereg_granted(line, urc=True)

    def _show_wake_hint(self):
        """Tell the user, once per silence, how to wake the modem."""
        if not self._wake_hint_shown:
            self._wake_hint_shown = True
            self.log(self.WAKE_HINT, "WARNING")

    def _probe_modem(self, tries: Optional[int] = None) -> bool:
        """Send ``AT`` a few times to see whether the modem answers.

        A module waking from sleep can lose the first character, so a single
        failed attempt does not mean it is silent. The caller must hold the lock.
        """
        for _ in range(tries or self.PROBE_TRIES):
            if self.is_ok(self._send_at_cmd_raw("AT", timeout_sec=self.PROBE_TIMEOUT)):
                return True
        return False

    def _send_at_cmd_raw(
        self,
        cmd: str,
        timeout_sec: Optional[float] = None,
        wait_for: Optional["re.Pattern[str]"] = None,
        retries: int = 0,
    ) -> str:
        """Send one AT command through the channel. The caller holds ``self.lock``."""
        return self.channel.send(cmd, timeout_sec=timeout_sec, wait_for=wait_for, retries=retries)

    def _on_channel_response(self):
        """The modem answered: it is alive and awake."""
        if not self.state.get("hardware_communicated", False):
            self.state["hardware_communicated"] = True
            self.log("[HARDWARE OK] Initial modem communication established.", "INFO")
        self.state["modem_responding"] = True
        self._wake_hint_shown = False
        if self.state["modem_state"] != MODEM_DISCONNECTED:
            self._set_modem_state(MODEM_AWAKE)

    def _record_exchange(self, cmd: str, response: str, seconds: float):
        """Append an answered command to the transcript, if one is being recorded."""
        if self.recorder is not None:
            self.recorder.record(cmd, response, seconds)

    def _on_channel_timeout(self):
        """The modem stayed silent."""
        if self._scan_in_progress:
            return  # a scan we started keeps the module quiet; do not call it dead
        self.state["modem_responding"] = False
        if self.state["modem_state"] == MODEM_AWAKE:
            self._set_modem_state(MODEM_UNRESPONSIVE)
        self._show_wake_hint()

    def send_at_command(self, cmd: str) -> str:
        if self.is_demo:
            self.log(f"TX> {cmd.strip()}", "TX")
            resp = self._simulated_at_response(cmd.strip())
            self.log(f"RX< {resp.strip()}", "RX")
            return resp

        with self.lock:
            return self._send_at_cmd_raw(cmd, timeout_sec=timeout_for(cmd, default=30.0))

    def trigger_async_cops_scan(self):
        if self.state["is_scanning"]:
            return

        def _scan_worker():
            with self.scan_lock:
                self.state["is_scanning"] = True
                self._notify("state", self.state)
                self.log("[SCAN START] Scanning visible carrier spectrum (AT+COPS=?)...", "INFO")

                if self.is_demo:
                    time.sleep(2.5)
                    scanned = [
                        {"status": "Current", "status_code": 2, "long_name": "Vodafone UK", "short_name": "voda UK", "plmn": "23415", "act": "NB-IoT (E-UTRAN NB-S1)"},
                        {"status": "Available", "status_code": 1, "long_name": "EE", "short_name": "EE", "plmn": "23430", "act": "NB-IoT (E-UTRAN NB-S1)"},
                        {"status": "Available", "status_code": 1, "long_name": "O2 - UK", "short_name": "O2", "plmn": "23410", "act": "NB-IoT (E-UTRAN NB-S1)"},
                        {"status": "Forbidden", "status_code": 3, "long_name": "Three UK", "short_name": "3 UK", "plmn": "23420", "act": "NB-IoT (E-UTRAN NB-S1)"}
                    ]
                else:
                    with self.lock:
                        # The module does not answer anything else during a scan.
                        self._scan_in_progress = True
                        try:
                            resp = self._send_at_cmd_raw("AT+COPS=?")
                        finally:
                            self._scan_in_progress = False
                        scanned = self._parse_cops_scan(resp)
                    if resp == TIMEOUT_RESPONSE:
                        self.log("[SCAN FAILED] No answer to AT+COPS=? within the scan time allowed.", "WARNING")

                self.state["networks_scan"] = scanned
                self.state["is_scanning"] = False
                self.last_cops_scan_time = time.time()
                self.log(f"[SCAN COMPLETE] Spectrum search finished. Found {len(scanned)} networks.", "INFO")
                self._notify("state", self.state)

        threading.Thread(target=_scan_worker, daemon=True).start()

    def _poll_hardware_info(self):
        """Run the start-up profile: identity, SIM, power-saving state and network.

        Called once after the modem first answers. Commands a particular
        firmware does not support simply leave the corresponding field at its
        placeholder.
        """
        self._send_at_cmd_raw("ATE0")  # echo off, so responses hold only the reply

        # Module identity
        self._parse_ati(self._send_at_cmd_raw("ATI"))
        self._parse_cgmr(self._send_at_cmd_raw("AT+CGMR"))
        self._parse_imei(self._send_at_cmd_raw("AT+CGSN=1"))

        # SIM
        self._parse_cpin(self._send_at_cmd_raw("AT+CPIN?"))
        self._parse_iccid(self._send_at_cmd_raw("AT+QCCID"))
        self._last_identity_check = time.monotonic()
        self._parse_imsi(self._send_at_cmd_raw("AT+CIMI"))

        # Supply and temperature
        self._parse_cbc(self._send_at_cmd_raw("AT+CBC"))
        # Not every firmware supports AT+QTEMP. Only keep polling it if the
        # first query returned a value.
        self._parse_qtemp(self._send_at_cmd_raw("AT+QTEMP"))
        self._temp_supported = self.state["system_info"]["temperature"] is not None

        # Ask the module to announce PSM and deep-sleep transitions, where supported
        self.state["sleep_events"] = all(
            self.is_ok(self._send_at_cmd_raw(c)) for c in ("AT+QNBIOTEVENT=1,1", 'AT+QCFG="dsevent",1')
        )

        # Extended registration reports include the timers the network granted
        self._send_at_cmd_raw("AT+CEREG=4")

        # Power saving: read what the module is configured to do
        self._parse_cpsms(self._send_at_cmd_raw("AT+CPSMS?"))
        self._parse_cedrxs(self._send_at_cmd_raw("AT+CEDRXS?"))
        self._parse_qsclk(self._send_at_cmd_raw("AT+QSCLK?"))
        self._parse_cedrxrdp(self._send_at_cmd_raw("AT+CEDRXRDP"))

        # Packet domain
        self._parse_cgdcont(self._send_at_cmd_raw("AT+CGDCONT?"))
        self._parse_cgatt(self._send_at_cmd_raw("AT+CGATT?"))
        # Ask about the context AT+CGDCONT? reported: a real board uses context 0,
        # and AT+CGPADDR=1 then answers without an address.
        cid = self.state["apn_info"]["pdp_cid"]
        self._parse_cgpaddr(self._send_at_cmd_raw(f"AT+CGPADDR={cid}"))

    def _poll_once(self):
        """Run one poll cycle.

        The serial lock is taken for one command at a time, so a console
        command, APN change or ping can interleave between poll commands
        instead of waiting for the whole cycle. The cycle stops at the first
        timeout so an unresponsive modem is not asked for every command.
        """
        with self.lock:
            if self.running:
                self._read_idle_urcs()

        if not self._hardware_info_loaded:
            # Silent, asleep or just restarted: back off to a cheap probe until
            # the modem answers, then run the start-up profile again.
            with self.lock:
                if not self.running or not self._probe_modem(tries=1):
                    return
                self._poll_hardware_info()
                self._hardware_info_loaded = True

        # Fast items every cycle: the serving-cell command (AT+QENG=0 on the BC660K) carries RSRP/RSRQ/RSSI/SINR and the cells.
        if not self._run_step("AT+CSQ", self._parse_csq):
            return
        if not self._run_step(self.driver.cell_command, self._parse_cell):
            return
        if self.state["signal"]["rsrp"] is None:  # QENG gave no RSRP: ask CESQ instead
            if not self._run_step("AT+CESQ", self._parse_cesq):
                return

        # Slow-changing items on their own timers.
        slow_steps = [
            ("AT+COPS?", self._parse_cops_query),
            ("AT+CEREG?", self._parse_cereg_query),
            ("AT+CBC", self._parse_cbc),
        ]
        if self._temp_supported:
            slow_steps.append(("AT+QTEMP", self._parse_qtemp))
        for cmd, parser in slow_steps:
            if not self._slow_step_due(cmd):
                continue
            if not self._run_step(cmd, parser):
                return

        if time.monotonic() - self._last_identity_check >= self.IDENTITY_RECHECK_SECONDS:
            self._refresh_identity()

    def _slow_step_due(self, cmd: str) -> bool:
        """True when a slow-changing item has not been read for its interval."""
        interval = self.SLOW_POLL_SECONDS.get(cmd, self.DEFAULT_SLOW_POLL_SECONDS)
        last = self._last_slow_run.get(cmd)
        return last is None or time.monotonic() - last >= interval

    def _run_step(self, cmd: str, parser) -> bool:
        """Send one poll command and parse the reply.

        Returns False if the cycle should stop (shutting down or timed out).
        """
        if not self.running:
            return False
        with self.lock:
            if not self.running:
                return False
            resp = self._send_at_cmd_raw(cmd)
        if resp == TIMEOUT_RESPONSE:
            self.log(f"[POLL] '{cmd}' timed out, ending this cycle.", "WARNING")
            return False
        self._last_slow_run[cmd] = time.monotonic()
        parser(resp)
        return True

    def _refresh_identity(self):
        """Re-read the ICCID so a SIM swap or module reset is noticed.

        History is scoped by ICCID, so the view follows the SIM that is
        actually in the board.
        """
        self._last_identity_check = time.monotonic()
        previous = self.state["sim_info"]["iccid"]
        with self.lock:
            resp = self._send_at_cmd_raw("AT+QCCID")
            if self.state["edrx_info"].get("enabled"):
                self._parse_cedrxrdp(self._send_at_cmd_raw("AT+CEDRXRDP"))
        self._parse_iccid(resp)
        if "ERROR" in resp and "Timeout" not in resp:
            self.state["sim_info"]["iccid"] = "--"
        current = self.state["sim_info"]["iccid"]
        if current != previous:
            self.log("[SIM] SIM identity changed; history view follows the new SIM.", "WARNING")

    def _poll_loop(self):
        last_db_log = 0
        while self.running and self.is_connected and not self.is_demo:
            try:
                self._poll_once()

                self.state["last_update"] = time.time()

                if self.cops_scan_interval > 0 and (time.time() - self.last_cops_scan_time) >= self.cops_scan_interval:
                    self.trigger_async_cops_scan()

                if time.time() - last_db_log >= self.history_interval:
                    self._log_history()
                    last_db_log = time.time()

                self._notify("state", self.state)
            except Exception as e:
                self.py_logger.error(f"Error in poll loop: {e}")

            time.sleep(self.telemetry_interval)

    def _demo_loop(self):
        base_rsrp = -95
        base_rsrq = -11
        base_sinr = 14
        last_db_log = 0

        while self.running and self.is_demo:
            rsrp_noise = random.randint(-4, 4)
            rsrq_noise = random.randint(-2, 2)
            sinr_noise = random.randint(-3, 3)

            current_rsrp = max(-130, min(-55, base_rsrp + rsrp_noise))
            current_rsrq = max(-20, min(-3, base_rsrq + rsrq_noise))
            current_sinr = max(-10, min(30, base_sinr + sinr_noise))

            csq = max(0, min(31, int((current_rsrp + 113) / 2)))
            rssi = -113 + (csq * 2)

            label = "Excellent" if current_rsrp > -80 else ("Good" if current_rsrp > -95 else ("Fair" if current_rsrp > -110 else "Poor"))

            self.state["signal"] = {
                "rssi": rssi,
                "csq": csq,
                "rsrp": current_rsrp,
                "rsrq": current_rsrq,
                "sinr": current_sinr,
                "ber": 0,
                "quality_label": label
            }

            self.state["system_info"]["voltage"] = 3470 + random.randint(-20, 20)

            self.state["last_update"] = time.time()

            if self.cops_scan_interval > 0 and (time.time() - self.last_cops_scan_time) >= self.cops_scan_interval:
                self.trigger_async_cops_scan()

            if time.time() - last_db_log >= self.history_interval:
                self._log_history()
                last_db_log = time.time()

            self._notify("state", self.state)
            time.sleep(self.telemetry_interval)

    # --- Parsers ---
    def _parse_csq(self, resp: str):
        match = re.search(r"\+CSQ:\s*(\d+),(\d+)", resp)
        if match:
            csq = int(match.group(1))
            ber = int(match.group(2))
            if csq != 99:
                rssi = -113 + (csq * 2)
                self.state["signal"]["csq"] = csq
                self.state["signal"]["rssi"] = rssi
                self.state["signal"]["ber"] = ber

    def _parse_cesq(self, resp: str):
        match = re.search(r"\+CESQ:\s*(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)", resp)
        if match:
            rxlev, ber, rscp, ecno, rsrq, rsrp = [int(x) for x in match.groups()]
            if rsrp not in (255, 99):
                rsrp_dbm = -141 + rsrp
                self.state["signal"]["rsrp"] = rsrp_dbm
                self.state["signal"]["quality_label"] = self._quality_label(rsrp_dbm)
            if rsrq not in (255, 99):
                rsrq_db = -20 + (rsrq * 0.5)
                self.state["signal"]["rsrq"] = round(rsrq_db, 1)

    def _parse_ati(self, resp: str):
        """Store the firmware revision and pick the driver for the module's model.

        The model comes from the ``ATI`` reply. An unrecognised reply keeps the
        BC660K commands, which is what the dashboard was written for.
        """
        match = re.search(r"Revision:\s*(\S+)", resp)
        if match:
            self.state["system_info"]["firmware"] = match.group(1)
        driver = detect_driver(resp)
        if driver is None:
            replied = [ln for ln in resp.splitlines() if ln.strip() and ln.strip() not in ("OK", "ERROR")]
            if replied and self.state["system_info"]["module"] == "--":
                self.log("[MODULE] Model not recognised from ATI; using the BC660K commands.", "WARNING")
            return
        model = driver.model_name(resp)
        if driver is not self.driver or self.state["system_info"]["module"] != model:
            self.log(f"[MODULE] Detected {model}; serving cell via {driver.cell_command}.", "INFO")
        self.driver = driver
        self.state["system_info"]["module"] = model

    def _parse_cpin(self, resp: str):
        """Store the SIM state from ``+CPIN: <code>``."""
        match = re.search(r"\+CPIN:\s*([A-Z0-9 ]+)", resp)
        if match:
            self.state["sim_info"]["sim_status"] = match.group(1).strip()
        elif re.search(r"\+CME ERROR:\s*(?:10|SIM not inserted)", resp, re.I):
            self.state["sim_info"]["sim_status"] = "NOT INSERTED"

    def _parse_imei(self, resp: str):
        """Store the IMEI from ``+CGSN: <imei>`` or a bare 15 digit line."""
        match = re.search(r"\+CGSN:\s*\"?(\d{15})", resp) or re.search(r"(?m)^(\d{15})\s*$", resp)
        if match:
            self.state["system_info"]["imei"] = match.group(1)

    def _parse_qtemp(self, resp: str):
        """Store the module temperature in degrees Celsius, if reported."""
        match = re.search(r"\+QTEMP:\s*(-?\d+)(?:,\s*(-?\d+))?", resp)
        if match:
            self.state["system_info"]["temperature"] = int(match.group(2) or match.group(1))

    def _parse_cgmr(self, resp: str):
        """Use the ``AT+CGMR`` revision when ``ATI`` did not provide one."""
        if self.state["system_info"]["firmware"] != "--":
            return
        for line in resp.splitlines():
            line = line.strip()
            if line and line != "OK" and not line.startswith(("AT", "+", "ERROR")):
                self.state["system_info"]["firmware"] = line.split(":", 1)[-1].strip()
                return

    def _update_psm_text(self):
        """Refresh the human readable requested/granted PSM timers and the mismatch flag."""
        info = self.state["psm_info"]
        granted = info.setdefault("granted", {"t3412": None, "t3324": None})

        def describe(t3412, t3324):
            return (
                f"T3412 {timers.format_duration(timers.decode_t3412(t3412))}, "
                f"T3324 {timers.format_duration(timers.decode_t3324(t3324))}"
            )

        info["requested_text"] = describe(info["t3412"], info["t3324"]) if info.get("enabled") else "PSM off"
        if granted["t3412"] and granted["t3324"]:
            info["granted_text"] = describe(granted["t3412"], granted["t3324"])
            info["mismatch"] = bool(info.get("enabled")) and (
                timers.decode_t3412(granted["t3412"]) != timers.decode_t3412(info["t3412"])
                or timers.decode_t3324(granted["t3324"]) != timers.decode_t3324(info["t3324"])
            )
        else:
            info["granted_text"] = "Not reported"
            info["mismatch"] = False

    def _parse_cedrxrdp(self, resp: str):
        """Store the network-granted eDRX cycle from ``AT+CEDRXRDP``.

        ``+CEDRXRDP: <AcT>,"<requested>","<granted>","<paging time window>"``
        """
        match = re.search(r'\+CEDRXRDP:\s*\d+,\s*"([01]{4})"\s*,\s*"([01]{4})"', resp)
        info = self.state["edrx_info"]
        if match:
            requested, granted = match.groups()
            cycle = timers.decode_edrx_cycle(granted)
            info["granted"] = granted
            info["granted_text"] = f"{cycle:g} s cycle" if cycle else granted
            info["requested_text"] = (
                f"{timers.decode_edrx_cycle(requested):g} s cycle" if timers.decode_edrx_cycle(requested) else requested
            )
            info["mismatch"] = granted != requested
        elif self.is_ok(resp):
            info["granted"] = None
            info["granted_text"] = "Not reported"
            info["mismatch"] = False

    def _parse_cedrxs(self, resp: str):
        """Update ``edrx_info`` from an ``AT+CEDRXS?`` read-back.

        The module lists one ``+CEDRXS: <AcT>,"<requested cycle>"`` line per
        configured access technology. No line means eDRX is not configured.
        """
        match = re.search(r'\+CEDRXS:\s*\d+,\s*"([01]{4})"', resp)
        info = self.state["edrx_info"]
        if match:
            info["enabled"] = True
            info["value"] = match.group(1)
            info["status"] = "eDRX Enabled"
        elif self.is_ok(resp):
            info["enabled"] = False
            info["status"] = "eDRX Disabled"

    def _parse_qsclk(self, resp: str):
        """Store the slow-clock (light sleep) setting from ``+QSCLK: <n>``."""
        match = re.search(r"\+QSCLK:\s*(\d+)", resp)
        if match:
            self.state["system_info"]["sleep_clock"] = int(match.group(1))

    def _parse_iccid(self, resp: str):
        match = re.search(r"(?:89\d{16,18}\w?)", resp)
        if match:
            self.state["sim_info"]["iccid"] = match.group(0)

    def _parse_imsi(self, resp: str):
        match = re.search(r"(\d{15})", resp)
        if match:
            self.state["sim_info"]["imsi"] = match.group(1)

    def _parse_cbc(self, resp: str):
        match = re.search(r"\+CBC:\s*(\d+)", resp)
        if match:
            self.state["system_info"]["voltage"] = int(match.group(1))

    def _parse_cgdcont(self, resp: str):
        """Store context id, type and APN from ``+CGDCONT: <cid>,"<type>","<apn>"[,"<address>"...]``.

        A real BC660K-GL reports context 0 and, once attached, the assigned
        address in the fourth field; that is used until ``AT+CGPADDR`` confirms it.
        """
        match = re.search(r'\+CGDCONT:\s*(\d+),"([^"]+)","([^"]*)"(?:,"(\d{1,3}(?:\.\d{1,3}){3})")?', resp)
        if match:
            cid, pdp_type, apn, address = match.groups()
            self.state["apn_info"]["pdp_cid"] = int(cid)
            self.state["apn_info"]["pdp_type"] = pdp_type
            self.state["apn_info"]["apn"] = apn or "Default / Blank"
            if address and address != "0.0.0.0":
                self.state["system_info"]["ip_address"] = address

    def _parse_cgpaddr(self, resp: str):
        """Store the IPv4 address from ``+CGPADDR: <cid>,"<addr>"``."""
        match = re.search(r'\+CGPADDR:\s*\d+,\s*"?(\d{1,3}(?:\.\d{1,3}){3})"?', resp)
        if match:
            self.state["system_info"]["ip_address"] = match.group(1)

    def _parse_cgatt(self, resp: str):
        # +CGATT: 1
        match = re.search(r'\+CGATT:\s*(\d+)', resp)
        if match:
            att_code = int(match.group(1))
            self.state["apn_info"]["attached"] = (att_code == 1)

    @staticmethod
    def _quality_label(rsrp: int) -> str:
        """Map an RSRP value in dBm to a quality label."""
        if rsrp > -80:
            return "Excellent"
        if rsrp > -95:
            return "Good"
        if rsrp > -110:
            return "Fair"
        return "Poor"

    @staticmethod
    def _optional_int(text: str) -> Optional[int]:
        """Parse an optional integer field; empty or non-numeric gives None."""
        try:
            return int(text)
        except ValueError:
            return None

    @staticmethod
    def _hex_to_int(text: str) -> Optional[int]:
        try:
            return int(text, 16)
        except ValueError:
            return None

    def _parse_cell(self, resp: str):
        """Parse the serving-cell reply with the driver chosen for this module."""
        info = self.driver.parse_cell(resp)
        if info is not None:
            self._apply_cell_info(info)

    def _apply_cell_info(self, info: CellInfo):
        """Store what a driver read; fields it did not report keep their value."""
        signal = self.state["signal"]
        if info.rsrp is not None:
            signal["rsrp"] = info.rsrp
            signal["quality_label"] = self._quality_label(info.rsrp)
        for key in ("rsrq", "rssi", "sinr"):
            value = getattr(info, key)
            if value is not None:
                signal[key] = value

        if info.cell_id is not None or info.pci is not None or info.earfcn is not None:
            cell = self.state["serving_cell"]
            cell_dec = self._hex_to_int(info.cell_id or "")
            tac_dec = self._hex_to_int(info.tac or "")
            cell.update({
                "rat": info.rat,
                "cell_id": info.cell_id or "--",
                "cell_id_dec": cell_dec if cell_dec is not None else "--",
                "pci": info.pci if info.pci is not None else "--",
                "earfcn": info.earfcn if info.earfcn is not None else "--",
                "band": info.band or "--",
                "tac": info.tac or "--",
                "tac_dec": tac_dec if tac_dec is not None else "--",
            })
            if info.mcc is not None and info.mnc is not None:
                cell["mcc"], cell["mnc"] = info.mcc, info.mnc
            if info.operation_mode is not None:
                cell["operation_mode"] = info.operation_mode
        if info.neighbours is not None:
            self.state["neighbour_cells"] = info.neighbours

    def _parse_cops_query(self, resp: str):
        """Parse ``+COPS: <mode>,<format>,"<oper>",<AcT>``.

        With the numeric format (2), which a real BC660K-GL uses, ``<oper>`` is
        the PLMN (MCC followed by a 2 or 3 digit MNC). It is shown as a PLMN and
        also stored as ``mcc``/``mnc``, which ``AT+QENG=0`` does not report.
        """
        match = re.search(r'\+COPS:\s*\d+,\d+,"([^"]+)"', resp)
        if not match:
            return
        op = match.group(1)
        cell = self.state["serving_cell"]
        if re.fullmatch(r"\d{5,6}", op):
            cell["mcc"], cell["mnc"] = op[:3], op[3:]
            op = f"PLMN {op}"
        if op != self.last_cops_op:
            self.log(f"[NETWORK OPERATOR] Carrier: {op} (Previous: {self.last_cops_op})", "INFO")
            self.last_cops_op = op
        cell["operator"] = op

    def _parse_cereg_query(self, resp: str):
        """Parse the response to ``AT+CEREG?`` (``+CEREG: <n>,<stat>[,<tac>,<ci>,...]``)."""
        match = re.search(r'\+CEREG:\s*\d+,(\d+)(?:,"([0-9A-Fa-f]+)","([0-9A-Fa-f]+)")?', resp)
        if match:
            self._apply_cereg(int(match.group(1)), match.group(2), match.group(3))
            self._parse_cereg_granted(resp)

    def _apply_cereg(self, stat_code: int, tac_hex: Optional[str], cell_id_hex: Optional[str]):
        """Store registration status and, when present, the TAC and cell ID."""
        stat_str = CEREG_STAT_NAMES.get(stat_code, f"Stat {stat_code}")
        if stat_str != self.last_cereg_stat:
            self.log(f"[CONNECTIVITY STATE] EPS Registration: {stat_str}", "INFO")
            self.last_cereg_stat = stat_str
            self.state["connectivity_status"] = f"Network: {stat_str}"

        if tac_hex and cell_id_hex:
            cell_id_dec = self._hex_to_int(cell_id_hex)
            tac_dec = self._hex_to_int(tac_hex)
            self.state["serving_cell"].update({
                "tac": tac_hex,
                "tac_dec": tac_dec if tac_dec is not None else 0,
                "cell_id": cell_id_hex,
                "cell_id_dec": cell_id_dec if cell_id_dec is not None else 0,
            })

    def _parse_cereg_granted(self, resp: str, urc: bool = False):
        """Read the granted timers from an extended ``+CEREG`` report.

        Query form (``<n>`` = 4)::

            +CEREG: 4,<stat>,<tac>,<ci>,<AcT>,<cause_type>,<reject_cause>,"<Active-Time>","<Periodic-TAU>"

        The URC form has no leading ``<n>``, so the timers sit one field earlier.
        """
        line = re.search(r"\+CEREG:[^\r\n]*", resp)
        if not line:
            return
        fields = [f.strip().strip('"') for f in line.group(0).split(",")]
        first = 6 if urc else 7
        if len(fields) >= first + 2 and all(re.fullmatch(r"[01]{8}", f) for f in fields[first:first + 2]):
            granted = self.state["psm_info"].setdefault("granted", {})
            granted["t3324"], granted["t3412"] = fields[first], fields[first + 1]
            self._update_psm_text()

    def _parse_cops_scan(self, resp: str) -> List[Dict[str, Any]]:
        status_map = {0: "Unknown", 1: "Available", 2: "Current", 3: "Forbidden"}

        results = []
        matches = re.findall(r'\((?:(\d+),"([^"]+)","([^"]+)","([^"]+)"(?:,(\d+))?)\)', resp)
        for m in matches:
            stat_code = int(m[0])
            long_name = m[1]
            short_name = m[2]
            plmn = m[3]
            act_code = int(m[4]) if m[4] else None

            results.append({
                "status": status_map.get(stat_code, "Unknown"),
                "status_code": stat_code,
                "long_name": long_name,
                "short_name": short_name,
                "plmn": plmn,
                "act": COPS_ACT_NAMES.get(act_code, "Unknown" if act_code is None else f"AcT {act_code}")
            })
        return results

    def _simulated_at_response(self, cmd: str) -> str:
        c = cmd.upper()
        if c == "AT":
            return "OK\r\n"
        elif c == "ATI":
            return "Quectel_Ltd\r\nQuectel_BC660K-GL\r\nRevision: BC660KGLAAR01A05\r\n\r\nOK\r\n"
        elif c == "AT+CSQ":
            s = self.state["signal"]
            return f"+CSQ: {s['csq']},0\r\n\r\nOK\r\n"
        elif c == "AT+CPIN?":
            return "+CPIN: READY\r\n\r\nOK\r\n"
        elif c == "AT+QCCID" or c == "AT+NCCID":
            return f'+QCCID: {self.state["sim_info"]["iccid"]}\r\n\r\nOK\r\n'
        elif c == "AT+CIMI":
            return f'{self.state["sim_info"]["imsi"]}\r\n\r\nOK\r\n'
        elif c == "AT+CBC":
            return f'+CBC: {self.state["system_info"]["voltage"]}\r\n\r\nOK\r\n'
        elif c == "AT+CGDCONT?":
            apn = self.state["apn_info"]
            return f'+CGDCONT: {apn["pdp_cid"]},"{apn["pdp_type"]}","{apn["apn"]}","0.0.0.0",0,0,0,0\r\n\r\nOK\r\n'
        elif c == "AT+CGATT?":
            att = 1 if self.state["apn_info"]["attached"] else 0
            return f'+CGATT: {att}\r\n\r\nOK\r\n'
        elif c == "AT+QENG=0":
            sc = self.state["serving_cell"]
            sig = self.state["signal"]
            return (
                f'+QENG: 0,{sc["earfcn"]},0,{sc["pci"]},"{sc["cell_id"]}",{sig["rsrp"]},{sig["rsrq"]},'
                f'{sig["rssi"]},{sig["sinr"]},{sc["band"]},"{sc["tac"]}",0,23,0\r\n'
                '+QENG: 1,6300,321,-100,-12\r\n\r\nOK\r\n'
            )
        elif c == "AT+COPS?":
            sc = self.state["serving_cell"]
            return f'+COPS: 0,0,"{sc["operator"]}",9\r\n\r\nOK\r\n'
        elif c == "AT+COPS=?":
            return '+COPS: (2,"Vodafone UK","voda UK","23415",9),(1,"EE","EE","23430",9),(1,"O2 - UK","O2","23410",9),(3,"Three UK","3 UK","23420",9)\r\n\r\nOK\r\n'
        elif c == "AT+CEREG?":
            sc = self.state["serving_cell"]
            return f'+CEREG: 3,1,"{sc["tac"]}","{sc["cell_id"]}",9\r\n\r\nOK\r\n'
        else:
            return "OK\r\n"
