"""Black-box tests for the installed MCP stdio surface and privacy boundary."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

REPO_ROOT = Path(__file__).resolve().parents[1]


async def test_stdio_server_lists_and_calls_all_beacon_tools_without_network(
    tmp_path: Path,
) -> None:
    pytest.importorskip("archolith_mcp_framework")
    guard_dir = tmp_path / "socket-guard"
    guard_dir.mkdir()
    marker = tmp_path / "network-attempted"
    (guard_dir / "sitecustomize.py").write_text(
        """\
import os
import socket
import ipaddress
from pathlib import Path

_original_create_connection = socket.create_connection
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex

def _deny(*args, **kwargs):
    Path(os.environ["BEACON_SOCKET_GUARD_MARKER"]).write_text("blocked", encoding="utf-8")
    raise RuntimeError("outbound network disabled by Beacon test")

def _is_loopback(address):
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

def _guard_create_connection(address, *args, **kwargs):
    if _is_loopback(address):
        return _original_create_connection(address, *args, **kwargs)
    return _deny(address, *args, **kwargs)

def _guard_connect(sock, address):
    if _is_loopback(address):
        return _original_connect(sock, address)
    return _deny(sock, address)

def _guard_connect_ex(sock, address):
    if _is_loopback(address):
        return _original_connect_ex(sock, address)
    return _deny(sock, address)

socket.create_connection = _guard_create_connection
socket.socket.connect = _guard_connect
socket.socket.connect_ex = _guard_connect_ex
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    python_path = [str(guard_dir)]
    if env.get("PYTHONPATH"):
        python_path.append(env["PYTHONPATH"])
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(python_path),
            "BEACON_MANIFEST_PATH": str(REPO_ROOT / "beacon.yaml"),
            "BEACON_DOCS_ROOT": str(REPO_ROOT),
            "BEACON_SOCKET_GUARD_MARKER": str(marker),
        }
    )

    log_path = tmp_path / "beacon-stderr.log"
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "beacon"],
        env=env,
        cwd=str(REPO_ROOT),
        log_file=log_path,
    )

    expected = {
        "beacon_project_overview",
        "beacon_agent_onboarding",
        "beacon_search",
        "beacon_explain_concept",
        "beacon_guardrails",
    }
    calls = {
        "beacon_project_overview": {},
        "beacon_agent_onboarding": {"task_hint": "review tests"},
        "beacon_search": {"query": "manifest"},
        "beacon_explain_concept": {"concept": "beacon_manifest"},
        "beacon_guardrails": {"task_hint": "review tests"},
    }

    async with Client(transport, timeout=20) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert expected <= names

        for name, arguments in calls.items():
            result = await client.call_tool(name, arguments)
            assert not result.is_error, name
            payload = result.data
            if not isinstance(payload, str):
                payload = result.content[0].text  # type: ignore[union-attr]
            parsed = json.loads(payload)
            assert "status" in parsed, name
            assert "sources" in parsed, name

    assert not marker.exists(), "Beacon attempted outbound network access"
    stderr = log_path.read_text(encoding="utf-8")
    assert "Update available" not in stderr
