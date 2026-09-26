"""Discovery descriptor 1.7 as an LLM entry point.

* Every resource family and dynamic route carries a one-line ``use_when``.
* ``recommended_flow`` is an ordered list of short steps whose URLs all answer
  200 on the servable surface and never mention dynamic or decision routes
  when the manifest is not servable.
* ``freshness`` mirrors the ``StatusObservation`` handed to ``create_http_app``
  (populated and ``unavailable``), the identity body stays byte-identical, and
  the same facts appear on identity response headers.
* Discovery bytes are deterministic per (snapshot, observation) and never
  contain absolute filesystem paths, hostnames, or query strings.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml
from starlette.testclient import TestClient

from beacon import __version__
from beacon.core.policy import PolicyEvaluation
from beacon.core.snapshot import (
    CONTENT_EMBEDDED,
    SNAPSHOT_VERSION,
    Snapshot,
    SnapshotGenerator,
    SnapshotManifest,
    SnapshotProject,
    SnapshotValidation,
    build_snapshot,
    identity_snapshot,
    snapshot_bytes,
)
from beacon.core.status import RepositoryEvidence, StatusObservation
from beacon.http_api import create_http_app

_DISCOVERY = "/.well-known/archolith-beacon"

_ADR_0001 = """# ADR 0001 - Discovery Entry Point

- **Status:** ACCEPTED (2026-09-26).
- **Date:** 2026-09-26
- **Deciders:** a maintainer

## Context

Agents need one entry point to the served surface.

## Decision

Discovery is the LLM entry point for Beacon.

## Consequences

Guidance and freshness live in the discovery document.
"""


def _manifest_data() -> dict[str, Any]:
    """A servable manifest with one served ADR, one concept, one guardrail."""
    citation = {
        "type": "file",
        "title": "ADR 0001",
        "path": "docs/adr/0001-entry-point.md",
        "line_start": 13,
        "line_end": 13,
        "status": "current",
    }
    return {
        "beacon_version": "0.1",
        "project": {
            "name": "discovery-guide",
            "description": "Fixture project for discovery guide tests.",
            "status": "current",
        },
        "purpose": {"one_sentence": "Exercise the discovery guide contract."},
        "audiences": ["coding_agent"],
        "core_concepts": [
            {
                "id": "entry_point",
                "name": "Entry Point",
                "definition": "Discovery is the LLM entry point.",
                "why_it_exists": "One place to learn the served surface.",
                "status": "current",
                "related_concepts": [],
                "sources": [citation],
                "implementation_locations": ["src/entry.py"],
            }
        ],
        "canonical_docs": [
            {"path": "README.md", "role": "entrypoint", "title": "Demo"},
            {"path": "docs/guide.md", "role": "workflow", "title": "Guide"},
            {
                "path": "docs/adr/0001-entry-point.md",
                "role": "decision",
                "title": "Discovery Entry Point",
            },
        ],
        "build_and_test": {"test": "pytest -q"},
        "guardrails": [
            {
                "id": "keep_entry_point",
                "rule": "Keep discovery the single LLM entry point.",
                "scope": "src",
                "severity": "high",
                "applies_to": ["src/entry.py"],
                "sources": [citation],
            }
        ],
        "decisions": [
            {
                "id": "adr-0001",
                "title": "Discovery Entry Point",
                "path": "docs/adr/0001-entry-point.md",
                "status": "current",
                "status_text": "ACCEPTED (2026-09-26)",
                "date": "2026-09-26",
                "decision": "Discovery is the LLM entry point for Beacon.",
                "sources": [citation],
            }
        ],
    }


def _write_repo(root: Path) -> None:
    (root / "docs" / "adr").mkdir(parents=True)
    (root / "README.md").write_text(
        "# Demo\n\nDemo project for the discovery guide tests.\n", encoding="utf-8"
    )
    (root / "docs" / "guide.md").write_text(
        "# Guide\n\nThe entry point pipeline starts in discovery.\n\n"
        "## Setup\n\nInstall with pip install -e .\n",
        encoding="utf-8",
    )
    (root / "docs" / "adr" / "0001-entry-point.md").write_text(_ADR_0001, encoding="utf-8")
    (root / "beacon.yaml").write_text(
        yaml.safe_dump(_manifest_data(), sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _write_repo(root)
    return root


@pytest.fixture()
def snapshot(repo: Path) -> Snapshot:
    return build_snapshot(repo / "beacon.yaml", docs_root=repo, content_mode=CONTENT_EMBEDDED)


@pytest.fixture()
def client(snapshot: Snapshot) -> TestClient:
    return TestClient(create_http_app(snapshot))


@pytest.fixture()
def observation() -> StatusObservation:
    return StatusObservation(
        mode="startup",
        observed_at="2026-09-26T12:00:00Z",
        repository=RepositoryEvidence(
            state="observed",
            commit="b" * 40,
            branch="feat/guide",
            dirty=True,
        ),
        sources=(),
    )


def _discovery(client: TestClient) -> dict[str, Any]:
    return client.get(_DISCOVERY).json()


def _unservable_snapshot() -> Snapshot:
    """A snapshot whose embedded manifest cannot be served (no query routes)."""
    return Snapshot(
        beacon_snapshot_version=SNAPSHOT_VERSION,
        generator=SnapshotGenerator(distribution="archolith-beacon", version=__version__),
        content_mode=CONTENT_EMBEDDED,
        project=SnapshotProject(name="unservable", status="current", repository=""),
        manifest=SnapshotManifest(
            beacon_version="0.1",
            source_sha256="0" * 64,
            data={"project": {"name": "unservable"}},
        ),
        documents=(),
        validation=SnapshotValidation(errors=0, warnings=0),
        policy=PolicyEvaluation(servable=True, publishable=True),
        security_findings=(),
    )


# ---------------------------------------------------------------------------
# Usage guidance (contract 8a)
# ---------------------------------------------------------------------------


def test_every_family_dynamic_route_and_flow_step_has_use_when(client: TestClient) -> None:
    body = _discovery(client)
    for name, family in body["resources"].items():
        assert isinstance(family.get("use_when"), str) and family["use_when"], name
    for name, route in body["dynamic"].items():
        assert isinstance(route.get("use_when"), str) and route["use_when"], name
    for step in body["recommended_flow"]:
        assert isinstance(step.get("use_when"), str) and step["use_when"], step


# ---------------------------------------------------------------------------
# Recommended flow (contract 8b)
# ---------------------------------------------------------------------------


def test_flow_urls_answer_200(client: TestClient) -> None:
    body = _discovery(client)
    assert [step["url"] for step in body["recommended_flow"]] == [
        "/v1/snapshot/identity",
        "/v1/search",
        "/v1/decisions/{id}",
        "/v1/search",
        "/v1/read",
        "/v1/explain",
        "/v1/guardrails",
    ]
    decision_id = client.get("/v1/decisions").json()["decisions"][0]["id"]
    chunk_id = client.get("/v1/chunks").json()["documents"][0]["chunks"][0]["id"]
    concept_id = client.get("/v1/concepts").json()["concepts"][0]["id"]
    params_by_template: dict[str, dict[str, str] | None] = {
        "/v1/search": {"q": "entry point", "types": "decisions"},
        "/v1/read": {"chunk_id": chunk_id},
        "/v1/explain": {"concept": concept_id},
        "/v1/snapshot/identity": None,
        "/v1/guardrails": None,
    }
    for step in body["recommended_flow"]:
        template = step["url"]
        url = template.replace("{id}", decision_id)
        response = client.get(url, params=params_by_template.get(template))
        assert response.status_code == 200, template


# ---------------------------------------------------------------------------
# Unservable manifests keep the flow static (contract 8c)
# ---------------------------------------------------------------------------


def test_unservable_flow_mentions_no_dynamic_or_decision_routes() -> None:
    client = TestClient(create_http_app(_unservable_snapshot()))
    body = _discovery(client)
    assert "dynamic" not in body
    assert "decisions" not in body["resources"]
    assert [step["url"] for step in body["recommended_flow"]] == [
        "/v1/snapshot/identity",
        "/v1/guardrails",
    ]
    for step in body["recommended_flow"]:
        assert not step["url"].startswith(
            ("/v1/search", "/v1/read", "/v1/explain", "/v1/decisions")
        ), step
    for name, family in body["resources"].items():
        assert isinstance(family.get("use_when"), str) and family["use_when"], name


# ---------------------------------------------------------------------------
# Freshness (contract 8d)
# ---------------------------------------------------------------------------


def test_freshness_matches_a_populated_observation(
    snapshot: Snapshot, observation: StatusObservation
) -> None:
    client = TestClient(create_http_app(snapshot, status_observation=observation))
    sha256 = hashlib.sha256(snapshot_bytes(snapshot)).hexdigest()
    body = _discovery(client)
    assert body["freshness"] == {
        "snapshot_sha256": sha256,
        "generator": {"distribution": "archolith-beacon", "version": __version__},
        "repository": {
            "state": "observed",
            "commit": "b" * 40,
            "dirty": True,
        },
        "observed_at": "2026-09-26T12:00:00Z",
        "status_url": "/v1/status",
    }
    identity = client.get("/v1/snapshot/identity")
    assert identity.content == snapshot_bytes(identity_snapshot(snapshot))
    assert identity.headers["x-beacon-observed-at"] == "2026-09-26T12:00:00Z"
    assert identity.headers["x-beacon-repository-state"] == "observed"
    assert identity.headers["x-beacon-repository-commit"] == "b" * 40
    # Branch names are never published (status 1.1 / descriptor 1.8).
    assert "x-beacon-repository-branch" not in identity.headers
    assert identity.headers["x-beacon-repository-dirty"] == "true"
    assert identity.headers["x-beacon-generator-version"] == __version__
    assert identity.headers["x-beacon-full-snapshot-sha256"] == sha256


def test_freshness_with_unavailable_observation(snapshot: Snapshot) -> None:
    client = TestClient(
        create_http_app(snapshot, status_observation=StatusObservation.unavailable())
    )
    sha256 = hashlib.sha256(snapshot_bytes(snapshot)).hexdigest()
    body = _discovery(client)
    assert body["freshness"] == {
        "snapshot_sha256": sha256,
        "generator": {"distribution": "archolith-beacon", "version": __version__},
        "repository": {"state": "unavailable"},
        "observed_at": None,
        "status_url": "/v1/status",
    }
    identity = client.get("/v1/snapshot/identity")
    assert identity.content == snapshot_bytes(identity_snapshot(snapshot))
    assert identity.headers["x-beacon-repository-state"] == "unavailable"
    assert identity.headers["x-beacon-generator-version"] == __version__
    assert identity.headers["x-beacon-full-snapshot-sha256"] == sha256
    for absent in (
        "x-beacon-observed-at",
        "x-beacon-repository-commit",
        "x-beacon-repository-branch",
        "x-beacon-repository-dirty",
    ):
        assert absent not in identity.headers, absent


# ---------------------------------------------------------------------------
# Determinism and redaction (contracts 8e and 8f)
# ---------------------------------------------------------------------------


def test_discovery_bytes_are_identical_across_apps(
    snapshot: Snapshot, observation: StatusObservation
) -> None:
    first = TestClient(create_http_app(snapshot, status_observation=observation))
    second = TestClient(create_http_app(snapshot, status_observation=observation))
    assert first.get(_DISCOVERY).content == second.get(_DISCOVERY).content


def test_discovery_has_no_paths_hosts_or_query_strings(client: TestClient, repo: Path) -> None:
    text = client.get(_DISCOVERY).text
    assert "?" not in text
    assert "\\" not in text
    assert "://" not in text
    assert "C:" not in text
    assert "localhost" not in text
    assert "127.0.0.1" not in text
    assert str(repo) not in text
    assert str(repo.parent) not in text
