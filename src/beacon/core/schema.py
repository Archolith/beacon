"""Typed schema for Beacon manifests and tool answer contracts.

Two families of frozen dataclasses live here:

* Manifest types (``BeaconManifest`` and friends) model the on-disk
  ``beacon.yaml`` after parsing. They are the structured source of truth a
  provider reads from.
* Answer-contract types (``ProjectOverview``, ``AgentOnboarding``,
  ``SearchResult``, ``ConceptExplanation``, ``GuardrailResponse``) model what a
  Beacon tool returns. Every answer carries provenance (``sources``) and an
  explicit ``status``/``confidence`` so agents do not treat all generated text
  equally.

Nothing in this module imports Menhir, Neo4j, or the MCP framework; it is pure
data so any project can reuse it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Controlled vocabularies (kept as plain strings, validated in validator.py)
# ---------------------------------------------------------------------------

#: Lifecycle status a piece of knowledge can carry.
KNOWLEDGE_STATUSES = frozenset(
    {"current", "experimental", "planned", "superseded", "disputed", "unknown"}
)

#: Status an *answer* can carry (aggregate over the knowledge it cites).
ANSWER_STATUSES = frozenset({"current", "experimental", "uncertain", "mixed"})

#: Confidence buckets for an answer.
CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})


# ---------------------------------------------------------------------------
# Manifest types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BeaconSource:
    """A traceable reference backing a claim.

    ``path`` plus an optional ``line_start``/``line_end`` is the minimum useful
    citation form (handoff open-question #3).
    """

    type: str  # doc | file | symbol | commit | issue | memory | benchmark | human_note
    title: str = ""
    path: str = ""
    url: str = ""
    line_start: int | None = None
    line_end: int | None = None
    status: str = "current"
    #: ``sha256:<hex>`` of the cited text when it was pinned (see
    #: :mod:`beacon.core.citation_digest`); "" when unpinned. A mismatch means
    #: the cited text changed after the claim was written.
    digest: str = ""


@dataclass(frozen=True)
class BeaconConcept:
    """A project-specific concept with a stable id."""

    id: str
    name: str
    definition: str
    why_it_exists: str = ""
    status: str = "current"
    related_concepts: tuple[str, ...] = ()
    implementation_locations: tuple[str, ...] = ()
    sources: tuple[BeaconSource, ...] = ()


@dataclass(frozen=True)
class BeaconDoc:
    """A canonical document the manifest points an agent at."""

    path: str
    role: str = ""  # entrypoint | architecture | research | implementation_plan | ...
    status: str = "current"
    title: str = ""
    #: ``public`` (default) or ``local``: local documents reach local MCP clients only and
    #: are never exported (snapshot, HTTP, Hub). See :mod:`beacon.core.serving_policy`.
    visibility: str = "public"


@dataclass(frozen=True)
class BeaconGuardrail:
    """A rule describing how *not* to break the project."""

    id: str
    rule: str
    scope: str = ""
    severity: str = "medium"  # low | medium | high
    applies_to: tuple[str, ...] = ()
    sources: tuple[BeaconSource, ...] = ()


@dataclass(frozen=True)
class BeaconProjectInfo:
    """Identity block: who/what the project is."""

    name: str
    tagline: str = ""
    description: str = ""
    #: "unknown" unless the maintainers state it: unknown is an answer.
    status: str = "unknown"
    repository: str = ""
    primary_language: str = ""
    license: str = ""


@dataclass(frozen=True)
class BeaconPurpose:
    """Why the project exists and what it explicitly is not."""

    one_sentence: str = ""
    problem: str = ""
    non_goals: tuple[str, ...] = ()


@dataclass(frozen=True)
class BeaconAgentGuidance:
    """Read-order and safety rails for an agent starting work."""

    read_first: tuple[str, ...] = ()
    safe_first_tasks: tuple[str, ...] = ()
    avoid_without_review: tuple[str, ...] = ()
    expected_behavior: tuple[str, ...] = ()


@dataclass(frozen=True)
class BeaconBuildTest:
    """How to set up, test, and benchmark the project."""

    setup: str = ""
    test: str = ""
    benchmark: str = ""


@dataclass(frozen=True)
class BeaconStateItem:
    """One source-cited unit of maintainer-declared project state."""

    title: str
    summary: str = ""
    next_step: str = ""
    sources: tuple[BeaconSource, ...] = ()


@dataclass(frozen=True)
class BeaconProjectState:
    """Optional current-work state published separately from project identity."""

    active_work: BeaconStateItem | None = None
    recently_completed: tuple[BeaconStateItem, ...] = ()
    blockers: tuple[BeaconStateItem, ...] = ()
    pending_decisions: tuple[BeaconStateItem, ...] = ()


#: Project-state groups the forge source fills from labelled issues.
FORGE_LABEL_GROUPS = ("blockers", "pending_decisions", "safe_first_tasks")


@dataclass(frozen=True)
class BeaconForgeConfig:
    """Build configuration for ``beacon build --forge``; never served to agents.

    ``labels`` maps a group in :data:`FORGE_LABEL_GROUPS` to the issue labels that mean
    it. Only groups the file states are present; an empty tuple turns a group off.
    """

    labels: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class BeaconServingConfig:
    """Which listed documents Beacon may serve; build configuration, never served.

    ``exclude`` holds path globs that no surface serves, even when the intent file,
    memory evidence or a convention lists the document. ``traversal`` switches the
    ``beacon_catalog`` and ``beacon_read`` tools on (default) or off; search is unaffected.
    """

    exclude: tuple[str, ...] = ()
    traversal: bool = True


@dataclass(frozen=True)
class BeaconManifest:
    """The parsed, typed representation of ``beacon.yaml``."""

    beacon_version: str
    project: BeaconProjectInfo
    purpose: BeaconPurpose = field(default_factory=BeaconPurpose)
    audiences: tuple[str, ...] = ()
    current_focus: tuple[str, ...] = ()
    core_concepts: tuple[BeaconConcept, ...] = ()
    canonical_docs: tuple[BeaconDoc, ...] = ()
    agent_guidance: BeaconAgentGuidance = field(default_factory=BeaconAgentGuidance)
    build_and_test: BeaconBuildTest = field(default_factory=BeaconBuildTest)
    guardrails: tuple[BeaconGuardrail, ...] = ()
    project_state: BeaconProjectState = field(default_factory=BeaconProjectState)
    forge: BeaconForgeConfig = field(default_factory=BeaconForgeConfig)
    serving: BeaconServingConfig = field(default_factory=BeaconServingConfig)

    def concept_by_id(self, concept_id: str) -> BeaconConcept | None:
        """Return the concept whose id matches (case-insensitive), or None."""
        needle = concept_id.strip().lower()
        for concept in self.core_concepts:
            if concept.id.lower() == needle or concept.name.lower() == needle:
                return concept
        return None


# ---------------------------------------------------------------------------
# Answer-contract types (what tools return)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectOverview:
    summary: str
    problem: str = ""
    current_status: str = ""
    core_components: tuple[str, ...] = ()
    read_next: tuple[str, ...] = ()
    status: str = "current"
    confidence: str = "medium"
    sources: tuple[BeaconSource, ...] = ()
    next_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentOnboarding:
    orientation: str
    relevant_docs: tuple[str, ...] = ()
    relevant_files: tuple[str, ...] = ()
    concepts_to_understand: tuple[str, ...] = ()
    safe_first_steps: tuple[str, ...] = ()
    do_not_touch: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    status: str = "current"
    confidence: str = "medium"
    sources: tuple[BeaconSource, ...] = ()
    next_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchHit:
    title: str
    source_type: str
    path: str = ""
    snippet: str = ""
    status: str = "current"
    confidence: str = "medium"
    why_relevant: str = ""
    #: For doc hits: pass to ``beacon_read`` to read the whole section.
    chunk_id: str = ""


@dataclass(frozen=True)
class CatalogSection:
    """One readable section of a catalogued document."""

    chunk_id: str
    heading: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class CatalogDoc:
    """A document an agent may browse and read through ``beacon_read``."""

    path: str
    role: str
    title: str
    status: str
    sections: tuple[CatalogSection, ...] = ()


@dataclass(frozen=True)
class DocCatalog:
    """``beacon_catalog``: the served documents, in reading order, one page at a time."""

    answer: str
    docs: tuple[CatalogDoc, ...] = ()
    total: int = 0
    offset: int = 0
    next_offset: int | None = None
    next_actions: tuple[str, ...] = ()
    status: str = "current"
    sources: tuple[BeaconSource, ...] = ()


@dataclass(frozen=True)
class DocSection:
    """``beacon_read``: one section's text with its citation."""

    path: str
    heading: str
    text: str
    line_start: int
    line_end: int
    status: str
    chunk_id: str
    truncated: bool = False
    next_chunk_id: str = ""
    sources: tuple[BeaconSource, ...] = ()


@dataclass(frozen=True)
class SearchResult:
    answer: str
    results: tuple[SearchHit, ...] = ()
    status: str = "current"
    confidence: str = "medium"
    sources: tuple[BeaconSource, ...] = ()
    next_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConceptExplanation:
    concept: str
    definition: str
    why_it_exists: str = ""
    related_concepts: tuple[str, ...] = ()
    implementation_locations: tuple[str, ...] = ()
    status: str = "current"
    confidence: str = "medium"
    sources: tuple[BeaconSource, ...] = ()
    next_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class GuardrailResponse:
    rules: tuple[str, ...] = ()
    risky_files: tuple[str, ...] = ()
    required_checks: tuple[str, ...] = ()
    related_guardrails: tuple[str, ...] = ()
    status: str = "current"
    confidence: str = "medium"
    sources: tuple[BeaconSource, ...] = ()
    next_actions: tuple[str, ...] = ()


def to_payload(obj: Any) -> dict[str, Any]:
    """Convert any answer-contract dataclass to a JSON-ready dict.

    Tuples become lists and nested dataclasses are expanded recursively via
    :func:`dataclasses.asdict`.
    """
    return asdict(obj)


def served_manifest_payload(manifest: BeaconManifest) -> dict[str, Any]:
    """The manifest as served data: authoring-only fields removed.

    A citation's ``digest`` exists to detect drift while authoring and
    building; the served resource contracts (snapshot 1.0, concept and
    guardrail resources 1.0) do not carry it.
    """
    payload = _without_digests(asdict(manifest))
    payload.pop("forge", None)  # build configuration, not project knowledge
    payload.pop("serving", None)  # build configuration; never tell a reader what is hidden
    return payload


def _without_digests(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_digests(item)
            for key, item in value.items()
            if not (key == "digest" and "line_start" in value)
        }
    if isinstance(value, list | tuple):
        # asdict keeps tuples as tuples; preserve the container type.
        return type(value)(_without_digests(item) for item in value)
    return value
