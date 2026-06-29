"""beacon_guardrails — tell an agent how not to break the project."""

from __future__ import annotations

from beacon.mcp.contracts import BeaconBaseTool


class GuardrailsTool(BeaconBaseTool):
    name = "beacon_guardrails"
    description = (
        "Return the rules, risky files, and required checks that apply to a given task — "
        "or all global guardrails when no task is specified. "
        "Use this before editing any non-trivial part of the project. "
        "Pass an optional task_hint describing what you plan to change."
    )

    async def endpoint(
        self,
        task_hint: str = "",
    ) -> str:
        provider = self.get_provider()
        result = provider.guardrails(task_hint=task_hint)
        return self.render_answer(result)
