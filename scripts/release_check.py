#!/usr/bin/env python3
"""Cross-platform installed-wheel release-check journey for Beacon v0.2 (WP5).

This script proves the product works from an *installed* distribution rather
than an editable checkout. It is deliberately pure Python (stdlib only, plus a
lazy ``yaml`` import for the review-edit step) so it runs identically on
Windows, macOS, and Linux with no bash-only logic.

Two input modes:

* **Wheel mode (CI):** pass ``--framework-wheel`` and ``--beacon-wheel``. The
  script creates a fresh virtual environment, installs the local framework
  wheel first, then the Beacon wheel, and runs every step against the installed
  ``beacon``. Installation may hit the package index for dependencies; the
  runtime steps afterwards are fully offline.
* **Executable mode:** pass ``--beacon-exe`` (or let it default to the current
  interpreter's ``python -m beacon``) to run the journey against an already
  installed Beacon.

``--dry-run`` prints the exact ordered plan (commands, working directories,
environment, and expected assertions) and performs no subprocess, build, install,
or network action -- it only creates a temporary scratch directory. This makes
the infrastructure reviewable without building.

The journey exercises: version/help; ``init`` of a fresh minimal repository;
the init JSON report; a deterministic explicit review edit into a clean
manifest; strict JSON validation; task-aware JSON inspect covering all five
tools; two embedded exports with identical bytes/SHA256; a metadata-only export
without chunk text; an explicit ``serve``/stdio MCP connection enumerating and
calling exactly five tools; and a socket-deny guard proving no runtime step
attempts outbound network. It uses temporary directories and leaves the checkout
clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The exact five MCP tools Beacon registers.
FIVE_TOOLS = (
    "beacon_project_overview",
    "beacon_agent_onboarding",
    "beacon_search",
    "beacon_explain_concept",
    "beacon_guardrails",
)

#: Default task hint used for task-aware inspect.
DEFAULT_TASK_HINT = "review the release-check journey implementation"

#: Purpose sentence written by the deterministic review edit.
REVIEW_PURPOSE = "A maintainer-authored purpose for the release-check fixture."
#: Guardrail entry written by the deterministic review edit.
REVIEW_GUARDRAILS = [
    {
        "id": "no_documented_assumptions",
        "severity": "high",
        "rule": "Do not introduce undocumented assumptions in this fixture.",
    }
]

_SOCKET_GUARD_SITECUSTOMIZE = """\
import os
import socket
import ipaddress
from pathlib import Path

_original_create_connection = socket.create_connection
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex

def _deny(*args, **kwargs):
    Path(os.environ["BEACON_SOCKET_GUARD_MARKER"]).write_text("blocked", encoding="utf-8")
    raise RuntimeError("outbound network disabled by Beacon release check")

def _is_loopback(address):
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

def _guard_create_connection(address, *args, **kwargs):
    if _is_loopback(address):
        return _original_create_connection(address, *args, **kwargs)
    return _deny(address, *args, **kwargs)

def _guard_connect(sock, address):
    if _is_loopback(address):
        return _original_connect(sock, address)
    return _deny(sock, address)

def _guard_connect_ex(sock, address):
    if _is_loopback(address):
        return _original_connect_ex(sock, address)
    return _deny(sock, address)

socket.create_connection = _guard_create_connection
socket.socket.connect = _guard_connect
socket.socket.connect_ex = _guard_connect_ex
"""


class JourneyError(Exception):
    """Raised when a journey step fails with actionable, non-secret detail."""


@dataclass(frozen=True)
class Step:
    """One journey step: a subprocess or an in-process action plus a checker."""

    name: str
    description: str
    argv: tuple[str, ...] | None = None
    func: Callable[[], None] | None = None
    cwd: Path | None = None
    env: dict[str, str] | None = None
    expect_exit: int = 0
    checker: Callable[[Any], None] | None = None

    def __post_init__(self) -> None:
        if (self.argv is None) == (self.func is None):
            raise ValueError(f"step {self.name!r} must define exactly one of argv/func")


@dataclass
class Plan:
    """The ordered journey plan, with temp roots created by the runner."""

    steps: list[Step] = field(default_factory=list)

    def extend(self, steps: list[Step]) -> None:
        self.steps.extend(steps)


# ---------------------------------------------------------------------------
# Pure planning (no subprocess / no I/O beyond path construction)
# ---------------------------------------------------------------------------


def build_plan(
    *,
    beacon_cmd: tuple[str, ...],
    manifest: Path,
    repo: Path,
    out_dir: Path,
    socket_guard_dir: Path,
    guard_marker: Path,
    inspect_task_hint: str = DEFAULT_TASK_HINT,
    serve_cmd: tuple[str, ...] | None = None,
    run_stdio_mcp: bool = True,
) -> Plan:
    """Build the ordered :class:`Plan` of steps for the release journey.

    Pure and deterministic for a given set of inputs, so it is unit-testable
    without building or executing the CLI.
    """
    plan = Plan()
    guard_env = socket_guard_env(socket_guard_dir, guard_marker)

    plan.extend(
        [
            Step(
                name="version",
                description="print the installed Beacon version",
                argv=beacon_cmd + ("--version",),
                env=guard_env,
            ),
            Step(
                name="help",
                description="print Beacon help and exit successfully",
                argv=beacon_cmd + ("--help",),
                env=guard_env,
            ),
            Step(
                name="init",
                description="initialize a fresh minimal repository with a JSON report",
                argv=beacon_cmd
                + (
                    "init",
                    "--format",
                    "json",
                    "--report",
                    str(out_dir / "init-report.json"),
                    str(repo),
                ),
                cwd=repo,
                env=guard_env,
                checker=_check_init,
            ),
            Step(
                name="review_edit",
                description="apply the explicit review edit to produce a clean manifest",
                func=lambda: apply_review_edits(manifest),
            ),
            Step(
                name="validate_strict",
                description="strict JSON validation succeeds with zero errors",
                argv=beacon_cmd
                + ("validate", "--strict-warnings", "--format", "json", str(manifest)),
                cwd=repo,
                env=guard_env,
                checker=_check_validate,
            ),
            Step(
                name="inspect",
                description="task-aware JSON inspect covering all five tools",
                argv=beacon_cmd
                + ("inspect", "--task-hint", inspect_task_hint, "--format", "json", str(manifest)),
                cwd=repo,
                env=guard_env,
                checker=_check_inspect,
            ),
            Step(
                name="export_1",
                description="first embedded export",
                argv=beacon_cmd
                + ("export", str(manifest), "--output", str(out_dir / "export-1.json")),
                cwd=repo,
                env=guard_env,
            ),
            Step(
                name="export_2",
                description="second embedded export",
                argv=beacon_cmd
                + ("export", str(manifest), "--output", str(out_dir / "export-2.json")),
                cwd=repo,
                env=guard_env,
            ),
            Step(
                name="export_compare",
                description="embedded exports are byte-identical with equal SHA256",
                func=lambda: compare_exports(out_dir / "export-1.json", out_dir / "export-2.json"),
            ),
            Step(
                name="export_metadata_only",
                description="metadata-only export omits chunk text",
                argv=beacon_cmd
                + (
                    "export",
                    "--metadata-only",
                    str(manifest),
                    "--output",
                    str(out_dir / "export-meta.json"),
                ),
                cwd=repo,
                env=guard_env,
                checker=_check_metadata_only,
            ),
            Step(
                name="serve_or_stdio",
                description="explicit serve / real stdio MCP enumerating and calling exactly five tools",
                func=lambda: serve_or_stdio(
                    serve_cmd or beacon_cmd,
                    manifest=manifest,
                    env=guard_env,
                    run_stdio_mcp=run_stdio_mcp,
                ),
            ),
            Step(
                name="socket_guard",
                description="no runtime step (including MCP/serve startup and tool calls) made an outbound network attempt",
                func=lambda: _check_socket_guard(guard_marker),
            ),
        ]
    )
    return plan


def socket_guard_env(
    guard_dir: Path, marker: Path, base_env: dict[str, str] | None = None
) -> dict[str, str]:
    """Return an environment with the socket-deny guard injected on PYTHONPATH."""
    env = dict(os.environ if base_env is None else base_env)
    env["BEACON_SOCKET_GUARD_MARKER"] = str(marker)
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(guard_dir) + (os.pathsep + current if current else "")
    return env


def apply_review_edits(manifest: Path) -> None:
    """Deterministically edit *manifest* into a strict-clean state (no guessing).

    The edits mirror exactly the review items ``init`` reports (unknown status,
    missing purpose, missing guardrails) and are written back with PyYAML so a
    subsequent strict validation passes. This is an explicit, documented review
    edit -- not a heuristic guess.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - yaml is a runtime dependency
        raise JourneyError("PyYAML is required to apply the review edit") from exc
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        raise JourneyError("review edit requires a project mapping in the manifest")
    project["status"] = "experimental"
    data["purpose"] = {"one_sentence": REVIEW_PURPOSE, "problem": "", "non_goals": []}
    data["guardrails"] = REVIEW_GUARDRAILS
    text = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1_000_000,
    )
    manifest.write_text(text.rstrip("\n") + "\n", encoding="utf-8")


def compare_exports(first: Path, second: Path) -> None:
    """Assert two embedded exports are byte-identical with equal SHA256."""
    if not first.is_file() or not second.is_file():
        raise JourneyError("one or both export files are missing")
    a = first.read_bytes()
    b = second.read_bytes()
    if a != b:
        raise JourneyError("two embedded exports of the same manifest are not byte-identical")
    if hashlib.sha256(a).hexdigest() != hashlib.sha256(b).hexdigest():
        raise JourneyError("embedded export SHA256 digests differ")


def serve_or_stdio(
    cmd: tuple[str, ...],
    *,
    manifest: Path,
    env: dict[str, str],
    run_stdio_mcp: bool,
) -> None:
    """Start the explicit serve / stdio server and verify exactly five tools.

    The default installed-wheel journey *requires* the real FastMCP client:
    ``archolith-mcp-framework`` supplies it, so an unavailable MCP stack is a
    packaging failure, never a reason to fall back to a lighter check. Only an
    explicit ``--no-stdio-mcp`` (``run_stdio_mcp=False``) selects the lighter
    serve-start check. *env* carries the socket-deny guard so any outbound
    attempt fails.
    """
    env = dict(env)
    env["BEACON_MANIFEST_PATH"] = str(manifest)
    env["BEACON_DOCS_ROOT"] = str(manifest.parent)
    env.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")
    env.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")

    if run_stdio_mcp:
        _stdio_mcp_check(cmd, env)
    else:
        _serve_start_check(cmd, env)


def _serve_start_check(cmd: tuple[str, ...], env: dict[str, str]) -> None:
    """Spawn ``serve`` and require it to stay up and log a startup line."""
    proc = subprocess.Popen(
        list(cmd) + ["serve"],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        try:
            _, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            return  # stayed up until the timeout -- good
        if b"start" not in stderr.lower() and b"mcp" not in stderr.lower():
            raise JourneyError("beacon serve did not emit an expected startup log")
    finally:
        if proc.poll() is None:
            proc.kill()


def _python_module_shape(cmd: tuple[str, ...]) -> tuple[str, list[str]] | None:
    """Return ``(interpreter, args)`` when *cmd* is a ``python -m beacon`` shape.

    Any interpreter path is accepted (including a fresh venv Python), but only
    when the command is exactly ``(<python>, "-m", "beacon", ...)``.
    """
    if len(cmd) >= 3 and cmd[1] == "-m" and cmd[2] == "beacon":
        return cmd[0], list(cmd[1:])
    return None


def _stdio_mcp_check(cmd: tuple[str, ...], env: dict[str, str]) -> None:
    """Connect over real stdio and enumerate/call exactly the five tools.

    This is the required installed-artifact check: it runs the *installed*
    interpreter named by *cmd* (a fresh venv Python in wheel mode), never the
    release-check process interpreter. An unavailable MCP client stack or a
    non-``python -m beacon`` command is a packaging failure and raises
    :class:`JourneyError` -- there is no lighter fallback here. Client/protocol
    runtime failures are normalized to a concise, non-secret
    :class:`JourneyError` so a real stdio failure surfaces as an actionable
    result instead of a full traceback.
    """
    try:
        import fastmcp  # noqa: F401
    except ImportError as exc:
        raise JourneyError(
            "the archolith-mcp-framework MCP client is not importable; the "
            "installed-wheel journey requires the real FastMCP stack"
        ) from exc

    shape = _python_module_shape(cmd)
    if shape is None:
        raise JourneyError("serve command must be '<python> -m beacon' to drive stdio MCP")
    interpreter, args = shape
    _run_stdio_client_normalized(interpreter, args, env)


def _run_stdio_client_normalized(interpreter: str, args: list[str], env: dict[str, str]) -> None:
    """Run the stdio MCP client, normalizing broad runtime failures."""
    try:
        _run_stdio_client(interpreter, args, env)
    except JourneyError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize client/protocol failures
        raise JourneyError(
            f"stdio MCP connection or tool call failed ({type(exc).__name__})"
        ) from exc


def _run_stdio_client(interpreter: str, args: list[str], env: dict[str, str]) -> None:
    """Connect and enumerate/call the five tools over real stdio."""
    import asyncio

    import fastmcp
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(command=interpreter, args=args, env=env)

    async def _run() -> None:
        async with fastmcp.Client(transport, timeout=20) as client:
            names = sorted(tool.name for tool in await client.list_tools())
            if tuple(names) != tuple(sorted(FIVE_TOOLS)):
                raise JourneyError(f"expected exactly the five tools, got: {', '.join(names)}")
            calls = {
                "beacon_project_overview": {},
                "beacon_agent_onboarding": {"task_hint": DEFAULT_TASK_HINT},
                "beacon_search": {"query": "manifest"},
                "beacon_explain_concept": {"concept": "beacon_manifest"},
                "beacon_guardrails": {"task_hint": DEFAULT_TASK_HINT},
            }
            for name, arguments in calls.items():
                result = await client.call_tool(name, arguments)
                if result.is_error:
                    raise JourneyError(f"tool call failed: {name}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Result checkers
# ---------------------------------------------------------------------------


def _check_init(completed: Any) -> None:
    _assert_exit(completed, 0, "init")
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JourneyError("init did not emit a JSON result") from exc
    envelope = _require_envelope(payload, "init")
    if envelope["command"] != "init":
        raise JourneyError(f"init envelope command={envelope['command']!r} != 'init'")
    if envelope["ok"] is not True:
        raise JourneyError("init envelope ok is not true")
    report = envelope["result"]
    if not isinstance(report, dict):
        raise JourneyError("init result is not an object")
    if report.get("written") is not True:
        raise JourneyError(f"init did not write the manifest: written={report.get('written')!r}")
    if not report.get("manifest_path"):
        raise JourneyError("init report is missing manifest_path")


def _check_validate(completed: Any) -> None:
    _assert_exit(completed, 0, "validate --strict-warnings")
    payload = json.loads(completed.stdout.decode("utf-8"))
    _require_envelope(payload, "validate")
    if payload.get("ok") is not True:
        raise JourneyError("strict validation envelope ok is not true")


def _check_inspect(completed: Any) -> None:
    _assert_exit(completed, 0, "inspect")
    payload = json.loads(completed.stdout.decode("utf-8"))
    envelope = _require_envelope(payload, "inspect")
    result = envelope["result"]
    if not isinstance(result, dict):
        raise JourneyError("inspect result is not an object")
    missing = [name for name in FIVE_TOOLS if name not in result]
    if missing:
        raise JourneyError(f"inspect result is missing tool payloads: {', '.join(missing)}")


def _check_metadata_only(completed: Any) -> None:
    _assert_exit(completed, 0, "export --metadata-only")
    output = _output_path_from_args(completed)
    if not output.is_file():
        raise JourneyError("metadata-only export did not produce an output file")
    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("content_mode") != "metadata_only":
        raise JourneyError(
            f"export content_mode={payload.get('content_mode')!r} != 'metadata_only'"
        )
    for doc in payload.get("documents", []):
        for chunk in doc.get("chunks", []):
            if "text" in chunk:
                raise JourneyError("metadata-only export unexpectedly contains chunk text")


def _output_path_from_args(completed: Any) -> Path:
    argv = getattr(completed, "args", None) or ()
    for index, item in enumerate(argv):
        if item == "--output" and index + 1 < len(argv):
            return Path(argv[index + 1])
    raise JourneyError("could not determine the --output path from the export invocation")


def _check_socket_guard(marker: Path) -> None:
    if marker.exists():
        raise JourneyError("a runtime step attempted outbound network access")


def _require_envelope(payload: Any, command: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise JourneyError(f"{command} JSON output is not an object")
    if payload.get("schema") != "beacon.cli-result":
        raise JourneyError(f"{command} JSON output is not a beacon.cli-result envelope")
    return payload


def _assert_exit(completed: Any, expected: int, what: str) -> None:
    code = getattr(completed, "returncode", None)
    if code != expected:
        stderr = getattr(completed, "stderr", b"") or b""
        tail = stderr.decode("utf-8", errors="replace").strip().splitlines()[-1:] or []
        detail = tail[0] if tail else "no stderr"
        raise JourneyError(f"{what} exited {code!r}, expected {expected}: {detail}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_step(step: Step, *, dry_run: bool, printer: Callable[[str], None]) -> None:
    """Execute (or print, in dry-run) one :class:`Step`."""
    printer(f"[{step.name}] {step.description}")
    if dry_run:
        if step.argv:
            printer(f"    run: {' '.join(step.argv)}")
        if step.cwd:
            printer(f"    cwd: {step.cwd}")
        if step.env and step.env.get("BEACON_SOCKET_GUARD_MARKER"):
            printer(f"    env: socket-guard active -> {step.env['BEACON_SOCKET_GUARD_MARKER']}")
        if step.checker is not None:
            printer("    assert: output/artifact check")
        return
    if step.func is not None:
        step.func()
        return
    completed = subprocess.run(
        list(step.argv or ()),
        cwd=str(step.cwd) if step.cwd else None,
        env=step.env,
        capture_output=True,
    )
    if step.checker is not None:
        step.checker(completed)
    else:
        _assert_exit(completed, step.expect_exit, step.name)


def run_plan(plan: Plan, *, dry_run: bool = False) -> None:
    """Run (or print) every step, failing fast with actionable detail."""
    for step in plan.steps:
        try:
            run_step(step, dry_run=dry_run, printer=print)
        except JourneyError as exc:
            raise JourneyError(f"journey step {step.name!r} failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="release_check",
        description="Cross-platform installed-wheel release-check journey for Beacon.",
    )
    parser.add_argument("--beacon-exe", help="installed beacon console script path")
    parser.add_argument("--framework-wheel", help="local archolith-mcp-framework wheel")
    parser.add_argument("--beacon-wheel", help="local archolith-beacon wheel")
    parser.add_argument("--workdir", help="temporary work root (default: system temp)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary work root")
    parser.add_argument("--no-stdio-mcp", action="store_true", help="only light serve-start check")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the ordered plan with no subprocess/build/install/network "
        "(a temporary scratch directory is still created)",
    )
    return parser.parse_args(argv)


def _resolve_beacon_cmd(
    args: argparse.Namespace,
) -> tuple[tuple[str, ...], tuple[Path, Path] | None]:
    """Return (beacon_cmd, wheels) honouring wheel vs executable mode."""
    wheels = None
    if args.framework_wheel and args.beacon_wheel:
        wheels = (Path(args.framework_wheel), Path(args.beacon_wheel))
        return (sys.executable, "-m", "beacon"), wheels
    if args.framework_wheel or args.beacon_wheel:
        raise JourneyError("--framework-wheel and --beacon-wheel must be provided together")
    if args.beacon_exe:
        return (args.beacon_exe,), wheels
    return (sys.executable, "-m", "beacon"), wheels


def _install_steps(
    venv_dir: Path, framework_wheel: Path, beacon_wheel: Path
) -> tuple[tuple[str, ...], list[Step]]:
    """Create a venv and install framework then Beacon wheels."""
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    steps: list[Step] = [
        Step(
            name="create_venv",
            description="create a fresh virtual environment",
            argv=(sys.executable, "-m", "venv", str(venv_dir)),
        ),
        Step(
            name="install_framework_wheel",
            description="install the local framework wheel (first)",
            argv=(str(venv_python), "-m", "pip", "install", str(framework_wheel)),
        ),
        Step(
            name="install_beacon_wheel",
            description="install the local Beacon wheel",
            argv=(str(venv_python), "-m", "pip", "install", str(beacon_wheel)),
        ),
    ]
    return (str(venv_python), "-m", "beacon"), steps


def _setup_guard(work: Path, *, write_sitecustomize: bool) -> tuple[Path, Path, dict[str, str]]:
    guard_dir = work / "socket-guard"
    guard_dir.mkdir(parents=True, exist_ok=True)
    if write_sitecustomize:
        (guard_dir / "sitecustomize.py").write_text(_SOCKET_GUARD_SITECUSTOMIZE, encoding="utf-8")
    marker = work / "network-attempted"
    return guard_dir, marker, socket_guard_env(guard_dir, marker)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    beacon_cmd, wheels = _resolve_beacon_cmd(args)
    dry_run = args.dry_run

    if args.workdir:
        work = Path(args.workdir)
        work.mkdir(parents=True, exist_ok=True)
        closer = None
    elif args.keep:
        work = Path(tempfile.mkdtemp(prefix="beacon-release-check-"))
        print(f"[release-check] keeping work dir: {work}", file=sys.stderr)
        closer = None
    else:
        temp = tempfile.TemporaryDirectory(prefix="beacon-release-check-")
        work = Path(temp.name)
        closer = temp

    try:
        repo = work / "journey-project"
        repo.mkdir(parents=True, exist_ok=True)
        if not dry_run:
            (repo / "README.md").write_text(
                "# journey-project\n\nFresh minimal repository.\n", encoding="utf-8"
            )
            (repo / "pyproject.toml").write_text(
                '[project]\nname = "journey-project"\n\n[tool.pytest.ini_options]\n',
                encoding="utf-8",
            )
        manifest = repo / "beacon.yaml"
        out_dir = work / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        guard_dir, guard_marker, _ = _setup_guard(work, write_sitecustomize=not dry_run)

        steps: list[Step] = []
        if wheels is not None:
            venv_dir = work / "venv"
            beacon_cmd, wheel_steps = _install_steps(venv_dir, wheels[0], wheels[1])
            steps.extend(wheel_steps)

        plan = build_plan(
            beacon_cmd=beacon_cmd,
            manifest=manifest,
            repo=repo,
            out_dir=out_dir,
            socket_guard_dir=guard_dir,
            guard_marker=guard_marker,
            inspect_task_hint=DEFAULT_TASK_HINT,
            serve_cmd=beacon_cmd,
            run_stdio_mcp=not args.no_stdio_mcp,
        )
        plan.steps = steps + plan.steps
        run_plan(plan, dry_run=dry_run)
        return 0
    except JourneyError as exc:
        print(f"RELEASE CHECK FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if closer is not None:
            closer.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
