"""MCP server: tool registration and process wiring for Beacon.

Beacon instantiates a plain :class:`fastmcp.FastMCP` server (no gateway
transforms) so the public surface is exactly the frozen five v0 tools — the
Archolith gateway ``create_gateway_server`` would additionally add the
``call_tool`` and ``search_tools`` meta-tools. Process execution still goes
through ``archolith_mcp_framework.run_server`` (see ``beacon.main``).
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastmcp import FastMCP

from beacon.mcp.lifecycle import beacon_lifespan
from beacon.mcp.tools import register_all_tools

__all__ = ["mcp", "register_all_tools"]

load_dotenv(os.getenv("ENV_FILE") or None)
logger = logging.getLogger(__name__)

# All five v0 tools are always visible — the surface is intentionally small and
# exactly five tools: no gateway meta-tools, no transforms.
mcp = FastMCP(
    name="beacon",
    instructions=(
        "Beacon: a self-describing, machine-readable project knowledge surface. "
        "Connect your agent to understand the project before touching code. "
        "Start with beacon_project_overview or beacon_agent_onboarding."
    ),
    lifespan=beacon_lifespan,
)

register_all_tools(mcp)
