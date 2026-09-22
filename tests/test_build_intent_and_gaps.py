"""The project supplies its own data; Beacon says what is still missing.

* ``beacon build --repo R`` reads ``R/beacon.yaml`` as the intent authority by
  default. ``--intent`` names another maintainer-authored manifest; there is no
  opt-out that drops the project's own manifest.
* A malformed, symlinked, or mid-build-modified own manifest refuses the build
  and writes nothing.
* Every build reports, per catalogued field, who supplied it and what is still
  missing; ``--gaps-only`` produces that report without writing, even when a
  required field is unresolved.
* The published catalogue matches the code, covers every manifest field, and
  every supplied value comes from a tier the catalogue allows.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from beacon.build import policy as policy_mod
from beacon.build.requirements import (
    BEACON_OWNED_FIELDS,
    CATALOGUE,
    catalogue_payload,
)
from beacon.core.schema import BeaconManifest
from beacon.main import app
from tests.test_build_pipeline import _evidence_file, _fixture_repo

runner = CliRunner()

_REPO_ROOT = Path(__file__).resolve().parents[1]

_INTENT: dict[str, Any] = {
    "beacon_version": "0.1",
    "project": {
        "name": "fixture-intent",
        "description": "Fixture project described by its own maintainers.",
        "status": "current",
        "license": "MIT",
    },
    "purpose": {
        "one_sentence": "A fixture that owns its own beacon data.",
        "problem": "Agents need the maintainers' own rules.",
        "non_goals": ["Being a real product."],
    },
    "core_concepts": [
        {
            "id": "ownership",
            "name": "Ownership",
            "definition": "Each project owns its beacon data.",
            "sources": [{"type": "doc", "title": "README", "path": "README.md"}],
        }
    ],
    "canonical_docs": [{"path": "README.md", "role": "entrypoint", "status": "current"}],
    "build_and_test": {"setup": "pip install -e .", "test": "pytest", "benchmark": ""},
    "guardrails": [
        {
            "id": "no-network",
            "rule": "Tests must not reach the network.",
            "severity": "high",
            "sources": [{"type": "doc", "title": "README", "path": "README.md"}],
        }
    ],
}


def _invoke(root: Path, *extra: str, evidence: bool = True) -> tuple[int, dict[str, Any]]:
    args = ["build", "--repo", str(root), "--format", "json", "--force", *extra]
    if evidence:
        path = _evidence_file(root, ["README.md", "docs/architecture.md"])
        args[3:3] = ["--menhir-evidence", str(path)]
    result = runner.invoke(app, args, catch_exceptions=False)
    return result.exit_code, json.loads(result.output)


def _write_intent(root: Path, data: dict[str, Any] | None = None) -> Path:
    path = root / "beacon.yaml"
    path.write_text(yaml.safe_dump(data or _INTENT, sort_keys=False), encoding="utf-8")
    return path


def _manifest(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / "beacon.generated.yaml").read_text(encoding="utf-8"))


def _gap_codes(payload: dict[str, Any]) -> set[str]:
    return {gap["code"] for gap in payload["result"]["gaps"]}


def _rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["field"]: row for row in payload["result"]["requirements"]}


# ---------------------------------------------------------------------------
# The project's own manifest is the intent authority
# ---------------------------------------------------------------------------


def test_repo_beacon_yaml_is_the_default_intent(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    intent_path = _write_intent(root)

    code, payload = _invoke(root)

    assert code == 0, payload
    assert payload["result"]["intent"] == {"path": str(intent_path), "source": "repo_default"}
    manifest = _manifest(root)
    assert manifest["project"]["name"] == "fixture-intent"
    assert manifest["build_and_test"]["test"] == "pytest"
    assert [g["id"] for g in manifest["guardrails"]] == ["no-network"]
    rows = _rows(payload)
    assert rows["guardrails"]["supplied_by"] == ["intent"]
    assert rows["build_and_test.test"]["supplied_by"] == ["intent"]
    assert rows["purpose.one_sentence"]["supplied_by"] == ["intent"]
    assert not _gap_codes(payload) & {
        "test_command_missing",
        "guardrails_missing",
        "problem_missing",
        "purpose_missing",
    }


def test_default_intent_also_reaches_stdout_builds(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _write_intent(root)
    evidence = _evidence_file(root, ["README.md"])

    result = runner.invoke(
        app,
        ["build", "--repo", str(root), "--menhir-evidence", str(evidence), "--out", "-"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert yaml.safe_load(result.output)["project"]["name"] == "fixture-intent"


def _elsewhere(tmp_path: Path, **project: Any) -> Path:
    other = dict(_INTENT, project=dict(_INTENT["project"], **project))
    explicit = tmp_path / "elsewhere.yaml"
    explicit.write_text(yaml.safe_dump(other, sort_keys=False), encoding="utf-8")
    return explicit


@pytest.mark.parametrize("repo_manifest", ["valid", "malformed"])
def test_explicit_intent_cannot_replace_the_repo_manifest(
    tmp_path: Path, repo_manifest: str
) -> None:
    root = _fixture_repo(tmp_path / "repo")
    if repo_manifest == "valid":
        _write_intent(root)
    else:
        (root / "beacon.yaml").write_text("project: [unterminated\n", encoding="utf-8")
    explicit = _elsewhere(tmp_path, name="explicit-intent")

    code, payload = _invoke(root, "--intent", str(explicit))

    assert code == 2
    assert payload["diagnostics"][0]["code"] == "intent_manifest_conflict"
    assert not (root / "beacon.generated.yaml").exists()


def test_explicit_intent_naming_the_repo_manifest_is_accepted(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    intent_path = _write_intent(root)

    code, payload = _invoke(root, "--intent", str(intent_path))

    assert code == 0, payload
    assert payload["result"]["intent"] == {"path": str(intent_path), "source": "repo_default"}


def test_explicit_intent_serves_a_repo_without_its_own_manifest(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path / "repo")
    explicit = _elsewhere(tmp_path, name="explicit-intent")

    code, payload = _invoke(root, "--intent", str(explicit))

    assert code == 0, payload
    assert payload["result"]["intent"] == {"path": str(explicit), "source": "explicit"}
    assert _manifest(root)["project"]["name"] == "explicit-intent"


def test_omitted_status_is_not_a_maintainer_statement(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    project = {k: v for k, v in _INTENT["project"].items() if k != "status"}
    _write_intent(root, dict(_INTENT, project=project))

    code, payload = _invoke(root, "--gaps-only", evidence=False)
    assert code == 0, payload
    assert _rows(payload)["project.status"]["status"] == "default"
    assert "project_status_unknown" in _gap_codes(payload)

    code, payload = _invoke(root)
    assert code == 0, payload
    assert _rows(payload)["project.status"]["supplied_by"] == ["memory"]


def test_stated_status_is_the_maintainers(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _write_intent(root)

    code, payload = _invoke(root)

    assert code == 0, payload
    assert _rows(payload)["project.status"]["supplied_by"] == ["intent"]
    assert _manifest(root)["project"]["status"] == "current"


def test_there_is_no_option_to_ignore_the_project_manifest(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _write_intent(root)

    result = runner.invoke(app, ["build", "--repo", str(root), "--no-intent"])

    assert result.exit_code == 2
    assert not (root / "beacon.generated.yaml").exists()


def test_malformed_repo_manifest_refuses_and_writes_nothing(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    (root / "beacon.yaml").write_text("project: [unterminated\n", encoding="utf-8")
    before = (root / "beacon.yaml").read_bytes()

    code, payload = _invoke(root)

    assert code == 2
    assert payload["diagnostics"][0]["code"] == "intent_manifest_invalid"
    assert (root / "beacon.yaml").read_bytes() == before
    assert not (root / "beacon.generated.yaml").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_symlinked_repo_manifest_is_refused(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path / "repo")
    target = tmp_path / "outside.yaml"
    target.write_text(yaml.safe_dump(_INTENT), encoding="utf-8")
    (root / "beacon.yaml").symlink_to(target)

    code, payload = _invoke(root)

    assert code == 2
    assert payload["diagnostics"][0]["code"] == "intent_manifest_unsafe"
    assert not (root / "beacon.generated.yaml").exists()


@pytest.mark.parametrize("out", ["beacon.generated.yaml", "-"])
def test_manifest_changed_during_build_refuses_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, out: str
) -> None:
    root = _fixture_repo(tmp_path)
    intent_path = _write_intent(root)
    original = policy_mod.resolve_project_facts

    def _edit_then_resolve(**kwargs: Any) -> Any:
        edited = dict(_INTENT, project=dict(_INTENT["project"], name="edited-mid-build"))
        intent_path.write_text(yaml.safe_dump(edited, sort_keys=False), encoding="utf-8")
        return original(**kwargs)

    monkeypatch.setattr(policy_mod, "resolve_project_facts", _edit_then_resolve)
    evidence = _evidence_file(root, ["README.md"])
    result = runner.invoke(
        app,
        ["build", "--repo", str(root), "--menhir-evidence", str(evidence), "--out", out],
        catch_exceptions=False,
    )

    assert result.exit_code == 2
    assert "intent_manifest_changed" in result.output
    assert "fixture-intent" not in result.output
    assert not (root / "beacon.generated.yaml").exists()


def test_repo_manifest_is_never_the_output(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    intent_path = _write_intent(root)
    before = intent_path.read_bytes()

    code, payload = _invoke(root, "--out", "beacon.yaml")

    assert code != 0, payload
    assert intent_path.read_bytes() == before


# ---------------------------------------------------------------------------
# Gap reporting
# ---------------------------------------------------------------------------


def test_init_then_build_keeps_placeholder_gaps(tmp_path: Path) -> None:
    """`beacon init`'s starter description and `unknown` status are not answers."""
    root = _fixture_repo(tmp_path)
    init = runner.invoke(app, ["init", str(root)], catch_exceptions=False)
    assert init.exit_code == 0, init.output

    code, payload = _invoke(root, evidence=False)

    assert code == 0, payload
    assert payload["result"]["intent"]["source"] == "repo_default"
    assert {"purpose_missing", "guardrails_missing", "project_status_unknown"} <= _gap_codes(
        payload
    )


def test_memory_only_build_is_thin_and_lists_gaps(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)

    code, payload = _invoke(root)

    assert code == 0, payload
    assert payload["result"]["intent"] == {"path": None, "source": None}
    assert {"test_command_missing", "guardrails_missing", "problem_missing"} <= _gap_codes(payload)
    rows = _rows(payload)
    assert rows["project.name"]["supplied_by"] == ["memory"]
    assert rows["core_concepts"] == dict(rows["core_concepts"], status="supplied")
    assert rows["core_concepts"]["supplied_by"] == ["memory"]
    assert "concepts_omitted" not in _gap_codes(payload)


def test_repo_only_build_refuses_and_points_at_the_gap_report(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)

    code, payload = _invoke(root, evidence=False)

    assert code == 1
    diagnostic = payload["diagnostics"][0]
    assert diagnostic["code"] == "build_identity_unresolved"
    assert "--gaps-only" in diagnostic["message"]
    assert not (root / "beacon.generated.yaml").exists()


def test_gaps_only_reports_unbuildable_repo_without_writing(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    (root / "beacon.generated.yaml").write_text("# existing\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["build", "--repo", str(root), "--gaps-only", "--format", "json"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["buildable"] is False
    rows = _rows(payload)
    assert set(rows) == {item.field for item in CATALOGUE}
    assert rows["project.name"]["status"] == "missing"
    assert rows["project.status"]["status"] == "default"
    assert rows["project.repository"]["status"] in {"supplied", "missing"}
    required_gaps = {g["code"] for g in payload["result"]["gaps"] if g["required"]}
    assert {"build_identity_unresolved", "build_description_unresolved"} <= required_gaps
    assert (root / "beacon.generated.yaml").read_text(encoding="utf-8") == "# existing\n"


def test_concept_count_matches_the_published_manifest(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _write_intent(root)

    code, payload = _invoke(root)

    assert code == 0, payload
    manifest = _manifest(root)
    assert payload["result"]["concepts"] == len(manifest["core_concepts"]) == 2
    assert _rows(payload)["core_concepts"]["supplied_by"] == ["intent", "memory"]


# ---------------------------------------------------------------------------
# Catalogue conformance
# ---------------------------------------------------------------------------


def _leaf_fields(cls: type, prefix: str = "") -> set[str]:
    """Manifest fields at catalogue granularity (nested only for flat sections)."""
    fields: set[str] = set()
    for field in dataclasses.fields(cls):
        path = f"{prefix}{field.name}"
        nested = field.name in {"project", "purpose", "agent_guidance", "build_and_test"}
        if not prefix and nested:
            subtype = {
                "project": "BeaconProjectInfo",
                "purpose": "BeaconPurpose",
                "agent_guidance": "BeaconAgentGuidance",
                "build_and_test": "BeaconBuildTest",
            }[field.name]
            from beacon.core import schema

            fields |= _leaf_fields(getattr(schema, subtype), f"{path}.")
        else:
            fields.add(path)
    return fields


def test_catalogue_covers_every_manifest_field() -> None:
    catalogued = {item.field for item in CATALOGUE}
    assert _leaf_fields(BeaconManifest) == catalogued | BEACON_OWNED_FIELDS
    assert not catalogued & BEACON_OWNED_FIELDS


@pytest.mark.parametrize("scenario", ["intent", "memory", "both", "init"])
def test_every_supplied_value_comes_from_an_allowed_tier(tmp_path: Path, scenario: str) -> None:
    root = _fixture_repo(tmp_path)
    if scenario in {"intent", "both"}:
        _write_intent(root)
    if scenario == "init":
        assert runner.invoke(app, ["init", str(root)]).exit_code == 0

    code, payload = _invoke(root, evidence=scenario in {"memory", "both"})

    assert code == 0, payload
    for row in payload["result"]["requirements"]:
        assert row["status"] in {"supplied", "missing", "default"}
        if row["status"] == "supplied":
            assert row["supplied_by"], row
            assert set(row["supplied_by"]) <= set(row["allowed_sources"]), row
        else:
            assert row["supplied_by"] == [], row


def test_published_catalogue_matches_the_code() -> None:
    published = json.loads(
        (_REPO_ROOT / "docs" / "schemas" / "beacon-requirements-1.0.json").read_text(
            encoding="utf-8"
        )
    )
    assert published == catalogue_payload()


def test_catalogue_is_well_formed() -> None:
    fields = [item.field for item in CATALOGUE]
    assert len(fields) == len(set(fields))
    codes = [item.gap_code for item in CATALOGUE]
    assert len(codes) == len(set(codes))
    for item in CATALOGUE:
        assert set(item.sources) <= {"intent", "git", "memory", "derived"}
        assert item.sources
        assert item.ask


def test_required_gap_codes_are_the_build_refusal_codes() -> None:
    required = {item.gap_code for item in CATALOGUE if item.required}
    assert required == {
        policy_mod.BUILD_IDENTITY_UNRESOLVED,
        policy_mod.BUILD_DESCRIPTION_UNRESOLVED,
        policy_mod.BUILD_NO_CANONICAL_DOCS,
    }


def test_gap_codes_shared_with_init_match_init() -> None:
    from beacon.core import scaffold

    init_codes = {
        scaffold.REVIEW_PURPOSE_MISSING,
        scaffold.REVIEW_GUARDRAILS_MISSING,
        scaffold.REVIEW_TEST_COMMAND_MISSING,
        scaffold.REVIEW_BUILD_COMMANDS_UNKNOWN,
        scaffold.REVIEW_PROJECT_STATUS_UNKNOWN,
        scaffold.OMITTED_CONCEPTS,
        scaffold.OMITTED_LICENSE,
        scaffold.OMITTED_BENCHMARK,
    }
    assert init_codes <= {item.gap_code for item in CATALOGUE}


def test_symlink_check_is_enforced_on_every_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Platform-independent twin of the symlink test (Windows cannot create one)."""
    root = _fixture_repo(tmp_path)
    intent_path = _write_intent(root)
    real_is_symlink = Path.is_symlink

    def _fake_is_symlink(self: Path) -> bool:
        return self == intent_path or real_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", _fake_is_symlink)

    code, payload = _invoke(root)

    assert code == 2
    assert payload["diagnostics"][0]["code"] == "intent_manifest_unsafe"
    assert not (root / "beacon.generated.yaml").exists()


def _edit_intent_during(
    monkeypatch: pytest.MonkeyPatch, module: Any, name: str, intent_path: Path
) -> None:
    original = getattr(module, name)

    def _edit_then_call(*args: Any, **kwargs: Any) -> Any:
        edited = dict(_INTENT, project=dict(_INTENT["project"], name="edited-mid-build"))
        intent_path.write_text(yaml.safe_dump(edited, sort_keys=False), encoding="utf-8")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, _edit_then_call)


def test_gap_report_refuses_when_the_manifest_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture_repo(tmp_path)
    intent_path = _write_intent(root)
    _edit_intent_during(monkeypatch, policy_mod, "resolve_project_facts", intent_path)

    code, payload = _invoke(root, "--gaps-only")

    assert code == 2
    assert payload["diagnostics"][0]["code"] == "intent_manifest_changed"


def test_snapshot_build_refuses_when_the_manifest_changes_during_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import beacon.main as main_mod

    root = _fixture_repo(tmp_path)
    intent_path = _write_intent(root)
    _edit_intent_during(monkeypatch, main_mod, "_build_verified_snapshot", intent_path)

    code, payload = _invoke(root, "--snapshot-out", "beacon.snapshot.json")

    assert code == 2
    assert payload["diagnostics"][0]["code"] == "intent_manifest_changed"
    assert not (root / "beacon.generated.yaml").exists()
    assert not (root / "beacon.snapshot.json").exists()


@pytest.mark.parametrize("prior", [False, True])
def test_failed_manifest_replace_restores_the_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prior: bool
) -> None:
    import beacon.main as main_mod

    root = _fixture_repo(tmp_path)
    _write_intent(root)
    manifest = root / "beacon.generated.yaml"
    snapshot = root / "beacon.snapshot.json"
    if prior:
        code, payload = _invoke(root, "--snapshot-out", "beacon.snapshot.json")
        assert code == 0, payload
        _write_intent(root, dict(_INTENT, project=dict(_INTENT["project"], name="second")))
    before = {p: p.read_bytes() for p in (manifest, snapshot) if p.exists()}

    real_replace = os.replace

    def _fail_manifest(src: Any, dst: Any) -> None:
        if Path(dst) == manifest:
            raise OSError("simulated manifest replace failure")
        real_replace(src, dst)

    monkeypatch.setattr(main_mod.os, "replace", _fail_manifest)
    code, payload = _invoke(root, "--snapshot-out", "beacon.snapshot.json")
    monkeypatch.setattr(main_mod.os, "replace", real_replace)

    assert code == 2
    assert payload["diagnostics"][0]["code"] == "build_manifest_write_failed"
    after = {p: p.read_bytes() for p in (manifest, snapshot) if p.exists()}
    assert after == before
    leftovers = [p.name for p in root.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_directory_named_beacon_yaml_is_refused_not_ignored(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path / "repo")
    (root / "beacon.yaml").mkdir()
    explicit = _elsewhere(tmp_path, name="explicit-intent")

    for extra in ((), ("--intent", str(explicit))):
        code, payload = _invoke(root, *extra)
        assert code == 2
        assert payload["diagnostics"][0]["code"] == "intent_manifest_unsafe"
    assert not (root / "beacon.generated.yaml").exists()


def test_failed_rollback_keeps_the_recovery_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import beacon.main as main_mod

    root = _fixture_repo(tmp_path)
    _write_intent(root)
    manifest = root / "beacon.generated.yaml"
    snapshot = root / "beacon.snapshot.json"
    code, payload = _invoke(root, "--snapshot-out", "beacon.snapshot.json")
    assert code == 0, payload
    original_snapshot = snapshot.read_bytes()
    _write_intent(root, dict(_INTENT, project=dict(_INTENT["project"], name="second")))

    real_replace = os.replace

    def _fail_manifest_and_restore(src: Any, dst: Any) -> None:
        if Path(dst) == manifest or (
            Path(dst) == snapshot
            and Path(src).suffix == ".tmp"
            and Path(src).name.startswith(".beacon.snapshot.json.")
        ):
            raise OSError("simulated failure")
        real_replace(src, dst)

    monkeypatch.setattr(main_mod.os, "replace", _fail_manifest_and_restore)
    code, payload = _invoke(root, "--snapshot-out", "beacon.snapshot.json")
    monkeypatch.setattr(main_mod.os, "replace", real_replace)

    assert code == 2
    assert payload["diagnostics"][0]["code"] == "build_rollback_failed"
    backups = [p for p in root.iterdir() if p.name.startswith(".beacon.snapshot.json.")]
    assert len(backups) == 1
    assert backups[0].read_bytes() == original_snapshot


def test_same_file_never_raises_on_bad_paths(tmp_path: Path) -> None:
    import beacon.main as main_mod

    real = tmp_path / "beacon.yaml"
    real.write_text("x", encoding="utf-8")
    assert main_mod._same_file(real, real) is True
    assert main_mod._same_file(tmp_path / "missing.yaml", real) is False
    assert main_mod._same_file(tmp_path / "a" / ".." / "beacon.yaml", real) is True


def test_indexed_documents_are_not_claimed_current(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)

    code, payload = _invoke(root)

    assert code == 0, payload
    statuses = {doc["path"]: doc["status"] for doc in _manifest(root)["canonical_docs"]}
    assert statuses == {"README.md": "unknown", "docs/architecture.md": "unknown"}


def test_intent_documents_keep_the_maintainers_status(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _write_intent(root)

    code, payload = _invoke(root)

    assert code == 0, payload
    statuses = {doc["path"]: doc["status"] for doc in _manifest(root)["canonical_docs"]}
    assert statuses["README.md"] == "current"
    assert statuses["docs/architecture.md"] == "unknown"


def test_policy_records_an_authority_for_every_catalogued_field(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _write_intent(root)
    facts = policy_mod.resolve_project_facts(
        intent=None, git_records=(), menhir_records=(), docs_root=root, strict=False
    )
    assert set(facts.field_authority) == {item.field for item in CATALOGUE}


def test_report_reads_policy_authority_rather_than_inferring(tmp_path: Path) -> None:
    from beacon.build.requirements import requirements_report

    root = _fixture_repo(tmp_path)
    facts = policy_mod.resolve_project_facts(
        intent=None, git_records=(), menhir_records=(), docs_root=root, strict=False
    )
    authority = dict(facts.field_authority, guardrails="menhir")
    rows = {
        row["field"]: row
        for row in requirements_report(dataclasses.replace(facts, field_authority=authority))
    }
    # The value is empty, but the report trusts the recorded authority -- and the
    # allowed-tier conformance test is what catches such a policy bug.
    assert rows["guardrails"]["supplied_by"] == ["memory"]
    assert "memory" not in rows["guardrails"]["allowed_sources"]
