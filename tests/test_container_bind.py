"""Container mode for ``serve-http``: a non-loopback bind behind an exact allowed-host list.

The loopback default must not change: without ``--allowed-host`` only 127.0.0.1 binds and
only loopback Host names pass. With it, the bind may be any IPv4 address, the guard admits
loopback names plus exactly the listed names (421 otherwise), foreign browser Origins stay
403, and discovery reports ``scope: container``.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import re
import unittest.mock as mock
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from beacon.loopback_guard import LoopbackGuard, host_allowed, normalize_allowed_hosts
from beacon.main import app
from tests.test_adr_decisions import _adr_repo
from tests.test_e2e_no_clone_access import _beacon, _start, _stop

runner = CliRunner()


# -- allowed-host validation -----------------------------------------------------------


def test_allowed_hosts_are_normalized_exact_names() -> None:
    assert normalize_allowed_hosts(["Beacon.Archolith.DEV.", "beacon-prod-app"]) == frozenset(
        {"beacon.archolith.dev", "beacon-prod-app"}
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "*",
        "*.archolith.dev",
        "beacon.*",
        "a b",
        "exa_mple.dev",
        "-x.dev",
        "x-.dev",
        "beacon.dev:443",
        "http://beacon.dev",
        "10.0.0.1",
        "[::1]",
        "a..b",
        "a" * 64 + ".dev",
        "x\n.y\n.z",
        "beacon.dev\n.x",
        "localhost",
        "localhost.",
        "127.0.0.1",
        "0x7f000001",
        "0x7f.0.0.1",
        "beacon.123",
        "beacon.0x10",
    ],
)
def test_invalid_allowed_hosts_are_refused(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_allowed_hosts([value])


def test_host_matching_is_exact() -> None:
    allowed = normalize_allowed_hosts(["beacon.archolith.dev"])
    for host in (
        "beacon.archolith.dev",
        "beacon.archolith.dev:443",
        "BEACON.archolith.dev",
        "beacon.archolith.dev.",
        "127.0.0.1:3366",
        "localhost",
    ):
        assert host_allowed(host, allowed), host
    for host in (
        "evil.archolith.dev",
        "beacon.archolith.dev.evil.com",
        "xbeacon.archolith.dev",
        "archolith.dev",
        "",
        "beacon.archolith.dev@evil.com",
        "beacon.archolith.dev..",
        "beacon.archolith.dev:443:1",
        "beacon.archolith.dev:abc",
        "beacon.archolith.dev:99999",
        "beacon.archolith.dev:0",
        "beacon.archolith.dev:",
        "[beacon.archolith.dev]junk",
        None,
    ):
        assert not host_allowed(host, allowed), host
    assert not host_allowed("beacon.archolith.dev")  # default: loopback names only
    assert not host_allowed("127.0.0.1:abc")  # port must be decimal 1-65535 in both modes


def test_real_dns_names_with_hex_looking_tlds_stay_valid() -> None:
    assert normalize_allowed_hosts(["demo.cafe", "beacon.dev"]) == frozenset(
        {"demo.cafe", "beacon.dev"}
    )


def test_a_bare_string_is_not_a_host_list() -> None:
    with pytest.raises(TypeError):
        normalize_allowed_hosts("beacon")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        LoopbackGuard(_ok_app, allowed_hosts="beacon")


# -- guard (ASGI) ----------------------------------------------------------------------


async def _status(guard: LoopbackGuard, headers: dict[str, str]) -> int:
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    await guard(scope, None, send)  # type: ignore[arg-type]
    return int(sent[0]["status"])


async def _ok_app(scope: Any, receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def test_container_guard_admits_only_listed_hosts_and_keeps_origin_rule() -> None:
    guard = LoopbackGuard(_ok_app, allowed_hosts=["beacon.archolith.dev"])
    assert await _status(guard, {"Host": "beacon.archolith.dev"}) == 200
    assert await _status(guard, {"Host": "127.0.0.1:3366"}) == 200
    assert await _status(guard, {"Host": "evil.example"}) == 421
    assert await _status(guard, {}) == 421
    assert (
        await _status(guard, {"Host": "beacon.archolith.dev", "Origin": "https://evil.example"})
        == 403
    )
    assert (
        await _status(
            guard, {"Host": "beacon.archolith.dev", "Origin": "https://beacon.archolith.dev"}
        )
        == 403
    )


async def test_default_guard_is_unchanged() -> None:
    guard = LoopbackGuard(_ok_app)
    assert await _status(guard, {"Host": "127.0.0.1:3366"}) == 200
    assert await _status(guard, {"Host": "beacon.archolith.dev"}) == 421


async def test_duplicate_host_headers_are_refused_in_both_modes() -> None:
    for guard in (LoopbackGuard(_ok_app), LoopbackGuard(_ok_app, allowed_hosts=["b.example"])):
        sent: list[dict[str, Any]] = []

        async def send(message: dict[str, Any], sent: list[dict[str, Any]] = sent) -> None:
            sent.append(message)

        scope = {"type": "http", "headers": [(b"host", b"127.0.0.1"), (b"host", b"b.example")]}
        await guard(scope, None, send)  # type: ignore[arg-type]
        assert sent[0]["status"] == 421


def test_unknown_discovery_scope_is_refused() -> None:
    from types import SimpleNamespace

    from beacon.http_api import CONTENT_EMBEDDED, create_http_app

    with pytest.raises(ValueError, match="scope"):
        create_http_app(SimpleNamespace(content_mode=CONTENT_EMBEDDED), scope="bogus")  # type: ignore[arg-type]


def test_guard_refuses_invalid_allowed_hosts_at_construction() -> None:
    with pytest.raises(ValueError):
        LoopbackGuard(_ok_app, allowed_hosts=["*"])


# -- CLI bind rules --------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = _adr_repo(tmp_path_factory.mktemp("container-bind"))
    built = _beacon("build", "--repo", str(root), "--format", "json", cwd=root)
    assert built.returncode == 0, built.stdout + built.stderr
    return root / "beacon.generated.yaml"


def _invoke(manifest: Path, *args: str) -> Any:
    with mock.patch("beacon.main._serve_http_snapshot") as run:
        result = runner.invoke(app, ["serve-http", "--manifest", str(manifest), *args])
    return result, run


def test_non_loopback_bind_without_allowed_host_is_refused(manifest: Path) -> None:
    result, run = _invoke(manifest, "--host", "0.0.0.0")
    assert result.exit_code != 0
    assert "http_host_not_loopback" in result.output
    run.assert_not_called()


def test_container_mode_needs_an_ipv4_literal_and_valid_names(manifest: Path) -> None:
    result, run = _invoke(manifest, "--host", "beacon.local", "--allowed-host", "beacon.dev")
    assert result.exit_code != 0 and "http_host_invalid" in result.output
    run.assert_not_called()
    result, run = _invoke(manifest, "--host", "0.0.0.0", "--allowed-host", "*")
    assert result.exit_code != 0 and "http_allowed_host_invalid" in result.output
    run.assert_not_called()
    result, run = _invoke(manifest, "--host", "0.0.0.0", "--allowed-host", "localhost")
    assert result.exit_code != 0 and "http_allowed_host_invalid" in result.output
    run.assert_not_called()


@pytest.mark.parametrize(
    "host",
    ["8.8.8.8", "147.93.132.141", "224.0.0.1", "255.255.255.255", "169.254.1.1", "100.64.0.1"],
)
def test_container_mode_refuses_non_private_binds(manifest: Path, host: str) -> None:
    result, run = _invoke(manifest, "--host", host, "--allowed-host", "beacon.dev", "--port", "0")
    assert result.exit_code != 0 and "http_host_not_private" in result.output
    run.assert_not_called()


@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1", "10.1.2.3", "172.20.0.5", "192.168.1.1"])
def test_container_mode_accepts_private_binds(manifest: Path, host: str) -> None:
    result, run = _invoke(manifest, "--host", host, "--allowed-host", "beacon.dev", "--port", "0")
    assert result.exit_code == 0, result.output
    assert run.call_args.kwargs["host"] == host


@pytest.mark.parametrize("port", ["70000", "-1"])
def test_container_mode_still_checks_the_port_range(manifest: Path, port: str) -> None:
    result, run = _invoke(
        manifest, "--host", "0.0.0.0", "--allowed-host", "beacon.dev", "--port", port
    )
    assert result.exit_code != 0 and "http_port_invalid" in result.output
    run.assert_not_called()


def test_container_mode_passes_normalized_hosts(manifest: Path) -> None:
    result, run = _invoke(
        manifest, "--host", "0.0.0.0", "--allowed-host", "Beacon.Archolith.dev", "--port", "0"
    )
    assert result.exit_code == 0, result.output
    assert run.call_args.kwargs["host"] == "0.0.0.0"
    assert run.call_args.kwargs["allowed_hosts"] == frozenset({"beacon.archolith.dev"})


def test_default_passes_no_allowed_hosts(manifest: Path) -> None:
    result, run = _invoke(manifest, "--port", "0")
    assert result.exit_code == 0, result.output
    assert run.call_args.kwargs["allowed_hosts"] == frozenset()


# -- real process ----------------------------------------------------------------------


def _request(port: int, method: str, path: str, host: str) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        conn.putrequest(method, path, skip_host=True)
        conn.putheader("Host", host)
        conn.endheaders()
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def test_container_mode_process_serves_allowed_host_only(manifest: Path, tmp_path: Path) -> None:
    proc, ready = _start(
        [
            "serve-http",
            "--manifest",
            str(manifest),
            "--host",
            "0.0.0.0",
            "--port",
            "0",
            "--allowed-host",
            "beacon.example.org",
        ],
        manifest.parent,
        tmp_path / "serve.log",
        re.compile(
            r"Beacon HTTP ready url=http://0\.0\.0\.0:(\d+) .*allowed_hosts=beacon\.example\.org"
        ),
    )
    try:
        port = int(ready.group(1))
        status, body = _request(port, "GET", "/.well-known/archolith-beacon", "beacon.example.org")
        assert status == 200
        assert json.loads(body)["scope"] == "container"
        assert _request(port, "GET", "/healthz", "evil.example.org")[0] == 421
        assert _request(port, "GET", "/healthz", f"127.0.0.1:{port}")[0] == 200
        assert _request(port, "POST", "/mcp", "evil.example.org")[0] == 421
        assert asyncio.run(_mcp_tool_count(port, "beacon.example.org")) == 7
    finally:
        _stop(proc)


async def _mcp_tool_count(port: int, host: str) -> int:
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    transport = StreamableHttpTransport(f"http://127.0.0.1:{port}/mcp", headers={"Host": host})
    async with Client(transport) as client:
        return len(await client.list_tools())


def test_allowed_host_with_loopback_bind_reports_loopback_scope(
    manifest: Path, tmp_path: Path
) -> None:
    proc, ready = _start(
        [
            "serve-http",
            "--manifest",
            str(manifest),
            "--port",
            "0",
            "--allowed-host",
            "beacon.example.org",
        ],
        manifest.parent,
        tmp_path / "serve.log",
        re.compile(r"Beacon HTTP ready url=http://127\.0\.0\.1:(\d+) .*allowed_hosts="),
    )
    try:
        port = int(ready.group(1))
        status, body = _request(port, "GET", "/.well-known/archolith-beacon", "beacon.example.org")
        assert status == 200 and json.loads(body)["scope"] == "loopback"
        assert _request(port, "GET", "/healthz", "evil.example.org")[0] == 421
    finally:
        _stop(proc)


def test_default_process_reports_loopback_scope(manifest: Path, tmp_path: Path) -> None:
    proc, ready = _start(
        ["serve-http", "--manifest", str(manifest), "--port", "0"],
        manifest.parent,
        tmp_path / "serve.log",
        re.compile(r"Beacon HTTP ready url=http://127\.0\.0\.1:(\d+)"),
    )
    try:
        port = int(ready.group(1))
        assert "allowed_hosts=" not in (tmp_path / "serve.log").read_text(encoding="utf-8")
        status, body = _request(port, "GET", "/.well-known/archolith-beacon", "127.0.0.1")
        assert status == 200 and json.loads(body)["scope"] == "loopback"
        assert _request(port, "GET", "/healthz", "beacon.example.org")[0] == 421
    finally:
        _stop(proc)
