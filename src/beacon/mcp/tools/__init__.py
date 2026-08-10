"""Beacon MCP tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from beacon.mcp.contracts import BeaconBaseTool
from beacon.mcp.tools.agent_onboarding import AgentOnboardingTool
from beacon.mcp.tools.explain_concept import ExplainConceptTool
from beacon.mcp.tools.guardrails import GuardrailsTool
from beacon.mcp.tools.project_overview import ProjectOverviewTool
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
]


def register_all_tools(mcp: FastMCP) -> None:
    """Instantiate every tool class and register its handler on *mcp*."""
    for tool_factory in ALL_TOOLS:
        tool_factory().register(mcp)
