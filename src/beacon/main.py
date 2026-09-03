"""Beacon CLI entry point.

Subcommands
-----------
  beacon                    Start the MCP stdio server (default when no subcommand).
  beacon validate PATH      Validate a beacon.yaml and exit 0 on success, 1 on errors.
  beacon inspect  PATH      Load a beacon.yaml and print a human-readable tool summary.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import typer

app = typer.Typer(
    name="beacon",
    no_args_is_help=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# ---------------------------------------------------------------------------
# Default: start the MCP stdio server
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


@app.callback(invoke_without_command=True)
def serve(ctx: typer.Context) -> None:
    """Start the Beacon MCP stdio server (default when no subcommand is given)."""
    if ctx.invoked_subcommand is not None:
        return

    from dotenv import load_dotenv

    load_dotenv(os.getenv("ENV_FILE") or None)
    _configure_logging(include_console=False)

    from archolith_mcp_framework import run_server

    from beacon.mcp.server import mcp

    print(
        f"[beacon] MCP stdio starting (pid={os.getpid()})",
        file=sys.stderr,
        flush=True,
    )
    run_server(mcp)


# ---------------------------------------------------------------------------
# beacon validate PATH
# ---------------------------------------------------------------------------


@app.command()
def validate(
    path: Path = typer.Argument(..., help="Path to beacon.yaml"),
) -> None:
    """Validate a beacon.yaml manifest and report errors and warnings.

    Exits 0 when there are no errors. Exits 1 if the manifest cannot be
    parsed or contains any error-level issues. Warnings are printed but do
    not cause a non-zero exit.
    """
    from beacon.core.loader import ManifestError, load_beacon_manifest
    from beacon.core.validator import validate_beacon_manifest

    if not path.is_file():
        typer.echo(f"✗  File not found: {path}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Validating {path} ...\n")

    try:
        manifest = load_beacon_manifest(path)
    except ManifestError as exc:
        typer.echo(f"✗  Parse error: {exc}")
        raise typer.Exit(1)

    report = validate_beacon_manifest(manifest, docs_root=path.parent)

    if report.errors:
        typer.echo(
            f"✗  {len(report.errors)} error(s), {len(report.warnings)} warning(s)\n"
        )
        for issue in report.errors:
            typer.echo(f"  ✗  {issue.where}: {issue.message}")
        for issue in report.warnings:
            typer.echo(f"  ⚠  {issue.where}: {issue.message}")
        raise typer.Exit(1)

    if report.warnings:
        typer.echo(f"✓  Valid — 0 errors, {len(report.warnings)} warning(s)\n")
        for issue in report.warnings:
            typer.echo(f"  ⚠  {issue.where}: {issue.message}")
    else:
        typer.echo("✓  Valid — 0 errors, 0 warnings")


# ---------------------------------------------------------------------------
# beacon inspect PATH
# ---------------------------------------------------------------------------


@app.command()
def inspect(
    path: Path = typer.Argument(..., help="Path to beacon.yaml"),
) -> None:
    """Load a beacon.yaml and print a human-readable summary of all five tool outputs.

    Useful as a local smoke test before connecting an MCP client. Calls every
    provider method and prints the key fields so you can confirm what agents
    will receive.
    """
    from beacon.core.doc_index import DocIndex
    from beacon.core.loader import ManifestError, load_beacon_manifest
    from beacon.core.validator import validate_beacon_manifest
    from beacon.provider.manifest_provider import ManifestBeaconProvider

    if not path.is_file():
        typer.echo(f"✗  File not found: {path}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Inspecting {path} ...\n")

    try:
        manifest = load_beacon_manifest(path)
    except ManifestError as exc:
        typer.echo(f"✗  Parse error: {exc}")
        raise typer.Exit(1)

    docs_root = path.parent
    report = validate_beacon_manifest(manifest, docs_root=docs_root)
    if report.errors:
        typer.echo(
            f"✗  Manifest has {len(report.errors)} error(s) — run 'beacon validate' to fix:"
        )
        for issue in report.errors:
            typer.echo(f"  ✗  {issue.where}: {issue.message}")
        raise typer.Exit(1)

    # --- header ---
    p = manifest.project
    typer.echo(f"Project:   {p.name} ({p.status})")
    if p.tagline:
        typer.echo(f"Tagline:   {p.tagline}")
    typer.echo(
        f"Manifest:  beacon_version={manifest.beacon_version}"
        f"  concepts={len(manifest.core_concepts)}"
        f"  docs={len(manifest.canonical_docs)}"
        f"  guardrails={len(manifest.guardrails)}"
    )
    typer.echo(f"Docs root: {docs_root}\n")

    provider = ManifestBeaconProvider(
        manifest=manifest,
        doc_index=DocIndex.from_docs(manifest.canonical_docs, docs_root=docs_root),
        docs_root=docs_root,
    )

    # --- beacon_project_overview ---
    _hr()
    ov = provider.project_overview()
    _section("beacon_project_overview")
    _field("summary", _trunc(ov.summary, 100))
    _field("status", f"{ov.status}  confidence: {ov.confidence}")
    _field("components", str(len(ov.core_components)))
    _field("read_next", _join(ov.read_next[:4]))

    # --- beacon_agent_onboarding ---
    _hr()
    ob = provider.agent_onboarding()
    _section("beacon_agent_onboarding")
    _field("orientation", _trunc(ob.orientation, 100))
    _field("docs", _join(ob.relevant_docs[:3]))
    _field("concepts", _join(ob.concepts_to_understand[:4]))
    _field("safe steps", f"{len(ob.safe_first_steps)} items")
    _field("do-not-touch", f"{len(ob.do_not_touch)} items")
    _field("commands", f"{len(ob.commands)} command(s)")
    _field("status", f"{ob.status}  confidence: {ob.confidence}")

    # --- beacon_search ---
    _hr()
    query = manifest.core_concepts[0].id if manifest.core_concepts else "overview"
    sr = provider.search(query=query)
    _section(f'beacon_search  (query: "{query}")')
    _field("answer", sr.answer)
    for hit in sr.results[:3]:
        typer.echo(f"    [{hit.source_type}] {hit.title} — {_trunc(hit.snippet, 60)}")
    _field("status", f"{sr.status}  confidence: {sr.confidence}")

    # --- beacon_explain_concept ---
    _hr()
    first_concept = manifest.core_concepts[0].id if manifest.core_concepts else "overview"
    ce = provider.explain_concept(concept=first_concept)
    _section(f'beacon_explain_concept  (concept: "{first_concept}")')
    _field("concept", f"{ce.concept}  ({ce.status})")
    _field("definition", _trunc(ce.definition, 100))
    if ce.related_concepts:
        _field("related", _join(ce.related_concepts))
    _field("status", f"{ce.status}  confidence: {ce.confidence}")

    # --- beacon_guardrails ---
    _hr()
    gr = provider.guardrails()
    high = sum(1 for r in gr.rules if r.startswith("[high]"))
    med = sum(1 for r in gr.rules if r.startswith("[medium]"))
    low_count = sum(1 for r in gr.rules if r.startswith("[low]"))
    _section("beacon_guardrails")
    _field("rules", f"{len(gr.rules)} total  ({high} high, {med} medium, {low_count} low)")
    if gr.risky_files:
        _field("risky files", _join(gr.risky_files[:4]))
    if gr.required_checks:
        _field("required checks", gr.required_checks[0])
    _field("status", f"{gr.status}  confidence: {gr.confidence}")
    _hr()

    if report.warnings:
        typer.echo(
            f"\n  ⚠  {len(report.warnings)} manifest warning(s)"
            " — run 'beacon validate' for details"
        )

    typer.echo("\n✓  Inspect complete. 5 tools responded.")


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
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":
    main()
