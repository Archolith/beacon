"""Offline tests for beacon-core: loader, validator, doc_index, schema."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from beacon.core.doc_index import DocIndex
from beacon.core.loader import ManifestError, load_beacon_manifest, parse_manifest
from beacon.core.paths import (
    CODE_UNSAFE_CANONICAL_PATH,
    UnsafeCanonicalPath,
    resolve_canonical_path,
)
from beacon.core.schema import BeaconManifest
from beacon.core.validator import (
    ManifestValidationError,
    require_valid_manifest,
    validate_beacon_manifest,
)

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
    raw["guardrails"] = [{"id": "g1", "rule": "Never do X.", "severity": "high", "scope": "schema"}]
    _write_readme(tmp_path)
    manifest = parse_manifest(raw)
    assert len(manifest.guardrails) == 1
    assert manifest.guardrails[0].id == "g1"
    assert manifest.guardrails[0].severity == "high"


def test_loader_parses_optional_project_state() -> None:
    raw = dict(MINIMAL_RAW)
    raw["project_state"] = {
        "active_work": {
            "title": "Ship status",
            "summary": "Expose current work.",
            "next_step": "Add the route.",
            "sources": [{"path": "README.md", "line_start": 1, "line_end": 2}],
        },
        "recently_completed": [{"title": "Chunk retrieval"}],
        "blockers": [],
        "pending_decisions": [{"title": "Summary budget"}],
    }

    state = parse_manifest(raw).project_state

    assert state.active_work is not None
    assert state.active_work.title == "Ship status"
    assert state.active_work.next_step == "Add the route."
    assert state.active_work.sources[0].path == "README.md"
    assert state.recently_completed[0].title == "Chunk retrieval"
    assert state.pending_decisions[0].title == "Summary budget"


@pytest.mark.parametrize(
    ("project_state", "match"),
    (
        (None, "project_state must be a mapping"),
        ({"active_work": None}, "project_state.active_work must be a mapping"),
        ({"active_work": {}}, "needs a 'title'"),
        ({"blockers": None}, "project_state.blockers must be a list"),
        ({"blockers": [{"title": 42}]}, "title must be a string"),
    ),
)
def test_loader_rejects_malformed_project_state(project_state: object, match: str) -> None:
    raw = dict(MINIMAL_RAW)
    raw["project_state"] = project_state
    with pytest.raises(ManifestError, match=match):
        parse_manifest(raw)


def test_loader_bounds_project_state_items_and_text() -> None:
    raw = dict(MINIMAL_RAW)
    raw["project_state"] = {"blockers": [{"title": "x"}] * 65}
    with pytest.raises(ManifestError, match="at most 64 items"):
        parse_manifest(raw)

    raw["project_state"] = {"active_work": {"title": "x" * 513}}
    with pytest.raises(ManifestError, match="at most 512 characters"):
        parse_manifest(raw)


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
# Loader strict typing — no scalar/list coercion to str, no raw ValueError
# ---------------------------------------------------------------------------


def test_loader_accepts_typed_string_values(tmp_path: Path) -> None:
    raw = dict(MINIMAL_RAW)
    raw["core_concepts"] = [
        {
            "id": "c",
            "name": "C",
            "description": "def",
            "sources": [{"type": "doc", "path": "a.md", "line_start": 1, "line_end": 5}],
        }
    ]
    manifest = parse_manifest(raw)
    src = manifest.core_concepts[0].sources[0]
    assert src.line_start == 1
    assert src.line_end == 5
    assert src.type == "doc"


def test_loader_rejects_non_string_project_name() -> None:
    raw = dict(MINIMAL_RAW)
    raw["project"] = {"name": 123, "description": "d"}
    with pytest.raises(ManifestError, match="project.name"):
        parse_manifest(raw)


def test_loader_rejects_bool_beacon_version() -> None:
    raw = dict(MINIMAL_RAW)
    raw["beacon_version"] = True
    with pytest.raises(ManifestError, match="beacon_version"):
        parse_manifest(raw)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("beacon_version", None, "beacon_version"),
        ("audiences", None, "string or list"),
        ("purpose", None, "purpose must be a mapping"),
    ],
)
def test_loader_rejects_explicit_null(field: str, value: object, match: str) -> None:
    raw = dict(MINIMAL_RAW)
    raw[field] = value
    with pytest.raises(ManifestError, match=match):
        parse_manifest(raw)


def test_loader_rejects_non_string_list_element() -> None:
    raw = dict(MINIMAL_RAW)
    raw["audiences"] = ["agents", 42]
    with pytest.raises(ManifestError, match="non-string"):
        parse_manifest(raw)


def test_loader_rejects_non_string_definition() -> None:
    raw = dict(MINIMAL_RAW)
    raw["core_concepts"] = [{"id": "c", "name": "C", "description": ["not a string"]}]
    with pytest.raises(ManifestError, match="definition"):
        parse_manifest(raw)


def test_loader_rejects_line_start_bool() -> None:
    raw = dict(MINIMAL_RAW)
    raw["core_concepts"] = [
        {"id": "c", "name": "C", "description": "d", "sources": [{"line_start": True}]}
    ]
    with pytest.raises(ManifestError, match="line_start"):
        parse_manifest(raw)


def test_loader_rejects_non_positive_line() -> None:
    raw = dict(MINIMAL_RAW)
    raw["core_concepts"] = [
        {"id": "c", "name": "C", "description": "d", "sources": [{"line_start": 0}]}
    ]
    with pytest.raises(ManifestError, match="line_start"):
        parse_manifest(raw)


def test_loader_rejects_line_end_before_start() -> None:
    raw = dict(MINIMAL_RAW)
    raw["core_concepts"] = [
        {
            "id": "c",
            "name": "C",
            "description": "d",
            "sources": [{"line_start": 10, "line_end": 3}],
        }
    ]
    with pytest.raises(ManifestError, match="line_end"):
        parse_manifest(raw)


def test_loader_line_malformed_raises_manifest_error_not_valueerror() -> None:
    raw = dict(MINIMAL_RAW)
    raw["core_concepts"] = [
        {"id": "c", "name": "C", "description": "d", "sources": [{"line_start": "abc"}]}
    ]
    with pytest.raises(ManifestError):
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


def test_validator_reports_missing_doc_when_stat_raises_name_too_long(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A canonical doc path past the platform PATH_MAX must be a missing-file error.

    On macOS (PATH_MAX 1024) ``stat`` raises ENAMETOOLONG for a resolved path just
    under Beacon's own 1024-byte ``path_bytes`` limit, and ``Path.is_file`` before
    Python 3.14 re-raises it: CI run 35671989668 showed ``validate`` exiting 3
    ``internal_error`` on the macOS 3.12/3.13 legs only. Injected here so every
    platform pins the behaviour without needing a filesystem that enforces it.
    """
    import errno

    _write_readme(tmp_path)
    manifest = parse_manifest(dict(MINIMAL_RAW))
    original_is_file = Path.is_file

    def _is_file(self: Path, *args: object, **kwargs: object) -> bool:
        if self.name == "README.md":
            raise OSError(errno.ENAMETOOLONG, "File name too long")
        return original_is_file(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", _is_file)
    report = validate_beacon_manifest(manifest, docs_root=tmp_path)
    codes = [issue.code for issue in report.errors]
    assert "canonical_doc_missing_file" in codes


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
    raw["core_concepts"] = [{"id": "x", "name": "X", "description": "d", "status": "banana"}]
    manifest = parse_manifest(raw)
    report = validate_beacon_manifest(manifest)
    assert report.ok  # warning only, not error
    assert any("unknown status" in w.message for w in report.warnings)


def test_validator_checks_project_and_source_statuses() -> None:
    raw = dict(MINIMAL_RAW)
    raw["project"] = {
        "name": "test-project",
        "description": "A test.",
        "status": "banana",
    }
    raw["core_concepts"] = [
        {
            "id": "x",
            "description": "d",
            "sources": [{"path": "README.md", "status": "banana"}],
        }
    ]
    report = validate_beacon_manifest(parse_manifest(raw))

    invalid = [issue.where for issue in report.warnings if "unknown status" in issue.message]
    assert "project.status" in invalid
    assert "core_concepts[x].sources[].status" in invalid


def test_validator_requires_sources_for_declared_project_state() -> None:
    raw = dict(MINIMAL_RAW)
    raw["project_state"] = {"active_work": {"title": "Unsourced active work"}}
    report = validate_beacon_manifest(parse_manifest(raw))

    assert any(issue.code == "project_state_sources_missing" for issue in report.warnings)


# ---------------------------------------------------------------------------
# Canonical path boundary — absolute / traversal / symlink escape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unsafe",
    [
        "/etc/passwd",
        "C:\\Windows\\secret.txt",
        "C:/Windows/secret.txt",
        "\\\\server\\share\\secret",
        "//server/share",
        "../outside.md",
        "sub/../../outside.md",
        "..\\outside.md",
    ],
)
def test_validator_rejects_unsafe_canonical_path(tmp_path: Path, unsafe: str) -> None:
    raw = dict(MINIMAL_RAW)
    raw["canonical_docs"] = [{"path": unsafe, "status": "current"}]
    manifest = parse_manifest(raw)
    report = validate_beacon_manifest(manifest, docs_root=tmp_path)
    unsafe_issues = [e for e in report.errors if e.code == CODE_UNSAFE_CANONICAL_PATH]
    assert unsafe_issues, f"expected unsafe_canonical_path for {unsafe!r}"
    for issue in unsafe_issues:
        assert unsafe not in issue.message  # never leak the escaped path


def test_validator_unsafe_path_is_error_without_docs_root() -> None:
    raw = dict(MINIMAL_RAW)
    raw["canonical_docs"] = [{"path": "../escape.md", "status": "current"}]
    manifest = parse_manifest(raw)
    report = validate_beacon_manifest(manifest)
    assert any(e.code == CODE_UNSAFE_CANONICAL_PATH for e in report.errors)


def test_resolve_canonical_path_preserves_valid_relative(tmp_path: Path) -> None:
    resolved = resolve_canonical_path(tmp_path, "subdir/file.md")
    assert resolved == tmp_path.resolve() / "subdir" / "file.md"


def test_doc_index_rejects_unsafe_path_even_without_validation(tmp_path: Path) -> None:
    from beacon.core.schema import BeaconDoc

    docs = [BeaconDoc(path="../escape.md")]
    with pytest.raises(UnsafeCanonicalPath):
        DocIndex.from_docs(docs, docs_root=tmp_path)


def test_doc_index_rejects_symlink_escape(tmp_path: Path) -> None:
    from beacon.core.schema import BeaconDoc

    outside = tmp_path.parent / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform")
    docs = [BeaconDoc(path="link.md")]
    with pytest.raises(UnsafeCanonicalPath):
        DocIndex.from_docs(docs, docs_root=tmp_path)


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
