# Transcripts

JSON Lines recordings of AT exchanges, replayed by `modem_replay.TranscriptModem`
(`python server.py --replay FILE`).

- `synthetic_attached.jsonl` is written by hand in the formats the manual
  describes, for an attached module. It is not a capture from hardware.

To add a real capture run `python server.py --port auto --record tests/transcripts/NAME.jsonl`.
ICCIDs, IMSIs and IMEIs are redacted as they are written; review the file for
anything else identifying (cell identities, locations) before committing it.
