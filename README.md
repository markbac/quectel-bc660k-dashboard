# Quectel BC660K Cellular & Network Signal Web Dashboard

A modern, real-time web dashboard for inspecting signal strength, serving cell metrics, neighboring cell towers, and available network operators on **Quectel BC660K-GL LTE Cat NB2 (NB-IoT)** breakout boards.

![Dashboard Preview](https://img.shields.io/badge/Quectel-BC660K--GL-blue) ![License](https://img.shields.io/badge/License-MIT-green) ![Py--LogKit](https://img.shields.io/badge/Py--LogKit-Integrated-purple) ![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688)

---

## 🌟 Key Features

- 📶 **Real-Time Signal Quality Telemetry**: Monitors **RSRP** (dBm), **RSRQ** (dB), **RSSI** (dBm), **SINR** (dB), and **CSQ** (0-31 scale) with live color-coded quality badges.
- ⚡ **Py-LogKit Integration**: Features structured, colorized, timestamped, and file-backed logging powered by [`markbac/py-logkit`](https://github.com/markbac/py-logkit).
- 🔒 **Serial Port Lock Warning & Auto-Reclaim**: Detects if a COM port is locked by another process, emits warnings, and reclaims handles automatically.
- 📡 **Automatic Initial & Scheduled Network Scan (`AT+COPS=?`)**: Runs a full cellular spectrum scan by default on connection and periodically in an asynchronous non-blocking thread.
- ⚙️ **Configurable Polling Frequencies**: Web UI controls for Signal Poll Interval (`1s`, `2s`, `3s`, `5s`, `10s`) and Spectrum Scan Frequency (`Off`, `30s`, `60s`, `120s`, `300s`).
- 🗄️ **SQLite Data Logging & CSV Export**: Automatic SQLite telemetry persistence (`telemetry.db`), historical analytics summary, and one-click CSV export.
- 🧹 **Fresh History Reset**: Instantly clear historical database records to start telemetry logging fresh.
- 💻 **Built-in AT Command Console**: Execute manual AT commands with quick-action presets (`AT`, `ATI`, `AT+CSQ`, `AT+QCCID`, `AT+CIMI`, `AT+CBC`, `AT+QENG`, `AT+COPS?`, `AT+CEREG?`).
- 🛑 **Graceful Shutdown & Signal Handling**: Supports web Exit button shutdown and terminal `Ctrl+C` / `Ctrl+X` clean resource releases.

---

## 🛠️ Hardware Requirements

- **Quectel BC660K-GL** module / TE-B breakout board (`BC660K-GL-TE-B`).
- Default Baud Rate: **`115200`** baud (or `9600` baud).
- USB-to-UART Adapter (FTDI FT4232H quad serial interface).

---

## 🚀 Quick Start Guide

### 1. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/markbac/quectel-bc660k-dashboard.git
cd quectel-bc660k-dashboard
pip install -r requirements.txt
```

### 2. Running the Server
Launch the server (connects to `COM3` @ `115200` baud by default):
```bash
python server.py --port COM3 --baud 115200
```
Open **[http://localhost:8080](http://localhost:8080)** in your web browser.

---

## 🧪 Running the Tests

```bash
pip install -r requirements-dev.txt
python -m pytest      # back end
npm install && npm test   # front end (jsdom)
```

---

## 📄 License

Distributed under the [MIT License](LICENSE).
