"""P0 of near-zero authoring: declared sources, precedence, citation digests, intent validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from beacon.build import policy as policy_mod
from beacon.core.citation_digest import CitationUnavailable, digest_citation, digest_text
from beacon.core.loader import ManifestError, load_beacon_manifest, parse_manifest
from beacon.core.schema import BeaconManifest, served_manifest_payload
from beacon.core.validator import validate_beacon_manifest
from beacon.main import app
from beacon.sources.base import KIND_GIT_TAG, Citation, NormalizedRecord
from beacon.sources.declared import DeclaredFacts, DeclaredValue, collect_declared

runner = CliRunner()

_MIT = (
    "MIT License\n\nCopyright (c) 2026 Someone\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
    "of this software...\n"
)
_APACHE = "                                 Apache License\n                           Version 2.0, January 2004\n"


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The declared source reads the project's own files
# ---------------------------------------------------------------------------


def test_package_manifest_supplies_name_description_license_language(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "widgets"\ndescription = "Widgets for everyone."\nlicense = "MIT"\n',
    )
    facts = collect_declared(tmp_path)
    assert facts.name == DeclaredValue("widgets", "declared", "pyproject.toml", 2)
    assert facts.description == DeclaredValue(
        "Widgets for everyone.", "declared", "pyproject.toml", 3
    )
    assert facts.license is not None and facts.license.value == "MIT"
    assert facts.primary_language is not None and facts.primary_language.value == "Python"


def test_package_json_and_cargo_are_read(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", json.dumps({"name": "web", "license": "ISC"}))
    facts = collect_declared(tmp_path)
    assert facts.name is not None and facts.name.value == "web"
    assert facts.license is not None and facts.license.value == "ISC"

    cargo = tmp_path / "cargo"
    _write(cargo, "Cargo.toml", '[package]\nname = "crab"\nlicense = "Apache-2.0"\n')
    rust = collect_declared(cargo)
    assert rust.name is not None and rust.name.value == "crab"
    assert rust.primary_language is not None and rust.primary_language.value == "Rust"


def test_readme_lead_skips_badges_and_strips_markup(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "README.md",
        "---\ntitle: x\n---\n# Widgets\n\n[![ci](https://x/badge.svg)](https://x)\n\n"
        "> Widgets **make** [everything](https://x) better, `quickly`.\n\n## Install\n",
    )
    facts = collect_declared(tmp_path)
    assert facts.description == DeclaredValue(
        "Widgets make everything better, quickly.", "declared", "README.md", 8
    )


def test_readme_without_prose_states_no_description(tmp_path: Path) -> None:
    _write(tmp_path, "README.md", "# Widgets\n\n## Install\n")
    assert collect_declared(tmp_path).description is None


@pytest.mark.parametrize(
    ("filename", "text", "expected"),
    [
        ("LICENSE", _MIT, ("MIT", "declared")),
        ("LICENSE", _APACHE, ("Apache-2.0", "declared")),
        ("LICENSE-MIT", "custom text nobody recognizes\n", ("MIT", "inferred")),
    ],
)
def test_license_text_is_matched_to_spdx(
    tmp_path: Path, filename: str, text: str, expected: tuple[str, str]
) -> None:
    _write(tmp_path, filename, text)
    facts = collect_declared(tmp_path)
    assert facts.license is not None
    assert (facts.license.value, facts.license.tier) == expected


def test_an_unrecognized_license_file_states_nothing(tmp_path: Path) -> None:
    _write(tmp_path, "LICENSE", "All rights reserved.\n")
    assert collect_declared(tmp_path).license is None


def test_ci_commands_are_the_projects_own_install_and_test(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname = "w"\n')
    _write(
        tmp_path,
        ".github/workflows/publish.yml",
        "jobs:\n  p:\n    steps:\n      - run: pip install -e .\n      - run: pytest -x\n",
    )
    workflow = (
        "jobs:\n"
        "  t:\n"
        "    steps:\n"
        "      - run: |\n"
        "          python -m pip install --upgrade pip\n"
        '          python -m pip install -e ".[dev]"\n'
        "      - run: pytest --token ${{ secrets.X }}\n"
        "      - run: python -m pytest -q\n"
    )
    _write(tmp_path, ".github/workflows/tests.yml", workflow)
    facts = collect_declared(tmp_path)
    assert facts.setup == DeclaredValue(
        'python -m pip install -e ".[dev]"', "declared", ".github/workflows/tests.yml", 6
    )
    assert facts.test == DeclaredValue(
        "python -m pytest -q", "declared", ".github/workflows/tests.yml", 8
    )


def test_without_ci_the_marker_command_is_an_inferred_guess(tmp_path: Path) -> None:
    _write(tmp_path, "Cargo.toml", '[package]\nname = "crab"\n')
    facts = collect_declared(tmp_path)
    assert facts.setup == DeclaredValue("cargo build", "inferred", "Cargo.toml")
    assert facts.test == DeclaredValue("cargo test", "inferred", "Cargo.toml")


def test_entry_docs_in_reading_order(tmp_path: Path) -> None:
    for rel in ("SECURITY.md", "AGENTS.md", "README.md", "docs/architecture.md", "CLAUDE.md"):
        _write(tmp_path, rel, "# x\n")
    facts = collect_declared(tmp_path)
    # Agent-vendor files such as CLAUDE.md are never read.
    assert facts.canonical_docs == ("README.md", "AGENTS.md", "SECURITY.md", "docs/architecture.md")
    assert facts.doc_role("AGENTS.md") == "entrypoint"


def test_symlinked_package_manifest_is_refused(tmp_path: Path) -> None:
    outside = _write(tmp_path / "outside", "pyproject.toml", '[project]\nname = "evil"\n')
    repo = tmp_path / "repo"
    repo.mkdir()
    try:
        (repo / "pyproject.toml").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert collect_declared(repo).name is None


# ---------------------------------------------------------------------------
# Precedence in the build policy
# ---------------------------------------------------------------------------


def _intent(**project: str) -> BeaconManifest:
    return parse_manifest({"beacon_version": "0.1", "project": dict(project)})


def _resolve(root: Path, intent: BeaconManifest | None, declared: DeclaredFacts, **kw: object):
    _write(root, "README.md", "# x\n")
    return policy_mod.resolve_project_facts(
        intent=intent,
        git_records=kw.pop("git_records", ()),  # type: ignore[arg-type]
        docs_root=root,
        repo_root=root,
        strict=False,
        declared=declared,
        **kw,  # type: ignore[arg-type]
    )


def test_intent_wins_for_judgment_and_declared_fills_the_rest(tmp_path: Path) -> None:
    declared = DeclaredFacts(
        name=DeclaredValue("archolith-widgets", "declared", "pyproject.toml", 2),
        description=DeclaredValue("From the manifest.", "declared", "pyproject.toml", 3),
        test=DeclaredValue("pytest -q", "declared", ".github/workflows/ci.yml", 9),
        canonical_docs=("README.md",),
    )
    facts = _resolve(tmp_path, _intent(name="widgets"), declared)
    assert (facts.name, facts.name_authority) == ("widgets", "intent")
    assert (facts.description, facts.description_authority) == ("From the manifest.", "declared")
    assert facts.build_and_test["test"] == "pytest -q"
    assert facts.field_authority["build_and_test.test"] == "declared"
    assert facts.field_citations["build_and_test.test"] == ".github/workflows/ci.yml:9"
    assert facts.field_authority["canonical_docs"] == "declared"


def test_the_checkout_wins_for_the_license_and_the_contradiction_is_drift(tmp_path: Path) -> None:
    declared = DeclaredFacts(license=DeclaredValue("Apache-2.0", "declared", "LICENSE", 1))
    facts = _resolve(tmp_path, _intent(name="w", license="MIT"), declared)
    assert facts.license == "Apache-2.0"
    assert facts.field_authority["project.license"] == "declared"
    assert [d.code for d in facts.drift] == ["intent_contradicts_checkout"]


def test_an_inferred_license_never_overrides_intent(tmp_path: Path) -> None:
    declared = DeclaredFacts(license=DeclaredValue("MIT", "inferred", "LICENSE-MIT"))
    facts = _resolve(tmp_path, _intent(name="w", license="BSD-3-Clause"), declared)
    assert facts.license == "BSD-3-Clause"
    assert facts.drift == ()


def test_git_tags_become_recently_completed_unless_intent_states_it(tmp_path: Path) -> None:
    def tag(name: str, date: str) -> NormalizedRecord:
        return NormalizedRecord(
            identity=f"git:tag:{name}",
            kind=KIND_GIT_TAG,
            payload={"name": name, "commit": "a" * 40, "date": date},
            citations=(Citation("path", "."),),
            adapter="git",
            adapter_version="1",
            confidence="high",
            confidence_reason="test",
        )

    records = (tag("v0.1.0", "2026-01-01T00:00:00Z"), tag("v0.2.0", "2026-02-01T00:00:00Z"))
    facts = _resolve(tmp_path, None, DeclaredFacts(), git_records=records)
    assert facts.project_state is not None
    titles = [item["title"] for item in facts.project_state["recently_completed"]]
    assert titles == ["Release v0.2.0", "Release v0.1.0"]
    assert facts.field_authority["project_state"] == "git"


def test_an_explicit_unknown_status_yields_to_memory(tmp_path: Path) -> None:
    from beacon.sources.memory import MemorySourceAdapter
    from tests.test_build_pipeline import _evidence_file, _fixture_repo

    root = _fixture_repo(tmp_path)
    records = MemorySourceAdapter(_evidence_file(root, ["README.md"])).collect()
    facts = policy_mod.resolve_project_facts(
        intent=_intent(status="unknown"),
        git_records=(),
        memory_records=records,
        docs_root=root,
        strict=False,
    )
    assert facts.status_authority == "memory"


# ---------------------------------------------------------------------------
# Citation digests and drift
# ---------------------------------------------------------------------------


def test_digest_is_stable_across_line_endings_and_trailing_space() -> None:
    assert digest_text("a\nb  \n") == digest_text("a\r\nb\r\n")
    assert digest_text("one\ntwo\nthree", 2, 3) == digest_text("two\nthree")
    assert digest_text("one\ntwo", 2) == digest_text("two")
    with pytest.raises(CitationUnavailable):
        digest_text("one\ntwo", 2, 5)


def _pinned_intent(root: Path, digest: str) -> BeaconManifest:
    _write(root, "AGENTS.md", "# Rules\nNever write files into indexed projects.\n")
    return parse_manifest(
        {
            "beacon_version": "0.1",
            "project": {"name": "w", "description": "d"},
            "canonical_docs": [{"path": "AGENTS.md"}],
            "guardrails": [
                {
                    "id": "no-writes",
                    "rule": "Never write files into indexed projects.",
                    "sources": [
                        {"type": "doc", "path": "AGENTS.md", "line_start": 2, "digest": digest}
                    ],
                }
            ],
        }
    )


def test_a_pinned_citation_that_still_matches_is_quiet(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md", "# Rules\nNever write files into indexed projects.\n")
    pinned = digest_citation(tmp_path, "AGENTS.md", 2)
    report = validate_beacon_manifest(_pinned_intent(tmp_path, pinned), docs_root=tmp_path)
    assert "source_changed" not in {issue.code for issue in report.issues}


def test_changed_cited_text_is_reported_as_source_changed(tmp_path: Path) -> None:
    manifest = _pinned_intent(tmp_path, "sha256:" + "0" * 64)
    report = validate_beacon_manifest(manifest, docs_root=tmp_path)
    changed = [issue for issue in report.issues if issue.code == "source_changed"]
    assert changed and changed[0].severity == "warning"
    assert changed[0].where == "guardrails[no-writes].sources[]"


def test_a_pinned_citation_to_a_missing_file_is_unavailable(tmp_path: Path) -> None:
    manifest = _pinned_intent(tmp_path, "sha256:" + "0" * 64)
    (tmp_path / "AGENTS.md").unlink()
    codes = {issue.code for issue in validate_beacon_manifest(manifest, docs_root=tmp_path).issues}
    assert "source_unavailable" in codes


def test_a_malformed_digest_is_refused_by_the_loader() -> None:
    with pytest.raises(ManifestError):
        parse_manifest(
            {
                "beacon_version": "0.1",
                "project": {"name": "w"},
                "guardrails": [{"id": "g", "rule": "r", "sources": [{"digest": "md5:abc"}]}],
            }
        )


def test_served_payload_drops_digests(tmp_path: Path) -> None:
    manifest = _pinned_intent(tmp_path, "sha256:" + "0" * 64)
    served = served_manifest_payload(manifest)
    assert "digest" not in served["guardrails"][0]["sources"][0]


# ---------------------------------------------------------------------------
# Intent validation, the status default, and the CLI
# ---------------------------------------------------------------------------


def test_intent_mode_allows_what_the_build_derives() -> None:
    overlay = parse_manifest(
        {"beacon_version": "0.1", "project": {}, "purpose": {"one_sentence": "Why."}}
    )
    published = {issue.code for issue in validate_beacon_manifest(overlay).errors}
    assert {"project_name_missing", "project_description_missing"} <= published
    intent = validate_beacon_manifest(overlay, intent=True)
    assert intent.ok
    assert "test_command_missing" not in {issue.code for issue in intent.issues}


def test_an_omitted_status_is_unknown() -> None:
    assert parse_manifest({"beacon_version": "0.1", "project": {"name": "w"}}).project.status == (
        "unknown"
    )


def test_cli_digest_and_intent_validate(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md", "# Rules\nline two\n")
    result = runner.invoke(app, ["digest", "AGENTS.md", "--lines", "2", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == digest_citation(tmp_path, "AGENTS.md", 2)

    missing = runner.invoke(app, ["digest", "nope.md", "--root", str(tmp_path)])
    assert missing.exit_code == 2

    overlay = _write(
        tmp_path, "beacon.yaml", "beacon_version: '0.1'\nproject:\n  status: unknown\n"
    )
    assert runner.invoke(app, ["validate", str(overlay)]).exit_code == 1
    ok = runner.invoke(app, ["validate", "--intent", str(overlay)])
    assert ok.exit_code == 0, ok.output


def test_init_then_build_needs_no_authoring(tmp_path: Path) -> None:
    """The zero-authoring path: init writes judgment fields only; build derives the rest."""
    from tests.test_build_pipeline import _fixture_repo

    root = _fixture_repo(tmp_path)
    assert runner.invoke(app, ["init", str(root)]).exit_code == 0
    written = yaml.safe_load((root / "beacon.yaml").read_text(encoding="utf-8"))
    assert "name" not in written["project"]

    built = runner.invoke(app, ["build", "--repo", str(root), "--format", "json"])
    assert built.exit_code == 0, built.output
    manifest = load_beacon_manifest(root / "beacon.generated.yaml")
    assert manifest.project.description == "A fixture repository."
    assert validate_beacon_manifest(manifest, docs_root=root).ok


def test_a_short_manifest_value_cites_its_own_key_line(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[tool.x]\nwhatever = "w"\n\n[project]\nname = "w"\n')
    facts = collect_declared(tmp_path)
    assert facts.name == DeclaredValue("w", "declared", "pyproject.toml", 5)


def test_build_reports_a_stale_pinned_citation_as_drift(tmp_path: Path) -> None:
    from tests.test_build_pipeline import _fixture_repo

    root = _fixture_repo(tmp_path)
    overlay = {
        "beacon_version": "0.1",
        "project": {"status": "experimental"},
        "guardrails": [
            {
                "id": "readme-rule",
                "rule": "Keep the README honest.",
                "sources": [
                    {
                        "type": "doc",
                        "path": "README.md",
                        "line_start": 2,
                        "digest": "sha256:" + "0" * 64,
                    }
                ],
            }
        ],
    }
    _write(root, "beacon.yaml", yaml.safe_dump(overlay, sort_keys=False))

    built = runner.invoke(app, ["build", "--repo", str(root), "--format", "json"])
    assert built.exit_code == 0, built.output
    drift = json.loads(built.output)["result"]["drift"]
    assert [d["code"] for d in drift] == ["source_changed"]
    assert "guardrails[readme-rule]" in drift[0]["detail"]
