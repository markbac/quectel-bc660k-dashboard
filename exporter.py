"""Push telemetry to an MQTT broker and/or an HTTP webhook.

The exporter listens to the dashboard's state events. It sends a telemetry
message at most every ``interval`` seconds and, optionally, an alert message
when RSRP falls below a limit (and when it recovers). Sending happens on a
worker thread, so a slow or unreachable endpoint never delays polling.

Credentials are never stored in the settings file: set ``QUECTEL_MQTT_USER``
and ``QUECTEL_MQTT_PASSWORD`` for the broker, and ``QUECTEL_WEBHOOK_TOKEN`` to
send ``Authorization: Bearer <token>`` to the webhook.

Messages carry signal figures and the serving cell's identity (operator, cell
id, PCI, band, TAC). They never include the ICCID, IMSI or IMEI.
"""
import importlib.util
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

DEGRADATION_HYSTERESIS_DB = 3
WEBHOOK_TIMEOUT_SECONDS = 5.0
QUEUE_SIZE = 20


@dataclass
class ExportConfig:
    """User settings for remote export."""

    enabled: bool = False
    interval: int = 60
    device_name: str = "bc660k"
    webhook_url: str = ""
    webhook_degradation_only: bool = False
    degradation_rsrp: int = -110
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_topic: str = "quectel/bc660k/telemetry"
    mqtt_tls: bool = False

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "ExportConfig":
        """Build a valid config from untrusted values; bad values fall back to defaults."""
        config = cls()
        source = raw if isinstance(raw, dict) else {}
        for field in fields(cls):
            if field.name not in source:
                continue
            value = source[field.name]
            default = getattr(config, field.name)
            try:
                if isinstance(default, bool):
                    if not isinstance(value, bool):
                        continue
                elif isinstance(default, int):
                    if isinstance(value, bool):
                        continue
                    value = int(value)
                else:
                    value = str(value).strip()
            except (TypeError, ValueError):
                continue
            setattr(config, field.name, value)
        config.interval = min(3600, max(10, config.interval))
        config.mqtt_port = min(65535, max(1, config.mqtt_port))
        config.degradation_rsrp = min(-40, max(-140, config.degradation_rsrp))
        if config.webhook_url and not valid_webhook_url(config.webhook_url):
            config.webhook_url = ""
        if "/" in config.mqtt_host or " " in config.mqtt_host:
            config.mqtt_host = ""
        if not config.mqtt_topic or "+" in config.mqtt_topic or "#" in config.mqtt_topic:
            config.mqtt_topic = cls.mqtt_topic
        return config

    def to_dict(self) -> Dict[str, Any]:
        """The settings as a plain dict (contains no secrets)."""
        return asdict(self)

    @classmethod
    def load(cls, path: str) -> "ExportConfig":
        """Read settings from a JSON file; a missing or damaged file gives the defaults."""
        try:
            with open(path, encoding="utf-8") as handle:
                return cls.from_dict(json.load(handle))
        except (OSError, ValueError):
            return cls()

    def save(self, path: str) -> None:
        """Write the settings as JSON."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2)


def valid_webhook_url(url: str) -> bool:
    """True for an ``http`` or ``https`` URL with a host."""
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def build_payload(state: Dict[str, Any], device_name: str, kind: str = "telemetry",
                  message: Optional[str] = None) -> Dict[str, Any]:
    """The JSON message for a state: signal, serving cell and a UTC timestamp."""
    signal = state.get("signal") or {}
    cell = state.get("serving_cell") or {}
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "type": kind,
        "device": device_name,
        "timestamp": now.isoformat(timespec="seconds"),
        "unix_time": int(now.timestamp()),
        "mode": state.get("mode"),
        "signal": {key: signal.get(key) for key in ("rsrp", "rsrq", "rssi", "sinr", "csq", "quality_label")},
        "cell": {key: cell.get(key) for key in
                 ("operator", "mcc", "mnc", "cell_id", "pci", "earfcn", "band", "tac")},
    }
    if message:
        payload["message"] = message
    return payload


def send_webhook(url: str, payload: Dict[str, Any], token: Optional[str] = None) -> None:
    """POST ``payload`` as JSON. Raises ``OSError`` or ``ValueError`` on failure."""
    if not valid_webhook_url(url):
        raise ValueError("webhook URL must be http or https")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT_SECONDS) as response:  # noqa: S310 (scheme checked)
        if response.status >= 300:
            raise OSError(f"webhook answered HTTP {response.status}")


def send_mqtt(config: ExportConfig, topic: str, payload: Dict[str, Any]) -> None:
    """Publish ``payload`` on ``topic``. Needs the optional ``paho-mqtt`` package."""
    try:
        from paho.mqtt import publish
    except ImportError as exc:
        raise RuntimeError("MQTT export needs the paho-mqtt package (pip install paho-mqtt)") from exc
    user = os.environ.get("QUECTEL_MQTT_USER")
    auth = {"username": user, "password": os.environ.get("QUECTEL_MQTT_PASSWORD", "")} if user else None
    publish.single(topic, json.dumps(payload), hostname=config.mqtt_host, port=config.mqtt_port,
                   auth=auth, tls={} if config.mqtt_tls else None, keepalive=30)


class Exporter:
    """Turns dashboard state events into outgoing messages."""

    def __init__(
        self,
        config: Optional[ExportConfig] = None,
        webhook: Callable[..., None] = send_webhook,
        mqtt: Callable[..., None] = send_mqtt,
        log: Callable[[str, str], None] = lambda text, direction: None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.config = config or ExportConfig()
        self._webhook = webhook
        self._mqtt = mqtt
        self._log = log
        self._clock = clock
        self._queue: "queue.Queue[tuple]" = queue.Queue(maxsize=QUEUE_SIZE)
        self._last_sent: Optional[float] = None
        self._degraded = False
        self._lock = threading.Lock()
        self.sent = 0
        self._errors: Dict[str, str] = {}
        self.last_success: Optional[str] = None
        self._worker: Optional[threading.Thread] = None

    # --- configuration -------------------------------------------------------

    def configure(self, config: ExportConfig) -> None:
        """Replace the settings; the next state event may send immediately."""
        with self._lock:
            self.config = config
            self._last_sent = None

    @property
    def last_error(self) -> Optional[str]:
        """The newest failure of a destination that has not delivered since, if any."""
        return next(reversed(self._errors.values()), None) if self._errors else None

    def status(self) -> Dict[str, Any]:
        """Settings plus delivery status, for the UI."""
        return {
            "config": self.config.to_dict(),
            "mqtt_available": _mqtt_available(),
            "sent": self.sent,
            "last_error": self.last_error,
            "last_success": self.last_success,
        }

    # --- events --------------------------------------------------------------

    def on_event(self, event_type: str, data: Any) -> None:
        """``SerialManager`` callback: look at every state and queue what is due."""
        if event_type != "state" or not self.config.enabled or not isinstance(data, dict):
            return
        signal = data.get("signal") or {}
        rsrp = signal.get("rsrp")
        if not data.get("hardware_communicated") or not isinstance(rsrp, (int, float)):
            return
        config = self.config

        message = self._degradation_message(rsrp, config)
        if message is not None:
            kind, text = message
            self._enqueue(build_payload(data, config.device_name, kind, text), alert=True)

        now = self._clock()
        with self._lock:
            due = self._last_sent is None or now - self._last_sent >= config.interval
            if due:
                self._last_sent = now
        if due:
            self._enqueue(build_payload(data, config.device_name), alert=False)

    def _degradation_message(self, rsrp: float, config: ExportConfig):
        if not self._degraded and rsrp < config.degradation_rsrp:
            self._degraded = True
            return "signal_degraded", f"RSRP {rsrp} dBm is below {config.degradation_rsrp} dBm"
        if self._degraded and rsrp >= config.degradation_rsrp + DEGRADATION_HYSTERESIS_DB:
            self._degraded = False
            return "signal_recovered", f"RSRP recovered to {rsrp} dBm"
        return None

    # --- delivery ------------------------------------------------------------

    def flush(self) -> None:
        """Block until every queued message has been delivered or has failed."""
        self._queue.join()

    def _enqueue(self, payload: Dict[str, Any], alert: bool) -> None:
        try:
            self._queue.put_nowait((payload, alert))
        except queue.Full:
            self._log("[EXPORT] Send queue full; dropping a message.", "WARNING")
            return
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, daemon=True, name="exporter")
            self._worker.start()

    def _run(self) -> None:
        while True:
            try:
                payload, alert = self._queue.get(timeout=30)
            except queue.Empty:
                return  # restarted on demand
            try:
                for sink, ok, error in self.deliver(payload, alert):
                    if ok:
                        self.sent += 1
                        self._errors.pop(sink, None)
                        self.last_success = payload["timestamp"]
                    else:
                        self._errors.pop(sink, None)
                        self._errors[sink] = f"{sink}: {error}"
                        self._log(f"[EXPORT] {sink} failed: {error}", "ERROR")
            finally:
                self._queue.task_done()

    def deliver(self, payload: Dict[str, Any], alert: bool, test: bool = False) -> List[tuple]:
        """Send one payload to the configured sinks; return ``(sink, ok, error)`` rows.

        Telemetry goes to MQTT and, unless webhook is alert-only, to the
        webhook. Alerts go to the webhook and to ``<topic>/alert`` on MQTT.
        Test messages go to every sink on the normal topic.
        """
        config = self.config
        results: List[tuple] = []
        if config.webhook_url and (alert or test or not config.webhook_degradation_only):
            results.append(self._attempt("webhook", lambda: self._webhook(
                config.webhook_url, payload, os.environ.get("QUECTEL_WEBHOOK_TOKEN"))))
        if config.mqtt_host:
            topic = f"{config.mqtt_topic}/alert" if alert and not test else config.mqtt_topic
            results.append(self._attempt("mqtt", lambda: self._mqtt(config, topic, payload)))
        return results

    @staticmethod
    def _attempt(sink: str, action: Callable[[], None]) -> tuple:
        try:
            action()
            return sink, True, None
        except Exception as exc:  # network libraries raise many kinds of error
            return sink, False, str(exc)

    def send_test(self, state: Dict[str, Any]) -> List[tuple]:
        """Send a test message now, synchronously, to every configured sink."""
        payload = build_payload(state, self.config.device_name, "test", "Test message from the dashboard")
        return self.deliver(payload, alert=False, test=True)


def _mqtt_available() -> bool:
    try:
        return importlib.util.find_spec("paho.mqtt.publish") is not None
    except ModuleNotFoundError:
        return False
