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

Every finding carries a stable, non-secret diagnostic ``code``. Warnings whose
code is in :data:`PUBLICATION_WARNING_CODES` block *publication* (strict
validation / export) unless explicitly acknowledged; ``error`` issues always
block serving and publication. See :mod:`beacon.core.policy`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from beacon.core.citation_digest import CitationUnavailable, digest_citation
from beacon.core.paths import (
    CODE_UNSAFE_CANONICAL_PATH,
    UnsafeCanonicalPath,
    is_unsafe_path,
    resolve_canonical_path,
)
from beacon.core.schema import (
    ANSWER_STATUSES,  # noqa: F401  (re-exported convenience)
    KNOWLEDGE_STATUSES,
    BeaconManifest,
    BeaconSource,
)

# ---------------------------------------------------------------------------
# Stable diagnostic codes (never include document content or secret values)
# ---------------------------------------------------------------------------

CODE_PROJECT_NAME_MISSING = "project_name_missing"
CODE_PROJECT_DESCRIPTION_MISSING = "project_description_missing"
CODE_BEACON_VERSION_MISSING = "beacon_version_missing"
CODE_CANONICAL_DOCS_MISSING = "canonical_docs_missing"
CODE_CANONICAL_DOC_DUPLICATE = "canonical_doc_duplicate"
CODE_CANONICAL_DOC_MISSING_FILE = "canonical_doc_missing_file"
CODE_CONCEPT_ID_DUPLICATE = "concept_id_duplicate"
CODE_CONCEPT_DEFINITION_MISSING = "concept_definition_missing"
CODE_RELATED_CONCEPT_UNKNOWN = "related_concept_unknown"
CODE_GUARDRAIL_ID_DUPLICATE = "guardrail_id_duplicate"
CODE_GUARDRAIL_SEVERITY_INVALID = "guardrail_severity_invalid"
CODE_GUARDRAILS_MISSING = "guardrails_missing"
CODE_TEST_COMMAND_MISSING = "test_command_missing"
CODE_KNOWLEDGE_STATUS_INVALID = "knowledge_status_invalid"
CODE_PROJECT_STATUS_UNKNOWN = "project_status_unknown"
CODE_PURPOSE_MISSING = "purpose_missing"
CODE_PROJECT_STATE_TITLE_MISSING = "project_state_title_missing"
CODE_PROJECT_STATE_SOURCES_MISSING = "project_state_sources_missing"
CODE_LEGACY_ISSUE = "legacy_issue"
CODE_DECISION_ID_DUPLICATE = "decision_id_duplicate"
#: A decision's ADR file must be a canonical doc, so the serving policy governs both.
CODE_DECISION_DOC_UNLISTED = "decision_doc_unlisted"
#: A pinned citation's text changed after the claim was written.
CODE_SOURCE_CHANGED = "source_changed"
#: A pinned citation can no longer be read (file gone or line range out of bounds).
CODE_SOURCE_UNAVAILABLE = "source_unavailable"

#: Every code the validator can emit. Used to tell an unknown acknowledgement
#: code (never a real finding) from a known-but-unallowlisted one.
VALIDATION_CODES = frozenset(
    {
        CODE_PROJECT_NAME_MISSING,
        CODE_PROJECT_DESCRIPTION_MISSING,
        CODE_BEACON_VERSION_MISSING,
        CODE_CANONICAL_DOCS_MISSING,
        CODE_CANONICAL_DOC_DUPLICATE,
        CODE_CANONICAL_DOC_MISSING_FILE,
        CODE_UNSAFE_CANONICAL_PATH,
        CODE_CONCEPT_ID_DUPLICATE,
        CODE_CONCEPT_DEFINITION_MISSING,
        CODE_RELATED_CONCEPT_UNKNOWN,
        CODE_GUARDRAIL_ID_DUPLICATE,
        CODE_GUARDRAIL_SEVERITY_INVALID,
        CODE_GUARDRAILS_MISSING,
        CODE_TEST_COMMAND_MISSING,
        CODE_KNOWLEDGE_STATUS_INVALID,
        CODE_PROJECT_STATUS_UNKNOWN,
        CODE_PURPOSE_MISSING,
        CODE_PROJECT_STATE_TITLE_MISSING,
        CODE_PROJECT_STATE_SOURCES_MISSING,
        CODE_LEGACY_ISSUE,
        CODE_SOURCE_CHANGED,
        CODE_SOURCE_UNAVAILABLE,
    }
)

#: Warnings that block *publication* (strict validation / export) unless
#: explicitly acknowledged. Exactly the codes listed in the addendum §5.
PUBLICATION_WARNING_CODES = frozenset(
    {
        CODE_PROJECT_STATUS_UNKNOWN,
        CODE_PURPOSE_MISSING,
        CODE_TEST_COMMAND_MISSING,
        CODE_GUARDRAILS_MISSING,
        CODE_CONCEPT_DEFINITION_MISSING,
        CODE_RELATED_CONCEPT_UNKNOWN,
        CODE_KNOWLEDGE_STATUS_INVALID,
        CODE_CANONICAL_DOC_DUPLICATE,
        CODE_PROJECT_STATE_SOURCES_MISSING,
    }
)


@dataclass(frozen=True)
class ValidationIssue:
    severity: str  # "error" | "warning"
    where: str
    message: str
    # Keep the three legacy positional fields first. External callers that
    # constructed ValidationIssue(severity, where, message) remain compatible,
    # while validator-generated findings always pass a specific stable code.
    code: str = CODE_LEGACY_ISSUE

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
    intent: bool = False,
) -> ValidationReport:
    """Validate *manifest*, optionally resolving doc paths against *docs_root*.

    When *docs_root* is provided, each canonical doc path is checked for
    existence (a dangling canonical doc is an error) and every pinned citation
    digest is recomputed (a mismatch is a ``source_changed`` warning). When it is
    ``None``, path existence and digests are skipped but every other check runs.

    ``intent=True`` validates a ``beacon.yaml`` overlay rather than a publishable
    manifest: name, description and canonical docs may be absent because
    ``beacon build`` derives them from the repository.
    """
    issues: list[ValidationIssue] = []
    root = Path(docs_root) if docs_root is not None else None

    # --- identity -----------------------------------------------------------
    if not manifest.project.name.strip() and not intent:
        issues.append(
            ValidationIssue("error", "project.name", "is required", CODE_PROJECT_NAME_MISSING)
        )
    if not manifest.project.description.strip() and not intent:
        issues.append(
            ValidationIssue(
                "error",
                "project.description",
                "is required",
                CODE_PROJECT_DESCRIPTION_MISSING,
            )
        )
    if not manifest.beacon_version.strip():
        issues.append(
            ValidationIssue("error", "beacon_version", "is required", CODE_BEACON_VERSION_MISSING)
        )
    # publication warning: project.status is the controlled "unknown" vocabulary
    if manifest.project.status.strip().lower() == "unknown":
        issues.append(
            ValidationIssue(
                "warning",
                "project.status",
                "is 'unknown'",
                CODE_PROJECT_STATUS_UNKNOWN,
            )
        )
    _check_status(issues, "project.status", manifest.project.status)
    # publication warning: no stated purpose
    if not manifest.purpose.one_sentence.strip():
        issues.append(
            ValidationIssue(
                "warning",
                "purpose.one_sentence",
                "is required",
                CODE_PURPOSE_MISSING,
            )
        )

    # --- canonical docs -----------------------------------------------------
    if not manifest.canonical_docs and not intent:
        issues.append(
            ValidationIssue(
                "error", "canonical_docs", "at least one is required", CODE_CANONICAL_DOCS_MISSING
            )
        )
    seen_doc_paths: set[str] = set()
    for doc in manifest.canonical_docs:
        if doc.path in seen_doc_paths:
            issues.append(
                ValidationIssue(
                    "warning",
                    "canonical_docs",
                    "duplicate canonical path",
                    CODE_CANONICAL_DOC_DUPLICATE,
                )
            )
        seen_doc_paths.add(doc.path)
        _check_status(issues, f"canonical_docs[{doc.path}].status", doc.status)
        if is_unsafe_path(doc.path):
            # Unsafe regardless of whether a docs_root is provided: never
            # echo the offending path into the diagnostic.
            issues.append(
                ValidationIssue(
                    "error",
                    "canonical_docs[]",
                    "unsafe canonical path",
                    CODE_UNSAFE_CANONICAL_PATH,
                )
            )
        elif root is not None:
            try:
                target = resolve_canonical_path(root, doc.path)
            except UnsafeCanonicalPath:
                issues.append(
                    ValidationIssue(
                        "error",
                        "canonical_docs[]",
                        "unsafe canonical path",
                        CODE_UNSAFE_CANONICAL_PATH,
                    )
                )
            else:
                # ``Path.is_file`` only swallows ENOENT/ENOTDIR-class errors before
                # Python 3.14; a resolved path past the platform PATH_MAX (1024 on
                # macOS) raises ENAMETOOLONG from stat and escaped as an internal
                # error. Any OSError here means "no usable file at that path".
                try:
                    is_file = target.is_file()
                except OSError:
                    is_file = False
                if not is_file:
                    issues.append(
                        ValidationIssue(
                            "error",
                            f"canonical_docs[{doc.path}]",
                            f"path does not exist under docs_root {root}",
                            CODE_CANONICAL_DOC_MISSING_FILE,
                        )
                    )

    # --- concepts -----------------------------------------------------------
    concept_ids: set[str] = set()
    for concept in manifest.core_concepts:
        cid = concept.id.lower()
        if cid in concept_ids:
            issues.append(
                ValidationIssue(
                    "error",
                    "core_concepts",
                    f"duplicate concept id: {concept.id}",
                    CODE_CONCEPT_ID_DUPLICATE,
                )
            )
        concept_ids.add(cid)
        if not concept.definition.strip():
            issues.append(
                ValidationIssue(
                    "warning",
                    f"core_concepts[{concept.id}]",
                    "has no definition",
                    CODE_CONCEPT_DEFINITION_MISSING,
                )
            )
        _check_status(issues, f"core_concepts[{concept.id}].status", concept.status)
        for source in concept.sources:
            _check_status(issues, f"core_concepts[{concept.id}].sources[].status", source.status)
    # --- decisions (ADRs) ----------------------------------------------------
    decision_ids: set[str] = set()
    listed_docs = {doc.path for doc in manifest.canonical_docs}
    for decision in manifest.decisions:
        where = f"decisions[{decision.id}]"
        if decision.id.lower() in decision_ids:
            issues.append(
                ValidationIssue(
                    "error",
                    "decisions",
                    f"duplicate decision id: {decision.id}",
                    CODE_DECISION_ID_DUPLICATE,
                )
            )
        decision_ids.add(decision.id.lower())
        if decision.path not in listed_docs:
            issues.append(
                ValidationIssue(
                    "error",
                    where,
                    "its ADR file is not a canonical document",
                    CODE_DECISION_DOC_UNLISTED,
                )
            )
        _check_status(issues, f"{where}.status", decision.status)
        for source in decision.sources:
            _check_status(issues, f"{where}.sources[].status", source.status)
    # related-id references resolve against known concept ids
    for concept in manifest.core_concepts:
        for related in concept.related_concepts:
            if related.lower() not in concept_ids:
                issues.append(
                    ValidationIssue(
                        "warning",
                        f"core_concepts[{concept.id}].related_concepts",
                        f"references unknown concept id: {related}",
                        CODE_RELATED_CONCEPT_UNKNOWN,
                    )
                )

    # --- guardrails ---------------------------------------------------------
    guardrail_ids: set[str] = set()
    for guard in manifest.guardrails:
        gid = guard.id.lower()
        if gid in guardrail_ids:
            issues.append(
                ValidationIssue(
                    "error",
                    "guardrails",
                    f"duplicate guardrail id: {guard.id}",
                    CODE_GUARDRAIL_ID_DUPLICATE,
                )
            )
        guardrail_ids.add(gid)
        if guard.severity not in {"low", "medium", "high"}:
            issues.append(
                ValidationIssue(
                    "warning",
                    f"guardrails[{guard.id}].severity",
                    f"unknown severity: {guard.severity}",
                    CODE_GUARDRAIL_SEVERITY_INVALID,
                )
            )
        for source in guard.sources:
            _check_status(issues, f"guardrails[{guard.id}].sources[].status", source.status)
    # publication warning: no guardrail declared
    if not manifest.guardrails:
        issues.append(
            ValidationIssue(
                "warning",
                "guardrails",
                "no guardrail is declared",
                CODE_GUARDRAILS_MISSING,
            )
        )

    # --- build/test ---------------------------------------------------------
    if not manifest.build_and_test.test.strip() and not intent:
        issues.append(
            ValidationIssue(
                "warning",
                "build_and_test.test",
                "no test command declared",
                CODE_TEST_COMMAND_MISSING,
            )
        )

    # --- maintainer-declared project state --------------------------------
    state_groups = (
        (
            "active_work",
            ()
            if manifest.project_state.active_work is None
            else (manifest.project_state.active_work,),
        ),
        ("recently_completed", manifest.project_state.recently_completed),
        ("blockers", manifest.project_state.blockers),
        ("pending_decisions", manifest.project_state.pending_decisions),
    )
    for group, items in state_groups:
        for index, item in enumerate(items):
            where = f"project_state.{group}[{index}]"
            if not item.title.strip():
                issues.append(
                    ValidationIssue(
                        "error",
                        f"{where}.title",
                        "is required",
                        CODE_PROJECT_STATE_TITLE_MISSING,
                    )
                )
            if not item.sources:
                issues.append(
                    ValidationIssue(
                        "warning",
                        f"{where}.sources",
                        "has no source citation",
                        CODE_PROJECT_STATE_SOURCES_MISSING,
                    )
                )
            for source in item.sources:
                _check_status(issues, f"{where}.sources[].status", source.status)

    if root is not None:
        _check_digests(issues, manifest, root)

    return ValidationReport(tuple(issues))


def _pinned_sources(manifest: BeaconManifest) -> list[tuple[str, BeaconSource]]:
    """Every citation in *manifest* that carries a digest, with where it sits."""
    found: list[tuple[str, BeaconSource]] = []
    for concept in manifest.core_concepts:
        found.extend((f"core_concepts[{concept.id}].sources[]", s) for s in concept.sources)
    for guard in manifest.guardrails:
        found.extend((f"guardrails[{guard.id}].sources[]", s) for s in guard.sources)
    for decision in manifest.decisions:
        found.extend((f"decisions[{decision.id}].sources[]", s) for s in decision.sources)
    state = manifest.project_state
    groups = (
        ("active_work", () if state.active_work is None else (state.active_work,)),
        ("recently_completed", state.recently_completed),
        ("blockers", state.blockers),
        ("pending_decisions", state.pending_decisions),
    )
    for group, items in groups:
        for index, item in enumerate(items):
            found.extend((f"project_state.{group}[{index}].sources[]", s) for s in item.sources)
    return [(where, source) for where, source in found if source.digest and source.path]


def _check_digests(issues: list[ValidationIssue], manifest: BeaconManifest, root: Path) -> None:
    for where, source in _pinned_sources(manifest):
        try:
            current = digest_citation(root, source.path, source.line_start, source.line_end)
        except CitationUnavailable:
            issues.append(
                ValidationIssue(
                    "warning",
                    where,
                    f"pinned citation cannot be read: {source.path}",
                    CODE_SOURCE_UNAVAILABLE,
                )
            )
            continue
        if current != source.digest:
            issues.append(
                ValidationIssue(
                    "warning",
                    where,
                    f"cited text changed since it was pinned: {source.path}; review the claim",
                    CODE_SOURCE_CHANGED,
                )
            )


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
                CODE_KNOWLEDGE_STATUS_INVALID,
            )
        )
