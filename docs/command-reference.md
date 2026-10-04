# Command Reference

Every AT command the dashboard sends to the module, when it sends it, and the HTTP and WebSocket interface the web page uses. The AT commands are the BC660K-GL ones unless a row says otherwise. The source of truth is the code (`serial_manager.py`, `survey.py`, `at_channel.py`, `drivers.py`) and the Quectel BC660K-GL&BC950K-GL AT Commands Manual V1.3.

> **Note:** a command a particular firmware does not support is not an error for the dashboard. The matching field stays empty and polling carries on.

## AT commands

### Start-up profile

Run once after the module first answers, and again after it has been silent (asleep or reset).

| Command | Purpose |
| --- | --- |
| `ATE0` | Echo off, so replies hold only the answer. |
| `ATI`, `AT+CGMR`, `AT+CGSN=1` | Manufacturer and model, firmware revision, IMEI. |
| `AT+CPIN?` | SIM state. |
| `AT+QCCID`, `AT+CIMI` | ICCID (history is stored per ICCID) and IMSI. |
| `AT+CBC`, `AT+QTEMP` | Supply voltage and temperature. `AT+QTEMP` is only polled again if the first query returned a value. |
| `AT+QNBIOTEVENT=1,1`, `AT+QCFG="dsevent",1` | Ask the module to announce PSM and deep-sleep changes. |
| `AT+CEREG=4` | Extended registration reports, which carry the timers the network granted. |
| `AT+CPSMS?`, `AT+CEDRXS?`, `AT+QSCLK?`, `AT+CEDRXRDP` | Read the PSM, eDRX and sleep-clock settings. |
| `AT+CGDCONT?`, `AT+CGATT?`, `AT+CGPADDR=<cid>` | APN, packet attach state and IP address, using the context `AT+CGDCONT?` reported. |

### Polling

| Command | How often | Purpose |
| --- | --- | --- |
| `AT+CSQ` | Every poll (1, 2, 3, 5 or 10 s, set in the UI) | CSQ and RSSI. |
| `AT+QENG=0` | Every poll | Serving cell (RSRP, RSRQ, SINR, PCI, EARFCN, cell ID) and neighbour cells. SIMCom modules use `AT+CPSI?` and other Quectel modules `AT+QENG="servingcell"`, chosen by the driver in `drivers.py`. |
| `AT+CESQ` | Only when the cell command gave no RSRP | Fallback signal reading. |
| `AT+COPS?` | 30 s | Current operator. |
| `AT+CEREG?` | 60 s | Registration state. Changes also arrive as `+CEREG` URCs. |
| `AT+CBC`, `AT+QTEMP` | 30 s | Supply voltage and temperature. |
| `AT+QCCID` (and `AT+CEDRXRDP` while eDRX is on) | 60 s | Notices a SIM swap or module reset. |

A poll cycle stops at the first timeout, so a silent module is not asked for every command.

### Network selection and scanning

| Command | Used by | Purpose |
| --- | --- | --- |
| `AT+COPS=?` | Scan button, scheduled scan, survey | List visible networks. Answers in about 5 minutes when deregistered. The dashboard waits up to 10 minutes. |
| `AT+COPS=2` | Deregister button, survey | Leave the network. |
| `AT+COPS=0` | Automatic button, survey restore | Automatic selection. |
| `AT+COPS=1,2,"<plmn>",<act>` | Register button, survey | Register on one network. `<act>` is 9 for NB-IoT. |

Registration commands are refused (HTTP 409) while a scan or survey is running.

### Survey only

| Command | Purpose |
| --- | --- |
| `AT+QSCLK=0` and back | Sleep clock off for the run, then restored to what it was. |
| `AT+CFUN=0`, `AT+CFUN=1` | Radio off and on around a cell lock. The manual says `AT+QLOCKF` only works with the radio off and takes effect after `AT+CFUN=1`. |
| `AT+QLOCKF?` | Read the current lock so it can be put back. |
| `AT+QLOCKF=1,<EARFCN>,<PCI>` | Lock to the strongest cell. Only sent when "Lock to its strongest cell" is ticked. EARFCN 0 (which removes a lock) and values outside EARFCN 1 to 262143 or PCI 0 to 503 are never sent. |
| `AT+QLOCKF=0` | Remove a lock. Also how a failed lock is undone when there was none before. |

The lock is saved by the module and survives reboots. To remove one by hand, send `AT+CFUN=0`, `AT+QLOCKF=0`, `AT+CFUN=1` from the AT console.

### Settings you change from the UI

| Command | Control | Notes |
| --- | --- | --- |
| `AT+CGDCONT=<cid>,"<pdp>","<apn>"`, `AT+CGATT=1` | APN panel | Then reads back `AT+CGATT?`, `AT+CGPADDR` and `AT+CGDCONT?`. |
| `AT+CPSMS=1,,,"<T3412>","<T3324>"` or `AT+CPSMS=0` | PSM panel | Falls back to the three-field form `AT+CPSMS=1,"<T3412>","<T3324>"` if the five-field one is rejected. Timers are 8 binary digits. |
| `AT+CEDRXS=<mode>,5,"<value>"` | eDRX panel | Value is 4 binary digits. A rejected setting is reported as a failure. |
| `AT+QPING=0,"<host>",<timeout>,<count>` | Ping test | Count is clamped. The host is validated. |
| `AT+QIDNSGIP=0,"<domain>"` | DNS test | The domain is validated. |

Values that would break the command (quotes, line breaks, wrong length) are refused with HTTP 422 before anything is sent.

### Console

The AT console sends whatever you type through the same channel, one command at a time, so it interleaves safely with polling.

### Timeouts

From `at_channel.py`, matched by prefix on the command, with the default of 5 s for anything not listed.

| Command | Timeout |
| --- | --- |
| `AT+COPS=?` | 600 s |
| `AT+COPS=` (select or release) | 180 s |
| `AT+CGATT=` | 70 s |
| `AT+QENG` | 15 s |
| `AT+CSQ`, `AT+CESQ`, `AT+CGPADDR`, `AT+CGMR`, `AT+CGSN`, `ATI` | 5 s |
| `AT+QPING` | `count x timeout + 5` s |

## HTTP interface

The server listens on loopback only and refuses requests whose `Host` or `Origin` is not the local machine. Bodies are JSON. Bad values give 422, a missing serial connection 400, and a busy module 409.

### Connection and state

| Method and path | Purpose |
| --- | --- |
| `GET /api/ports` | List serial ports. |
| `POST /api/detect` | Probe the ports for an AT modem. Body: none. |
| `POST /api/connect` | Open a port. Body: `port`, `baudrate` (default 115200). |
| `POST /api/disconnect` | Close the port. |
| `GET /api/state` | The full state the web page shows. |
| `POST /api/settings` | Poll, scan and history intervals (`telemetry_interval`, `cops_scan_interval`, `history_interval`). |
| `POST /api/file_logging` | Body: `enabled`. |
| `POST /api/send_at` | Body: `command`. Returns `command` and `response`. |
| `POST /api/shutdown` | Stop the server cleanly. |

### Networks

| Method and path | Purpose |
| --- | --- |
| `POST /api/scan` | Start a carrier scan (`AT+COPS=?`) in the background. |
| `POST /api/register` | Body: `action` (`deregister`, `auto` or `manual`), `plmn` and `act` for `manual`. |
| `POST /api/survey` | Start a network survey. Body: `select_best` (default true), `lock_best_cell` (default false). 409 if a scan or survey is running. |
| `POST /api/survey/stop` | Stop after the network being tried. |

### Module settings and tests

| Method and path | Body |
| --- | --- |
| `POST /api/apn` | `apn`, `pdp_type` (default `IP`), `cid` (default 1) |
| `POST /api/psm` | `enabled`, `t3412`, `t3324`. 502 if the module does not reply OK. |
| `POST /api/edrx` | `enabled`, `edrx_val`. 502 if the module does not reply OK. |
| `POST /api/ping` | `host`, `count`, `timeout` |
| `POST /api/dns` | `domain` |

### History

| Method and path | Purpose |
| --- | --- |
| `GET /api/history?limit=` | Latest rows of the connected SIM (10 to 2000), with stats. |
| `GET /api/history/series` | Averaged series for the chart: `window` (`1h`, `24h`, `7d`, `session`, `all`, `custom`), `max_points` (10 to 2000, default 300), and `start` and `end` in unix seconds for `custom`. Each point carries `rsrp`, `rsrq`, `sinr`, `rssi` and `csq`. |
| `GET /api/sessions` | Recording sessions of the connected SIM. |
| `GET /api/history/export` | CSV of up to 5000 rows. |
| `POST /api/history/clear` | Delete the connected SIM's history, or all with `?all=true`. |

### Export and cell location

| Method and path | Purpose |
| --- | --- |
| `GET /api/export`, `POST /api/export` | Read or set the webhook and MQTT export settings. Credentials are never returned. |
| `POST /api/export/test` | Send a test message to each destination. |
| `GET /api/cell_location`, `POST /api/cell_location` | Whether an OpenCellID key is set, and look up the serving cell on OpenCellID. The lookup sends the cell identity to that service. |

### WebSocket

`/ws` pushes `{"type": "state", "data": ...}` after each change and `{"type": "log", ...}` for each log line. Log lines are not part of the state message.
