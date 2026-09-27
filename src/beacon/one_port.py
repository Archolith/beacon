"""One loopback port for both HTTP surfaces: the JSON API and MCP over Streamable HTTP.

``beacon serve-http`` mounts Beacon's MCP server at ``/mcp`` beside the JSON routes. Both
answer from the same provider (built once from the same snapshot) and sit behind the same
``LoopbackGuard``. The dispatch is a plain ASGI split rather than a Starlette ``Mount`` so
the FastMCP app keeps its own middleware and session-manager lifespan intact.
"""

from __future__ import annotations

from typing import Any

from beacon.loopback_guard import ASGIApp, Receive, Scope, Send

#: The path the MCP endpoint answers on (Streamable HTTP).
MCP_PATH = "/mcp"


class OnePortApp:
    """Send ``/mcp`` (and ``/mcp/...``) to the MCP app and every other path to the JSON app.

    Lifespan events go to the MCP app, whose session manager must start and stop with the
    server; the JSON app is a static Starlette app with no lifespan work of its own.
    """

    def __init__(self, json_app: ASGIApp, mcp_app: ASGIApp, mcp_path: str = MCP_PATH) -> None:
        self.json_app = json_app
        self.mcp_app = mcp_app
        self.mcp_path = mcp_path.rstrip("/")

    def _is_mcp(self, path: str) -> bool:
        return path == self.mcp_path or path.startswith(self.mcp_path + "/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope.get("type")
        if kind == "lifespan":
            await self.mcp_app(scope, receive, send)
        elif kind in ("http", "websocket") and self._is_mcp(str(scope.get("path", ""))):
            await self.mcp_app(scope, receive, send)
        else:
            await self.json_app(scope, receive, send)


def build_mcp_app(provider: Any, mcp_path: str = MCP_PATH) -> ASGIApp:
    """A Streamable HTTP ASGI app for Beacon's seven tools, answering from *provider*."""
    from beacon.mcp.server import create_mcp_server

    server = create_mcp_server(provider=provider)
    # Beacon's LoopbackGuard wraps this app; fastmcp's own guard stays off explicitly so a
    # FASTMCP_HTTP_HOST_ORIGIN_PROTECTION setting cannot refuse container-mode allowed hosts.
    app: ASGIApp = server.http_app(path=mcp_path, transport="http", host_origin_protection=False)
    return app
