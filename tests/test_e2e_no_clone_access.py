"""End to end: an agent with no checkout answers a "why" question over HTTP (issue #26).

Real processes only: ``beacon build`` reads a repository's ADRs, ``beacon export`` writes
the snapshot, and ``beacon serve-http`` / ``beacon serve --transport http`` serve it on
loopback sockets. The HTTP JSON walk follows discovery as a fetch-only agent would
(discovery -> search decisions -> decision record -> read -> explain), and MCP over
Streamable HTTP must give the same answers. Also checked on the live servers: an excluded
ADR is absent everywhere and probes like a bogus id, queries are never echoed, and the
MCP endpoint refuses a forged Host (DNS rebinding).
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from tests.test_adr_decisions import _adr_repo

MARKER = "QQ-E2E-QUERY-MARKER-QQ"
SERVED_DECISION = "Namespace isolation is enforced below transport-specific code."
WITHHELD_TEXT = "One canonical identity"
READY_TIMEOUT_S = 60.0


def _beacon(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "beacon", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _start(
    args: list[str], cwd: Path, log: Path, ready: re.Pattern[str]
) -> tuple[Any, re.Match[str]]:
    """Start ``python -m beacon <args>``; return the process once *ready* matches its stderr."""
    handle = log.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "beacon", *args],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=handle,
    )
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        text = log.read_text(encoding="utf-8", errors="replace")
        found = ready.search(text)
        if found:
            return proc, found
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    _stop(proc)
    raise AssertionError(
        f"server not ready: {log.read_text(encoding='utf-8', errors='replace')[-2000:]}"
    )


def _stop(proc: Any) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _get(
    base: str, route: str, params: dict[str, str] | None = None
) -> tuple[int, bytes, dict[str, str]]:
    url = base + route + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _mcp_status_for_host(port: int, host: str) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest("POST", "/mcp", skip_host=True)
        body = b"{}"
        for key, value in {
            "Host": host,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Content-Length": str(len(body)),
        }.items():
            conn.putheader(key, value)
        conn.endheaders(body)
        response = conn.getresponse()
        response.read()
        return response.status
    finally:
        conn.close()


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """Build and export a repository with two ADRs (one excluded), then serve it both ways."""
    tmp = tmp_path_factory.mktemp("e2e")
    root = _adr_repo(tmp, {"serving": {"exclude": ["docs/adr/0010-self.md"]}})
    built = _beacon("build", "--repo", str(root), "--format", "json", cwd=root)
    assert built.returncode == 0, built.stdout + built.stderr
    manifest = root / "beacon.generated.yaml"
    snapshot = tmp / "beacon.snapshot.json"
    exported = _beacon(
        "export", str(manifest), "--docs-root", str(root), "--output", str(snapshot), cwd=root
    )
    assert exported.returncode == 0, exported.stdout + exported.stderr

    http_proc, http_ready = _start(
        ["serve-http", "--manifest", str(manifest), "--docs-root", str(root), "--port", "0"],
        root,
        tmp / "serve-http.log",
        re.compile(r"Beacon HTTP ready url=(http://127\.0\.0\.1:\d+)"),
    )
    # `serve --transport http` refuses port 0, so a picked port can be taken before the
    # bind; retry a start that failed with http_bind_failed on a fresh port.
    try:
        for attempt in range(3):
            mcp_port = _free_port()
            try:
                mcp_proc, _ = _start(
                    [
                        "serve",
                        "--snapshot",
                        str(snapshot),
                        "--transport",
                        "http",
                        "--port",
                        str(mcp_port),
                    ],
                    root,
                    tmp / "serve-mcp.log",
                    re.compile(r"MCP http listening"),
                )
                break
            except AssertionError:
                log_text = (tmp / "serve-mcp.log").read_text(encoding="utf-8", errors="replace")
                if attempt == 2 or "http_bind_failed" not in log_text:
                    raise
    except BaseException:
        _stop(http_proc)
        raise
    try:
        yield {
            "http": http_ready.group(1),
            "mcp_port": mcp_port,
            "logs": (tmp / "serve-http.log", tmp / "serve-mcp.log"),
        }
    finally:
        _stop(http_proc)
        _stop(mcp_proc)


def _no_marker(*bodies: bytes | str) -> None:
    for body in bodies:
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
        assert MARKER.lower() not in text.lower()


def test_fetch_only_agent_answers_why_by_following_discovery(served: dict[str, Any]) -> None:
    base = served["http"]
    status, body, _ = _get(base, "/.well-known/archolith-beacon")
    assert status == 200
    discovery = json.loads(body)
    assert discovery["trust"] == "direct_unverified"
    assert discovery["capabilities"]["query"] is True
    flow_urls = [step["url"] for step in discovery["recommended_flow"]]
    search_url = discovery["dynamic"]["search"]["url"]
    decisions_index = discovery["resources"]["decisions"]["index_url"]
    assert search_url in flow_urls

    # Search the decisions for the "why", with a marker that must never come back.
    status, body, headers = _get(
        base, search_url, {"q": f"namespace isolation transport {MARKER}", "types": "decisions"}
    )
    assert status == 200
    _no_marker(body, json.dumps(headers))
    hits = json.loads(body)["results"]
    hit = next(h for h in hits if h["source_type"] == "decision")
    assert hit["title"].startswith("adr-0005")

    # The decision record carries the verbatim decision and its rejected alternatives.
    status, body, _ = _get(base, decisions_index)
    assert status == 200
    assert [d["id"] for d in json.loads(body)["decisions"]] == ["adr-0005"]
    item = discovery["resources"]["decisions"]["item_url_template"].replace("{id}", "adr-0005")
    status, body, _ = _get(base, item)
    assert status == 200
    record = json.loads(body)
    assert record["decision"] == SERVED_DECISION
    assert any("Enforce the pin in every route" in str(alt) for alt in record["alternatives"])

    # Read the ADR section the hit points at, then explain the decision.
    status, body, _ = _get(base, discovery["dynamic"]["read"]["url"], {"chunk_id": hit["chunk_id"]})
    assert status == 200
    assert "Namespace isolation is enforced" in json.loads(body)["text"]
    status, body, _ = _get(base, discovery["dynamic"]["explain"]["url"], {"concept": "adr-0005"})
    assert status == 200
    assert json.loads(body)["why_it_exists"].startswith("Alternatives considered:")


def test_excluded_adr_is_absent_from_every_http_surface(served: dict[str, Any]) -> None:
    base = served["http"]
    withheld = _get(base, "/v1/decisions/adr-0010")
    bogus = _get(base, "/v1/decisions/adr-9999")
    assert withheld[0] == bogus[0] == 404
    assert withheld[1] == bogus[1]
    # Each probe must answer normally (a generic 500 would also "not contain" the ADR).
    for path, params, expected in (
        ("/v1/snapshot", {}, 200),
        ("/v1/search", {"q": "canonical identity namespace"}, 200),
        ("/v1/explain", {"concept": "Canonical Self Identity"}, 200),
        ("/v1/read", {"path": "docs/adr/0010-self.md"}, 404),
    ):
        status, body, _ = _get(base, path, params)
        assert status == expected, (path, status)
        payload = json.loads(body)
        if path == "/v1/read":
            assert payload["error"]["code"] == "read_not_found"
        elif path != "/v1/snapshot":
            assert payload.get("ok") is not False, path
        text = body.decode("utf-8")
        assert WITHHELD_TEXT not in text and "0010-self" not in text, path


def test_unknown_concept_and_refusals_never_echo_the_query(served: dict[str, Any]) -> None:
    base = served["http"]
    status, body, headers = _get(base, "/v1/explain", {"concept": MARKER})
    assert status == 200
    _no_marker(body, json.dumps(headers))
    status, body, headers = _get(base, "/v1/search", {"q": MARKER + "x" * 5000})
    assert status == 400
    _no_marker(body, json.dumps(headers))
    for log in served["logs"]:
        _no_marker(log.read_text(encoding="utf-8", errors="replace"))


async def test_remote_mcp_gives_the_same_answers_as_http_json(served: dict[str, Any]) -> None:
    base = served["http"]
    port = served["mcp_port"]
    _, body, _ = _get(base, "/v1/search", {"q": "namespace isolation", "types": "decisions"})
    chunk_id = json.loads(body)["results"][0]["chunk_id"]
    over_cap = "namespace " * 1000
    async with Client(f"http://127.0.0.1:{port}/mcp", timeout=30) as client:
        tools = {tool.name for tool in await client.list_tools()}
        assert {"beacon_search", "beacon_read", "beacon_explain_concept"} <= tools
        for tool, arguments, path, params, expected in (
            (
                "beacon_search",
                {"query": "namespace isolation transport", "source_types": ["decisions"]},
                "/v1/search",
                {"q": "namespace isolation transport", "types": "decisions"},
                200,
            ),
            (
                "beacon_explain_concept",
                {"concept": "adr-0005"},
                "/v1/explain",
                {"concept": "adr-0005"},
                200,
            ),
            ("beacon_read", {"chunk_id": chunk_id}, "/v1/read", {"chunk_id": chunk_id}, 200),
            # Refusals must match too: same error envelope, mapped to HTTP 400 / 404.
            ("beacon_search", {"query": over_cap}, "/v1/search", {"q": over_cap}, 400),
            (
                "beacon_read",
                {"path": "docs/adr/0010-self.md"},
                "/v1/read",
                {"path": "docs/adr/0010-self.md"},
                404,
            ),
        ):
            result = await client.call_tool(tool, arguments)
            mcp_payload = json.loads(result.content[0].text)
            status, body, _ = _get(base, path, params)
            assert status == expected, (tool, status)
            assert json.loads(body) == mcp_payload, tool
            assert (mcp_payload.get("ok") is False) == (expected != 200), tool
        read = await client.call_tool("beacon_read", {"chunk_id": chunk_id})
        assert "Namespace isolation is enforced" in read.content[0].text


def test_remote_mcp_refuses_a_forged_host(served: dict[str, Any]) -> None:
    port = served["mcp_port"]
    assert _mcp_status_for_host(port, "evil.example") == 421
    assert _mcp_status_for_host(port, f"evil.example:{port}") == 421
    assert _mcp_status_for_host(port, f"127.0.0.1:{port}") not in (421, 403)


def _json_api_status(base: str, host: str, origin: str | None = None) -> int:
    """GET discovery on the real serve-http with an explicit Host (and Origin)."""
    port = int(base.rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest("GET", "/.well-known/archolith-beacon", skip_host=True)
        conn.putheader("Host", host)
        if origin is not None:
            conn.putheader("Origin", origin)
        conn.endheaders()
        response = conn.getresponse()
        response.read()
        return response.status
    finally:
        conn.close()


def test_json_api_refuses_a_forged_host_or_origin(served: dict[str, Any]) -> None:
    # F20: serve-http gets the same DNS-rebinding guard as MCP over HTTP.
    base = served["http"]
    port = base.rsplit(":", 1)[1]
    assert _json_api_status(base, "evil.example") == 421
    assert _json_api_status(base, f"evil.example:{port}") == 421
    assert _json_api_status(base, f"127.0.0.1:{port}", origin="http://evil.example") == 403
    assert _json_api_status(base, f"127.0.0.1:{port}") == 200
    assert _json_api_status(base, f"localhost:{port}") == 200
