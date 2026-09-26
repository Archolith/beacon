"""Lower-severity review fixes for the HTTP JSON surface (astra review of PR #28).

* B4: provider work runs off the event loop, so a slow query does not stall other requests.
* B5: a decision id containing "/" (an ADR in a nested directory) is reachable.
* B8: an unexpected tool exception is logged without its message, which can quote the query.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import yaml
from starlette.testclient import TestClient

from beacon.core.snapshot import CONTENT_EMBEDDED, Snapshot, build_snapshot
from beacon.http_api import create_http_app
from tests.test_http_api_dynamic import _manifest_data, _write_repo, repo, snapshot  # noqa: F401

MARKER = "QQ-REVIEW-LOWS-MARKER-QQ"


async def test_a_slow_query_does_not_block_other_requests(snapshot: Snapshot) -> None:  # noqa: F811
    app = create_http_app(snapshot)
    provider = app.state.beacon_provider
    real_search = provider.search

    def slow_search(**kwargs: Any) -> Any:
        time.sleep(0.8)  # synchronous, like a large scan
        return real_search(**kwargs)

    provider.search = slow_search
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        health_done: list[float] = []
        # Measured from one fixed start: a blocked loop would also delay the sleep below,
        # so timing only the health request itself could not see the block.
        start = time.monotonic()

        async def health() -> None:
            await anyio.sleep(0.2)  # let the search start first
            response = await client.get("/healthz")
            health_done.append(time.monotonic() - start)
            assert response.status_code == 200

        async with anyio.create_task_group() as group:
            group.start_soon(client.get, "/v1/search?q=namespace+isolation")
            group.start_soon(health)
    # The search holds its thread for 0.8 s; health must answer long before that.
    assert health_done and health_done[0] < 0.6, health_done


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
