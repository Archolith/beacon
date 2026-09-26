"""Host/Origin guard for loopback HTTP servers (blocks DNS-rebinding requests).

Binding 127.0.0.1 keeps other machines out, but a web page in the user's browser can
still reach the port through DNS rebinding: the request arrives from loopback with a
foreign ``Host`` (and ``Origin``). This ASGI wrapper refuses those before the app runs.
It is local rather than fastmcp's ``host_origin_protection`` because the supported
fastmcp floor (3.2.4) lacks that option.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import urlsplit

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost"})


def _hostname(value: str) -> str | None:
    """Lower-case host name of a ``Host`` header value, without its port."""
    value = value.strip().lower()
    if not value or "@" in value or "/" in value:
        return None
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else None
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def host_allowed(host: str | None) -> bool:
    return host is not None and _hostname(host) in LOOPBACK_NAMES


def origin_allowed(origin: str | None) -> bool:
    """No Origin (non-browser client) is fine; a browser Origin must be loopback http."""
    if origin is None:
        return True
    try:
        parts = urlsplit(origin.strip())
    except ValueError:
        return False
    return parts.scheme == "http" and (parts.hostname or "") in LOOPBACK_NAMES


def _header(scope: Scope, name: bytes) -> str | None:
    values = [v for k, v in scope.get("headers") or () if k.lower() == name]
    if len(values) != 1:
        return None if not values else "\x00"  # duplicated header: never allowed
    return bytes(values[0]).decode("latin-1")


class LoopbackGuard:
    """Refuse HTTP/WebSocket requests whose Host (421) or Origin (403) is not loopback."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if not host_allowed(_header(scope, b"host")):
            await _refuse(scope, send, 421, b"Misdirected Request")
            return
        if not origin_allowed(_header(scope, b"origin")):
            await _refuse(scope, send, 403, b"Forbidden Origin")
            return
        await self.app(scope, receive, send)


async def _refuse(scope: Scope, send: Send, status: int, body: bytes) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
