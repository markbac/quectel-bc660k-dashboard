import logging
import time
import re
import os
import sys
import threading
import random
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, List, Optional
import serial
import serial.tools.list_ports

import instance
from db_manager import DBManager
from pylogkit import setup_logging

__version__ = "1.2.0"
LOG_FILE_PATH = os.path.join(os.path.dirname(__file__), "dashboard_serial.log")

# Maximum response times from the BC660K-GL AT Commands Manual V1.3, plus a
# margin. Matched by prefix, first match wins, on the upper-cased command.
AT_TIMEOUTS = (
    ("AT+CGATT=", 70.0),
    ("AT+COPS=?", 35.0),
    ("AT+QENG", 15.0),
    ("AT+CSQ", 5.0),
    ("AT+CESQ", 5.0),
    ("AT+CGPADDR", 5.0),
    ("AT+CGMR", 5.0),
    ("AT+CGSN", 5.0),
    ("ATI", 5.0),
)
DEFAULT_AT_TIMEOUT = 5.0


def timeout_for(cmd: str, default: float = DEFAULT_AT_TIMEOUT) -> float:
    """Return the response timeout in seconds for an AT command."""
    normalised = cmd.strip().upper().replace(" ", "")
    for prefix, seconds in AT_TIMEOUTS:
        if normalised.startswith(prefix):
            return seconds
    return default


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
DEMO_ICCID = "DEMO-SIMULATED-SIM"


class SerialManager:
    VERSION = __version__
    IDENTITY_RECHECK_SECONDS = 60.0
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
    ):
        """Create a manager.

        Args:
            file_logging_enabled: Write the serial log to disk.
            telemetry_interval: Seconds between poll cycles.
            cops_scan_interval: Seconds between operator scans (0 disables).
            db_path: SQLite file to use. Defaults to the per-user data directory
                (see ``db_manager.default_db_path``).
            log_file_path: Log file to use. Defaults to ``dashboard_serial.log``.
        """
        self.ser: Optional[serial.Serial] = None
        self.port: Optional[str] = None
        self.baudrate: int = 115200
        self.is_connected: bool = False
        self.is_demo: bool = False

        self.lock = threading.Lock()
        self.scan_lock = threading.Lock()

        self.poll_thread: Optional[threading.Thread] = None
        self.running: bool = False
        self.callbacks = []
        self.db = DBManager(db_path) if db_path else DBManager()

        self.telemetry_interval: int = telemetry_interval
        self.cops_scan_interval: int = cops_scan_interval
        self.last_cops_scan_time: float = 0

        self.file_logging_enabled: bool = file_logging_enabled
        self.log_file_path: str = log_file_path or LOG_FILE_PATH

        self.py_logger = setup_logging(
            name="QuectelManager",
            to_console=True,
            to_file=self.file_logging_enabled,
            file_path=self.log_file_path,
            level="DEBUG"
        )
        self.py_logger.info(f"Quectel BC660K Serial Manager v{self.VERSION} Initialized.")

        self.last_cops_op: str = "Unknown"
        self.last_cereg_stat: str = "Unknown"
        self._temp_supported: bool = False
        self._last_identity_check: float = 0.0

        # Current state cache
        self.state = self._get_initial_state()

    def _get_initial_state(self) -> Dict[str, Any]:
        return {
            "connected": False,
            "port": None,
            "baudrate": 115200,
            "mode": "DISCONNECTED",
            "hardware_communicated": False,
            "file_logging_enabled": self.file_logging_enabled,
            "telemetry_interval": self.telemetry_interval,
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
                "firmware": "--"
            },
            "neighbour_cells": [],
            "networks_scan": [],
            "is_scanning": False,
            "psm_info": {
                "enabled": False,
                "t3412": "10100101",
                "t3324": "00100100",
                "status": "PSM Disabled"
            },
            "edrx_info": {
                "enabled": False,
                "value": "0010",
                "status": "eDRX Disabled"
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

    def update_settings(self, telemetry_interval: Optional[int] = None, cops_scan_interval: Optional[int] = None):
        if telemetry_interval is not None and telemetry_interval >= 1:
            self.telemetry_interval = telemetry_interval
            self.state["telemetry_interval"] = telemetry_interval

        if cops_scan_interval is not None and cops_scan_interval >= 0:
            self.cops_scan_interval = cops_scan_interval
            self.state["cops_scan_interval"] = cops_scan_interval

        self.log(f"[CONFIG] Updated intervals: Telemetry={self.telemetry_interval}s, COPS Scan={self.cops_scan_interval}s", "INFO")
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
        self._apply_file_logging(enabled)
        self.file_logging_enabled = enabled
        self.state["file_logging_enabled"] = enabled
        status_msg = "ENABLED" if enabled else "DISABLED"
        self.log(f"[CONFIG] Disk file logging {status_msg} ({self.log_file_path})", "INFO")
        self._notify("state", self.state)

    def _apply_file_logging(self, enabled: bool):
        """Attach or detach the rotating file handler on the logger."""
        handlers = [h for h in self.py_logger.handlers if isinstance(h, RotatingFileHandler)]
        if enabled and not handlers:
            handler = RotatingFileHandler(
                self.log_file_path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] [%(name)s] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            ))
            self.py_logger.addHandler(handler)
        elif not enabled:
            for handler in handlers:
                self.py_logger.removeHandler(handler)
                handler.close()

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
            self.log("[PSM OK] Simulated PSM updated.", "INFO")
            self._notify("state", self.state)
            return "OK"

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

    @staticmethod
    def is_ok(resp: str) -> bool:
        """True when a response contains a final ``OK`` line."""
        return bool(re.search(r"(?m)^OK\s*$", resp))

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

    # AT+QPING ends with a summary line (or a bare error code). The per-reply
    # lines carry a quoted address and do not match.
    _PING_DONE = re.compile(r"\+QPING:\s*(?:\d+,\d+,\d+,\d+(?:,\d+,\d+,\d+)?|\d+)\s*$", re.M)
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
            min_rtt, max_rtt, avg_rtt = rtts if len(rtts) == 3 else (None, None, None)
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
            self.py_logger.debug(f"TX> {ascii_text}")
        elif direction == "RX":
            self.py_logger.debug(f"RX< {ascii_text}")
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
                self.state["connectivity_status"] = "Connected - Serial Active"
                self.running = True
                self.log(f"[SUCCESS] Serial port {port} opened successfully @ {baudrate} baud.", "INFO")

                self._poll_hardware_info()

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
        self.state = self._get_initial_state()
        self.state["logs"] = logs
        self.state["connected"] = False
        self.state["mode"] = "DISCONNECTED"
        self.state["connectivity_status"] = "Disconnected"
        self._notify("state", self.state)

    # Lines that mark the end of a command response.
    _FINAL_RESULT = re.compile(r"(?m)^(?:OK|ERROR|\+CME ERROR:.*|\+CMS ERROR:.*)\s*$")
    # Unsolicited result codes that may be interleaved with a response.
    _URC_PREFIXES = ("+CEREG", "+CSCON", "+QNBIOTEVENT", "+CGEV", "+CREG", "+CGREG", "+CPIN", "+PSM_EINT")

    def _drain_input(self, quiet_sec: float = 0.0, max_sec: float = 0.0) -> str:
        """Read and discard pending serial input.

        With ``quiet_sec`` set, keep reading until the line has been quiet for
        that long (or ``max_sec`` elapses), so a late reply cannot leak into
        the next command.
        """
        discarded = ""
        deadline = time.time() + max_sec
        last_data = time.time()
        while True:
            if self.ser.in_waiting > 0:
                discarded += self.ser.read(self.ser.in_waiting).decode("ascii", errors="replace")
                last_data = time.time()
            elif quiet_sec <= 0 or time.time() - last_data >= quiet_sec or time.time() >= deadline:
                break
            else:
                time.sleep(0.02)
        return discarded

    def _split_urcs(self, cmd: str, response: str) -> str:
        """Remove unsolicited lines from a response and log them separately.

        A line is kept when it belongs to the command itself, for example the
        ``+CEREG:`` line returned for ``AT+CEREG?``.
        """
        own = re.match(r"AT(\+[A-Z0-9_]+)", cmd.upper())
        own_prefix = own.group(1) if own else ""
        kept = []
        for line in response.splitlines(keepends=True):
            stripped = line.strip()
            is_urc = stripped.startswith(self._URC_PREFIXES) and not (
                own_prefix and stripped.upper().startswith(own_prefix)
            )
            if is_urc:
                self.log(f"URC< {stripped}", "RX")
            else:
                kept.append(line)
        return "".join(kept)

    def _send_at_cmd_raw(
        self,
        cmd: str,
        timeout_sec: Optional[float] = None,
        wait_for: Optional["re.Pattern[str]"] = None,
    ) -> str:
        """Send one AT command and return its response.

        ``timeout_sec`` defaults to the documented maximum for the command
        (see ``AT_TIMEOUTS``). Some commands (``AT+QPING``, ``AT+QIDNSGIP``)
        answer ``OK`` first and deliver the result later as unsolicited
        lines. For those, ``wait_for`` is a pattern that must also appear
        before the response is considered complete; on timeout the partial
        response is returned.

        Pending input is discarded before sending so a reply that arrived
        late for an earlier command is not mistaken for this one. After a
        timeout the line is drained until quiet before returning.
        """
        if not self.ser or not self.ser.is_open:
            return "ERROR: Port not open"

        if timeout_sec is None:
            timeout_sec = timeout_for(cmd)

        if not cmd.endswith("\r\n"):
            cmd_str = cmd + "\r\n"
        else:
            cmd_str = cmd

        self.log(f"TX> {cmd_str.strip()}", "TX")
        try:
            stale = self._drain_input()
            if stale.strip():
                self.log(f"[STALE] Discarded unread output before '{cmd.strip()}': {stale.strip()!r}", "WARNING")

            self.ser.write(cmd_str.encode("ascii", errors="ignore"))
            response = ""
            start = time.time()
            timed_out = True

            while time.time() - start < timeout_sec:
                if self.ser.in_waiting > 0:
                    response += self.ser.read(self.ser.in_waiting).decode("ascii", errors="replace")
                    if self._FINAL_RESULT.search(response) and (wait_for is None or wait_for.search(response)):
                        timed_out = False
                        break
                else:
                    time.sleep(0.02)

            if timed_out:
                late = self._drain_input(quiet_sec=0.3, max_sec=1.0)
                if late.strip():
                    self.log(f"[LATE] Discarded late output after timeout: {late.strip()!r}", "WARNING")
                if not response:
                    self.log(f"[TIMEOUT] No response for '{cmd.strip()}' after {timeout_sec}s.", "ERROR")
                    return "ERROR: Timeout"

            if not self.state.get("hardware_communicated", False):
                self.state["hardware_communicated"] = True
                self.log("[HARDWARE OK] Initial modem communication established.", "INFO")

            response = self._split_urcs(cmd, response)
            self.log(f"RX< {response.strip()}", "RX")
            return response
        except Exception as e:
            self.log(f"[SERIAL IO ERROR] TX/RX failure on {cmd.strip()}: {e}", "ERROR")
            return f"ERROR: {e}"

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
                        resp = self._send_at_cmd_raw("AT+COPS=?")
                        scanned = self._parse_cops_scan(resp)

                self.state["networks_scan"] = scanned
                self.state["is_scanning"] = False
                self.last_cops_scan_time = time.time()
                self.log(f"[SCAN COMPLETE] Spectrum search finished. Found {len(scanned)} networks.", "INFO")
                self._notify("state", self.state)

        threading.Thread(target=_scan_worker, daemon=True).start()

    def _poll_hardware_info(self):
        """Read static identity and status information once after connecting."""
        self._parse_ati(self._send_at_cmd_raw("ATI"))
        self._parse_cpin(self._send_at_cmd_raw("AT+CPIN?"))
        self._parse_imei(self._send_at_cmd_raw("AT+CGSN=1"))

        iccid_resp = self._send_at_cmd_raw("AT+QCCID")
        self._parse_iccid(iccid_resp)
        self._last_identity_check = time.monotonic()

        imsi_resp = self._send_at_cmd_raw("AT+CIMI")
        self._parse_imsi(imsi_resp)

        cbc_resp = self._send_at_cmd_raw("AT+CBC")
        self._parse_cbc(cbc_resp)

        # Not every firmware supports AT+QTEMP. Only keep polling it if the
        # first query returned a value.
        self._parse_qtemp(self._send_at_cmd_raw("AT+QTEMP"))
        self._temp_supported = self.state["system_info"]["temperature"] is not None

        cgdcont_resp = self._send_at_cmd_raw("AT+CGDCONT?")
        self._parse_cgdcont(cgdcont_resp)

        cgatt_resp = self._send_at_cmd_raw("AT+CGATT?")
        self._parse_cgatt(cgatt_resp)

        self._parse_cgpaddr(self._send_at_cmd_raw("AT+CGPADDR=1"))

    def _poll_once(self):
        """Run one poll cycle. The caller must hold ``self.lock``.

        The cycle stops at the first timeout so an unresponsive modem does
        not hold the lock for the sum of every command's timeout.
        """
        steps = [
            ("AT+CSQ", self._parse_csq),
            ("AT+CESQ", self._parse_cesq),
            ("AT+QENG=0", self._parse_qeng),
            ("AT+COPS?", self._parse_cops_query),
            ("AT+CEREG?", self._parse_cereg_query),
            ("AT+CBC", self._parse_cbc),
        ]
        if self._temp_supported:
            steps.append(("AT+QTEMP", self._parse_qtemp))

        for cmd, parser in steps:
            if not self.running:
                return
            resp = self._send_at_cmd_raw(cmd)
            if resp == "ERROR: Timeout":
                self.log(f"[POLL] '{cmd}' timed out, ending this cycle.", "WARNING")
                return
            parser(resp)

        if time.monotonic() - self._last_identity_check >= self.IDENTITY_RECHECK_SECONDS:
            self._refresh_identity()

    def _refresh_identity(self):
        """Re-read the ICCID so a SIM swap or module reset is noticed.

        History is scoped by ICCID, so the view follows the SIM that is
        actually in the board.
        """
        self._last_identity_check = time.monotonic()
        previous = self.state["sim_info"]["iccid"]
        resp = self._send_at_cmd_raw("AT+QCCID")
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
                with self.lock:
                    self._poll_once()

                self.state["last_update"] = time.time()

                if self.cops_scan_interval > 0 and (time.time() - self.last_cops_scan_time) >= self.cops_scan_interval:
                    self.trigger_async_cops_scan()

                if time.time() - last_db_log >= 5.0:
                    self.db.log_record(self.state)
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

            if time.time() - last_db_log >= 4.0:
                self.db.log_record(self.state)
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
        """Store the firmware revision from the ``Revision:`` line of ``ATI``."""
        match = re.search(r"Revision:\s*(\S+)", resp)
        if match:
            self.state["system_info"]["firmware"] = match.group(1)

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
        # +CGDCONT: 1,"IP","iot.vodafone.com","0.0.0.0",0,0,0,0
        match = re.search(r'\+CGDCONT:\s*(\d+),"([^"]+)","([^"]*)"', resp)
        if match:
            cid, pdp_type, apn = match.groups()
            self.state["apn_info"]["pdp_cid"] = int(cid)
            self.state["apn_info"]["pdp_type"] = pdp_type
            self.state["apn_info"]["apn"] = apn or "Default / Blank"

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

    def _parse_qeng(self, resp: str):
        """Parse ``AT+QENG=0`` (serving cell and neighbour cells).

        Documented format (BC660K-GL AT Commands Manual V1.3)::

            +QENG: 0,<earfcn>,<earfcn_offset>,<pci>,<cell_id>,[<rsrp>],[<rsrq>],
                   [<rssi>],[<sinr>],<band>,<tac>,[<ecl>],[<tx_pwr>],<operation_mode>
            +QENG: 1,<earfcn>,<pci>,<rsrp>,<rsrq>          (one per neighbour)

        Optional fields may be empty. Neighbours are replaced on every call so
        a cell that disappears is removed.
        """
        neighbours = []
        for line in resp.splitlines():
            line = line.strip()
            if not line.startswith("+QENG:"):
                continue
            fields = [f.strip().strip('"') for f in line[len("+QENG:"):].split(",")]
            if fields[0] == "0" and len(fields) >= 11:
                self._apply_serving_cell(fields)
            elif fields[0] == "1" and len(fields) >= 5:
                earfcn, pci, rsrp, rsrq = (self._optional_int(f) for f in fields[1:5])
                if earfcn is not None and pci is not None:
                    neighbours.append({
                        "rat": "NB-IoT",
                        "earfcn": earfcn,
                        "pci": pci,
                        "rsrp": rsrp,
                        "rsrq": rsrq,
                    })
        if "+QENG:" in resp:
            self.state["neighbour_cells"] = neighbours

    def _apply_serving_cell(self, fields: List[str]):
        """Store the serving-cell fields of one ``+QENG: 0,...`` line."""
        earfcn = self._optional_int(fields[1])
        pci = self._optional_int(fields[3])
        cell_id = fields[4]
        rsrp, rsrq, rssi, sinr = (self._optional_int(f) for f in fields[5:9])
        band = fields[9]
        tac = fields[10]

        signal = self.state["signal"]
        if rsrp is not None:
            signal["rsrp"] = rsrp
            signal["quality_label"] = self._quality_label(rsrp)
        if rsrq is not None:
            signal["rsrq"] = rsrq
        if rssi is not None:
            signal["rssi"] = rssi
        if sinr is not None:
            signal["sinr"] = sinr

        cell_dec = self._hex_to_int(cell_id)
        tac_dec = self._hex_to_int(tac)
        self.state["serving_cell"].update({
            "rat": "NB-IoT",
            "cell_id": cell_id or "--",
            "cell_id_dec": cell_dec if cell_dec is not None else "--",
            "pci": pci if pci is not None else "--",
            "earfcn": earfcn if earfcn is not None else "--",
            "band": band or "--",
            "tac": tac or "--",
            "tac_dec": tac_dec if tac_dec is not None else "--",
        })
        if len(fields) >= 14:
            self.state["serving_cell"]["operation_mode"] = fields[13]

    def _parse_cops_query(self, resp: str):
        match = re.search(r'\+COPS:\s*\d+,\d+,"([^"]+)"', resp)
        if match:
            op = match.group(1)
            if op != self.last_cops_op:
                self.log(f"[NETWORK OPERATOR] Carrier: {op} (Previous: {self.last_cops_op})", "INFO")
                self.last_cops_op = op
            self.state["serving_cell"]["operator"] = op

    def _parse_cereg_query(self, resp: str):
        match = re.search(r'\+CEREG:\s*\d+,(\d+)(?:,"([0-9A-Fa-f]+)","([0-9A-Fa-f]+)")?', resp)
        if match:
            stat_code = int(match.group(1))
            stat_str = CEREG_STAT_NAMES.get(stat_code, f"Stat {stat_code}")
            if stat_str != self.last_cereg_stat:
                self.log(f"[CONNECTIVITY STATE] EPS Registration: {stat_str}", "INFO")
                self.last_cereg_stat = stat_str
                self.state["connectivity_status"] = f"Network: {stat_str}"

            if match.group(2) and match.group(3):
                tac_hex = match.group(2)
                cell_id_hex = match.group(3)
                try:
                    cell_id_dec = int(cell_id_hex, 16)
                    tac_dec = int(tac_hex, 16)
                except ValueError:
                    cell_id_dec, tac_dec = 0, 0

                self.state["serving_cell"].update({
                    "tac": tac_hex,
                    "tac_dec": tac_dec,
                    "cell_id": cell_id_hex,
                    "cell_id_dec": cell_id_dec
                })

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
