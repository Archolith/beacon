"""Authority resolution for the v0.3 build: intent, reality, history.

The merge policy (build-pipeline plan §4) assigns each fact exactly one
authority:

* **Intent** -- the hand-authored manifest, when one is supplied. What
  *should* be true: purpose, guardrails, non-goals, focus, commands, and
  the maintainer-authored concepts, agent guidance, tagline, license,
  audiences, project state, and document currentness (carried verbatim).
* **Reality** -- the repository (git adapter, filesystem existence checks).
  What *is* true: which files and documents actually exist.
* **History** -- memory-provider evidence. What was *decided* and what is indexed
  about the project: identity, structure, documents, decision outcomes.
* **Declared** -- other files the project wrote (package manifests, the license
  file, CI workflows, the README lead, entry documents), read at every build
  (:mod:`beacon.sources.declared`). ``inferred`` marks the heuristic guesses
  that source makes (a conventional command, a license named only by filename).

Precedence: for judgment (name, purpose, description, commands to recommend)
intent wins and declared fills what intent leaves empty. For facts about the
code the checkout wins: a license the project's files state overrides a
different license in intent, and the contradiction is reported as drift.

Three consequences implemented here:

1. A source may not answer outside its authority: git and memory never
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

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

from beacon.core.paths import resolve_canonical_path
from beacon.core.schema import BeaconManifest
from beacon.sources.base import (
    KIND_GIT_HEAD,
    KIND_GIT_TAG,
    KIND_MEMORY_DECISION,
    KIND_MEMORY_DOCUMENT,
    KIND_MEMORY_IDENTITY,
    KIND_MEMORY_STRUCTURE,
    NormalizedRecord,
)
from beacon.sources.conventions import ConventionFacts, read_frontmatter
from beacon.sources.declared import DeclaredFacts, DeclaredValue

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
#: Most recent git tags published as recently completed work.
_MAX_RECENT_RELEASES = 5


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
    """One memory-indexed decision, projected with its locations resolved."""

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
    #: Intent-authored fields carried through verbatim (maintainer authority).
    #: Empty when no intent manifest is supplied, so an evidence-only build is
    #: unchanged by them.
    project_description: str = ""
    tagline: str = ""
    license: str = ""
    intent_concepts: tuple[dict[str, Any], ...] = ()
    agent_guidance: dict[str, tuple[str, ...]] = field(default_factory=dict)
    project_state: dict[str, Any] | None = None
    #: ``purpose.one_sentence`` exactly as the maintainers wrote it ("" if unstated).
    stated_purpose: str = ""
    #: Catalogue field -> the authority label that supplied it ("" = nothing did).
    #: Labels: intent, git, memory, derived, default; "+"-joined when several did.
    field_authority: dict[str, str] = field(default_factory=dict)
    #: Fields whose published value is a placeholder rather than an answer: a
    #: schema default, `beacon init`'s "unknown", or a description standing in
    #: for a purpose the maintainers never stated. Still reported as gaps.
    field_placeholder: frozenset[str] = frozenset()
    #: Catalogue field -> "path" or "path:line" of the project file a declared or
    #: inferred value was read from (reported by the build, not published).
    field_citations: dict[str, str] = field(default_factory=dict)
    #: Catalogue fields answered by explicit ``<!-- beacon:... -->`` markers (exact) ...
    marked_fields: frozenset[str] = frozenset()
    #: ... and by conventions (headings, CODEOWNERS, glossary, nav): usable, less exact.
    convention_fields: frozenset[str] = frozenset()


def _plain(value: Any) -> Any:
    """Return *value* as plain YAML data: tuples as lists, ``None`` entries dropped.

    Mirrors the loader's "absent key" convention so a round-tripped intent
    section parses exactly as the maintainer wrote it.
    """
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items() if item is not None}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _intent_project_state(intent: BeaconManifest) -> dict[str, Any] | None:
    state = intent.project_state
    if state.active_work is None and not (
        state.recently_completed or state.blockers or state.pending_decisions
    ):
        return None
    return cast(dict[str, Any], _plain(asdict(state)))


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
    memory_records: tuple[NormalizedRecord, ...] = (),
    docs_root: Path,
    repo_root: Path | None = None,
    git_origin: str | None = None,
    strict: bool = True,
    menhir_records: tuple[NormalizedRecord, ...] | None = None,
    declared: DeclaredFacts | None = None,
) -> MergedProjectFacts:
    """Resolve merged records into the facts the projection consumes.

    ``intent`` is the (optional) hand-authored manifest. ``docs_root`` is the
    directory the built manifest will live in; canonical doc paths resolve
    against it. ``repo_root`` enables the memory-indexed-root cross-check.
    ``git_origin`` is the adapter's already-sanitized repository URL (the
    :meth:`GitSourceAdapter.repository_url` capability, applied by the CLI
    layer). Raises :class:`BuildError` when a required fact cannot be
    resolved. ``strict=False`` is for the non-publishing gap report only: an
    unresolved name, description or canonical-doc set is left empty instead
    of refusing (errors such as a root mismatch or a missing intent doc still
    raise). Facts from a non-strict call must never be projected.
    ``declared`` is what the project's own files state (see the module docstring
    for precedence).
    """
    if menhir_records is not None:  # deprecated keyword, one release
        memory_records = menhir_records
    drift: list[DriftRecord] = []
    citations: dict[str, str] = {}
    conventions = declared.conventions if declared is not None else ConventionFacts()

    def _take(value: DeclaredValue | None, *fields: str) -> tuple[str, str]:
        if value is None or not value.value.strip():
            return "", ""
        where = value.path if value.line is None else f"{value.path}:{value.line}"
        for field_name in fields:
            citations[field_name] = where
        return value.value.strip(), value.tier

    identity = _first_record(memory_records, KIND_MEMORY_IDENTITY)
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
    if not name and declared is not None:
        name, name_authority = _take(declared.name, "project.name")
    if not name and identity is not None:
        name, name_authority = str(identity.payload.get("name") or ""), "memory"
    if not name and git_origin:
        tail = git_origin.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        if tail:
            name, name_authority = tail, "git"
    if not name and repo_root is not None and repo_root.name:
        # Last resort, a guess: the checkout's directory name.
        name, name_authority = repo_root.resolve().name, "inferred"
        citations["project.name"] = "."
    if not name and strict:
        raise BuildError(
            BUILD_IDENTITY_UNRESOLVED,
            "no project name from intent, the project's files, memory evidence or git; "
            "refusing to invent one",
        )

    description = ""
    description_authority = ""
    if intent is not None and (
        intent.purpose.one_sentence.strip() or intent.project.description.strip()
    ):
        description = intent.purpose.one_sentence.strip() or intent.project.description.strip()
        description_authority = "intent"
    if not description and conventions.purpose:
        # A purpose the maintainers marked in their own docs: their words, exactly.
        description, description_authority = conventions.purpose, "declared"
        source = conventions.purpose_source or {}
        citations["purpose.one_sentence"] = (
            f"{source.get('path', '')}:{source.get('line_start', '')}"
        )
    if not description and declared is not None:
        description, description_authority = _take(
            declared.description, "project.description", "purpose.one_sentence"
        )
    if (
        not description
        and identity is not None
        and str(identity.payload.get("description") or "").strip()
    ):
        description = str(identity.payload.get("description") or "").strip()
        description_authority = "memory"
    if not description and strict:
        raise BuildError(
            BUILD_DESCRIPTION_UNRESOLVED,
            "no project description from intent, the project's files or memory evidence; "
            "refusing to invent one",
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
        primary_language_authority = "memory"
    if not primary_language and declared is not None:
        primary_language, primary_language_authority = _take(
            declared.primary_language, "project.primary_language"
        )

    repository = ""
    repository_authority = ""
    if intent is not None and intent.project.repository.strip():
        repository, repository_authority = intent.project.repository.strip(), "intent"
    elif git_origin:
        repository, repository_authority = git_origin, "git"

    # project.status is always published (the manifest schema defaults it),
    # so an absent source falls back to Beacon's own default -- reported as
    # authority "default", never attributed to a source that did not say it.
    status = "unknown"
    status_authority = "default"
    intent_status = intent.project.status.strip() if intent is not None else ""
    if intent_status and not (intent_status.lower() == "unknown" and identity is not None):
        # An explicit "unknown" (what `beacon init` writes) yields to a source that knows.
        status, status_authority = intent_status, "intent"
    elif identity is not None and str(identity.payload.get("status") or "").strip():
        status = str(identity.payload.get("status") or "").strip()
        status_authority = "memory"
    if status_authority == "default" and intent_status:
        status, status_authority = intent_status, "intent"

    # -- canonical docs (intent asserts; memory cites; the filesystem decides) --
    docs: list[dict[str, str]] = []
    seen: set[str] = set()
    intent_doc_count = 0
    memory_doc_count = 0
    if intent is not None:
        for doc in intent.canonical_docs:
            if not _doc_exists(docs_root, doc.path):
                raise BuildError(
                    BUILD_INTENT_DOC_MISSING,
                    "intent manifest cites a canonical document missing on disk",
                )
            if doc.path not in seen:
                seen.add(doc.path)
                intent_doc_count += 1
                docs.append(
                    {
                        "path": doc.path,
                        "role": doc.role,
                        "title": doc.title,
                        # Intent owns currentness: a superseded doc stays superseded. A doc
                        # listed without a status takes its own frontmatter, else current.
                        "status": doc.status
                        or _frontmatter(docs_root, doc.path).get("status", "current"),
                    }
                )
    memory_docs = sorted(
        (r for r in memory_records if r.kind == KIND_MEMORY_DOCUMENT),
        key=lambda r: str(r.payload.get("path") or ""),
    )
    for record in memory_docs:
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
        memory_doc_count += 1
        docs.append(
            {
                "path": path,
                "role": str(record.payload.get("document_type") or "reference"),
                "title": str(record.payload.get("title") or path),
                # Being indexed is not a claim that the document is current.
                "status": "unknown",
            }
        )
    declared_doc_count = 0
    for path in declared.canonical_docs if declared is not None else ():
        if path in seen or not _doc_exists(docs_root, path):
            continue
        seen.add(path)
        declared_doc_count += 1
        docs.append(
            {
                "path": path,
                "role": declared.doc_role(path) if declared is not None else "reference",
                "title": path,
                # Existing is not a claim that the document is current.
                "status": "unknown",
            }
        )
    # Frontmatter is the project's own statement of a document's status and role; it
    # refines memory and declared docs, never a status the intent manifest stated.
    for index, entry in enumerate(docs):
        if index < intent_doc_count:
            continue
        stated_doc = _frontmatter(docs_root, entry["path"])
        if stated_doc:
            docs[index] = {**entry, **stated_doc}
    # Attribute the set to the sources whose documents actually survived.
    docs_authority = "+".join(
        tier
        for tier, count in (
            ("intent", intent_doc_count),
            ("memory", memory_doc_count),
            ("declared", declared_doc_count),
        )
        if count
    )
    if not docs and strict:
        raise BuildError(
            BUILD_NO_CANONICAL_DOCS,
            "no canonical document survived the reality check; refusing to publish an empty beacon",
        )

    # -- structure concept (memory structure + git inventory summary) ---------
    structure_summary: str | None = None
    structure_fingerprint: str | None = None
    structure = _first_record(memory_records, KIND_MEMORY_STRUCTURE)
    if structure is not None:
        entities = cast(dict[str, int], structure.payload.get("entities") or {})
        edges = cast(dict[str, int], structure.payload.get("edges") or {})
        parts = [f"{role}: {count}" for role, count in sorted(entities.items()) if count]
        edge_parts = [f"{rel}: {count}" for rel, count in sorted(edges.items()) if count]
        structure_summary = (
            "Indexed repository structure as of the latest memory-provider scan: "
            + "; ".join(parts + edge_parts)
        ).strip()
        structure_fingerprint = str(structure.payload.get("scan_fingerprint") or "") or None

    # -- decisions (history) with location reality checks ---------------------
    decisions: list[DecisionFact] = []
    # Sorted on the full record content so the order -- and therefore the
    # id suffix a colliding title receives -- never depends on input order.
    decision_records = sorted(
        (r for r in memory_records if r.kind == KIND_MEMORY_DECISION),
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
    non_goals_authority = "intent" if non_goals else ""
    if not non_goals and conventions.non_goals:
        non_goals, non_goals_authority = conventions.non_goals, "declared"
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
    command_authority = {
        key: ("intent" if build_and_test.get(key, "").strip() else "")
        for key in ("setup", "test", "benchmark")
    }
    if declared is not None:
        for key, value in (("setup", declared.setup), ("test", declared.test)):
            if not build_and_test.get(key, "").strip():
                build_and_test[key], command_authority[key] = _take(value, f"build_and_test.{key}")
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
                        # Kept so the built manifest's validation can report drift.
                        "digest": source.digest,
                    }
                    for source in guard.sources
                ],
            }
            for guard in intent.guardrails
        ]
    guardrails_authority = "intent" if guardrails else ""
    known_ids = {str(guard["id"]).lower() for guard in guardrails}
    extra_guards = [g for g in conventions.guardrails if str(g["id"]).lower() not in known_ids]
    if extra_guards:
        guardrails.extend(extra_guards)
        guardrails_authority = "+".join(t for t in (guardrails_authority, "declared") if t)

    git_head: str | None = None
    head = _first_record(git_records, KIND_GIT_HEAD)
    if head is not None:
        git_head = str(head.payload.get("commit") or "") or None

    read_first = tuple(doc["path"] for doc in docs[:_READ_FIRST_LIMIT])
    agent_guidance: dict[str, tuple[str, ...]] = {}
    if intent is not None:
        guidance = intent.agent_guidance
        if guidance.read_first:
            read_first = tuple(guidance.read_first)
        agent_guidance = {
            "safe_first_tasks": tuple(guidance.safe_first_tasks),
            "avoid_without_review": tuple(guidance.avoid_without_review),
            "expected_behavior": tuple(guidance.expected_behavior),
        }
    guidance_authority = {key: ("intent" if value else "") for key, value in agent_guidance.items()}
    for key, derived_items in (
        ("avoid_without_review", conventions.avoid),
        ("expected_behavior", conventions.expected_behavior),
    ):
        if not agent_guidance.get(key) and derived_items:
            agent_guidance[key] = tuple(derived_items)
            guidance_authority[key] = "declared"

    tagline = intent.project.tagline if intent is not None else ""
    license_name = intent.project.license.strip() if intent is not None else ""
    license_authority = "intent" if license_name else ""
    stated = declared.license if declared is not None else None
    if stated is not None and stated.tier == "declared":
        # A fact about the code: the project's own files win over intent.
        if license_name and license_name.lower() != stated.value.lower():
            drift.append(
                DriftRecord(
                    code="intent_contradicts_checkout",
                    detail="beacon.yaml states a different license than the project's files; "
                    "the files win",
                    citation=stated.path,
                )
            )
        license_name, license_authority = _take(stated, "project.license")
    elif not license_name and stated is not None:
        license_name, license_authority = _take(stated, "project.license")
    stated_purpose = intent.purpose.one_sentence.strip() if intent is not None else ""
    intent_concepts = (
        tuple(cast(dict[str, Any], _plain(asdict(concept))) for concept in intent.core_concepts)
        if intent is not None
        else ()
    )
    intent_ids = {str(concept.get("id", "")).lower() for concept in intent_concepts}
    declared_concepts = tuple(
        concept for concept in conventions.concepts if concept["id"].lower() not in intent_ids
    )
    intent_concepts = intent_concepts + declared_concepts
    project_state = _intent_project_state(intent) if intent is not None else None
    project_state_authority = "intent" if project_state else ""
    releases = _recent_releases(git_records)
    if releases and not (project_state or {}).get("recently_completed"):
        project_state = dict(project_state or {})
        project_state["recently_completed"] = releases
        project_state_authority = "+".join(
            tier for tier in (project_state_authority, "git") if tier
        )

    def _from_intent(value: Any) -> str:
        filled = value.strip() if isinstance(value, str) else value
        return "intent" if filled else ""

    concept_authority = "+".join(
        tier
        for tier, supplied in (
            ("intent", len(intent_concepts) > len(declared_concepts)),
            ("memory", bool(decisions) or structure_summary is not None),
            ("declared", bool(declared_concepts)),
        )
        if supplied
    )
    intent_read_first = intent is not None and bool(intent.agent_guidance.read_first)
    field_authority = {
        "project.name": name_authority if name else "",
        "project.description": description_authority if description else "",
        "project.tagline": _from_intent(tagline),
        "project.repository": repository_authority if repository else "",
        "project.primary_language": primary_language_authority if primary_language else "",
        "project.status": status_authority,
        "project.license": license_authority if license_name else "",
        # The projection publishes `description` here, so the supplier is the one
        # that supplied the description; `stated_purpose` says whether the
        # maintainers actually wrote a purpose (see field_placeholder).
        "purpose.one_sentence": description_authority if description else "",
        "purpose.problem": _from_intent(purpose_problem),
        "purpose.non_goals": non_goals_authority,
        "audiences": _from_intent(tuple(audiences)),
        "current_focus": _from_intent(tuple(current_focus)),
        "canonical_docs": docs_authority if docs else "",
        "core_concepts": concept_authority,
        "agent_guidance.read_first": (
            "intent" if intent_read_first else ("derived" if read_first else "")
        ),
        "agent_guidance.safe_first_tasks": guidance_authority.get("safe_first_tasks", ""),
        "agent_guidance.avoid_without_review": guidance_authority.get("avoid_without_review", ""),
        "agent_guidance.expected_behavior": guidance_authority.get("expected_behavior", ""),
        "build_and_test.setup": command_authority["setup"],
        "build_and_test.test": command_authority["test"],
        "build_and_test.benchmark": command_authority["benchmark"],
        "guardrails": guardrails_authority,
        "project_state": (
            project_state_authority
            if any(bool(value) for value in (project_state or {}).values())
            else ""
        ),
    }

    if not stated_purpose and conventions.purpose and description == conventions.purpose:
        stated_purpose = conventions.purpose
    placeholders = set()
    if not stated_purpose:
        placeholders.add("purpose.one_sentence")
    if status.strip().lower() == "unknown":
        # A schema default is reported as authority "default", which the report
        # already treats as a gap; only an explicit "unknown" needs the flag.
        placeholders.add("project.status")

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
        project_description=(intent.project.description.strip() if intent is not None else ""),
        tagline=tagline,
        license=license_name,
        intent_concepts=intent_concepts,
        agent_guidance=agent_guidance,
        project_state=project_state,
        stated_purpose=stated_purpose,
        field_authority=field_authority,
        field_placeholder=frozenset(placeholders),
        field_citations=citations,
        marked_fields=conventions.by_marker,
        convention_fields=frozenset(
            name_
            for name_ in conventions.by_convention
            if field_authority.get(name_) == "declared"
            or "declared" in field_authority.get(name_, "").split("+")
        ),
    )


def _frontmatter(docs_root: Path, path: str) -> dict[str, str]:
    """``status``/``role`` a document states about itself in YAML frontmatter."""
    try:
        target = resolve_canonical_path(docs_root, path)
        with target.open("rb") as handle:
            head = handle.read(8192)
    except Exception:  # noqa: BLE001 - unreadable means "states nothing"
        return {}
    return read_frontmatter(head.decode("utf-8", errors="replace"))


def _recent_releases(git_records: tuple[NormalizedRecord, ...]) -> list[dict[str, Any]]:
    """The newest git tags as recently completed work, each citing its commit."""
    tags = [r.payload for r in git_records if r.kind == KIND_GIT_TAG]
    tags = [tag for tag in tags if str(tag.get("name") or "") and str(tag.get("commit") or "")]
    tags.sort(
        key=lambda tag: (str(tag.get("date") or ""), str(tag.get("name") or "")), reverse=True
    )
    items: list[dict[str, Any]] = []
    for tag in tags[:_MAX_RECENT_RELEASES]:
        name = str(tag["name"])
        commit = str(tag["commit"])
        date = str(tag.get("date") or "")
        summary = f"Tagged {date[:10]} at {commit[:12]}." if date else f"Tagged at {commit[:12]}."
        items.append(
            {
                "title": f"Release {name}",
                "summary": summary,
                "sources": [{"type": "commit", "title": name, "status": "current"}],
            }
        )
    return items


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
