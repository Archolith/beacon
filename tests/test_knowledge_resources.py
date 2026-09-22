"""Tests for static concept and guardrail companion resources."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from beacon import __version__
from beacon.core.knowledge_resources import build_knowledge_catalogs
from beacon.core.limits import LIMIT_SNAPSHOT_BYTES, LimitError
from beacon.core.policy import PolicyEvaluation
from beacon.core.snapshot import (
    CONTENT_EMBEDDED,
    CONTENT_METADATA_ONLY,
    SNAPSHOT_VERSION,
    Snapshot,
    SnapshotGenerator,
    SnapshotManifest,
    SnapshotProject,
    SnapshotValidation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPO_ROOT / "docs" / "schemas"


def _source() -> dict[str, object]:
    return {
        "type": "file",
        "title": "Résumé source",
        "path": "src/contracts.py",
        "url": "",
        "line_start": 1,
        "line_end": 3,
        "status": "current",
    }


def _concept(
    logical_id: str = "answer/contract", *, definition: str = "Traceable answers 🛰️"
) -> dict[str, object]:
    return {
        "id": logical_id,
        "name": "Answer Contract",
        "definition": definition,
        "why_it_exists": "Make claims reviewable.",
        "status": "current",
        "related_concepts": [],
        "implementation_locations": ["src/contracts.py"],
        "sources": [_source()],
    }


def _guardrail(
    logical_id: str = "preserve/contract", *, rule: str = "Keep the contract stable."
) -> dict[str, object]:
    return {
        "id": logical_id,
        "rule": rule,
        "scope": "public_api",
        "severity": "high",
        "applies_to": ["src/contracts.py"],
        "sources": [_source()],
    }


def _snapshot(
    *,
    concepts: object | None = None,
    guardrails: object | None = None,
    byte_ceiling: int = 50 * 1024 * 1024,
) -> Snapshot:
    data: dict[str, object] = {}
    if concepts is not None:
        data["core_concepts"] = concepts
    if guardrails is not None:
        data["guardrails"] = guardrails
    return Snapshot(
        beacon_snapshot_version=SNAPSHOT_VERSION,
        generator=SnapshotGenerator("archolith-beacon", __version__),
        content_mode=CONTENT_EMBEDDED,
        project=SnapshotProject("knowledge-project", "current"),
        manifest=SnapshotManifest("0.1", "a" * 64, data),
        documents=(),
        validation=SnapshotValidation(0, 0),
        policy=PolicyEvaluation(servable=True, publishable=True),
        byte_ceiling=byte_ceiling,
    )


def test_catalogs_advertise_exact_budgets_hashes_and_full_records() -> None:
    snapshot_sha = "c" * 64
    catalogs = build_knowledge_catalogs(
        _snapshot(concepts=[_concept()], guardrails=[_guardrail()]),
        snapshot_sha256=snapshot_sha,
    )

    concept_index = json.loads(catalogs.concepts.index_body)
    assert concept_index["concept_index_version"] == "1.0"
    assert concept_index["snapshot"] == {
        "sha256": snapshot_sha,
        "schema_version": SNAPSHOT_VERSION,
    }
    concept_entry = concept_index["concepts"][0]
    assert concept_entry["resource_id"].startswith("k1-")
    assert "answer/contract" not in concept_entry["resource_id"]
    concept_resource = catalogs.concepts.resources[0]
    assert concept_entry["bytes"] == len(concept_resource.body)
    assert concept_entry["sha256"] == hashlib.sha256(concept_resource.body).hexdigest()
    assert json.loads(concept_resource.body)["concept"] == _concept()

    guardrail_index = json.loads(catalogs.guardrails.index_body)
    assert guardrail_index["guardrail_index_version"] == "1.0"
    guardrail_entry = guardrail_index["guardrails"][0]
    assert guardrail_entry["resource_id"].startswith("g1-")
    assert "preserve/contract" not in guardrail_entry["resource_id"]
    guardrail_resource = catalogs.guardrails.resources[0]
    assert guardrail_entry["bytes"] == len(guardrail_resource.body)
    assert guardrail_entry["sha256"] == hashlib.sha256(guardrail_resource.body).hexdigest()
    assert json.loads(guardrail_resource.body)["guardrail"] == _guardrail()


def test_catalogs_and_resources_validate_against_published_schemas() -> None:
    catalogs = build_knowledge_catalogs(
        _snapshot(concepts=[_concept()], guardrails=[_guardrail()]),
        snapshot_sha256="c" * 64,
    )
    cases = (
        ("beacon-concept-index-1.0.schema.json", catalogs.concepts.index_body),
        ("beacon-concept-resource-1.0.schema.json", catalogs.concepts.resources[0].body),
        ("beacon-guardrail-index-1.0.schema.json", catalogs.guardrails.index_body),
        ("beacon-guardrail-resource-1.0.schema.json", catalogs.guardrails.resources[0].body),
    )
    for schema_name, body in cases:
        schema = json.loads((SCHEMA_ROOT / schema_name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(json.loads(body), schema)


def test_scopeless_guardrail_builds_and_validates_against_published_schemas() -> None:
    """``scope`` is optional in the loader (default ``""``); the catalog must accept it."""
    scopeless = _guardrail() | {"scope": ""}
    catalogs = build_knowledge_catalogs(
        _snapshot(concepts=[], guardrails=[scopeless]),
        snapshot_sha256="c" * 64,
    )
    index = json.loads(catalogs.guardrails.index_body)
    assert index["guardrails"][0]["scope"] == ""
    assert json.loads(catalogs.guardrails.resources[0].body)["guardrail"] == scopeless
    for schema_name, body in (
        ("beacon-guardrail-index-1.0.schema.json", catalogs.guardrails.index_body),
        ("beacon-guardrail-resource-1.0.schema.json", catalogs.guardrails.resources[0].body),
    ):
        schema = json.loads((SCHEMA_ROOT / schema_name).read_text(encoding="utf-8"))
        jsonschema.validate(json.loads(body), schema)


def test_catalogs_are_byte_deterministic() -> None:
    snapshot = _snapshot(concepts=[_concept()], guardrails=[_guardrail()])
    first = build_knowledge_catalogs(snapshot, snapshot_sha256="c" * 64)
    second = build_knowledge_catalogs(snapshot, snapshot_sha256="c" * 64)
    assert first == second


def test_resource_ids_track_logical_identity_not_record_text() -> None:
    before = build_knowledge_catalogs(
        _snapshot(concepts=[_concept()], guardrails=[_guardrail()]),
        snapshot_sha256="c" * 64,
    )
    after = build_knowledge_catalogs(
        _snapshot(
            concepts=[_concept(definition="Changed")],
            guardrails=[_guardrail(rule="Changed")],
        ),
        snapshot_sha256="d" * 64,
    )
    assert before.concepts.resources[0].id == after.concepts.resources[0].id
    assert before.guardrails.resources[0].id == after.guardrails.resources[0].id
    assert before.concepts.resources[0].sha256 != after.concepts.resources[0].sha256
    assert before.guardrails.resources[0].sha256 != after.guardrails.resources[0].sha256


def test_resource_ids_change_with_logical_identity() -> None:
    before = build_knowledge_catalogs(
        _snapshot(concepts=[_concept()], guardrails=[_guardrail()]),
        snapshot_sha256="c" * 64,
    )
    after = build_knowledge_catalogs(
        _snapshot(concepts=[_concept("other")], guardrails=[_guardrail("other")]),
        snapshot_sha256="c" * 64,
    )
    assert before.concepts.resources[0].id != after.concepts.resources[0].id
    assert before.guardrails.resources[0].id != after.guardrails.resources[0].id


def test_missing_collections_produce_valid_empty_indexes() -> None:
    catalogs = build_knowledge_catalogs(_snapshot(), snapshot_sha256="c" * 64)
    assert json.loads(catalogs.concepts.index_body)["concepts"] == []
    assert json.loads(catalogs.guardrails.index_body)["guardrails"] == []
    assert catalogs.concepts.resources == ()
    assert catalogs.guardrails.resources == ()


def test_explicit_null_collection_is_refused() -> None:
    snapshot = _snapshot()
    invalid = replace(
        snapshot,
        manifest=replace(snapshot.manifest, data={"core_concepts": None}),
    )
    with pytest.raises(ValueError, match="core_concepts must be a list"):
        build_knowledge_catalogs(invalid, snapshot_sha256="c" * 64)


@pytest.mark.parametrize(
    ("concepts", "guardrails", "message"),
    (
        ({}, [], "core_concepts must be a list"),
        ([], {}, "guardrails must be a list"),
        ([None], [], "concept record must be a mapping"),
        ([], [None], "guardrail record must be a mapping"),
        ([_concept() | {"name": ""}], [], "concept name"),
        ([], [_guardrail() | {"id": ""}], "guardrail id"),
        ([], [_guardrail() | {"severity": " "}], "guardrail severity"),
        ([], [_guardrail() | {"scope": None}], "guardrail scope must be a string"),
    ),
)
def test_malformed_collections_and_selector_fields_are_refused(
    concepts: object, guardrails: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_knowledge_catalogs(
            _snapshot(concepts=concepts, guardrails=guardrails),
            snapshot_sha256="c" * 64,
        )


@pytest.mark.parametrize(
    ("concepts", "guardrails", "message"),
    (
        ([_concept(), _concept()], [], "duplicate concept logical id"),
        ([], [_guardrail(), _guardrail()], "duplicate guardrail logical id"),
    ),
)
def test_duplicate_logical_ids_are_refused(
    concepts: object, guardrails: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_knowledge_catalogs(
            _snapshot(concepts=concepts, guardrails=guardrails),
            snapshot_sha256="c" * 64,
        )


@pytest.mark.parametrize(
    ("concepts", "guardrails", "message"),
    (
        ([_concept() | {"unexpected": True}], [], "concept record has invalid fields"),
        ([], [_guardrail() | {"sources": [{"path": "incomplete"}]}], "guardrail source"),
        ([_concept() | {"related_concepts": [1]}], [], "concept related_concepts"),
        (
            [],
            [_guardrail() | {"sources": [_source() | {"line_end": 0}]}],
            "guardrail source line_end",
        ),
    ),
)
def test_schema_invalid_full_records_are_refused_before_serialization(
    concepts: object, guardrails: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_knowledge_catalogs(
            _snapshot(concepts=concepts, guardrails=guardrails),
            snapshot_sha256="c" * 64,
        )


@pytest.mark.parametrize("snapshot_sha", ("", "C" * 64, "g" * 64, "c" * 63))
def test_invalid_snapshot_lineage_is_refused(snapshot_sha: str) -> None:
    with pytest.raises(ValueError, match="snapshot sha256"):
        build_knowledge_catalogs(_snapshot(), snapshot_sha256=snapshot_sha)


def test_non_1_0_snapshot_schema_is_refused() -> None:
    snapshot = replace(_snapshot(), beacon_snapshot_version="2.0")
    with pytest.raises(ValueError, match="snapshot schema 1.0"):
        build_knowledge_catalogs(snapshot, snapshot_sha256="c" * 64)


def test_metadata_only_snapshot_is_refused() -> None:
    snapshot = replace(_snapshot(), content_mode=CONTENT_METADATA_ONLY)
    with pytest.raises(ValueError, match="embedded content mode"):
        build_knowledge_catalogs(snapshot, snapshot_sha256="c" * 64)


def test_catalogs_obey_snapshot_byte_ceiling() -> None:
    with pytest.raises(LimitError) as excinfo:
        build_knowledge_catalogs(
            _snapshot(concepts=[_concept()], guardrails=[_guardrail()], byte_ceiling=32),
            snapshot_sha256="c" * 64,
        )
    assert excinfo.value.code == LIMIT_SNAPSHOT_BYTES
