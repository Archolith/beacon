"""Authority resolution for the v0.3 build: intent, reality, history.

The merge policy (build-pipeline plan §4) assigns each fact exactly one
authority:

* **Intent** -- the hand-authored manifest, when one is supplied. What
  *should* be true: purpose, guardrails, non-goals, focus, commands.
* **Reality** -- the repository (git adapter, filesystem existence checks).
  What *is* true: which files and documents actually exist.
* **History** -- Menhir evidence. What was *decided* and what is indexed
  about the project: identity, structure, documents, decision outcomes.

Three consequences implemented here:

1. A source may not answer outside its authority: git and Menhir never
   invent guardrails or purpose; the intent manifest cannot assert a
   document exists that the filesystem says does not (that is an error,
   not a tie to break).
2. Divergence is a finding: an indexed document missing on disk or a
   decision location that no longer resolves becomes a
   :class:`DriftRecord` and the affected claim is omitted.
3. Ambiguity fails closed: an unresolvable required field (no identity, no
   description, no surviving canonical docs) raises :class:`BuildError`
   with a stable code. Nothing is synthesized to fill a schema field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from beacon.core.paths import resolve_canonical_path
from beacon.core.schema import BeaconManifest
from beacon.sources.base import (
    KIND_GIT_HEAD,
    KIND_MENHIR_DECISION,
    KIND_MENHIR_DOCUMENT,
    KIND_MENHIR_IDENTITY,
    KIND_MENHIR_STRUCTURE,
    NormalizedRecord,
)

#: Stable build-failure codes (never carry content or paths).
BUILD_IDENTITY_UNRESOLVED = "build_identity_unresolved"
BUILD_DESCRIPTION_UNRESOLVED = "build_description_unresolved"
BUILD_NO_CANONICAL_DOCS = "build_no_canonical_docs"
BUILD_INTENT_DOC_MISSING = "build_intent_doc_missing"
BUILD_IDENTITY_ROOT_MISMATCH = "build_identity_root_mismatch"

#: How many of the resolved canonical docs become the read-first order.
_READ_FIRST_LIMIT = 3
#: Maximum decision concepts and implementation locations per concept.
_MAX_DECISIONS = 32
_MAX_LOCATIONS = 8


class BuildError(ValueError):
    """The build cannot resolve its inputs; it fails closed.

    ``code`` is a stable, non-secret diagnostic string.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class DriftRecord:
    """One divergence between an indexed claim and repository reality."""

    code: str
    detail: str
    citation: str


@dataclass(frozen=True)
class DecisionFact:
    """One Menhir-indexed decision, projected with its locations resolved."""

    title: str
    summary: str
    status: str
    locations: tuple[str, ...]


@dataclass(frozen=True)
class MergedProjectFacts:
    """The resolved, evidence-backed facts the projection consumes.

    Every value carries the authority that supplied it so the projection
    (and the build report) can state where each claim came from.
    """

    name: str
    name_authority: str
    description: str
    description_authority: str
    primary_language: str
    primary_language_authority: str
    repository: str
    repository_authority: str
    status: str
    status_authority: str
    canonical_docs: tuple[dict[str, str], ...]
    canonical_docs_authority: str
    structure_summary: str | None
    structure_fingerprint: str | None
    git_head: str | None
    decisions: tuple[DecisionFact, ...]
    guardrails: tuple[dict[str, object], ...]
    purpose_problem: str
    non_goals: tuple[str, ...]
    current_focus: tuple[str, ...]
    read_first: tuple[str, ...]
    build_and_test: dict[str, str]
    audiences: tuple[str, ...]
    drift: tuple[DriftRecord, ...] = field(default_factory=tuple)
    #: ``"intent"`` when the intent manifest names audiences, else ``""``
    #: (no source: the field is published empty, never defaulted).
    audiences_authority: str = ""


def _doc_exists(docs_root: Path, path: str) -> bool:
    try:
        return resolve_canonical_path(docs_root, path).is_file()
    except Exception:  # noqa: BLE001 - any resolution failure means "not usable"
        return False


def _first_record(records: tuple[NormalizedRecord, ...], kind: str) -> NormalizedRecord | None:
    for record in records:
        if record.kind == kind:
            return record
    return None


def resolve_project_facts(
    *,
    intent: BeaconManifest | None,
    git_records: tuple[NormalizedRecord, ...],
    menhir_records: tuple[NormalizedRecord, ...],
    docs_root: Path,
    repo_root: Path | None = None,
    git_origin: str | None = None,
) -> MergedProjectFacts:
    """Resolve merged records into the facts the projection consumes.

    ``intent`` is the (optional) hand-authored manifest. ``docs_root`` is the
    directory the built manifest will live in; canonical doc paths resolve
    against it. ``repo_root`` enables the Menhir-indexed-root cross-check.
    ``git_origin`` is the adapter's already-sanitized repository URL (the
    :meth:`GitSourceAdapter.repository_url` capability, applied by the CLI
    layer). Raises :class:`BuildError` when a required fact cannot be
    resolved.
    """
    drift: list[DriftRecord] = []

    identity = _first_record(menhir_records, KIND_MENHIR_IDENTITY)
    if repo_root is not None and identity is not None:
        indexed_root = str(identity.payload.get("root") or "")
        if indexed_root:
            try:
                if Path(indexed_root).resolve() != repo_root.resolve():
                    raise BuildError(
                        BUILD_IDENTITY_ROOT_MISMATCH,
                        "indexed project root does not match the requested repository",
                    )
            except OSError as exc:
                raise BuildError(
                    BUILD_IDENTITY_ROOT_MISMATCH,
                    "indexed project root could not be resolved",
                ) from exc

    # -- identity ------------------------------------------------------------
    name = ""
    name_authority = ""
    if intent is not None and intent.project.name.strip():
        name, name_authority = intent.project.name.strip(), "intent"
    elif identity is not None:
        name, name_authority = str(identity.payload.get("name") or ""), "menhir"
    if not name:
        raise BuildError(
            BUILD_IDENTITY_UNRESOLVED,
            "no project name from intent manifest or Menhir evidence; refusing to invent one",
        )

    description = ""
    description_authority = ""
    if intent is not None and (
        intent.purpose.one_sentence.strip() or intent.project.description.strip()
    ):
        description = intent.purpose.one_sentence.strip() or intent.project.description.strip()
        description_authority = "intent"
    elif identity is not None and str(identity.payload.get("description") or "").strip():
        description = str(identity.payload.get("description") or "").strip()
        description_authority = "menhir"
    if not description:
        raise BuildError(
            BUILD_DESCRIPTION_UNRESOLVED,
            "no project description from intent manifest or Menhir evidence; refusing to invent one",
        )

    primary_language = ""
    primary_language_authority = ""
    if intent is not None and intent.project.primary_language.strip():
        primary_language, primary_language_authority = (
            intent.project.primary_language.strip(),
            "intent",
        )
    elif identity is not None and str(identity.payload.get("primary_language") or "").strip():
        primary_language = str(identity.payload.get("primary_language") or "").strip()
        primary_language_authority = "menhir"

    repository = ""
    repository_authority = ""
    if intent is not None and intent.project.repository.strip():
        repository, repository_authority = intent.project.repository.strip(), "intent"
    elif git_origin:
        repository, repository_authority = git_origin, "git"

    # project.status is always published (the manifest schema defaults it),
    # so an absent source falls back to Beacon's own default -- reported as
    # authority "default", never attributed to a source that did not say it.
    status = "experimental"
    status_authority = "default"
    if intent is not None and intent.project.status.strip():
        status, status_authority = intent.project.status.strip(), "intent"
    elif identity is not None and str(identity.payload.get("status") or "").strip():
        status = str(identity.payload.get("status") or "").strip()
        status_authority = "menhir"

    # -- canonical docs (intent asserts; Menhir cites; the filesystem decides) --
    docs: list[dict[str, str]] = []
    seen: set[str] = set()
    if intent is not None:
        for doc in intent.canonical_docs:
            if not _doc_exists(docs_root, doc.path):
                raise BuildError(
                    BUILD_INTENT_DOC_MISSING,
                    "intent manifest cites a canonical document missing on disk",
                )
            if doc.path not in seen:
                seen.add(doc.path)
                docs.append({"path": doc.path, "role": doc.role, "title": doc.title})
    menhir_docs = sorted(
        (r for r in menhir_records if r.kind == KIND_MENHIR_DOCUMENT),
        key=lambda r: str(r.payload.get("path") or ""),
    )
    for record in menhir_docs:
        path = str(record.payload.get("path") or "")
        if not path or path in seen:
            continue
        if not _doc_exists(docs_root, path):
            drift.append(
                DriftRecord(
                    code="doc_path_missing",
                    detail="indexed canonical document does not exist on disk; omitted",
                    citation=path,
                )
            )
            continue
        seen.add(path)
        docs.append(
            {
                "path": path,
                "role": str(record.payload.get("document_type") or "reference"),
                "title": str(record.payload.get("title") or path),
            }
        )
    docs_authority = (
        "intent+menhir"
        if intent is not None and menhir_docs
        else ("intent" if intent is not None else "menhir")
    )
    if not docs:
        raise BuildError(
            BUILD_NO_CANONICAL_DOCS,
            "no canonical document survived the reality check; refusing to publish an empty beacon",
        )

    # -- structure concept (Menhir structure + git inventory summary) ---------
    structure_summary: str | None = None
    structure_fingerprint: str | None = None
    structure = _first_record(menhir_records, KIND_MENHIR_STRUCTURE)
    if structure is not None:
        entities = cast(dict[str, int], structure.payload.get("entities") or {})
        edges = cast(dict[str, int], structure.payload.get("edges") or {})
        parts = [f"{role}: {count}" for role, count in sorted(entities.items()) if count]
        edge_parts = [f"{rel}: {count}" for rel, count in sorted(edges.items()) if count]
        structure_summary = (
            "Indexed repository structure as of the latest Menhir scan: "
            + "; ".join(parts + edge_parts)
        ).strip()
        structure_fingerprint = str(structure.payload.get("scan_fingerprint") or "") or None

    # -- decisions (history) with location reality checks ---------------------
    decisions: list[DecisionFact] = []
    # Sorted on the full record content so the order -- and therefore the
    # id suffix a colliding title receives -- never depends on input order.
    decision_records = sorted(
        (r for r in menhir_records if r.kind == KIND_MENHIR_DECISION),
        key=lambda r: (
            str(r.payload.get("title") or ""),
            str(r.payload.get("summary") or ""),
            str(r.payload.get("status") or ""),
            tuple(
                str(item)
                for item in cast(list[object], r.payload.get("implementation_locations") or [])
            ),
        ),
    )
    for record in decision_records[:_MAX_DECISIONS]:
        raw_locations = cast(list[object], record.payload.get("implementation_locations") or [])
        locations = [str(item) for item in raw_locations if str(item)]
        resolved: list[str] = []
        for location in locations:
            if _doc_exists(docs_root, location):
                resolved.append(location)
            else:
                drift.append(
                    DriftRecord(
                        code="decision_location_missing",
                        detail="decision implementation location does not exist on disk; omitted",
                        citation=location,
                    )
                )
        decisions.append(
            DecisionFact(
                title=str(record.payload.get("title") or ""),
                summary=str(record.payload.get("summary") or ""),
                status=str(record.payload.get("status") or "current"),
                locations=tuple(resolved[:_MAX_LOCATIONS]),
            )
        )

    # -- intent-only facts -----------------------------------------------------
    guardrails: list[dict[str, object]] = []
    purpose_problem = intent.purpose.problem if intent is not None else ""
    non_goals = intent.purpose.non_goals if intent is not None else ()
    current_focus = intent.current_focus if intent is not None else ()
    audiences = intent.audiences if intent is not None else ()
    build_and_test = (
        {
            "setup": intent.build_and_test.setup,
            "test": intent.build_and_test.test,
            "benchmark": intent.build_and_test.benchmark,
        }
        if intent is not None
        else {"setup": "", "test": "", "benchmark": ""}
    )
    if intent is not None:
        guardrails = [
            {
                "id": guard.id,
                "rule": guard.rule,
                "scope": guard.scope,
                "severity": guard.severity,
                "applies_to": list(guard.applies_to),
                "sources": [
                    {
                        "type": source.type,
                        "title": source.title,
                        "path": source.path,
                        "url": source.url,
                        "line_start": source.line_start,
                        "line_end": source.line_end,
                        "status": source.status,
                    }
                    for source in guard.sources
                ],
            }
            for guard in intent.guardrails
        ]

    git_head: str | None = None
    head = _first_record(git_records, KIND_GIT_HEAD)
    if head is not None:
        git_head = str(head.payload.get("commit") or "") or None

    read_first = tuple(doc["path"] for doc in docs[:_READ_FIRST_LIMIT])

    return MergedProjectFacts(
        name=name,
        name_authority=name_authority,
        description=description,
        description_authority=description_authority,
        primary_language=primary_language,
        primary_language_authority=primary_language_authority,
        repository=repository,
        repository_authority=repository_authority,
        status=status,
        status_authority=status_authority,
        canonical_docs=tuple(docs),
        canonical_docs_authority=docs_authority,
        structure_summary=structure_summary,
        structure_fingerprint=structure_fingerprint,
        git_head=git_head,
        decisions=tuple(decisions),
        guardrails=tuple(guardrails),
        purpose_problem=purpose_problem,
        non_goals=tuple(non_goals),
        current_focus=tuple(current_focus),
        read_first=read_first,
        build_and_test=build_and_test,
        audiences=tuple(audiences),
        drift=tuple(drift),
        audiences_authority="intent" if audiences else "",
    )


__all__ = [
    "BUILD_DESCRIPTION_UNRESOLVED",
    "BUILD_IDENTITY_ROOT_MISMATCH",
    "BUILD_IDENTITY_UNRESOLVED",
    "BUILD_INTENT_DOC_MISSING",
    "BUILD_NO_CANONICAL_DOCS",
    "BuildError",
    "DecisionFact",
    "DriftRecord",
    "MergedProjectFacts",
    "resolve_project_facts",
]
