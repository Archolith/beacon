"""Shared contract base for Beacon MCP tools.

Simplified relative to menhir's contracts because:
- All Beacon v0 tools are ``readonly`` — no tier enforcement needed yet.
- The provider is synchronous and in-memory — no async track wrapping needed.
- Errors return a structured JSON error payload rather than raising so agents
  always receive a response.

Tools subclass :class:`BeaconBaseTool`, set ``name``/``description``, and
implement ``async endpoint(...)`` (even though the provider is sync — FastMCP
expects async tool functions).
"""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from functools import wraps
from typing import TYPE_CHECKING, Any

from beacon.core.schema import to_payload
from beacon.mcp.lifecycle import get_provider

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=_json_default)


def _error_payload(tool: str, message: str) -> str:
    return render_json({"ok": False, "tool": tool, "error": {"message": message}})


class BeaconBaseTool:
    """Contract base for Beacon MCP tools.

    Subclass, set ``name`` + ``description``, implement ``async endpoint(...)``.
    ``required_tier`` defaults to ``"readonly"`` (all v0 tools are public).
    """

    name: str
    description: str
    required_tier: str = "readonly"

    def get_provider(self):  # noqa: ANN201
        return get_provider()

    @property
    def operation(self) -> str:
        return self.name

    @abstractmethod
    async def endpoint(self, *args: Any, **kwargs: Any) -> str:
        """Tool implementation — typed signature for MCP discovery."""

    async def execute(self, *args: Any, **kwargs: Any) -> str:
        try:
            return await self.endpoint(*args, **kwargs)
        except Exception as exc:
            logger.exception("beacon tool %r raised", self.name)
            return _error_payload(self.name, str(exc))

    def render_json(self, payload: dict[str, Any]) -> str:
        return render_json(payload)

    def render_answer(self, answer_obj: Any) -> str:
        """Render a frozen-dataclass answer-contract object to a JSON string."""
        return render_json(to_payload(answer_obj))

    def register(self, mcp: "FastMCP") -> None:
        target = self.endpoint

        @wraps(target)
        async def handler(*args: Any, **kwargs: Any) -> str:
            return await self.execute(*args, **kwargs)

        handler.__name__ = self.name
        handler.__qualname__ = self.name
        mcp.tool()(handler)
