"""Offline tests for ManifestBeaconProvider — all five capabilities."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from beacon.core.loader import parse_manifest
from beacon.core.doc_index import DocIndex
from beacon.core.schema import BeaconDoc
from beacon.provider.manifest_provider import ManifestBeaconProvider


SAMPLE_MD = textwrap.dedent("""\
    # Architecture

    menhir stores memories in a knowledge graph.

    ## Retrieval

    Retrieval uses vector search then graph re-ranking.

    ## Lifecycle

    Memories decay from active to compressed to gone.
""")

MANIFEST_RAW = {
    "beacon_version": "0.1",
    "project": {
        "name": "menhir",
        "description": "Graph memory for agents.",
        "tagline": "Long-term memory for coding agents.",
        "status": "experimental",
    },
    "purpose": {
        "one_sentence": "menhir helps coding agents remember context across sessions.",
        "problem": "Agents forget everything between conversations.",
        "non_goals": ["Replace git."],
    },
    "current_focus": ["temporal memory", "beacon"],
    "core_concepts": [
        {
            "id": "graph_memory",
            "name": "Graph Memory",
            "description": "Memories stored as a knowledge graph with scoring.",
            "status": "current",
            "why_it_exists": "Vector-only search ignores structure.",
        },
        {
            "id": "lifecycle",
            "name": "Memory Lifecycle",
            "description": "SESSION → ACTIVE → COMPRESSED → GONE.",
            "status": "current",
            "related_concepts": ["graph_memory"],
        },
        {
            "id": "chronostratum",
            "name": "Chronostratum",
            "description": "Planned temporal memory layer.",
            "status": "experimental",
        },
    ],
    "canonical_docs": [
        {"path": "arch.md", "role": "architecture", "status": "current"},
    ],
    "agent_guidance": {
        "read_first": ["arch.md"],
        "safe_first_tasks": ["Add tests.", "Improve docs."],
        "avoid_without_review": ["Change schema."],
    },
    "build_and_test": {
        "setup": "pip install -e '.[dev]'",
        "test": "python -m pytest tests/ -x",
    },
    "guardrails": [
        {
            "id": "no_schema_change",
            "rule": "Do not change schema without migration.",
            "scope": "schema",
            "severity": "high",
            "applies_to": ["src/", "migrations/"],
        }
    ],
}


@pytest.fixture()
def provider(tmp_path: Path) -> ManifestBeaconProvider:
    (tmp_path / "arch.md").write_text(SAMPLE_MD, encoding="utf-8")
    manifest = parse_manifest(MANIFEST_RAW)
    docs = [BeaconDoc(path="arch.md", role="architecture", status="current")]
    doc_index = DocIndex.from_docs(docs, docs_root=tmp_path)
    return ManifestBeaconProvider(manifest=manifest, doc_index=doc_index, docs_root=tmp_path)


# ---------------------------------------------------------------------------
# project_overview
# ---------------------------------------------------------------------------


def test_project_overview_returns_populated(provider: ManifestBeaconProvider) -> None:
    result = provider.project_overview()
    assert result.summary
    assert result.status
    assert result.confidence
    assert len(result.sources) >= 1


def test_project_overview_includes_core_components(provider: ManifestBeaconProvider) -> None:
    result = provider.project_overview(depth="standard")
    assert len(result.core_components) >= 1
    assert any("Graph Memory" in c for c in result.core_components)


def test_project_overview_short_depth(provider: ManifestBeaconProvider) -> None:
    result = provider.project_overview(depth="short")
    assert result.summary


# ---------------------------------------------------------------------------
# agent_onboarding
# ---------------------------------------------------------------------------


def test_agent_onboarding_returns_populated(provider: ManifestBeaconProvider) -> None:
    result = provider.agent_onboarding()
    assert result.orientation
    assert result.relevant_docs
    assert result.safe_first_steps
    assert len(result.sources) >= 1


def test_agent_onboarding_with_task_hint(provider: ManifestBeaconProvider) -> None:
    result = provider.agent_onboarding(task_hint="retrieval scoring")
    assert result.orientation
    # Should surface retrieval-related docs/concepts from the doc index
    assert result.relevant_docs or result.relevant_files


def test_agent_onboarding_do_not_touch_populated(provider: ManifestBeaconProvider) -> None:
    result = provider.agent_onboarding()
    assert "Change schema." in result.do_not_touch


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_finds_concept(provider: ManifestBeaconProvider) -> None:
    result = provider.search(query="graph memory scoring")
    assert result.results
    titles = [h.title for h in result.results]
    assert any("Graph Memory" in t or "graph" in t.lower() for t in titles)


def test_search_returns_sources(provider: ManifestBeaconProvider) -> None:
    result = provider.search(query="lifecycle compressed")
    assert result.results
    assert result.confidence


def test_search_no_match_returns_uncertain(provider: ManifestBeaconProvider) -> None:
    result = provider.search(query="xylophone quantum banana")
    assert result.status == "uncertain"


def test_search_concept_source_type_filter(provider: ManifestBeaconProvider) -> None:
    result = provider.search(query="graph", source_types=("concepts",))
    types = {h.source_type for h in result.results}
    assert types <= {"concept"}


def test_search_limit_respected(provider: ManifestBeaconProvider) -> None:
    result = provider.search(query="memory", limit=2)
    assert len(result.results) <= 2


# ---------------------------------------------------------------------------
# explain_concept
# ---------------------------------------------------------------------------


def test_explain_known_concept(provider: ManifestBeaconProvider) -> None:
    result = provider.explain_concept(concept="graph_memory")
    assert result.concept == "Graph Memory"
    assert result.definition
    assert result.status == "current"
    assert result.confidence == "high"


def test_explain_concept_by_name(provider: ManifestBeaconProvider) -> None:
    result = provider.explain_concept(concept="Chronostratum")
    assert result.concept == "Chronostratum"
    assert result.status == "experimental"


def test_explain_unknown_concept_low_confidence(provider: ManifestBeaconProvider) -> None:
    result = provider.explain_concept(concept="xyzzy_nonexistent_abc")
    assert result.confidence in {"low", "medium"}
    assert result.status == "uncertain"


def test_explain_concept_experimental_flagged(provider: ManifestBeaconProvider) -> None:
    result = provider.explain_concept(concept="chronostratum")
    assert "experimental" in result.status or any(
        "experimental" in a for a in result.next_actions
    )


# ---------------------------------------------------------------------------
# guardrails
# ---------------------------------------------------------------------------


def test_guardrails_returns_rules(provider: ManifestBeaconProvider) -> None:
    result = provider.guardrails()
    assert result.rules
    assert any("schema" in r.lower() for r in result.rules)


def test_guardrails_sources_populated(provider: ManifestBeaconProvider) -> None:
    result = provider.guardrails()
    assert result.confidence


def test_guardrails_task_hint_filters(provider: ManifestBeaconProvider) -> None:
    result_schema = provider.guardrails(task_hint="schema migrations")
    # Should include the schema guardrail
    assert result_schema.rules


def test_guardrails_includes_avoid_list(provider: ManifestBeaconProvider) -> None:
    result = provider.guardrails()
    assert "Change schema." in result.related_guardrails


def test_guardrails_required_checks_from_build_test(provider: ManifestBeaconProvider) -> None:
    result = provider.guardrails()
    assert result.required_checks
    assert any("pytest" in cmd for cmd in result.required_checks)
