"""The :class:`BeaconProvider` contract.

A provider answers the five Beacon v0 capabilities. The MCP layer depends only
on this Protocol, so the data source is swappable: v0 ships
:class:`~beacon.provider.manifest_provider.ManifestBeaconProvider`; a richer
Menhir-backed provider (temporal memory, structure graph, git history) can be
dropped in later without touching the tools.

Methods are synchronous and deterministic in v0 -- there is no I/O beyond the
in-memory manifest and doc index, so async buys nothing yet. The Protocol can
grow async variants if a future provider needs them.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from beacon.core.schema import (
    AgentOnboarding,
    ConceptExplanation,
    GuardrailResponse,
    ProjectOverview,
    SearchResult,
)


@runtime_checkable
class BeaconProvider(Protocol):
    """Backend-agnostic source of project knowledge for the Beacon tools."""

    def project_overview(
        self, *, audience: str = "coding_agent", depth: str = "standard"
    ) -> ProjectOverview:
        """Concise, current explanation of the project (identify + orient)."""
        ...

    def agent_onboarding(
        self, *, task_hint: str = "", risk_tolerance: str = "low"
    ) -> AgentOnboarding:
        """Minimum context to begin safely: read order, files, do-not-touch."""
        ...

    def search(
        self,
        *,
        query: str,
        source_types: tuple[str, ...] = (),
        limit: int = 8,
    ) -> SearchResult:
        """Search project knowledge with structured, status-typed results."""
        ...

    def explain_concept(self, *, concept: str, depth: str = "technical") -> ConceptExplanation:
        """Explain project-specific vocabulary and why it exists."""
        ...

    def guardrails(self, *, task_hint: str = "") -> GuardrailResponse:
        """Tell an agent how not to break the project for a given task."""
        ...
