import os
import sys
import time
import signal
import asyncio
import json
import csv
import io
import argparse
import threading
import webbrowser
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel
import uvicorn

import instance
from db_manager import SchemaTooNewError
from security import LocalOnlyMiddleware
from serial_manager import SerialManager
from pylogkit import setup_logging

# Parse Command Line Arguments
parser = argparse.ArgumentParser(description="Quectel BC660K Signal & Network Web Dashboard")
parser.add_argument("--demo", "-d", action="store_true", help="Start dashboard in hardware simulator demo mode")
parser.add_argument("--port", "-p", type=str, default="COM3", help="Initial COM port to connect on startup (default: COM3)")
parser.add_argument("--baud", "-b", type=int, default=115200, help="Initial baud rate (default: 115200)")
parser.add_argument("--db-path", type=str, default=None, help="SQLite database file (default: per-user data directory, or $QUECTEL_DASHBOARD_DB)")
parser.add_argument("--no-file-log", action="store_true", help="Disable writing serial logs to disk file")
args, _ = parser.parse_known_args()

app = FastAPI(title="Quectel BC660K Signal & Network Dashboard")
app.add_middleware(LocalOnlyMiddleware)
try:
    manager = SerialManager(file_logging_enabled=not args.no_file_log, db_path=args.db_path)
except SchemaTooNewError as exc:
    sys.exit(f"ERROR: {exc}")

# Store active WebSocket connections
active_connections: List[WebSocket] = []
loop = None

def broadcast(event_type: str, data: Any):
    """Callback from SerialManager to broadcast updates over WebSockets."""
    if not active_connections:
        return
    message = json.dumps({"type": event_type, "data": data})
    if loop and loop.is_running():
        for connection in list(active_connections):
            asyncio.run_coroutine_threadsafe(connection.send_text(message), loop)

manager.register_callback(broadcast)

# --- Pydantic Models ---
class ConnectRequest(BaseModel):
    port: str
    baudrate: int = 115200

class SendATRequest(BaseModel):
    command: str

class FileLogToggleRequest(BaseModel):
    enabled: bool

class SettingsRequest(BaseModel):
    telemetry_interval: Optional[int] = None
    cops_scan_interval: Optional[int] = None

class APNRequest(BaseModel):
    apn: str
    pdp_type: str = "IP"
    cid: int = 1

class PSMRequest(BaseModel):
    enabled: bool
    t3412: Optional[str] = "10100101"
    t3324: Optional[str] = "00100100"

class EDRXRequest(BaseModel):
    enabled: bool
    edrx_val: Optional[str] = "0010"

class PingRequest(BaseModel):
    host: str = "8.8.8.8"
    count: Optional[int] = 4

class DNSRequest(BaseModel):
    domain: str = "leshan.eclipseprojects.io"

# --- REST Endpoints ---
@app.post("/api/psm")
def config_psm(req: PSMRequest):
    res = manager.set_psm_config(req.enabled, req.t3412 or "10100101", req.t3324 or "00100100")
    if not manager.is_ok(res):
        raise HTTPException(status_code=502, detail=f"Modem did not accept AT+CPSMS: {res.strip()}")
    return {"status": "ok", "response": res, "state": manager.state}

@app.post("/api/edrx")
def config_edrx(req: EDRXRequest):
    res = manager.set_edrx_config(req.enabled, req.edrx_val or "0010")
    return {"status": "ok", "response": res, "state": manager.state}

@app.post("/api/ping")
def run_ping(req: PingRequest):
    res = manager.run_ping_benchmark(req.host or "8.8.8.8", req.count or 4)
    return {"status": "ok", "result": res, "state": manager.state}

@app.post("/api/dns")
def run_dns(req: DNSRequest):
    res = manager.run_dns_query(req.domain or "leshan.eclipseprojects.io")
    return {"status": "ok", "result": res, "state": manager.state}
@app.get("/api/ports")
def get_ports():
    return {"ports": manager.get_ports()}

@app.get("/api/state")
def get_state():
    return manager.state

@app.post("/api/connect")
def connect_port(req: ConnectRequest):
    success = manager.connect(req.port, req.baudrate)
    if not success:
        raise HTTPException(status_code=400, detail=f"Could not connect to {req.port}")
    return {"status": "ok", "state": manager.state}

@app.post("/api/disconnect")
def disconnect_port():
    manager.disconnect()
    return {"status": "ok", "state": manager.state}

@app.post("/api/settings")
def update_settings(req: SettingsRequest):
    manager.update_settings(req.telemetry_interval, req.cops_scan_interval)
    return {"status": "ok", "state": manager.state}

@app.post("/api/apn")
def configure_apn(req: APNRequest):
    if not manager.is_connected:
        raise HTTPException(status_code=400, detail="Serial port not connected")
    res = manager.set_apn(req.apn, req.pdp_type, req.cid)
    return {"status": "ok", "response": res, "apn_info": manager.state["apn_info"]}

@app.post("/api/file_logging")
def toggle_file_logging(req: FileLogToggleRequest):
    manager.set_file_logging(req.enabled)
    return {"status": "ok", "file_logging_enabled": manager.file_logging_enabled}

@app.post("/api/send_at")
def send_at(req: SendATRequest):
    if not manager.is_connected:
        raise HTTPException(status_code=400, detail="Serial port not connected")
    resp = manager.send_at_command(req.command)
    return {"command": req.command, "response": resp}

@app.post("/api/scan")
def scan_networks():
    if not manager.is_connected:
        raise HTTPException(status_code=400, detail="Serial port not connected")
    manager.trigger_async_cops_scan()
    return {"status": "ok", "message": "Async network scan triggered"}

# --- SQLite History & Export Endpoints ---
# History is scoped to the ICCID of the SIM in the connected board.
@app.get("/api/history")
def get_history(limit: int = Query(200, ge=10, le=2000)):
    iccid = manager.current_iccid
    return {
        "history": manager.db.get_history(iccid, limit=limit),
        "stats": manager.db.get_stats(iccid),
        "awaiting_identity": iccid is None,
    }

@app.get("/api/sessions")
def get_sessions():
    """Recording sessions of the connected SIM (empty until its ICCID is known)."""
    return {"sessions": manager.db.get_sessions(manager.current_iccid)}

@app.get("/api/history/export")
def export_csv():
    records = manager.db.get_history(manager.current_iccid, limit=5000)
    if not records:
        return Response(content="No data logged yet for the connected SIM", media_type="text/plain")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=records[0].keys())
    writer.writeheader()
    writer.writerows(records)

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=quectel_signal_history.csv"}
    )

@app.post("/api/history/clear")
def clear_history(all_sims: bool = Query(False, alias="all")):
    """Delete the connected SIM's history, or every SIM's with ``?all=true``."""
    deleted = manager.db.clear_history(manager.current_iccid, everything=all_sims)
    return {"status": "ok", "deleted": deleted, "stats": manager.db.get_stats(manager.current_iccid)}

# --- Shutdown Endpoint ---
@app.post("/api/shutdown")
def shutdown_server():
    print("\n[SYSTEM] Exit requested via Web UI. Shutting down cleanly...")
    manager.disconnect()
    instance.remove_pid_file()

    def delayed_exit():
        time.sleep(0.5)
        print("[SYSTEM] Goodbye!")
        os._exit(0)

    threading.Thread(target=delayed_exit, daemon=True).start()
    return {"status": "ok", "message": "Server shutting down cleanly..."}

# --- WebSocket Endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    await websocket.send_text(json.dumps({"type": "state", "data": manager.state}))
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("action") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        active_connections.remove(websocket)
    except Exception:
        if websocket in active_connections:
            active_connections.remove(websocket)

# Static Files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Dashboard HTML loading...</h1>")

def setup_signal_handlers():
    def handle_signal(sig, frame):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print(f"\n[SYSTEM] Signal {sig} received (Ctrl+C / Terminal Interrupt). Goodbye!")
        try:
            manager.disconnect()
        except Exception:
            pass
        instance.remove_pid_file()
        os._exit(0)

    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except Exception as e:
        print(f"[SYSTEM] Signal handler notice: {e}")

if __name__ == "__main__":
    setup_signal_handlers()
    instance.write_pid_file()

    if args.demo:
        print("[STARTUP] Demo mode CLI flag '--demo' enabled. Starting simulator...")
        manager.enable_demo_mode()
    elif args.port:
        print(f"[STARTUP] Connecting to serial port {args.port} @ {args.baud} baud...")
        manager.connect(args.port, args.baud)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    port_num = 8080
    url = f"http://localhost:{port_num}"
    print(f"\n=======================================================")
    print(f"Quectel BC660K Web Dashboard v{manager.VERSION} running at: {url}")
    print(f"Baud Rate: {args.baud}")
    print(f"Mode: {'SIMULATED DEMO (--demo)' if args.demo else 'REAL HARDWARE'}")
    print(f"Database: {manager.db.db_path}")
    print(f"Py-LogKit File Logging: {'ENABLED (dashboard_serial.log)' if not args.no_file_log else 'DISABLED'}")
    print(f"Press Ctrl+C in terminal or click Exit in Web UI to stop")
    print(f"=======================================================\n")

    try:
        webbrowser.open(url)
    except Exception:
        pass

    config = uvicorn.Config(app=app, host="127.0.0.1", port=port_num, loop="asyncio")
    server = uvicorn.Server(config)
    try:
        loop.run_until_complete(server.serve())
    except (KeyboardInterrupt, SystemExit):
        print("\n[SYSTEM] Server process terminated.")
        manager.disconnect()
