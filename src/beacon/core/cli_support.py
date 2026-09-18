"""Small reusable CLI support layer (not Typer wiring) for v0.2 commands.

This module centralises the shared, pure decisions that ``validate``,
``inspect``, and ``export`` would otherwise re-derive independently, so their
behaviour cannot drift:

* :func:`build_resource_limits` — ``ResourceLimits`` with
  ``CLI override > environment > default`` precedence for exactly the six
  overridable fields, reusing :mod:`beacon.core.limits` and its stable
  :class:`~beacon.core.limits.LimitError` behaviour.
* :func:`resolve_manifest_path` / :func:`resolve_docs_root` — default the
  manifest to ``./beacon.yaml`` and the docs root to its parent, rejecting a
  missing/non-file manifest or an invalid docs root as user/input/safety
  failures (exit class 2) without echoing absolute paths or secrets.
* :class:`CommandContext` — one immutable snapshot holding limits, manifest,
  validation report, policy evaluation, acknowledgements, and an optional
  provider, so validate/inspect/export share a single pipeline.
* :class:`CliFailure` — a stable error carrying an ``exit_code`` (1/2/3) and a
  safe :class:`~beacon.core.cli_result.Diagnostic`.
* :func:`report_to_diagnostics` — convert report issues to diagnostics,
  labelling acknowledged warnings with their reasons while preserving facts.
* :func:`effective_limits_mapping` — a JSON-ready effective-limits mapping.

Exit classes follow the addendum: expected validation/policy failures are 1;
bad acknowledgements, missing inputs, unsafe paths, malformed YAML, and limits
are 2; :func:`normalize_internal` turns unexpected exceptions into 3 without
any exception details. Nothing here prints, logs, executes manifest commands,
or touches the network; environment access is limited to reading the limit
variables via an injected mapping.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from beacon.core.cli_result import (
    INTERNAL_ERROR_CODE,
    INTERNAL_ERROR_MESSAGE,
    Diagnostic,
    Severity,
    from_validation_issue,
)
from beacon.core.cli_result import (
    diagnostic as _build_diagnostic,
)
from beacon.core.doc_index import DocIndex
from beacon.core.limits import (
    OVERRIDABLE_LIMIT_FIELDS,
    LimitError,
    ResourceLimits,
    resource_limits_from_env,
)
from beacon.core.loader import ManifestError, load_beacon_manifest
from beacon.core.policy import (
    Acknowledgement,
    AcknowledgementError,
    PolicyEvaluation,
    evaluate_policy,
    parse_acknowledgements,
)
from beacon.core.schema import BeaconManifest
from beacon.core.validator import ValidationReport, validate_beacon_manifest
from beacon.provider.manifest_provider import ManifestBeaconProvider

#: Default manifest filename (relative to the working directory).
DEFAULT_MANIFEST_NAME = "beacon.yaml"

#: Exit codes carried by :class:`CliFailure`.
EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_INPUT = 2
EXIT_INTERNAL = 3

#: Stable, non-secret codes for input/safety failures (exit 2).
CODE_MANIFEST_NOT_FOUND = "manifest_not_found"
CODE_INVALID_DOCS_ROOT = "invalid_docs_root"
CODE_MANIFEST_INVALID = "manifest_invalid"

#: Stable code for a servable-failure when a provider is required (exit 1).
CODE_NOT_SERVABLE = "manifest_not_servable"


@dataclass
class CliFailure(Exception):
    """A stable command failure with an exit code and a safe diagnostic.

    ``exit_code`` is 1 (expected validation/policy failure), 2 (user/input/
    safety failure), or 3 (unexpected internal failure). ``code`` and
    ``message`` are stable and never contain absolute paths, secrets, or
    exception details. This is intentionally *not* a frozen dataclass so the
    standard exception traceback protocol works.
    """

    exit_code: int
    code: str
    message: str = "command failed"
    severity: str = "error"

    def __post_init__(self) -> None:
        if self.exit_code not in (EXIT_VALIDATION, EXIT_INPUT, EXIT_INTERNAL):
            raise ValueError(f"invalid CliFailure exit_code: {self.exit_code}")
        if not isinstance(self.severity, str) or not self.severity.strip():
            raise ValueError("CliFailure severity must be a non-empty string")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("CliFailure message must be a non-empty string")
        # Initialise the Exception base so str(exc) is meaningful yet safe.
        Exception.__init__(self, self.message)

    def __str__(self) -> str:
        """Return a stable, safe, human-readable summary (no secret details)."""
        return f"{self.code}: {self.message}"

    def to_diagnostic(self) -> Diagnostic:
        """Return the safe :class:`Diagnostic` for this failure."""
        try:
            severity = Severity(self.severity)
        except ValueError:
            severity = Severity.ERROR
        return _failure_diagnostic(severity, self.code, self.message)


def _failure_diagnostic(severity: Severity, code: str, message: str) -> Diagnostic:
    return _build_diagnostic(severity, code, message)


def normalize_internal(exc: Exception | None = None) -> CliFailure:
    """Return a safe exit-3 failure for an unexpected exception.

    *exc* is intentionally ignored: neither its type nor its ``str()`` text is
    ever placed into the failure, so paths, environment values, and secrets
    cannot leak.
    """
    return CliFailure(EXIT_INTERNAL, INTERNAL_ERROR_CODE, INTERNAL_ERROR_MESSAGE, severity="error")


# ---------------------------------------------------------------------------
# Limits / path resolution
# ---------------------------------------------------------------------------


def build_resource_limits(
    cli_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> ResourceLimits:
    """Return :class:`ResourceLimits` with ``CLI > env > default`` precedence.

    *env* supplies the environment layer (defaults to ``os.environ`` when
    ``None``); *cli_overrides* is a field-name -> integer mapping applied on top
    of the environment result. Only the six overridable fields are honoured;
    non-overridable and unknown keys are ignored. Invalid values raise
    :class:`~beacon.core.limits.LimitError` with a stable code.
    """
    base = resource_limits_from_env(env)
    if not cli_overrides:
        return base
    # Typer passes unset options as None; drop them so environment wins.
    cli = {name: value for name, value in cli_overrides.items() if value is not None}
    if not cli:
        return base
    return base.apply_overrides(cli, where="cli")


def resolve_manifest_path(
    manifest_path: str | Path | None = None, *, cwd: str | Path = "."
) -> Path:
    """Resolve the manifest path, defaulting to ``<cwd>/beacon.yaml``.

    Rejects a missing or non-file path as an exit-2 :class:`CliFailure` whose
    message never includes the (possibly absolute) path.
    """
    raw = Path(manifest_path) if manifest_path is not None else Path(DEFAULT_MANIFEST_NAME)
    if not raw.is_absolute():
        raw = Path(cwd) / raw
    if not raw.is_file():
        raise CliFailure(EXIT_INPUT, CODE_MANIFEST_NOT_FOUND, "manifest not found")
    return raw


def resolve_docs_root(docs_root: str | Path | None = None, *, manifest_path: str | Path) -> Path:
    """Resolve the docs root, defaulting to the manifest file's parent directory.

    When *docs_root* is provided it must be an existing directory; otherwise the
    input is rejected as an exit-2 :class:`CliFailure` without echoing the path.
    """
    if docs_root is None:
        return Path(manifest_path).resolve().parent
    root = Path(docs_root)
    if not root.is_dir():
        raise CliFailure(EXIT_INPUT, CODE_INVALID_DOCS_ROOT, "invalid docs root")
    return root


def effective_limits_mapping(limits: ResourceLimits) -> dict[str, int]:
    """Return a JSON-ready mapping of the six overridable limits."""
    return {field: limits.ceiling(field) for field in OVERRIDABLE_LIMIT_FIELDS}


# ---------------------------------------------------------------------------
# Command context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandContext:
    """Immutable snapshot of everything a CLI command needs.

    Built once by :func:`build_command_context` so validate/inspect/export read
    the same manifest, limits, report, policy, and (optionally) provider.
    """

    limits: ResourceLimits
    manifest_path: Path
    docs_root: Path
    manifest: BeaconManifest
    report: ValidationReport
    policy: PolicyEvaluation
    acknowledgements: tuple[Acknowledgement, ...]
    provider: ManifestBeaconProvider | None = None


def build_command_context(
    *,
    cli_limits: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    manifest_path: str | Path | None = None,
    docs_root: str | Path | None = None,
    acknowledgements: Iterable[str] = (),
    build_provider: bool = False,
    cwd: str | Path = ".",
) -> CommandContext:
    """Load, validate, and evaluate one shared command context.

    Raises :class:`CliFailure` with exit 2 for input/safety failures (bad
    acknowledgements, missing/invalid inputs, malformed YAML, limits) and exit
    1 when *build_provider* is requested but the manifest is not servable.
    Expected validation/policy outcomes are *stored* in the returned context
    (with ``report``/``policy``) rather than raised. Any unexpected exception
    is normalized to an exit-3 :class:`CliFailure` without details.
    """
    try:
        return _build_command_context(
            cli_limits=cli_limits,
            env=env,
            manifest_path=manifest_path,
            docs_root=docs_root,
            acknowledgements=acknowledgements,
            build_provider=build_provider,
            cwd=cwd,
        )
    except CliFailure:
        raise
    except Exception as exc:  # noqa: BLE001 - normalized safely for the CLI
        raise normalize_internal(exc) from exc


def _build_command_context(
    *,
    cli_limits: Mapping[str, Any] | None,
    env: Mapping[str, str] | None,
    manifest_path: str | Path | None,
    docs_root: str | Path | None,
    acknowledgements: Iterable[str],
    build_provider: bool,
    cwd: str | Path,
) -> CommandContext:
    try:
        limits = build_resource_limits(cli_limits, env)
    except LimitError as exc:
        raise _limit_failure(exc) from exc

    try:
        manifest_path_resolved = resolve_manifest_path(manifest_path, cwd=cwd)
    except CliFailure:
        raise
    docs_root_resolved = resolve_docs_root(docs_root, manifest_path=manifest_path_resolved)

    try:
        acks = parse_acknowledgements(acknowledgements)
    except AcknowledgementError as exc:
        raise CliFailure(EXIT_INPUT, exc.code, "invalid acknowledgement", severity="error") from exc

    try:
        manifest = load_beacon_manifest(manifest_path_resolved, limits=limits)
    except LimitError as exc:
        raise _limit_failure(exc) from exc
    except ManifestError as exc:
        raise CliFailure(
            EXIT_INPUT, CODE_MANIFEST_INVALID, "malformed or invalid manifest", severity="error"
        ) from exc

    report = validate_beacon_manifest(manifest, docs_root=docs_root_resolved)
    policy = evaluate_policy(report, acknowledgements=acks)

    provider = None
    if build_provider:
        if not report.ok:
            raise CliFailure(
                EXIT_VALIDATION,
                CODE_NOT_SERVABLE,
                "manifest is not servable",
                severity="error",
            )
        provider = _build_provider(docs_root_resolved, limits, manifest)

    return CommandContext(
        limits=limits,
        manifest_path=manifest_path_resolved,
        docs_root=docs_root_resolved,
        manifest=manifest,
        report=report,
        policy=policy,
        acknowledgements=acks,
        provider=provider,
    )


def build_provider(context: CommandContext) -> ManifestBeaconProvider:
    """Attach a provider to an already-built *context* without re-reading the manifest.

    Requires ``context.report.ok`` (servable); otherwise raises an exit-1
    :class:`CliFailure` with :data:`CODE_NOT_SERVABLE`. The provider is built
    from the context's already-loaded manifest, limits, and docs root so the
    shared one-read pipeline holds. Used by ``inspect`` and the explicit
    ``serve`` command after they have surfaced the full validation diagnostics.
    """
    if not context.report.ok:
        raise CliFailure(
            EXIT_VALIDATION,
            CODE_NOT_SERVABLE,
            "manifest is not servable",
            severity="error",
        )
    return _build_provider(context.docs_root, context.limits, context.manifest)


def _build_provider(
    docs_root: Path, limits: ResourceLimits, manifest: BeaconManifest
) -> ManifestBeaconProvider:
    """Build the provider from the already-loaded *manifest* (one snapshot).

    Does not re-read the manifest from disk: the doc index is built from
    ``manifest.canonical_docs`` so :class:`CommandContext` holds a single,
    internally-consistent snapshot. Unexpected errors are normalized safely.
    """
    try:
        doc_index = DocIndex.from_docs(manifest.canonical_docs, docs_root=docs_root, limits=limits)
        return ManifestBeaconProvider(
            manifest=manifest,
            doc_index=doc_index,
            docs_root=docs_root,
            limits=limits,
        )
    except LimitError as exc:
        raise _limit_failure(exc) from exc
    except Exception as exc:  # noqa: BLE001 - normalized safely for the CLI
        raise normalize_internal(exc) from exc


def _limit_failure(exc: LimitError) -> CliFailure:
    return CliFailure(EXIT_INPUT, exc.code, "resource limit exceeded", severity="error")


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def report_to_diagnostics(
    report: ValidationReport,
    acknowledgements: Iterable[Acknowledgement] = (),
) -> tuple[Diagnostic, ...]:
    """Convert *report* issues to diagnostics, labelling acknowledged warnings.

    Each acknowledged warning is marked with its reason; all other facts
    (severity, code, ``where`` -> ``path``, message) are preserved verbatim and
    nothing is mutated. Order matches the report's deterministic issue order.
    """
    ack_reason: dict[str, str] = {ack.code: ack.reason for ack in acknowledgements}
    out: list[Diagnostic] = []
    for issue in report.issues:
        reason = ack_reason.get(issue.code) if issue.severity == "warning" else None
        if reason is not None:
            out.append(
                from_validation_issue(issue, acknowledged=True, acknowledgement_reason=reason)
            )
        else:
            out.append(from_validation_issue(issue))
    return tuple(out)


__all__ = [
    "CODE_INVALID_DOCS_ROOT",
    "CODE_MANIFEST_INVALID",
    "CODE_MANIFEST_NOT_FOUND",
    "CODE_NOT_SERVABLE",
    "DEFAULT_MANIFEST_NAME",
    "EXIT_INPUT",
    "EXIT_INTERNAL",
    "EXIT_OK",
    "EXIT_VALIDATION",
    "CliFailure",
    "CommandContext",
    "build_command_context",
    "build_provider",
    "build_resource_limits",
    "effective_limits_mapping",
    "normalize_internal",
    "report_to_diagnostics",
    "resolve_docs_root",
    "resolve_manifest_path",
]
