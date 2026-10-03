# Changelog

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

- `--port auto` now finds a module in deep sleep: it sends `AT` up to three times, waiting 2.5 s after each, because a sleeping BC660K answers the first one with a blank line (#94).
- A carrier scan that gets no answer from the module now shows why in the Available Carrier Networks panel instead of "Found 0 networks", keeps the previous result, and the panel shows elapsed time and says a scan can take up to 3 minutes (#93).
- Deadlock when opening a serial port failed (#41), undefined `_parse_ip()` in the APN code (#42), a front-end crash on missing elements (#43), the file-logging toggle (#45).
- Hard-coded telemetry and SIM identifiers removed from the page (#44).
- Late replies, stale input and unsolicited result codes no longer corrupt the next command (#48, #50, #66). Commands use the documented per-command timeouts (#49).
- Wrong access-technology and registration labels (#52). PSM changes are checked and the granted timers read back (#53).
- Only a previous instance of this dashboard is stopped when reclaiming a port (#47).
- Modem and network strings are escaped before rendering (#55).
- Found by running 2.0.0 on a real BC660K-GL: the ping result is read from its summary line rather than the first per-packet code (#82), network scans get 180 s and no longer make the module look dead (#83), the IP address is read from the board's own PDP context (#84), and MCC/MNC are derived from the numeric operator code (#85).

### Added

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
