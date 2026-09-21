"""Offline tests for the Beacon CLI — init, validate, inspect, export, serve, --version.

All tests run fully offline (no network, no MCP transport actually started; the
framework runner and MCP server module are patched where a server would start).
JSON outputs are parsed and schema-asserted rather than matched as prose.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import textwrap
import types
import unittest.mock as mock
from pathlib import Path

import pytest
from typer.testing import CliRunner

from beacon.main import app

runner = CliRunner()

GITHUB_TOKEN = "ghp_" + "A" * 36

# ---------------------------------------------------------------------------
# Manifest fixtures
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

# test_command_missing + guardrails_missing (both acknowledgeable), no errors.
WARNING_YAML = textwrap.dedent("""\
    beacon_version: "0.1"
    project:
      name: test-project
      description: A project with warnings but no errors.
      status: current
    purpose:
      one_sentence: Has warnings that block publication.
    canonical_docs:
      - path: README.md
        role: entrypoint
        status: current
        title: Test README
""")

# project.name empty -> error.
BROKEN_YAML = textwrap.dedent("""\
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

MALFORMED_YAML = "key: [unclosed"


@pytest.fixture()
def manifest_dir(tmp_path: Path) -> Path:
    """A temp dir with README.md present (satisfies canonical_docs path check)."""
    (tmp_path / "README.md").write_text("# Test README\n\nSome content.", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def valid_manifest(manifest_dir: Path) -> Path:
    p = manifest_dir / "beacon.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    return p


@pytest.fixture()
def warning_manifest(manifest_dir: Path) -> Path:
    p = manifest_dir / "beacon.yaml"
    p.write_text(WARNING_YAML, encoding="utf-8")
    return p


@pytest.fixture()
def broken_manifest(manifest_dir: Path) -> Path:
    p = manifest_dir / "beacon.yaml"
    p.write_text(BROKEN_YAML, encoding="utf-8")
    return p


def _assert_single_json_doc(output: str) -> dict:
    """Assert *output* is exactly one JSON document plus one trailing newline."""
    assert output.endswith("\n")
    assert output.count("\n") == 1
    return json.loads(output)


# ---------------------------------------------------------------------------
# beacon --version
# ---------------------------------------------------------------------------


class TestVersion:
    def test_version_prints_exact_string(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert result.output == "beacon 0.2.0rc2\n"

    def test_version_does_not_start_server(self) -> None:
        blocked = {
            "archolith_mcp_framework": None,
            "beacon.mcp.server": None,
        }
        with mock.patch.dict(sys.modules, blocked):
            result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert result.output == "beacon 0.2.0rc2\n"

    def test_version_no_startup_text(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert "MCP" not in result.output
        assert "pid=" not in result.output


# ---------------------------------------------------------------------------
# No-argument stdio (unchanged) and runtime privacy
# ---------------------------------------------------------------------------


def _patch_server():
    fake_framework = types.ModuleType("archolith_mcp_framework")
    fake_framework.run_server = lambda mcp: None
    fake_server = types.ModuleType("beacon.mcp.server")
    fake_server.mcp = object()
    return mock.patch.dict(
        sys.modules,
        {
            "archolith_mcp_framework": fake_framework,
            "beacon.mcp.server": fake_server,
        },
    )


def test_no_arg_runs_stdio_with_no_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, str | None] = {}
    fake_framework = types.ModuleType("archolith_mcp_framework")
    fake_framework.run_server = lambda mcp: captured.update(
        {
            "check": os.environ.get("FASTMCP_CHECK_FOR_UPDATES"),
            "banner": os.environ.get("FASTMCP_SHOW_SERVER_BANNER"),
        }
    )
    fake_server = types.ModuleType("beacon.mcp.server")
    fake_server.mcp = object()
    with mock.patch.dict(
        sys.modules,
        {"archolith_mcp_framework": fake_framework, "beacon.mcp.server": fake_server},
    ):
        result = runner.invoke(app, [])
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert captured["check"] == "off"
    assert captured["banner"] == "false"


def test_configure_utf8_stdio_reconfigures_both_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encodings: list[str] = []

    class _FakeStream:
        def reconfigure(self, **kwargs: object) -> None:
            encodings.append(str(kwargs.get("encoding")))

    fake_out = _FakeStream()
    fake_err = _FakeStream()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stderr", fake_err)
    from beacon.main import _configure_utf8_stdio

    _configure_utf8_stdio()
    assert encodings == ["utf-8", "utf-8"]


# ---------------------------------------------------------------------------
# beacon serve
# ---------------------------------------------------------------------------


class TestServe:
    def test_serve_validates_and_sets_env_then_restores(
        self, valid_manifest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Baseline: ensure the overrides are absent before the run.
        for key in _SERVE_ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        fake_framework = types.ModuleType("archolith_mcp_framework")
        captured: dict[str, str | None] = {}
        fake_framework.run_server = lambda mcp: captured.update(
            {
                "manifest": os.environ.get("BEACON_MANIFEST_PATH"),
                "check": os.environ.get("FASTMCP_CHECK_FOR_UPDATES"),
            }
        )
        fake_server = types.ModuleType("beacon.mcp.server")
        fake_server.mcp = object()
        with mock.patch.dict(
            sys.modules,
            {"archolith_mcp_framework": fake_framework, "beacon.mcp.server": fake_server},
        ):
            result = runner.invoke(app, ["serve", "--manifest", str(valid_manifest)])
        assert result.exit_code == 0, result.output
        assert result.stdout == ""  # stdout reserved for MCP framing
        # The framework observed the manifest + privacy overrides during the run.
        assert captured["manifest"] == str(valid_manifest.resolve())
        assert captured["check"] == "off"
        # Overrides are scoped to the server run and restored (to absent) afterward.
        assert os.environ.get("BEACON_MANIFEST_PATH") is None
        assert os.environ.get("FASTMCP_CHECK_FOR_UPDATES") is None

    def test_serve_restores_prior_env_values(
        self, valid_manifest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BEACON_MANIFEST_PATH", "prior-manifest")
        monkeypatch.setenv("BEACON_MAX_DOCUMENTS", "11")
        fake_framework = types.ModuleType("archolith_mcp_framework")
        captured: dict[str, str | None] = {}
        fake_framework.run_server = lambda mcp: captured.update(
            {"docs": os.environ.get("BEACON_MAX_DOCUMENTS")}
        )
        fake_server = types.ModuleType("beacon.mcp.server")
        fake_server.mcp = object()
        with mock.patch.dict(
            sys.modules,
            {"archolith_mcp_framework": fake_framework, "beacon.mcp.server": fake_server},
        ):
            result = runner.invoke(
                app,
                ["serve", "--manifest", str(valid_manifest), "--max-documents", "7"],
            )
        assert result.exit_code == 0, result.output
        assert captured["docs"] == "7"
        # Prior values are restored exactly.
        assert os.environ["BEACON_MANIFEST_PATH"] == "prior-manifest"
        assert os.environ["BEACON_MAX_DOCUMENTS"] == "11"

    def test_serve_broken_manifest_exits_one(self, broken_manifest: Path) -> None:
        with _patch_server():
            result = runner.invoke(app, ["serve", "--manifest", str(broken_manifest)])
        assert result.exit_code == 1
        assert result.stdout == ""

    def test_serve_missing_manifest_exits_two(self, tmp_path: Path) -> None:
        with _patch_server():
            result = runner.invoke(app, ["serve", "--manifest", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 2

    def test_serve_provider_limit_failure_exits_two(self, valid_manifest: Path) -> None:
        with _patch_server():
            result = runner.invoke(
                app, ["serve", "--manifest", str(valid_manifest), "--max-documents", "0"]
            )
        assert result.exit_code == 2
        assert result.stdout == ""

    def test_serve_startup_failure_exits_three_and_restores_env(
        self, valid_manifest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in _SERVE_ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        fake_framework = types.ModuleType("archolith_mcp_framework")

        def boom(mcp: object) -> None:
            raise RuntimeError("startup boom")

        fake_framework.run_server = boom
        fake_server = types.ModuleType("beacon.mcp.server")
        fake_server.mcp = object()
        with mock.patch.dict(
            sys.modules,
            {"archolith_mcp_framework": fake_framework, "beacon.mcp.server": fake_server},
        ):
            result = runner.invoke(app, ["serve", "--manifest", str(valid_manifest)])
        assert result.exit_code == 3
        assert result.stdout == ""
        assert "startup boom" not in result.stderr  # no exception details
        # Environment overrides were restored to absent despite the startup failure.
        assert os.environ.get("BEACON_MANIFEST_PATH") is None


# ---------------------------------------------------------------------------
# beacon serve-http
# ---------------------------------------------------------------------------


class TestServeHttp:
    def test_builds_embedded_snapshot_then_serves(self, valid_manifest: Path) -> None:
        with mock.patch("beacon.main._serve_http_snapshot") as run:
            result = runner.invoke(
                app,
                ["serve-http", "--manifest", str(valid_manifest), "--port", "0"],
            )
        assert result.exit_code == 0, result.output
        assert result.stdout == ""
        snap = run.call_args.args[0]
        assert snap.content_mode == "embedded"
        assert run.call_args.kwargs["host"] == "127.0.0.1"
        assert run.call_args.kwargs["port"] == 0
        observation = run.call_args.kwargs["status_observation"]
        assert observation.mode == "startup"
        assert observation.observed_at.endswith("Z")
        assert observation.sources

    def test_non_loopback_host_refuses_before_snapshot(self, valid_manifest: Path) -> None:
        with mock.patch("beacon.main._serve_http_snapshot") as run:
            result = runner.invoke(
                app,
                [
                    "serve-http",
                    "--manifest",
                    str(valid_manifest),
                    "--host",
                    "0.0.0.0",
                ],
            )
        assert result.exit_code == 2
        assert "http_host_not_loopback" in result.stderr
        run.assert_not_called()

    @pytest.mark.parametrize("port", ["-1", "65536"])
    def test_invalid_port_refuses(self, valid_manifest: Path, port: str) -> None:
        with mock.patch("beacon.main._serve_http_snapshot") as run:
            result = runner.invoke(
                app,
                ["serve-http", "--manifest", str(valid_manifest), "--port", port],
            )
        assert result.exit_code == 2
        assert "http_port_invalid" in result.stderr
        run.assert_not_called()

    def test_occupied_loopback_port_refuses_without_path_leak(self, valid_manifest: Path) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            port = int(occupied.getsockname()[1])
            result = runner.invoke(
                app,
                ["serve-http", "--manifest", str(valid_manifest), "--port", str(port)],
            )
        assert result.exit_code == 2
        assert "http_bind_failed" in result.stderr
        assert str(valid_manifest.parent) not in result.stderr

    def test_unresolved_publication_warning_refuses(self, warning_manifest: Path) -> None:
        with mock.patch("beacon.main._serve_http_snapshot") as run:
            result = runner.invoke(app, ["serve-http", "--manifest", str(warning_manifest)])
        assert result.exit_code == 1
        assert "snapshot_blocked_policy" in result.stderr
        run.assert_not_called()

    def test_acknowledged_publication_warnings_allow_start(self, warning_manifest: Path) -> None:
        with mock.patch("beacon.main._serve_http_snapshot") as run:
            result = runner.invoke(
                app,
                [
                    "serve-http",
                    "--manifest",
                    str(warning_manifest),
                    "--acknowledge",
                    "test_command_missing=Manual smoke tests cover this project.",
                    "--acknowledge",
                    "guardrails_missing=Guardrails live in the agent handbook.",
                ],
            )
        assert result.exit_code == 0, result.output
        assert len(run.call_args.args[0].validation.acknowledgements) == 2

    def test_sensitive_content_refuses_without_leaking(self, valid_manifest: Path) -> None:
        valid_manifest.with_name("README.md").write_text(
            f"# Test\n\ntoken {GITHUB_TOKEN} here.\n", encoding="utf-8"
        )
        with mock.patch("beacon.main._serve_http_snapshot") as run:
            result = runner.invoke(app, ["serve-http", "--manifest", str(valid_manifest)])
        assert result.exit_code == 1
        assert "snapshot_blocked_security" in result.stderr
        assert GITHUB_TOKEN not in result.output
        run.assert_not_called()

    def test_reasoned_sensitive_override_allows_start(self, valid_manifest: Path) -> None:
        valid_manifest.with_name("README.md").write_text(
            f"# Test\n\ntoken {GITHUB_TOKEN} here.\n", encoding="utf-8"
        )
        with mock.patch("beacon.main._serve_http_snapshot") as run:
            result = runner.invoke(
                app,
                [
                    "serve-http",
                    "--manifest",
                    str(valid_manifest),
                    "--allow-sensitive",
                    "sensitive_known_token=Fixture token for HTTP CLI tests.",
                ],
            )
        assert result.exit_code == 0, result.output
        assert len(run.call_args.args[0].validation.security_overrides) == 1

    def test_scopeless_guardrail_manifest_builds_http_app(self, valid_manifest: Path) -> None:
        """A guardrail without ``scope`` is valid to the loader and must not crash startup."""
        valid_manifest.write_text(
            VALID_YAML.replace("    scope: core\n", ""), encoding="utf-8"
        )
        assert "scope:" not in valid_manifest.read_text(encoding="utf-8")
        validated = runner.invoke(
            app, ["validate", str(valid_manifest), "--strict-warnings", "--format", "json"]
        )
        assert validated.exit_code == 0, validated.output
        # Run the real startup path (snapshot -> create_http_app -> bind); only the
        # blocking uvicorn loop is replaced.
        with mock.patch("uvicorn.Server") as server:
            result = runner.invoke(
                app, ["serve-http", "--manifest", str(valid_manifest), "--port", "0"]
            )
        assert result.exit_code == 0, result.output
        assert "internal_error" not in result.stderr
        assert "Beacon HTTP ready" in result.stderr
        server.return_value.run.assert_called_once()

    def test_startup_exception_is_redacted(self, valid_manifest: Path) -> None:
        with mock.patch(
            "beacon.main._serve_http_snapshot", side_effect=RuntimeError("private startup detail")
        ):
            result = runner.invoke(app, ["serve-http", "--manifest", str(valid_manifest)])
        assert result.exit_code == 3
        assert "private startup detail" not in result.stderr


_SERVE_ENV_KEYS = [
    "BEACON_MANIFEST_PATH",
    "BEACON_DOCS_ROOT",
    "BEACON_MAX_MANIFEST_BYTES",
    "BEACON_MAX_DOCUMENTS",
    "BEACON_MAX_DOCUMENT_BYTES",
    "BEACON_MAX_TOTAL_DOCUMENT_BYTES",
    "BEACON_MAX_CHUNKS",
    "BEACON_MAX_SNAPSHOT_BYTES",
    "FASTMCP_CHECK_FOR_UPDATES",
    "FASTMCP_SHOW_SERVER_BANNER",
]


# ---------------------------------------------------------------------------
# beacon init
# ---------------------------------------------------------------------------


class TestInit:
    def test_creates_manifest(self, manifest_dir: Path) -> None:
        result = runner.invoke(app, ["init", str(manifest_dir)])
        assert result.exit_code == 0, result.output
        assert (manifest_dir / "beacon.yaml").is_file()

    def test_refuses_overwrite_without_force(self, valid_manifest: Path) -> None:
        before = valid_manifest.read_text(encoding="utf-8")
        result = runner.invoke(app, ["init", str(valid_manifest.parent)])
        assert result.exit_code == 2
        assert valid_manifest.read_text(encoding="utf-8") == before

    def test_force_replaces(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["init", str(valid_manifest.parent), "--force"])
        assert result.exit_code == 0, result.output
        assert (valid_manifest.parent / "beacon.yaml").is_file()

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Test", encoding="utf-8")
        result = runner.invoke(app, ["init", str(tmp_path), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert not (tmp_path / "beacon.yaml").exists()
        assert "dry_run" in result.output

    def test_no_doc_refuses(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 2

    def test_invalid_root_exits_two(self, valid_manifest: Path) -> None:
        # A non-directory root is an input error (exit 2), not an internal failure.
        result = runner.invoke(app, ["init", str(valid_manifest)])
        assert result.exit_code == 2

    def test_report_collision_with_manifest_exits_two(self, manifest_dir: Path) -> None:
        result = runner.invoke(
            app, ["init", str(manifest_dir), "--report", str(manifest_dir / "beacon.yaml")]
        )
        assert result.exit_code == 2
        assert not (manifest_dir / "beacon.yaml").exists()  # no manifest mutation

    def test_report_existing_target_exits_two(self, manifest_dir: Path, tmp_path: Path) -> None:
        existing = tmp_path / "report.json"
        existing.write_text("old", encoding="utf-8")
        result = runner.invoke(app, ["init", str(manifest_dir), "--report", str(existing)])
        assert result.exit_code == 2
        assert existing.read_text(encoding="utf-8") == "old"
        assert not (manifest_dir / "beacon.yaml").exists()

    def test_report_missing_parent_exits_two(self, manifest_dir: Path) -> None:
        result = runner.invoke(
            app,
            ["init", str(manifest_dir), "--report", str(manifest_dir / "missing" / "report.json")],
        )
        assert result.exit_code == 2
        assert not (manifest_dir / "beacon.yaml").exists()

    def test_json_envelope_wraps_report(self, manifest_dir: Path) -> None:
        result = runner.invoke(app, ["init", str(manifest_dir), "--format", "json"])
        assert result.exit_code == 0, result.output
        payload = _assert_single_json_doc(result.output)
        assert payload["schema"] == "beacon.cli-result"
        assert payload["command"] == "init"
        assert payload["ok"] is True
        assert payload["result"]["operation"] in {"create", "replace"}

    def test_report_persisted_raw(self, manifest_dir: Path, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        result = runner.invoke(app, ["init", str(manifest_dir), "--report", str(report_path)])
        assert result.exit_code == 0, result.output
        assert report_path.is_file()
        raw = json.loads(report_path.read_text(encoding="utf-8"))
        assert raw["beacon_init_report_version"] == "1.0"
        assert "operation" in raw


# ---------------------------------------------------------------------------
# beacon validate
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_exits_zero(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(valid_manifest)])
        assert result.exit_code == 0, result.output
        assert "0 errors" in result.output

    def test_valid_json_envelope(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(valid_manifest), "--format", "json"])
        assert result.exit_code == 0, result.output
        payload = _assert_single_json_doc(result.output)
        assert payload["command"] == "validate"
        assert payload["ok"] is True
        assert payload["result"]["errors"] == 0

    def test_broken_exits_one(self, broken_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(broken_manifest)])
        assert result.exit_code == 1

    def test_broken_json_exits_one(self, broken_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(broken_manifest), "--format", "json"])
        assert result.exit_code == 1
        payload = _assert_single_json_doc(result.output)
        assert payload["ok"] is False
        assert any(d["code"] == "project_name_missing" for d in payload["diagnostics"])

    def test_missing_file_exits_two(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["validate", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 2

    def test_malformed_yaml_exits_two(self, tmp_path: Path) -> None:
        bad = tmp_path / "beacon.yaml"
        bad.write_text(MALFORMED_YAML, encoding="utf-8")
        result = runner.invoke(app, ["validate", str(bad)])
        assert result.exit_code == 2

    def test_warning_exits_zero(self, warning_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(warning_manifest)])
        assert result.exit_code == 0

    def test_strict_warning_exits_one(self, warning_manifest: Path) -> None:
        result = runner.invoke(app, ["validate", str(warning_manifest), "--strict-warnings"])
        assert result.exit_code == 1

    def test_strict_warning_json_ok_false(self, warning_manifest: Path) -> None:
        result = runner.invoke(
            app, ["validate", str(warning_manifest), "--strict-warnings", "--format", "json"]
        )
        assert result.exit_code == 1
        payload = _assert_single_json_doc(result.output)
        assert payload["ok"] is False
        assert payload["result"]["servable"] is True  # servable but not publishable
        assert payload["result"]["publishable"] is False

    def test_strict_acknowledged_exits_zero(self, warning_manifest: Path) -> None:
        result = runner.invoke(
            app,
            [
                "validate",
                str(warning_manifest),
                "--strict-warnings",
                "--format",
                "json",
                "--acknowledge",
                "test_command_missing=Manual smoke tests cover this project.",
                "--acknowledge",
                "guardrails_missing=Guardrails live in the agent handbook.",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = _assert_single_json_doc(result.output)
        assert payload["ok"] is True
        acked = {d["code"] for d in payload["diagnostics"] if d.get("acknowledged")}
        assert acked == {"test_command_missing", "guardrails_missing"}

    def test_bad_ack_exits_two(self, warning_manifest: Path) -> None:
        result = runner.invoke(
            app, ["validate", str(warning_manifest), "--acknowledge", "bogus=short"]
        )
        assert result.exit_code == 2

    def test_unallowlisted_ack_exits_two(self, warning_manifest: Path) -> None:
        result = runner.invoke(
            app,
            [
                "validate",
                str(warning_manifest),
                "--acknowledge",
                "purpose_missing=A purpose is genuinely unknown here.",
            ],
        )
        assert result.exit_code == 2

    def test_default_manifest_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "README.md").write_text("# Test", encoding="utf-8")
        (tmp_path / "beacon.yaml").write_text(VALID_YAML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["validate"])
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# beacon inspect
# ---------------------------------------------------------------------------


class TestInspect:
    def test_valid_exits_zero(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(valid_manifest)])
        assert result.exit_code == 0, result.output

    def test_shows_five_tools(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(valid_manifest)])
        for tool in (
            "beacon_project_overview",
            "beacon_agent_onboarding",
            "beacon_search",
            "beacon_explain_concept",
            "beacon_guardrails",
        ):
            assert tool in result.output

    def test_json_returns_all_five_complete(self, valid_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(valid_manifest), "--format", "json"])
        assert result.exit_code == 0, result.output
        payload = _assert_single_json_doc(result.output)
        assert payload["ok"] is True
        result_payload = payload["result"]
        for key in (
            "beacon_project_overview",
            "beacon_agent_onboarding",
            "beacon_search",
            "beacon_explain_concept",
            "beacon_guardrails",
        ):
            assert key in result_payload
        # Complete dataclass payloads: presence of nested/answer fields, not truncation.
        assert "summary" in result_payload["beacon_project_overview"]
        assert "orientation" in result_payload["beacon_agent_onboarding"]
        assert "answer" in result_payload["beacon_search"]
        assert "definition" in result_payload["beacon_explain_concept"]
        assert "rules" in result_payload["beacon_guardrails"]

    def test_task_hint_passed_to_onboarding_and_guardrails(self, valid_manifest: Path) -> None:
        from beacon.provider.manifest_provider import ManifestBeaconProvider

        original_onboarding = ManifestBeaconProvider.agent_onboarding
        original_guardrails = ManifestBeaconProvider.guardrails
        captured: dict[str, str] = {}

        def onboarding(self, *, task_hint: str = "", risk_tolerance: str = "low"):
            captured["onboarding"] = task_hint
            return original_onboarding(self, task_hint=task_hint, risk_tolerance=risk_tolerance)

        def guardrails(self, *, task_hint: str = ""):
            captured["guardrails"] = task_hint
            return original_guardrails(self, task_hint=task_hint)

        with (
            mock.patch.object(ManifestBeaconProvider, "agent_onboarding", onboarding),
            mock.patch.object(ManifestBeaconProvider, "guardrails", guardrails),
        ):
            result = runner.invoke(
                app, ["inspect", str(valid_manifest), "--task-hint", "add a regression test"]
            )
        assert result.exit_code == 0, result.output
        assert captured["onboarding"] == "add a regression test"
        assert captured["guardrails"] == "add a regression test"

    def test_broken_exits_one(self, broken_manifest: Path) -> None:
        result = runner.invoke(app, ["inspect", str(broken_manifest)])
        assert result.exit_code == 1

    def test_missing_file_exits_two(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["inspect", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# beacon export
# ---------------------------------------------------------------------------


class TestExport:
    def test_writes_snapshot_file(self, valid_manifest: Path, tmp_path: Path) -> None:
        out = tmp_path / "snapshot.json"
        result = runner.invoke(app, ["export", str(valid_manifest), "--output", str(out)])
        assert result.exit_code == 0, result.output
        assert out.is_file()
        snap = json.loads(out.read_text(encoding="utf-8"))
        assert snap["beacon_snapshot_version"] == "1.0"
        assert snap["content_mode"] == "embedded"

    def test_default_output_path(
        self, valid_manifest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(valid_manifest.parent)
        result = runner.invoke(app, ["export", str(valid_manifest)])
        assert result.exit_code == 0, result.output
        assert (valid_manifest.parent / "beacon.snapshot.json").is_file()

    def test_stdout_raw_single_doc(self, valid_manifest: Path, tmp_path: Path) -> None:
        result = runner.invoke(app, ["export", str(valid_manifest), "--output", "-"])
        assert result.exit_code == 0, result.output
        assert result.output.count("\n") == 1
        assert result.output.endswith("\n")
        snap = json.loads(result.output)
        assert snap["beacon_snapshot_version"] == "1.0"
        assert not (tmp_path / "beacon.snapshot.json").exists()

    def test_determinism(self, valid_manifest: Path) -> None:
        first = runner.invoke(app, ["export", str(valid_manifest), "--output", "-"])
        second = runner.invoke(app, ["export", str(valid_manifest), "--output", "-"])
        assert first.output == second.output

    def test_metadata_only(self, valid_manifest: Path) -> None:
        result = runner.invoke(
            app, ["export", str(valid_manifest), "--output", "-", "--metadata-only"]
        )
        assert result.exit_code == 0, result.output
        snap = json.loads(result.output)
        assert snap["content_mode"] == "metadata_only"
        for doc in snap["documents"]:
            for chunk in doc["chunks"]:
                assert "text" not in chunk

    def test_policy_refusal_exits_one(self, warning_manifest: Path) -> None:
        result = runner.invoke(app, ["export", str(warning_manifest), "--output", "-"])
        assert result.exit_code == 1

    def test_security_refusal_exits_one(self, manifest_dir: Path) -> None:
        (manifest_dir / "beacon.yaml").write_text(VALID_YAML, encoding="utf-8")
        (manifest_dir / "README.md").write_text(
            f"# Test\n\ntoken {GITHUB_TOKEN} here.\n", encoding="utf-8"
        )
        result = runner.invoke(app, ["export", str(manifest_dir / "beacon.yaml"), "--output", "-"])
        assert result.exit_code == 1
        assert GITHUB_TOKEN not in result.output

    def test_allow_sensitive_allows(self, manifest_dir: Path, tmp_path: Path) -> None:
        (manifest_dir / "beacon.yaml").write_text(VALID_YAML, encoding="utf-8")
        (manifest_dir / "README.md").write_text(
            f"# Test\n\ntoken {GITHUB_TOKEN} here.\n", encoding="utf-8"
        )
        out = tmp_path / "snapshot.json"
        result = runner.invoke(
            app,
            [
                "export",
                str(manifest_dir / "beacon.yaml"),
                "--output",
                str(out),
                "--allow-sensitive",
                "sensitive_known_token=Fixture token for CLI export tests.",
            ],
        )
        assert result.exit_code == 0, result.output
        snap = json.loads(out.read_text(encoding="utf-8"))
        codes = {o["code"] for o in snap["validation"]["security_overrides"]}
        assert codes == {"sensitive_known_token"}

    def test_bad_override_exits_two(self, valid_manifest: Path) -> None:
        result = runner.invoke(
            app,
            ["export", str(valid_manifest), "--output", "-", "--allow-sensitive", "bogus=short"],
        )
        assert result.exit_code == 2

    def test_missing_manifest_exits_two(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["export", str(tmp_path / "nope.yaml"), "--output", "-"])
        assert result.exit_code == 2

    def test_json_envelope(self, valid_manifest: Path, tmp_path: Path) -> None:
        out = tmp_path / "snapshot.json"
        result = runner.invoke(
            app, ["export", str(valid_manifest), "--output", str(out), "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        payload = _assert_single_json_doc(result.output)
        assert payload["command"] == "export"
        assert payload["ok"] is True
        assert payload["result"]["content_mode"] == "embedded"

    def test_json_reports_artifact_sha_and_bytes(
        self, valid_manifest: Path, tmp_path: Path
    ) -> None:
        import hashlib

        out = tmp_path / "snapshot.json"
        result = runner.invoke(
            app, ["export", str(valid_manifest), "--output", str(out), "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        payload = _assert_single_json_doc(result.output)
        artifact = payload["result"]["artifact_sha256"]
        assert artifact == hashlib.sha256(out.read_bytes()).hexdigest()
        assert payload["result"]["artifact_bytes"] == out.stat().st_size
        assert "output" not in payload["result"]  # no absolute path in JSON

    def test_security_refusal_json_reports_findings(self, manifest_dir: Path) -> None:
        (manifest_dir / "beacon.yaml").write_text(VALID_YAML, encoding="utf-8")
        (manifest_dir / "README.md").write_text(
            f"# Test\n\ntoken {GITHUB_TOKEN} here.\n", encoding="utf-8"
        )
        result = runner.invoke(
            app,
            [
                "export",
                str(manifest_dir / "beacon.yaml"),
                "--output",
                "-",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 1
        payload = _assert_single_json_doc(result.output)
        assert payload["ok"] is False
        codes = [d["code"] for d in payload["diagnostics"]]
        assert "snapshot_blocked_security" in codes
        assert "sensitive_known_token" in codes
        serialized = result.output
        assert GITHUB_TOKEN not in serialized

    def test_no_partial_file_on_refusal(self, manifest_dir: Path, tmp_path: Path) -> None:
        (manifest_dir / "beacon.yaml").write_text(VALID_YAML, encoding="utf-8")
        (manifest_dir / "README.md").write_text(
            f"# Test\n\ntoken {GITHUB_TOKEN} here.\n", encoding="utf-8"
        )
        out = tmp_path / "snapshot.json"
        out.write_text("old-content", encoding="utf-8")
        result = runner.invoke(
            app, ["export", str(manifest_dir / "beacon.yaml"), "--output", str(out)]
        )
        assert result.exit_code == 1
        assert out.read_text(encoding="utf-8") == "old-content"

    def test_low_snapshot_limit_stdout_exits_two_no_partial(self, valid_manifest: Path) -> None:
        result = runner.invoke(
            app, ["export", str(valid_manifest), "--output", "-", "--max-snapshot-bytes", "10"]
        )
        assert result.exit_code == 2
        assert result.stdout == ""

    def test_low_snapshot_limit_file_exits_two_no_partial(
        self, valid_manifest: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "snapshot.json"
        result = runner.invoke(
            app,
            ["export", str(valid_manifest), "--output", str(out), "--max-snapshot-bytes", "10"],
        )
        assert result.exit_code == 2
        assert not out.exists()

    def test_manifest_output_collision_refused(self, valid_manifest: Path) -> None:
        before = valid_manifest.read_text(encoding="utf-8")
        result = runner.invoke(
            app, ["export", str(valid_manifest), "--output", str(valid_manifest)]
        )
        assert result.exit_code == 2
        assert "export_output_collision" in result.stderr
        assert valid_manifest.read_text(encoding="utf-8") == before

    def test_doc_output_collision_refused(self, valid_manifest: Path) -> None:
        doc = valid_manifest.parent / "README.md"
        before = doc.read_text(encoding="utf-8")
        result = runner.invoke(app, ["export", str(valid_manifest), "--output", str(doc)])
        assert result.exit_code == 2
        assert "export_output_collision" in result.stderr
        assert doc.read_text(encoding="utf-8") == before

    @pytest.mark.parametrize("target", ["manifest", "doc"])
    def test_force_never_overrides_source_collision(
        self, valid_manifest: Path, target: str
    ) -> None:
        path = valid_manifest if target == "manifest" else valid_manifest.parent / "README.md"
        before = path.read_bytes()
        result = runner.invoke(
            app, ["export", str(valid_manifest), "--output", str(path), "--force"]
        )
        assert result.exit_code == 2
        assert "export_output_collision" in result.stderr
        assert path.read_bytes() == before

    @pytest.mark.parametrize("name", ["pyproject.toml", "notes.md"])
    def test_existing_unrelated_file_refused_without_force(
        self, valid_manifest: Path, name: str
    ) -> None:
        other = valid_manifest.parent / name
        other.write_bytes(b"[project]\nname = 'keep-me'\n")
        result = runner.invoke(
            app, ["export", str(valid_manifest), "--output", str(other), "--format", "json"]
        )
        assert result.exit_code == 2, result.output
        payload = _assert_single_json_doc(result.output)
        assert [d["code"] for d in payload["diagnostics"]] == ["export_output_exists"]
        assert str(other) not in result.output
        assert other.read_bytes() == b"[project]\nname = 'keep-me'\n"

    def test_force_replaces_existing_unrelated_file(self, valid_manifest: Path) -> None:
        other = valid_manifest.parent / "notes.md"
        other.write_text("scratch", encoding="utf-8")
        result = runner.invoke(
            app, ["export", str(valid_manifest), "--output", str(other), "--force"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(other.read_text(encoding="utf-8"))["beacon_snapshot_version"] == "1.0"

    def test_rerun_replaces_previous_snapshot_without_force(
        self, valid_manifest: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "snapshot.json"
        first = runner.invoke(app, ["export", str(valid_manifest), "--output", str(out)])
        assert first.exit_code == 0, first.output
        second = runner.invoke(
            app, ["export", str(valid_manifest), "--output", str(out), "--metadata-only"]
        )
        assert second.exit_code == 0, second.output
        assert json.loads(out.read_text(encoding="utf-8"))["content_mode"] == "metadata_only"

    def test_existing_directory_refused_without_force(
        self, valid_manifest: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "outdir"
        target.mkdir()
        result = runner.invoke(app, ["export", str(valid_manifest), "--output", str(target)])
        assert result.exit_code == 2
        assert "export_output_exists" in result.stderr
        assert target.is_dir()

    def test_text_security_refusal_reports_location(self, manifest_dir: Path) -> None:
        (manifest_dir / "beacon.yaml").write_text(VALID_YAML, encoding="utf-8")
        (manifest_dir / "README.md").write_text(
            f"# Test\n\ntoken {GITHUB_TOKEN} here.\n", encoding="utf-8"
        )
        result = runner.invoke(app, ["export", str(manifest_dir / "beacon.yaml"), "--output", "-"])
        assert result.exit_code == 1
        assert "README.md" in result.stderr  # safe relative path + line, never the value
        assert GITHUB_TOKEN not in result.stdout
        assert GITHUB_TOKEN not in result.stderr


# ---------------------------------------------------------------------------
# Windows UTF-8
# ---------------------------------------------------------------------------


def test_validate_json_unicode_round_trip(manifest_dir: Path) -> None:
    manifest = VALID_YAML.replace("A test project for CLI tests.", "日本語 café — ✓")
    (manifest_dir / "beacon.yaml").write_text(manifest, encoding="utf-8")
    result = runner.invoke(app, ["validate", str(manifest_dir / "beacon.yaml"), "--format", "json"])
    assert result.exit_code == 0, result.output
    _assert_single_json_doc(result.output)
