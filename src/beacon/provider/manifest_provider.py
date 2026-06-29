"""Manifest-driven Beacon provider (v0).

Everything is derived deterministically from the typed :class:`BeaconManifest`
and an in-memory :class:`DocIndex` over the canonical docs. No LLM, no network,
no Neo4j -- the strength of Beacon v0 is *structure*, not generation (handoff
Phase 4 and 14.2).

Each answer carries provenance and an honest aggregate ``status``/``confidence``
so an agent can tell current knowledge from experimental or uncertain.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from beacon.core.doc_index import DocChunk, DocIndex
from beacon.core.loader import load_beacon_manifest
from beacon.core.schema import (
    AgentOnboarding,
    BeaconConcept,
    BeaconManifest,
    BeaconSource,
    ConceptExplanation,
    GuardrailResponse,
    ProjectOverview,
    SearchHit,
    SearchResult,
)
from beacon.core.validator import require_valid_manifest


@dataclass
class ManifestBeaconProvider:
    """v0 :class:`~beacon.provider.base.BeaconProvider` over a manifest."""

    manifest: BeaconManifest
    doc_index: DocIndex
    docs_root: Path

    # -- construction --------------------------------------------------------

    @classmethod
    def from_paths(
        cls, *, manifest_path: str | Path, docs_root: str | Path, validate: bool = True
    ) -> "ManifestBeaconProvider":
        """Load + (optionally) validate a manifest and build the doc index."""
        manifest = load_beacon_manifest(manifest_path)
        root = Path(docs_root)
        if validate:
            require_valid_manifest(manifest, docs_root=root)
        doc_index = DocIndex.from_docs(manifest.canonical_docs, docs_root=root)
        return cls(manifest=manifest, doc_index=doc_index, docs_root=root)

    @classmethod
    def from_settings(cls, settings: "object") -> "ManifestBeaconProvider":
        """Build from a settings object exposing ``manifest_path``/``docs_root``."""
        return cls.from_paths(
            manifest_path=getattr(settings, "manifest_path"),
            docs_root=getattr(settings, "docs_root"),
            validate=getattr(settings, "validate_on_load", True),
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

        commands = tuple(
            cmd for cmd in (m.build_and_test.setup, m.build_and_test.test) if cmd
        )
        orientation = (
            m.purpose.one_sentence or m.project.description
        )
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
        answer = (
            f"{len(hits)} result(s) for '{query}'."
            if hits
            else f"No indexed knowledge matched '{query}'."
        )
        return SearchResult(
            answer=answer,
            results=tuple(hits),
            status=_aggregate_status(statuses) if hits else "uncertain",
            confidence=_confidence(len(hits)),
            sources=tuple(_dedupe_sources(sources)),
            next_actions=(
                ("read the top-cited doc section",) if hits else ("broaden the query",)
            ),
        )

    def explain_concept(self, *, concept: str, depth: str = "technical") -> ConceptExplanation:
        m = self.manifest
        found = m.concept_by_id(concept)
        if found is None:
            # Fall back to fuzzy match then doc search.
            matches = _concepts_matching(m, concept)
            found = matches[0] if matches else None
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
            concept=concept,
            definition=definition,
            why_it_exists="",
            status="uncertain",
            confidence="low" if not hits else "medium",
            sources=sources,
            next_actions=("not a registered concept; try beacon_search",),
        )

    def guardrails(self, *, task_hint: str = "") -> GuardrailResponse:
        m = self.manifest
        selected = (
            _guardrails_matching(m, task_hint) if task_hint else list(m.guardrails)
        )
        if not selected:
            selected = list(m.guardrails)
        rules = tuple(f"[{g.severity}] {g.rule}" for g in selected)
        risky = _dedupe(
            applies for g in selected for applies in g.applies_to
        )
        checks = tuple(
            cmd for cmd in (m.build_and_test.test, m.build_and_test.benchmark) if cmd
        )
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


# Backwards-friendly alias used by DocChunk typing imports.
_DocChunk = DocChunk
