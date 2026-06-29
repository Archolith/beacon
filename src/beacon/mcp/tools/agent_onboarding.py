"""beacon_agent_onboarding — minimum context to begin working safely."""

from __future__ import annotations

from beacon.mcp.contracts import BeaconBaseTool


class AgentOnboardingTool(BeaconBaseTool):
    name = "beacon_agent_onboarding"
    description = (
        "Return the minimum context an agent needs to begin working on this project "
        "safely: read order, relevant docs and files, core concepts, safe first steps, "
        "and a do-not-touch list. "
        "Pass an optional task_hint describing what you plan to do, and "
        "risk_tolerance=low|medium|high."
    )

    async def endpoint(
        self,
        task_hint: str = "",
        risk_tolerance: str = "low",
    ) -> str:
        provider = self.get_provider()
        result = provider.agent_onboarding(
            task_hint=task_hint, risk_tolerance=risk_tolerance
        )
        return self.render_answer(result)
