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
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

from beacon.mcp.lifecycle import beacon_lifespan
from beacon.mcp.tools import register_all_tools

__all__ = ["INSTRUCTIONS", "create_mcp_server", "mcp", "register_all_tools"]

load_dotenv(os.getenv("ENV_FILE") or None)
logger = logging.getLogger(__name__)

# All seven tools are always visible — the surface is intentionally small: the five v0
# tools plus beacon_catalog and beacon_read; no gateway meta-tools, no transforms.
# Sent once on connect, so it is kept to a few lines: load only what the task needs.
INSTRUCTIONS = (
    "Beacon: cited, current knowledge about this project. Load it lazily: start with "
    "beacon_project_overview, then call beacon_agent_onboarding or beacon_guardrails "
    "with a task_hint for what you are about to change. When a question comes up, use "
    "beacon_search or beacon_catalog, then beacon_read only the sections you need; "
    "beacon_explain_concept defines project terms. For why something is built the way "
    "it is, search source_types=['decisions'] (the project's ADRs)."
)


def create_mcp_server(provider: Any = None) -> FastMCP:
    """A Beacon MCP server with all seven tools.

    Without *provider* the server builds its provider at startup (``beacon_lifespan``, from
    the environment) — the stdio and ``serve --transport http`` path. With *provider* it
    answers from that provider and has no lifespan of its own: ``serve-http`` mounts it at
    ``/mcp`` beside the JSON routes so both surfaces share one snapshot.
    """
    server: FastMCP = FastMCP(
        name="beacon",
        instructions=INSTRUCTIONS,
        lifespan=beacon_lifespan if provider is None else None,
    )
    register_all_tools(server, provider=provider)
    return server


mcp = create_mcp_server()
