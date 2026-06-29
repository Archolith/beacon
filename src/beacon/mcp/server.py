"""MCP server: tool registration and process wiring for Beacon."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from cth_mcp_framework import create_gateway_server, run_server

from beacon.mcp.lifecycle import beacon_lifespan
from beacon.mcp.tools import register_all_tools

__all__ = ["mcp", "register_all_tools"]

load_dotenv(os.getenv("ENV_FILE") or None)
logger = logging.getLogger(__name__)

# All five v0 tools are always visible — the surface is intentionally small.
mcp = create_gateway_server(
    "beacon",
    instructions=(
        "Beacon: a self-describing, machine-readable project knowledge surface. "
        "Connect your agent to understand the project before touching code. "
        "Start with beacon_project_overview or beacon_agent_onboarding."
    ),
    lifespan=beacon_lifespan,
    always_visible=[
        "beacon_project_overview",
        "beacon_agent_onboarding",
        "beacon_search",
        "beacon_explain_concept",
        "beacon_guardrails",
    ],
)

register_all_tools(mcp)
