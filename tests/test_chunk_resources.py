"""Tests for the snapshot-1.0 companion chunk resource contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from beacon import __version__
from beacon.core.chunk_resources import (
    CHUNK_INDEX_VERSION,
    CHUNK_RESOURCE_VERSION,
    build_chunk_catalog,
)
from beacon.core.limits import LIMIT_SNAPSHOT_BYTES, LimitError
from beacon.core.policy import PolicyEvaluation
from beacon.core.snapshot import (
    CONTENT_EMBEDDED,
    CONTENT_METADATA_ONLY,
    SNAPSHOT_VERSION,
    Snapshot,
    SnapshotChunk,
    SnapshotDocument,
    SnapshotGenerator,
    SnapshotManifest,
    SnapshotProject,
    SnapshotValidation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_SCHEMA = REPO_ROOT / "docs" / "schemas" / "beacon-chunk-index-1.0.schema.json"
RESOURCE_SCHEMA = REPO_ROOT / "docs" / "schemas" / "beacon-chunk-resource-1.0.schema.json"


def _snapshot(
    text: str = "# Héading\n\nBody 🛰️\n",
    *,
    line_start: int = 1,
    line_end: int = 3,
    byte_ceiling: int = 50 * 1024 * 1024,
) -> Snapshot:
    return Snapshot(
        beacon_snapshot_version=SNAPSHOT_VERSION,
        generator=SnapshotGenerator("archolith-beacon", __version__),
        content_mode=CONTENT_EMBEDDED,
        project=SnapshotProject("chunks-project", "current"),
        manifest=SnapshotManifest("0.1", "a" * 64, {"project": {"name": "chunks-project"}}),
        documents=(
            SnapshotDocument(
                path="docs/guide.md",
                role="entrypoint",
                status="current",
                title="Guide",
                source_sha256="b" * 64,
                chunks=(
                    SnapshotChunk(
                        heading_path=("Héading",),
                        line_start=line_start,
                        line_end=line_end,
                        text=text,
                    ),
                ),
            ),
        ),
        validation=SnapshotValidation(0, 0),
        policy=PolicyEvaluation(servable=True, publishable=True),
        byte_ceiling=byte_ceiling,
    )


def test_catalog_advertises_exact_budget_and_parent_context() -> None:
    snapshot_sha = "c" * 64
    catalog = build_chunk_catalog(_snapshot(), snapshot_sha256=snapshot_sha)
    index = json.loads(catalog.index_body)

    assert index["chunk_index_version"] == CHUNK_INDEX_VERSION
    assert index["snapshot"] == {"sha256": snapshot_sha, "schema_version": SNAPSHOT_VERSION}
    assert index["item_url_template"] == "/v1/chunks/{id}"
    assert index["count"] == 1
    document = index["documents"][0]
    assert document["path"] == "docs/guide.md"
    entry = document["chunks"][0]
    assert entry["id"].startswith("c1-") and len(entry["id"]) == 35
    assert entry["parent_role"] == "entrypoint"
    assert entry["parent_status"] == "current"
    assert entry["text_bytes"] == len("# Héading\n\nBody 🛰️\n".encode())

    resource = catalog.resources[0]
    assert resource.id == entry["id"]
    assert entry["bytes"] == len(resource.body)
    assert resource.sha256 == hashlib.sha256(resource.body).hexdigest()
    body = json.loads(resource.body)
    assert body["chunk_resource_version"] == CHUNK_RESOURCE_VERSION
    assert body["snapshot_sha256"] == snapshot_sha
    assert body["text_bytes"] == entry["text_bytes"]
    assert body["text"] == "# Héading\n\nBody 🛰️\n"
    assert body["document"]["role"] == entry["parent_role"]
    assert body["document"]["status"] == entry["parent_status"]


def test_catalog_and_resource_validate_against_published_schemas() -> None:
    catalog = build_chunk_catalog(_snapshot(), snapshot_sha256="c" * 64)
    index_schema = json.loads(INDEX_SCHEMA.read_text(encoding="utf-8"))
    resource_schema = json.loads(RESOURCE_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(index_schema)
    jsonschema.Draft202012Validator.check_schema(resource_schema)
    jsonschema.validate(json.loads(catalog.index_body), index_schema)
    for resource in catalog.resources:
        jsonschema.validate(json.loads(resource.body), resource_schema)


def test_catalog_is_byte_deterministic() -> None:
    first = build_chunk_catalog(_snapshot(), snapshot_sha256="c" * 64)
    second = build_chunk_catalog(_snapshot(), snapshot_sha256="c" * 64)
    assert first.index_body == second.index_body
    assert first.resources == second.resources


def test_chunk_id_tracks_logical_location_not_body_text() -> None:
    before = build_chunk_catalog(_snapshot("first"), snapshot_sha256="c" * 64)
    after = build_chunk_catalog(_snapshot("second"), snapshot_sha256="d" * 64)
    assert before.resources[0].id == after.resources[0].id
    assert before.resources[0].sha256 != after.resources[0].sha256


def test_chunk_id_changes_when_location_changes() -> None:
    before = build_chunk_catalog(_snapshot(line_end=3), snapshot_sha256="c" * 64)
    after = build_chunk_catalog(_snapshot(line_end=4), snapshot_sha256="c" * 64)
    assert before.resources[0].id != after.resources[0].id


def test_metadata_only_snapshot_is_refused() -> None:
    with pytest.raises(ValueError, match="embedded content mode"):
        build_chunk_catalog(
            replace(_snapshot(), content_mode=CONTENT_METADATA_ONLY),
            snapshot_sha256="c" * 64,
        )


def test_missing_embedded_text_is_refused() -> None:
    snapshot = _snapshot()
    document = snapshot.documents[0]
    chunk = replace(document.chunks[0], text=None)
    invalid = replace(snapshot, documents=(replace(document, chunks=(chunk,)),))
    with pytest.raises(ValueError, match="missing text"):
        build_chunk_catalog(invalid, snapshot_sha256="c" * 64)


def test_catalog_obeys_snapshot_byte_ceiling() -> None:
    with pytest.raises(LimitError) as excinfo:
        build_chunk_catalog(_snapshot(byte_ceiling=32), snapshot_sha256="c" * 64)
    assert excinfo.value.code == LIMIT_SNAPSHOT_BYTES
