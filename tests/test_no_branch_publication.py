"""Repository branch names are never published (status 1.1, discovery descriptor 1.8).

A branch name is free text read from the live checkout, outside the export filter and the
secret scan, so it can name tickets, customers or internal hosts. Beacon keeps the commit,
dirty state and observation time as freshness evidence and publishes no branch anywhere.
"""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from beacon.core.snapshot import Snapshot
from beacon.core.status import RepositoryEvidence, StatusObservation
from beacon.http_api import create_http_app
from tests.test_http_discovery_guide import repo, snapshot  # noqa: F401  (pytest fixtures)

BRANCH_MARKER = "QQ-BRANCH-internal-db.example-QQ"


def test_no_http_surface_carries_the_branch_name(snapshot: Snapshot, tmp_path: Path) -> None:  # noqa: F811
    observed = StatusObservation(
        mode="startup",
        observed_at="2026-09-26T12:00:00Z",
        repository=RepositoryEvidence(
            state="observed", commit="c" * 40, branch=f"fix/{BRANCH_MARKER}", dirty=False
        ),
        sources=(),
    )
    client = TestClient(create_http_app(snapshot, status_observation=observed))
    for route in (
        "/.well-known/archolith-beacon",
        "/v1/snapshot/identity",
        "/v1/snapshot/orientation",
        "/v1/snapshot",
        "/v1/status",
        "/healthz",
    ):
        response = client.get(route)
        assert response.status_code == 200, route
        assert BRANCH_MARKER not in response.text, route
        assert BRANCH_MARKER not in str(response.headers), route
    # The evidence that remains still identifies the observed revision.
    status = client.get("/v1/status").json()
    assert status["beacon_status_version"] == "1.1"
    assert status["observed"]["repository"] == {
        "state": "observed",
        "commit": "c" * 40,
        "dirty": False,
    }
    discovery = client.get("/.well-known/archolith-beacon").json()
    assert discovery["freshness"]["repository"] == status["observed"]["repository"]
