"""Beacon CLI entry point.

Subcommands
-----------
  beacon                    Start the MCP stdio server (default when no subcommand).
  beacon serve              Start the stdio server with explicit manifest/docs-root/limits.
  beacon serve-http         Serve one immutable canonical snapshot over loopback HTTP.
  beacon init ROOT          Initialize a starter beacon.yaml.
  beacon validate [PATH]    Validate a beacon.yaml and exit 0 on success, 1 on errors.
  beacon inspect [PATH]     Inspect all five tool outputs for a beacon.yaml.
  beacon export [PATH]      Write the canonical static snapshot.

Exit classes (addendum §5): 0 success, 1 validation/policy/security refusal,
2 user/input/safety/parse/limit/refused-overwrite, 3 unexpected internal failure.
In JSON mode, expected outcomes emit exactly one ``beacon.cli-result`` v1.0
envelope plus a single newline and no human prose. Diagnostics before an
envelope are written only to stderr. The default (no-argument) invocation and
the explicit ``serve`` command run the MCP stdio server, so they never put an
envelope or prose on stdout.
"""

from __future__ import annotations

import hashlib
import logging
import os
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from beacon.core import cli_result, cli_support, scaffold
from beacon.core import snapshot as snapshot_mod
from beacon.core.discovery import DiscoveryError
from beacon.core.limits import FIELD_ENV_VARS, LimitError, ResourceLimits
from beacon.core.loader import ManifestError
from beacon.core.paths import UnsafeCanonicalPath, resolve_canonical_path
from beacon.core.scaffold import OPERATION_REFUSED, InitReport
from beacon.core.schema import to_payload as schema_payload
from beacon.core.security import SecurityOverrideError, parse_security_overrides
from beacon.core.status import StatusObservation, observe_project_status

EXIT_OK = cli_support.EXIT_OK
EXIT_VALIDATION = cli_support.EXIT_VALIDATION
EXIT_INPUT = cli_support.EXIT_INPUT
EXIT_INTERNAL = cli_support.EXIT_INTERNAL

app = typer.Typer(
    name="beacon",
    no_args_is_help=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------


def _version_callback(*, value: bool) -> None:
    """Print the Beacon version and exit without starting the MCP server."""
    if not value:
        return
    from beacon import __version__

    typer.echo(f"beacon {__version__}")
    raise typer.Exit()


# ---------------------------------------------------------------------------
# Runtime configuration shared by the stdio server paths
# ---------------------------------------------------------------------------


def _configure_logging(*, include_console: bool = False) -> None:
    level = os.environ.get("BEACON_LOG_LEVEL", "WARNING").upper()
    handlers: list[logging.Handler] = []
    if include_console:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        handlers=handlers or None,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _configure_utf8_stdio() -> None:
    """Reconfigure stdout and stderr to UTF-8 on Windows."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - defensive
                pass


def _prepare_runtime() -> None:
    """Load dotenv and force FastMCP privacy *before* the framework is imported."""
    from dotenv import load_dotenv

    load_dotenv(os.getenv("ENV_FILE") or None)
    # Never check for updates on a programmatic runner, never print the banner.
    os.environ["FASTMCP_CHECK_FOR_UPDATES"] = "off"
    os.environ["FASTMCP_SHOW_SERVER_BANNER"] = "false"
    _configure_utf8_stdio()
    _configure_logging(include_console=False)


def _run_mcp_server() -> None:
    from archolith_mcp_framework import run_server

    from beacon.mcp.server import mcp

    print(
        f"[beacon] MCP stdio starting (pid={os.getpid()})",
        file=sys.stderr,
        flush=True,
    )
    run_server(mcp)


def _set_serve_env(context: cli_support.CommandContext) -> None:
    """Point the lifecycle-driven server at the validated manifest/docs-root/limits."""
    os.environ["BEACON_MANIFEST_PATH"] = str(context.manifest_path)
    os.environ["BEACON_DOCS_ROOT"] = str(context.docs_root)
    for field, var in FIELD_ENV_VARS.items():
        os.environ[var] = str(context.limits.ceiling(field))


#: Environment variables the explicit ``serve`` path mutates (restored after run).
_SERVE_MUTATED_ENV = (
    ("BEACON_MANIFEST_PATH", "BEACON_DOCS_ROOT")
    + tuple(FIELD_ENV_VARS.values())
    + ("FASTMCP_CHECK_FOR_UPDATES", "FASTMCP_SHOW_SERVER_BANNER")
)


def _serve_with_env(context: cli_support.CommandContext) -> None:
    """Run the stdio server with *context* env overrides, restoring prior values.

    The manifest/docs-root/limit (and privacy) overrides are scoped to the
    server run so embedding callers and CliRunner never retain them afterward.
    Prior values are restored exactly, including variables that were absent.
    """
    saved = {var: os.environ.get(var) for var in _SERVE_MUTATED_ENV}
    try:
        _set_serve_env(context)
        _prepare_runtime()
        _run_mcp_server()
    finally:
        for var, prior in saved.items():
            if prior is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prior


# ---------------------------------------------------------------------------
# Default: start the MCP stdio server (no-argument, environment-driven)
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the Beacon version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
) -> None:
    """Start the Beacon MCP stdio server (default when no subcommand is given)."""
    if ctx.invoked_subcommand is not None:
        return
    _prepare_runtime()
    _run_mcp_server()


# ---------------------------------------------------------------------------
# beacon serve
# ---------------------------------------------------------------------------


@app.command("serve")
def serve(
    manifest: str | None = typer.Option(
        None, "--manifest", "-m", help="Path to beacon.yaml (default: ./beacon.yaml)."
    ),
    docs_root: str | None = typer.Option(None, "--docs-root", help="Docs root directory."),
    max_manifest_bytes: int | None = typer.Option(None, "--max-manifest-bytes"),
    max_documents: int | None = typer.Option(None, "--max-documents"),
    max_document_bytes: int | None = typer.Option(None, "--max-document-bytes"),
    max_total_document_bytes: int | None = typer.Option(None, "--max-total-document-bytes"),
    max_chunks: int | None = typer.Option(None, "--max-chunks"),
    max_snapshot_bytes: int | None = typer.Option(None, "--max-snapshot-bytes"),
) -> None:
    """Validate servability, then run the same stdio server with the given inputs."""
    try:
        context = cli_support.build_command_context(
            cli_limits=_cli_limit_mapping(
                max_manifest_bytes,
                max_documents,
                max_document_bytes,
                max_total_document_bytes,
                max_chunks,
                max_snapshot_bytes,
            ),
            manifest_path=manifest,
            docs_root=docs_root,
        )
    except cli_support.CliFailure as exc:
        typer.echo(f"✗ {exc.code}: {exc.message}", err=True)
        raise typer.Exit(exc.exit_code) from exc
    except Exception as exc:  # noqa: BLE001 - normalized safely for the CLI
        fail = cli_support.normalize_internal(exc)
        typer.echo(f"✗ {fail.code}: {fail.message}", err=True)
        raise typer.Exit(fail.exit_code) from exc

    # Surface the full validation diagnostics to stderr (stdout stays MCP-only).
    for diag in cli_support.report_to_diagnostics(context.report, context.acknowledgements):
        symbol = "✗" if diag.severity == "error" else "⚠"
        label = f"{symbol} {diag.code}: {diag.message}"
        if diag.acknowledged:
            label += f"  (acknowledged: {diag.acknowledgement_reason})"
        typer.echo(label, err=True)

    if not context.report.ok:
        raise typer.Exit(EXIT_VALIDATION)

    # Attach the provider from the already-loaded context (one read), then serve.
    # Any provider/limit/startup failure is normalized to a stable exit code with
    # env overrides restored by ``_serve_with_env``'s finally block.
    try:
        cli_support.build_provider(context)
        _serve_with_env(context)
    except cli_support.CliFailure as exc:
        typer.echo(f"✗ {exc.code}: {exc.message}", err=True)
        raise typer.Exit(exc.exit_code) from exc
    except Exception as exc:  # noqa: BLE001 - normalized safely for the CLI
        fail = cli_support.normalize_internal(exc)
        typer.echo(f"✗ {fail.code}: {fail.message}", err=True)
        raise typer.Exit(fail.exit_code) from exc


# ---------------------------------------------------------------------------
# beacon serve-http
# ---------------------------------------------------------------------------


@app.command("serve-http")
def serve_http(
    manifest: str | None = typer.Option(
        None, "--manifest", "-m", help="Path to beacon.yaml (default: ./beacon.yaml)."
    ),
    docs_root: str | None = typer.Option(None, "--docs-root", help="Docs root directory."),
    host: str = typer.Option("127.0.0.1", "--host", help="Loopback bind address."),
    port: int = typer.Option(8765, "--port", help="Loopback port; 0 selects an available port."),
    acknowledge: list[str] = typer.Option([], "--acknowledge"),
    allow_sensitive: list[str] = typer.Option([], "--allow-sensitive"),
    max_manifest_bytes: int | None = typer.Option(None, "--max-manifest-bytes"),
    max_documents: int | None = typer.Option(None, "--max-documents"),
    max_document_bytes: int | None = typer.Option(None, "--max-document-bytes"),
    max_total_document_bytes: int | None = typer.Option(None, "--max-total-document-bytes"),
    max_chunks: int | None = typer.Option(None, "--max-chunks"),
    max_snapshot_bytes: int | None = typer.Option(None, "--max-snapshot-bytes"),
) -> None:
    """Serve an immutable canonical snapshot over loopback HTTP."""
    _safe(
        "serve-http",
        "text",
        lambda: _serve_http_impl(
            manifest,
            docs_root,
            host=host,
            port=port,
            acknowledges=acknowledge,
            allow_sensitive=allow_sensitive,
            cli_limits=_six_limit_args(
                max_manifest_bytes,
                max_documents,
                max_document_bytes,
                max_total_document_bytes,
                max_chunks,
                max_snapshot_bytes,
            ),
        ),
    )


def _serve_http_impl(
    manifest: str | None,
    docs_root: str | None,
    *,
    host: str,
    port: int,
    acknowledges: list[str],
    allow_sensitive: list[str],
    cli_limits: dict[str, Any],
) -> int:
    if host != "127.0.0.1":
        raise cli_support.CliFailure(
            EXIT_INPUT,
            "http_host_not_loopback",
            "HTTP server host must be 127.0.0.1",
        )
    if port < 0 or port > 65535:
        raise cli_support.CliFailure(
            EXIT_INPUT,
            "http_port_invalid",
            "HTTP server port must be between 0 and 65535",
        )

    context = cli_support.build_command_context(
        cli_limits=cli_limits,
        manifest_path=manifest,
        docs_root=docs_root,
        acknowledgements=acknowledges,
    )
    try:
        overrides = parse_security_overrides(allow_sensitive)
    except SecurityOverrideError as exc:
        raise cli_support.CliFailure(EXIT_INPUT, exc.code, "invalid security override") from exc

    try:
        snap = snapshot_mod.build_snapshot(
            context.manifest_path,
            docs_root=context.docs_root,
            content_mode=snapshot_mod.CONTENT_EMBEDDED,
            acknowledgements=context.acknowledgements,
            security_overrides=overrides,
            limits=context.limits,
        )
    except snapshot_mod.SnapshotError as exc:
        return _emit_snapshot_refusal("serve-http", exc, "text")
    except LimitError as exc:
        raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc
    except ManifestError as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, cli_support.CODE_MANIFEST_INVALID, "malformed or invalid manifest"
        ) from exc
    except UnsafeCanonicalPath as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, "unsafe_canonical_path", "unsafe canonical path"
        ) from exc

    status_observation = observe_project_status(
        snap,
        manifest_path=context.manifest_path,
        docs_root=context.docs_root,
        limits=context.limits,
    )
    _serve_http_snapshot(
        snap,
        host=host,
        port=port,
        status_observation=status_observation,
    )
    return EXIT_OK


def _serve_http_snapshot(
    snap: snapshot_mod.Snapshot,
    *,
    host: str,
    port: int,
    status_observation: StatusObservation,
) -> None:
    """Bind one loopback socket and run the immutable ASGI snapshot application."""
    import uvicorn

    from beacon import __version__
    from beacon.http_api import create_http_app

    app_http = create_http_app(snap, status_observation=status_observation)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind((host, port))
        listener.listen(2048)
    except OSError as exc:
        listener.close()
        raise cli_support.CliFailure(
            EXIT_INPUT, "http_bind_failed", "could not bind loopback HTTP server"
        ) from exc

    actual_port = int(listener.getsockname()[1])
    snapshot_sha = str(app_http.state.beacon_snapshot_sha256)
    typer.echo(
        f"Beacon HTTP ready url=http://{host}:{actual_port} beacon={__version__} "
        f"snapshot_schema={snap.beacon_snapshot_version} snapshot_sha256={snapshot_sha}",
        err=True,
    )
    config = uvicorn.Config(
        app_http,
        host=host,
        port=actual_port,
        access_log=False,
        server_header=False,
        date_header=False,
        log_level="warning",
    )
    try:
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        listener.close()


# ---------------------------------------------------------------------------
# Shared emit / dispatch helpers
# ---------------------------------------------------------------------------


def _json(
    command: str,
    *,
    ok: bool,
    result_payload: dict[str, Any] | None = None,
    diagnostics: tuple[cli_result.Diagnostic, ...] = (),
) -> None:
    typer.echo(
        cli_result.dumps(
            cli_result.result(
                command, ok=ok, result_payload=result_payload, diagnostics=diagnostics
            )
        ),
        nl=False,
    )


def _emit_failure(command: str, fmt: str, diag: cli_result.Diagnostic) -> None:
    if fmt == "json":
        _json(command, ok=False, diagnostics=(diag,))
    else:
        typer.echo(f"✗ {diag.code}: {diag.message}", err=True)


def _safe(command: str, fmt: str, fn: Callable[[], int]) -> None:
    """Run *fn*, emit a failure envelope/prose on CliFailure, and exit by code."""
    try:
        code = fn()
    except cli_support.CliFailure as exc:
        _emit_failure(command, fmt, exc.to_diagnostic())
        code = exc.exit_code
    except Exception as exc:  # noqa: BLE001 - normalized safely for the CLI
        fail = cli_support.normalize_internal(exc)
        _emit_failure(command, fmt, fail.to_diagnostic())
        code = fail.exit_code
    raise typer.Exit(code)


def _require_format(fmt: str) -> None:
    if fmt not in ("text", "json"):
        typer.echo("✗ invalid format: expected text|json", err=True)
        raise typer.Exit(EXIT_INPUT)


def _cli_limit_mapping(
    manifest_bytes: int | None,
    documents: int | None,
    document_bytes: int | None,
    total_document_bytes: int | None,
    chunks: int | None,
    snapshot_bytes: int | None,
) -> dict[str, Any]:
    """Collect the six overridable CLI limit options (None values are dropped)."""
    return {
        "manifest_bytes": manifest_bytes,
        "documents": documents,
        "document_bytes": document_bytes,
        "total_document_bytes": total_document_bytes,
        "chunks": chunks,
        "snapshot_bytes": snapshot_bytes,
    }


def _six_limit_args(
    max_manifest_bytes: int | None,
    max_documents: int | None,
    max_document_bytes: int | None,
    max_total_document_bytes: int | None,
    max_chunks: int | None,
    max_snapshot_bytes: int | None,
) -> dict[str, Any]:
    return _cli_limit_mapping(
        max_manifest_bytes,
        max_documents,
        max_document_bytes,
        max_total_document_bytes,
        max_chunks,
        max_snapshot_bytes,
    )


def _limit_ok_payload(limits: ResourceLimits) -> dict[str, int]:
    return cli_support.effective_limits_mapping(limits)


# ---------------------------------------------------------------------------
# beacon init ROOT
# ---------------------------------------------------------------------------


@app.command()
def init(
    root: Path = typer.Argument(Path("."), help="Repository root (default: current directory)."),
    output: str = typer.Option(
        "beacon.yaml", "--output", help="Output manifest path (repo-relative)."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Discover and report without writing."),
    force: bool = typer.Option(
        False, "--force", help="Replace an existing recognizable beacon.yaml."
    ),
    format: str = typer.Option("text", "--format", help="Output format: text|json."),
    report: str | None = typer.Option(
        None, "--report", help="Optional path to persist the raw init report."
    ),
    max_manifest_bytes: int | None = typer.Option(None, "--max-manifest-bytes"),
    max_documents: int | None = typer.Option(None, "--max-documents"),
    max_document_bytes: int | None = typer.Option(None, "--max-document-bytes"),
    max_total_document_bytes: int | None = typer.Option(None, "--max-total-document-bytes"),
    max_chunks: int | None = typer.Option(None, "--max-chunks"),
    max_snapshot_bytes: int | None = typer.Option(None, "--max-snapshot-bytes"),
) -> None:
    """Initialize a starter beacon.yaml in ROOT (exit 2 on any refusal)."""
    _require_format(format)
    _safe(
        "init",
        format,
        lambda: _init_impl(
            root,
            output,
            dry_run=dry_run,
            force=force,
            fmt=format,
            report_path=report,
            cli_limits=_six_limit_args(
                max_manifest_bytes,
                max_documents,
                max_document_bytes,
                max_total_document_bytes,
                max_chunks,
                max_snapshot_bytes,
            ),
        ),
    )


def _init_impl(
    root: Path,
    output: str,
    *,
    dry_run: bool,
    force: bool,
    fmt: str,
    report_path: str | None,
    cli_limits: dict[str, Any],
) -> int:
    try:
        limits = cli_support.build_resource_limits(cli_limits)
    except LimitError as exc:
        raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc

    # Preflight --report *before* any manifest write: no report overwrite, no
    # collision with the manifest output, and an existing safe parent directory.
    if report_path is not None:
        try:
            manifest_target = scaffold.resolve_output_path(root, output)
        except UnsafeCanonicalPath as exc:
            raise cli_support.CliFailure(
                EXIT_INPUT, "unsafe_canonical_path", "unsafe output path"
            ) from exc
        except LimitError as exc:
            raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc
        _preflight_report(report_path, manifest_target)

    try:
        report = scaffold.init(
            root, dry_run=dry_run, force=force, manifest_path=output, limits=limits
        )
    except DiscoveryError as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, "init_invalid_root", "repository root is not usable"
        ) from exc
    except LimitError as exc:
        raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc
    except UnsafeCanonicalPath as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, "unsafe_canonical_path", "unsafe output path"
        ) from exc
    except OSError as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, "init_write_failed", "could not write manifest"
        ) from exc

    if report_path is not None:
        try:
            scaffold.write_report(report, report_path, limits=limits)
        except LimitError as exc:
            raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc
        except OSError as exc:
            raise cli_support.CliFailure(
                EXIT_INPUT, "init_report_write_failed", "could not write report"
            ) from exc

    ok = report.operation != OPERATION_REFUSED
    exit_code = EXIT_OK if ok else EXIT_INPUT
    if fmt == "json":
        _json("init", ok=ok, result_payload=scaffold.to_payload(report))
    else:
        _text_init(report)
    return exit_code


def _preflight_report(report_path: str, manifest_target: Path) -> None:
    """Preflight ``--report`` before any manifest write.

    Refuses an existing report target (no report-overwrite flag), a report that
    collides with the resolved manifest output, or a missing parent directory.
    All are stable exit-2 :class:`CliFailure` cases with no source mutation.
    """
    report = Path(report_path)
    if not report.parent.is_dir():
        raise cli_support.CliFailure(
            EXIT_INPUT, "init_report_missing_parent", "report parent directory does not exist"
        )
    try:
        if report.resolve() == manifest_target.resolve():
            raise cli_support.CliFailure(
                EXIT_INPUT, "init_report_collision", "report path collides with manifest output"
            )
    except (OSError, RuntimeError) as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, "init_report_invalid", "invalid report path"
        ) from exc
    if report.exists():
        raise cli_support.CliFailure(
            EXIT_INPUT, "init_report_exists", "report target already exists"
        )


def _text_init(report: InitReport) -> None:
    typer.echo(f"Init operation: {report.operation}")
    typer.echo(f"Manifest path: {report.manifest_path}")
    typer.echo(
        f"Would write: {report.would_write}  Written: {report.written}  Replaced: {report.replaced}"
    )
    for item in report.review_required:
        typer.echo(f"  ⚠ {item.code}: {item.reason}")


# ---------------------------------------------------------------------------
# beacon validate [PATH]
# ---------------------------------------------------------------------------


@app.command()
def validate(
    manifest: Path | None = typer.Argument(
        None, help="Path to beacon.yaml (default: ./beacon.yaml)."
    ),
    docs_root: str | None = typer.Option(None, "--docs-root"),
    format: str = typer.Option("text", "--format"),
    strict_warnings: bool = typer.Option(False, "--strict-warnings"),
    acknowledge: list[str] = typer.Option(
        [], "--acknowledge", help="Acknowledge a CODE=REASON warning."
    ),
    max_manifest_bytes: int | None = typer.Option(None, "--max-manifest-bytes"),
    max_documents: int | None = typer.Option(None, "--max-documents"),
    max_document_bytes: int | None = typer.Option(None, "--max-document-bytes"),
    max_total_document_bytes: int | None = typer.Option(None, "--max-total-document-bytes"),
    max_chunks: int | None = typer.Option(None, "--max-chunks"),
    max_snapshot_bytes: int | None = typer.Option(None, "--max-snapshot-bytes"),
) -> None:
    """Validate a beacon.yaml and exit 0 on success, 1 on errors/strict warnings."""
    _require_format(format)
    _safe(
        "validate",
        format,
        lambda: _validate_impl(
            manifest,
            docs_root,
            fmt=format,
            strict_warnings=strict_warnings,
            acknowledges=acknowledge,
            cli_limits=_six_limit_args(
                max_manifest_bytes,
                max_documents,
                max_document_bytes,
                max_total_document_bytes,
                max_chunks,
                max_snapshot_bytes,
            ),
        ),
    )


def _validate_impl(
    manifest: Path | None,
    docs_root: str | None,
    *,
    fmt: str,
    strict_warnings: bool,
    acknowledges: list[str],
    cli_limits: dict[str, Any],
) -> int:
    context = cli_support.build_command_context(
        cli_limits=cli_limits,
        manifest_path=manifest,
        docs_root=docs_root,
        acknowledgements=acknowledges,
    )
    diagnostics = cli_support.report_to_diagnostics(context.report, context.acknowledgements)
    servable = context.report.ok
    publishable = context.policy.publishable
    ok = servable and not (strict_warnings and not publishable)
    exit_code = EXIT_OK if ok else EXIT_VALIDATION
    payload = {
        "servable": servable,
        "publishable": publishable,
        "errors": len(context.report.errors),
        "warnings": len(context.report.warnings),
        "acknowledged": len(context.policy.acknowledged),
        "limits": _limit_ok_payload(context.limits),
    }
    if fmt == "json":
        _json("validate", ok=ok, result_payload=payload, diagnostics=diagnostics)
    else:
        _text_validate(
            diagnostics, servable=servable, publishable=publishable, strict_warnings=strict_warnings
        )
    return exit_code


def _text_validate(
    diagnostics: tuple[cli_result.Diagnostic, ...],
    *,
    servable: bool,
    publishable: bool,
    strict_warnings: bool,
) -> None:
    errors = [d for d in diagnostics if d.severity == "error"]
    warnings = [d for d in diagnostics if d.severity == "warning"]
    if servable:
        typer.echo(f"✓ Valid — 0 errors, {len(warnings)} warning(s)")
    else:
        typer.echo(f"✗ {len(errors)} error(s), {len(warnings)} warning(s)")
    for diag in [*errors, *warnings]:
        symbol = "✗" if diag.severity == "error" else "⚠"
        label = f"  {symbol} {diag.path}: {diag.message}"
        if diag.acknowledged:
            label += f"  (acknowledged: {diag.acknowledgement_reason})"
        typer.echo(label)
    if strict_warnings and not publishable:
        typer.echo("✗ strict-warnings: unresolved publication warnings present")


# ---------------------------------------------------------------------------
# beacon inspect [PATH]
# ---------------------------------------------------------------------------


@app.command()
def inspect(
    manifest: Path | None = typer.Argument(
        None, help="Path to beacon.yaml (default: ./beacon.yaml)."
    ),
    docs_root: str | None = typer.Option(None, "--docs-root"),
    format: str = typer.Option("text", "--format"),
    task_hint: str = typer.Option(
        "", "--task-hint", help="Task hint passed to onboarding and guardrails."
    ),
    acknowledge: list[str] = typer.Option([], "--acknowledge"),
    max_manifest_bytes: int | None = typer.Option(None, "--max-manifest-bytes"),
    max_documents: int | None = typer.Option(None, "--max-documents"),
    max_document_bytes: int | None = typer.Option(None, "--max-document-bytes"),
    max_total_document_bytes: int | None = typer.Option(None, "--max-total-document-bytes"),
    max_chunks: int | None = typer.Option(None, "--max-chunks"),
    max_snapshot_bytes: int | None = typer.Option(None, "--max-snapshot-bytes"),
) -> None:
    """Inspect all five tool outputs for a beacon.yaml (exit 1 on validation errors)."""
    _require_format(format)
    _safe(
        "inspect",
        format,
        lambda: _inspect_impl(
            manifest,
            docs_root,
            fmt=format,
            task_hint=task_hint,
            acknowledges=acknowledge,
            cli_limits=_six_limit_args(
                max_manifest_bytes,
                max_documents,
                max_document_bytes,
                max_total_document_bytes,
                max_chunks,
                max_snapshot_bytes,
            ),
        ),
    )


def _inspect_impl(
    manifest: Path | None,
    docs_root: str | None,
    *,
    fmt: str,
    task_hint: str,
    acknowledges: list[str],
    cli_limits: dict[str, Any],
) -> int:
    context = cli_support.build_command_context(
        cli_limits=cli_limits,
        manifest_path=manifest,
        docs_root=docs_root,
        acknowledgements=acknowledges,
    )
    diagnostics = cli_support.report_to_diagnostics(context.report, context.acknowledgements)
    if not context.report.ok:
        if fmt == "json":
            _json("inspect", ok=False, diagnostics=diagnostics)
        else:
            for diag in diagnostics:
                symbol = "✗" if diag.severity == "error" else "⚠"
                typer.echo(f"  {symbol} {diag.path}: {diag.message}")
        return EXIT_VALIDATION

    provider = cli_support.build_provider(context)

    ov = provider.project_overview()
    ob = provider.agent_onboarding(task_hint=task_hint)
    query = context.manifest.core_concepts[0].id if context.manifest.core_concepts else "overview"
    sr = provider.search(query=query)
    first = context.manifest.core_concepts[0].id if context.manifest.core_concepts else "overview"
    ce = provider.explain_concept(concept=first)
    gr = provider.guardrails(task_hint=task_hint)

    if fmt == "json":
        payload = {
            "beacon_project_overview": schema_payload(ov),
            "beacon_agent_onboarding": schema_payload(ob),
            "beacon_search": schema_payload(sr),
            "beacon_explain_concept": schema_payload(ce),
            "beacon_guardrails": schema_payload(gr),
        }
        _json("inspect", ok=True, result_payload=payload, diagnostics=diagnostics)
    else:
        _text_inspect(context, provider, task_hint, ov, ob, sr, ce, gr)
    return EXIT_OK


def _text_inspect(
    context: cli_support.CommandContext,
    provider: Any,
    task_hint: str,
    ov: Any,
    ob: Any,
    sr: Any,
    ce: Any,
    gr: Any,
) -> None:
    p = context.manifest.project
    typer.echo(f"Project:   {p.name} ({p.status})")
    typer.echo(
        f"Manifest:  beacon_version={context.manifest.beacon_version}"
        f"  concepts={len(context.manifest.core_concepts)}"
        f"  docs={len(context.manifest.canonical_docs)}"
        f"  guardrails={len(context.manifest.guardrails)}"
    )
    if task_hint:
        typer.echo(f"Task hint: {task_hint}\n")
    typer.echo("")

    _hr()
    _section("beacon_project_overview")
    _field("summary", _trunc(ov.summary, 100))
    _field("status", f"{ov.status}  confidence: {ov.confidence}")
    _field("components", str(len(ov.core_components)))

    _hr()
    _section("beacon_agent_onboarding")
    _field("orientation", _trunc(ob.orientation, 100))
    _field("docs", _join(ob.relevant_docs[:3]))
    _field("concepts", _join(ob.concepts_to_understand[:4]))
    _field("commands", f"{len(ob.commands)} command(s)")
    _field("status", f"{ob.status}  confidence: {ob.confidence}")

    _hr()
    query = context.manifest.core_concepts[0].id if context.manifest.core_concepts else "overview"
    _section(f"beacon_search  (query: {query!r})")
    _field("answer", sr.answer)
    _field("hits", str(len(sr.results)))

    _hr()
    _section(f"beacon_explain_concept  (concept: {ce.concept!r})")
    _field("definition", _trunc(ce.definition, 100))
    _field("status", f"{ce.status}  confidence: {ce.confidence}")

    _hr()
    _section("beacon_guardrails")
    _field("rules", f"{len(gr.rules)} total")
    _field("status", f"{gr.status}  confidence: {gr.confidence}")
    _hr()

    for diag in cli_support.report_to_diagnostics(context.report, context.acknowledgements):
        if diag.severity == "warning":
            typer.echo(f"  ⚠ {diag.code}: {diag.message}")
    typer.echo("\n✓  Inspect complete. 5 tools responded.")


# ---------------------------------------------------------------------------
# beacon export [PATH]
# ---------------------------------------------------------------------------


@app.command()
def export(
    manifest: Path | None = typer.Argument(
        None, help="Path to beacon.yaml (default: ./beacon.yaml)."
    ),
    output: str = typer.Option(
        "beacon.snapshot.json", "--output", help="Output path, or '-' for stdout."
    ),
    docs_root: str | None = typer.Option(None, "--docs-root"),
    format: str = typer.Option("text", "--format"),
    metadata_only: bool = typer.Option(False, "--metadata-only"),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Replace an existing --output file that is not a previous Beacon snapshot. "
            "Never allows overwriting the manifest or a canonical document."
        ),
    ),
    acknowledge: list[str] = typer.Option([], "--acknowledge"),
    allow_sensitive: list[str] = typer.Option([], "--allow-sensitive"),
    max_manifest_bytes: int | None = typer.Option(None, "--max-manifest-bytes"),
    max_documents: int | None = typer.Option(None, "--max-documents"),
    max_document_bytes: int | None = typer.Option(None, "--max-document-bytes"),
    max_total_document_bytes: int | None = typer.Option(None, "--max-total-document-bytes"),
    max_chunks: int | None = typer.Option(None, "--max-chunks"),
    max_snapshot_bytes: int | None = typer.Option(None, "--max-snapshot-bytes"),
) -> None:
    """Write the canonical static snapshot (exit 1 on policy/security refusal)."""
    _require_format(format)
    _safe(
        "export",
        format,
        lambda: _export_impl(
            manifest,
            output,
            docs_root,
            fmt=format,
            metadata_only=metadata_only,
            force=force,
            acknowledges=acknowledge,
            allow_sensitive=allow_sensitive,
            cli_limits=_six_limit_args(
                max_manifest_bytes,
                max_documents,
                max_document_bytes,
                max_total_document_bytes,
                max_chunks,
                max_snapshot_bytes,
            ),
        ),
    )


def _export_impl(
    manifest: Path | None,
    output: str,
    docs_root: str | None,
    *,
    fmt: str,
    metadata_only: bool,
    force: bool = False,
    acknowledges: list[str],
    allow_sensitive: list[str],
    cli_limits: dict[str, Any],
) -> int:
    context = cli_support.build_command_context(
        cli_limits=cli_limits,
        manifest_path=manifest,
        docs_root=docs_root,
        acknowledgements=acknowledges,
    )
    try:
        overrides = parse_security_overrides(allow_sensitive)
    except SecurityOverrideError as exc:
        raise cli_support.CliFailure(EXIT_INPUT, exc.code, "invalid security override") from exc

    content_mode = (
        snapshot_mod.CONTENT_METADATA_ONLY if metadata_only else snapshot_mod.CONTENT_EMBEDDED
    )
    try:
        snap = snapshot_mod.build_snapshot(
            context.manifest_path,
            docs_root=context.docs_root,
            content_mode=content_mode,
            acknowledgements=context.acknowledgements,
            security_overrides=overrides,
            limits=context.limits,
        )
    except snapshot_mod.SnapshotError as exc:
        return _emit_snapshot_refusal("export", exc, fmt)
    except LimitError as exc:
        raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc
    except ManifestError as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, cli_support.CODE_MANIFEST_INVALID, "malformed or invalid manifest"
        ) from exc
    except UnsafeCanonicalPath as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, "unsafe_canonical_path", "unsafe canonical path"
        ) from exc

    if output == "-":
        # Raw canonical snapshot to stdout: exactly one document + newline, no write.
        try:
            snapshot_bytes_out = snapshot_mod.snapshot_bytes(snap)
        except LimitError as exc:
            raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            buffer.write(snapshot_bytes_out)
            buffer.flush()
        else:  # pragma: no cover - defensive when stdout has no byte buffer
            sys.stdout.write(snapshot_bytes_out.decode("utf-8"))
            sys.stdout.flush()
        return EXIT_OK

    # Preserve the read-only invariant: never turn a source file into snapshot JSON.
    out_path = Path(output)
    _preflight_export_output(out_path, context, force=force)

    # Exact canonical bytes for the artifact digest/byte count and the file write.
    try:
        snapshot_bytes_out = snapshot_mod.snapshot_bytes(snap)
    except LimitError as exc:
        raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc
    artifact_sha = hashlib.sha256(snapshot_bytes_out).hexdigest()
    artifact_bytes = len(snapshot_bytes_out)
    try:
        snapshot_mod.write_snapshot_atomic(out_path, snap, byte_ceiling=snap.byte_ceiling)
    except LimitError as exc:
        raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc
    except OSError as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, "export_write_failed", "could not write snapshot"
        ) from exc

    diagnostics = cli_support.report_to_diagnostics(context.report, context.acknowledgements)
    if fmt == "json":
        result_payload = {
            "content_mode": snap.content_mode,
            "documents": len(snap.documents),
            "chunks": sum(len(d.chunks) for d in snap.documents),
            "artifact_sha256": artifact_sha,
            "artifact_bytes": artifact_bytes,
            "acknowledgements": len(snap.validation.acknowledgements),
            "security_overrides": len(snap.validation.security_overrides),
            "limits": _limit_ok_payload(context.limits),
        }
        _json("export", ok=True, result_payload=result_payload, diagnostics=diagnostics)
    else:
        _text_export(out_path, snap, artifact_sha=artifact_sha, artifact_bytes=artifact_bytes)
    return EXIT_OK


def _preflight_export_output(
    out_path: Path, context: cli_support.CommandContext, *, force: bool = False
) -> None:
    """Refuse an export output that would overwrite the manifest, a canonical doc,
    or any other existing file.

    Preserves the v0.2 read-only invariant: a new artifact or the replacement of
    a previous Beacon snapshot remains allowed, but export never turns
    ``beacon.yaml`` or a selected canonical document into snapshot JSON (not even
    with ``--force``), and never replaces any other existing path unless
    ``--force`` is given. Raises a stable exit-2 :class:`CliFailure` before any
    write.
    """
    try:
        out_resolved = out_path.resolve()
    except (OSError, RuntimeError) as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, "export_output_invalid", "invalid output path"
        ) from exc
    if out_resolved == context.manifest_path.resolve():
        raise cli_support.CliFailure(
            EXIT_INPUT, "export_output_collision", "output collides with the manifest"
        )
    for doc in context.manifest.canonical_docs:
        try:
            doc_target = resolve_canonical_path(context.docs_root, doc.path)
        except UnsafeCanonicalPath:
            continue  # build_snapshot already validated; not a real write target
        if out_resolved == doc_target.resolve():
            raise cli_support.CliFailure(
                EXIT_INPUT,
                "export_output_collision",
                "output collides with a canonical document",
            )
    if not force and _existing_non_snapshot(out_path):
        raise cli_support.CliFailure(
            EXIT_INPUT,
            "export_output_exists",
            "output path already exists and is not a Beacon snapshot (use --force to replace)",
        )


#: Canonical snapshot JSON sorts keys, so every snapshot starts with this prefix.
_SNAPSHOT_PREFIX = b'{"beacon_snapshot_version":"'


def _existing_non_snapshot(out_path: Path) -> bool:
    """Return True when *out_path* exists and is not a regular Beacon snapshot file.

    Symlinks and directories always count as non-snapshots. Only a bounded prefix
    of an existing regular file is read.
    """
    if out_path.is_symlink():
        return True
    if not out_path.exists():
        return False
    if not out_path.is_file():
        return True
    try:
        with out_path.open("rb") as handle:
            head = handle.read(len(_SNAPSHOT_PREFIX))
    except OSError:
        return True
    return head != _SNAPSHOT_PREFIX


def _emit_snapshot_refusal(command: str, exc: snapshot_mod.SnapshotError, fmt: str) -> int:
    """Emit a snapshot refusal with safe metadata-only findings; return exit code.

    Policy/security refusals are exit 1; other snapshot errors (unsafe path,
    source changed, invalid mode) are exit 2. Findings carry only stable
    ``sensitive_*`` codes plus relative path/line -- never matched values.
    """
    exit_code = (
        EXIT_VALIDATION
        if exc.code
        in (snapshot_mod.SNAPSHOT_BLOCKED_POLICY, snapshot_mod.SNAPSHOT_BLOCKED_SECURITY)
        else EXIT_INPUT
    )
    diagnostics: list[cli_result.Diagnostic] = [cli_result.diagnostic("error", exc.code, str(exc))]
    for finding in exc.findings:
        kwargs: dict[str, Any] = {}
        if finding.path:
            kwargs["path"] = finding.path
        if finding.line is not None:
            kwargs["line"] = finding.line
        diagnostics.append(
            cli_result.diagnostic(
                "error", finding.code, "high-confidence sensitive content", **kwargs
            )
        )
    if fmt == "json":
        _json(command, ok=False, diagnostics=tuple(diagnostics))
    else:
        for diag in diagnostics:
            location = ""
            if diag.path:
                location = f" ({diag.path}"
                if diag.line is not None:
                    location += f":{diag.line}"
                location += ")"
            typer.echo(f"✗ {diag.code}: {diag.message}{location}", err=True)
    return exit_code


def _text_export(
    out_path: Path, snap: snapshot_mod.Snapshot, *, artifact_sha: str, artifact_bytes: int
) -> None:
    total_chunks = sum(len(d.chunks) for d in snap.documents)
    typer.echo(f"✓ Exported beacon snapshot to {out_path}")
    typer.echo(
        f"  content_mode={snap.content_mode} documents={len(snap.documents)} "
        f"chunks={total_chunks} bytes={artifact_bytes} sha={artifact_sha}"
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _hr() -> None:
    typer.echo("─" * 55)


def _section(name: str) -> None:
    typer.echo(name)


def _field(label: str, value: str) -> None:
    typer.echo(f"  {label:<14} {value}")


def _trunc(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s[:n] + "…" if len(s) > n else s


def _join(items: tuple[str, ...] | list[str]) -> str:
    return ", ".join(items) if items else "(none)"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    # Ensure UTF-8 output on Windows (cp1252 can't encode the status symbols).
    _configure_utf8_stdio()
    app()


if __name__ == "__main__":
    main()
