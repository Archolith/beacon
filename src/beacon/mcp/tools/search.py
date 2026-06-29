"""beacon_search — structured, source-typed project knowledge search."""

from __future__ import annotations

from beacon.mcp.contracts import BeaconBaseTool


class SearchTool(BeaconBaseTool):
    name = "beacon_search"
    description = (
        "Search indexed project knowledge and return structured, status-typed results "
        "with source citations. Each hit carries a status label "
        "(current|experimental|planned|superseded|uncertain) so you know whether to trust "
        "the answer. "
        "source_types filters results: pass any subset of "
        "'docs', 'concepts', 'guardrails'. "
        "limit controls the max number of hits returned (default 8)."
    )

    async def endpoint(
        self,
        query: str,
        source_types: list[str] | None = None,
        limit: int = 8,
    ) -> str:
        provider = self.get_provider()
        types_tuple = tuple(source_types) if source_types else ()
        result = provider.search(query=query, source_types=types_tuple, limit=limit)
        return self.render_answer(result)
