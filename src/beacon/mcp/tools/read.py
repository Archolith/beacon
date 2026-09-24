"""beacon_read — read one section of a served document, with its citation."""

from __future__ import annotations

from beacon.mcp.contracts import BeaconBaseTool


class ReadTool(BeaconBaseTool):
    name = "beacon_read"
    description = (
        "Read one section of a project document with its citation (path, lines, status). "
        "Pass a chunk_id from beacon_catalog or beacon_search, or a path with a heading or "
        "a line number. Returns at most max_chars characters (default 4000, up to 8000). "
        "When truncated, read the same chunk_id with offset=next_offset for the rest of the "
        "section; next_chunk_id is the following section."
    )

    async def endpoint(
        self,
        chunk_id: str = "",
        path: str = "",
        heading: str = "",
        line: int = 0,
        max_chars: int = 4000,
        offset: int = 0,
    ) -> str:
        provider = self.get_provider()
        return self.render_answer(
            provider.read(
                chunk_id=chunk_id,
                path=path,
                heading=heading,
                line=line,
                max_chars=max_chars,
                offset=offset,
            )
        )
