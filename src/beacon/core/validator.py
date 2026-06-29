"""Semantic validation for a parsed :class:`BeaconManifest`.

The loader guarantees a structurally well-formed manifest; the validator checks
that it is *useful and honest*: it has identity, points at docs that actually
exist, uses no duplicate concept ids, declares how to build/test, and only uses
known status vocabulary.

Two severities:

* ``error``  -- the manifest should not be served (missing identity, dangling
  canonical docs, duplicate ids).
* ``warning`` -- servable but incomplete (no build/test commands, unknown
  status label, concept referencing an unknown related id).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from beacon.core.schema import (
    ANSWER_STATUSES,  # noqa: F401  (re-exported convenience)
    KNOWLEDGE_STATUSES,
    BeaconManifest,
)


@dataclass(frozen=True)
class ValidationIssue:
    severity: str  # "error" | "warning"
    where: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"[{self.severity}] {self.where}: {self.message}"


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

    @property
    def ok(self) -> bool:
        """True when there are no error-level issues."""
        return not self.errors


class ManifestValidationError(ValueError):
    """Raised by :func:`require_valid_manifest` when errors are present."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        joined = "; ".join(str(i) for i in report.errors)
        super().__init__(f"invalid beacon manifest: {joined}")


def validate_beacon_manifest(
    manifest: BeaconManifest,
    *,
    docs_root: str | Path | None = None,
) -> ValidationReport:
    """Validate *manifest*, optionally resolving doc paths against *docs_root*.

    When *docs_root* is provided, each canonical doc path is checked for
    existence (a dangling canonical doc is an error). When it is ``None``, path
    existence is skipped but every other check still runs.
    """
    issues: list[ValidationIssue] = []
    root = Path(docs_root) if docs_root is not None else None

    # --- identity -----------------------------------------------------------
    if not manifest.project.name.strip():
        issues.append(ValidationIssue("error", "project.name", "is required"))
    if not manifest.project.description.strip():
        issues.append(
            ValidationIssue("error", "project.description", "is required")
        )
    if not manifest.beacon_version.strip():
        issues.append(ValidationIssue("error", "beacon_version", "is required"))

    # --- canonical docs -----------------------------------------------------
    if not manifest.canonical_docs:
        issues.append(
            ValidationIssue("error", "canonical_docs", "at least one is required")
        )
    seen_doc_paths: set[str] = set()
    for doc in manifest.canonical_docs:
        if doc.path in seen_doc_paths:
            issues.append(
                ValidationIssue("warning", "canonical_docs", f"duplicate path: {doc.path}")
            )
        seen_doc_paths.add(doc.path)
        _check_status(issues, f"canonical_docs[{doc.path}].status", doc.status)
        if root is not None and not (root / doc.path).exists():
            issues.append(
                ValidationIssue(
                    "error",
                    f"canonical_docs[{doc.path}]",
                    f"path does not exist under docs_root {root}",
                )
            )

    # --- concepts -----------------------------------------------------------
    concept_ids: set[str] = set()
    for concept in manifest.core_concepts:
        cid = concept.id.lower()
        if cid in concept_ids:
            issues.append(
                ValidationIssue("error", "core_concepts", f"duplicate concept id: {concept.id}")
            )
        concept_ids.add(cid)
        if not concept.definition.strip():
            issues.append(
                ValidationIssue(
                    "warning", f"core_concepts[{concept.id}]", "has no definition"
                )
            )
        _check_status(issues, f"core_concepts[{concept.id}].status", concept.status)
    # related-id references resolve against known concept ids
    for concept in manifest.core_concepts:
        for related in concept.related_concepts:
            if related.lower() not in concept_ids:
                issues.append(
                    ValidationIssue(
                        "warning",
                        f"core_concepts[{concept.id}].related_concepts",
                        f"references unknown concept id: {related}",
                    )
                )

    # --- guardrails ---------------------------------------------------------
    guardrail_ids: set[str] = set()
    for guard in manifest.guardrails:
        gid = guard.id.lower()
        if gid in guardrail_ids:
            issues.append(
                ValidationIssue("error", "guardrails", f"duplicate guardrail id: {guard.id}")
            )
        guardrail_ids.add(gid)
        if guard.severity not in {"low", "medium", "high"}:
            issues.append(
                ValidationIssue(
                    "warning",
                    f"guardrails[{guard.id}].severity",
                    f"unknown severity: {guard.severity}",
                )
            )

    # --- build/test ---------------------------------------------------------
    if not manifest.build_and_test.test.strip():
        issues.append(
            ValidationIssue("warning", "build_and_test.test", "no test command declared")
        )

    return ValidationReport(tuple(issues))


def require_valid_manifest(
    manifest: BeaconManifest,
    *,
    docs_root: str | Path | None = None,
) -> ValidationReport:
    """Validate and raise :class:`ManifestValidationError` on any error.

    Returns the report (with any warnings) when there are no errors. Used at
    server startup so an unservable manifest fails loudly.
    """
    report = validate_beacon_manifest(manifest, docs_root=docs_root)
    if not report.ok:
        raise ManifestValidationError(report)
    return report


def _check_status(issues: list[ValidationIssue], where: str, status: str) -> None:
    if status not in KNOWLEDGE_STATUSES:
        issues.append(
            ValidationIssue(
                "warning",
                where,
                f"unknown status '{status}' (expected one of {sorted(KNOWLEDGE_STATUSES)})",
            )
        )
