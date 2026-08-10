"""Tests for the canonical static snapshot core (WP3)."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import jsonschema
import pytest

from beacon import __version__
from beacon.core.canonical_json import dumps_canonical
from beacon.core.limits import (
    LIMIT_DOCUMENT_BYTES,
    LIMIT_SNAPSHOT_BYTES,
    LIMIT_TOTAL_DOCUMENT_BYTES,
    LimitError,
    ResourceLimits,
)
from beacon.core.policy import Acknowledgement, PolicyEvaluation
from beacon.core.security import (
    SENSITIVE_CREDENTIAL_URL,
    SENSITIVE_KNOWN_TOKEN,
    SecurityOverride,
)
from beacon.core.snapshot import (
    CONTENT_EMBEDDED,
    CONTENT_METADATA_ONLY,
    SNAPSHOT_BLOCKED_POLICY,
    SNAPSHOT_BLOCKED_SECURITY,
    SNAPSHOT_INVALID_CONTENT_MODE,
    SNAPSHOT_SOURCE_CHANGED,
    SNAPSHOT_UNSAFE_MANIFEST_PATH,
    SNAPSHOT_VERSION,
    Snapshot,
    SnapshotError,
    SnapshotGenerator,
    SnapshotManifest,
    SnapshotProject,
    SnapshotValidation,
    build_snapshot,
    metadata_only_snapshot,
    snapshot_bytes,
    write_snapshot_atomic,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "beacon-snapshot-1.0.schema.json"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "schemas"

GITHUB_TOKEN = "ghp_" + "A" * 36
CRED_URL = "https://deploy:supersecretpassword@example.com/acme/repo.git"

#: A publishable manifest that leaves both acknowledgeable warnings unresolved.
WARNING_MANIFEST = """\
beacon_version: "0.1"
project:
  name: snapshot-project
  description: A fixture project for snapshot tests.
  status: current
purpose:
  one_sentence: Exercise the canonical static snapshot core.
canonical_docs:
  - path: README.md
    role: entrypoint
    status: current
    title: Read Me
"""

CLEAN_MANIFEST = """\
beacon_version: "0.1"
project:
  name: snapshot-project
  description: A fixture project for snapshot tests.
  status: current
purpose:
  one_sentence: Exercise the canonical static snapshot core.
build_and_test:
  test: pytest
guardrails:
  - id: g1
    rule: Do not break things.
canonical_docs:
  - path: README.md
    role: entrypoint
    status: current
    title: Read Me
"""


def _load_schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _write_project(tmp_path: Path, *, manifest: str = CLEAN_MANIFEST) -> Path:
    (tmp_path / "README.md").write_text(
        "# One\n\nbody one.\n\n## Two\n\nbody two.\n", encoding="utf-8"
    )
    manifest_file = tmp_path / "beacon.yaml"
    manifest_file.write_text(manifest, encoding="utf-8")
    return manifest_file


# ---------------------------------------------------------------------------
# Schema meta-validation and golden fixtures
# ---------------------------------------------------------------------------


def test_snapshot_schema_is_valid_draft202012() -> None:
    jsonschema.Draft202012Validator.check_schema(_load_schema())


def test_positive_snapshot_fixture_validates() -> None:
    jsonschema.validate(_load_fixture("snapshot-valid.json"), _load_schema())


def test_negative_snapshot_fixture_fails() -> None:
    errors = sorted(
        jsonschema.Draft202012Validator(_load_schema()).iter_errors(
            _load_fixture("snapshot-invalid.json")
        ),
        key=lambda e: e.validator,
    )
    assert errors
    validators = {e.validator for e in errors}
    assert "const" in validators  # snapshot version / validation.errors
    assert "enum" in validators  # invalid project status
    assert "pattern" in validators  # bad sha / escaping path / bad code
    assert "minimum" in validators  # negative warnings count


# ---------------------------------------------------------------------------
# Building and schema conformance of a real snapshot
# ---------------------------------------------------------------------------


def test_built_snapshot_validates_against_schema(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path)
    snap = build_snapshot(manifest_file)
    jsonschema.validate(snap.to_payload(), _load_schema())


def test_generator_identity_and_version(tmp_path: Path) -> None:
    snap = build_snapshot(_write_project(tmp_path))
    payload = snap.to_payload()
    assert payload["beacon_snapshot_version"] == SNAPSHOT_VERSION
    assert payload["generator"]["distribution"] == "archolith-beacon"
    assert payload["generator"]["version"] == __version__


def test_invalid_content_mode_rejected(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(_write_project(tmp_path), content_mode="raw")
    assert excinfo.value.code == SNAPSHOT_INVALID_CONTENT_MODE


# ---------------------------------------------------------------------------
# Determinism and digest mutation
# ---------------------------------------------------------------------------


def test_two_exports_are_byte_identical(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path)
    first = snapshot_bytes(build_snapshot(manifest_file))
    second = snapshot_bytes(build_snapshot(manifest_file))
    assert first == second
    assert first.endswith(b"\n")
    assert first.count(b"\n") == 1


def test_changing_doc_changes_digest_and_bytes(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path)
    before = build_snapshot(manifest_file)
    (tmp_path / "README.md").write_text(
        "# One\n\nCHANGED body one.\n\n## Two\n\nbody two.\n", encoding="utf-8"
    )
    after = build_snapshot(manifest_file)
    assert before.manifest.source_sha256 == after.manifest.source_sha256
    assert (
        before.to_payload()["documents"][0]["source_sha256"]
        != after.to_payload()["documents"][0]["source_sha256"]
    )
    assert snapshot_bytes(before) != snapshot_bytes(after)


def test_manifest_digest_is_exact_source_sha256(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path)
    snap = build_snapshot(manifest_file)
    expected = __import__("hashlib").sha256(manifest_file.read_bytes()).hexdigest()
    assert snap.manifest.source_sha256 == expected


def test_doc_digest_is_exact_source_sha256(tmp_path: Path) -> None:
    _write_project(tmp_path)
    snap = build_snapshot(tmp_path / "beacon.yaml")
    expected = __import__("hashlib").sha256((tmp_path / "README.md").read_bytes()).hexdigest()
    assert snap.to_payload()["documents"][0]["source_sha256"] == expected


# ---------------------------------------------------------------------------
# Content modes
# ---------------------------------------------------------------------------


def test_embedded_chunks_include_text(tmp_path: Path) -> None:
    snap = build_snapshot(_write_project(tmp_path), content_mode=CONTENT_EMBEDDED)
    chunks = snap.to_payload()["documents"][0]["chunks"]
    assert chunks
    assert all("text" in chunk and chunk["text"] for chunk in chunks)


def test_metadata_only_omits_text_keeps_structure(tmp_path: Path) -> None:
    snap = build_snapshot(_write_project(tmp_path), content_mode=CONTENT_METADATA_ONLY)
    payload = snap.to_payload()
    assert payload["content_mode"] == "metadata_only"
    chunks = payload["documents"][0]["chunks"]
    assert chunks
    for chunk in chunks:
        assert "text" not in chunk
        assert "heading_path" in chunk
        assert chunk["line_start"] >= 1
        assert chunk["line_end"] >= 1
    assert payload["documents"][0]["source_sha256"]  # hashes still present


def test_metadata_only_can_be_derived_without_mutating_embedded_snapshot(tmp_path: Path) -> None:
    embedded = build_snapshot(_write_project(tmp_path), content_mode=CONTENT_EMBEDDED)
    orientation = metadata_only_snapshot(embedded)

    assert orientation is not embedded
    assert orientation.content_mode == CONTENT_METADATA_ONLY
    assert orientation.manifest == embedded.manifest
    assert orientation.project == embedded.project
    assert orientation.validation == embedded.validation
    assert orientation.policy == embedded.policy
    assert orientation.documents[0].source_sha256 == embedded.documents[0].source_sha256
    assert all(
        chunk.text is None for document in orientation.documents for chunk in document.chunks
    )
    assert all(
        chunk.text is not None for document in embedded.documents for chunk in document.chunks
    )
    jsonschema.validate(orientation.to_payload(), _load_schema())


def test_metadata_only_derivation_is_idempotent(tmp_path: Path) -> None:
    metadata = build_snapshot(_write_project(tmp_path), content_mode=CONTENT_METADATA_ONLY)
    assert metadata_only_snapshot(metadata) is metadata


def test_plan_documents_are_title_only_in_embedded_snapshot(tmp_path: Path) -> None:
    plan_text = "# Internal execution plan\n\nDetailed private implementation sequence.\n"
    (tmp_path / "README.md").write_text("# Public entrypoint\n\nPublic body.\n", encoding="utf-8")
    (tmp_path / "internal-plan.md").write_text(plan_text, encoding="utf-8")
    manifest = (
        CLEAN_MANIFEST
        + """\
  - path: internal-plan.md
    role: implementation_plan
    status: current
    title: Internal execution plan
"""
    )
    manifest_file = tmp_path / "beacon.yaml"
    manifest_file.write_text(manifest, encoding="utf-8")

    snapshot = build_snapshot(manifest_file)
    documents = {document["path"]: document for document in snapshot.to_payload()["documents"]}

    assert documents["README.md"]["chunks"]
    plan = documents["internal-plan.md"]
    assert plan["path"] == "internal-plan.md"
    assert plan["role"] == "implementation_plan"
    assert plan["status"] == "current"
    assert plan["title"] == "Internal execution plan"
    assert plan["source_sha256"]
    assert plan["chunks"] == []
    assert plan_text.encode() not in snapshot_bytes(snapshot)


def test_title_only_plan_body_is_not_scanned_as_exported_content(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Public entrypoint\n\nPublic body.\n", encoding="utf-8")
    (tmp_path / "internal-plan.md").write_text(
        f"# Internal plan\n\nfixture token {GITHUB_TOKEN}\n", encoding="utf-8"
    )
    manifest = (
        CLEAN_MANIFEST
        + """\
  - path: internal-plan.md
    role: architecture_plan
    status: current
    title: Internal architecture plan
"""
    )
    manifest_file = tmp_path / "beacon.yaml"
    manifest_file.write_text(manifest, encoding="utf-8")

    snapshot = build_snapshot(manifest_file)

    assert snapshot.to_payload()["validation"]["security_overrides"] == []
    assert GITHUB_TOKEN.encode() not in snapshot_bytes(snapshot)


# ---------------------------------------------------------------------------
# Line ranges resolve to chunk text
# ---------------------------------------------------------------------------


def test_chunk_line_ranges_resolve_to_text(tmp_path: Path) -> None:
    snap = build_snapshot(_write_project(tmp_path), content_mode=CONTENT_EMBEDDED)
    source_lines = (tmp_path / "README.md").read_text(encoding="utf-8").splitlines()
    for doc in snap.to_payload()["documents"]:
        for chunk in doc["chunks"]:
            start, end = chunk["line_start"], chunk["line_end"]
            assert 1 <= start <= end <= len(source_lines)
            body = "\n".join(source_lines[start - 1 : end]).strip()
            assert chunk["text"] == body


# ---------------------------------------------------------------------------
# Policy: errors and unresolved publication warnings block
# ---------------------------------------------------------------------------


def test_validation_error_blocks(tmp_path: Path) -> None:
    manifest = CLEAN_MANIFEST.replace(
        "canonical_docs:\n  - path: README.md\n    role: entrypoint\n    status: current\n    title: Read Me\n",
        "",
    )
    manifest_file = _write_project(tmp_path, manifest=manifest)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_BLOCKED_POLICY


def test_unresolved_publication_warning_blocks(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path, manifest=WARNING_MANIFEST)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_BLOCKED_POLICY


def test_acknowledged_publication_warnings_allow(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path, manifest=WARNING_MANIFEST)
    acks = (
        Acknowledgement(
            code="test_command_missing", reason="Manual smoke tests cover this project."
        ),
        Acknowledgement(code="guardrails_missing", reason="Guardrails live in the agent handbook."),
    )
    snap = build_snapshot(manifest_file, acknowledgements=acks)
    validation = snap.to_payload()["validation"]
    assert validation["errors"] == 0
    codes = {a["code"] for a in validation["acknowledgements"]}
    assert codes == {"test_command_missing", "guardrails_missing"}


def test_no_output_when_policy_blocks(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path, manifest=WARNING_MANIFEST)
    out = tmp_path / "snapshot.json"
    with pytest.raises(SnapshotError):
        build_snapshot(manifest_file)
    assert not out.exists()


# ---------------------------------------------------------------------------
# Security: blocking, override, and no leak
# ---------------------------------------------------------------------------


def test_embedded_secret_in_doc_blocks(tmp_path: Path) -> None:
    _write_project(tmp_path)
    (tmp_path / "README.md").write_text(f"# One\n\ntoken {GITHUB_TOKEN} here.\n", encoding="utf-8")
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(tmp_path / "beacon.yaml")
    assert excinfo.value.code == SNAPSHOT_BLOCKED_SECURITY
    assert excinfo.value.findings
    assert GITHUB_TOKEN not in str(excinfo.value)
    assert GITHUB_TOKEN not in "".join(f.path for f in excinfo.value.findings)


def test_embedded_secret_override_allows_and_records(tmp_path: Path) -> None:
    _write_project(tmp_path)
    (tmp_path / "README.md").write_text(f"# One\n\ntoken {GITHUB_TOKEN} here.\n", encoding="utf-8")
    override = SecurityOverride(code=SENSITIVE_KNOWN_TOKEN, reason="Fixture token for unit tests.")
    snap = build_snapshot(tmp_path / "beacon.yaml", security_overrides=[override])
    codes = {o["code"] for o in snap.to_payload()["validation"]["security_overrides"]}
    assert codes == {SENSITIVE_KNOWN_TOKEN}
    # Exceptional export embeds the overridden content by design.
    assert GITHUB_TOKEN in snap.to_payload()["documents"][0]["chunks"][0]["text"]


def test_metadata_only_does_not_scan_doc_bodies(tmp_path: Path) -> None:
    _write_project(tmp_path)
    (tmp_path / "README.md").write_text(f"# One\n\ntoken {GITHUB_TOKEN} here.\n", encoding="utf-8")
    snap = build_snapshot(tmp_path / "beacon.yaml", content_mode=CONTENT_METADATA_ONLY)
    assert snap.to_payload()["validation"]["security_overrides"] == []


def test_manifest_credential_url_blocks_both_modes(tmp_path: Path) -> None:
    manifest = CLEAN_MANIFEST.replace(
        "  status: current\n", f"  status: current\n  repository: {CRED_URL}\n", 1
    )
    manifest_file = _write_project(tmp_path, manifest=manifest)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_BLOCKED_SECURITY
    assert CRED_URL not in str(excinfo.value)
    with pytest.raises(SnapshotError):
        build_snapshot(manifest_file, content_mode=CONTENT_METADATA_ONLY)


def test_manifest_credential_override_allows(tmp_path: Path) -> None:
    manifest = CLEAN_MANIFEST.replace(
        "  status: current\n", f"  status: current\n  repository: {CRED_URL}\n", 1
    )
    manifest_file = _write_project(tmp_path, manifest=manifest)
    override = SecurityOverride(
        code=SENSITIVE_CREDENTIAL_URL, reason="Private mirror URL for fixture tests."
    )
    snap = build_snapshot(manifest_file, security_overrides=[override])
    codes = {o["code"] for o in snap.to_payload()["validation"]["security_overrides"]}
    assert codes == {SENSITIVE_CREDENTIAL_URL}


def test_security_override_recorded_once_in_caller_order(tmp_path: Path) -> None:
    _write_project(tmp_path)
    # A body with two lines each carrying the same token code.
    (tmp_path / "README.md").write_text(
        f"# One\n\ntoken {GITHUB_TOKEN}\n\nmore {GITHUB_TOKEN}\n", encoding="utf-8"
    )
    override = SecurityOverride(code=SENSITIVE_KNOWN_TOKEN, reason="Fixture token for unit tests.")
    snap = build_snapshot(tmp_path / "beacon.yaml", security_overrides=[override])
    records = snap.to_payload()["validation"]["security_overrides"]
    assert [r["code"] for r in records] == [SENSITIVE_KNOWN_TOKEN]


# ---------------------------------------------------------------------------
# Paths: dangling and escaping docs are rejected
# ---------------------------------------------------------------------------


def test_dangling_doc_blocks(tmp_path: Path) -> None:
    manifest = CLEAN_MANIFEST.replace("README.md", "missing.md")
    manifest_file = _write_project(tmp_path, manifest=manifest)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_BLOCKED_POLICY


def test_escaping_doc_path_blocks(tmp_path: Path) -> None:
    manifest = CLEAN_MANIFEST.replace("README.md", "../escape.md")
    manifest_file = _write_project(tmp_path, manifest=manifest)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_BLOCKED_POLICY


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


def test_snapshot_byte_ceiling_enforced(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path)
    snap = build_snapshot(manifest_file)
    with pytest.raises(LimitError) as excinfo:
        snapshot_bytes(snap, byte_ceiling=16)
    assert excinfo.value.code == LIMIT_SNAPSHOT_BYTES


def test_atomic_write_oversized_leaves_destination_untouched(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path)
    snap = build_snapshot(manifest_file)
    out = tmp_path / "snapshot.json"
    out.write_text("old-content", encoding="utf-8")
    with pytest.raises(LimitError):
        write_snapshot_atomic(out, snap, byte_ceiling=16)
    assert out.read_text(encoding="utf-8") == "old-content"
    assert {p.name for p in tmp_path.iterdir()} == {"beacon.yaml", "README.md", "snapshot.json"}


def test_doc_bytes_limit_enforced(tmp_path: Path) -> None:
    _write_project(tmp_path)
    (tmp_path / "README.md").write_text("# Big\n\n" + "x" * 5000, encoding="utf-8")
    limits = ResourceLimits(document_bytes=100)
    with pytest.raises(LimitError) as excinfo:
        build_snapshot(tmp_path / "beacon.yaml", limits=limits)
    assert excinfo.value.code == LIMIT_DOCUMENT_BYTES


def test_aggregate_doc_bytes_limit_enforced_before_retention(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# A\n\nbody a.\n", encoding="utf-8")
    (tmp_path / "B.md").write_text("# B\n\nbody b.\n", encoding="utf-8")
    manifest = """\
beacon_version: "0.1"
project:
  name: aggregate-project
  description: A fixture project for aggregate limits.
  status: current
purpose:
  one_sentence: Exercise aggregate total document bytes.
build_and_test:
  test: pytest
guardrails:
  - id: g1
    rule: Do not break things.
canonical_docs:
  - path: README.md
    role: entrypoint
    status: current
  - path: B.md
    role: architecture
    status: current
"""
    manifest_file = _write_project(tmp_path, manifest=manifest)
    with pytest.raises(LimitError) as excinfo:
        build_snapshot(manifest_file, limits=ResourceLimits(total_document_bytes=20))
    assert excinfo.value.code == LIMIT_TOTAL_DOCUMENT_BYTES


def test_low_snapshot_limit_default_ceiling_refuses(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path)
    snap = build_snapshot(manifest_file, limits=ResourceLimits(snapshot_bytes=32))
    assert snap.byte_ceiling == 32
    with pytest.raises(LimitError) as excinfo:
        snapshot_bytes(snap)
    assert excinfo.value.code == LIMIT_SNAPSHOT_BYTES


def test_low_snapshot_limit_write_leaves_no_partial_file(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path)
    snap = build_snapshot(manifest_file, limits=ResourceLimits(snapshot_bytes=32))
    out = tmp_path / "snapshot.json"
    out.write_text("old-content", encoding="utf-8")
    with pytest.raises(LimitError):
        write_snapshot_atomic(out, snap)
    assert out.read_text(encoding="utf-8") == "old-content"
    assert {p.name for p in tmp_path.iterdir()} == {"beacon.yaml", "README.md", "snapshot.json"}


# ---------------------------------------------------------------------------
# Manifest path metadata: no local absolute paths in snapshot content
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "manifest",
    [
        CLEAN_MANIFEST.replace(
            "build_and_test:\n  test: pytest\n",
            "build_and_test:\n  test: pytest\ncore_concepts:\n"
            "  - id: concept-a\n    name: Concept A\n    description: A definition.\n"
            "    status: current\n    implementation_locations: [C:\\\\Users\\\\me\\\\secret.py]\n",
        ),
        CLEAN_MANIFEST.replace(
            "  test: pytest\n",
            "  test: pytest\ncore_concepts:\n"
            "  - id: concept-a\n    name: Concept A\n    description: A definition.\n"
            "    status: current\n"
            "    sources:\n      - type: doc\n        path: /etc/passwd\n",
        ),
        CLEAN_MANIFEST.replace(
            "guardrails:\n  - id: g1\n    rule: Do not break things.\n",
            "guardrails:\n  - id: g1\n    rule: Do not break things.\n"
            "    applies_to: [../outside.py]\n",
        ),
        CLEAN_MANIFEST.replace(
            "build_and_test:\n  test: pytest\n",
            "build_and_test:\n  test: pytest\nagent_guidance:\n  read_first: [C:\\\\tmp\\\\x.md]\n",
        ),
    ],
)
def test_absolute_manifest_path_refused(tmp_path: Path, manifest: str) -> None:
    manifest_file = _write_project(tmp_path, manifest=manifest)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_UNSAFE_MANIFEST_PATH
    assert "C:\\\\Users" not in str(excinfo.value)
    assert "/etc" not in str(excinfo.value)
    assert "../outside.py" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# No volatile data: no timestamp, hostname, absolute path, or environment
# ---------------------------------------------------------------------------


def test_no_volatile_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEACON_FIXTURE_SECRET", "SECRET_ENV_VALUE_XYZ")
    manifest_file = _write_project(tmp_path)
    snap = build_snapshot(manifest_file)
    raw = snapshot_bytes(snap).decode("utf-8")
    assert "SECRET_ENV_VALUE_XYZ" not in raw
    assert socket.gethostname() not in raw
    absolute = str(manifest_file.resolve().parent).replace("\\", "/")
    assert absolute not in raw
    assert "read_bytes_bounded" not in raw


# ---------------------------------------------------------------------------
# Tuple normalization: manifest lists must serialize through canonical JSON
# ---------------------------------------------------------------------------


def test_manifest_tuples_serialize_via_canonical_json(tmp_path: Path) -> None:
    manifest = """\
beacon_version: "0.1"
project:
  name: snapshot-project
  description: A fixture project for snapshot tests.
  status: current
purpose:
  one_sentence: Exercise the canonical static snapshot core.
audiences: [agent, human]
current_focus: [snapshots, export]
core_concepts:
  - id: concept-a
    name: Concept A
    description: A definition.
    status: current
    related_concepts: [concept-b]
    implementation_locations: [src/a.py, src/b.py]
  - id: concept-b
    name: Concept B
    description: Another definition.
    status: current
canonical_docs:
  - path: README.md
    role: entrypoint
    status: current
    title: Read Me
build_and_test:
  test: pytest
guardrails:
  - id: g1
    rule: Do not break things.
    applies_to: [src/a.py, src/b.py]
"""
    manifest_file = _write_project(tmp_path, manifest=manifest)
    snap = build_snapshot(manifest_file)
    payload = snap.to_payload()
    assert payload["manifest"]["data"]["audiences"] == ["agent", "human"]
    assert payload["manifest"]["data"]["core_concepts"][0]["related_concepts"] == ["concept-b"]
    # canonical_json refuses tuples; this must not raise InvalidJsonValue.
    out = dumps_canonical(payload)
    assert json.loads(out.decode("utf-8"))["beacon_snapshot_version"] == SNAPSHOT_VERSION


# ---------------------------------------------------------------------------
# Deterministic serialization shape
# ---------------------------------------------------------------------------


def test_snapshot_is_exactly_one_document_plus_newline(tmp_path: Path) -> None:
    snap = build_snapshot(_write_project(tmp_path))
    raw = snapshot_bytes(snap)
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 1
    json.loads(raw.decode("utf-8"))


def test_snapshot_byte_stability(tmp_path: Path) -> None:
    manifest_file = _write_project(tmp_path)
    assert snapshot_bytes(build_snapshot(manifest_file)) == snapshot_bytes(
        build_snapshot(manifest_file)
    )


# ---------------------------------------------------------------------------
# Source-integrity: TOCTOU detection between digest reads and parse/chunk
# ---------------------------------------------------------------------------


def test_manifest_source_changed_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from beacon.core import snapshot as snap_mod

    manifest_file = _write_project(tmp_path)
    original = snap_mod.read_bytes_bounded
    calls = {"count": 0}

    def fake(path: object, **kwargs: object) -> bytes:
        data = original(path, **kwargs)  # type: ignore[arg-type]
        calls["count"] += 1
        # Second read is the manifest-after verification read.
        if calls["count"] == 2:
            return data + b"\n# changed during export\n"
        return data

    monkeypatch.setattr(snap_mod, "read_bytes_bounded", fake)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_SOURCE_CHANGED
    assert "# changed" not in str(excinfo.value)


def test_doc_source_changed_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from beacon.core import snapshot as snap_mod

    manifest_file = _write_project(tmp_path)
    original = snap_mod.read_bytes_bounded
    seen: dict[str, int] = {}

    def fake(path: object, **kwargs: object) -> bytes:
        data = original(path, **kwargs)  # type: ignore[arg-type]
        key = Path(str(path)).name
        seen[key] = seen.get(key, 0) + 1
        # Second read of the doc is the doc-after verification read.
        if key == "README.md" and seen[key] == 2:
            return data + b"\nchanged during export\n"
        return data

    monkeypatch.setattr(snap_mod, "read_bytes_bounded", fake)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_SOURCE_CHANGED


def test_manually_constructed_snapshot_default_ceiling() -> None:
    snap = Snapshot(
        beacon_snapshot_version=SNAPSHOT_VERSION,
        generator=SnapshotGenerator("archolith-beacon", "0.2.0rc1"),
        content_mode="embedded",
        project=SnapshotProject("p", "current"),
        manifest=SnapshotManifest("0.1", "a" * 64, {}),
        documents=(),
        validation=SnapshotValidation(0, 0),
        policy=PolicyEvaluation(servable=True, publishable=True),
    )
    assert snap.byte_ceiling == ResourceLimits().snapshot_bytes


# ---------------------------------------------------------------------------
# Absolute / file:// local metadata refusal
# ---------------------------------------------------------------------------


def test_file_url_repository_refused(tmp_path: Path) -> None:
    manifest = CLEAN_MANIFEST.replace(
        "  status: current\n", "  status: current\n  repository: file:///srv/secret/repo\n", 1
    )
    manifest_file = _write_project(tmp_path, manifest=manifest)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_UNSAFE_MANIFEST_PATH


def test_uppercase_file_url_repository_refused(tmp_path: Path) -> None:
    manifest = CLEAN_MANIFEST.replace(
        "  status: current\n", "  status: current\n  repository: FILE:///srv/secret/repo\n", 1
    )
    manifest_file = _write_project(tmp_path, manifest=manifest)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_UNSAFE_MANIFEST_PATH


def test_source_file_url_refused(tmp_path: Path) -> None:
    manifest = CLEAN_MANIFEST.replace(
        "build_and_test:\n  test: pytest\n",
        "build_and_test:\n  test: pytest\ncore_concepts:\n"
        "  - id: concept-a\n    name: Concept A\n    description: A definition.\n"
        "    status: current\n"
        "    sources:\n      - type: doc\n        url: file:///etc/shadow\n",
    )
    manifest_file = _write_project(tmp_path, manifest=manifest)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_UNSAFE_MANIFEST_PATH


@pytest.mark.parametrize(
    "command",
    [
        "pytest /usr/bin/helper",
        "C:\\Python\\python.exe -m pytest",
        'pytest "C:\\Tools\\runner.exe"',
        "X=/opt/tools pytest",
    ],
)
def test_absolute_path_in_test_command_refused(tmp_path: Path, command: str) -> None:
    manifest = CLEAN_MANIFEST.replace("  test: pytest\n", f"  test: {command}\n")
    manifest_file = _write_project(tmp_path, manifest=manifest)
    with pytest.raises(SnapshotError) as excinfo:
        build_snapshot(manifest_file)
    assert excinfo.value.code == SNAPSHOT_UNSAFE_MANIFEST_PATH
    assert command not in str(excinfo.value)


def test_relative_test_command_allowed(tmp_path: Path) -> None:
    manifest = CLEAN_MANIFEST.replace("  test: pytest\n", "  test: pytest tests\n")
    snap = build_snapshot(_write_project(tmp_path, manifest=manifest))
    assert snap.to_payload()["validation"]["errors"] == 0


def test_https_url_in_test_command_allowed(tmp_path: Path) -> None:
    manifest = CLEAN_MANIFEST.replace("  test: pytest\n", "  test: pytest https://example.com/ci\n")
    snap = build_snapshot(_write_project(tmp_path, manifest=manifest))
    assert snap.to_payload()["validation"]["errors"] == 0
