"""Offline tests for the Beacon CLI — validate and inspect subcommands."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from beacon.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_YAML = textwrap.dedent("""\
    beacon_version: "0.1"
    project:
      name: test-project
      tagline: A minimal test beacon.
      status: experimental
      description: A test project for CLI tests.
    purpose:
      one_sentence: Tests the CLI.
      problem: Untested CLIs break silently.
    canonical_docs:
      - path: README.md
        role: entrypoint
        status: current
        title: Test README
    core_concepts:
      - id: core_idea
        name: Core Idea
        status: current
        description: The central thing this project does.
        why_it_exists: Because it needs to exist.
    build_and_test:
      setup: pip install -e .
      test: python -m pytest tests/
    guardrails:
      - id: no_breaking_change
        scope: core
        severity: high
        rule: Do not change the public API without a major version bump.
        applies_to:
          - src/myproject/api.py
""")

MISSING_NAME_YAML = textwrap.dedent("""\
    beacon_version: "0.1"
    project:
      name: ""
      description: A project with no name.
    canonical_docs:
      - path: README.md
        role: entrypoint
        status: current
        title: Test README
""")

WARNING_ONLY_YAML = textwrap.dedent("""\
    beacon_version: "0.1"
    project:
      name: test-project
      description: A project with a warning but no errors.
    canonical_docs:
      - path: README.md
        role: entrypoint
        status: current
        title: Test README
""")
# Missing build_and_test.test triggers a warning (not an error).


@pytest.fixture()
def manifest_dir(tmp_path: Path) -> Path:
    """Return a temp dir with a README.md present (satisfies canonical_docs path check)."""
    (tmp_path / "README.md").write_text("# Test README\n\nSome content.", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def valid_manifest(manifest_dir: Path) -> Path:
    p = manifest_dir / "beacon.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    return p


@pytest.fixture()
def broken_manifest(manifest_dir: Path) -> Path:
    p = manifest_dir / "beacon.yaml"
    p.write_text(MISSING_NAME_YAML, encoding="utf-8")
    return p


@pytest.fixture()
def warning_manifest(manifest_dir: Path) -> Path:
    p = manifest_dir / "beacon.yaml"
    p.write_text(WARNING_ONLY_YAML, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# beacon validate
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_manifest_exits_zero(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(valid_manifest)])
        assert result.exit_code == 0
        assert "✓" in result.output
        assert "0 errors" in result.output

    def test_valid_manifest_prints_path(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(valid_manifest)])
        assert "Validating" in result.output

    def test_broken_manifest_exits_one(self, broken_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(broken_manifest)])
        assert result.exit_code == 1

    def test_broken_manifest_shows_errors(self, broken_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(broken_manifest)])
        assert "✗" in result.output
        assert "error" in result.output.lower()
        assert "project.name" in result.output

    def test_warning_only_exits_zero(self, warning_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(warning_manifest)])
        assert result.exit_code == 0

    def test_warning_only_shows_warnings(self, warning_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(warning_manifest)])
        assert "⚠" in result.output
        assert "warning" in result.output.lower()

    def test_missing_file_exits_one(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["validate", str(tmp_path / "nonexistent.yaml")])
        assert result.exit_code == 1

    def test_invalid_yaml_exits_one(self, tmp_path: Path) -> None:
        bad = tmp_path / "beacon.yaml"
        bad.write_text("key: [unclosed", encoding="utf-8")
        result = runner.invoke(app, ["validate", str(bad)])
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_dangling_doc_path_is_error(self, tmp_path: Path) -> None:
        """A canonical doc that doesn't exist on disk is a validation error."""
        manifest = tmp_path / "beacon.yaml"
        manifest.write_text(
            textwrap.dedent("""\
                beacon_version: "0.1"
                project:
                  name: test
                  description: Test project.
                canonical_docs:
                  - path: DOES_NOT_EXIST.md
                    role: entrypoint
                    status: current
                    title: Missing doc
            """),
            encoding="utf-8",
        )
        result = runner.invoke(app, ["validate", str(manifest)])
        assert result.exit_code == 1
        assert "DOES_NOT_EXIST.md" in result.output


# ---------------------------------------------------------------------------
# beacon inspect
# ---------------------------------------------------------------------------


class TestInspect:
    def test_valid_manifest_exits_zero(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(valid_manifest)])
        assert result.exit_code == 0, result.output

    def test_shows_project_header(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(valid_manifest)])
        assert "test-project" in result.output
        assert "experimental" in result.output

    def test_shows_all_five_tools(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(valid_manifest)])
        assert "beacon_project_overview" in result.output
        assert "beacon_agent_onboarding" in result.output
        assert "beacon_search" in result.output
        assert "beacon_explain_concept" in result.output
        assert "beacon_guardrails" in result.output

    def test_shows_completion_line(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(valid_manifest)])
        assert "5 tools responded" in result.output

    def test_broken_manifest_exits_one(self, broken_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(broken_manifest)])
        assert result.exit_code == 1

    def test_broken_manifest_suggests_validate(self, broken_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(broken_manifest)])
        assert "beacon validate" in result.output

    def test_missing_file_exits_one(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["inspect", str(tmp_path / "nonexistent.yaml")])
        assert result.exit_code == 1

    def test_shows_concept_name(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(valid_manifest)])
        assert "core_idea" in result.output or "Core Idea" in result.output

    def test_shows_guardrails_count(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(valid_manifest)])
        assert "1 total" in result.output

    def test_warning_manifest_notes_warnings(self, warning_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(warning_manifest)])
        assert result.exit_code == 0
        assert "warning" in result.output.lower()
