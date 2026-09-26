"""Static safety checks for the shipped deployment configs (issue #26, phase 4).

The deployment story is documentation and config: the servers stay loopback-only
and the proxy carries TLS, method limits, rate limits, the required upstream
Host rewrite for MCP, and a query-free access-log format. These checks pin the
safety-critical settings in ``deploy/`` so later edits cannot silently drop
them, and prove that the nginx Host rewrite matches what ``LoopbackGuard``
accepts.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from beacon.loopback_guard import LoopbackGuard

REPO_ROOT = Path(__file__).resolve().parents[1]
NGINX_CONF = REPO_ROOT / "deploy" / "nginx" / "beacon.conf"
CADDYFILE = REPO_ROOT / "deploy" / "caddy" / "Caddyfile"
HTTP_UNIT = REPO_ROOT / "deploy" / "systemd" / "beacon-http.service"
MCP_UNIT = REPO_ROOT / "deploy" / "systemd" / "beacon-mcp.service"

#: Tokens that would smuggle the query string into an access log.
QUERY_LOG_TOKENS = (
    r"\$request\b",
    r"\$request_uri\b",
    r"\$args\b",
    r"\$query_string\b",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing deployment config: {path}"
    return path.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """Drop whole-line ``#`` comments (nginx, Caddy, and systemd comment syntax)."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _brace_block(text: str, opener: re.Pattern[str]) -> str:
    """Return the ``{...}`` block whose header matches *opener*, braces matched."""
    match = opener.search(text)
    assert match, f"no block matches {opener.pattern!r}"
    depth = 0
    for pos in range(match.end() - 1, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start() : pos + 1]
    raise AssertionError(f"unbalanced braces after {opener.pattern!r}")


def _nginx_mcp_location() -> str:
    return _brace_block(_read(NGINX_CONF), re.compile(r"location\s+/mcp\s*\{"))


# --- nginx -----------------------------------------------------------------


def test_nginx_mcp_location_rewrites_host_to_loopback() -> None:
    rewrite = re.search(r"proxy_set_header\s+Host\s+(\S+);", _nginx_mcp_location())
    assert rewrite, "the /mcp location must set an explicit upstream Host"
    assert rewrite.group(1) == "127.0.0.1:8766"


def test_nginx_mcp_location_streams_unbuffered() -> None:
    mcp = _nginx_mcp_location()
    assert re.search(r"proxy_buffering\s+off\s*;", mcp), (
        "buffered responses stall Server-Sent Events"
    )
    assert re.search(r"proxy_read_timeout\s+\d+s\s*;", mcp), (
        "idle event streams need a long read timeout"
    )


def test_nginx_upstreams_are_loopback_only() -> None:
    conf = _strip_comments(_read(NGINX_CONF))
    passes = re.findall(r"proxy_pass\s+https?://([^/;\s]+)", conf)
    assert passes, "the config must proxy to the two Beacon upstreams"
    hosts = {target.rsplit(":", 1)[0] for target in passes}
    ports = {target.rsplit(":", 1)[1] for target in passes}
    assert hosts == {"127.0.0.1"}, f"non-loopback upstreams: {sorted(hosts)}"
    assert ports == {"8765", "8766"}, f"unexpected upstream ports: {sorted(ports)}"
    assert "0.0.0.0" not in conf


def test_nginx_access_log_format_omits_query_string() -> None:
    conf = _read(NGINX_CONF)
    formats = re.findall(r"log_format\s+\S+[^;]*;", conf, flags=re.DOTALL)
    assert formats, "the config must define its own log format"
    joined = "\n".join(formats)
    assert re.search(r"\$uri\b", joined), "log format should carry the path via $uri"
    # The query-carrying variables stay out of everything that writes a log.
    # (The HTTP->HTTPS redirect's `return ... $request_uri` echoes the query
    # into the Location header, not into a log, so it is out of scope here.)
    logged = "\n".join(formats + re.findall(r"access_log\s+[^;]*;", conf))
    for token in QUERY_LOG_TOKENS:
        assert not re.search(token, logged), (
            f"log directives must not use {token} — it includes the query string"
        )
    servers = re.findall(r"access_log\s+\S+\s+(\w+)\s*;", conf)
    assert servers and all(name == "beacon_no_query" for name in servers), (
        "every access_log must use the query-free format"
    )


def test_nginx_rate_limits_cover_search_and_mcp() -> None:
    conf = _strip_comments(_read(NGINX_CONF))
    search = _brace_block(conf, re.compile(r"location\s+=\s+/v1/search\s*\{"))
    mcp = _brace_block(conf, re.compile(r"location\s+/mcp\s*\{"))
    search_zone = re.search(r"limit_req\s+zone=(\S+)", search)
    mcp_zone = re.search(r"limit_req\s+zone=(\S+)", mcp)
    assert search_zone, "the exact /v1/search location must carry a limit_req"
    assert mcp_zone, "the /mcp location must carry a limit_req"
    assert search_zone.group(1).split()[0] != mcp_zone.group(1).split()[0], (
        "/v1/search must use its own, stricter zone, not the /mcp zone"
    )


def test_nginx_limits_request_body_size() -> None:
    match = re.search(r"client_max_body_size\s+(\S+)\s*;", _read(NGINX_CONF))
    assert match, "the config must set client_max_body_size"


def test_nginx_adds_no_cors_header() -> None:
    assert "access-control-allow-origin" not in _read(NGINX_CONF).lower()


# --- systemd units ---------------------------------------------------------


def test_systemd_units_bind_loopback_only() -> None:
    for unit in (HTTP_UNIT, MCP_UNIT):
        text = _read(unit)
        assert "0.0.0.0" not in text, f"{unit.name} must not bind 0.0.0.0"
        for host in re.findall(r"--host\s+(\S+)", text):
            assert host == "127.0.0.1", f"{unit.name} --host must be 127.0.0.1"


def test_systemd_units_leave_served_content_read_only() -> None:
    # StateDirectory= would make the content dir writable despite ProtectSystem=strict,
    # and a writable child mount escapes ReadOnlyPaths (astra review, PR #28).
    for unit in (HTTP_UNIT, MCP_UNIT):
        text = _strip_comments(_read(unit))
        assert "StateDirectory" not in text, unit.name
        assert "ReadWritePaths" not in text, unit.name
        assert re.search(r"^ProtectSystem=strict$", text, re.MULTILINE), unit.name
        assert re.search(r"^ReadOnlyPaths=/var/lib/beacon$", text, re.MULTILINE), unit.name


def test_nginx_rate_limit_refusals_stay_out_of_the_error_log() -> None:
    # limit_req refusals log the request line (query included); warn < error keeps them out.
    text = _strip_comments(_read(NGINX_CONF))
    assert re.search(r"^\s*limit_req_log_level\s+warn;", text, re.MULTILINE)
    levels = re.findall(r"^\s*error_log\s+\S+\s+(\w+);", text, re.MULTILINE)
    assert levels and all(level in ("error", "crit", "alert", "emerg") for level in levels)


def test_systemd_units_keep_default_ports() -> None:
    for unit, default in ((HTTP_UNIT, "8765"), (MCP_UNIT, "8766")):
        for port in re.findall(r"--port\s+(\S+)", _read(unit)):
            assert port == default, f"{unit.name} must keep the default port {default}"


def test_systemd_units_run_the_documented_servers() -> None:
    http_exec = re.search(r"^ExecStart=(.+)$", _read(HTTP_UNIT), re.MULTILINE)
    assert http_exec and " serve-http" in http_exec.group(1)
    mcp_exec = re.search(r"^ExecStart=(.+)$", _read(MCP_UNIT), re.MULTILINE)
    assert mcp_exec, "beacon-mcp.service must carry an ExecStart"
    for fragment in (" serve ", "--snapshot", "--transport http"):
        assert fragment in mcp_exec.group(1), (
            f"beacon-mcp.service ExecStart must contain {fragment!r}"
        )


# --- Caddyfile -------------------------------------------------------------


def test_caddy_rewrites_host_for_the_mcp_upstream() -> None:
    conf = _read(CADDYFILE)
    mcp = _brace_block(conf, re.compile(r"handle\s+/mcp\*\s*\{"))
    assert "reverse_proxy 127.0.0.1:8766" in mcp, "the /mcp upstream must be 8766"
    assert re.search(r"header_up\s+Host\s+\{upstream_hostport\}", mcp), (
        "the /mcp reverse proxy must rewrite Host to the loopback upstream"
    )
    for target in re.findall(r"reverse_proxy\s+(\S+)", conf):
        assert target.startswith("127.0.0.1"), f"non-loopback Caddy upstream: {target}"


# --- the documented rewrite matches the guard ------------------------------


async def _ok_app(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Trivial ASGI app behind the guard: 200 for anything the guard lets through."""
    assert scope["type"] == "http"
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": b"ok"})


def test_nginx_upstream_host_passes_the_loopback_guard() -> None:
    """The Host the nginx config sends upstream is exactly what the guard accepts."""
    rewrite = re.search(r"proxy_set_header\s+Host\s+(\S+);", _nginx_mcp_location())
    assert rewrite, "the nginx /mcp location must pin the upstream Host"
    upstream_host = rewrite.group(1)

    client = TestClient(LoopbackGuard(_ok_app))
    accepted = client.get("/mcp", headers={"Host": upstream_host})
    assert accepted.status_code == 200, (
        f"Host {upstream_host!r} is what nginx sends upstream; the guard must accept it"
    )

    refused = client.get("/mcp", headers={"Host": "beacon.example.org"})
    assert refused.status_code == 421, (
        "a public Host straight at the MCP port must be refused with 421"
    )
