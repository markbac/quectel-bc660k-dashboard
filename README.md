# Quectel BC660K Cellular & Network Signal Web Dashboard

A modern, real-time web dashboard for inspecting signal strength, serving cell metrics, neighboring cell towers, and available network operators on **Quectel BC660K-GL LTE Cat NB2 (NB-IoT)** breakout boards.

![Dashboard Preview](https://img.shields.io/badge/Quectel-BC660K--GL-blue) ![License](https://img.shields.io/badge/License-MIT-green) ![Py--LogKit](https://img.shields.io/badge/Py--LogKit-Integrated-purple) ![FastAPI](https://img.shields.io/badge/FastAPI-%E2%89%A50.100-009688)

---

## 🌟 Key Features

- 📶 **Real-Time Signal Quality Telemetry**: Monitors **RSRP** (dBm), **RSRQ** (dB), **RSSI** (dBm), **SINR** (dB), and **CSQ** (0-31 scale) with live color-coded quality badges.
- ⚡ **Py-LogKit Integration**: Features structured, colorized, timestamped, and file-backed logging powered by [`markbac/py-logkit`](https://github.com/markbac/py-logkit), installed from GitHub by `pip install -r requirements.txt`. Server start-up, shutdown and uvicorn access logs use the same handlers. Needs Python 3.10 or later.
- 🔒 **Serial Port Lock Warning & Auto-Reclaim**: Detects if a COM port is locked by another process, emits warnings, and reclaims handles automatically.
- 🏷️ **Operator Names**: the module reports its network as a numeric PLMN such as `23415`. `plmn.py` maps the codes it knows (UK, Ireland, Germany, France, the Netherlands, Finland, Sweden) to names, so Vodafone UK appears only when the module is on Vodafone UK's network. Any other code shows as `PLMN <code>`, and names the network reports itself are kept. To add a network, add its code to `OPERATORS` in `plmn.py`.
- 🏆 **Network Survey**: the Network Survey card deregisters, scans, then registers on each network that is not forbidden in turn, waits for it to attach (up to 2 minutes), averages three readings of RSRP, RSRQ and SINR, and deregisters again. Networks are ranked by RSRP, then SINR, then RSRQ. At the end it connects to the best one, or with the box unticked puts back your original selection. Denied or silent networks are listed but not ranked. The module's sleep clock is turned off for the run and restored, and your original selection is restored if the survey fails or you press Stop (Stop takes effect after the network being tried, not during the scan). Expect 10 to 20 minutes with no connection. It is based on the scan and registration behaviour seen on a BC660K-GL, and a full survey has not yet been run on hardware.
- 🔌 **Register and Deregister**: buttons on the Available Carrier Networks card send `AT+COPS=2` (leave the network), `AT+COPS=0` (automatic) or `AT+COPS=1,2,"<plmn>",<act>` (the Register button on a scanned network). Deregistering takes the module off the network until you register again. It is refused while a scan is running.
- 📡 **Scheduled Network Scan (`AT+COPS=?`)**: Runs a full cellular spectrum scan in an asynchronous non-blocking thread, at the interval chosen in the UI. The default is `Off` because a scan can occupy the modem for several minutes (a real BC660K-GL took about 5 minutes to answer one while deregistered and gave no answer at all while registered, so the dashboard waits up to 10 minutes and does not report the module as unresponsive meanwhile); choosing an interval starts the first scan immediately, and the Scan button starts one on demand.
- ⚙️ **Configurable Polling Frequencies**: Web UI controls for Signal Poll Interval (`1s`, `2s`, `3s`, `5s`, `10s`) and Spectrum Scan Frequency (`Off`, `30s`, `60s`, `120s`, `300s`).
- 🗄️ **SQLite Data Logging & CSV Export**: A row is written every 5 seconds by default; the **Log Every** control sets 1s, 5s, 30s or 60s, independent of the poll interval. Automatic SQLite telemetry persistence (created on first start in your per-user data directory, never committed), historical analytics summary, and one-click CSV export.
- 📈 **History Chart**: the trend chart shows the live trace or a stored window (last hour, 24 hours, 7 days, this session, all history). Stored windows are averaged into at most 300 points by the server (`GET /api/history/series?window=1h|24h|7d|session|all|custom&max_points=`, with `start` and `end` in unix seconds for `custom`) and fetched on demand. A "Custom range" option takes a start and end date and time.
- 🪶 **Light Polling**: each cycle sends only `AT+CSQ` and `AT+QENG`; operator, registration, voltage and temperature are polled on slower timers, and `+CEREG` updates arrive as URCs.
- 🔔 **Signal Alerts**: the bell in the header opens a dialog with RSRP and RSRQ minimums (defaults -110 dBm and -15 dB), and switches for the Poor zone, cell handovers, a modem that stops answering, desktop notifications and an audible beep. Alerts are edge triggered with 3 dB of hysteresis, show as highlighted lines in the terminal log, and a recovery line is logged when the condition ends. Silence while the modem is in PSM or deep sleep is expected and does not alert. Settings are kept in the browser (`localStorage`). Desktop notifications need the browser's permission and, outside `localhost`, a secure context.: Instantly clear historical database records to start telemetry logging fresh.
- 💻 **Built-in AT Command Console**: Execute manual AT commands with quick-action presets (`AT`, `ATI`, `AT+CSQ`, `AT+QCCID`, `AT+CIMI`, `AT+CBC`, `AT+QENG`, `AT+COPS?`, `AT+CEREG?`).
- 🛑 **Graceful Shutdown & Signal Handling**: Supports web Exit button shutdown and terminal `Ctrl+C` (`SIGINT`) and `SIGTERM` clean resource releases.

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

This needs Python 3.10 or later and `git`, because [py-logkit](https://github.com/markbac/py-logkit) is installed from GitHub.

On Windows, `run_dashboard.ps1` does the whole set-up and then starts the server. It checks Python and git, removes a leftover empty `pylogkit` folder from the old bundled copy, creates `.venv`, installs `requirements.txt` when a package is missing and runs `server.py` with the arguments you give it:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_dashboard.ps1 --port auto --record session.jsonl
.\run_dashboard.ps1 -SetupOnly      # prepare the environment and stop
.\run_dashboard.ps1 -WithMqtt --port COM3   # also install paho-mqtt
```

If py-logkit is missing or hidden, the dashboard now stops with a message saying what to do instead of a traceback.

On Python 3.13 the test suite and the checks below run in GitHub Actions (`.github/workflows/ci.yml`).

### 2. Running the Server
Launch the server. It does not connect to a port unless asked to:
```bash
python server.py                            # choose or detect a port in the web UI
python server.py --port auto                # probe every serial port for an AT modem (up to about 8 s per port, so a sleeping module is found)
python server.py --port COM3 --baud 115200  # Windows
python server.py --port /dev/ttyUSB0        # Linux (macOS: /dev/cu.usbserial-*)
```
Other options: `--host` (loopback addresses only, default `127.0.0.1`), `--http-port` (web server port, default `8080`), `--no-browser`, `--db-path`, `--retention-days`, `--no-file-log`; `--help` lists them all. The `Host` and `Origin` checks follow `--http-port`.

For a `quectel-dashboard` command, install the project in editable mode from the checkout (the web assets are read from the checkout, so a plain install is not supported):
```bash
pip install -e .
quectel-dashboard --demo --no-browser
```

The magnifying-glass button next to the port list does the same probing from the UI. Candidate ports from FTDI (the FT4232H board exposes four) and Quectel come first, and each is sent `AT` to find the one that answers `OK`.
Open **[http://localhost:8080](http://localhost:8080)** in your web browser.

> **Note:** after powering the evaluation board, press the **RESET** button to wake the modem. Until the modem answers, the status badge reads "Connecting ... press RESET on the board if just powered" and the log shows a `[HINT]` line. The dashboard keeps probing with a plain `AT` and loads the module details as soon as it replies. If PSM is enabled the module can also go quiet later; the same hint is shown.

---

## 🗄️ Database Location

The database is created on first start if it does not exist. By default it lives in your per-user data directory (`%LOCALAPPDATA%\\quectel-bc660k-dashboard` on Windows, `~/Library/Application Support/quectel-bc660k-dashboard` on macOS, `~/.local/share/quectel-bc660k-dashboard` on Linux). Override it with `--db-path FILE` or the `QUECTEL_DASHBOARD_DB` environment variable. Database files are git-ignored.

### Retention

History older than 90 days is deleted at start-up and once a day. Change it with `--retention-days N` (`0` keeps everything).

### Schema versions

The schema version is stored in SQLite's `PRAGMA user_version`. On start-up the dashboard creates a new database at the latest version, or runs any pending migrations in order, each in its own transaction. Before migrating an existing database it writes a copy next to it (`telemetry.db.bak-v<old version>`). A database written by a newer dashboard is refused with a clear message instead of being modified. Migrations only add things: data columns are never dropped automatically. To change the schema, append a function to `MIGRATIONS` in `db_manager.py`.

---

## 🔋 PSM Timers

The PSM panel sends the timers as 8-bit strings (3GPP unit bits followed by a 5-bit value). The defaults are:

| Timer | Default | Meaning |
|---|---|---|
| T3412 (periodic TAU) | `10100101` | unit `101` = 1 minute, value 5, so 5 minutes |
| T3324 (active time) | `00100100` | unit `001` = 1 minute, value 4, so 4 minutes |

These are requests. The network decides the values actually granted, so the panel shows what the module reports from `AT+CPSMS?` after the command. Once PSM is on, the module can stop answering on the UART after T3324 expires.

---

## 📟 Supported Modules

The module is identified from the `ATI` reply when the modem first answers, and the serving-cell command is chosen to match. The Module field in the System card shows the result. An unrecognised reply keeps the BC660K commands and logs a warning.

| Family | Models matched | Serving-cell command | Status |
|---|---|---|---|
| Quectel BC660K | BC660K-GL | `AT+QENG=0` | Used on a real board |
| Quectel LTE | BG95, BG96, EC25, EG25, EG91, EG95 | `AT+QENG="servingcell"` | Written from the vendor manual, not tested on hardware |
| SIMCom LTE | SIM7000, SIM7600 | `AT+CPSI?` | Written from the vendor manual, not tested on hardware |

The parsers live in `drivers.py`, one small class per family, so another module is one class and one entry in `DRIVERS`. The other start-up and poll commands (`AT+CSQ`, `AT+COPS?`, `AT+CEREG?`, `AT+CBC`, power-saving queries) are the 3GPP or BC660K ones; where a module rejects one, the matching field simply stays empty. u-blox modules (`AT+UCED`) are not supported yet.

---

## 🧰 Bench Scripts

`tools/` holds small scripts for checking a board without the dashboard. They take the port as an argument:

```bash
python tools/probe_ports.py                       # list ports and probe each with AT
python tools/send_at_twice.py COM3 COM4           # raw reply to AT on the given ports
python tools/validate_board.py /dev/ttyUSB0       # run a fixed set of identification commands
python tools/cops_scan_bench.py COM3               # does AT+COPS=? answer when deregistered? (restores settings after)
```

---

## 🎞️ Recording and Replaying a Modem

`python server.py --port auto --record session.jsonl` appends every answered AT exchange to a JSON Lines file. ICCIDs, IMSIs and IMEIs are redacted as they are written (cell identities and locations are not, so review a recording before sharing it). `python server.py --replay session.jsonl` plays it back through a pseudo-terminal, so the real serial code path runs without hardware (POSIX only). The nth request for a command gets its nth recorded reply and the last reply repeats. `tests/transcripts/synthetic_attached.jsonl` is a hand-written transcript used by the tests; it is not a hardware capture.

---

## 🧪 Running the Tests

```bash
pip install -r requirements-dev.txt
python -m pyflakes .  # unused imports and similar
python -m pytest      # back end
npm install && npm test   # front end (jsdom)
```

---

## 📄 License

Distributed under the [MIT License](LICENSE).
