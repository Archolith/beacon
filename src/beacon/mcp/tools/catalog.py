"""beacon_catalog — browse the project's served documents and their sections."""

from __future__ import annotations

from beacon.mcp.contracts import BeaconBaseTool


class CatalogTool(BeaconBaseTool):
    name = "beacon_catalog"
    description = (
        "List the project's documents an agent may read, in reading order: path, role, "
        "title, status, and each section's heading and chunk_id. Pass a chunk_id to "
        "beacon_read to read that section. Filter with role or status; page with offset "
        "and limit (default 50). Documents the project withholds are never listed."
    )

    async def endpoint(
        self, role: str = "", status: str = "", offset: int = 0, limit: int = 50
    ) -> str:
        provider = self.get_provider()
        return self.render_answer(
            provider.catalog(role=role, status=status, offset=offset, limit=limit)
        )
