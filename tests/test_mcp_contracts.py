"""Security-focused tests for the shared MCP tool contract."""

from __future__ import annotations

import json

from beacon.core.limits import LIMIT_QUERY_BYTES, LimitError
from beacon.mcp.contracts import BeaconBaseTool


class _FailingTool(BeaconBaseTool):
    name = "test_failure"
    description = "Test-only failing tool."

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def endpoint(self) -> str:
        raise self.error


async def test_unexpected_tool_error_does_not_leak_exception_text() -> None:
    secret = "C:/private/internal/path token=do-not-leak"
    payload = json.loads(await _FailingTool(RuntimeError(secret)).execute())

    assert payload["error"]["code"] == "internal_error"
    assert secret not in json.dumps(payload)


async def test_limit_error_preserves_stable_public_diagnostic() -> None:
    error = LimitError(
        LIMIT_QUERY_BYTES,
        "resource limit exceeded: limit_query_bytes",
        limit="query_bytes",
        limit_value=4096,
    )
    payload = json.loads(await _FailingTool(error).execute())

    assert payload["error"] == {
        "code": LIMIT_QUERY_BYTES,
        "message": "resource limit exceeded: limit_query_bytes",
    }


async def test_public_tool_surface_is_exactly_the_seven_beacon_tools() -> None:
    """The plain FastMCP server exposes exactly the seven Beacon tools.

    Guards against the Archolith gateway adding ``call_tool``/``search_tools``
    meta-tools or any transform-based tool appearing on the public surface.
    """
    from beacon.mcp.server import mcp

    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "beacon_project_overview",
        "beacon_agent_onboarding",
        "beacon_search",
        "beacon_explain_concept",
        "beacon_guardrails",
        "beacon_catalog",
        "beacon_read",
    }
