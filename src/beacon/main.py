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
import json
import logging
import os
import socket
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from beacon.core import cli_result, cli_support, scaffold
from beacon.core import snapshot as snapshot_mod
from beacon.core.discovery import DiscoveryError
from beacon.core.limits import (
    FIELD_ENV_VARS,
    LIMIT_SNAPSHOT_BYTES,
    LimitError,
    ResourceLimits,
    read_bytes_bounded,
)
from beacon.core.loader import ManifestError
from beacon.core.paths import UnsafeCanonicalPath, resolve_canonical_path
from beacon.core.scaffold import OPERATION_REFUSED, InitReport
from beacon.core.schema import to_payload as schema_payload
from beacon.core.security import SecurityOverrideError, parse_security_overrides
from beacon.core.status import StatusObservation, observe_project_status
from beacon.sources.git import GitSourceAdapter, GitSourceError, GitSourceUnavailable

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
    ("BEACON_MANIFEST_PATH", "BEACON_DOCS_ROOT", "BEACON_SNAPSHOT_PATH")
    + tuple(FIELD_ENV_VARS.values())
    + ("FASTMCP_CHECK_FOR_UPDATES", "FASTMCP_SHOW_SERVER_BANNER")
)


def _serve_with_env(
    context: cli_support.CommandContext | None, *, snapshot_path: str | None = None
) -> None:
    """Run the stdio server with *context* env overrides, restoring prior values.

    The manifest/docs-root/limit (and privacy) overrides are scoped to the
    server run so embedding callers and CliRunner never retain them afterward.
    Prior values are restored exactly, including variables that were absent.
    When *snapshot_path* is given the server runs snapshot-only: the manifest
    and document chunks come from the canonical snapshot and no source file
    is read at startup.
    """
    saved = {var: os.environ.get(var) for var in _SERVE_MUTATED_ENV}
    try:
        if context is not None:
            _set_serve_env(context)
        if snapshot_path:
            os.environ["BEACON_SNAPSHOT_PATH"] = snapshot_path
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
    snapshot: str | None = typer.Option(
        None, "--snapshot", help="Serve from a canonical snapshot instead of a manifest."
    ),
    max_manifest_bytes: int | None = typer.Option(None, "--max-manifest-bytes"),
    max_documents: int | None = typer.Option(None, "--max-documents"),
    max_document_bytes: int | None = typer.Option(None, "--max-document-bytes"),
    max_total_document_bytes: int | None = typer.Option(None, "--max-total-document-bytes"),
    max_chunks: int | None = typer.Option(None, "--max-chunks"),
    max_snapshot_bytes: int | None = typer.Option(None, "--max-snapshot-bytes"),
) -> None:
    """Validate servability, then run the same stdio server with the given inputs."""
    cli_limits = _cli_limit_mapping(
        max_manifest_bytes,
        max_documents,
        max_document_bytes,
        max_total_document_bytes,
        max_chunks,
        max_snapshot_bytes,
    )

    if snapshot is not None:
        # Snapshot-only serving: load and verify, then let the lifespan build
        # the provider from the snapshot (no manifest read, no doc file reads).
        try:
            limits = cli_support.build_resource_limits(cli_limits)
        except LimitError as exc:
            typer.echo(f"✗ {exc.code}: {exc}", err=True)
            raise typer.Exit(EXIT_INPUT) from exc
        from beacon.build.snapshot import SnapshotReadError, load_snapshot
        from beacon.provider.manifest_provider import ManifestBeaconProvider

        try:
            loaded = load_snapshot(snapshot, limits=limits)
            ManifestBeaconProvider.from_snapshot(loaded, limits=limits)
        except SnapshotReadError as exc:
            typer.echo(f"✗ {exc.code}: {exc}", err=True)
            raise typer.Exit(EXIT_INPUT) from exc
        except Exception as exc:  # noqa: BLE001 - normalized safely for the CLI
            fail = cli_support.normalize_internal(exc)
            typer.echo(f"✗ {fail.code}: {fail.message}", err=True)
            raise typer.Exit(fail.exit_code) from exc
        try:
            _serve_with_env(None, snapshot_path=snapshot)
        except cli_support.CliFailure as exc:
            typer.echo(f"✗ {exc.code}: {exc.message}", err=True)
            raise typer.Exit(exc.exit_code) from exc
        except Exception as exc:  # noqa: BLE001 - normalized safely for the CLI
            fail = cli_support.normalize_internal(exc)
            typer.echo(f"✗ {fail.code}: {fail.message}", err=True)
            raise typer.Exit(fail.exit_code) from exc
        return

    try:
        context = cli_support.build_command_context(
            cli_limits=cli_limits,
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
    if report.git_evidence is not None:
        head = report.git_evidence.get("head")
        if isinstance(head, dict):
            branch = head.get("branch") or "detached"
            commit = str(head.get("commit"))[:12]
            dirty = "dirty" if head.get("dirty") else "clean"
            typer.echo(f"Git: {branch} @ {commit} ({dirty})")
    for item in report.review_required:
        typer.echo(f"  ⚠ {item.code}: {item.reason}")


# ---------------------------------------------------------------------------
# beacon build
# ---------------------------------------------------------------------------


@app.command("build")
def build(
    intent: str | None = typer.Option(
        None, "--intent", help="Hand-authored manifest merged as the intent authority."
    ),
    repo: str | None = typer.Option(
        None, "--repo", help="Repository root for the git reality adapter."
    ),
    menhir_evidence: str | None = typer.Option(
        None, "--menhir-evidence", help="Menhir evidence document (JSON) for the history tier."
    ),
    out: str = typer.Option(
        "beacon.generated.yaml", "--out", help="Output manifest path (relative to --docs-root)."
    ),
    snapshot_out: str | None = typer.Option(
        None, "--snapshot-out", help="Also write the canonical static snapshot to this path."
    ),
    docs_root: str | None = typer.Option(
        None, "--docs-root", help="Docs root for canonical docs (default: output directory)."
    ),
    note: str | None = typer.Option(
        None, "--note", help="Fixed provenance comment prepended to the generated manifest."
    ),
    force: bool = typer.Option(False, "--force", help="Replace an existing regular output file."),
    format: str = typer.Option("text", "--format", help="Output format: text|json."),
    max_manifest_bytes: int | None = typer.Option(None, "--max-manifest-bytes"),
    max_documents: int | None = typer.Option(None, "--max-documents"),
    max_document_bytes: int | None = typer.Option(None, "--max-document-bytes"),
    max_total_document_bytes: int | None = typer.Option(None, "--max-total-document-bytes"),
    max_chunks: int | None = typer.Option(None, "--max-chunks"),
    max_snapshot_bytes: int | None = typer.Option(None, "--max-snapshot-bytes"),
) -> None:
    """Build a manifest/snapshot from merged sources (exit 1/2 on refusal)."""
    _require_format(format)
    _safe(
        "build",
        format,
        lambda: _build_impl(
            intent=intent,
            repo=repo,
            menhir_evidence=menhir_evidence,
            out=out,
            snapshot_out=snapshot_out,
            docs_root=docs_root,
            note=note,
            force=force,
            fmt=format,
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


def _build_impl(
    *,
    intent: str | None,
    repo: str | None,
    menhir_evidence: str | None,
    out: str,
    snapshot_out: str | None,
    docs_root: str | None,
    note: str | None,
    force: bool,
    fmt: str,
    cli_limits: dict[str, Any],
) -> int:
    from beacon.build.policy import BuildError, resolve_project_facts
    from beacon.build.project import (
        build_raw_manifest,
        manifest_bytes_sha256,
        render_manifest_yaml,
    )
    from beacon.core.loader import parse_manifest
    from beacon.core.validator import ManifestValidationError, require_valid_manifest
    from beacon.sources.menhir import MenhirEvidenceError, MenhirSourceAdapter

    try:
        limits = cli_support.build_resource_limits(cli_limits)
    except LimitError as exc:
        raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc

    if intent is None and menhir_evidence is None and repo is None:
        raise cli_support.CliFailure(
            EXIT_INPUT, "build_no_sources", "build requires --intent, --menhir-evidence, or --repo"
        )

    # -- resolve the output location and docs root ---------------------------
    # `--out -` streams the manifest YAML to stdout (no envelope, no file):
    # the same convention as `beacon export --output -`, for embedding
    # generators that own publication. A relative --out otherwise resolves
    # against the repository root when one is given (the generated manifest
    # belongs to that repo), otherwise the CWD.
    to_stdout = out == "-"
    if to_stdout and snapshot_out:
        raise cli_support.CliFailure(
            EXIT_INPUT,
            "build_stdout_snapshot_unsupported",
            "snapshot output requires a file --out",
        )
    base_dir = Path(repo) if repo else Path.cwd()
    root_dir = Path(docs_root) if docs_root else base_dir
    # The build's own inputs are never output targets, not even with --force.
    protected_inputs = tuple(Path(path) for path in (menhir_evidence, intent) if path)
    target: Path | None = None
    snapshot_path: Path | None = None
    if not to_stdout:
        try:
            target = scaffold.resolve_output_path(root_dir, out)
        except UnsafeCanonicalPath as exc:
            raise cli_support.CliFailure(
                EXIT_INPUT, "unsafe_canonical_path", "unsafe output path"
            ) from exc
        except LimitError as exc:
            raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc
        _preflight_build_manifest_target(
            target, force=force, limits=limits, protected=protected_inputs
        )
        if snapshot_out:
            # The snapshot output resolves next to the manifest and must stay
            # inside the same root --out is confined to (--repo, or
            # --docs-root when given).
            snapshot_path = _resolve_build_snapshot_path(snapshot_out, target, root_dir)
            # A snapshot target that is a build input or the manifest is refused
            # here; the exists/--force rule runs after projection so that a
            # collision with a canonical document is reported as such.
            _preflight_build_snapshot_target(
                snapshot_path,
                target,
                force=True,
                limits=limits,
                protected=protected_inputs,
                check_existing=False,
            )
    docs_home = target.parent if target is not None else root_dir

    # -- collect the source tiers ---------------------------------------------
    menhir_records: tuple[Any, ...] = ()
    if menhir_evidence:
        adapter = MenhirSourceAdapter(menhir_evidence, limits=limits)
        try:
            menhir_records = adapter.collect()
        except MenhirEvidenceError as exc:
            raise cli_support.CliFailure(EXIT_INPUT, "menhir_evidence_invalid", str(exc)) from exc

    git_records: tuple[Any, ...] = ()
    git_origin: str | None = None
    if repo:
        git_adapter = GitSourceAdapter(repo)
        try:
            git_records = git_adapter.collect()
        except GitSourceUnavailable:
            # Tier 1 is optional by design: no git repository means the
            # repository tier is absent and the build degrades to the
            # remaining sources (build-pipeline plan §3).
            git_records = ()
        except GitSourceError as exc:
            raise cli_support.CliFailure(
                EXIT_INPUT, "build_git_failed", "a bounded git query failed"
            ) from exc
        if git_records:
            url, _url_findings = git_adapter.repository_url()
            git_origin = url

    intent_manifest = None
    if intent:
        from beacon.core.loader import load_beacon_manifest

        try:
            intent_manifest = load_beacon_manifest(Path(intent), limits=limits)
        except ManifestError as exc:
            raise cli_support.CliFailure(
                EXIT_INPUT, "intent_manifest_invalid", "malformed or invalid intent manifest"
            ) from exc

    try:
        facts = resolve_project_facts(
            intent=intent_manifest,
            git_records=git_records,
            menhir_records=menhir_records,
            docs_root=docs_home,
            repo_root=Path(repo) if repo else None,
            git_origin=git_origin,
        )
        raw = build_raw_manifest(facts)
        manifest_obj = parse_manifest(raw)
        require_valid_manifest(manifest_obj, docs_root=docs_home)
    except BuildError as exc:
        raise cli_support.CliFailure(EXIT_VALIDATION, exc.code, str(exc)) from exc
    except ManifestValidationError as exc:
        raise cli_support.CliFailure(
            EXIT_VALIDATION, "build_projection_invalid", "projected manifest is invalid"
        ) from exc

    data = render_manifest_yaml(raw, note=note)

    if target is None:
        # Raw manifest bytes to stdout: exactly one document, no envelope.
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            buffer.write(data)
            buffer.flush()
        else:  # pragma: no cover - defensive when stdout has no byte buffer
            sys.stdout.write(data.decode("utf-8"))
            sys.stdout.flush()
        return EXIT_OK

    # -- every remaining gate runs before any write ----------------------------
    # The output checks are repeated (source collection may have taken a
    # while) and extended with the projected canonical documents; the
    # snapshot policy gate and the reader check run on a temporary sibling of
    # the manifest. Only when all of them pass is anything replaced, so a
    # refused build leaves the previous manifest and snapshot untouched.
    _preflight_build_manifest_target(target, force=force, limits=limits, protected=protected_inputs)
    _refuse_build_output_over_canonical_doc(target, manifest_obj, docs_home)
    if snapshot_path is not None:
        # Collision with a canonical document is reported before the generic
        # exists/--force rule: it names the actual hazard.
        _preflight_build_snapshot_output(snapshot_path, target, manifest_obj, docs_home)
        _preflight_build_snapshot_target(
            snapshot_path, target, force=force, limits=limits, protected=protected_inputs
        )
    snapshot_sha = _write_build_outputs(target, data, snapshot_path, limits)

    payload = {
        "manifest_path": str(target),
        "manifest_sha256": manifest_bytes_sha256(data),
        "manifest_bytes": len(data),
        "snapshot_path": str(snapshot_path) if snapshot_path else None,
        "snapshot_manifest_sha256": snapshot_sha,
        "docs": len(facts.canonical_docs),
        "concepts": 1 + len(facts.decisions) if facts.structure_summary else len(facts.decisions),
        "guardrails": len(facts.guardrails),
        "drift": [{"code": d.code, "detail": d.detail} for d in facts.drift],
        "authorities": {
            "name": facts.name_authority,
            "description": facts.description_authority,
            "repository": facts.repository_authority,
            "language": facts.primary_language_authority,
            "status": facts.status_authority,
            "docs": facts.canonical_docs_authority,
            "audiences": facts.audiences_authority,
        },
        "git_head": facts.git_head,
    }
    if fmt == "json":
        _json("build", ok=True, result_payload=payload)
    else:
        _text_build(payload)
    return EXIT_OK


def _text_build(payload: dict[str, Any]) -> None:
    typer.echo(f"✓ Built manifest at {payload['manifest_path']}")
    typer.echo(
        f"  sha256={payload['manifest_sha256'][:16]}…  docs={payload['docs']}  "
        f"concepts={payload['concepts']}  guardrails={payload['guardrails']}"
    )
    authorities = payload["authorities"]
    typer.echo(
        f"  authorities: name={authorities['name']} description={authorities['description']} "
        f"repository={authorities['repository']}"
    )
    for drift in payload["drift"]:
        typer.echo(f"  ⚠ drift {drift['code']}: {drift['detail']}")
    if payload["snapshot_path"]:
        typer.echo(f"  snapshot: {payload['snapshot_path']}")


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _write_temp_sibling(path: Path, data: bytes) -> str:
    """Write *data* to a fsynced temporary file next to *path*; return its name."""
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    temp_name = handle.name
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        _unlink_quietly(temp_name)
        raise
    return temp_name


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically replace *path* with *data* (temp file + fsync + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = _write_temp_sibling(path, data)
    try:
        os.replace(temp_name, path)
    except BaseException:
        _unlink_quietly(temp_name)
        raise


def _write_build_outputs(
    target: Path, data: bytes, snapshot_path: Path | None, limits: ResourceLimits
) -> str | None:
    """Write the manifest and optional snapshot; every gate has already passed.

    With a snapshot, the manifest bytes go to a temporary sibling first (so
    canonical docs resolve exactly as they will for the final file), the
    snapshot is built -- policy gate included -- and verified through the
    reader, and only then is the snapshot written and the manifest renamed
    into place. Any refusal removes the temporary file and replaces nothing.
    Returns the snapshot's recorded manifest digest, or ``None``.
    """
    if snapshot_path is None:
        _atomic_write_bytes(target, data)
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = _write_temp_sibling(target, data)
    committed = False
    try:
        snap, snapshot_sha = _build_verified_snapshot(Path(temp_name), target.parent, limits)
        try:
            snapshot_mod.write_snapshot_atomic(snapshot_path, snap, byte_ceiling=snap.byte_ceiling)
        except LimitError as exc:
            raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc
        except OSError as exc:
            raise cli_support.CliFailure(
                EXIT_INPUT, "build_snapshot_write_failed", "could not write snapshot"
            ) from exc
        os.replace(temp_name, target)
        committed = True
    finally:
        if not committed:
            _unlink_quietly(temp_name)
    return snapshot_sha


def _build_verified_snapshot(
    manifest_file: Path, docs_root: Path, limits: ResourceLimits
) -> tuple[snapshot_mod.Snapshot, str]:
    """Build the canonical snapshot (v0.2 writer end to end) and verify it loads."""
    from beacon.build.project import ACK_GUARDRAILS_MISSING, ACK_TEST_COMMAND_MISSING
    from beacon.build.snapshot import snapshot_from_payload
    from beacon.core.policy import Acknowledgement

    acknowledgements = (
        Acknowledgement(code=ACK_GUARDRAILS_MISSING[0], reason=ACK_GUARDRAILS_MISSING[1]),
        Acknowledgement(code=ACK_TEST_COMMAND_MISSING[0], reason=ACK_TEST_COMMAND_MISSING[1]),
    )
    try:
        snap = snapshot_mod.build_snapshot(
            manifest_file,
            docs_root=docs_root,
            content_mode=snapshot_mod.CONTENT_EMBEDDED,
            acknowledgements=acknowledgements,
            limits=limits,
        )
        encoded = snapshot_mod.snapshot_bytes(snap)
    except snapshot_mod.SnapshotError as exc:
        raise cli_support.CliFailure(
            EXIT_VALIDATION if "policy" in exc.code or "security" in exc.code else EXIT_INPUT,
            exc.code,
            str(exc),
        ) from exc
    except LimitError as exc:
        raise cli_support.CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded") from exc
    except OSError as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, "build_snapshot_write_failed", "could not write snapshot"
        ) from exc
    # Load the exact bytes back through the reader before anything is written,
    # so an artifact that would not be servable is never published.
    try:
        verified = snapshot_from_payload(json.loads(encoded.decode("utf-8")))
    except Exception as exc:  # noqa: BLE001 - reader errors are stable codes
        raise cli_support.CliFailure(
            EXIT_INTERNAL, "build_snapshot_unreadable", "built snapshot failed to load back"
        ) from exc
    return snap, verified.manifest.source_sha256


def _same_path(first: Path, second: Path) -> bool:
    """Return whether two paths name the same file (symlinks and case aware)."""
    try:
        if first.exists() and second.exists():
            return os.path.samefile(first, second)
        return os.path.normcase(str(first.resolve())) == os.path.normcase(str(second.resolve()))
    except (OSError, RuntimeError, ValueError):
        return False


def _preflight_build_manifest_target(
    target: Path, *, force: bool, limits: ResourceLimits, protected: tuple[Path, ...]
) -> None:
    """Refuse a manifest output that is a build input, unusable, or not replaceable.

    ``--force`` replaces only a file that is recognizably a Beacon manifest
    (the v0.2 ``init --force`` rule); a build input is never replaced.
    """
    if any(_same_path(target, path) for path in protected):
        raise cli_support.CliFailure(
            EXIT_INPUT, "build_output_protected", "output path is a build input"
        )
    if target.is_symlink() or target.is_dir():
        raise cli_support.CliFailure(
            EXIT_INPUT, "build_output_unusable", "output path exists and is not a regular file"
        )
    if target.exists():
        if not force:
            raise cli_support.CliFailure(
                EXIT_INPUT, "build_output_exists", "output already exists (use --force to replace)"
            )
        if not scaffold.is_recognizable_manifest(target, limits=limits):
            raise cli_support.CliFailure(
                EXIT_INPUT,
                "build_output_not_manifest",
                "existing output is not a Beacon manifest; --force replaces only a manifest",
            )


def _refuse_build_output_over_canonical_doc(
    target: Path, manifest_obj: Any, docs_root: Path
) -> None:
    """Refuse a manifest output that is one of the projected canonical documents."""
    for doc in manifest_obj.canonical_docs:
        try:
            doc_target = resolve_canonical_path(docs_root, doc.path)
        except UnsafeCanonicalPath:
            continue
        if _same_path(target, doc_target):
            raise cli_support.CliFailure(
                EXIT_INPUT, "build_output_protected", "output path is a canonical document"
            )


def _resolve_build_snapshot_path(snapshot_out: str, target: Path, root_dir: Path) -> Path:
    """Resolve ``--snapshot-out`` next to the manifest, contained in *root_dir*.

    Relative paths resolve against the manifest's directory; absolute paths
    are accepted only inside *root_dir*. Containment is checked on the fully
    resolved path, so ``..`` and symlinked components cannot escape.
    """
    candidate = Path(snapshot_out)
    if not candidate.is_absolute():
        candidate = target.parent / candidate
    try:
        resolved = candidate.resolve()
        root_resolved = root_dir.resolve()
    except (OSError, RuntimeError) as exc:
        raise cli_support.CliFailure(
            EXIT_INPUT, "build_snapshot_path_invalid", "invalid snapshot path"
        ) from exc
    if resolved == root_resolved or not resolved.is_relative_to(root_resolved):
        raise cli_support.CliFailure(
            EXIT_INPUT, "build_snapshot_path_invalid", "snapshot output escapes the output root"
        )
    if candidate.is_symlink() or resolved.is_dir():
        raise cli_support.CliFailure(
            EXIT_INPUT,
            "build_snapshot_path_invalid",
            "snapshot output exists and is not a regular file",
        )
    return resolved


def _is_beacon_snapshot(path: Path, limits: ResourceLimits) -> bool:
    """Return whether *path* is recognizably a Beacon snapshot (bounded read)."""
    try:
        raw = read_bytes_bounded(
            path, ceiling=limits.snapshot_bytes, code=LIMIT_SNAPSHOT_BYTES, field="snapshot_bytes"
        )
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, LimitError, UnicodeDecodeError, ValueError):
        return False
    return isinstance(payload, dict) and "beacon_snapshot_version" in payload


def _preflight_build_snapshot_target(
    snapshot_path: Path,
    manifest_target: Path,
    *,
    force: bool,
    limits: ResourceLimits,
    protected: tuple[Path, ...],
    check_existing: bool = True,
) -> None:
    """Refuse a snapshot output that collides with an input or is not replaceable.

    Overwriting requires ``--force``, and ``--force`` replaces only a file
    that is recognizably a Beacon snapshot (skipped when *check_existing* is
    false; the caller runs that rule later).
    """
    if _same_path(snapshot_path, manifest_target):
        raise cli_support.CliFailure(
            EXIT_INPUT, "build_snapshot_collision", "snapshot output collides with the manifest"
        )
    if any(_same_path(snapshot_path, path) for path in protected):
        raise cli_support.CliFailure(
            EXIT_INPUT, "build_snapshot_collision", "snapshot output collides with a build input"
        )
    if check_existing and snapshot_path.exists():
        if not force:
            raise cli_support.CliFailure(
                EXIT_INPUT,
                "build_snapshot_output_exists",
                "snapshot output already exists (use --force to replace)",
            )
        if not _is_beacon_snapshot(snapshot_path, limits):
            raise cli_support.CliFailure(
                EXIT_INPUT,
                "build_snapshot_not_replaceable",
                "existing snapshot output is not a Beacon snapshot; --force replaces only one",
            )


def _preflight_build_snapshot_output(
    snapshot_path: Path, manifest_target: Path, manifest_obj: Any, docs_root: Path
) -> None:
    """Refuse a snapshot output colliding with the manifest or a canonical doc.

    Canonical documents resolve against *docs_root* -- the directory the
    manifest is written to, exactly as the projection and the snapshot
    builder resolve them.
    """
    if _same_path(snapshot_path, manifest_target):
        raise cli_support.CliFailure(
            EXIT_INPUT, "build_snapshot_collision", "snapshot output collides with the manifest"
        )
    for doc in manifest_obj.canonical_docs:
        try:
            doc_target = resolve_canonical_path(docs_root, doc.path)
        except UnsafeCanonicalPath:
            continue
        if _same_path(snapshot_path, doc_target):
            raise cli_support.CliFailure(
                EXIT_INPUT,
                "build_snapshot_collision",
                "snapshot output collides with a canonical document",
            )


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
    _preflight_export_output(out_path, context)

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


def _preflight_export_output(out_path: Path, context: cli_support.CommandContext) -> None:
    """Refuse an export output that would overwrite the manifest or a canonical doc.

    Preserves the v0.2 read-only invariant: a new artifact or the replacement of
    an explicitly selected non-source snapshot remains allowed, but export never
    turns ``beacon.yaml`` or a selected canonical document into snapshot JSON.
    Raises a stable exit-2 :class:`CliFailure` before any write.
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
