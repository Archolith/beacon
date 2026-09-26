"""Parity and CLI-refusal tests for the MCP Streamable HTTP transport.

Pins Beacon issue #26 phase 1: ``beacon serve --snapshot S --transport http``
serves the same seven tools as stdio from the same snapshot, and the CLI
refuses non-loopback hosts, invalid ports, and snapshot-less HTTP serving
before anything starts.
"""

from __future__ import annotations

import http.client
import json
import socket
import subprocess
import sys
import time
import types
import unittest.mock as mock
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from typer.testing import CliRunner

from beacon.core import cli_support
from beacon.loopback_guard import host_allowed, origin_allowed
from beacon.main import app

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[1]


def _patch_server():
    """Same guard as test_snapshot_reader.py: a patched server that never starts."""
    fake_framework = types.ModuleType("archolith_mcp_framework")
    fake_framework.run_server = lambda mcp: None
    fake_server = types.ModuleType("beacon.mcp.server")
    fake_server.mcp = object()
    return mock.patch.dict(
        sys.modules,
        {
            "archolith_mcp_framework": fake_framework,
            "beacon.mcp.server": fake_server,
        },
    )


_VALID_MANIFEST = """\
beacon_version: "0.1"
project:
  name: fixture
  description: A fixture project for the snapshot reader.
  status: experimental
purpose:
  one_sentence: A fixture project for the snapshot reader.
audiences:
  - coding-agents
core_concepts:
  - id: fixture-concept
    name: Fixture concept
    definition: The one concept the fixture defines.
    status: current
    sources:
      - type: doc
        title: Read me
        path: README.md
        status: current
canonical_docs:
  - path: README.md
    role: reference
    status: current
    title: README
guardrails:
  - id: no-net
    rule: No network access is required.
    severity: low
build_and_test:
  test: pytest -q
"""


def _fixture(tmp_path: Path) -> Path:
    (tmp_path / "beacon.yaml").write_text(_VALID_MANIFEST, encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Fixture\n\n## Usage\nRun the fixture.\n", encoding="utf-8"
    )
    return tmp_path / "beacon.yaml"


def _export_snapshot(manifest_path: Path) -> Path:
    from beacon.core.snapshot import build_snapshot, write_snapshot_atomic

    snap = build_snapshot(manifest_path, docs_root=manifest_path.parent)
    out = manifest_path.parent / "beacon.snapshot.json"
    write_snapshot_atomic(out, snap)
    return out


def _payload(result: Any) -> Any:
    """The parsed JSON payload of a tool result, whatever shape the client gave."""
    payload = result.data
    if not isinstance(payload, str):
        payload = result.content[0].text
    return json.loads(payload)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _raw_post(port: int, *, host: str, origin: str | None = None) -> int:
    """POST an MCP initialize with an explicit Host (and Origin); return the status."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0"},
            },
        }
    ).encode()
    headers = {
        "Host": host,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if origin is not None:
        headers["Origin"] = origin
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest("POST", "/mcp", skip_host=True)
        for key, value in {**headers, "Content-Length": str(len(body))}.items():
            conn.putheader(key, value)
        conn.endheaders(body)
        response = conn.getresponse()
        response.read()
        return response.status
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("127.0.0.1", True),
        ("127.0.0.1:8766", True),
        ("LOCALHOST:8766", True),
        ("evil.example", False),
        ("evil.example:8766", False),
        ("127.0.0.1.evil.example", False),
        ("user@127.0.0.1", False),
        ("[::1]:8766", False),
        ("", False),
        (None, False),
    ],
)
def test_loopback_guard_host(host: str | None, allowed: bool) -> None:
    assert host_allowed(host) is allowed


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        (None, True),
        ("http://127.0.0.1:8766", True),
        ("http://localhost", True),
        ("https://127.0.0.1:8766", False),
        ("http://evil.example", False),
        ("http://127.0.0.1.evil.example", False),
        ("null", False),
        ("", False),
    ],
)
def test_loopback_guard_origin(origin: str | None, allowed: bool) -> None:
    assert origin_allowed(origin) is allowed


def test_http_transport_bind_failure_is_a_clean_refusal(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    snapshot_path = _export_snapshot(manifest)
    fake_server = types.ModuleType("beacon.mcp.server")
    fake_server.mcp = types.SimpleNamespace(http_app=lambda **_: object())
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy,
        mock.patch.dict(sys.modules, {"beacon.mcp.server": fake_server}),
    ):
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = busy.getsockname()[1]
        result = runner.invoke(
            app,
            ["serve", "--snapshot", str(snapshot_path), "--transport", "http", "--port", str(port)],
        )
    assert result.exit_code == cli_support.EXIT_INPUT
    assert "http_bind_failed" in result.stderr


def _start_http_server(snapshot_path: Path, log_path: Path) -> tuple[Any, int]:
    """Start ``serve --transport http`` on a free port; ready means its own ready line.

    ``serve --transport http`` refuses port 0, so a picked port can be taken before the
    bind; a start that fails with ``http_bind_failed`` is retried on a new port.
    """
    for _attempt in range(3):
        port = _free_loopback_port()
        with log_path.open("wb") as log_file:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "beacon",
                    "serve",
                    "--snapshot",
                    str(snapshot_path),
                    "--transport",
                    "http",
                    "--port",
                    str(port),
                ],
                cwd=str(REPO_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=log_file,
            )
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            if "MCP http listening" in text and proc.poll() is None:
                return proc, port
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)
        text = log_path.read_text(encoding="utf-8", errors="replace")
        if "http_bind_failed" not in text:
            raise AssertionError("http server not ready: " + text[-2000:])
    raise AssertionError("http server could not bind a free port in 3 attempts")


async def test_http_transport_matches_stdio_on_all_seven_tools(tmp_path: Path) -> None:
    pytest.importorskip("archolith_mcp_framework")
    manifest = _fixture(tmp_path)
    snapshot_path = _export_snapshot(manifest)
    log_path = tmp_path / "beacon-http-stderr.log"
    http_proc, port = _start_http_server(snapshot_path, log_path)
    try:
        expected = {
            "beacon_project_overview",
            "beacon_agent_onboarding",
            "beacon_search",
            "beacon_explain_concept",
            "beacon_guardrails",
            "beacon_catalog",
            "beacon_read",
        }
        calls = {
            "beacon_project_overview": {},
            "beacon_agent_onboarding": {"task_hint": "review tests"},
            "beacon_search": {"query": "fixture"},
            "beacon_explain_concept": {"concept": "fixture-concept"},
            "beacon_guardrails": {"task_hint": "review tests"},
            "beacon_catalog": {},
            "beacon_read": {"path": "README.md"},
        }

        stdio_transport = StdioTransport(
            command=sys.executable,
            args=["-m", "beacon", "serve", "--snapshot", str(snapshot_path)],
            cwd=str(REPO_ROOT),
        )
        async with Client(stdio_transport, timeout=20) as stdio_client:
            async with Client(f"http://127.0.0.1:{port}/mcp", timeout=20) as http_client:
                stdio_tools = {tool.name for tool in await stdio_client.list_tools()}
                http_tools = {tool.name for tool in await http_client.list_tools()}
                assert stdio_tools == expected
                assert http_tools == expected

                for name, arguments in calls.items():
                    stdio_result = await stdio_client.call_tool(name, arguments)
                    http_result = await http_client.call_tool(name, arguments)
                    assert not stdio_result.is_error, name
                    assert not http_result.is_error, name
                    payload = _payload(stdio_result)
                    # Tool errors come back as {"ok": false, ...} with is_error False.
                    assert not (isinstance(payload, dict) and payload.get("ok") is False), (
                        name,
                        payload,
                    )
                    assert _payload(http_result) == payload, name

        # DNS rebinding: a foreign Host or browser Origin is refused before MCP runs.
        assert _raw_post(port, host="evil.example") == 421
        assert _raw_post(port, host=f"evil.example:{port}") == 421
        assert _raw_post(port, host=f"127.0.0.1:{port}", origin="http://evil.example") == 403
        assert _raw_post(port, host=f"localhost:{port}", origin="null") == 403
        assert _raw_post(port, host=f"127.0.0.1:{port}") not in (421, 403)
        assert _raw_post(port, host=f"127.0.0.1:{port}", origin=f"http://localhost:{port}") not in (
            421,
            403,
        )
    finally:
        http_proc.terminate()
        http_proc.wait(timeout=10)


def test_http_transport_cli_refusals(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    snapshot_path = _export_snapshot(manifest)

    with _patch_server():
        result = runner.invoke(
            app,
            [
                "serve",
                "--snapshot",
                str(snapshot_path),
                "--transport",
                "http",
                "--host",
                "0.0.0.0",
            ],
        )
        assert result.exit_code == cli_support.EXIT_INPUT
        assert "http_host_not_loopback" in result.stderr

        result = runner.invoke(
            app,
            ["serve", "--snapshot", str(snapshot_path), "--transport", "http", "--port", "0"],
        )
        assert result.exit_code == cli_support.EXIT_INPUT
        assert "http_port_invalid" in result.stderr

        result = runner.invoke(app, ["serve", "--transport", "http"])
        assert result.exit_code == cli_support.EXIT_INPUT
        assert "serve_http_requires_snapshot" in result.stderr

        # If the gate regressed this must fail, not start a real server and hang.
        with mock.patch(
            "beacon.main._serve_http_snapshot", side_effect=AssertionError("server started")
        ):
            result = runner.invoke(app, ["serve-http", "--host", "0.0.0.0"])
        assert result.exit_code == cli_support.EXIT_INPUT
        assert "http_host_not_loopback" in result.stderr

        result = runner.invoke(
            app, ["serve", "--snapshot", str(snapshot_path), "--transport", "bogus"]
        )
        assert result.exit_code == cli_support.EXIT_INPUT
        assert "transport" in result.stderr
