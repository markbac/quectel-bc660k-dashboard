# Quectel BC660K Cellular & Network Signal Web Dashboard

A modern, real-time web dashboard for inspecting signal strength, serving cell metrics, neighboring cell towers, and available network operators on **Quectel BC660K-GL LTE Cat NB2 (NB-IoT)** breakout boards.

![Dashboard Preview](https://img.shields.io/badge/Quectel-BC660K--GL-blue) ![License](https://img.shields.io/badge/License-MIT-green) ![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688)

---

## 🌟 Key Features

- 📶 **Real-Time Signal Quality Telemetry**: Monitors **RSRP** (dBm), **RSRQ** (dB), **RSSI** (dBm), **SINR** (dB), and **CSQ** (0-31 scale) with live color-coded quality badges.
- 📈 **Live Trend Charts**: Rolling history chart for RSRP and RSRQ signal power over time.
- 🗼 **Serving Cell Details** (`AT+QENG="servingcell"`): Displays carrier operator, PLMN ID (MCC-MNC), Cell ID (hex/dec), TAC, PCI, EARFCN, and Frequency Band.
- 📡 **Neighboring Cell Towers** (`AT+QENG="neighbourcell"`): Lists surrounding cell towers with PCI, EARFCN, RSRP, and RSRQ.
- 🔍 **Cellular Network Scanner** (`AT+COPS=?`): Scans the cellular spectrum to discover all visible carrier networks and their registration status.
- 💻 **Built-in AT Command Console**: Execute manual AT commands with quick-action presets (`AT`, `ATI`, `AT+CSQ`, `AT+QENG`, `AT+COPS?`, `AT+CEREG?`).
- 🧪 **Hardware Simulator (Demo Mode)**: Test and demonstrate the UI instantly even when no physical hardware is plugged in.
- ⚡ **Asynchronous WebSocket Backend**: Ultra-responsive FastAPI server streaming serial telemetry live to the UI without polling overhead.

---

## 🛠️ Hardware Requirements

- **Quectel BC660K-GL** module / TE-B breakout board (`BC660K-GL-TE-B`).
- USB-to-UART Adapter or USB serial cable connected to module TX/RX/GND.
- Active NB-IoT SIM card (optional for signal scan / network discovery).

---

## 🚀 Quick Start Guide

### 1. Prerequisites
Ensure Python 3.9+ is installed.

### 2. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/markbac/quectel-bc660k-dashboard.git
cd quectel-bc660k-dashboard
pip install -r requirements.txt
```

### 3. Running the Server
Launch the server:
```bash
python server.py
```
Open **[http://localhost:8080](http://localhost:8080)** in your web browser.

---

## 🔌 Serial Connection & Usage

1. Plug in your Quectel BC660K breakout board via USB/UART.
2. Open the dashboard at `http://localhost:8080`.
3. Select your serial **COM Port** (e.g., `COM3`, `COM4` or `/dev/ttyUSB0`).
4. Set the Baud Rate (default: `9600` baud).
5. Click **Connect**.
6. *No board available?* Click **Demo Mode** to run the hardware simulator!

---

## 📋 AT Command Reference

The dashboard automatically parses the following Quectel BC660K AT commands:

| Command | Purpose | Output Parsed |
| :--- | :--- | :--- |
| `AT+CSQ` | Signal Quality | CSQ (0-31), RSSI (dBm), Bit Error Rate |
| `AT+CESQ` | Extended Signal Quality | RSRP, RSRQ, RXLEV |
| `AT+QENG="servingcell"` | Serving Cell Parameters | State, RAT, Duplex, MCC, MNC, Cell ID, PCI, EARFCN, Band, TAC, RSRP, RSRQ, RSSI, SINR |
| `AT+QENG="neighbourcell"` | Neighboring Cell Survey | Neighbor PCI, EARFCN, RSRP, RSRQ |
| `AT+COPS=?` | Carrier Spectrum Scan | Visible PLMNs, Operator names, Access Technology |
| `AT+COPS?` | Current Carrier | Registered Network Operator |
| `AT+CEREG?` | EPS Registration | Network attachment state, Location info |

---

## 🏗️ Project Architecture

```
quectel-bc660k-dashboard/
├── server.py              # FastAPI server with WebSocket & REST endpoints
├── serial_manager.py      # PySerial engine, Quectel AT parser & Demo mode simulator
├── requirements.txt       # Dependencies
├── static/
│   ├── index.html         # Single-page application UI
│   ├── css/
│   │   └── style.css      # Dark mode glassmorphic styling
│   └── js/
│       └── app.js         # WebSocket client, Chart.js trends & AT console
└── README.md              # Project documentation
```

---

## 📄 License

Distributed under the [MIT License](LICENSE).
