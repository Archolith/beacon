"""The project supplies its own data; Beacon says what is still missing.

* ``beacon build --repo R`` reads ``R/beacon.yaml`` as the intent authority by
  default, so a project's purpose, guardrails and commands reach the build.
* ``--no-intent`` opts out; ``--intent`` still overrides.
* A malformed or symlinked own manifest refuses the build (fail closed): it is
  never silently skipped, which would publish a beacon without the project's
  guardrails.
* Every successful build reports gaps against the published requirements
  catalogue.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from beacon.build.requirements import CATALOGUE, catalogue_payload
from beacon.main import app
from tests.test_build_pipeline import _evidence_file, _fixture_repo

runner = CliRunner()

_REPO_ROOT = Path(__file__).resolve().parents[1]

_INTENT = {
    "beacon_version": "0.1",
    "project": {
        "name": "fixture-intent",
        "description": "Fixture project described by its own maintainers.",
        "status": "active",
        "license": "MIT",
    },
    "purpose": {
        "one_sentence": "A fixture that owns its own beacon data.",
        "problem": "Agents need the maintainers' own rules.",
        "non_goals": ["Being a real product."],
    },
    "canonical_docs": [{"path": "README.md", "role": "entrypoint", "status": "current"}],
    "build_and_test": {"setup": "pip install -e .", "test": "pytest", "benchmark": ""},
    "guardrails": [
        {
            "id": "no-network",
            "rule": "Tests must not reach the network.",
            "severity": "must",
            "sources": [{"type": "doc", "title": "README", "path": "README.md"}],
        }
    ],
}


def _build(root: Path, *extra: str) -> tuple[int, dict]:
    evidence = _evidence_file(root, ["README.md", "docs/architecture.md"])
    result = runner.invoke(
        app,
        [
            "build",
            "--repo",
            str(root),
            "--menhir-evidence",
            str(evidence),
            "--format",
            "json",
            "--force",
            *extra,
        ],
        catch_exceptions=False,
    )
    return result.exit_code, json.loads(result.output)


def _write_intent(root: Path, data: dict | None = None) -> Path:
    path = root / "beacon.yaml"
    path.write_text(yaml.safe_dump(data or _INTENT, sort_keys=False), encoding="utf-8")
    return path


def _manifest(root: Path) -> dict:
    return yaml.safe_load((root / "beacon.generated.yaml").read_text(encoding="utf-8"))


def _gap_codes(payload: dict) -> set[str]:
    return {gap["code"] for gap in payload["result"]["gaps"]}


def test_repo_beacon_yaml_is_the_default_intent(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    intent_path = _write_intent(root)

    code, payload = _build(root)

    assert code == 0, payload
    result = payload["result"]
    assert result["intent"] == {"path": str(intent_path), "source": "repo_default"}
    manifest = _manifest(root)
    assert manifest["project"]["name"] == "fixture-intent"
    assert manifest["build_and_test"]["test"] == "pytest"
    assert [g["id"] for g in manifest["guardrails"]] == ["no-network"]
    assert manifest["purpose"]["problem"] == "Agents need the maintainers' own rules."
    # What the project supplied is no longer a gap.
    codes = _gap_codes(payload)
    assert not codes & {
        "test_command_missing",
        "guardrails_missing",
        "problem_missing",
        "purpose_missing",
    }


def test_init_then_build_keeps_the_purpose_gap(tmp_path: Path) -> None:
    """`beacon init`'s starter description is not a stated purpose."""
    root = _fixture_repo(tmp_path)
    init = runner.invoke(app, ["init", str(root)], catch_exceptions=False)
    assert init.exit_code == 0, init.output
    assert (root / "beacon.yaml").is_file()

    result = runner.invoke(
        app, ["build", "--repo", str(root), "--format", "json"], catch_exceptions=False
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["result"]["intent"]["source"] == "repo_default"
    assert {"purpose_missing", "guardrails_missing"} <= _gap_codes(payload)


def test_without_own_manifest_build_is_thin_and_lists_gaps(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)

    code, payload = _build(root)

    assert code == 0, payload
    assert payload["result"]["intent"] == {"path": None, "source": None}
    codes = _gap_codes(payload)
    assert {"test_command_missing", "guardrails_missing", "problem_missing"} <= codes
    for gap in payload["result"]["gaps"]:
        assert gap["required"] is False
        assert gap["sources"]


def test_no_intent_opts_out_of_the_repo_manifest(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _write_intent(root)

    code, payload = _build(root, "--no-intent")

    assert code == 0, payload
    assert payload["result"]["intent"]["source"] is None
    assert _manifest(root)["project"]["name"] == "fixture"
    assert "guardrails_missing" in _gap_codes(payload)


def test_explicit_intent_overrides_the_repo_manifest(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _write_intent(root)
    other = dict(_INTENT, project=dict(_INTENT["project"], name="explicit-intent"))
    explicit = tmp_path / "elsewhere.yaml"
    explicit.write_text(yaml.safe_dump(other, sort_keys=False), encoding="utf-8")

    code, payload = _build(root, "--intent", str(explicit))

    assert code == 0, payload
    assert payload["result"]["intent"] == {"path": str(explicit), "source": "explicit"}
    assert _manifest(root)["project"]["name"] == "explicit-intent"


def test_intent_and_no_intent_conflict(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    explicit = _write_intent(root)

    code, payload = _build(root, "--intent", str(explicit), "--no-intent")

    assert code == 2
    assert payload["diagnostics"][0]["code"] == "build_intent_conflict"


def test_malformed_repo_manifest_refuses_and_writes_nothing(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    (root / "beacon.yaml").write_text("project: [unterminated\n", encoding="utf-8")
    before = (root / "beacon.yaml").read_bytes()

    code, payload = _build(root)

    assert code == 2
    assert payload["diagnostics"][0]["code"] == "intent_manifest_invalid"
    assert "--no-intent" in payload["diagnostics"][0]["message"]
    assert (root / "beacon.yaml").read_bytes() == before
    assert not (root / "beacon.generated.yaml").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_symlinked_repo_manifest_is_refused(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path / "repo")
    target = tmp_path / "outside.yaml"
    target.write_text(yaml.safe_dump(_INTENT), encoding="utf-8")
    (root / "beacon.yaml").symlink_to(target)

    code, payload = _build(root)

    assert code == 2
    assert payload["diagnostics"][0]["code"] == "intent_manifest_unsafe"


def test_repo_manifest_is_never_the_output(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    intent_path = _write_intent(root)
    before = intent_path.read_bytes()

    code, payload = _build(root, "--out", "beacon.yaml")

    assert code != 0, payload
    assert intent_path.read_bytes() == before


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
        assert set(item.sources) <= {"intent", "git", "memory"}
        assert item.sources
        assert item.ask


def test_gap_codes_shared_with_init_match_init() -> None:
    from beacon.core import scaffold

    init_codes = {
        scaffold.REVIEW_PURPOSE_MISSING,
        scaffold.REVIEW_GUARDRAILS_MISSING,
        scaffold.REVIEW_TEST_COMMAND_MISSING,
        scaffold.REVIEW_CANONICAL_DOCS_MISSING,
        scaffold.REVIEW_BUILD_COMMANDS_UNKNOWN,
        scaffold.REVIEW_PROJECT_STATUS_UNKNOWN,
        scaffold.OMITTED_CONCEPTS,
        scaffold.OMITTED_LICENSE,
        scaffold.OMITTED_BENCHMARK,
    }
    assert init_codes <= {item.gap_code for item in CATALOGUE}
