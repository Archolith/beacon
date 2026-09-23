"""P1 of near-zero authoring: markers, conventions, frontmatter, nav, CODEOWNERS, conformance."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from beacon.build import policy as policy_mod
from beacon.core.citation_digest import digest_citation
from beacon.core.loader import parse_manifest
from beacon.main import app
from beacon.sources.conventions import EXCERPT_CHARS, read_frontmatter
from beacon.sources.declared import collect_declared

runner = CliRunner()


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


_AGENTS = (
    "# Agents\n\n"
    "## Start here\n\nRead the router first.\n\n"
    "## Verification\n\n- Run the smallest credible tests.\n- CI runs the full suite.\n\n"
    "## Layout\n\nsrc holds the code.\n"
)


def _resolve(root: Path, intent: dict | None = None) -> policy_mod.MergedProjectFacts:
    return policy_mod.resolve_project_facts(
        intent=parse_manifest(intent) if intent else None,
        git_records=(),
        docs_root=root,
        repo_root=root,
        strict=False,
        declared=collect_declared(root),
    )


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------


def test_a_marked_guardrail_is_exact_and_pinned(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "AGENTS.md",
        "# Agents\n\n<!-- beacon:guardrail id=no-writes severity=high -->\n"
        "Never write files into indexed projects.\n<!-- /beacon -->\n",
    )
    conv = collect_declared(tmp_path).conventions
    (guard,) = conv.guardrails
    assert guard["id"] == "no-writes" and guard["severity"] == "high"
    assert guard["rule"] == "Never write files into indexed projects."
    source = guard["sources"][0]
    assert (source["line_start"], source["line_end"]) == (4, 4)
    assert source["digest"] == digest_citation(tmp_path, "AGENTS.md", 4, 4)
    assert conv.by_marker == {"guardrails"}


def test_markers_supply_purpose_non_goals_concepts_commands_and_review_areas(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "README.md",
        "# W\n\n<!-- beacon:purpose -->\nWidgets for every team.\n<!-- /beacon -->\n\n"
        "<!-- beacon:non-goals -->\n- a database\n- a UI\n<!-- /beacon -->\n\n"
        '<!-- beacon:concept id=widget name="Widget" -->\nThe unit of work.\n<!-- /beacon -->\n\n'
        "<!-- beacon:command for=test -->\n`make check`\n<!-- /beacon -->\n\n"
        "<!-- beacon:avoid -->\n- the wire format\n<!-- /beacon -->\n",
    )
    facts = _resolve(tmp_path)
    assert (facts.description, facts.stated_purpose) == ("Widgets for every team.",) * 2
    assert "purpose.one_sentence" not in facts.field_placeholder
    assert facts.non_goals == ("a database", "a UI")
    assert facts.intent_concepts[0]["id"] == "widget"
    assert facts.build_and_test["test"] == "make check"
    assert facts.agent_guidance["avoid_without_review"] == ("the wire format",)
    assert facts.marked_fields == {
        "purpose.one_sentence",
        "purpose.non_goals",
        "core_concepts",
        "build_and_test.test",
        "agent_guidance.avoid_without_review",
    }


def test_vendor_files_are_never_read(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "CLAUDE.md",
        "<!-- beacon:guardrail id=vendor -->\nFrom a vendor file.\n<!-- /beacon -->\n",
    )
    assert collect_declared(tmp_path).conventions.guardrails == ()


# ---------------------------------------------------------------------------
# Conventions (fallback)
# ---------------------------------------------------------------------------


def test_agents_sections_become_cited_guardrails_and_pointers(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md", _AGENTS)
    conv = collect_declared(tmp_path).conventions
    (guard,) = conv.guardrails
    assert guard["id"] == "agents-verification"
    assert guard["rule"] == "Run the smallest credible tests. CI runs the full suite."
    assert (guard["sources"][0]["line_start"], guard["sources"][0]["line_end"]) == (9, 10)
    assert conv.expected_behavior == (
        "AGENTS.md > Start here (lines 5-5)",
        "AGENTS.md > Layout (lines 14-14)",
    )
    assert conv.by_convention == {"guardrails", "agent_guidance.expected_behavior"}


def test_markers_replace_the_heading_fallback(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "AGENTS.md",
        _AGENTS + "\n<!-- beacon:guardrail id=only -->\nThe one rule.\n<!-- /beacon -->\n",
    )
    assert [g["id"] for g in collect_declared(tmp_path).conventions.guardrails] == ["only"]


def test_security_reporting_is_a_guardrail_but_known_limits_are_not(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "SECURITY.md",
        "# Security\n\n## Reporting a Vulnerability\n\nEmail security@example.com.\n\n"
        "## Known Design Limits (Not Vulnerabilities)\n\nSingle tenant.\n",
    )
    ids = [g["id"] for g in collect_declared(tmp_path).conventions.guardrails]
    assert ids == ["security-reporting-a-vulnerability"]


def test_excerpts_are_capped(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md", "# A\n\n## Rules\n\n" + "word " * 400 + "\n")
    (guard,) = collect_declared(tmp_path).conventions.guardrails
    assert len(guard["rule"]) <= EXCERPT_CHARS and guard["rule"].endswith("...")


def test_glossary_codeowners_and_non_goals_by_convention(tmp_path: Path) -> None:
    _write(tmp_path, "GLOSSARY.md", "# Glossary\n\n## Episode\n\nOne ingest event.\n")
    _write(tmp_path, ".github/CODEOWNERS", "# owners\n/src/core/ @alice @bob\n")
    _write(tmp_path, "README.md", "# W\n\nWidgets.\n\n## Non-goals\n\n- a database\n")
    conv = collect_declared(tmp_path).conventions
    assert [(c["id"], c["definition"], c["status"]) for c in conv.concepts] == [
        ("episode", "One ingest event.", "unknown")
    ]
    assert conv.avoid == ("/src/core/ (review by @alice, @bob; .github/CODEOWNERS)",)
    assert conv.non_goals == ("a database",)


def test_mkdocs_nav_adds_docs_in_order_and_skips_unsafe_paths(tmp_path: Path) -> None:
    _write(tmp_path, "README.md", "# W\n")
    _write(tmp_path, "docs/guide.md", "# Guide\n")
    _write(tmp_path, "docs/api.md", "# API\n")
    _write(
        tmp_path,
        "mkdocs.yml",
        "nav:\n  - Guide: guide.md\n  - Ref:\n    - api.md\n    - ../../etc/passwd.md\n"
        "  - https://x/y.md\n",
    )
    assert collect_declared(tmp_path).canonical_docs == (
        "README.md",
        "docs/guide.md",
        "docs/api.md",
    )


# ---------------------------------------------------------------------------
# Frontmatter and precedence
# ---------------------------------------------------------------------------


def test_frontmatter_status_words_including_artifact_metadata() -> None:
    assert read_frontmatter("---\nstatus: Current\nrole: architecture\n---\n# x\n") == {
        "status": "current",
        "role": "architecture",
    }
    assert read_frontmatter("---\nartifact_status: SUPERSEDED\n---\n") == {"status": "superseded"}
    assert read_frontmatter("---\nartifact_status: PROPOSED\n---\n") == {"status": "planned"}
    assert read_frontmatter("# no frontmatter\n") == {}


def test_frontmatter_refines_derived_docs_but_never_intent(tmp_path: Path) -> None:
    _write(tmp_path, "README.md", "---\nstatus: superseded\n---\n# W\n\nWidgets for teams.\n")
    _write(tmp_path, "AGENTS.md", "---\nstatus: current\n---\n# A\n")
    facts = _resolve(
        tmp_path,
        {
            "beacon_version": "0.1",
            "project": {"name": "w"},
            "canonical_docs": [{"path": "README.md", "status": "current"}],
        },
    )
    statuses = {doc["path"]: doc["status"] for doc in facts.canonical_docs}
    assert statuses == {"README.md": "current", "AGENTS.md": "current"}


def test_intent_guardrails_come_first_and_win_on_id(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "AGENTS.md",
        "# A\n\n<!-- beacon:guardrail id=shared -->\nFrom docs.\n<!-- /beacon -->\n\n"
        "<!-- beacon:guardrail id=extra -->\nOnly in docs.\n<!-- /beacon -->\n",
    )
    facts = _resolve(
        tmp_path,
        {
            "beacon_version": "0.1",
            "project": {"name": "w"},
            "guardrails": [{"id": "shared", "rule": "From beacon.yaml."}],
        },
    )
    assert [(g["id"], g["rule"]) for g in facts.guardrails] == [
        ("shared", "From beacon.yaml."),
        ("extra", "Only in docs."),
    ]
    assert facts.field_authority["guardrails"] == "intent+declared"


# ---------------------------------------------------------------------------
# Conformance warning and connect-time instructions
# ---------------------------------------------------------------------------


def test_build_warns_when_fields_come_from_conventions(tmp_path: Path) -> None:
    _write(tmp_path, "README.md", "# W\n\nWidgets for every team.\n")
    _write(tmp_path, "AGENTS.md", _AGENTS)
    result = runner.invoke(app, ["build", "--repo", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    conformance = json.loads(result.output)["result"]["conformance"]
    assert "guardrails" in conformance["by_convention"]
    assert "project.name" in conformance["inferred"]
    assert "beacon:guardrail" in conformance["hint"]

    text = runner.invoke(app, ["build", "--repo", str(tmp_path), "--gaps-only"])
    assert "conforming docs give better results" in text.output


def test_connect_instructions_ask_agents_to_load_lazily() -> None:
    from beacon.mcp.server import mcp

    instructions = mcp.instructions or ""
    assert "lazily" in instructions and "task_hint" in instructions
    assert len(instructions) < 500  # paid on every connection


def test_a_doc_listed_without_status_takes_its_frontmatter(tmp_path: Path) -> None:
    import yaml

    _write(tmp_path, "README.md", "# W\n\nWidgets for every team.\n")
    _write(tmp_path, "docs/old.md", "---\nstatus: superseded\n---\n# Old roadmap\n")
    _write(tmp_path, "docs/pinned.md", "---\nstatus: superseded\n---\n# Pinned\n")
    _write(tmp_path, "docs/plain.md", "# Plain\n")
    overlay = {
        "beacon_version": "0.1",
        "project": {"status": "experimental"},
        "canonical_docs": [
            {"path": "docs/old.md"},
            {"path": "docs/pinned.md", "status": "current"},
            {"path": "docs/plain.md"},
        ],
    }
    _write(tmp_path, "beacon.yaml", yaml.safe_dump(overlay, sort_keys=False))
    result = runner.invoke(app, ["build", "--repo", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    built = yaml.safe_load((tmp_path / "beacon.generated.yaml").read_text(encoding="utf-8"))
    statuses = {doc["path"]: doc["status"] for doc in built["canonical_docs"]}
    # Unstated -> frontmatter; stated -> intent wins; neither -> current.
    assert statuses["docs/old.md"] == "superseded"
    assert statuses["docs/pinned.md"] == "current"
    assert statuses["docs/plain.md"] == "current"


def test_markers_in_one_document_keep_the_fallback_for_the_others(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "AGENTS.md",
        _AGENTS + "\n<!-- beacon:guardrail id=marked -->\nThe marked rule.\n<!-- /beacon -->\n",
    )
    _write(tmp_path, "SECURITY.md", "# Security\n\n## Reporting\n\nEmail security@example.com.\n")
    ids = [g["id"] for g in collect_declared(tmp_path).conventions.guardrails]
    # AGENTS.md's markers replace its headings; SECURITY.md still uses its own.
    assert ids == ["marked", "security-reporting"]
