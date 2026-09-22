"""Tests for the v0.3 build pipeline: policy, projection, and ``beacon build``.

Pins the authority rules (intent > reality/history, fail closed on
ambiguity), deterministic projection without an LLM, byte-identical rebuilds,
and the CLI's safe-output behavior.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed-argv local git fixture setup only
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from beacon.build.policy import (
    BUILD_DESCRIPTION_UNRESOLVED,
    BUILD_IDENTITY_ROOT_MISMATCH,
    BUILD_IDENTITY_UNRESOLVED,
    BUILD_INTENT_DOC_MISSING,
    BUILD_NO_CANONICAL_DOCS,
    BuildError,
    resolve_project_facts,
)
from beacon.build.project import build_raw_manifest, render_manifest_yaml
from beacon.core.loader import parse_manifest
from beacon.core.validator import require_valid_manifest
from beacon.main import app
from beacon.sources.base import (
    KIND_MENHIR_DOCUMENT,
    KIND_MENHIR_IDENTITY,
    KIND_MENHIR_STRUCTURE,
    Citation,
    NormalizedRecord,
)
from beacon.sources.menhir import MenhirSourceAdapter

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _menhir_identity(
    name: str = "fixture", description: str = "Fixture project."
) -> NormalizedRecord:
    return NormalizedRecord(
        identity=f"menhir:identity:{name}",
        kind=KIND_MENHIR_IDENTITY,
        payload={
            "name": name,
            "description": description,
            "primary_language": "python",
            "root": "",
            "status": "experimental",
            "scan_fingerprint": "fp-1",
        },
        citations=(Citation("memory", "scan:fp-1"),),
        adapter="menhir",
        adapter_version="1",
        confidence="high",
        confidence_reason="test",
    )


def _menhir_structure() -> NormalizedRecord:
    return NormalizedRecord(
        identity="menhir:structure:fixture",
        kind=KIND_MENHIR_STRUCTURE,
        payload={"entities": {"file": 2}, "edges": {"IMPORTS": 1}, "scan_fingerprint": "fp-1"},
        citations=(Citation("memory", "scan:fp-1"),),
        adapter="menhir",
        adapter_version="1",
        confidence="high",
        confidence_reason="test",
    )


def _menhir_document(path: str) -> NormalizedRecord:
    return NormalizedRecord(
        identity=f"menhir:document:{path}",
        kind=KIND_MENHIR_DOCUMENT,
        payload={
            "path": path,
            "title": path,
            "document_type": "reference",
            "scan_fingerprint": "fp-1",
        },
        citations=(Citation("path", path),),
        adapter="menhir",
        adapter_version="1",
        confidence="high",
        confidence_reason="test",
    )


def _fixture_repo(tmp_path: Path, *, with_git: bool = True) -> Path:
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "README.md").write_text("# Fixture\nA fixture repository.\n", encoding="utf-8")
    (tmp_path / "docs" / "architecture.md").write_text(
        "# Architecture\nLayered.\n", encoding="utf-8"
    )
    if with_git:
        subprocess.run(
            ["git", "init", "-q", str(tmp_path)],
            check=True,
            capture_output=True,  # nosec B603 B607
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "add", "."],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "-m",
                "init",
            ],
            check=True,
            capture_output=True,
        )
    return tmp_path


def _evidence_file(tmp_path: Path, docs: list[str]) -> Path:
    payload = {
        "evidence_version": "1.0",
        "project": {
            "name": "fixture",
            "description": "Fixture project generated through Beacon.",
            "primary_language": "python",
            "root": str(tmp_path),
            "status": "experimental",
            "scan_fingerprint": "fp-e2e",
        },
        "documents": [{"path": p, "title": p, "document_type": "generic"} for p in sorted(docs)],
        "structure": {"entities": {"file": 2}, "edges": {"IMPORTS": 1}},
    }
    path = tmp_path / "menhir-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def test_identity_and_description_fail_closed_without_sources(tmp_path: Path) -> None:
    with pytest.raises(BuildError) as err:
        resolve_project_facts(intent=None, git_records=(), menhir_records=(), docs_root=tmp_path)
    assert err.value.code == BUILD_IDENTITY_UNRESOLVED
    with pytest.raises(BuildError) as err:
        resolve_project_facts(
            intent=None,
            git_records=(),
            menhir_records=(
                NormalizedRecord(
                    identity="x",
                    kind=KIND_MENHIR_IDENTITY,
                    payload={"name": "fixture", "description": ""},
                    citations=(),
                    adapter="menhir",
                    adapter_version="1",
                    confidence="high",
                    confidence_reason="test",
                ),
            ),
            docs_root=tmp_path,
        )
    assert err.value.code == BUILD_DESCRIPTION_UNRESOLVED


def test_menhir_supplies_identity_without_intent(tmp_path: Path) -> None:
    facts = resolve_project_facts(
        intent=None,
        git_records=(),
        menhir_records=(
            _menhir_identity(description="From Menhir."),
            _menhir_document("README.md"),
        ),
        docs_root=_fixture_repo(tmp_path, with_git=False),
    )
    assert facts.description == "From Menhir."
    assert facts.description_authority == "menhir"


def test_intent_wins_over_menhir_for_identity_fields(tmp_path: Path) -> None:
    intent = parse_manifest(
        {
            "beacon_version": "0.1",
            "project": {
                "name": "intent-name",
                "description": "From intent.",
                "status": "current",
                "primary_language": "rust",
            },
            "canonical_docs": [{"path": "README.md", "role": "entrypoint"}],
        }
    )
    facts = resolve_project_facts(
        intent=intent,
        git_records=(),
        menhir_records=(
            _menhir_identity(name="menhir-name", description="From Menhir."),
            _menhir_document("README.md"),
        ),
        docs_root=_fixture_repo(tmp_path, with_git=False),
    )
    assert (facts.name, facts.name_authority) == ("intent-name", "intent")
    assert (facts.description, facts.description_authority) == ("From intent.", "intent")
    assert (facts.status, facts.status_authority) == ("current", "intent")
    assert (facts.primary_language, facts.primary_language_authority) == ("rust", "intent")
    # Intent's doc entry wins over Menhir's indexed row for the same path.
    assert facts.canonical_docs[0]["role"] == "entrypoint"


def test_missing_menhir_doc_becomes_drift_and_is_omitted(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path, with_git=False)
    facts = resolve_project_facts(
        intent=None,
        git_records=(),
        menhir_records=(
            _menhir_identity(),
            _menhir_document("README.md"),
            _menhir_document("gone.md"),
        ),
        docs_root=root,
    )
    codes = {d.code for d in facts.drift}
    assert "doc_path_missing" in codes
    assert [doc["path"] for doc in facts.canonical_docs] == ["README.md"]


def test_intent_doc_missing_fails_closed(tmp_path: Path) -> None:
    from beacon.core.loader import parse_manifest as parse

    intent = parse(
        {
            "beacon_version": "0.1",
            "project": {"name": "fixture", "description": "d"},
            "canonical_docs": [{"path": "absent.md"}],
        }
    )
    with pytest.raises(BuildError) as err:
        resolve_project_facts(intent=intent, git_records=(), menhir_records=(), docs_root=tmp_path)
    assert err.value.code == BUILD_INTENT_DOC_MISSING


def test_root_mismatch_fails_closed(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path, with_git=False)
    identity = NormalizedRecord(
        identity="menhir:identity:fixture",
        kind=KIND_MENHIR_IDENTITY,
        payload={
            "name": "fixture",
            "description": "d",
            "root": "C:/somewhere/else",
            "scan_fingerprint": "f",
        },
        citations=(),
        adapter="menhir",
        adapter_version="1",
        confidence="high",
        confidence_reason="test",
    )
    with pytest.raises(BuildError) as err:
        resolve_project_facts(
            intent=None,
            git_records=(),
            menhir_records=(identity, _menhir_document("README.md")),
            docs_root=root,
            repo_root=root,
        )
    assert err.value.code == BUILD_IDENTITY_ROOT_MISMATCH


def test_no_surviving_docs_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(BuildError) as err:
        resolve_project_facts(
            intent=None,
            git_records=(),
            menhir_records=(_menhir_identity(), _menhir_document("absent.md")),
            docs_root=tmp_path,
        )
    assert err.value.code == BUILD_NO_CANONICAL_DOCS


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def test_projection_populates_only_evidence_backed_fields(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path, with_git=False)
    facts = resolve_project_facts(
        intent=None,
        git_records=(),
        menhir_records=(_menhir_identity(), _menhir_structure(), _menhir_document("README.md")),
        docs_root=root,
    )
    raw = build_raw_manifest(facts)
    assert raw["project"]["name"] == "fixture"
    assert raw["project"]["description"] == "Fixture project."
    assert raw["guardrails"] == []
    assert raw["build_and_test"] == {"setup": "", "test": "", "benchmark": ""}
    assert raw["current_focus"] == []
    assert raw["purpose"]["one_sentence"] == "Fixture project."
    structure = raw["core_concepts"][0]
    assert structure["id"] == "project-structure"
    assert structure["sources"][0]["type"] == "memory"
    assert structure["sources"][0]["title"].startswith("Menhir structure scan (fp-1)")
    manifest = parse_manifest(raw)
    require_valid_manifest(manifest, docs_root=root)


def test_manifest_render_is_byte_deterministic_with_note(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path, with_git=False)
    facts = resolve_project_facts(
        intent=None,
        git_records=(),
        menhir_records=(_menhir_identity(), _menhir_structure(), _menhir_document("README.md")),
        docs_root=root,
    )
    raw = build_raw_manifest(facts)
    first = render_manifest_yaml(raw, note="Generated by Menhir (bridge v2)")
    second = render_manifest_yaml(raw, note="Generated by Menhir (bridge v2)")
    assert first == second
    assert first.startswith(b"# Generated by Menhir (bridge v2)\n")
    assert first.endswith(b"\n")
    plain = render_manifest_yaml(raw)
    assert not plain.startswith(b"#")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_build_cli_generates_valid_deterministic_output(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md", "docs/architecture.md"])

    def _build(*, force: bool) -> dict[str, object]:
        args = [
            "build",
            "--repo",
            str(root),
            "--menhir-evidence",
            str(evidence),
            "--out",
            "beacon.generated.yaml",
            "--snapshot-out",
            "beacon.snapshot.json",
            "--note",
            "Generated by Menhir (bridge v2)",
            "--format",
            "json",
        ]
        if force:
            args.append("--force")
        result = runner.invoke(app, args, catch_exceptions=False)
        assert result.exit_code == 0, result.output
        return json.loads(result.output)["result"]

    first = _build(force=False)
    manifest_path = root / "beacon.generated.yaml"
    assert manifest_path.is_file()
    manifest_bytes = manifest_path.read_bytes()
    assert manifest_bytes.startswith(b"# Generated by Menhir (bridge v2)\n")

    # The generated output validates with zero errors through the real CLI.
    validated = runner.invoke(
        app, ["validate", str(manifest_path), "--format", "json"], catch_exceptions=False
    )
    assert validated.exit_code == 0, validated.output
    report = json.loads(validated.output)
    assert report["result"]["servable"] is True
    assert report["result"]["errors"] == 0

    # Snapshot written next to the manifest and loadable.
    snapshot_path = root / "beacon.snapshot.json"
    assert snapshot_path.is_file()
    assert first["snapshot_manifest_sha256"] == first["manifest_sha256"]
    assert first["concepts"] >= 1
    snapshot_one = snapshot_path.read_bytes()

    # Unchanged rebuild is byte-identical (manifest AND snapshot).
    second = _build(force=True)
    assert manifest_path.read_bytes() == manifest_bytes
    assert snapshot_path.read_bytes() == snapshot_one
    assert second["manifest_sha256"] == first["manifest_sha256"]
    assert second["snapshot_manifest_sha256"] == first["snapshot_manifest_sha256"]


def test_build_cli_refuses_existing_output_without_force(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    (root / "beacon.generated.yaml").write_text("# existing\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["build", "--repo", str(root), "--menhir-evidence", str(evidence)],
        catch_exceptions=False,
    )
    assert result.exit_code == 2
    assert "build_output_exists" in result.stderr


def test_build_cli_refuses_snapshot_collision_with_manifest(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    result = runner.invoke(
        app,
        [
            "build",
            "--repo",
            str(root),
            "--menhir-evidence",
            str(evidence),
            "--snapshot-out",
            "beacon.generated.yaml",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 2
    assert "build_snapshot_collision" in result.stderr


def test_build_cli_reports_drift_for_missing_doc(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md", "docs/gone.md"])
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
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    codes = {d["code"] for d in payload["result"]["drift"]}
    assert "doc_path_missing" in codes


def test_build_cli_requires_a_source(tmp_path: Path) -> None:
    result = runner.invoke(app, ["build"], catch_exceptions=False)
    assert result.exit_code == 2
    assert "build_no_sources" in result.stderr


def test_build_cli_fails_closed_on_bad_evidence(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    bad = root / "bad.json"
    bad.write_text(json.dumps({"evidence_version": "0.9", "project": {}}), encoding="utf-8")
    result = runner.invoke(
        app, ["build", "--menhir-evidence", str(bad), "--format", "json"], catch_exceptions=False
    )
    assert result.exit_code == 2
    envelope = json.loads(result.output)
    assert any(d["code"] == "menhir_evidence_invalid" for d in envelope["diagnostics"])


def test_adapter_origin_reaches_repository_field(tmp_path: Path) -> None:
    """The git adapter's sanitized origin URL becomes project.repository."""
    root = _fixture_repo(tmp_path)
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin", "https://example.com/fixture.git"],
        check=True,
        capture_output=True,
    )
    evidence = _evidence_file(root, ["README.md"])
    result = runner.invoke(
        app,
        ["build", "--repo", str(root), "--menhir-evidence", str(evidence), "--format", "json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["result"]["authorities"]["repository"] == "git"
    manifest_text = (root / "beacon.generated.yaml").read_text(encoding="utf-8")
    assert "example.com/fixture.git" in manifest_text


def test_build_stdout_mode_emits_manifest_bytes(tmp_path: Path) -> None:
    """`--out -` streams only the YAML (the embedding-generator contract)."""
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    result = runner.invoke(
        app,
        [
            "build",
            "--repo",
            str(root),
            "--menhir-evidence",
            str(evidence),
            "--out",
            "-",
            "--note",
            "Generated by Menhir beacon v1",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("# Generated by Menhir beacon v1\n")
    assert "beacon_version" in result.stdout
    # Stdout mode forbids snapshot output.
    refused = runner.invoke(
        app,
        [
            "build",
            "--repo",
            str(root),
            "--menhir-evidence",
            str(evidence),
            "--out",
            "-",
            "--snapshot-out",
            "beacon.snapshot.json",
        ],
        catch_exceptions=False,
    )
    assert refused.exit_code == 2
    assert "build_stdout_snapshot_unsupported" in refused.stderr


def test_build_degrades_when_repo_has_no_git(tmp_path: Path) -> None:
    """Tier 1 is optional: a non-git --repo degrades instead of failing."""
    root = _fixture_repo(tmp_path, with_git=False)
    evidence = _evidence_file(root, ["README.md"])
    result = runner.invoke(
        app,
        [
            "build",
            "--repo",
            str(root),
            "--menhir-evidence",
            str(evidence),
            "--out",
            "beacon.generated.yaml",
            "--format",
            "json",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.output)["result"]
    assert payload["git_head"] is None
    assert payload["authorities"]["repository"] == ""


def test_menhir_adapter_round_trips_through_build(tmp_path: Path) -> None:
    """The evidence file written for the CLI parses into the expected records."""
    root = _fixture_repo(tmp_path, with_git=False)
    evidence = _evidence_file(root, ["README.md"])
    records = MenhirSourceAdapter(evidence).collect()
    kinds = {record.kind for record in records}
    assert KIND_MENHIR_IDENTITY in kinds
    assert KIND_MENHIR_DOCUMENT in kinds


# ---------------------------------------------------------------------------
# Provenance of defaults (F6)
# ---------------------------------------------------------------------------


def _build_json(root: Path, evidence: Path, *extra: str) -> dict[str, object]:
    result = runner.invoke(
        app,
        ["build", "--repo", str(root), "--menhir-evidence", str(evidence), "--format", "json"]
        + list(extra),
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["result"]


def test_absent_evidence_status_is_attributed_to_beacon_default(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    del payload["project"]["status"]
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    result = _build_json(root, evidence)
    authorities = result["authorities"]
    assert isinstance(authorities, dict)
    # The schema-required project.status is still filled, but the report says
    # it is Beacon's default -- never a claim attributed to Menhir.
    assert authorities["status"] == "default"
    manifest = parse_manifest(
        yaml.safe_load((root / "beacon.generated.yaml").read_text(encoding="utf-8"))
    )
    assert manifest.project.status == "experimental"


def test_evidence_status_is_attributed_to_menhir(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    authorities = _build_json(root, evidence)["authorities"]
    assert isinstance(authorities, dict)
    assert authorities["status"] == "menhir"


def test_audiences_are_omitted_without_a_source(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    result = _build_json(root, evidence)
    authorities = result["authorities"]
    assert isinstance(authorities, dict)
    assert authorities["audiences"] == ""
    text = (root / "beacon.generated.yaml").read_text(encoding="utf-8")
    assert "coding-agents" not in text
    assert "audiences: []" in text


# ---------------------------------------------------------------------------
# Decision id collisions (F5)
# ---------------------------------------------------------------------------


def test_colliding_decision_titles_get_deterministic_distinct_ids(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["decisions"] = [
        {"title": title, "summary": f"Summary of {title}."}
        for title in ("keep-one-root", "Keep One Root", "日本", "中文", "Project Structure")
    ]
    evidence.write_text(json.dumps(payload), encoding="utf-8")

    def _ids() -> list[str]:
        result = runner.invoke(
            app,
            ["build", "--repo", str(root), "--menhir-evidence", str(evidence), "--out", "-"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        raw = yaml.safe_load(result.stdout)
        return [concept["id"] for concept in raw["core_concepts"]]

    ids = _ids()
    assert len(ids) == len({i.lower() for i in ids}) == 6
    assert ids[0] == "project-structure"
    # Sorted-title order; case variants and the reserved structure id get a
    # stable numeric suffix, non-ASCII titles a stable content-derived slug.
    assert ids[1:4] == ["keep-one-root", "project-structure-2", "keep-one-root-2"]
    assert all(i.startswith("decision-") for i in ids[4:])
    assert ids[4] != ids[5]
    assert _ids() == ids  # deterministic across rebuilds


# ---------------------------------------------------------------------------
# Intent manifests through the CLI (F7)
# ---------------------------------------------------------------------------

_INTENT = """\
beacon_version: "0.1"
project:
  name: intent-project
  tagline: The tagline the maintainer wrote.
  description: Project description text.
  status: current
  license: MIT
purpose:
  one_sentence: One sentence from intent.
  problem: The problem statement.
audiences:
  - maintainers
core_concepts:
  - id: my-concept
    name: My concept
    definition: A maintainer-authored concept.
    status: current
    sources:
      - type: doc
        title: Read me
        path: README.md
canonical_docs:
  - path: README.md
    role: entrypoint
    status: current
    title: Read me
  - path: docs/architecture.md
    role: architecture
    status: superseded
    title: Old architecture
agent_guidance:
  read_first:
    - docs/architecture.md
  safe_first_tasks:
    - write tests
  avoid_without_review:
    - src/core
  expected_behavior:
    - keep diffs small
build_and_test:
  test: pytest -q
guardrails:
  - id: no-net
    rule: No network access.
    severity: low
project_state:
  active_work:
    title: Shipping the build pipeline
    summary: In progress.
    sources:
      - type: doc
        path: README.md
"""


def test_build_cli_intent_preserves_intent_authored_fields(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    intent = root / "beacon.yaml"
    intent.write_text(_INTENT, encoding="utf-8")
    evidence = _evidence_file(root, ["README.md", "docs/architecture.md"])
    result = runner.invoke(
        app,
        [
            "build",
            "--intent",
            str(intent),
            "--repo",
            str(root),
            "--menhir-evidence",
            str(evidence),
            "--format",
            "json",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)["result"]
    assert report["authorities"]["name"] == "intent"
    assert report["authorities"]["audiences"] == "intent"

    raw = yaml.safe_load((root / "beacon.generated.yaml").read_text(encoding="utf-8"))
    project = raw["project"]
    assert project["name"] == "intent-project"
    assert project["tagline"] == "The tagline the maintainer wrote."
    assert project["license"] == "MIT"
    assert project["description"] == "Project description text."
    assert raw["purpose"]["one_sentence"] == "One sentence from intent."
    assert raw["audiences"] == ["maintainers"]
    concept_ids = [c["id"] for c in raw["core_concepts"]]
    assert "my-concept" in concept_ids
    assert "project-structure" in concept_ids
    docs = {d["path"]: d for d in raw["canonical_docs"]}
    assert docs["docs/architecture.md"]["status"] == "superseded"
    assert docs["docs/architecture.md"]["title"] == "Old architecture"
    guidance = raw["agent_guidance"]
    assert guidance["read_first"] == ["docs/architecture.md"]
    assert guidance["safe_first_tasks"] == ["write tests"]
    assert guidance["avoid_without_review"] == ["src/core"]
    assert guidance["expected_behavior"] == ["keep diffs small"]
    assert raw["project_state"]["active_work"]["title"] == "Shipping the build pipeline"
    assert raw["build_and_test"]["test"] == "pytest -q"
    assert [g["id"] for g in raw["guardrails"]] == ["no-net"]

    # The output is a valid manifest through the real CLI.
    validated = runner.invoke(
        app,
        ["validate", str(root / "beacon.generated.yaml"), "--format", "json"],
        catch_exceptions=False,
    )
    assert validated.exit_code == 0, validated.output


def test_build_cli_intent_concept_id_reserves_generated_ids(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    intent = root / "beacon.yaml"
    intent.write_text(_INTENT.replace("id: my-concept", "id: project-structure"), encoding="utf-8")
    evidence = _evidence_file(root, ["README.md"])
    result = runner.invoke(
        app,
        [
            "build",
            "--intent",
            str(intent),
            "--menhir-evidence",
            str(evidence),
            "--repo",
            str(root),
            "--out",
            "-",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    ids = [c["id"] for c in yaml.safe_load(result.stdout)["core_concepts"]]
    assert ids == ["project-structure", "project-structure-2"]


# ---------------------------------------------------------------------------
# Output safety (F1-F4)
# ---------------------------------------------------------------------------


def _codes(result: Any) -> set[str]:
    envelope = json.loads(result.output)
    return {d["code"] for d in envelope["diagnostics"]}


def _build_args(root: Path, evidence: Path, *extra: str) -> list[str]:
    return [
        "build",
        "--repo",
        str(root),
        "--menhir-evidence",
        str(evidence),
        "--format",
        "json",
        *extra,
    ]


def _with_undocumented_decision(evidence: Path) -> None:
    # A decision without a summary is a concept_definition_missing publication
    # warning: the snapshot policy gate refuses it.
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["decisions"] = [{"title": "Undocumented decision"}]
    evidence.write_text(json.dumps(payload), encoding="utf-8")


def test_snapshot_out_cannot_overwrite_canonical_doc_of_nested_manifest(tmp_path: Path) -> None:
    """F1 repro: docs resolve against the --out directory, so must the guard."""
    root = _fixture_repo(tmp_path)
    (root / "sub").mkdir()
    nested_readme = root / "sub" / "README.md"
    nested_readme.write_text("# Nested\nThe real source doc.\n", encoding="utf-8")
    evidence = _evidence_file(root, ["README.md"])
    result = runner.invoke(
        app,
        _build_args(root, evidence, "--out", "sub/gen.yaml", "--snapshot-out", "README.md"),
        catch_exceptions=False,
    )
    assert result.exit_code == 2, result.output
    assert "build_snapshot_collision" in _codes(result)
    assert nested_readme.read_text(encoding="utf-8") == "# Nested\nThe real source doc.\n"
    assert not (root / "sub" / "gen.yaml").exists()


@pytest.mark.parametrize("escape", ["../escaped.json", "../../escaped.json"])
def test_snapshot_out_is_contained_in_the_repo(tmp_path: Path, escape: str) -> None:
    root = _fixture_repo(tmp_path / "work" / "repo")
    evidence = _evidence_file(root, ["README.md"])
    result = runner.invoke(
        app, _build_args(root, evidence, "--snapshot-out", escape), catch_exceptions=False
    )
    assert result.exit_code == 2, result.output
    assert "build_snapshot_path_invalid" in _codes(result)
    assert not (root / escape).resolve().exists()
    assert not (root / "beacon.generated.yaml").exists()


def test_snapshot_out_absolute_path_outside_repo_is_refused(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path / "repo")
    evidence = _evidence_file(root, ["README.md"])
    outside = tmp_path / "elsewhere.json"
    result = runner.invoke(
        app, _build_args(root, evidence, "--snapshot-out", str(outside)), catch_exceptions=False
    )
    assert result.exit_code == 2, result.output
    assert "build_snapshot_path_invalid" in _codes(result)
    assert not outside.exists()


def test_snapshot_out_refuses_existing_file_without_force(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    important = root / "important.json"
    important.write_text('{"keep": true}', encoding="utf-8")
    result = runner.invoke(
        app, _build_args(root, evidence, "--snapshot-out", "important.json"), catch_exceptions=False
    )
    assert result.exit_code == 2, result.output
    assert "build_snapshot_output_exists" in _codes(result)
    assert important.read_text(encoding="utf-8") == '{"keep": true}'
    assert not (root / "beacon.generated.yaml").exists()


def test_snapshot_out_force_replaces_only_a_beacon_snapshot(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    important = root / "important.json"
    important.write_text('{"keep": true}', encoding="utf-8")
    result = runner.invoke(
        app,
        _build_args(root, evidence, "--snapshot-out", "important.json", "--force"),
        catch_exceptions=False,
    )
    assert result.exit_code == 2, result.output
    assert "build_snapshot_not_replaceable" in _codes(result)
    assert important.read_text(encoding="utf-8") == '{"keep": true}'


def test_snapshot_out_cannot_overwrite_the_evidence_input(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    before = evidence.read_bytes()
    result = runner.invoke(
        app,
        _build_args(root, evidence, "--snapshot-out", evidence.name, "--force"),
        catch_exceptions=False,
    )
    assert result.exit_code == 2, result.output
    assert "build_snapshot_collision" in _codes(result)
    assert evidence.read_bytes() == before


def test_force_does_not_replace_a_canonical_doc(tmp_path: Path) -> None:
    """F3 repro: --out README.md --force used to replace the source doc."""
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    before = (root / "README.md").read_bytes()
    result = runner.invoke(
        app, _build_args(root, evidence, "--out", "README.md", "--force"), catch_exceptions=False
    )
    assert result.exit_code == 2, result.output
    assert "build_output_not_manifest" in _codes(result)
    assert (root / "README.md").read_bytes() == before


def test_force_does_not_replace_a_manifest_shaped_canonical_doc(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    other = root / "other.yaml"
    other.write_text(
        'beacon_version: "0.1"\nproject:\n  name: other\n  description: Other.\n',
        encoding="utf-8",
    )
    evidence = _evidence_file(root, ["README.md", "other.yaml"])
    before = other.read_bytes()
    result = runner.invoke(
        app,
        _build_args(root, evidence, "--out", "other.yaml", "--force"),
        catch_exceptions=False,
    )
    assert result.exit_code == 2, result.output
    assert "build_output_protected" in _codes(result)
    assert other.read_bytes() == before


def test_force_does_not_replace_the_evidence_input(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    before = evidence.read_bytes()
    result = runner.invoke(
        app,
        _build_args(root, evidence, "--out", evidence.name, "--force"),
        catch_exceptions=False,
    )
    assert result.exit_code == 2, result.output
    assert "build_output_protected" in _codes(result)
    assert evidence.read_bytes() == before


def test_force_does_not_replace_the_intent_input(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    intent = root / "beacon.yaml"
    intent.write_text(_INTENT, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "build",
            "--intent",
            str(intent),
            "--repo",
            str(root),
            "--out",
            "beacon.yaml",
            "--force",
            "--format",
            "json",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 2, result.output
    assert "build_output_protected" in _codes(result)
    assert intent.read_text(encoding="utf-8") == _INTENT


def test_force_replaces_a_previous_generated_manifest(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    assert runner.invoke(app, _build_args(root, evidence)).exit_code == 0
    again = runner.invoke(app, _build_args(root, evidence, "--force"), catch_exceptions=False)
    assert again.exit_code == 0, again.output


def test_failed_snapshot_policy_leaves_no_manifest(tmp_path: Path) -> None:
    """F4: every gate runs before any write; a refused build changes nothing."""
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    _with_undocumented_decision(evidence)
    result = runner.invoke(
        app,
        _build_args(root, evidence, "--snapshot-out", "beacon.snapshot.json"),
        catch_exceptions=False,
    )
    assert result.exit_code == 1, result.output
    assert "snapshot_blocked_policy" in _codes(result)
    assert not (root / "beacon.generated.yaml").exists()
    assert not (root / "beacon.snapshot.json").exists()
    assert not [p.name for p in root.iterdir() if p.name.endswith(".tmp")]


def test_failed_snapshot_policy_keeps_previous_manifest_under_force(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    assert runner.invoke(app, _build_args(root, evidence)).exit_code == 0
    manifest = root / "beacon.generated.yaml"
    good = manifest.read_bytes()
    _with_undocumented_decision(evidence)
    result = runner.invoke(
        app,
        _build_args(root, evidence, "--snapshot-out", "beacon.snapshot.json", "--force"),
        catch_exceptions=False,
    )
    assert result.exit_code == 1, result.output
    assert manifest.read_bytes() == good


def test_snapshot_collision_leaves_no_manifest(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    result = runner.invoke(
        app, _build_args(root, evidence, "--snapshot-out", "README.md"), catch_exceptions=False
    )
    assert result.exit_code == 2, result.output
    assert not (root / "beacon.generated.yaml").exists()
