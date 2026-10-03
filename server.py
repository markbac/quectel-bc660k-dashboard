import os
import sys
import time
import signal
import asyncio
import json
import csv
import io
import threading
import webbrowser
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel
import uvicorn

import cli
import instance
from db_manager import SchemaTooNewError
from security import LocalOnlyMiddleware
from serial_manager import SerialManager
from modem_replay import TranscriptModem
from port_detect import detect_at_port
from transcript import TranscriptRecorder, load_transcript

args = cli.parse_args()

app = FastAPI(title="Quectel BC660K Signal & Network Dashboard")
app.add_middleware(LocalOnlyMiddleware, port=args.http_port)
try:
    manager = SerialManager(file_logging_enabled=not args.no_file_log, db_path=args.db_path, retention_days=args.retention_days)
except SchemaTooNewError as exc:
    sys.exit(f"ERROR: {exc}")

# Store active WebSocket connections
active_connections: List[WebSocket] = []
loop = None

def public_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """State as sent to browsers. Log lines travel as separate ``log`` events."""
    return {key: value for key, value in state.items() if key != "logs"}

def broadcast(event_type: str, data: Any):
    """Callback from SerialManager to broadcast updates over WebSockets."""
    if not active_connections:
        return
    if event_type == "state":
        data = public_state(data)
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
    history_interval: Optional[int] = None

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
@app.post("/api/detect")
def detect_port():
    """Probe the system's serial ports and report the one with an AT modem."""
    if manager.is_connected and manager.port:
        return {"port": manager.port, "baudrate": manager.baudrate}
    found = detect_at_port()
    if found is None:
        raise HTTPException(status_code=404, detail="No serial port answered AT")
    return {"port": found[0], "baudrate": found[1]}

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
    manager.update_settings(req.telemetry_interval, req.cops_scan_interval, req.history_interval)
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

WINDOW_SECONDS = {"1h": 3600, "24h": 86400, "7d": 7 * 86400}


@app.get("/api/history/series")
def get_history_series(
    window: str = Query("1h", pattern="^(1h|24h|7d|all|session|custom)$"),
    max_points: int = Query(300, ge=10, le=2000),
    start: Optional[float] = Query(None, description="custom window start, unix seconds"),
    end: Optional[float] = Query(None, description="custom window end, unix seconds"),
):
    """Downsampled RSRP/RSRQ/SINR series of the connected SIM for charting.

    ``window`` is ``1h``, ``24h``, ``7d``, ``all``, ``session`` (the current
    recording session) or ``custom`` (between ``start`` and ``end``, unix
    seconds, either optional). The series is averaged into at most
    ``max_points``.
    """
    iccid = manager.current_iccid
    session_id = None
    if window == "custom":
        if start is not None and end is not None and start > end:
            raise HTTPException(status_code=422, detail="start must not be after end")
    elif window in WINDOW_SECONDS:
        start = time.time() - WINDOW_SECONDS[window]
        end = None
    else:
        start = end = None
    if window == "session":
        session_id = manager.session_id
        if session_id is None:
            return {"series": [], "window": window, "awaiting_identity": iccid is None}
    return {
        "series": manager.db.get_series(
            iccid, start_time=start, end_time=end, session_id=session_id, max_points=max_points),
        "window": window,
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
    await websocket.send_text(json.dumps({"type": "state", "data": public_state(manager.state)}))
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

def main() -> None:
    """Start the dashboard server (console-script entry point)."""
    global loop
    setup_signal_handlers()
    instance.write_pid_file()
    if args.record:
        manager.recorder = TranscriptRecorder(args.record)
        print(f"[STARTUP] Recording AT exchanges to {args.record} (identifiers redacted).")

    if args.demo:
        print("[STARTUP] Demo mode CLI flag '--demo' enabled. Starting simulator...")
        manager.enable_demo_mode()
    elif args.replay:
        modem = TranscriptModem(load_transcript(args.replay))
        modem.start().close()
        print(f"[STARTUP] Replaying {args.replay} on {modem.slave_name}...")
        manager.connect(modem.slave_name, args.baud)
    elif args.port == "auto":
        print("[STARTUP] Probing serial ports for an AT modem...")
        found = detect_at_port(bauds=(args.baud,))
        if found:
            print(f"[STARTUP] Found modem on {found[0]} @ {found[1]} baud.")
            manager.connect(*found)
        else:
            print("[STARTUP] No port answered AT; choose one in the web UI.")
    elif args.port:
        print(f"[STARTUP] Connecting to serial port {args.port} @ {args.baud} baud...")
        manager.connect(args.port, args.baud)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    port_num = args.http_port
    url = cli.server_url(args.host, port_num)
    print("\n=======================================================")
    print(f"Quectel BC660K Web Dashboard v{manager.VERSION} running at: {url}")
    print(f"Baud Rate: {args.baud}")
    print(f"Mode: {'SIMULATED DEMO (--demo)' if args.demo else 'REAL HARDWARE'}")
    print(f"Database: {manager.db.db_path}")
    print(f"Py-LogKit File Logging: {'ENABLED (dashboard_serial.log)' if not args.no_file_log else 'DISABLED'}")
    print("Press Ctrl+C in terminal or click Exit in Web UI to stop")
    print("=======================================================\n")

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    config = uvicorn.Config(app=app, host=args.host, port=port_num, loop="asyncio")
    server = uvicorn.Server(config)
    try:
        loop.run_until_complete(server.serve())
    except (KeyboardInterrupt, SystemExit):
        print("\n[SYSTEM] Server process terminated.")
        manager.disconnect()


if __name__ == "__main__":
    main()
