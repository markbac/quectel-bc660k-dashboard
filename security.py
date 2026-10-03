"""Request checks that keep the local dashboard API from being driven by other sites.

The server only listens on the loopback interface, but a web page open in the
same browser can still send requests to it, directly or through DNS
rebinding. This ASGI middleware refuses HTTP and WebSocket requests whose
``Host`` or ``Origin`` is not the local machine.
"""
from typing import Iterable, Optional
from urllib.parse import urlsplit

ALLOWED_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})


def hostname_of(host_header: str) -> str:
    """Return the host name part of a ``Host`` header value, lower-cased."""
    host = host_header.strip().lower()
    if host.startswith("["):  # IPv6 literal, possibly with a port
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    return host.split(":", 1)[0]


def port_of(host_header: str) -> Optional[int]:
    """Return the port in a ``Host`` header value, or ``None`` if absent or invalid."""
    host = host_header.strip()
    tail = host[host.find("]") + 1:] if host.startswith("[") else host[host.find(":"):] if ":" in host else ""
    if not tail.startswith(":") or not tail[1:].isdigit():
        return None
    return int(tail[1:])


def origin_allowed(origin: str, allowed: Iterable[str] = ALLOWED_HOSTNAMES,
                   port: Optional[int] = None) -> bool:
    """True if an ``Origin`` header value names the local machine.

    :param port: if given, the origin must also use this TCP port (the default
        port of the scheme when the origin names none).
    """
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    hostname = parts.hostname.lower()
    if hostname not in allowed and f"[{hostname}]" not in allowed:
        return False
    if port is None:
        return True
    try:
        origin_port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False
    return origin_port == port


class LocalOnlyMiddleware:
    """ASGI middleware that rejects foreign ``Host`` and ``Origin`` headers."""

    def __init__(self, app, allowed_hostnames: Iterable[str] = ALLOWED_HOSTNAMES,
                 port: Optional[int] = None):
        self.app = app
        self.allowed = frozenset(allowed_hostnames)
        self.port = port

    @staticmethod
    def _header(scope, name: bytes) -> Optional[str]:
        for key, value in scope.get("headers", []):
            if key == name:
                return value.decode("latin-1")
        return None

    def _permitted(self, scope) -> bool:
        host = self._header(scope, b"host")
        if host is None or hostname_of(host) not in self.allowed:
            return False
        if self.port is not None and port_of(host) not in (None, self.port):
            return False
        origin = self._header(scope, b"origin")
        # A missing Origin means a non-browser client (curl, scripts).
        return origin is None or origin_allowed(origin, self.allowed, self.port)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or self._permitted(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = b'{"detail":"Forbidden: unexpected Host or Origin"}'
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
