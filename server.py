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

from serial_manager import SerialManager

app = FastAPI(title="Quectel BC660K Signal & Network Dashboard")
manager = SerialManager()

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
    baudrate: int = 9600

class SendATRequest(BaseModel):
    command: str

# --- REST Endpoints ---
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

@app.post("/api/demo")
def enable_demo():
    manager.enable_demo_mode()
    return {"status": "ok", "state": manager.state}

@app.post("/api/disconnect")
def disconnect_port():
    manager.disconnect()
    return {"status": "ok", "state": manager.state}

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
    networks = manager.scan_networks()
    return {"status": "ok", "networks": networks}

# --- SQLite History & Export Endpoints ---
@app.get("/api/history")
def get_history(limit: int = Query(200, ge=10, le=2000)):
    history = manager.db.get_history(limit=limit)
    stats = manager.db.get_stats()
    return {"history": history, "stats": stats}

@app.get("/api/history/export")
def export_csv():
    records = manager.db.get_history(limit=5000)
    if not records:
        return Response(content="No data logged yet", media_type="text/plain")

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
def clear_history():
    manager.db.clear_history()
    return {"status": "ok", "stats": manager.db.get_stats()}

# --- Shutdown Endpoint ---
@app.post("/api/shutdown")
def shutdown_server():
    """Cleanly disconnect serial port and terminate server process."""
    print("\n[SYSTEM] Exit requested via Web UI. Shutting down cleanly...")
    manager.disconnect()

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

# Signal Handlers for Ctrl+C / Ctrl+X / SIGINT / SIGTERM
def setup_signal_handlers():
    def handle_signal(sig, frame):
        print(f"\n[SYSTEM] Signal {sig} received (Ctrl+C / Terminal Interrupt). Shutting down...")
        manager.disconnect()
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except Exception as e:
        print(f"[SYSTEM] Signal handler notice: {e}")

if __name__ == "__main__":
    setup_signal_handlers()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    port_num = 8080
    url = f"http://localhost:{port_num}"
    print(f"\n=======================================================")
    print(f"Quectel BC660K Web Dashboard running at: {url}")
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
