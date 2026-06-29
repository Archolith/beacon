"""Offline tests for beacon-core: loader, validator, doc_index, schema."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from beacon.core.loader import ManifestError, load_beacon_manifest, parse_manifest
from beacon.core.schema import BeaconManifest
from beacon.core.validator import (
    ManifestValidationError,
    require_valid_manifest,
    validate_beacon_manifest,
)
from beacon.core.doc_index import DocIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_RAW = {
    "beacon_version": "0.1",
    "project": {
        "name": "test-project",
        "description": "A test project for unit testing Beacon.",
    },
    "canonical_docs": [{"path": "README.md", "role": "entrypoint", "status": "current"}],
    "core_concepts": [
        {
            "id": "concept_a",
            "name": "Concept A",
            "description": "The first concept.",
            "status": "current",
        }
    ],
}


def _write_manifest(tmp_path: Path, data: dict) -> Path:
    manifest_file = tmp_path / "beacon.yaml"
    manifest_file.write_text(yaml.dump(data), encoding="utf-8")
    return manifest_file


def _write_readme(tmp_path: Path, content: str = "# Hello\n\nSome text.") -> None:
    (tmp_path / "README.md").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


def test_load_minimal_manifest(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    manifest_file = _write_manifest(tmp_path, MINIMAL_RAW)
    manifest = load_beacon_manifest(manifest_file)
    assert isinstance(manifest, BeaconManifest)
    assert manifest.project.name == "test-project"
    assert manifest.beacon_version == "0.1"


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="not found"):
        load_beacon_manifest(tmp_path / "nonexistent.yaml")


def test_load_invalid_yaml_root_raises(tmp_path: Path) -> None:
    bad_file = tmp_path / "beacon.yaml"
    bad_file.write_text("- this\n- is\n- a list\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="mapping"):
        load_beacon_manifest(bad_file)


def test_loader_parses_concepts(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    manifest_file = _write_manifest(tmp_path, MINIMAL_RAW)
    manifest = load_beacon_manifest(manifest_file)
    assert len(manifest.core_concepts) == 1
    assert manifest.core_concepts[0].id == "concept_a"
    assert manifest.core_concepts[0].definition == "The first concept."


def test_loader_parses_guardrails(tmp_path: Path) -> None:
    raw = dict(MINIMAL_RAW)
    raw["guardrails"] = [
        {"id": "g1", "rule": "Never do X.", "severity": "high", "scope": "schema"}
    ]
    _write_readme(tmp_path)
    manifest = parse_manifest(raw)
    assert len(manifest.guardrails) == 1
    assert manifest.guardrails[0].id == "g1"
    assert manifest.guardrails[0].severity == "high"


def test_loader_concept_requires_id(tmp_path: Path) -> None:
    raw = dict(MINIMAL_RAW)
    raw["core_concepts"] = [{"name": "Missing ID", "description": "no id"}]
    with pytest.raises(ManifestError, match="id"):
        parse_manifest(raw)


def test_loader_doc_requires_path(tmp_path: Path) -> None:
    raw = dict(MINIMAL_RAW)
    raw["canonical_docs"] = [{"role": "entrypoint"}]
    with pytest.raises(ManifestError, match="path"):
        parse_manifest(raw)


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------


def test_validator_clean_manifest(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    manifest_file = _write_manifest(tmp_path, MINIMAL_RAW)
    manifest = load_beacon_manifest(manifest_file)
    report = validate_beacon_manifest(manifest, docs_root=tmp_path)
    assert report.ok, f"Unexpected errors: {report.errors}"


def test_validator_missing_project_name() -> None:
    raw = dict(MINIMAL_RAW)
    raw["project"] = {"name": "", "description": "desc"}
    manifest = parse_manifest(raw)
    report = validate_beacon_manifest(manifest)
    errors = [e.where for e in report.errors]
    assert "project.name" in errors


def test_validator_missing_description() -> None:
    raw = dict(MINIMAL_RAW)
    raw["project"] = {"name": "ok", "description": ""}
    manifest = parse_manifest(raw)
    report = validate_beacon_manifest(manifest)
    errors = [e.where for e in report.errors]
    assert "project.description" in errors


def test_validator_duplicate_concept_id() -> None:
    raw = dict(MINIMAL_RAW)
    raw["core_concepts"] = [
        {"id": "dup", "name": "A", "description": "First"},
        {"id": "dup", "name": "B", "description": "Second"},
    ]
    manifest = parse_manifest(raw)
    report = validate_beacon_manifest(manifest)
    assert not report.ok
    assert any("duplicate concept id" in e.message for e in report.errors)


def test_validator_missing_canonical_docs() -> None:
    raw = dict(MINIMAL_RAW)
    raw["canonical_docs"] = []
    manifest = parse_manifest(raw)
    report = validate_beacon_manifest(manifest)
    assert not report.ok
    assert any("canonical_docs" in e.where for e in report.errors)


def test_validator_dangling_doc_path(tmp_path: Path) -> None:
    """A canonical doc whose file does not exist is an error when docs_root given."""
    manifest_file = _write_manifest(tmp_path, MINIMAL_RAW)
    manifest = load_beacon_manifest(manifest_file)
    # README.md is not written; should error
    report = validate_beacon_manifest(manifest, docs_root=tmp_path)
    assert not report.ok
    assert any("does not exist" in e.message for e in report.errors)


def test_require_valid_manifest_raises_on_error() -> None:
    raw = dict(MINIMAL_RAW)
    raw["project"] = {"name": "", "description": ""}
    manifest = parse_manifest(raw)
    with pytest.raises(ManifestValidationError):
        require_valid_manifest(manifest)


def test_validator_unknown_status_is_warning() -> None:
    raw = dict(MINIMAL_RAW)
    raw["core_concepts"] = [
        {"id": "x", "name": "X", "description": "d", "status": "banana"}
    ]
    manifest = parse_manifest(raw)
    report = validate_beacon_manifest(manifest)
    assert report.ok  # warning only, not error
    assert any("unknown status" in w.message for w in report.warnings)


# ---------------------------------------------------------------------------
# Doc index tests
# ---------------------------------------------------------------------------

SAMPLE_MD = textwrap.dedent("""\
    # Overview

    This is the introduction.

    ## Setup

    Run the install command first.

    ### Advanced Setup

    Only for power users.

    ## Usage

    Call the main function.
""")


def test_doc_index_produces_chunks(tmp_path: Path) -> None:
    doc_file = tmp_path / "guide.md"
    doc_file.write_text(SAMPLE_MD, encoding="utf-8")
    from beacon.core.schema import BeaconDoc

    docs = [BeaconDoc(path="guide.md", role="reference", status="current")]
    index = DocIndex.from_docs(docs, docs_root=tmp_path)
    assert len(index.chunks) >= 3  # Overview, Setup, Advanced Setup, Usage


def test_doc_index_chunks_have_line_ranges(tmp_path: Path) -> None:
    doc_file = tmp_path / "guide.md"
    doc_file.write_text(SAMPLE_MD, encoding="utf-8")
    from beacon.core.schema import BeaconDoc

    docs = [BeaconDoc(path="guide.md", role="reference", status="current")]
    index = DocIndex.from_docs(docs, docs_root=tmp_path)
    for chunk in index.chunks:
        assert chunk.start_line >= 1
        assert chunk.end_line >= chunk.start_line


def test_doc_index_search_returns_hits(tmp_path: Path) -> None:
    doc_file = tmp_path / "guide.md"
    doc_file.write_text(SAMPLE_MD, encoding="utf-8")
    from beacon.core.schema import BeaconDoc

    docs = [BeaconDoc(path="guide.md", role="reference", status="current")]
    index = DocIndex.from_docs(docs, docs_root=tmp_path)
    hits = index.search("install setup")
    assert hits, "Expected at least one search hit"
    top_chunk, top_score = hits[0]
    assert "setup" in top_chunk.text.lower() or "install" in top_chunk.text.lower()


def test_doc_index_search_empty_query(tmp_path: Path) -> None:
    doc_file = tmp_path / "guide.md"
    doc_file.write_text(SAMPLE_MD, encoding="utf-8")
    from beacon.core.schema import BeaconDoc

    docs = [BeaconDoc(path="guide.md", role="reference", status="current")]
    index = DocIndex.from_docs(docs, docs_root=tmp_path)
    assert index.search("") == []


def test_doc_index_missing_file_skipped(tmp_path: Path) -> None:
    from beacon.core.schema import BeaconDoc

    docs = [BeaconDoc(path="missing.md", role="reference", status="current")]
    index = DocIndex.from_docs(docs, docs_root=tmp_path)
    assert len(index.chunks) == 0
