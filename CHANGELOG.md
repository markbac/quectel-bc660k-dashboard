# Changelog

## Unreleased

### Added

- The Signal Strength Trend chart can plot RSRP, RSRQ, SINR, RSSI and CSQ, with a checkbox for each. The choice is remembered in the browser, and an axis is drawn only while a metric on it is shown. `/api/history/series` now also returns `rssi` and `csq` (#115).
- The network survey records every cell it can see on each network (serving and neighbour cells, with PCI, EARFCN, RSRP and RSRQ), lists them under the network and marks the strongest (#128).
- Optional "Lock to its strongest cell" for the network survey (off by default): after joining the best network the module is locked to its strongest cell with `AT+QLOCKF`, and the previous lock is put back if it cannot attach (#129).

### Fixed

- Reconnecting no longer leaves two poll loops running (#116).
- No history row or live chart point is recorded while the module is asleep or silent, and the live chart no longer adds duplicate points for scan, survey or APN events (#117, #125).
- APN, PDP type, context id, ping host, DNS name, PSM timers and the eDRX value are validated, and bad values give HTTP 422 instead of a broken or doubled AT command (#118).
- An eDRX change the module rejects is reported as a failure (HTTP 502) and keeps the granted values (#119).
- A carrier scan can no longer start twice or stay stuck on "scanning" after an error (#120). The demo simulator no longer stops silently on an error (#121).
- RSRQ and RSSI bars are empty when there is no value, PCI 0 and EARFCN 0 are shown, and the log console keeps the newest 500 lines (#122, #123, #124).
- The webhook bearer token is no longer sent to another host when the server redirects (#126).
- A stale `dashboard.pid` no longer lets the dashboard terminate an unrelated process that reused the PID: the file records the process start time and is checked first (#127). This adds the `psutil` dependency.

## 2.0.0 - 2026-10-03

A large reliability, security and feature release. Several changes are not backwards compatible, see "Upgrading".

### Upgrading

- The dashboard no longer connects to `COM3` by default. Pass `--port COM3` (or `/dev/ttyUSB0`, or `--port auto`).
- The SQLite database is created in your per-user data directory (or `$QUECTEL_DASHBOARD_DB`, or `--db-path`) instead of next to the code. A `telemetry.db` from an earlier version is not picked up automatically. Copy it to the new location to keep it, and the first start migrates it (a backup is written first).
- History is now scoped to the ICCID of the connected SIM. Older rows are assigned to the SIM they were recorded with where that is known.
- The serving cell is read with `AT+QENG=0`, the documented BC660K-GL command, instead of `AT+QENG="servingcell"`.
- The web server only accepts requests whose `Host` and `Origin` are the local machine.
- Logging uses the [py-logkit](https://github.com/markbac/py-logkit) package, installed from GitHub (it is not the `pylogkit` on PyPI). The old vendored copy is gone, `server.py` start-up, shutdown and uvicorn output now go through it instead of `print()`, and Python 3.10 or later is required.
- `paho-mqtt` is optional (`pip install -e .[mqtt]`).

### Fixed

- Starting without py-logkit installed, or with a leftover `pylogkit` folder in the way, now stops with a clear message instead of an `ImportError`. `run_dashboard.ps1` sets up a virtual environment, installs the requirements and starts the server on Windows (#107, #109).
- `--port auto` now finds a module in deep sleep: it sends `AT` up to three times, waiting 2.5 s after each, because a sleeping BC660K answers the first one with a blank line (#94).
- A carrier scan that gets no answer from the module now shows why in the Available Carrier Networks panel instead of "Found 0 networks", keeps the previous result, and the panel shows elapsed time and says a scan can take up to 3 minutes (#93).
- Dashboard layout: a missing `</section>` made every row after System Diagnostics nest inside the hardware row, which stretched cards and left empty space. Rows now lay out as intended, the PSM and ping cards are styled and side by side, the log console is taller and resizable, CID 0 is no longer shown as 1, the console no longer shows `[TX] TX>`, and old bare PLMN codes in the history table are labelled like new ones (#95).
- `AT+COPS=?` can take about 5 minutes on a real board, so its timeout is now 10 minutes. Scan replies with empty operator names (`(1,"","","23415",9)`) were being dropped and are parsed. Operator names are looked up from the PLMN the network reports (`plmn.py`, for example `23415` is Vodafone UK) and anything unknown shows as `PLMN <code>`. The APN box is no longer pre-filled with an operator (#102).
- The ping timeout per packet is configurable (field in the ping card and `timeout` in `POST /api/ping`, 1 to 255 s) and defaults to 20 s instead of 4 s, with which a real BC660K-GL timed out on every packet (#111).
- Deadlock when opening a serial port failed (#41), undefined `_parse_ip()` in the APN code (#42), a front-end crash on missing elements (#43), the file-logging toggle (#45).
- Hard-coded telemetry and SIM identifiers removed from the page (#44).
- Late replies, stale input and unsolicited result codes no longer corrupt the next command (#48, #50, #66). Commands use the documented per-command timeouts (#49).
- Wrong access-technology and registration labels (#52). PSM changes are checked and the granted timers read back (#53).
- Only a previous instance of this dashboard is stopped when reclaiming a port (#47).
- Modem and network strings are escaped before rendering (#55).
- Found by running 2.0.0 on a real BC660K-GL: the ping result is read from its summary line rather than the first per-packet code (#82), network scans no longer make the module look dead (#83, and a scan timeout of 10 minutes after a real scan took about 5 minutes, #102), the IP address is read from the board's own PDP context (#84), and MCC/MNC are derived from the numeric operator code (#85).

### Added

- A Network Survey card and `POST /api/survey` (and `/api/survey/stop`): scan, try every allowed network in turn, rank by RSRP, SINR and RSRQ, and connect to the best or restore the previous selection (#112). Not yet run on a real board.
- `tools/cops_scan_bench.py` checks whether `AT+COPS=?` answers while the module is deregistered, and restores the operator selection and sleep setting afterwards (#100).
- The Available Carrier Networks card can deregister (`AT+COPS=2`), register automatically (`AT+COPS=0`) and register on a scanned network (`AT+COPS=1,2,"<plmn>",<act>`), through `POST /api/register` (#103).
- Modem state machine with PSM and deep-sleep detection, a start-up profile that reads the real modem state, requested versus granted PSM and eDRX values, and a reminder to press RESET (#61, #62, #63, #64).
- Versioned database migrations, ICCID-scoped history, recording sessions, retention (default 90 days) and a lighter poll cycle (#57, #58, #59, #60, #67).
- Serial port auto-detection, `--host`, `--http-port`, `--no-browser`, a `quectel-dashboard` command and a pinned Chart.js (#68, #69).
- A history chart with selectable windows, a custom date range, server-side downsampling and a configurable logging interval (#70, #74).
- Configurable signal alerts with desktop notifications and an optional beep (#75).
- MQTT and webhook telemetry export (#76).
- A serving-cell map using OpenCellID and OpenStreetMap, loaded only on request (#78).
- Per-module drivers with model detection for Quectel LTE and SIMCom modules. These two are written from the vendor manuals and not yet tested on hardware (#80).
- Recording and replaying a modem session (`--record`, `--replay`) (#71).

### Internal

- A sanitised capture from a real BC660K-GL is replayed in the tests, which confirmed the formats of `AT+QENG=0`, `AT+CEREG?` with granted timers, `AT+CPSMS?`, `AT+CEDRXS?`, `AT+QSCLK?`, `AT+CBC` and `AT+CGSN=1` (#86).
- AT command layer extracted into `at_channel.py` (#65), a pytest and jsdom test suite, GitHub Actions CI, bench scripts moved to `tools/` (#72).
