import time
import re
import os
import sys
import threading
import random
import subprocess
from typing import Dict, Any, List, Optional
import serial
import serial.tools.list_ports

from db_manager import DBManager
from pylogkit import setup_logging

LOG_FILE_PATH = os.path.join(os.path.dirname(__file__), "dashboard_serial.log")

class SerialManager:
    def __init__(self, file_logging_enabled: bool = True, telemetry_interval: int = 3, cops_scan_interval: int = 60):
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
        self.db = DBManager()

        self.telemetry_interval: int = telemetry_interval
        self.cops_scan_interval: int = cops_scan_interval
        self.last_cops_scan_time: float = 0

        self.file_logging_enabled: bool = file_logging_enabled
        self.log_file_path: str = LOG_FILE_PATH

        self.py_logger = setup_logging(
            name="QuectelManager",
            to_console=True,
            to_file=self.file_logging_enabled,
            file_path=self.log_file_path,
            level="DEBUG"
        )

        self.last_cops_op: str = "Unknown"
        self.last_cereg_stat: str = "Unknown"

        # Current state cache
        self.state = {
            "connected": False,
            "port": None,
            "baudrate": 115200,
            "mode": "DISCONNECTED",
            "file_logging_enabled": self.file_logging_enabled,
            "telemetry_interval": self.telemetry_interval,
            "cops_scan_interval": self.cops_scan_interval,
            "connectivity_status": "No Connection",
            "signal": {
                "rssi": -85,
                "csq": 14,
                "rsrp": -98,
                "rsrq": -10,
                "sinr": 12,
                "ber": 0,
                "quality_label": "Good"
            },
            "apn_info": {
                "apn": "iot.vodafone.com",
                "pdp_type": "IP",
                "attached": True,
                "pdp_cid": 1
            },
            "serving_cell": {
                "rat": "NB-IoT",
                "state": "CONNECTED",
                "mcc": "234",
                "mnc": "15",
                "operator": "Vodafone UK",
                "cell_id": "1D2F401",
                "cell_id_dec": 30602241,
                "pci": 320,
                "earfcn": 6300,
                "band": "8",
                "tac": "5F4E",
                "tac_dec": 24398
            },
            "sim_info": {
                "iccid": "89882390000692255782",
                "imsi": "901280085050088",
                "sim_status": "READY",
                "number": "Unknown / Network Assigned"
            },
            "system_info": {
                "imei": "860492040182941",
                "ip_address": "Not Connected",
                "voltage": 3470,
                "temperature": 28.5,
                "firmware": "BC660KGLAAR01A05"
            },
            "location": {
                "lat": 51.5074,
                "lon": -0.1278,
                "accuracy": 450,
                "source": "Cell Tower Geolocation"
            },
            "neighbour_cells": [],
            "networks_scan": [],
            "is_scanning": False,
            "last_update": time.time(),
            "logs": []
        }

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
            
            # Trigger packet domain attach
            resp2 = self._send_at_cmd_raw("AT+CGATT=1")
            
            # Refresh assigned IP
            ip_resp = self._send_at_cmd_raw("AT+CGPADDR=1")
            self._parse_ip(ip_resp)
            self._parse_cgdcont(self._send_at_cmd_raw("AT+CGDCONT?"))
            self._parse_cgatt(self._send_at_cmd_raw("AT+CGATT?"))
            
            self._notify("state", self.state)
            return f"{resp1}\n{resp2}"

    def set_file_logging(self, enabled: bool):
        self.file_logging_enabled = enabled
        self.state["file_logging_enabled"] = enabled
        status_msg = "ENABLED" if enabled else "DISABLED"
        self.log(f"[CONFIG] Disk file logging {status_msg} ({self.log_file_path})", "INFO")
        self._notify("state", self.state)

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
        self.log(f"[WARNING] Port {port} is locked by another process! Attempting to free port handle...", "WARNING")
        try:
            cmd = f'powershell -Command "Get-CimInstance Win32_Process | Where-Object {{ $_.ProcessId -ne {os.getpid()} -and ($_.Name -eq \'python.exe\' -or $_.CommandLine -like \'*server.py*\') }} | Stop-Process -Force -ErrorAction SilentlyContinue"'
            subprocess.run(cmd, shell=True, timeout=3)
            time.sleep(0.5)
        except Exception as e:
            self.log(f"[RECLAIM ERROR] Could not terminate locking process: {e}", "ERROR")

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

                self.trigger_async_cops_scan()

                self._notify("state", self.state)
                return True
            except Exception as e:
                self.log(f"[PORT ERROR] Could not open serial port {port}: {e}", "ERROR")
                self.disconnect()
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
            old_port = self.port
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                    self.log(f"[PORT CLOSED] Closed serial port {old_port}.", "INFO")
                except Exception as e:
                    self.log(f"[PORT ERROR] Error closing {old_port}: {e}", "ERROR")

            self.ser = None
            self.is_connected = False
            self.is_demo = False
            self.state["connected"] = False
            self.state["mode"] = "DISCONNECTED"
            self.state["connectivity_status"] = "Disconnected"
            self._notify("state", self.state)

    def _send_at_cmd_raw(self, cmd: str, timeout_sec: float = 2.0) -> str:
        if not self.ser or not self.ser.is_open:
            return "ERROR: Port not open"

        if not cmd.endswith("\r\n"):
            cmd_str = cmd + "\r\n"
        else:
            cmd_str = cmd

        self.log(f"TX> {cmd_str.strip()}", "TX")
        try:
            self.ser.write(cmd_str.encode("ascii", errors="ignore"))
            time.sleep(0.1)
            response = ""
            start = time.time()
            timed_out = True

            while time.time() - start < timeout_sec:
                if self.ser.in_waiting > 0:
                    chunk = self.ser.read(self.ser.in_waiting).decode("ascii", errors="replace")
                    response += chunk
                    if "OK\r\n" in response or "ERROR\r\n" in response:
                        timed_out = False
                        break
                time.sleep(0.04)

            if timed_out and not response:
                self.log(f"[TIMEOUT] No response for '{cmd.strip()}' after {timeout_sec}s.", "ERROR")
                return "ERROR: Timeout"

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
            return self._send_at_cmd_raw(cmd, timeout_sec=3.0)

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
                        {"status": "Current", "status_code": 2, "long_name": "Vodafone UK", "short_name": "voda UK", "plmn": "23415", "act": "LTE Cat NB2"},
                        {"status": "Available", "status_code": 1, "long_name": "EE", "short_name": "EE", "plmn": "23430", "act": "LTE Cat NB2"},
                        {"status": "Available", "status_code": 1, "long_name": "O2 - UK", "short_name": "O2", "plmn": "23410", "act": "LTE Cat NB2"},
                        {"status": "Forbidden", "status_code": 3, "long_name": "Three UK", "short_name": "3 UK", "plmn": "23420", "act": "LTE Cat NB2"}
                    ]
                else:
                    with self.lock:
                        resp = self._send_at_cmd_raw("AT+COPS=?", timeout_sec=35.0)
                        scanned = self._parse_cops_scan(resp)

                self.state["networks_scan"] = scanned
                self.state["is_scanning"] = False
                self.last_cops_scan_time = time.time()
                self.log(f"[SCAN COMPLETE] Spectrum search finished. Found {len(scanned)} networks.", "INFO")
                self._notify("state", self.state)

        threading.Thread(target=_scan_worker, daemon=True).start()

    def _poll_hardware_info(self):
        self._send_at_cmd_raw("ATI")
        self._send_at_cmd_raw("AT+CPIN?")

        iccid_resp = self._send_at_cmd_raw("AT+QCCID")
        self._parse_iccid(iccid_resp)

        imsi_resp = self._send_at_cmd_raw("AT+CIMI")
        self._parse_imsi(imsi_resp)

        cbc_resp = self._send_at_cmd_raw("AT+CBC")
        self._parse_cbc(cbc_resp)

        cgdcont_resp = self._send_at_cmd_raw("AT+CGDCONT?")
        self._parse_cgdcont(cgdcont_resp)

        cgatt_resp = self._send_at_cmd_raw("AT+CGATT?")
        self._parse_cgatt(cgatt_resp)

    def _poll_loop(self):
        last_db_log = 0
        while self.running and self.is_connected and not self.is_demo:
            try:
                with self.lock:
                    csq_resp = self._send_at_cmd_raw("AT+CSQ")
                    self._parse_csq(csq_resp)

                    qeng_resp = self._send_at_cmd_raw('AT+QENG="servingcell"')
                    self._parse_qeng_serving(qeng_resp)

                    cops_resp = self._send_at_cmd_raw("AT+COPS?")
                    self._parse_cops_query(cops_resp)

                    cereg_resp = self._send_at_cmd_raw("AT+CEREG?")
                    self._parse_cereg_query(cereg_resp)

                    cbc_resp = self._send_at_cmd_raw("AT+CBC")
                    self._parse_cbc(cbc_resp)

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

    def _parse_cgatt(self, resp: str):
        # +CGATT: 1
        match = re.search(r'\+CGATT:\s*(\d+)', resp)
        if match:
            att_code = int(match.group(1))
            self.state["apn_info"]["attached"] = (att_code == 1)

    def _parse_qeng_serving(self, resp: str):
        match = re.search(r'\+QENG:\s*"servingcell","([^"]+)","([^"]+)","([^"]+)",(\d+),(\d+),([0-9A-Fa-f]+),(\d+),(\d+),(\d+),.*?([0-9A-Fa-f]+),(-?\d+),(-?\d+),(-?\d+),(-?\d+)', resp)
        if match:
            cell_state, rat, duplex, mcc, mnc, cell_id_hex, pci, earfcn, band, tac_hex, rsrp, rsrq, rssi, sinr = match.groups()
            try:
                cell_id_dec = int(cell_id_hex, 16)
            except ValueError:
                cell_id_dec = 0

            try:
                tac_dec = int(tac_hex, 16)
            except ValueError:
                tac_dec = 0

            rsrp_val = int(rsrp)
            rsrq_val = int(rsrq)
            rssi_val = int(rssi)
            sinr_val = int(sinr)

            label = "Excellent" if rsrp_val > -80 else ("Good" if rsrp_val > -95 else ("Fair" if rsrp_val > -110 else "Poor"))

            self.state["signal"]["rsrp"] = rsrp_val
            self.state["signal"]["rsrq"] = rsrq_val
            self.state["signal"]["rssi"] = rssi_val
            self.state["signal"]["sinr"] = sinr_val
            self.state["signal"]["quality_label"] = label

            self.state["serving_cell"].update({
                "rat": rat,
                "state": cell_state,
                "mcc": mcc,
                "mnc": mnc,
                "cell_id": cell_id_hex,
                "cell_id_dec": cell_id_dec,
                "pci": int(pci),
                "earfcn": int(earfcn),
                "band": band,
                "tac": tac_hex,
                "tac_dec": tac_dec
            })

    def _parse_cops_query(self, resp: str):
        match = re.search(r'\+COPS:\s*\d+,\d+,"([^"]+)"', resp)
        if match:
            op = match.group(1)
            if op != self.last_cops_op:
                self.log(f"[NETWORK OPERATOR] Carrier: {op} (Previous: {self.last_cops_op})", "INFO")
                self.last_cops_op = op
            self.state["serving_cell"]["operator"] = op

    def _parse_cereg_query(self, resp: str):
        match = re.search(r'\+CEREG:\s*\d+,(\d+)', resp)
        if match:
            stat_code = int(match.group(1))
            stat_names = {
                0: "Not registered, searching...",
                1: "Registered, home network",
                2: "Not registered, searching...",
                3: "Registration denied",
                4: "Unknown / Out of coverage",
                5: "Registered, roaming"
            }
            stat_str = stat_names.get(stat_code, f"Stat {stat_code}")
            if stat_str != self.last_cereg_stat:
                self.log(f"[CONNECTIVITY STATE] EPS Registration: {stat_str}", "INFO")
                self.last_cereg_stat = stat_str
                self.state["connectivity_status"] = f"Network: {stat_str}"

    def _parse_cops_scan(self, resp: str) -> List[Dict[str, Any]]:
        status_map = {0: "Unknown", 1: "Available", 2: "Current", 3: "Forbidden"}
        act_map = {0: "GSM", 2: "UTRAN (3G)", 7: "LTE Cat M1", 9: "LTE Cat NB2"}

        results = []
        matches = re.findall(r'\((?:(\d+),"([^"]+)","([^"]+)","([^"]+)"(?:,(\d+))?)\)', resp)
        for m in matches:
            stat_code = int(m[0])
            long_name = m[1]
            short_name = m[2]
            plmn = m[3]
            act_code = int(m[4]) if m[4] else 9

            results.append({
                "status": status_map.get(stat_code, "Unknown"),
                "status_code": stat_code,
                "long_name": long_name,
                "short_name": short_name,
                "plmn": plmn,
                "act": act_map.get(act_code, f"AcT {act_code}")
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
        elif "AT+QENG=\"SERVINGCELL\"" in c:
            sc = self.state["serving_cell"]
            sig = self.state["signal"]
            return f'+QENG: "servingcell","{sc["state"]}","{sc["rat"]}","FDD",{sc["mcc"]},{sc["mnc"]},{sc["cell_id"]},{sc["pci"]},{sc["earfcn"]},{sc["band"]},0,0,{sc["tac"]},{sig["rsrp"]},{sig["rsrq"]},{sig["rssi"]},{sig["sinr"]}\r\n\r\nOK\r\n'
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
