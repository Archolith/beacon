"""Manifest-driven Beacon provider (v0).

Everything is derived deterministically from the typed :class:`BeaconManifest`
and an in-memory :class:`DocIndex` over the canonical docs. No LLM, no network,
no Neo4j -- the strength of Beacon v0 is *structure*, not generation (handoff
Phase 4 and 14.2).

Each answer carries provenance and an honest aggregate ``status``/``confidence``
so an agent can tell current knowledge from experimental or uncertain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from beacon.build.snapshot import Snapshot, SnapshotReadError
from beacon.config.settings import BeaconSettings
from beacon.core.chunk_resources import chunk_id_for
from beacon.core.doc_index import DocChunk, DocIndex
from beacon.core.limits import (
    LIMIT_INVALID_VALUE,
    LIMIT_QUERY_BYTES,
    LIMIT_RESULT_LIMIT,
    LimitError,
    ResourceLimits,
)
from beacon.core.loader import load_beacon_manifest, parse_manifest
from beacon.core.schema import (
    AgentOnboarding,
    BeaconConcept,
    BeaconDecision,
    BeaconManifest,
    BeaconSource,
    CatalogDoc,
    CatalogSection,
    ConceptExplanation,
    DocCatalog,
    DocSection,
    GuardrailResponse,
    ProjectOverview,
    SearchHit,
    SearchResult,
)
from beacon.core.serving_policy import (
    CONTEXT_LOCAL,
    READ_NOT_FOUND,
    READ_TARGET_REQUIRED,
    TRAVERSAL_DISABLED,
    ServingRequestError,
    WithheldDoc,
    manifest_for_context,
)
from beacon.core.validator import require_valid_manifest

#: ``beacon_read`` returns at most this many characters of a section (and at least the floor).
READ_MAX_CHARS = 8000
READ_MIN_CHARS = 200


@dataclass
class ManifestBeaconProvider:
    """v0 :class:`~beacon.provider.base.BeaconProvider` over a manifest."""

    manifest: BeaconManifest
    doc_index: DocIndex
    docs_root: Path
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    #: Listed documents this provider will not serve (path and code only).
    withheld: tuple[WithheldDoc, ...] = ()

    # -- construction --------------------------------------------------------

    @classmethod
    def from_paths(
        cls,
        *,
        manifest_path: str | Path,
        docs_root: str | Path,
        validate: bool = True,
        limits: ResourceLimits | None = None,
    ) -> ManifestBeaconProvider:
        """Load + (optionally) validate a manifest and build the doc index."""
        active = limits if limits is not None else ResourceLimits()
        manifest = load_beacon_manifest(manifest_path, limits=active)
        root = Path(docs_root)
        if validate:
            require_valid_manifest(manifest, docs_root=root)
        # Serve only what the serving policy allows; the index never holds a withheld doc.
        manifest, withheld = manifest_for_context(
            manifest, context=CONTEXT_LOCAL, docs_root=root, limits=active
        )
        doc_index = DocIndex.from_docs(manifest.canonical_docs, docs_root=root, limits=active)
        return cls(
            manifest=manifest, doc_index=doc_index, docs_root=root, limits=active, withheld=withheld
        )

    @classmethod
    def from_settings(cls, settings: BeaconSettings) -> ManifestBeaconProvider:
        """Build from a settings object exposing ``manifest_path``/``docs_root``."""
        return cls.from_paths(
            manifest_path=settings.manifest_path,
            docs_root=settings.resolved_docs_root(),
            validate=settings.validate_on_load,
            limits=settings.limits,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Snapshot,
        *,
        limits: ResourceLimits | None = None,
    ) -> ManifestBeaconProvider:
        """Build the provider from a loaded canonical snapshot (no file reads).

        The manifest is parsed from the snapshot's embedded canonical data
        through the one manifest parser, and the doc index is rebuilt from the
        snapshot's embedded chunk text. Metadata-only snapshots carry no
        chunk bodies and cannot serve search-backed answers, so they are
        refused.
        """
        if snapshot.content_mode != "embedded":
            raise SnapshotReadError(
                "snapshot_not_servable",
                "metadata-only snapshots carry no document text; embedded content_mode is required",
            )
        active = limits if limits is not None else ResourceLimits()
        manifest = parse_manifest(_strip_none_values(snapshot.manifest.data))
        require_valid_manifest(manifest, docs_root=None)
        manifest, withheld = manifest_for_context(manifest, context=CONTEXT_LOCAL)
        served = {doc.path for doc in manifest.canonical_docs}
        documents = tuple(doc for doc in snapshot.documents if doc.path in served)
        doc_index = DocIndex.from_snapshot_documents(documents, limits=active)
        return cls(
            manifest=manifest,
            doc_index=doc_index,
            docs_root=Path("."),
            limits=active,
            withheld=withheld,
        )

    # -- capabilities --------------------------------------------------------

    def project_overview(
        self, *, audience: str = "coding_agent", depth: str = "standard"
    ) -> ProjectOverview:
        m = self.manifest
        sources = [_project_source(m)]
        components = tuple(f"{c.name} ({c.status})" for c in m.core_concepts)
        read_next = m.agent_guidance.read_first or tuple(d.path for d in m.canonical_docs[:4])
        summary = m.purpose.one_sentence or m.project.description or m.project.tagline
        statuses = [m.project.status] + [c.status for c in m.core_concepts]
        return ProjectOverview(
            summary=summary,
            problem=m.purpose.problem,
            current_status=m.project.status,
            core_components=components if depth != "short" else components[:5],
            read_next=read_next,
            status=_aggregate_status(statuses),
            confidence=_confidence(len(sources) + len(m.core_concepts)),
            sources=tuple(sources),
            next_actions=("call beacon_agent_onboarding for a task-scoped start",),
        )

    def agent_onboarding(
        self, *, task_hint: str = "", risk_tolerance: str = "low"
    ) -> AgentOnboarding:
        m = self.manifest
        self._check_query(task_hint, "task_hint")
        guidance = m.agent_guidance
        relevant_files: list[str] = []
        concepts: list[str] = []
        sources: list[BeaconSource] = [_project_source(m)]

        if task_hint:
            hits = self.doc_index.search(task_hint, limit=5)
            relevant_files = _dedupe(hit.path for hit, _ in hits)
            sources.extend(hit.to_source() for hit, _ in hits)
            concepts = _dedupe(c.name for c in _concepts_matching(m, task_hint))
        if not concepts:
            concepts = _dedupe(c.name for c in m.core_concepts[:5])

        commands = tuple(cmd for cmd in (m.build_and_test.setup, m.build_and_test.test) if cmd)
        orientation = m.purpose.one_sentence or m.project.description
        if task_hint:
            orientation = f"For '{task_hint}': {orientation}".strip()
        return AgentOnboarding(
            orientation=orientation,
            relevant_docs=guidance.read_first or tuple(d.path for d in m.canonical_docs[:4]),
            relevant_files=tuple(relevant_files),
            concepts_to_understand=tuple(concepts),
            safe_first_steps=guidance.safe_first_tasks,
            do_not_touch=guidance.avoid_without_review,
            commands=commands,
            status=_aggregate_status([m.project.status]),
            confidence=_confidence(len(sources)),
            sources=tuple(sources),
            next_actions=("call beacon_guardrails before editing risky areas",),
        )

    def search(
        self,
        *,
        query: str,
        source_types: tuple[str, ...] = (),
        limit: int = 8,
    ) -> SearchResult:
        m = self.manifest
        self._check_query(query, "query")
        self._check_result_limit(limit)
        wanted = set(source_types)
        hits: list[SearchHit] = []
        sources: list[BeaconSource] = []
        statuses: list[str] = []

        if not wanted or "concepts" in wanted or "concept" in wanted:
            for concept in _concepts_matching(m, query):
                hits.append(
                    SearchHit(
                        title=concept.name,
                        source_type="concept",
                        snippet=concept.definition,
                        status=concept.status,
                        confidence="high",
                        why_relevant="concept id/name/definition matched the query",
                    )
                )
                statuses.append(concept.status)
                sources.extend(concept.sources)

        if not wanted or "decisions" in wanted or "decision" in wanted:
            # Unfiltered search keeps a few ADRs so they do not crowd out docs.
            ranked = _decisions_matching(m, query)
            for decision in ranked if wanted else ranked[:_UNFILTERED_DECISIONS]:
                hits.append(
                    SearchHit(
                        title=f"{decision.id}: {decision.title}",
                        source_type="decision",
                        path=decision.path,
                        snippet=_decision_snippet(decision),
                        status=decision.status,
                        confidence="high",
                        why_relevant=(
                            f"architecture decision record ({decision.status_text or decision.status}); "
                            f"beacon_explain_concept '{decision.id}' for its reasons and rejected alternatives"
                        ),
                        chunk_id=self._decision_chunk_id(decision) if m.serving.traversal else "",
                    )
                )
                statuses.append(decision.status)
                sources.extend(decision.sources)

        if not wanted or "docs" in wanted or "doc" in wanted:
            for chunk, _score in self.doc_index.search(query, limit=limit):
                source = chunk.to_source()
                hits.append(
                    SearchHit(
                        title=source.title,
                        source_type="doc",
                        path=chunk.path,
                        snippet=chunk.snippet(),
                        status=chunk.status,
                        confidence="medium",
                        why_relevant="keyword overlap with doc section",
                        chunk_id=_chunk_id(chunk) if m.serving.traversal else "",
                    )
                )
                statuses.append(chunk.status)
                sources.append(source)

        if not wanted or "guardrails" in wanted or "decisions" in wanted:
            for guard in _guardrails_matching(m, query):
                hits.append(
                    SearchHit(
                        title=guard.id,
                        source_type="guardrail",
                        snippet=guard.rule,
                        status="current",
                        confidence="high",
                        why_relevant="guardrail scope matched the query",
                    )
                )
                statuses.append("current")

        hits = hits[:limit]
        # The query is never echoed: answers are served over HTTP, cached and logged.
        answer = f"{len(hits)} result(s)." if hits else "No indexed knowledge matched the query."
        return SearchResult(
            answer=answer,
            results=tuple(hits),
            status=_aggregate_status(statuses) if hits else "uncertain",
            confidence=_confidence(len(hits)),
            sources=tuple(_dedupe_sources(sources)),
            next_actions=(("read the top-cited doc section",) if hits else ("broaden the query",)),
        )

    def explain_concept(self, *, concept: str, depth: str = "technical") -> ConceptExplanation:
        m = self.manifest
        self._check_query(concept, "concept")
        found = m.concept_by_id(concept)
        decision = m.decision_by_id(concept) if found is None else None
        if found is None and decision is None:
            # Fall back to fuzzy match then doc search.
            matches = _concepts_matching(m, concept)
            found = matches[0] if matches else None
            if found is None:
                ranked = _decisions_matching(m, concept)
                decision = ranked[0] if ranked else None
        if decision is not None:
            return self._explain_decision(decision)
        if found is not None:
            return ConceptExplanation(
                concept=found.name,
                definition=found.definition,
                why_it_exists=found.why_it_exists,
                related_concepts=found.related_concepts,
                implementation_locations=found.implementation_locations,
                status=_aggregate_status([found.status]),
                confidence="high",
                sources=found.sources or (_project_source(m),),
                next_actions=(
                    ("note: this concept is experimental/planned",)
                    if found.status in {"experimental", "planned"}
                    else ()
                ),
            )

        # Unknown concept: be honest and offer doc evidence if any.
        hits = self.doc_index.search(concept, limit=3)
        sources = tuple(hit.to_source() for hit, _ in hits)
        definition = hits[0][0].snippet() if hits else ""
        return ConceptExplanation(
            concept="",  # the unmatched input is never echoed back
            definition=definition,
            why_it_exists="",
            status="uncertain",
            confidence="low" if not hits else "medium",
            sources=sources,
            next_actions=("not a registered concept; try beacon_search",),
        )

    def _explain_decision(self, decision: BeaconDecision) -> ConceptExplanation:
        """An ADR as an explanation: the decision verbatim, its rejected alternatives with
        their reasons, and where to read the context and consequences."""
        rejected = "; ".join(
            f"{alt.alternative}: {alt.reason}" if alt.reason else alt.alternative
            for alt in decision.alternatives
        )
        why = f"Alternatives considered: {rejected}" if rejected else ""
        notes: list[str] = []
        if decision.implemented is False:
            notes.append(f"accepted but not in effect yet: {decision.status_text}")
        if decision.superseded_by:
            notes.append("superseded by " + ", ".join(decision.superseded_by))
        elif decision.status == "superseded":
            notes.append(f"superseded: {decision.status_text}")
        if decision.truncated:
            notes.append(f"decision text truncated; beacon_read path={decision.path} for the rest")
        for role in ("context", "consequences"):
            span = decision.sections.get(role)
            if span is not None:
                notes.append(
                    f"{role}: beacon_read path={decision.path} line={span.line_start} "
                    f"(lines {span.line_start}-{span.line_end})"
                )
        return ConceptExplanation(
            concept=f"{decision.id}: {decision.title}",
            definition=decision.decision,
            why_it_exists=why,
            related_concepts=decision.supersedes + decision.superseded_by,
            status=_aggregate_status([decision.status]),
            confidence="high",
            sources=decision.sources or (_project_source(self.manifest),),
            next_actions=tuple(notes),
        )

    def _decision_chunk_id(self, decision: BeaconDecision) -> str:
        """The served chunk holding the ADR's Decision section, for ``beacon_read``."""
        source = decision.sources[0] if decision.sources else None
        for chunk in self.doc_index.chunks:
            if chunk.path != decision.path:
                continue
            if source is None or source.line_start is None:
                return _chunk_id(chunk)
            if chunk.start_line <= source.line_start <= chunk.end_line:
                return _chunk_id(chunk)
        return ""

    def guardrails(self, *, task_hint: str = "") -> GuardrailResponse:
        m = self.manifest
        self._check_query(task_hint, "task_hint")
        selected = _guardrails_matching(m, task_hint) if task_hint else list(m.guardrails)
        if not selected:
            selected = list(m.guardrails)
        rules = tuple(f"[{g.severity}] {g.rule}" for g in selected)
        risky = _dedupe(applies for g in selected for applies in g.applies_to)
        checks = tuple(cmd for cmd in (m.build_and_test.test, m.build_and_test.benchmark) if cmd)
        sources = [s for g in selected for s in g.sources]
        # Global "avoid without review" list reinforces task-specific rules.
        avoid = m.agent_guidance.avoid_without_review
        return GuardrailResponse(
            rules=rules,
            risky_files=tuple(risky),
            required_checks=checks,
            related_guardrails=avoid,
            status="current",
            confidence=_confidence(len(selected)),
            sources=tuple(_dedupe_sources(sources)),
            next_actions=("run the required checks before committing",),
        )

    # -- limit enforcement --------------------------------------------------

    def _check_query(self, text: str, field: str) -> None:
        """Refuse free-text input whose UTF-8 size exceeds the query ceiling."""
        size = len(text.encode("utf-8"))
        if size > self.limits.query_bytes:
            raise LimitError(
                LIMIT_QUERY_BYTES,
                "resource limit exceeded: "
                f"{LIMIT_QUERY_BYTES} (field={field}, limit={self.limits.query_bytes}, "
                f"actual={size})",
                limit="query_bytes",
                limit_value=self.limits.query_bytes,
            )

    def catalog(
        self, *, role: str = "", status: str = "", offset: int = 0, limit: int = 50
    ) -> DocCatalog:
        self._require_traversal()
        self._check_result_limit(limit)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise LimitError(
                LIMIT_INVALID_VALUE,
                "invalid offset: expected a non-negative integer",
                limit="offset",
            )
        sections: dict[str, list[CatalogSection]] = {}
        for chunk in self.doc_index.chunks:
            sections.setdefault(chunk.path, []).append(
                CatalogSection(
                    chunk_id=_chunk_id(chunk),
                    heading=_heading(chunk),
                    line_start=chunk.start_line,
                    line_end=chunk.end_line,
                )
            )
        docs = [
            doc
            for doc in self.manifest.canonical_docs
            if (not role or doc.role == role) and (not status or doc.status == status)
        ]
        page = docs[offset : offset + limit] if limit else []
        entries = tuple(
            CatalogDoc(
                path=doc.path,
                role=doc.role,
                title=doc.title or _first_heading(sections.get(doc.path, ())) or doc.path,
                status=doc.status,
                sections=tuple(sections.get(doc.path, ())),
            )
            for doc in page
        )
        end = offset + len(entries)
        return DocCatalog(
            answer=f"{len(docs)} document(s); showing {len(entries)} from {offset}.",
            docs=entries,
            total=len(docs),
            offset=offset,
            next_offset=end if end < len(docs) else None,
            next_actions=("beacon_read a section's chunk_id to read it",) if entries else (),
            status=_aggregate_status([doc.status for doc in entries]) if entries else "uncertain",
            sources=(_project_source(self.manifest),),
        )

    def read(
        self,
        *,
        chunk_id: str = "",
        path: str = "",
        heading: str = "",
        line: int = 0,
        max_chars: int = 4000,
        offset: int = 0,
    ) -> DocSection:
        self._require_traversal()
        chunks = self.doc_index.chunks
        target = None
        if chunk_id:
            target = next((c for c in chunks if _chunk_id(c) == chunk_id), None)
        elif path:
            in_doc = [c for c in chunks if c.path == path]
            if heading:
                needle = heading.strip().lower()
                target = next(
                    (c for c in in_doc if c.heading_path and c.heading_path[-1].lower() == needle),
                    None,
                )
                target = target or next((c for c in in_doc if needle in _heading(c).lower()), None)
            elif line:
                target = next((c for c in in_doc if c.start_line <= line <= c.end_line), None)
                target = target or next((c for c in in_doc if c.start_line >= line), None)
            else:
                target = in_doc[0] if in_doc else None
        else:
            raise ServingRequestError(
                READ_TARGET_REQUIRED, "pass a chunk_id, or a path with a heading or line"
            )
        if target is None:
            # One code for unknown and withheld, so a reader cannot probe for hidden documents.
            raise ServingRequestError(READ_NOT_FOUND, "no served section matches that request")
        cap = max(READ_MIN_CHARS, min(int(max_chars or READ_MAX_CHARS), READ_MAX_CHARS))
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or (offset and offset >= len(target.text))
        ):
            raise LimitError(
                LIMIT_INVALID_VALUE,
                "invalid offset: expected a non-negative integer inside the section",
                limit="offset",
            )
        text = target.text[offset : offset + cap]
        end = offset + len(text)
        truncated = end < len(target.text)
        in_doc = [c for c in chunks if c.path == target.path]
        position = in_doc.index(target)
        following = in_doc[position + 1] if position + 1 < len(in_doc) else None
        return DocSection(
            path=target.path,
            heading=_heading(target),
            text=text,
            line_start=target.start_line,
            line_end=target.end_line,
            status=target.status,
            chunk_id=_chunk_id(target),
            truncated=truncated,
            offset=offset,
            # The rest of this section: read the same chunk_id again from here. next_chunk_id
            # stays the following section, so a client that ignores next_offset skips text
            # (visible via truncated) rather than rereading one page forever.
            next_offset=end if truncated else None,
            next_chunk_id=_chunk_id(following) if following is not None else "",
            sources=(target.to_source(),),
        )

    def _require_traversal(self) -> None:
        if not self.manifest.serving.traversal:
            raise ServingRequestError(
                TRAVERSAL_DISABLED, "document traversal is switched off for this project"
            )

    def _check_result_limit(self, limit: int) -> None:
        """Refuse a requested result limit above the non-overridable ceiling."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise LimitError(
                LIMIT_INVALID_VALUE,
                "invalid result limit: expected a non-negative integer",
                limit="result_limit",
            )
        if limit > self.limits.result_limit:
            raise LimitError(
                LIMIT_RESULT_LIMIT,
                "resource limit exceeded: "
                f"{LIMIT_RESULT_LIMIT} (limit={self.limits.result_limit}, actual={limit})",
                limit="result_limit",
                limit_value=self.limits.result_limit,
            )


# ---------------------------------------------------------------------------
# Matching + aggregation helpers
# ---------------------------------------------------------------------------


def _concepts_matching(manifest: BeaconManifest, query: str) -> list[BeaconConcept]:
    needle = query.lower().strip()
    if not needle:
        return []
    out: list[BeaconConcept] = []
    for concept in manifest.core_concepts:
        haystack = " ".join(
            [concept.id, concept.name, concept.definition, concept.why_it_exists]
        ).lower()
        if needle in haystack or any(tok in haystack for tok in needle.split()):
            out.append(concept)
    return out


_UNFILTERED_DECISIONS = 3
_SNIPPET_CHARS = 400


def _decisions_matching(manifest: BeaconManifest, query: str) -> list[BeaconDecision]:
    """ADRs whose id, title, status, decision or alternatives mention the query, best first
    (whole-query match, then the share of query words found; ties keep file order)."""
    needle = query.lower().strip()
    if not needle:
        return []
    tokens = [tok for tok in re.findall(r"[a-z0-9]+", needle) if len(tok) > 2] or [needle]
    scored: list[tuple[float, int, BeaconDecision]] = []
    for index, decision in enumerate(manifest.decisions):
        haystack = " ".join(
            [
                decision.id,
                decision.title,
                decision.status_text,
                decision.decision,
                *(f"{a.alternative} {a.reason}" for a in decision.alternatives),
            ]
        ).lower()
        share = sum(tok in haystack for tok in tokens) / len(tokens)
        title_hit = any(tok in decision.title.lower() for tok in tokens)
        if needle in haystack or share > 0:
            score = (2.0 if needle in haystack else 0.0) + share + (0.5 if title_hit else 0.0)
            scored.append((-score, index, decision))
    return [decision for _, _, decision in sorted(scored, key=lambda item: item[:2])]


def _decision_snippet(decision: BeaconDecision) -> str:
    text = " ".join(decision.decision.split())
    return text if len(text) <= _SNIPPET_CHARS else text[: _SNIPPET_CHARS - 3] + "..."


def _guardrails_matching(manifest: BeaconManifest, query: str):
    needle = query.lower().strip()
    if not needle:
        return []
    out = []
    for guard in manifest.guardrails:
        haystack = " ".join([guard.id, guard.scope, guard.rule, *guard.applies_to]).lower()
        if needle in haystack or any(tok in haystack for tok in needle.split()):
            out.append(guard)
    return out


def _chunk_id(chunk: DocChunk) -> str:
    return chunk_id_for(
        document_path=chunk.path,
        heading_path=chunk.heading_path,
        line_start=chunk.start_line,
        line_end=chunk.end_line,
    )


def _heading(chunk: DocChunk) -> str:
    return " > ".join(chunk.heading_path) if chunk.heading_path else "(preamble)"


def _first_heading(sections: Any) -> str:
    for section in sections:
        if section.heading != "(preamble)":
            return str(section.heading).split(" > ")[0]
    return ""


def _project_source(manifest: BeaconManifest) -> BeaconSource:
    return BeaconSource(
        type="manifest",
        title=f"{manifest.project.name} beacon manifest",
        path="beacon.yaml",
        status=manifest.project.status,
    )


def _aggregate_status(statuses: list[str]) -> str:
    present = {s for s in statuses if s}
    if not present:
        return "uncertain"
    if present == {"current"}:
        return "current"
    if present <= {"experimental", "planned"}:
        return "experimental"
    if present & {"disputed", "unknown", "superseded"}:
        return "uncertain"
    return "mixed"


def _confidence(n: int) -> str:
    if n >= 4:
        return "high"
    if n >= 1:
        return "medium"
    return "low"


def _dedupe(items) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _dedupe_sources(sources: list[BeaconSource]) -> list[BeaconSource]:
    seen: set[tuple] = set()
    out: list[BeaconSource] = []
    for s in sources:
        key = (s.path, s.line_start, s.line_end, s.title)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _strip_none_values(value: Any) -> Any:
    """Remove ``None``-valued mapping entries recursively.

    The snapshot embeds the manifest via ``dataclasses.asdict``, which
    serializes absent optional fields (source line ranges, an absent
    ``project_state.active_work``) as explicit ``null``. The loader treats
    explicit nulls as malformed, so the snapshot-serving path adapts the
    embedded form to the loader's "absent key" convention before parsing.
    """
    if isinstance(value, dict):
        return {key: _strip_none_values(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_strip_none_values(item) for item in value]
    return value


# Backwards-friendly alias used by DocChunk typing imports.
_DocChunk = DocChunk
