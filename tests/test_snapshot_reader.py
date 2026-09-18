"""Tests for the snapshot reader and snapshot-only serving.

Pins plan §8 Step 1's gate: a server built from a loaded snapshot returns
answers identical to a server built from the live manifest, and the reader
refuses malformed, foreign-version, or error-carrying snapshots.
"""

from __future__ import annotations

import json
import sys
import types
import unittest.mock as mock
from pathlib import Path

import pytest
from typer.testing import CliRunner

from beacon.build.snapshot import (
    SNAPSHOT_READER_BAD_VERSION,
    SNAPSHOT_READER_CARRIES_ERRORS,
    SNAPSHOT_READER_MALFORMED,
    SnapshotReadError,
    load_snapshot,
    reserialize_snapshot,
)
from beacon.core.snapshot import (
    CONTENT_METADATA_ONLY,
    build_snapshot,
    metadata_only_snapshot,
    write_snapshot_atomic,
)
from beacon.main import app
from beacon.provider.manifest_provider import ManifestBeaconProvider

runner = CliRunner()


def _patch_server():
    fake_framework = types.ModuleType("archolith_mcp_framework")
    fake_framework.run_server = lambda mcp: None
    fake_server = types.ModuleType("beacon.mcp.server")
    fake_server.mcp = object()
    return mock.patch.dict(
        sys.modules,
        {
            "archolith_mcp_framework": fake_framework,
            "beacon.mcp.server": fake_server,
        },
    )


_VALID_MANIFEST = """\
beacon_version: "0.1"
project:
  name: fixture
  description: A fixture project for the snapshot reader.
  status: experimental
purpose:
  one_sentence: A fixture project for the snapshot reader.
audiences:
  - coding-agents
core_concepts:
  - id: fixture-concept
    name: Fixture concept
    definition: The one concept the fixture defines.
    status: current
    sources:
      - type: doc
        title: Read me
        path: README.md
        status: current
canonical_docs:
  - path: README.md
    role: reference
    status: current
    title: README
guardrails:
  - id: no-net
    rule: No network access is required.
    severity: low
build_and_test:
  test: pytest -q
"""


def _fixture(tmp_path: Path) -> Path:
    (tmp_path / "beacon.yaml").write_text(_VALID_MANIFEST, encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Fixture\n\n## Usage\nRun the fixture.\n", encoding="utf-8"
    )
    return tmp_path / "beacon.yaml"


def _export_snapshot(manifest_path: Path) -> Path:
    snap = build_snapshot(manifest_path, docs_root=manifest_path.parent)
    out = manifest_path.parent / "beacon.snapshot.json"
    write_snapshot_atomic(out, snap)
    return out


def test_reader_round_trips_canonical_bytes(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    snapshot_path = _export_snapshot(manifest)
    loaded = load_snapshot(snapshot_path)
    assert loaded.project.name == "fixture"
    assert loaded.content_mode == "embedded"
    # Canonical reserialization is byte-identical to the exported artifact.
    assert reserialize_snapshot(loaded) == snapshot_path.read_bytes()


def test_snapshot_served_answers_match_manifest_served(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    snapshot_path = _export_snapshot(manifest)
    loaded = load_snapshot(snapshot_path)

    from_paths = ManifestBeaconProvider.from_paths(
        manifest_path=manifest, docs_root=manifest.parent
    )
    from_snapshot = ManifestBeaconProvider.from_snapshot(loaded)

    assert from_paths.project_overview().summary == from_snapshot.project_overview().summary
    a = from_paths.agent_onboarding(task_hint="usage")
    b = from_snapshot.agent_onboarding(task_hint="usage")
    assert a.orientation == b.orientation
    assert a.relevant_files == b.relevant_files
    assert a.concepts_to_understand == b.concepts_to_understand
    sa = from_paths.search(query="usage")
    sb = from_snapshot.search(query="usage")
    assert [h.title for h in sa.results] == [h.title for h in sb.results]
    assert [h.path for h in sa.results] == [h.path for h in sb.results]
    ca = from_paths.explain_concept(concept="fixture-concept")
    cb = from_snapshot.explain_concept(concept="fixture-concept")
    assert ca.definition == cb.definition
    assert ca.sources == cb.sources


def test_metadata_only_snapshot_is_refused_for_serving(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    snap = build_snapshot(manifest, docs_root=manifest.parent)
    out = tmp_path / "metadata.json"
    write_snapshot_atomic(out, metadata_only_snapshot(snap))
    loaded = load_snapshot(out)
    assert loaded.content_mode == CONTENT_METADATA_ONLY
    with pytest.raises(SnapshotReadError):
        ManifestBeaconProvider.from_snapshot(loaded)


def test_reader_refuses_foreign_version_and_errors(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    snapshot_path = _export_snapshot(manifest)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    payload["beacon_snapshot_version"] = "9.9"
    bad_version = tmp_path / "bad-version.json"
    bad_version.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SnapshotReadError) as err:
        load_snapshot(bad_version)
    assert err.value.code == SNAPSHOT_READER_BAD_VERSION

    payload["beacon_snapshot_version"] = "1.0"
    payload["validation"]["errors"] = 1
    carries = tmp_path / "carries-errors.json"
    carries.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SnapshotReadError) as err:
        load_snapshot(carries)
    assert err.value.code == SNAPSHOT_READER_CARRIES_ERRORS

    payload["validation"]["errors"] = 0
    payload["documents"] = "not-a-list"
    malformed = tmp_path / "malformed.json"
    malformed.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SnapshotReadError) as err:
        load_snapshot(malformed)
    assert err.value.code == SNAPSHOT_READER_MALFORMED


def test_serve_snapshot_flag_starts_snapshot_only(tmp_path: Path) -> None:
    """`beacon serve --snapshot` validates the snapshot and starts serving."""
    manifest = _fixture(tmp_path)
    snapshot_path = _export_snapshot(manifest)

    with _patch_server():
        result = runner.invoke(app, ["serve", "--snapshot", str(snapshot_path)])
    assert result.exit_code == 0

    # A foreign artifact is refused before the server starts.
    bad = tmp_path / "bad.json"
    bad.write_text('{"beacon_snapshot_version": "0.4"}', encoding="utf-8")
    result = runner.invoke(app, ["serve", "--snapshot", str(bad)])
    assert result.exit_code == 2
