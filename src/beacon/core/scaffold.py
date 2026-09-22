"""Starter-manifest rendering, init report model, and guarded atomic writing.

This module turns a :class:`~beacon.core.discovery.DiscoveryResult` into a
deterministic UTF-8 ``beacon.yaml`` and an immutable
``beacon-init-report`` v1.0 report, and performs the only file writes core init
is allowed to make:

* the generated manifest, written atomically (temp file + fsync + rename, with
  cleanup on every failure); and
* an optional JSON report, delegated to
  :mod:`beacon.core.canonical_json` with the init-report byte ceiling.

Safety rules (matching ``docs/schemas/beacon-init-report-1.0.schema.json`` and
the WP1 plan):

* the output manifest path is resolved safely within the repository root and
  must be a relative forward-slash path;
* there is no overwrite by default;
* ``force`` replaces only an existing regular, in-root, recognizable Beacon
  manifest -- never an unrelated file, directory, symlink, or path escape;
* if the repository has no safe allowlisted entry document, init *refuses*
  with a stable review code and writes nothing (an empty ``canonical_docs``
  would otherwise fail validation);
* rendered YAML is deterministic (fixed human-facing field order, UTF-8, one
  trailing newline) and every emitted manifest parses with zero errors; and
* no partial artifacts survive a failed write.

The module is pure data plus file writes; it does not touch the CLI.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any

import yaml

from beacon.core import discovery as _discovery
from beacon.core.canonical_json import write_atomic as _write_json_atomic
from beacon.core.discovery import (
    KIND_GIT_REMOTE,
    DiscoveryResult,
    Evidence,
)
from beacon.core.limits import (
    LIMIT_MANIFEST_BYTES,
    LIMIT_PATH_BYTES,
    LimitError,
    ResourceLimits,
)
from beacon.core.loader import ManifestError, load_beacon_manifest
from beacon.core.paths import (
    CODE_UNSAFE_CANONICAL_PATH,
    UnsafeCanonicalPath,
    is_unsafe_path,
)
from beacon.core.security import SecurityFinding
from beacon.sources.git import (
    GitSourceAdapter,
    GitSourceError,
    GitSourceUnavailable,
    records_to_git_evidence,
)

#: Machine name and version from the canonical schema ``$id``.
SCHEMA_NAME = "beacon.init-report"
SCHEMA_VERSION = "1.1"

#: Default manifest filename written into the repository root.
DEFAULT_MANIFEST_NAME = "beacon.yaml"

#: Operations the report schema permits.
OPERATION_DRY_RUN = "dry_run"
OPERATION_CREATE = "create"
OPERATION_REPLACE = "replace"
OPERATION_REFUSED = "refused"
OPERATIONS = frozenset({OPERATION_DRY_RUN, OPERATION_CREATE, OPERATION_REPLACE, OPERATION_REFUSED})

#: Stable review/input codes used by init (all match ``^[a-z][a-z0-9_]{1,63}$``).
REVIEW_PROJECT_STATUS_UNKNOWN = "project_status_unknown"
REVIEW_PURPOSE_MISSING = "purpose_missing"
REVIEW_GUARDRAILS_MISSING = "guardrails_missing"
REVIEW_TEST_COMMAND_MISSING = "test_command_missing"
REVIEW_CANONICAL_DOCS_MISSING = "canonical_docs_missing"
REVIEW_BUILD_COMMANDS_UNKNOWN = "build_commands_unknown"
REVIEW_MANIFEST_EXISTS = "manifest_exists"
OMITTED_CONCEPTS = "concepts_omitted"
OMITTED_LICENSE = "license_omitted"
OMITTED_BENCHMARK = "benchmark_omitted"

#: Stable refusal reason codes carried on a refused report.
REFUSED_NO_CANONICAL_DOC = REVIEW_CANONICAL_DOCS_MISSING


@dataclass(frozen=True)
class DiscoveredField:
    """A discovered manifest field plus the evidence that supports it."""

    manifest_path: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class ReviewItem:
    """A field left for human review or intentionally omitted."""

    code: str
    manifest_path: str
    reason: str
    evidence_checked: tuple[str, ...] = ()


@dataclass(frozen=True)
class InitReport:
    """The immutable ``beacon.init-report`` v1.1 report.

    ``git_evidence`` is the optional, adapter-owned ``git_evidence`` section
    (schema 1.1, additive): bounded local git history supplied by
    :class:`~beacon.sources.git.GitSourceAdapter`. It is absent when the
    repository has no usable git metadata. Git evidence is reality/history
    for the maintainer's review; it never fills intent-bearing manifest
    fields by itself.
    """

    operation: str
    manifest_path: str
    would_write: bool
    written: bool
    replaced: bool
    discovered: tuple[DiscoveredField, ...] = ()
    omitted: tuple[ReviewItem, ...] = ()
    review_required: tuple[ReviewItem, ...] = ()
    security_findings: tuple[SecurityFinding, ...] = ()
    git_evidence: dict[str, Any] | None = None
    schema: str = SCHEMA_NAME
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.operation not in OPERATIONS:
            raise ValueError(f"unknown init operation: {self.operation}")
        if self.schema != SCHEMA_NAME or self.schema_version != SCHEMA_VERSION:
            raise ValueError("init report must declare the canonical schema/version")


class InitRefused(Exception):
    """Raised (and caught inside :func:`init`) when core init refuses to write.

    ``review_code`` is the stable code explaining the refusal (e.g.
    ``canonical_docs_missing``). The message never contains paths or secrets.
    """

    def __init__(self, review_code: str, message: str) -> None:
        self.review_code = review_code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Manifest rendering (deterministic, fixed human-facing order)
# ---------------------------------------------------------------------------


def render_manifest_yaml(discovery: DiscoveryResult) -> bytes:
    """Render *discovery* into deterministic UTF-8 ``beacon.yaml`` bytes.

    Field order is fixed for humans (``beacon_version`` first, then project,
    purpose, audiences/current_focus, concepts, canonical_docs, guidance,
    build/test, guardrails). Output is one YAML document ending in a single
    newline. ``project.status`` is ``unknown`` and the description is a factual,
    nonempty sentence; unknown lists are explicit and empty.
    """
    manifest: dict[str, object] = {
        "beacon_version": "0.1",
        "project": _render_project(discovery),
        "purpose": {
            "one_sentence": "",
            "problem": "",
            "non_goals": [],
        },
        "audiences": [],
        "current_focus": [],
        "core_concepts": [],
        "canonical_docs": [
            {
                "path": path,
                "role": "entrypoint" if _is_entrypoint(path) else "reference",
                "status": "current",
            }
            for path in discovery.canonical_docs
        ],
        "agent_guidance": {
            "read_first": list(discovery.canonical_docs),
            "safe_first_tasks": [],
            "avoid_without_review": [],
            "expected_behavior": [],
        },
        "build_and_test": _render_build_test(discovery),
        "guardrails": [],
    }
    text = yaml.safe_dump(
        manifest,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1_000_000,
    )
    text = text.rstrip("\n") + "\n"
    return text.encode("utf-8")


def _render_project(discovery: DiscoveryResult) -> dict[str, object]:
    project: dict[str, object] = {
        "name": discovery.name,
        "tagline": "",
        "status": "unknown",
        "description": (
            f"Starter Beacon manifest for {discovery.name}. Generated from the repository "
            "directory name and local signals; purpose, core concepts, and guardrails are "
            "unknown and require maintainer review."
        ),
    }
    if discovery.repository:
        project["repository"] = discovery.repository
    if discovery.primary_language:
        project["primary_language"] = discovery.primary_language
    if discovery.license_name:
        project["license"] = discovery.license_name
    return project


def _render_build_test(discovery: DiscoveryResult) -> dict[str, object]:
    build_test: dict[str, object] = {"benchmark": ""}
    if discovery.setup_command:
        build_test["setup"] = discovery.setup_command
    if discovery.test_command:
        build_test["test"] = discovery.test_command
    return build_test


def _is_entrypoint(path: str) -> bool:
    return path.endswith("README.md")


# ---------------------------------------------------------------------------
# Init orchestration: discovery -> classify -> write
# ---------------------------------------------------------------------------


def init(
    root: str | Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    manifest_path: str = DEFAULT_MANIFEST_NAME,
    limits: ResourceLimits | None = None,
    before_write: Callable[[InitReport], None] | None = None,
) -> InitReport:
    """Run core init against *root* and return a report (no CLI side effects).

    Discovery runs first. If no safe allowlisted entry document exists the
    result is a *refused* report (``would_write`` false, nothing written) with a
    stable ``canonical_docs_missing`` review item. Otherwise the target manifest
    path is resolved safely and written atomically unless ``dry_run`` is set.
    ``force`` permits replacement only of an existing recognizable Beacon
    manifest; unrelated files, directories, symlinks, and escapes are refused.

    *before_write*, when given, is called with the final report immediately
    before the manifest is written (only when a write will happen). If it
    raises, the manifest is not written. This lets a caller persist a report
    first so a report failure never leaves a half-applied init behind.
    """
    active = limits if limits is not None else ResourceLimits()
    discovery = _discovery.discover(root, limits=active)
    discovery, git_evidence = _collect_git_evidence(root, discovery)
    normalized_path = _normalize_manifest_path(manifest_path)
    # Resolve/validate the manifest target up front (without writing) so an
    # over-long or unsafe path is refused even when no canonical doc exists and
    # the no-doc branch would otherwise return a schema-shaped report.
    target = _resolve_manifest_target(
        root,
        normalized_path,
        active,
        preserve_target_symlink=True,
    )
    root_path = Path(root).resolve()

    if not discovery.canonical_docs:
        return _refused_report(
            discovery,
            manifest_path=normalized_path,
            review_code=REFUSED_NO_CANONICAL_DOC,
            reason="no safe allowlisted entry document was found; nothing to record as canonical",
            git_evidence=git_evidence,
        )

    writable, replace = _classify_target(target, force=force, limits=active, root=root_path)

    extra_review: tuple[ReviewItem, ...] = ()
    if not writable:
        extra_review = (
            ReviewItem(
                REVIEW_MANIFEST_EXISTS,
                normalized_path,
                "an existing or unsafe target occupies the manifest path; refusing to overwrite",
            ),
        )

    report = _build_report(
        discovery,
        operation=_select_operation(dry_run=dry_run, writable=writable, replace=replace),
        manifest_path=normalized_path,
        would_write=writable,
        written=(not dry_run) and writable,
        replaced=(not dry_run) and writable and replace,
        no_docs=False,
        extra_review=extra_review,
        git_evidence=git_evidence,
    )

    if (not dry_run) and writable:
        rendered = render_manifest_yaml(discovery)
        if before_write is not None:
            before_write(report)
        _write_manifest_atomic(target, rendered, limits=active)
    return report


def resolve_output_path(root: str | Path, manifest_path: str) -> Path:
    """Resolve *manifest_path* to the lexical in-root candidate or raise.

    The candidate is the *lexical* in-root path (symlink identity preserved).
    Raises :class:`UnsafeCanonicalPath` (``unsafe_canonical_path``) for absolute
    paths, ``..`` traversal, symlink escapes, or an over-long path.
    """
    return _resolve_manifest_target(root, _normalize_manifest_path(manifest_path), ResourceLimits())


def is_recognizable_manifest(path: str | Path, *, limits: ResourceLimits | None = None) -> bool:
    """Return True when *path* is a recognizable Beacon YAML manifest.

    Recognition uses the bounded strict loader: *path* must parse into a typed
    :class:`~beacon.core.schema.BeaconManifest` declaring ``beacon_version``
    ``0.1`` with a project mapping. Any read, parse, or structural error, or a
    version other than ``0.1``, is ``False``.
    """
    active = limits if limits is not None else ResourceLimits()
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        return False
    try:
        manifest = load_beacon_manifest(candidate, limits=active)
    except (ManifestError, LimitError):
        return False
    return manifest.beacon_version == "0.1"


def write_report(
    report: InitReport, path: str | Path, *, limits: ResourceLimits | None = None
) -> None:
    """Write *report* as canonical JSON via the shared atomic writer.

    Uses the init-report byte ceiling so an oversized report refuses before
    touching the destination.
    """
    active = limits if limits is not None else ResourceLimits()
    _write_json_atomic(path, to_payload(report), byte_ceiling=active.init_report_bytes)


# ---------------------------------------------------------------------------
# Report payload conversion
# ---------------------------------------------------------------------------


def to_payload(report: InitReport) -> dict[str, object]:
    """Convert *report* to a JSON-ready dict matching the init-report schema."""
    payload: dict[str, object] = {
        "beacon_init_report_version": report.schema_version,
        "operation": report.operation,
        "repository_root": ".",
        "manifest_path": report.manifest_path,
        "would_write": report.would_write,
        "written": report.written,
        "replaced": report.replaced,
        "discovered": [_discovered_field_payload(f) for f in report.discovered],
        "omitted": [_review_item_payload(i) for i in report.omitted],
        "review_required": [_review_item_payload(i) for i in report.review_required],
        "security_findings": [_security_finding_payload(f) for f in report.security_findings],
    }
    if report.git_evidence is not None:
        payload["git_evidence"] = report.git_evidence
    return payload


def _discovered_field_payload(field: DiscoveredField) -> dict[str, object]:
    return {
        "manifest_path": field.manifest_path,
        "value": True,
        "evidence": [_evidence_payload(e) for e in field.evidence],
    }


def _evidence_payload(evidence: Evidence) -> dict[str, object]:
    payload: dict[str, object] = {"kind": evidence.kind, "path": evidence.path}
    if evidence.sha256 is not None:
        payload["sha256"] = evidence.sha256
    return payload


def _review_item_payload(item: ReviewItem) -> dict[str, object]:
    payload: dict[str, object] = {
        "code": item.code,
        "manifest_path": item.manifest_path,
        "reason": item.reason,
    }
    if item.evidence_checked:
        payload["evidence_checked"] = list(item.evidence_checked)
    return payload


def _security_finding_payload(finding: SecurityFinding) -> dict[str, object]:
    payload: dict[str, object] = {
        "code": finding.code,
        "path": finding.path,
        "blocked": finding.blocked,
    }
    if finding.line is not None:
        payload["line"] = finding.line
    return payload


# ---------------------------------------------------------------------------
# Write classification and atomic YAML write
# ---------------------------------------------------------------------------


def _resolve_manifest_target(
    root: str | Path,
    manifest_path: str,
    limits: ResourceLimits,
    *,
    preserve_target_symlink: bool = False,
) -> Path:
    """Return the lexical in-root candidate for *manifest_path*.

    The lexical candidate preserves symlink identity so a target symlink (or a
    symlinked parent component below root) is not mistaken for its referent.
    Resolution is used *only* for containment: the candidate must resolve to a
    path still under the resolved root, or :class:`UnsafeCanonicalPath` is
    raised. When ``preserve_target_symlink`` is true, an existing final-component
    symlink is returned lexically so init's target classifier can produce its
    required refusal report without following or writing through the link. The
    normalized ``manifest_path`` is also subject to the one-relative-path byte
    limit (``limit_path_bytes``) and refused before any write.
    """
    if not manifest_path or is_unsafe_path(manifest_path):
        raise UnsafeCanonicalPath()
    rel_bytes = len(manifest_path.encode("utf-8"))
    if rel_bytes > limits.path_bytes:
        raise LimitError(
            LIMIT_PATH_BYTES,
            f"resource limit exceeded: {LIMIT_PATH_BYTES} "
            f"(limit={limits.path_bytes}, actual={rel_bytes})",
            limit="path_bytes",
            limit_value=limits.path_bytes,
        )
    root_resolved = Path(root).resolve()
    lexical = root_resolved.joinpath(manifest_path)
    if preserve_target_symlink and lexical.is_symlink():
        return lexical
    try:
        resolved = lexical.resolve()
    except (OSError, RuntimeError) as exc:
        raise UnsafeCanonicalPath() from exc
    if not resolved.is_relative_to(root_resolved):
        raise UnsafeCanonicalPath()
    return lexical


def _normalize_manifest_path(manifest_path: str) -> str:
    """Normalize to a repository-relative, forward-slash relative path."""
    return manifest_path.replace("\\", "/")


def _has_symlinked_component(root: Path, target: Path) -> bool:
    """Return True when any parent component of *target* below *root* is a symlink."""
    try:
        rel = target.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in rel.parts[:-1]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _classify_target(
    target: Path, *, force: bool, limits: ResourceLimits, root: Path
) -> tuple[bool, bool]:
    """Return ``(writable, replace)`` for *target* under the overwrite policy.

    The target's parent must be an existing, in-root, non-symlink directory
    (including every symlinked component below root); otherwise it is not
    writable. A symlink, directory, or non-manifest regular file is never
    replaced.
    """
    if _has_symlinked_component(root, target):
        return False, False
    parent = target.parent
    if parent.is_symlink() or not parent.is_dir():
        return False, False
    if target.is_symlink() or target.is_dir():
        return False, False
    if not target.exists():
        return True, False
    if force and is_recognizable_manifest(target, limits=limits):
        return True, True
    return False, False


def _select_operation(*, dry_run: bool, writable: bool, replace: bool) -> str:
    if not writable:
        return OPERATION_REFUSED
    if dry_run:
        return OPERATION_DRY_RUN
    return OPERATION_REPLACE if replace else OPERATION_CREATE


def _collect_git_evidence(
    root: str | Path, discovery: DiscoveryResult
) -> tuple[DiscoveryResult, dict[str, Any] | None]:
    """Collect git evidence for init, preferring the adapter for the origin URL.

    The adapter is the primary source of the repository URL (it resolves
    worktrees and URL rewrites correctly); the pure ``.git/config`` read in
    discovery remains the fallback when git evidence is unavailable. Any
    adapter failure degrades to "no git section" rather than failing init:
    the manifest never depends on git evidence, because git supplies
    reality/history, never intent.
    """
    adapter = GitSourceAdapter(root)
    try:
        records = adapter.collect()
    except (GitSourceUnavailable, GitSourceError):
        return discovery, None
    git_evidence = records_to_git_evidence(records)
    url, url_findings = adapter.repository_url()
    # The adapter's URL findings (a credential embedded in the origin URL,
    # for example) are merged into the report whether or not the URL itself
    # is used, deduplicated against discovery's own config-read findings.
    merged: dict[tuple[str, str | None, bool], SecurityFinding] = {}
    for finding in (*discovery.security_findings, *url_findings):
        merged[(finding.code, finding.path, finding.blocked)] = finding
    findings = tuple(merged.values())
    if url is not None:
        discovery = dataclass_replace(
            discovery,
            repository=url,
            git_evidence=Evidence(kind=KIND_GIT_REMOTE, path="."),
            security_findings=findings,
        )
    else:
        discovery = dataclass_replace(discovery, security_findings=findings)
    return discovery, git_evidence


def _build_report(
    discovery: DiscoveryResult,
    *,
    operation: str,
    manifest_path: str,
    would_write: bool,
    written: bool,
    replaced: bool,
    no_docs: bool,
    extra_review: tuple[ReviewItem, ...] = (),
    git_evidence: dict[str, Any] | None = None,
) -> InitReport:
    discovered = _discovered_fields(discovery, no_docs=no_docs)
    omitted = _omitted_items(discovery)
    review = _review_items(discovery, no_docs=no_docs) + extra_review
    return InitReport(
        operation=operation,
        manifest_path=manifest_path,
        would_write=would_write,
        written=written,
        replaced=replaced,
        discovered=discovered,
        omitted=omitted,
        review_required=review,
        security_findings=discovery.security_findings,
        git_evidence=git_evidence,
    )


def _discovered_fields(discovery: DiscoveryResult, *, no_docs: bool) -> tuple[DiscoveredField, ...]:
    fields: list[DiscoveredField] = [DiscoveredField("project.name", (discovery.name_evidence,))]
    if discovery.repository and discovery.git_evidence is not None:
        fields.append(DiscoveredField("project.repository", (discovery.git_evidence,)))
    if discovery.primary_language and discovery.build_evidence is not None:
        fields.append(DiscoveredField("project.primary_language", (discovery.build_evidence,)))
    if discovery.license_name and discovery.license_evidence is not None:
        fields.append(DiscoveredField("project.license", (discovery.license_evidence,)))
    if not no_docs and discovery.canonical_docs:
        fields.append(DiscoveredField("canonical_docs", discovery.doc_evidence))
    if discovery.setup_command and discovery.build_evidence is not None:
        fields.append(DiscoveredField("build_and_test.setup", (discovery.build_evidence,)))
    if discovery.test_command and discovery.build_evidence is not None:
        fields.append(DiscoveredField("build_and_test.test", (discovery.build_evidence,)))
    return tuple(fields)


def _omitted_items(discovery: DiscoveryResult) -> tuple[ReviewItem, ...]:
    items = [
        ReviewItem(
            OMITTED_CONCEPTS,
            "core_concepts",
            "no core concepts were discovered",
            evidence_checked=discovery.canonical_docs,
        )
    ]
    if discovery.license_name is None:
        items.append(
            ReviewItem(OMITTED_LICENSE, "project.license", "no known license file was found")
        )
    items.append(
        ReviewItem(OMITTED_BENCHMARK, "build_and_test.benchmark", "no benchmark was configured")
    )
    return tuple(items)


def _review_items(discovery: DiscoveryResult, *, no_docs: bool) -> tuple[ReviewItem, ...]:
    items = [
        ReviewItem(
            REVIEW_PROJECT_STATUS_UNKNOWN,
            "project.status",
            "project status is unknown and must be set by the maintainer",
        ),
        ReviewItem(
            REVIEW_PURPOSE_MISSING,
            "purpose.one_sentence",
            "project purpose is unknown and must be authored",
        ),
        ReviewItem(
            REVIEW_GUARDRAILS_MISSING,
            "guardrails",
            "no guardrails were discovered; they must be authored",
        ),
    ]
    if discovery.build_commands_unknown:
        items.append(
            ReviewItem(
                REVIEW_BUILD_COMMANDS_UNKNOWN,
                "build_and_test",
                "package manager is ambiguous; setup and test commands were omitted",
            )
        )
    elif discovery.test_command is None:
        items.append(
            ReviewItem(
                REVIEW_TEST_COMMAND_MISSING,
                "build_and_test.test",
                "no unambiguous test command was detected",
            )
        )
    if no_docs:
        items.append(
            ReviewItem(
                REVIEW_CANONICAL_DOCS_MISSING,
                "canonical_docs",
                "no safe allowlisted entry document was found; nothing to record as canonical",
            )
        )
    return tuple(items)


def _refused_report(
    discovery: DiscoveryResult,
    *,
    manifest_path: str,
    review_code: str,
    reason: str,
    git_evidence: dict[str, Any] | None = None,
) -> InitReport:
    return InitReport(
        operation=OPERATION_REFUSED,
        manifest_path=manifest_path,
        would_write=False,
        written=False,
        replaced=False,
        discovered=_discovered_fields(discovery, no_docs=True),
        omitted=_omitted_items(discovery),
        review_required=_review_items(discovery, no_docs=True),
        security_findings=discovery.security_findings,
        git_evidence=git_evidence,
    )


def _write_manifest_atomic(target: Path, payload: bytes, *, limits: ResourceLimits) -> None:
    """Atomically replace *target* with *payload*, cleaning up temp files."""
    if len(payload) > limits.manifest_bytes:
        raise LimitError(
            LIMIT_MANIFEST_BYTES,
            f"resource limit exceeded: {LIMIT_MANIFEST_BYTES} "
            f"(limit={limits.manifest_bytes}, actual={len(payload)})",
            limit="manifest_bytes",
            limit_value=limits.manifest_bytes,
        )
    fd = -1
    tmp_path = ""
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
        tmp_path = ""
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


__all__ = [
    "CODE_UNSAFE_CANONICAL_PATH",
    "DEFAULT_MANIFEST_NAME",
    "OMITTED_BENCHMARK",
    "OMITTED_CONCEPTS",
    "OMITTED_LICENSE",
    "OPERATION_CREATE",
    "OPERATION_DRY_RUN",
    "OPERATION_REFUSED",
    "OPERATION_REPLACE",
    "OPERATIONS",
    "REFUSED_NO_CANONICAL_DOC",
    "REVIEW_BUILD_COMMANDS_UNKNOWN",
    "REVIEW_CANONICAL_DOCS_MISSING",
    "REVIEW_MANIFEST_EXISTS",
    "REVIEW_GUARDRAILS_MISSING",
    "REVIEW_PROJECT_STATUS_UNKNOWN",
    "REVIEW_PURPOSE_MISSING",
    "REVIEW_TEST_COMMAND_MISSING",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "DiscoveredField",
    "InitRefused",
    "InitReport",
    "ReviewItem",
    "init",
    "is_recognizable_manifest",
    "render_manifest_yaml",
    "resolve_output_path",
    "to_payload",
    "write_report",
]
