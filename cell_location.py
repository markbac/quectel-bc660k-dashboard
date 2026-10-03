"""Look up where a serving cell is, using the OpenCellID database.

This sends the cell's identity (MCC, MNC, TAC, cell id) to opencellid.org, so
it only runs when the user asks for it and an API key is configured in the
``QUECTEL_OPENCELLID_KEY`` environment variable. The key is never returned by
the dashboard's API.
"""
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

API_URL = "https://opencellid.org/cell/get"
KEY_ENV_VAR = "QUECTEL_OPENCELLID_KEY"
TIMEOUT_SECONDS = 8.0


class CellLookupError(Exception):
    """Base class for lookup failures that carry a user-readable message."""


class NoApiKey(CellLookupError):
    """No OpenCellID key is configured."""


class CellNotFound(CellLookupError):
    """OpenCellID does not know this cell."""


class LookupFailed(CellLookupError):
    """The service could not be reached or answered unexpectedly."""


def _fetch(url: str) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "quectel-bc660k-dashboard"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (fixed https URL)
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise CellNotFound("OpenCellID has no record of this cell") from exc
        raise LookupFailed(f"OpenCellID answered HTTP {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise LookupFailed(f"Could not reach OpenCellID: {exc}") from exc


class CellLocator:
    """Looks cells up and remembers the answers for the life of the process."""

    def __init__(self, fetch: Callable[[str], Dict[str, Any]] = _fetch,
                 key: Optional[Callable[[], Optional[str]]] = None):
        self._fetch = fetch
        self._key = key or (lambda: os.environ.get(KEY_ENV_VAR))
        self._cache: Dict[Tuple[int, int, int, int], Dict[str, Any]] = {}
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        """True when an API key is available."""
        return bool(self._key())

    def locate(self, mcc: Any, mnc: Any, tac: Any, cell_id: Any) -> Dict[str, Any]:
        """Return ``{"lat", "lon", "range"}`` (range in metres, may be ``None``).

        Arguments are the decimal values of the serving cell. Raises
        ``NoApiKey``, ``CellNotFound`` or ``LookupFailed``.
        """
        try:
            ident = (int(mcc), int(mnc), int(tac), int(cell_id))
        except (TypeError, ValueError):
            raise CellNotFound("The serving cell is not known yet") from None
        with self._lock:
            if ident in self._cache:
                return self._cache[ident]
        key = self._key()
        if not key:
            raise NoApiKey(f"Set {KEY_ENV_VAR} to an OpenCellID API key to locate cells")
        query = urllib.parse.urlencode({
            "key": key, "mcc": ident[0], "mnc": ident[1], "lac": ident[2], "cellid": ident[3],
            "radio": "LTE", "format": "json",
        })
        data = self._fetch(f"{API_URL}?{query}")
        try:
            result = {"lat": float(data["lat"]), "lon": float(data["lon"]),
                      "range": int(data["range"]) if data.get("range") is not None else None}
        except (KeyError, TypeError, ValueError) as exc:
            raise CellNotFound("OpenCellID has no record of this cell") from exc
        with self._lock:
            self._cache[ident] = result
        return result
