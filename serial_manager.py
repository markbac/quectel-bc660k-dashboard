import time
import re
import threading
import random
import logging
from typing import Dict, Any, List, Optional
import serial
import serial.tools.list_ports

logger = logging.getLogger("SerialManager")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class SerialManager:
    def __init__(self):
        self.ser: Optional[serial.Serial] = None
        self.port: Optional[str] = None
        self.baudrate: int = 9600
        self.is_connected: bool = False
        self.is_demo: bool = False
        self.lock = threading.Lock()
        self.poll_thread: Optional[threading.Thread] = None
        self.running: bool = False
        self.callbacks = []

        # Current state cache
        self.state = {
            "connected": False,
            "port": None,
            "baudrate": 9600,
            "mode": "DISCONNECTED",  # "REAL", "DEMO", "DISCONNECTED"
            "signal": {
                "rssi": -85,
                "csq": 14,
                "rsrp": -98,
                "rsrq": -10,
                "sinr": 12,
                "ber": 0,
                "quality_label": "Good"
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
            "neighbour_cells": [
                {"pci": 142, "earfcn": 6300, "rsrp": -104, "rsrq": -14},
                {"pci": 289, "earfcn": 6300, "rsrp": -112, "rsrq": -16},
                {"pci": 88, "earfcn": 6150, "rsrp": -118, "rsrq": -18}
            ],
            "networks_scan": [],
            "is_scanning": False,
            "last_update": time.time(),
            "logs": []
        }

    def register_callback(self, callback):
        """Register callback function for state updates or log broadcasts."""
        self.callbacks.append(callback)

    def _notify(self, event_type: str, data: Any):
        for cb in self.callbacks:
            try:
                cb(event_type, data)
            except Exception as e:
                logger.error(f"Error in callback: {e}")

    def log(self, text: str, direction: str = "INFO"):
        entry = {
            "timestamp": time.strftime("%H:%M:%S"),
            "direction": direction,  # "TX", "RX", "INFO", "ERROR"
            "text": text
        }
        self.state["logs"].append(entry)
        if len(self.state["logs"]) > 200:
            self.state["logs"].pop(0)
        self._notify("log", entry)

    @staticmethod
    def get_ports() -> List[Dict[str, str]]:
        """List all system COM ports."""
        ports = serial.tools.list_ports.comports()
        result = []
        for p in ports:
            result.append({
                "device": p.device,
                "description": p.description,
                "hardware_id": p.hwid
            })
        return result

    def connect(self, port: str, baudrate: int = 9600) -> bool:
        self.disconnect()
        with self.lock:
            try:
                self.ser = serial.Serial(port, baudrate, timeout=1.5)
                self.port = port
                self.baudrate = baudrate
                self.is_connected = True
                self.is_demo = False
                self.state["connected"] = True
                self.state["port"] = port
                self.state["baudrate"] = baudrate
                self.state["mode"] = "REAL"
                self.running = True
                self.log(f"Connected to {port} @ {baudrate} baud", "INFO")
                
                # Test connection
                resp = self._send_at_cmd_raw("AT\r\n")
                if "OK" in resp:
                    self.log("Module responded to AT command successfully", "INFO")
                
                # Query basic info
                self._poll_hardware_info()

                # Start background polling
                self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
                self.poll_thread.start()
                self._notify("state", self.state)
                return True
            except Exception as e:
                self.log(f"Failed to open port {port}: {e}", "ERROR")
                self.disconnect()
                return False

    def enable_demo_mode(self):
        """Enable simulated demo mode for testing UI without physical board."""
        self.disconnect()
        with self.lock:
            self.is_connected = True
            self.is_demo = True
            self.state["connected"] = True
            self.state["port"] = "DEMO-PORT (Simulated Quectel BC660K)"
            self.state["baudrate"] = 9600
            self.state["mode"] = "DEMO"
            self.running = True
            self.log("Started Demo Mode (Simulating Quectel BC660K-GL)", "INFO")

            self.poll_thread = threading.Thread(target=self._demo_loop, daemon=True)
            self.poll_thread.start()
            self._notify("state", self.state)
            return True

    def disconnect(self):
        self.running = False
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=1.0)
        
        with self.lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = None
            self.is_connected = False
            self.is_demo = False
            self.state["connected"] = False
            self.state["mode"] = "DISCONNECTED"
            self.log("Disconnected from serial port", "INFO")
            self._notify("state", self.state)

    def _send_at_cmd_raw(self, cmd: str) -> str:
        if not self.ser or not self.ser.is_open:
            return "ERROR: Port not open"
        
        if not cmd.endswith("\r\n"):
            cmd_str = cmd + "\r\n"
        else:
            cmd_str = cmd
            
        self.log(cmd.strip(), "TX")
        try:
            self.ser.write(cmd_str.encode("utf-8", errors="ignore"))
            time.sleep(0.15)
            response = ""
            start = time.time()
            while time.time() - start < 2.0:
                if self.ser.in_waiting > 0:
                    chunk = self.ser.read(self.ser.in_waiting).decode("utf-8", errors="ignore")
                    response += chunk
                    if "OK" in response or "ERROR" in response:
                        break
                time.sleep(0.05)
            self.log(response.strip(), "RX")
            return response
        except Exception as e:
            self.log(f"TX/RX Error: {e}", "ERROR")
            return f"ERROR: {e}"

    def send_at_command(self, cmd: str) -> str:
        """User-triggered manual AT command."""
        if self.is_demo:
            self.log(cmd.strip(), "TX")
            resp = self._simulated_at_response(cmd.strip())
            self.log(resp.strip(), "RX")
            return resp
        
        with self.lock:
            return self._send_at_cmd_raw(cmd)

    def scan_networks(self) -> List[Dict[str, Any]]:
        """Run network scan (AT+COPS=?)."""
        self.state["is_scanning"] = True
        self._notify("state", self.state)
        self.log("Starting network scan (AT+COPS=?... this may take up to 30s)", "INFO")

        if self.is_demo:
            time.sleep(3.0)  # Simulate scan delay
            scanned = [
                {"status": "Current", "status_code": 2, "long_name": "Vodafone UK", "short_name": "voda UK", "plmn": "23415", "act": "LTE Cat NB2"},
                {"status": "Available", "status_code": 1, "long_name": "EE", "short_name": "EE", "plmn": "23430", "act": "LTE Cat NB2"},
                {"status": "Available", "status_code": 1, "long_name": "O2 - UK", "short_name": "O2", "plmn": "23410", "act": "LTE Cat NB2"},
                {"status": "Forbidden", "status_code": 3, "long_name": "Three UK", "short_name": "3 UK", "plmn": "23420", "act": "LTE Cat NB2"}
            ]
            self.state["networks_scan"] = scanned
            self.state["is_scanning"] = False
            self.log(f"Scan complete. Found {len(scanned)} networks.", "INFO")
            self._notify("state", self.state)
            return scanned

        with self.lock:
            resp = self._send_at_cmd_raw("AT+COPS=?")
            scanned = self._parse_cops_scan(resp)
            self.state["networks_scan"] = scanned
            self.state["is_scanning"] = False
            self.log(f"Scan complete. Found {len(scanned)} networks.", "INFO")
            self._notify("state", self.state)
            return scanned

    def _poll_hardware_info(self):
        """Query ATI, AT+GMR, etc."""
        self._send_at_cmd_raw("ATI")
        self._send_at_cmd_raw("AT+GMR")
        self._send_at_cmd_raw("AT+CEREG=2")  # Enable location info in CEREG

    def _poll_loop(self):
        """Background thread to poll signal and cell info periodically."""
        while self.running and self.is_connected and not self.is_demo:
            try:
                with self.lock:
                    csq_resp = self._send_at_cmd_raw("AT+CSQ")
                    self._parse_csq(csq_resp)

                    qeng_resp = self._send_at_cmd_raw('AT+QENG="servingcell"')
                    self._parse_qeng_serving(qeng_resp)

                    qeng_n_resp = self._send_at_cmd_raw('AT+QENG="neighbourcell"')
                    self._parse_qeng_neighbour(qeng_n_resp)

                    cops_resp = self._send_at_cmd_raw("AT+COPS?")
                    self._parse_cops_query(cops_resp)

                self.state["last_update"] = time.time()
                self._notify("state", self.state)
            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
            time.sleep(3.0)

    def _demo_loop(self):
        """Simulate realistic signal noise, small handovers, and metrics."""
        base_rsrp = -95
        base_rsrq = -11
        base_sinr = 14

        while self.running and self.is_demo:
            # Add slight realistic noise
            rsrp_noise = random.randint(-4, 4)
            rsrq_noise = random.randint(-2, 2)
            sinr_noise = random.randint(-3, 3)

            current_rsrp = max(-130, min(-55, base_rsrp + rsrp_noise))
            current_rsrq = max(-20, min(-3, base_rsrq + rsrq_noise))
            current_sinr = max(-10, min(30, base_sinr + sinr_noise))

            # Calculate CSQ based on RSRP
            # RSRP -113 dBm -> CSQ 0, RSRP -51 dBm -> CSQ 31
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

            # Occasionally update neighbor signal slightly
            self.state["neighbour_cells"] = [
                {"pci": 142, "earfcn": 6300, "rsrp": current_rsrp - random.randint(6, 12), "rsrq": current_rsrq - random.randint(2, 4)},
                {"pci": 289, "earfcn": 6300, "rsrp": current_rsrp - random.randint(14, 20), "rsrq": current_rsrq - random.randint(4, 6)},
                {"pci": 88, "earfcn": 6150, "rsrp": current_rsrp - random.randint(18, 26), "rsrq": current_rsrq - random.randint(5, 8)}
            ]

            self.state["last_update"] = time.time()
            self._notify("state", self.state)
            time.sleep(2.0)

    # --- AT Response Parsers ---

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

    def _parse_qeng_serving(self, resp: str):
        """
        Parses Quectel BC660K AT+QENG="servingcell"
        Example output:
        +QENG: "servingcell","NOCONN","NB-IoT","FDD",234,15,1D2F401,320,6300,8,0,0,5F4E,-102,-11,-91,12
        """
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

    def _parse_qeng_neighbour(self, resp: str):
        """
        Parses Quectel BC660K AT+QENG="neighbourcell"
        Example output:
        +QENG: "neighbourcell","NB-IoT",6300,142,-108,-14
        +QENG: "neighbourcell","NB-IoT",6300,289,-114,-16
        """
        neighbours = []
        matches = re.findall(r'\+QENG:\s*"neighbourcell","([^"]+)",(\d+),(\d+),(-?\d+),(-?\d+)', resp)
        for m in matches:
            rat, earfcn, pci, rsrp, rsrq = m
            neighbours.append({
                "pci": int(pci),
                "earfcn": int(earfcn),
                "rsrp": int(rsrp),
                "rsrq": int(rsrq)
            })
        if neighbours:
            self.state["neighbour_cells"] = neighbours

    def _parse_cops_query(self, resp: str):
        match = re.search(r'\+COPS:\s*\d+,\d+,"([^"]+)"', resp)
        if match:
            self.state["serving_cell"]["operator"] = match.group(1)

    def _parse_cops_scan(self, resp: str) -> List[Dict[str, Any]]:
        """
        Parse AT+COPS=? response.
        Example: +COPS: (2,"Vodafone UK","voda UK","23415",9),(1,"EE","EE","23430",9),...
        """
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
            return "Quectel\r\nBC660K-GL\r\nRevision: BC660KGLAAR01A03\r\n\r\nOK\r\n"
        elif c == "AT+GMR":
            return "BC660KGLAAR01A03_01.001.01.001\r\n\r\nOK\r\n"
        elif c == "AT+CSQ":
            s = self.state["signal"]
            return f"+CSQ: {s['csq']},0\r\n\r\nOK\r\n"
        elif "AT+QENG=\"SERVINGCELL\"" in c:
            sc = self.state["serving_cell"]
            sig = self.state["signal"]
            return f'+QENG: "servingcell","{sc["state"]}","{sc["rat"]}","FDD",{sc["mcc"]},{sc["mnc"]},{sc["cell_id"]},{sc["pci"]},{sc["earfcn"]},{sc["band"]},0,0,{sc["tac"]},{sig["rsrp"]},{sig["rsrq"]},{sig["rssi"]},{sig["sinr"]}\r\n\r\nOK\r\n'
        elif "AT+QENG=\"NEIGHBOURCELL\"" in c:
            res = ""
            for nc in self.state["neighbour_cells"]:
                res += f'+QENG: "neighbourcell","NB-IoT",{nc["earfcn"]},{nc["pci"]},{nc["rsrp"]},{nc["rsrq"]}\r\n'
            return res + "\r\nOK\r\n"
        elif c == "AT+COPS?":
            sc = self.state["serving_cell"]
            return f'+COPS: 0,0,"{sc["operator"]}",9\r\n\r\nOK\r\n'
        elif c == "AT+COPS=?":
            return '+COPS: (2,"Vodafone UK","voda UK","23415",9),(1,"EE","EE","23430",9),(1,"O2 - UK","O2","23410",9),(3,"Three UK","3 UK","23420",9)\r\n\r\nOK\r\n'
        elif c == "AT+CEREG?":
            sc = self.state["serving_cell"]
            return f'+CEREG: 2,1,"{sc["tac"]}","{sc["cell_id"]}",9\r\n\r\nOK\r\n'
        else:
            return "OK\r\n"
