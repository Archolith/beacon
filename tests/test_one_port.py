"""One port: ``beacon serve-http`` serves the JSON API and MCP (at ``/mcp``) together.

Both surfaces answer from one provider built from one snapshot, behind one Host/Origin
guard, on one loopback port (default 3366). ``--no-mcp`` keeps the JSON API alone.
"""

from __future__ import annotations

import json
import re
import unittest.mock as mock
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from typer.testing import CliRunner

from beacon.main import DEFAULT_HTTP_PORT, app
from beacon.one_port import MCP_PATH, OnePortApp
from tests.test_adr_decisions import _adr_repo
from tests.test_e2e_no_clone_access import (  # noqa: F401  (served is a pytest fixture)
    _beacon,
    _get,
    _mcp_status_for_host,
    _start,
    _stop,
    served,
)

runner = CliRunner()


# -- dispatch ------------------------------------------------------------------------


def _recorder(name: str, seen: list[tuple[str, str]]) -> Any:
    async def asgi(scope: dict[str, Any], receive: Any, send: Any) -> None:
        seen.append((name, str(scope.get("path", scope["type"]))))

    return asgi


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ({"type": "http", "path": "/mcp"}, "mcp"),
        ({"type": "http", "path": "/mcp/"}, "mcp"),
        ({"type": "http", "path": "/mcp/session/x"}, "mcp"),
        ({"type": "http", "path": "/mcpx"}, "json"),
        ({"type": "http", "path": "/v1/search"}, "json"),
        ({"type": "http", "path": "/.well-known/archolith-beacon"}, "json"),
        ({"type": "lifespan"}, "mcp"),
    ],
)
async def test_dispatch_sends_only_mcp_paths_and_lifespan_to_mcp(
    scope: dict[str, Any], expected: str
) -> None:
    seen: list[tuple[str, str]] = []
    one_port = OnePortApp(_recorder("json", seen), _recorder("mcp", seen), MCP_PATH)
    await one_port(scope, None, None)
    assert [name for name, _ in seen] == [expected]


# -- defaults ------------------------------------------------------------------------


def test_default_port_is_3366_for_serve_http(tmp_path: Path) -> None:
    assert DEFAULT_HTTP_PORT == 3366
    root = _adr_repo(tmp_path)
    assert _beacon("build", "--repo", str(root), "--format", "json", cwd=root).returncode == 0
    with mock.patch("beacon.main._serve_http_snapshot") as run:
        result = runner.invoke(
            app, ["serve-http", "--manifest", str(root / "beacon.generated.yaml")]
        )
    assert result.exit_code == 0, result.output
    assert run.call_args.kwargs["port"] == 3366
    assert run.call_args.kwargs["mcp"] is True


# -- real processes ------------------------------------------------------------------


def test_json_and_mcp_share_one_port_and_one_guard(served: dict[str, Any]) -> None:  # noqa: F811
    base = served["http"]
    port = int(base.rsplit(":", 1)[1])
    status, body, _ = _get(base, "/.well-known/archolith-beacon")
    discovery = json.loads(body)
    assert status == 200
    assert discovery["descriptor_version"] == "1.10"
    assert discovery["capabilities"]["mcp_http"] is True
    assert discovery["mcp"]["url"] == "/mcp" and discovery["mcp"]["transport"] == "streamable-http"
    log = served["logs"][0].read_text(encoding="utf-8", errors="replace")
    assert re.search(r"Beacon HTTP ready url=http://127\.0\.0\.1:\d+ .* mcp=/mcp", log)
    # The Host/Origin guard covers /mcp on the JSON server's port too.
    assert _mcp_status_for_host(port, "evil.example") == 421
    assert _mcp_status_for_host(port, f"127.0.0.1:{port}") not in (421, 403)


async def test_mcp_on_the_json_port_answers_like_the_json_routes(served: dict[str, Any]) -> None:  # noqa: F811
    base = served["http"]
    async with Client(f"{base}/mcp", timeout=30) as client:
        tools = {tool.name for tool in await client.list_tools()}
        assert len(tools) == 7 and "beacon_search" in tools
        for tool, arguments, path, params in (
            (
                "beacon_search",
                {"query": "namespace isolation", "source_types": ["decisions"]},
                "/v1/search",
                {"q": "namespace isolation", "types": "decisions"},
            ),
            (
                "beacon_explain_concept",
                {"concept": "adr-0005"},
                "/v1/explain",
                {"concept": "adr-0005"},
            ),
        ):
            result = await client.call_tool(tool, arguments)
            _, body, _ = _get(base, path, params)
            # Same process, same provider: identical payloads.
            assert json.loads(body) == json.loads(result.content[0].text), tool


def test_no_mcp_serves_the_json_api_alone(tmp_path: Path) -> None:
    root = _adr_repo(tmp_path)
    assert _beacon("build", "--repo", str(root), "--format", "json", cwd=root).returncode == 0
    proc, ready = _start(
        [
            "serve-http",
            "--manifest",
            str(root / "beacon.generated.yaml"),
            "--docs-root",
            str(root),
            "--port",
            "0",
            "--no-mcp",
        ],
        root,
        tmp_path / "serve-http-no-mcp.log",
        re.compile(r"Beacon HTTP ready url=(http://127\.0\.0\.1:\d+)"),
    )
    try:
        base = ready.group(1)
        discovery = json.loads(_get(base, "/.well-known/archolith-beacon")[1])
        assert discovery["capabilities"]["mcp_http"] is False
        assert "mcp" not in discovery
        status, body, _ = _get(base, "/mcp")
        assert status == 404
        assert json.loads(body)["error"]["code"]
        log = (tmp_path / "serve-http-no-mcp.log").read_text(encoding="utf-8", errors="replace")
        assert "mcp=/mcp" not in log
    finally:
        _stop(proc)
