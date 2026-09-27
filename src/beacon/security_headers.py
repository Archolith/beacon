"""Browser-hardening response headers for every ``serve-http`` response.

A reverse proxy used to add these; behind a tunnel nothing does, so the server sets them
itself. They apply to the JSON routes, ``/mcp`` and the Host/Origin guard's own refusals.
A header the app already set is left alone.
"""

from __future__ import annotations

from beacon.loopback_guard import ASGIApp, Message, Receive, Scope, Send

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)


class SecurityHeaders:
    """ASGI wrapper that adds :data:`SECURITY_HEADERS` to HTTP responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {bytes(name).lower() for name, _ in headers}
                headers.extend(pair for pair in SECURITY_HEADERS if pair[0] not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
