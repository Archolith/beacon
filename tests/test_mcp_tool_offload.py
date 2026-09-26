"""MCP tool work runs off the transport's event loop (MCP over HTTP and stdio alike).

``BeaconBaseTool.execute`` runs the synchronous provider call on a worker thread, so one slow
tool call cannot stall other calls or the MCP session on the same loop.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import anyio
import anyio.to_thread
import pytest
from fastmcp import Client, FastMCP

from beacon.core.snapshot import Snapshot
from beacon.mcp import contracts
from beacon.mcp.tools.guardrails import GuardrailsTool
from beacon.mcp.tools.search import SearchTool
from beacon.provider.manifest_provider import ManifestBeaconProvider
from tests.test_http_api_dynamic import repo, snapshot  # noqa: F401  (pytest fixtures)


async def test_a_slow_tool_call_does_not_block_another(
    snapshot: Snapshot,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ManifestBeaconProvider.from_snapshot(snapshot)
    real_search = provider.search
    entered, release = threading.Event(), threading.Event()

    def blocked_search(**kwargs: Any) -> Any:
        entered.set()
        assert release.wait(30), "the test never released the search"
        return real_search(**kwargs)

    provider.search = blocked_search  # type: ignore[method-assign]
    monkeypatch.setattr(contracts, "get_provider", lambda: provider)
    server = FastMCP("offload-test")
    SearchTool().register(server)
    GuardrailsTool().register(server)

    async with Client(server) as client:
        search = asyncio.create_task(
            client.call_tool("beacon_search", {"query": "namespace isolation"})
        )
        # Synchronized, not timed: the second call must finish while the first is provably
        # inside the provider, which only happens if the provider runs off the event loop.
        assert await anyio.to_thread.run_sync(entered.wait, 30)
        with anyio.fail_after(10):  # a hang guard; a blocked loop never gets here
            guardrails = await client.call_tool("beacon_guardrails", {})
        assert json.loads(guardrails.content[0].text).get("ok") is not False
        assert not search.done()
        release.set()
        result = await search
    payload = json.loads(result.content[0].text)
    assert payload.get("ok") is not False and payload["results"], payload
