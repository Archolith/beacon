"""beacon_explain_concept — explain project-specific vocabulary."""

from __future__ import annotations

from beacon.mcp.contracts import BeaconBaseTool


class ExplainConceptTool(BeaconBaseTool):
    name = "beacon_explain_concept"
    description = (
        "Explain a project-specific term or concept: its definition, why it exists, "
        "related concepts, and where it is implemented. "
        "The response includes a status label so you know whether the concept is current, "
        "experimental, planned, or superseded. "
        "Also explains an architecture decision record by id (e.g. adr-0005) or title: "
        "the decision verbatim, the alternatives it considered with their reasons, and "
        "where to read its context. "
        "depth=simple|technical|implementation controls detail level."
    )

    async def endpoint(
        self,
        concept: str,
        depth: str = "technical",
    ) -> str:
        provider = self.get_provider()
        result = provider.explain_concept(concept=concept, depth=depth)
        return self.render_answer(result)
