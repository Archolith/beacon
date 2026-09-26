"""Tests for the immutable project-status companion resource."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import jsonschema
import pytest

from beacon.core.limits import ResourceLimits
from beacon.core.policy import PolicyEvaluation
from beacon.core.snapshot import (
    SNAPSHOT_VERSION,
    Snapshot,
    SnapshotDocument,
    SnapshotGenerator,
    SnapshotManifest,
    SnapshotProject,
    SnapshotValidation,
)
from beacon.core.status import (
    RepositoryEvidence,
    StatusObservation,
    build_status_payload,
    observe_project_status,
)


def _snapshot(manifest_sha: str, document_sha: str) -> Snapshot:
    return Snapshot(
        beacon_snapshot_version=SNAPSHOT_VERSION,
        generator=SnapshotGenerator(distribution="archolith-beacon", version="test"),
        content_mode="embedded",
        project=SnapshotProject(name="status-project", status="current"),
        manifest=SnapshotManifest(
            beacon_version="0.1",
            source_sha256=manifest_sha,
            data={
                "project_state": {
                    "active_work": {
                        "title": "Verified status",
                        "summary": "Expose declared and observed state separately.",
                        "next_step": "Implement bounded orientation summaries.",
                        "sources": [
                            {
                                "type": "doc",
                                "title": "Roadmap",
                                "path": "docs/roadmap.md",
                                "url": "",
                                "line_start": 1,
                                "line_end": 4,
                                "status": "current",
                            }
                        ],
                    },
                    "recently_completed": [],
                    "blockers": [],
                    "pending_decisions": [],
                }
            },
        ),
        documents=(
            SnapshotDocument(
                path="docs/roadmap.md",
                role="product_roadmap",
                status="current",
                title="Roadmap",
                source_sha256=document_sha,
                chunks=(),
            ),
        ),
        validation=SnapshotValidation(errors=0, warnings=0),
        policy=PolicyEvaluation(servable=True, publishable=True),
    )


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_observation_reports_fresh_sources_and_fixed_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_bytes = b"beacon_version: '0.1'\n"
    document_bytes = b"# Roadmap\n"
    (tmp_path / "beacon.yaml").write_bytes(manifest_bytes)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "roadmap.md").write_bytes(document_bytes)
    snapshot = _snapshot(_sha(manifest_bytes), _sha(document_bytes))
    monkeypatch.setattr(
        "beacon.core.status._observe_repository",
        lambda _root: RepositoryEvidence(
            state="observed", commit="a" * 40, branch="release/v0.2.0", dirty=False
        ),
    )

    observation = observe_project_status(
        snapshot,
        manifest_path=tmp_path / "beacon.yaml",
        docs_root=tmp_path,
        observed_at="2026-08-10T19:00:00Z",
    )

    assert observation.observed_at == "2026-08-10T19:00:00Z"
    assert observation.repository.commit == "a" * 40
    assert [source.state for source in observation.sources] == ["fresh", "fresh"]
    assert [source.path for source in observation.sources] == [
        "beacon.yaml",
        "docs/roadmap.md",
    ]


def test_observation_reports_stale_and_missing_without_leaking_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "beacon.yaml"
    manifest.write_bytes(b"changed")
    snapshot = _snapshot("0" * 64, "1" * 64)
    monkeypatch.setattr(
        "beacon.core.status._observe_repository",
        lambda _root: RepositoryEvidence(state="unavailable"),
    )

    observation = observe_project_status(
        snapshot,
        manifest_path=manifest,
        docs_root=tmp_path,
        observed_at="2026-08-10T19:00:00Z",
    )
    payload = build_status_payload(
        snapshot,
        snapshot_sha256="2" * 64,
        observation=observation,
    )

    assert payload["observed"]["freshness"]["state"] == "stale"
    assert payload["observed"]["freshness"]["stale"] == 1
    assert payload["observed"]["freshness"]["missing"] == 1
    assert str(tmp_path) not in str(payload)


def test_observation_bounds_source_rereads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = tmp_path / "beacon.yaml"
    manifest.write_bytes(b"too large")
    snapshot = _snapshot(_sha(b"too large"), "1" * 64)
    monkeypatch.setattr(
        "beacon.core.status._observe_repository",
        lambda _root: RepositoryEvidence(state="unavailable"),
    )

    observation = observe_project_status(
        snapshot,
        manifest_path=manifest,
        docs_root=tmp_path,
        observed_at="2026-08-10T19:00:00Z",
        limits=ResourceLimits(manifest_bytes=4),
    )

    assert observation.sources[0].state == "unavailable"


def test_observation_refuses_unstable_double_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "beacon.yaml"
    manifest.write_bytes(b"first")
    snapshot = _snapshot(_sha(b"first"), "1" * 64)
    reads = iter((b"first", b"changed", b"document", b"document"))
    monkeypatch.setattr(
        "beacon.core.status.read_bytes_bounded",
        lambda *_args, **_kwargs: next(reads),
    )
    monkeypatch.setattr(
        "beacon.core.status._observe_repository",
        lambda _root: RepositoryEvidence(state="unavailable"),
    )

    observation = observe_project_status(
        snapshot,
        manifest_path=manifest,
        docs_root=tmp_path,
        observed_at="2026-08-10T19:00:00Z",
    )

    assert observation.sources[0].state == "unavailable"


def test_status_payload_separates_declared_observed_and_trust() -> None:
    snapshot = _snapshot("0" * 64, "1" * 64)
    observation = StatusObservation(
        mode="startup",
        observed_at="2026-08-10T19:00:00Z",
        repository=RepositoryEvidence(state="observed", commit="a" * 40, branch="main", dirty=True),
        sources=(),
    )

    payload = build_status_payload(
        snapshot,
        snapshot_sha256="2" * 64,
        observation=observation,
    )

    assert payload["declared"]["active_work"]["title"] == "Verified status"
    assert payload["observed"]["repository"] == {
        "state": "observed",
        "commit": "a" * 40,
        "dirty": True,
    }
    assert payload["trust"]["assertion"] == "self_reported"
    assert payload["trust"]["signed"] is False


def test_status_payload_has_deterministic_unavailable_fallback() -> None:
    payload = build_status_payload(_snapshot("0" * 64, "1" * 64), snapshot_sha256="2" * 64)

    assert payload["observed"] == {
        "mode": "not_collected",
        "observed_at": None,
        "repository": {"state": "unavailable"},
        "freshness": {
            "state": "unavailable",
            "checked": 0,
            "fresh": 0,
            "stale": 0,
            "missing": 0,
            "unavailable": 0,
            "sources": [],
        },
    }


def test_status_payload_validates_against_published_schema() -> None:
    payload = build_status_payload(_snapshot("0" * 64, "1" * 64), snapshot_sha256="2" * 64)
    schema_path = (
        Path(__file__).resolve().parents[1] / "docs" / "schemas" / "beacon-status-1.1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        payload
    )


def test_repository_observation_degrades_when_git_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("beacon.core.status.shutil.which", lambda _name: None)
    from beacon.core.status import _observe_repository

    assert _observe_repository(tmp_path) == RepositoryEvidence(state="unavailable")


def test_repository_observation_redacts_git_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("beacon.core.status.shutil.which", lambda _name: "git")

    def fail(*_args: object, **_kwargs: object) -> str:
        raise subprocess.CalledProcessError(1, ["git"], stderr="private detail")

    monkeypatch.setattr("beacon.core.status._git", fail)
    from beacon.core.status import _observe_repository

    assert _observe_repository(tmp_path) == RepositoryEvidence(state="unavailable")


@pytest.mark.parametrize("commit_length", [40, 64])
def test_repository_observation_uses_one_porcelain_status_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit_length: int
) -> None:
    monkeypatch.setattr("beacon.core.status.shutil.which", lambda _name: "git")
    calls: list[tuple[str, ...]] = []

    def git_status(_executable: str, _root: Path, *arguments: str) -> str:
        calls.append(arguments)
        return "# branch.oid " + "a" * commit_length + "\n# branch.head main\n1 .M N... src/a.py"

    monkeypatch.setattr("beacon.core.status._git", git_status)
    from beacon.core.status import _observe_repository

    assert _observe_repository(tmp_path) == RepositoryEvidence(
        state="observed", commit="a" * commit_length, branch="main", dirty=True
    )
    assert calls == [("status", "--porcelain=v2", "--branch", "--untracked-files=normal")]
