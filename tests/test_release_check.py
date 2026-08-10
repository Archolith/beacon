"""Focused tests for the WP5 installed-wheel release-check journey.

These test the *planning and argument-construction* layer of
``scripts/release_check.py`` so the infrastructure is reviewable without
building a wheel, installing the package, or running the (concurrently landing)
CLI. No subprocess that builds or runs Beacon is executed here.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "release_check.py"


@pytest.fixture(scope="module")
def rc() -> Any:
    """Load ``scripts/release_check.py`` as a plain module (not a package)."""
    spec = importlib.util.spec_from_file_location("release_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register so dataclass/typing annotation resolution can find the module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _plan(rc, **kw):
    defaults = {
        "beacon_cmd": ("beacon",),
        "manifest": Path("/repo/beacon.yaml"),
        "repo": Path("/repo"),
        "out_dir": Path("/out"),
        "socket_guard_dir": Path("/guard"),
        "guard_marker": Path("/guard/marker"),
    }
    defaults.update(kw)
    return rc.build_plan(**defaults)


# ---------------------------------------------------------------------------
# Plan shape / ordering
# ---------------------------------------------------------------------------


def test_plan_step_names_and_order(rc) -> None:
    plan = _plan(rc)
    names = [step.name for step in plan.steps]
    assert names == [
        "version",
        "help",
        "init",
        "review_edit",
        "validate_strict",
        "inspect",
        "export_1",
        "export_2",
        "export_compare",
        "export_metadata_only",
        "serve_or_stdio",
        "socket_guard",
    ]
    # The socket-deny marker check must be the final step so it also covers
    # MCP/serve startup and tool calls.
    assert names[-1] == "socket_guard"


def test_every_step_is_described(rc) -> None:
    for step in _plan(rc).steps:
        assert step.name
        assert step.description
        assert (step.argv is None) != (step.func is None)


# ---------------------------------------------------------------------------
# Command argument construction
# ---------------------------------------------------------------------------


def test_version_and_help_commands(rc) -> None:
    plan = _plan(rc, beacon_cmd=("python", "-m", "beacon"))
    version = plan.steps[0]
    assert version.argv == ("python", "-m", "beacon", "--version")
    help_ = plan.steps[1]
    assert help_.argv == ("python", "-m", "beacon", "--help")


def test_init_command_construction(rc) -> None:
    plan = _plan(rc, beacon_cmd=("beacon",), repo=Path("/repo"), out_dir=Path("/out"))
    init = plan.steps[2]
    assert init.argv == (
        "beacon",
        "init",
        "--format",
        "json",
        "--report",
        str(Path("/out") / "init-report.json"),
        str(Path("/repo")),
    )
    assert init.cwd == Path("/repo")


def test_validate_strict_command(rc) -> None:
    plan = _plan(rc, beacon_cmd=("beacon",), manifest=Path("/repo/beacon.yaml"))
    step = plan.steps[4]
    assert step.argv == (
        "beacon",
        "validate",
        "--strict-warnings",
        "--format",
        "json",
        str(Path("/repo/beacon.yaml")),
    )


def test_inspect_command_with_task_hint(rc) -> None:
    plan = _plan(
        rc,
        beacon_cmd=("beacon",),
        manifest=Path("/repo/beacon.yaml"),
        inspect_task_hint="add a parser",
    )
    step = plan.steps[5]
    assert step.argv == (
        "beacon",
        "inspect",
        "--task-hint",
        "add a parser",
        "--format",
        "json",
        str(Path("/repo/beacon.yaml")),
    )


def test_export_commands_output_paths(rc) -> None:
    plan = _plan(
        rc, beacon_cmd=("beacon",), manifest=Path("/repo/beacon.yaml"), out_dir=Path("/out")
    )
    assert plan.steps[6].argv == (
        "beacon",
        "export",
        str(Path("/repo/beacon.yaml")),
        "--output",
        str(Path("/out/export-1.json")),
    )
    assert plan.steps[7].argv == (
        "beacon",
        "export",
        str(Path("/repo/beacon.yaml")),
        "--output",
        str(Path("/out/export-2.json")),
    )
    meta = plan.steps[9]
    assert "--metadata-only" in meta.argv
    assert meta.argv[-1] == str(Path("/out/export-meta.json"))


# ---------------------------------------------------------------------------
# Socket guard
# ---------------------------------------------------------------------------


def test_socket_guard_env_injects_guard(rc) -> None:
    env = rc.socket_guard_env(
        Path("/guard"), Path("/guard/marker"), base_env={"PYTHONPATH": "/existing"}
    )
    assert env["BEACON_SOCKET_GUARD_MARKER"] == str(Path("/guard/marker"))
    parts = env["PYTHONPATH"].split(os.pathsep)
    assert str(Path("/guard")) in parts
    assert "/existing" in parts
    # guard dir must come first so the sitecustomize hook is imported
    assert parts[0] == str(Path("/guard"))


def test_every_runtime_step_runs_under_socket_guard(rc) -> None:
    plan = _plan(rc)
    for step in plan.steps:
        if step.argv is not None:
            assert step.env and step.env.get("BEACON_SOCKET_GUARD_MARKER"), (
                f"{step.name} not guarded"
            )


# ---------------------------------------------------------------------------
# Wheel install steps
# ---------------------------------------------------------------------------


def test_wheel_install_order(rc) -> None:
    cmd, steps = rc._install_steps(Path("/v"), Path("/fw.whl"), Path("/bw.whl"))
    assert cmd[0].endswith(("Scripts" + os.sep + "python.exe", "bin" + os.sep + "python"))
    names = [s.name for s in steps]
    assert names == ["create_venv", "install_framework_wheel", "install_beacon_wheel"]
    assert steps[1].argv[-1] == str(Path("/fw.whl"))  # framework first
    assert steps[2].argv[-1] == str(Path("/bw.whl"))  # beacon second


# ---------------------------------------------------------------------------
# Deterministic review edit (in-process, no build required)
# ---------------------------------------------------------------------------


def test_apply_review_edits_produces_strict_clean_manifest(rc, tmp_path: Path) -> None:
    manifest = tmp_path / "beacon.yaml"
    manifest.write_text(
        'beacon_version: "0.1"\n'
        "project:\n"
        "  name: journey-project\n"
        "  status: unknown\n"
        "  description: generated\n"
        "canonical_docs:\n"
        "  - path: README.md\n"
        "    status: current\n"
        "build_and_test:\n"
        '  test: "python -m pytest"\n',
        encoding="utf-8",
    )
    rc.apply_review_edits(manifest)
    import yaml

    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert data["project"]["status"] == "experimental"
    assert data["purpose"]["one_sentence"] == rc.REVIEW_PURPOSE
    assert data["guardrails"] == rc.REVIEW_GUARDRAILS


# ---------------------------------------------------------------------------
# Dry-run performs no subprocess
# ---------------------------------------------------------------------------


def test_run_plan_dry_run_prints_and_does_not_execute(rc, monkeypatch, capsys) -> None:
    called: list[list[str]] = []

    def fake_run(*_a, **_k):  # pragma: no cover - must never be called
        called.append(["called"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    plan = _plan(rc)
    rc.run_plan(plan, dry_run=True)
    out = capsys.readouterr().out
    for step in plan.steps:
        assert f"[{step.name}]" in out
    assert called == []
    assert "socket-guard" in out


def test_run_plan_dry_run_lists_commands(rc, capsys) -> None:
    rc.run_plan(_plan(rc, beacon_cmd=("beacon",)), dry_run=True)
    out = capsys.readouterr().out
    assert "beacon --version" in out
    assert "beacon init --format json" in out
    assert "beacon export --metadata-only" in out


# ---------------------------------------------------------------------------
# Work-dir lifecycle: --keep preserves the auto temp dir
# ---------------------------------------------------------------------------


def test_keep_uses_mkdtemp_and_preserves_workdir(rc, tmp_path: Path, monkeypatch, capsys) -> None:
    kept = tmp_path / "kept"
    cleaned: list[bool] = []
    monkeypatch.setattr(rc.tempfile, "mkdtemp", lambda *a, **k: str(kept))

    class FakeTemp:  # should never be constructed under --keep
        def __init__(self, *a, **k):  # pragma: no cover
            raise AssertionError("TemporaryDirectory must not be used with --keep")

        def cleanup(self):  # pragma: no cover
            cleaned.append(True)

    monkeypatch.setattr(rc.tempfile, "TemporaryDirectory", FakeTemp)
    rc.main(["--keep", "--dry-run"])
    assert Path(kept).exists()
    assert cleaned == []
    assert "keeping" in capsys.readouterr().err


def test_default_cleans_temp_dir(rc, tmp_path: Path, monkeypatch) -> None:
    kept = tmp_path / "t"
    cleaned: list[bool] = []

    class FakeTemp:
        def __init__(self, *a, **k):
            self.name = str(kept)
            kept.mkdir()

        def cleanup(self):
            cleaned.append(True)

    monkeypatch.setattr(rc.tempfile, "TemporaryDirectory", FakeTemp)
    rc.main(["--dry-run"])
    assert cleaned == [True]


# ---------------------------------------------------------------------------
# In-process step execution (no CLI required)
# ---------------------------------------------------------------------------


def test_run_step_executes_func_step(rc, tmp_path: Path) -> None:
    probe = tmp_path / "probe.txt"

    def action() -> None:
        probe.write_text("done", encoding="utf-8")

    step = rc.Step(name="probe", description="write probe", func=action)
    rc.run_step(step, dry_run=False, printer=lambda _s: None)
    assert probe.read_text(encoding="utf-8") == "done"


def test_compare_exports_detects_difference(rc, tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_bytes(b'{"x": 1}')
    b.write_bytes(b'{"x": 2}')
    with pytest.raises(rc.JourneyError):
        rc.compare_exports(a, b)
    b.write_bytes(a.read_bytes())
    rc.compare_exports(a, b)  # no raise


# ---------------------------------------------------------------------------
# Result checkers
# ---------------------------------------------------------------------------


def _completed(rc, argv, stdout: str, returncode: int = 0):
    completed = subprocess.CompletedProcess(argv, returncode, stdout.encode("utf-8"), b"")
    completed.args = argv  # type: ignore[attr-defined]
    return completed


def test_check_validate_rejects_failure(rc) -> None:
    completed = _completed(
        rc,
        ["beacon", "validate", "--strict-warnings", "--format", "json", "beacon.yaml"],
        json.dumps({"schema": "beacon.cli-result", "ok": False, "command": "validate"}),
        returncode=1,
    )
    with pytest.raises(rc.JourneyError):
        rc._check_validate(completed)


def test_check_inspect_requires_all_five_tools(rc) -> None:
    envelope = {
        "schema": "beacon.cli-result",
        "command": "inspect",
        "ok": True,
        "result": {
            "beacon_project_overview": {},
            "beacon_agent_onboarding": {},
            "beacon_search": {},
            "beacon_explain_concept": {},
            # beacon_guardrails missing deliberately
        },
    }
    completed = _completed(
        rc,
        ["beacon", "inspect", "--task-hint", "t", "--format", "json", "beacon.yaml"],
        json.dumps(envelope),
    )
    with pytest.raises(rc.JourneyError) as info:
        rc._check_inspect(completed)
    assert "beacon_guardrails" in str(info.value)


def test_check_metadata_only_rejects_embedded_text(rc, tmp_path: Path) -> None:
    out = tmp_path / "meta.json"
    out.write_text(
        json.dumps(
            {
                "content_mode": "metadata_only",
                "documents": [
                    {
                        "path": "README.md",
                        "chunks": [{"heading_path": "# x", "line_start": 1, "line_end": 2}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    argv = ["beacon", "export", "--metadata-only", "beacon.yaml", "--output", str(out)]
    completed = _completed(rc, argv, "", returncode=0)
    rc._check_metadata_only(completed)  # no raise

    embedded = tmp_path / "embedded.json"
    embedded.write_text(
        json.dumps(
            {
                "content_mode": "metadata_only",
                "documents": [
                    {
                        "path": "README.md",
                        "chunks": [
                            {
                                "heading_path": "# x",
                                "line_start": 1,
                                "line_end": 2,
                                "text": "secret",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    bad = _completed(
        rc, ["beacon", "export", "--metadata-only", "beacon.yaml", "--output", str(embedded)], ""
    )
    with pytest.raises(rc.JourneyError):
        rc._check_metadata_only(bad)


# ---------------------------------------------------------------------------
# CLI entry point wiring
# ---------------------------------------------------------------------------


def test_wheel_and_exe_modes_are_mutually_exclusive(rc) -> None:
    from argparse import Namespace

    with pytest.raises(rc.JourneyError):
        rc._resolve_beacon_cmd(
            Namespace(framework_wheel="a.whl", beacon_wheel=None, beacon_exe=None)
        )
    cmd, wheels = rc._resolve_beacon_cmd(
        Namespace(framework_wheel="fw.whl", beacon_wheel="bw.whl", beacon_exe=None)
    )
    assert wheels is not None
    assert cmd[1:] == ("-m", "beacon")
    cmd2, wheels2 = rc._resolve_beacon_cmd(
        Namespace(framework_wheel=None, beacon_wheel=None, beacon_exe="/bin/beacon")
    )
    assert cmd2 == ("/bin/beacon",)
    assert wheels2 is None


# ---------------------------------------------------------------------------
# Stdio MCP wiring (installed-artifact enumeration/calls, no fallback)
# ---------------------------------------------------------------------------


def test_python_module_shape_accepts_venv_python(rc) -> None:
    shape = rc._python_module_shape(("/opt/venv/bin/python", "-m", "beacon"))
    assert shape == ("/opt/venv/bin/python", ["-m", "beacon"])


def test_python_module_shape_rejects_console_script(rc) -> None:
    assert rc._python_module_shape(("/usr/local/bin/beacon",)) is None
    assert rc._python_module_shape(("python", "beacon")) is None


def test_serve_stdio_uses_installed_interpreter_for_venv_python(rc, monkeypatch) -> None:
    # A fresh venv Python must drive the real stdio MCP check, not the
    # release-check process interpreter, and must not fall back to serve-start.
    called: list[tuple[str, ...]] = []
    fallback_called: list[bool] = []

    def fake_stdio(cmd, env):  # type: ignore[no-untyped-def]
        called.append(cmd)

    def fake_serve(cmd, env):  # type: ignore[no-untyped-def]
        fallback_called.append(True)

    monkeypatch.setattr(rc, "_stdio_mcp_check", fake_stdio)
    monkeypatch.setattr(rc, "_serve_start_check", fake_serve)
    venv_cmd = ("/opt/venv/bin/python", "-m", "beacon")
    rc.serve_or_stdio(venv_cmd, manifest=Path("/m/beacon.yaml"), env={}, run_stdio_mcp=True)
    assert called == [venv_cmd]
    assert fallback_called == []


def test_serve_stdio_no_stdio_mcp_selects_lighter_check(rc, monkeypatch) -> None:
    called: list[bool] = []

    def fake_stdio(cmd, env):  # type: ignore[no-untyped-def]
        called.append(True)
        raise AssertionError("stdio check must not run")

    def fake_serve(cmd, env):  # type: ignore[no-untyped-def]
        called.append(False)

    monkeypatch.setattr(rc, "_stdio_mcp_check", fake_stdio)
    monkeypatch.setattr(rc, "_serve_start_check", fake_serve)
    rc.serve_or_stdio(("beacon",), manifest=Path("/m/beacon.yaml"), env={}, run_stdio_mcp=False)
    assert called == [False]


def test_stdio_client_failures_are_normalized_without_leaks(rc, monkeypatch) -> None:
    def boom(interpreter, args, env):  # type: ignore[no-untyped-def]
        raise RuntimeError("path=/etc/passwd SECRET=abc")

    monkeypatch.setattr(rc, "_run_stdio_client", boom)
    with pytest.raises(rc.JourneyError) as info:
        rc._run_stdio_client_normalized("/opt/venv/bin/python", ["-m", "beacon"], {})
    message = str(info.value)
    assert "RuntimeError" in message  # concise type only, no value/stack
    assert "/etc/passwd" not in message
    assert "SECRET" not in message


def test_main_returns_one_on_journey_error_without_traceback(rc, monkeypatch, capsys) -> None:
    def boom(**kwargs):  # type: ignore[no-untyped-def]
        raise rc.JourneyError("boom detail")

    monkeypatch.setattr(rc, "build_plan", boom)
    code = rc.main(["--dry-run"])
    err = capsys.readouterr().err
    assert code == 1
    assert "RELEASE CHECK FAILED: boom detail" in err
    assert "Traceback" not in err
