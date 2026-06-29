"""beacon_project_overview — concise, current explanation of the project."""

from __future__ import annotations

from beacon.mcp.contracts import BeaconBaseTool


class ProjectOverviewTool(BeaconBaseTool):
    name = "beacon_project_overview"
    description = (
        "Return a concise, current explanation of this project: what it is, what problem "
        "it solves, its current status, core components, and what to read first. "
        "Pass audience=new_contributor|coding_agent|researcher|maintainer and "
        "depth=short|standard|deep."
    )

    async def endpoint(
        self,
        audience: str = "coding_agent",
        depth: str = "standard",
    ) -> str:
        provider = self.get_provider()
        result = provider.project_overview(audience=audience, depth=depth)
        return self.render_answer(result)
