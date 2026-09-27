"""Beacon MCP tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from beacon.mcp.contracts import BeaconBaseTool
from beacon.mcp.tools.agent_onboarding import AgentOnboardingTool
from beacon.mcp.tools.catalog import CatalogTool
from beacon.mcp.tools.explain_concept import ExplainConceptTool
from beacon.mcp.tools.guardrails import GuardrailsTool
from beacon.mcp.tools.project_overview import ProjectOverviewTool
from beacon.mcp.tools.read import ReadTool
from beacon.mcp.tools.search import SearchTool

if TYPE_CHECKING:
    from fastmcp import FastMCP


class _ToolFactory(Protocol):
    """A callable that constructs a concrete Beacon tool instance."""

    def __call__(self) -> BeaconBaseTool: ...


ALL_TOOLS: list[_ToolFactory] = [
    ProjectOverviewTool,
    AgentOnboardingTool,
    SearchTool,
    ExplainConceptTool,
    GuardrailsTool,
    CatalogTool,
    ReadTool,
]


def register_all_tools(mcp: FastMCP, provider: Any = None) -> None:
    """Instantiate every tool class and register its handler on *mcp*.

    With *provider*, each tool answers from that provider instead of the process-wide
    lifespan slot, so a server can be built around an already-loaded snapshot.
    """

    def bound_provider() -> Any:
        return provider

    for tool_factory in ALL_TOOLS:
        tool = tool_factory()
        if provider is not None:
            tool.get_provider = bound_provider  # type: ignore[method-assign]
        tool.register(mcp)
