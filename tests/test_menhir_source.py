"""Tests for the Menhir evidence adapter (``beacon.sources.menhir``).

The evidence document is the build pipeline's tier-2 boundary; these tests
pin the fail-closed parsing contract, record shapes, citation provenance,
and byte-level determinism of ``collect()``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from beacon.sources.base import (
    CITATION_MEMORY,
    CITATION_PATH,
    KIND_MENHIR_DECISION,
    KIND_MENHIR_DOCUMENT,
    KIND_MENHIR_FILE,
    KIND_MENHIR_IDENTITY,
    KIND_MENHIR_LIFECYCLE,
    KIND_MENHIR_STRUCTURE,
)
from beacon.sources.menhir import (
    MenhirEvidenceCaps,
    MenhirEvidenceError,
    MenhirSourceAdapter,
    parse_evidence_document,
)


def _evidence(
    *,
    name: str = "fixture",
    description: str = "Fixture project for the evidence adapter.",
    fingerprint: str = "fp-123",
    documents: list[dict[str, str]] | None = None,
    files: list[dict[str, str]] | None = None,
    structure: dict[str, object] | None = None,
    decisions: list[dict[str, object]] | None = None,
    lifecycle: list[dict[str, object]] | None = None,
    version: str = "1.0",
    **overrides: object,
) -> dict[str, object]:
    project: dict[str, object] = {
        "name": name,
        "description": description,
        "primary_language": "python",
        "root": "/repo/fixture",
        "status": "experimental",
        "scan_fingerprint": fingerprint,
    }
    project.update(overrides)  # type: ignore[arg-type]
    payload: dict[str, object] = {"evidence_version": version, "project": project}
    if documents is not None:
        payload["documents"] = documents
    if files is not None:
        payload["files"] = files
    if structure is not None:
        payload["structure"] = structure
    if decisions is not None:
        payload["decisions"] = decisions
    if lifecycle is not None:
        payload["lifecycle"] = lifecycle
    return payload


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_collect_emits_expected_kinds_with_fingerprint_citations(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _evidence(
            documents=[{"path": "README.md", "title": "Read Me", "document_type": "generic"}],
            files=[{"path": "src/core.py", "role": "file", "description": "core"}],
            structure={"entities": {"file": 3}, "edges": {"IMPORTS": 2}},
            decisions=[
                {
                    "title": "Keep one view root",
                    "summary": "Exactly one previous view root is kept.",
                    "status": "current",
                    "implementation_locations": ["src/core.py"],
                }
            ],
            lifecycle=[
                {
                    "subject": "Keep one view root",
                    "status": "current",
                    "superseded_by": "",
                    "note": "",
                }
            ],
        ),
    )
    records = MenhirSourceAdapter(path).collect()
    kinds = {record.kind for record in records}
    assert {
        KIND_MENHIR_IDENTITY,
        KIND_MENHIR_STRUCTURE,
        KIND_MENHIR_DOCUMENT,
        KIND_MENHIR_FILE,
        KIND_MENHIR_DECISION,
        KIND_MENHIR_LIFECYCLE,
    } <= kinds
    identity = next(r for r in records if r.kind == KIND_MENHIR_IDENTITY)
    assert identity.payload["name"] == "fixture"
    assert identity.payload["description"] == "Fixture project for the evidence adapter."
    citation_values = {(c.kind, c.value) for c in identity.citations}
    assert (CITATION_MEMORY, "scan:fp-123") in citation_values
    document = next(r for r in records if r.kind == KIND_MENHIR_DOCUMENT)
    assert (CITATION_PATH, "README.md") in {(c.kind, c.value) for c in document.citations}
    decision = next(r for r in records if r.kind == KIND_MENHIR_DECISION)
    assert decision.payload["status"] == "current"
    assert decision.confidence == "medium"
    assert decision.confidence_reason


def test_collect_is_deterministic_and_sorts_documents(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _evidence(
            documents=[
                {"path": "docs/b.md", "title": "B", "document_type": "generic"},
                {"path": "docs/a.md", "title": "A", "document_type": "generic"},
            ]
        ),
    )
    adapter = MenhirSourceAdapter(path)
    first = adapter.collect()
    second = MenhirSourceAdapter(path).collect()
    assert first == second
    doc_paths = [r.payload["path"] for r in first if r.kind == KIND_MENHIR_DOCUMENT]
    assert doc_paths == sorted(doc_paths)


def test_minimal_evidence_emits_identity_only(tmp_path: Path) -> None:
    path = _write(tmp_path, _evidence())
    records = MenhirSourceAdapter(path).collect()
    assert [r.kind for r in records] == [KIND_MENHIR_IDENTITY]


@pytest.mark.parametrize(
    "payload",
    [
        _evidence(version="9.9"),
        _evidence(name=""),
        _evidence(description=""),
        _evidence(fingerprint=""),
        {"evidence_version": "1.0", "project": True},
    ],
)
def test_invalid_documents_fail_closed(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MenhirEvidenceError):
        MenhirSourceAdapter(path).collect()


def test_malformed_json_and_missing_file_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(MenhirEvidenceError):
        MenhirSourceAdapter(path).collect()
    with pytest.raises(MenhirEvidenceError):
        MenhirSourceAdapter(tmp_path / "absent.json").collect()


def test_section_caps_and_byte_cap_fail_closed(tmp_path: Path) -> None:
    payload = _evidence(
        documents=[
            {"path": f"docs/{i}.md", "title": "D", "document_type": "generic"} for i in range(3)
        ]
    )
    path = _write(tmp_path, payload)
    tight = MenhirEvidenceCaps(documents=2)
    with pytest.raises(MenhirEvidenceError):
        MenhirSourceAdapter(path, caps=tight).collect()

    big = tmp_path / "big.json"
    big.write_bytes(b'{"evidence_version":"1.0","pad":"' + b"x" * 4096 + b'"}')
    with pytest.raises(MenhirEvidenceError):
        MenhirSourceAdapter(big, caps=MenhirEvidenceCaps(evidence_bytes=128)).collect()


def test_bad_decision_and_lifecycle_status_fail_closed(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _evidence(decisions=[{"title": "X", "status": "invented"}]),
    )
    with pytest.raises(MenhirEvidenceError):
        parse_evidence_document(path.read_bytes())
    path2 = tmp_path / "evidence-lifecycle.json"
    path2.write_text(
        json.dumps(_evidence(lifecycle=[{"subject": "X", "status": "planned"}])), encoding="utf-8"
    )
    with pytest.raises(MenhirEvidenceError):
        parse_evidence_document(path2.read_bytes())


def test_parse_rejects_oversized_summary_and_paths(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _evidence(decisions=[{"title": "X", "summary": "y" * 5000}]),
    )
    with pytest.raises(MenhirEvidenceError):
        parse_evidence_document(
            path.read_bytes(), caps=MenhirEvidenceCaps(definition_max_chars=100)
        )
