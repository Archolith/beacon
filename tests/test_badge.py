"""README badge (``/v1/badge.json``, ``/v1/badge.svg``) and serve-http security headers.

The badge renders only startup facts (served commit, its committer time, the MCP tool count)
plus the clock, so no request input reaches it. Every serve-http response, including the
Host/Origin guard's refusals, carries the browser-hardening headers a proxy used to add.
"""

from __future__ import annotations

import http.client
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from beacon.badge import STALE_AFTER_DAYS, badge_state, endpoint_payload, render_svg
from beacon.core.status import (
    RepositoryEvidence,
    StatusObservation,
    build_status_payload,
    observe_project_status,
)
from beacon.http_api import create_http_app
from beacon.mcp.tools import ALL_TOOLS
from beacon.security_headers import SecurityHeaders
from tests.test_adr_decisions import _adr_repo
from tests.test_e2e_no_clone_access import _beacon, _start, _stop
from tests.test_http_api import _make_snapshot

COMMIT = "6bb36fa498611e154beef8330b5040cdfd72471f"
T0 = 1_790_000_000
DAY = 86_400


# -- badge state -----------------------------------------------------------------------


def test_fresh_commit_is_live_with_commit_and_tools() -> None:
    state = badge_state(commit=COMMIT, commit_time=T0, tools=7, now=T0 + 3 * DAY)
    assert state.message == "live · 6bb36fa · 7 tools"
    assert state.color_name == "brightgreen"


def test_stale_boundary() -> None:
    at_limit = badge_state(commit=COMMIT, commit_time=T0, tools=7, now=T0 + STALE_AFTER_DAYS * DAY)
    assert at_limit.message.startswith("live")
    past = badge_state(
        commit=COMMIT, commit_time=T0, tools=7, now=T0 + (STALE_AFTER_DAYS + 1) * DAY
    )
    assert past.message == f"stale · {STALE_AFTER_DAYS + 1} days"
    assert past.color_name == "yellow"


def test_future_commit_time_and_missing_facts_degrade_gracefully() -> None:
    assert badge_state(commit=COMMIT, commit_time=T0 + DAY, tools=None, now=T0).message == (
        "live · 6bb36fa"
    )
    assert badge_state(commit="", commit_time=None, tools=None, now=T0).message == "live"
    # No commit time: never stale, still shows the commit.
    assert badge_state(commit=COMMIT, commit_time=None, tools=7, now=T0).color_name == "brightgreen"


def test_endpoint_payload_matches_the_shields_schema() -> None:
    payload = endpoint_payload(badge_state(commit=COMMIT, commit_time=T0, tools=7, now=T0))
    assert payload == {
        "schemaVersion": 1,
        "label": "beacon",
        "message": "live · 6bb36fa · 7 tools",
        "color": "brightgreen",
        "cacheSeconds": 3600,
    }


def test_svg_is_well_formed_and_escaped() -> None:
    svg = render_svg(badge_state(commit=COMMIT, commit_time=T0, tools=7, now=T0))
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg") and int(root.attrib["width"]) > 100
    assert "live · 6bb36fa · 7 tools" in svg.decode("utf-8")
    assert b"<script" not in svg.lower()
    from beacon.badge import BadgeState

    hostile = render_svg(BadgeState('<x"&>', "brightgreen", "#44cc11"))
    ET.fromstring(hostile)  # still well-formed
    assert b'<x"&>' not in hostile


# -- HTTP routes -----------------------------------------------------------------------


def _observation(commit_time: int | None) -> StatusObservation:
    return StatusObservation(
        mode="startup",
        observed_at="2026-09-27T00:00:00Z",
        repository=RepositoryEvidence(
            state="observed",
            commit=COMMIT,
            branch="(detached)",
            dirty=False,
            commit_time=commit_time,
        ),
        sources=(),
    )


def test_badge_routes_serve_json_and_svg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("beacon.http_api.time.time", lambda: T0 + DAY)
    app = create_http_app(_make_snapshot(), status_observation=_observation(T0), mcp_path="/mcp")
    tools = len(ALL_TOOLS) if app.state.beacon_provider is not None else None
    with TestClient(app) as client:
        data = client.get("/v1/badge.json")
        svg = client.get("/v1/badge.svg")
        head = client.head("/v1/badge.svg")
        hostile = client.get("/v1/badge.json?message=%3Cscript%3E&label=x")
    assert data.status_code == 200
    body = data.json()
    assert body["schemaVersion"] == 1 and body["label"] == "beacon"
    assert body["message"].startswith("live · 6bb36fa")
    assert (f"{tools} tools" in body["message"]) is (tools is not None)
    assert data.headers["cache-control"] == "public, max-age=3600"
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert "default-src 'none'" in svg.headers["content-security-policy"]
    assert head.status_code == 200 and head.content == b""
    assert hostile.json() == body  # query strings are ignored


def test_stale_badge_over_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("beacon.http_api.time.time", lambda: T0 + 45 * DAY)
    app = create_http_app(_make_snapshot(), status_observation=_observation(T0))
    with TestClient(app) as client:
        assert client.get("/v1/badge.json").json()["message"] == "stale · 45 days"


def test_commit_time_is_not_published_in_status() -> None:
    payload = build_status_payload(
        _make_snapshot(), snapshot_sha256="0" * 64, observation=_observation(T0)
    )
    assert "commit_time" not in json.dumps(payload)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_observed_repository_carries_commit_time(tmp_path: Path) -> None:
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t.invalid", *a],
        check=True,
        capture_output=True,
        text=True,
    )
    run("init", "-q")
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "one")
    expected = int(run("show", "-s", "--format=%ct", "HEAD").stdout.strip())
    manifest = tmp_path / "beacon.yaml"
    manifest.write_text("x", encoding="utf-8")
    observation = observe_project_status(
        _make_snapshot(), manifest_path=manifest, docs_root=tmp_path
    )
    evidence = observation.repository
    assert evidence.state == "observed" and evidence.commit_time == expected


# -- security headers ------------------------------------------------------------------


async def test_security_headers_are_added_but_never_override() -> None:
    sent: list[dict[str, Any]] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"x-frame-options", b"SAMEORIGIN")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await SecurityHeaders(app)({"type": "http"}, None, send)  # type: ignore[arg-type]
    headers = dict(sent[0]["headers"])
    assert headers[b"x-frame-options"] == b"SAMEORIGIN"
    assert headers[b"referrer-policy"] == b"no-referrer"
    assert headers[b"x-content-type-options"] == b"nosniff"


def _get(port: int, path: str, host: str) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host)
        conn.endheaders()
        response = conn.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        conn.close()


def test_serve_http_process_sends_security_headers_and_badges(tmp_path: Path) -> None:
    root = _adr_repo(tmp_path)
    built = _beacon("build", "--repo", str(root), "--format", "json", cwd=root)
    assert built.returncode == 0, built.stdout + built.stderr
    proc, ready = _start(
        ["serve-http", "--manifest", str(root / "beacon.generated.yaml"), "--port", "0"],
        root,
        tmp_path / "serve.log",
        re.compile(r"Beacon HTTP ready url=http://127\.0\.0\.1:(\d+)"),
    )
    try:
        port = int(ready.group(1))
        for path, host, status in (
            ("/v1/badge.json", "127.0.0.1", 200),
            ("/nope", "127.0.0.1", 404),
            ("/healthz", "evil.example.org", 421),  # the guard's own refusal
        ):
            code, headers, _ = _get(port, path, host)
            assert code == status, path
            assert headers["x-frame-options"] == "DENY", path
            assert headers["referrer-policy"] == "no-referrer", path
            assert headers["x-content-type-options"] == "nosniff", path
        _, _, body = _get(port, "/v1/badge.json", "127.0.0.1")
        message = json.loads(body)["message"]
        assert message.startswith("live") and f"{len(ALL_TOOLS)} tools" in message
    finally:
        _stop(proc)
