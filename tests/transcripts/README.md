# Transcripts

JSON Lines recordings of AT exchanges, replayed by `modem_replay.TranscriptModem`
(`python server.py --replay FILE`).

- `synthetic_attached.jsonl` is written by hand in the formats the manual
  describes, for an attached module. It is not a capture from hardware.

- `bc660k_real_2026-10-03.jsonl` is a capture from a real BC660K-GL (firmware BC660KGLAAR01A05) on a live NB-IoT network, recorded with `--record`. The cell id, tracking area code, APN and IP address were replaced afterwards; the recorder had already replaced the ICCID, IMSI and IMEI. Its `AT+QPING` reply is cut short (recorded before #82 was fixed) and the `AT+COPS=?` scan never answered, so neither is in it.

To add a real capture run `python server.py --port auto --record tests/transcripts/NAME.jsonl`.
ICCIDs, IMSIs and IMEIs are redacted as they are written; review the file for
anything else identifying (cell identities, locations) before committing it.
