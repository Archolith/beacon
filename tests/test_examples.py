"""Example-matrix test for the maintained Beacon v0.2 examples (WP4).

This test enumerates exactly the maintained example repositories under
``examples/`` and, for each, drives only the public core APIs:

* loads and semantically validates the manifest (zero errors, publishable),
* builds a provider and executes all five provider methods,
* builds both an embedded and a metadata-only snapshot,
* schema-validates both snapshot payloads against the ``beacon-snapshot``
  v1.0 schema (``docs/schemas/beacon-snapshot-1.0.schema.json``), and
* asserts no leak of content or absolute paths.

It deliberately does not depend on the CLI (``beacon.main``) or any unfinished
command wiring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from beacon.core.loader import load_beacon_manifest
from beacon.core.policy import evaluate_policy
from beacon.core.schema import to_payload
from beacon.core.snapshot import (
    CONTENT_EMBEDDED,
    CONTENT_METADATA_ONLY,
    SNAPSHOT_VERSION,
    build_snapshot,
    snapshot_bytes,
)
from beacon.core.validator import validate_beacon_manifest
from beacon.provider.manifest_provider import ManifestBeaconProvider

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES_ROOT = _REPO_ROOT / "examples"
_SNAPSHOT_SCHEMA = _REPO_ROOT / "docs" / "schemas" / "beacon-snapshot-1.0.schema.json"


@dataclass(frozen=True)
class Example:
    """One maintained example: name, relative dir, and a representative task."""

    name: str
    directory: str
    task_hint: str


#: Exactly the maintained example set. Adding an example means adding it here.
EXAMPLES = (
    Example(
        name="library",
        directory="library",
        task_hint="add support for a new front-matter delimiter",
    ),
    Example(
        name="service",
        directory="service",
        task_hint="change the retry backoff schedule",
    ),
    Example(
        name="monorepo-research",
        directory="monorepo-research",
        task_hint="add a new tide-gauge station dataset",
    ),
)


def _example_dir(example: Example) -> Path:
    return _EXAMPLES_ROOT / example.directory


def _manifest_path(example: Example) -> Path:
    return _example_dir(example) / "beacon.yaml"


def _load_validator(example: Example):
    """Load + validate an example; return (manifest, report)."""
    manifest = load_beacon_manifest(_manifest_path(example))
    report = validate_beacon_manifest(manifest, docs_root=_example_dir(example))
    return manifest, report


# ---------------------------------------------------------------------------
# Enumeration / shape
# ---------------------------------------------------------------------------


def test_examples_enumeration_matches_layout() -> None:
    expected_dirs = {e.directory for e in EXAMPLES}
    on_disk = {p.name for p in _EXAMPLES_ROOT.iterdir() if p.is_dir()}
    # The enumeration is exactly the on-disk set, so an unmaintained extra
    # example directory cannot silently bypass CI.
    assert expected_dirs == on_disk
    assert len(EXAMPLES) == 3


def test_every_example_has_a_distinct_shape() -> None:
    names = {e.name for e in EXAMPLES}
    assert names == {"library", "service", "monorepo-research"}
    assert len({e.directory for e in EXAMPLES}) == len(EXAMPLES)


# ---------------------------------------------------------------------------
# Validate / publish
# ---------------------------------------------------------------------------


def test_every_example_validates_with_zero_errors() -> None:
    for example in EXAMPLES:
        manifest, report = _load_validator(example)
        assert report.ok, f"{example.name}: expected zero errors"
        assert report.errors == ()
        assert manifest.beacon_version == "0.1"


def test_every_example_is_publishable() -> None:
    for example in EXAMPLES:
        _, report = _load_validator(example)
        policy = evaluate_policy(report)
        assert policy.publishable, f"{example.name}: expected a clean publication policy"
        assert policy.unresolved_publication_warnings == ()


def test_every_example_has_meaningful_metadata() -> None:
    for example in EXAMPLES:
        manifest, _ = _load_validator(example)
        assert manifest.project.name
        assert manifest.project.description
        assert manifest.purpose.one_sentence
        assert manifest.canonical_docs
        assert manifest.core_concepts
        assert manifest.guardrails
        assert manifest.build_and_test.test


# ---------------------------------------------------------------------------
# Provider: all five tools
# ---------------------------------------------------------------------------


def test_every_example_provider_answers_all_five_tools() -> None:
    for example in EXAMPLES:
        manifest, _ = _load_validator(example)
        provider = ManifestBeaconProvider.from_paths(
            manifest_path=_manifest_path(example),
            docs_root=_example_dir(example),
        )
        assert provider.manifest is not None

        overview = provider.project_overview()
        assert overview.summary
        assert overview.status in {"current", "experimental", "uncertain", "mixed"}

        onboarding = provider.agent_onboarding(task_hint=example.task_hint)
        assert onboarding.orientation
        assert onboarding.relevant_docs

        query = manifest.core_concepts[0].id
        search = provider.search(query=query)
        assert search.answer

        explained = provider.explain_concept(concept=query)
        assert explained.definition or explained.status == "uncertain"

        guardrails = provider.guardrails(task_hint=example.task_hint)
        assert guardrails.rules
        assert guardrails.required_checks


# ---------------------------------------------------------------------------
# Snapshot: embedded + metadata-only, schema-valid
# ---------------------------------------------------------------------------


def _snapshot_payload_validates(payload: dict, schema: dict) -> None:
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_every_example_builds_embedded_and_metadata_snapshots() -> None:
    schema = json.loads(_SNAPSHOT_SCHEMA.read_text(encoding="utf-8"))
    for example in EXAMPLES:
        for content_mode in (CONTENT_EMBEDDED, CONTENT_METADATA_ONLY):
            snap = build_snapshot(
                _manifest_path(example),
                docs_root=_example_dir(example),
                content_mode=content_mode,
            )
            assert snap.beacon_snapshot_version == SNAPSHOT_VERSION
            assert snap.content_mode == content_mode
            payload = snap.to_payload()
            _snapshot_payload_validates(payload, schema)
            # The serialized stream is also schema-valid and parseable.
            raw = snapshot_bytes(snap)
            _snapshot_payload_validates(json.loads(raw), schema)


def test_embedded_snapshot_has_chunk_text_metadata_only_does_not() -> None:
    example = EXAMPLES[0]
    embedded = build_snapshot(
        _manifest_path(example),
        docs_root=_example_dir(example),
        content_mode=CONTENT_EMBEDDED,
    )
    metadata = build_snapshot(
        _manifest_path(example),
        docs_root=_example_dir(example),
        content_mode=CONTENT_METADATA_ONLY,
    )
    embedded_texts = [chunk.text for doc in embedded.documents for chunk in doc.chunks]
    assert any(text for text in embedded_texts)  # embedded carries text
    for doc in metadata.documents:
        for chunk in doc.chunks:
            assert chunk.text is None  # metadata-only drops text


# ---------------------------------------------------------------------------
# No leaks
# ---------------------------------------------------------------------------


def test_snapshot_payloads_contain_no_absolute_paths() -> None:
    for example in EXAMPLES:
        for content_mode in (CONTENT_EMBEDDED, CONTENT_METADATA_ONLY):
            snap = build_snapshot(
                _manifest_path(example),
                docs_root=_example_dir(example),
                content_mode=content_mode,
            )
            raw = snapshot_bytes(snap).decode("utf-8")
            absolute = str(_example_dir(example).resolve()).replace("\\", "/")
            assert absolute not in raw, f"{example.name}/{content_mode}"
            assert "file://" not in raw


def test_every_example_is_safe_to_export_by_default() -> None:
    # No security override should be required for the maintained examples.
    for example in EXAMPLES:
        snap = build_snapshot(_manifest_path(example), docs_root=_example_dir(example))
        assert snap.validation.security_overrides == ()
        assert snap.security_findings == ()


def test_example_payloads_are_json_ready() -> None:
    for example in EXAMPLES:
        manifest, _ = _load_validator(example)
        payload = to_payload(manifest)
        # JSON-serializable and contains no unexpected nesting surprises.
        json.dumps(payload)
