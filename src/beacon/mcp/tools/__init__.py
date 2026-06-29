"""Beacon MCP tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from beacon.mcp.tools.agent_onboarding import AgentOnboardingTool
from beacon.mcp.tools.explain_concept import ExplainConceptTool
from beacon.mcp.tools.guardrails import GuardrailsTool
from beacon.mcp.tools.project_overview import ProjectOverviewTool
from beacon.mcp.tools.search import SearchTool

if TYPE_CHECKING:
    from fastmcp import FastMCP

ALL_TOOLS = [
    ProjectOverviewTool,
    AgentOnboardingTool,
    SearchTool,
    ExplainConceptTool,
    GuardrailsTool,
]


def register_all_tools(mcp: "FastMCP") -> None:
    """Instantiate every tool class and register its handler on *mcp*."""
    for tool_cls in ALL_TOOLS:
        tool_cls().register(mcp)
