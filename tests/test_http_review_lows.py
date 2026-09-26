"""Lower-severity review fixes for the HTTP JSON surface (astra review of PR #28).

* B4: provider work runs off the event loop, so a slow query does not stall other requests.
* B5: a decision id containing "/" (an ADR in a nested directory) is reachable.
* B8: an unexpected tool exception is logged without its message, which can quote the query.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any

import anyio
import anyio.to_thread
import httpx
import pytest
import yaml
from starlette.testclient import TestClient

from beacon.core.snapshot import CONTENT_EMBEDDED, Snapshot, build_snapshot
from beacon.http_api import _TOOL_CONCURRENCY, create_http_app
from tests.test_http_api_dynamic import _manifest_data, _write_repo, repo, snapshot  # noqa: F401

MARKER = "QQ-REVIEW-LOWS-MARKER-QQ"


async def test_a_slow_query_does_not_block_other_requests(snapshot: Snapshot) -> None:  # noqa: F811
    app = create_http_app(snapshot)
    provider = app.state.beacon_provider
    real_search = provider.search
    entered, release = threading.Event(), threading.Event()

    def blocked_search(**kwargs: Any) -> Any:
        entered.set()
        assert release.wait(30), "the test never released the search"
        return real_search(**kwargs)

    provider.search = blocked_search
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        search = asyncio.create_task(
            client.get("/v1/search", params={"q": "namespace isolation", "types": "decisions"})
        )
        # Synchronized, not timed: health must answer while the search is provably inside
        # the provider, which it only is if the provider runs off the event loop.
        assert await anyio.to_thread.run_sync(entered.wait, 30)
        with anyio.fail_after(10):  # a hang guard only; a blocked loop never gets here
            health = await client.get("/healthz")
        assert health.status_code == 200
        assert not search.done()
        release.set()
        response = await search
    assert response.status_code == 200
    body = response.json()
    assert body.get("ok") is not False and body["results"], body


async def test_cancelled_requests_keep_their_worker_slots(snapshot: Snapshot) -> None:  # noqa: F811
    app = create_http_app(snapshot)
    provider = app.state.beacon_provider
    real_search = provider.search
    lock, release = threading.Lock(), threading.Event()
    counts = {"active": 0, "peak": 0, "entered": 0}

    def blocked_search(**kwargs: Any) -> Any:
        with lock:
            counts["active"] += 1
            counts["entered"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
        try:
            assert release.wait(30), "the test never released the searches"
            return real_search(**kwargs)
        finally:
            with lock:
                counts["active"] -= 1

    provider.search = blocked_search

    def entered(n: int) -> bool:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with lock:
                if counts["entered"] >= n:
                    return True
            time.sleep(0.01)
        return False

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        first = [
            asyncio.create_task(client.get("/v1/search", params={"q": f"namespace {i}"}))
            for i in range(_TOOL_CONCURRENCY)
        ]
        assert await anyio.to_thread.run_sync(entered, _TOOL_CONCURRENCY)
        for task in first:
            task.cancel()
        second = [
            asyncio.create_task(client.get("/v1/search", params={"q": f"isolation {i}"}))
            for i in range(_TOOL_CONCURRENCY)
        ]
        # The cancelled requests' workers still run, so no new search may enter yet. (With
        # the slots freed on cancel, the second batch enters within milliseconds.)
        await anyio.sleep(0.3)
        with lock:
            assert counts["entered"] == _TOOL_CONCURRENCY, counts
        release.set()
        results = await asyncio.gather(*second)
    assert all(r.status_code == 200 for r in results)
    assert counts["peak"] <= _TOOL_CONCURRENCY, counts


def test_a_decision_id_with_a_slash_is_reachable(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _write_repo(root)
    data = _manifest_data()
    data["decisions"][0]["id"] = "team/adr-0005"
    (root / "beacon.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    snap = build_snapshot(root / "beacon.yaml", docs_root=root, content_mode=CONTENT_EMBEDDED)
    client = TestClient(create_http_app(snap))
    listed = [d["id"] for d in client.get("/v1/decisions").json()["decisions"]]
    assert "team/adr-0005" in listed
    response = client.get("/v1/decisions/team/adr-0005")
    assert response.status_code == 200
    assert response.json()["id"] == "team/adr-0005"
    assert client.get("/v1/decisions/team%2Fadr-0005").status_code == 200
    assert client.get("/v1/decisions/team/adr-9999").status_code == 404


def test_an_unexpected_error_is_logged_without_its_message(
    snapshot: Snapshot,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_http_app(snapshot)

    def broken_search(**kwargs: Any) -> Any:
        raise RuntimeError(f"cannot handle {kwargs['query']}")

    app.state.beacon_provider.search = broken_search
    with caplog.at_level(logging.DEBUG):
        response = TestClient(app).get("/v1/search", params={"q": MARKER})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert MARKER not in response.text
    # Beacon's own log lines only (the test client logs its request URL itself).
    beacon_log = "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("beacon")
    )
    assert "RuntimeError" in beacon_log
    assert MARKER not in beacon_log


def test_a_chained_error_logs_every_type_but_no_message(
    snapshot: Snapshot,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_http_app(snapshot)

    def broken_search(**kwargs: Any) -> Any:
        try:
            raise ValueError(f"bad token in {kwargs['query']}")
        except ValueError as inner:
            raise RuntimeError(f"search failed for {kwargs['query']}") from inner

    app.state.beacon_provider.search = broken_search
    with caplog.at_level(logging.ERROR):
        response = TestClient(app).get("/v1/search", params={"q": MARKER})
    assert response.status_code == 500
    beacon_log = "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("beacon")
    )
    assert "RuntimeError" in beacon_log and "caused by ValueError" in beacon_log
    assert "broken_search" in beacon_log  # the cause's stack survives
    assert MARKER not in beacon_log
