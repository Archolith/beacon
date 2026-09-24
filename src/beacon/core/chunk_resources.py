"""Deterministic companion index and static resources for snapshot chunks.

The companion contract adds addressability and byte budgeting without changing
the frozen Beacon snapshot 1.0 schema. Everything is derived from one approved
embedded :class:`~beacon.core.snapshot.Snapshot`; no source file is opened.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from beacon import __version__
from beacon.core.canonical_json import dumps_canonical
from beacon.core.snapshot import CONTENT_EMBEDDED, Snapshot

CHUNK_INDEX_VERSION = "1.0"
CHUNK_RESOURCE_VERSION = "1.0"
_CHUNK_ID_VERSION = "1"


@dataclass(frozen=True)
class StaticChunkResource:
    """One precomputed chunk response."""

    id: str
    body: bytes
    sha256: str


@dataclass(frozen=True)
class StaticChunkCatalog:
    """Precomputed chunk index and its individually addressable resources."""

    index_body: bytes
    index_sha256: str
    resources: tuple[StaticChunkResource, ...]


def build_chunk_catalog(snapshot: Snapshot, *, snapshot_sha256: str) -> StaticChunkCatalog:
    """Build a bounded static chunk catalog from an embedded *snapshot*.

    Chunk IDs are stable hashes of logical location (document path, heading
    path, and line range), independent of body text. Every index entry carries
    the exact UTF-8 text size and exact canonical HTTP response size so a
    client can budget before retrieval.
    """
    if snapshot.content_mode != CONTENT_EMBEDDED:
        raise ValueError("chunk resources require embedded content mode")

    resources: list[StaticChunkResource] = []
    document_entries: list[dict[str, object]] = []
    chunk_count = 0
    seen_ids: set[str] = set()

    for document in snapshot.documents:
        chunk_entries: list[dict[str, object]] = []
        parent = {
            "path": document.path,
            "title": document.title,
            "role": document.role,
            "status": document.status,
            "source_sha256": document.source_sha256,
        }
        for chunk in document.chunks:
            if chunk.text is None:
                raise ValueError("embedded snapshot chunk is missing text")
            chunk_id = _chunk_id(
                document_path=document.path,
                heading_path=chunk.heading_path,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
            )
            if chunk_id in seen_ids:
                raise ValueError("duplicate stable chunk id")
            seen_ids.add(chunk_id)

            text_bytes = len(chunk.text.encode("utf-8"))
            resource_payload = {
                "chunk_resource_version": CHUNK_RESOURCE_VERSION,
                "beacon_version": __version__,
                "snapshot_sha256": snapshot_sha256,
                "id": chunk_id,
                "document": parent,
                "heading_path": list(chunk.heading_path),
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
                "text_bytes": text_bytes,
                "text": chunk.text,
            }
            resource_body = dumps_canonical(
                resource_payload,
                byte_ceiling=snapshot.byte_ceiling,
            )
            resource_sha256 = hashlib.sha256(resource_body).hexdigest()
            resources.append(
                StaticChunkResource(
                    id=chunk_id,
                    body=resource_body,
                    sha256=resource_sha256,
                )
            )
            chunk_entries.append(
                {
                    "id": chunk_id,
                    "parent_role": document.role,
                    "parent_status": document.status,
                    "heading_path": list(chunk.heading_path),
                    "line_start": chunk.line_start,
                    "line_end": chunk.line_end,
                    "text_bytes": text_bytes,
                    "bytes": len(resource_body),
                }
            )
            chunk_count += 1
        if chunk_entries:
            document_entries.append(
                {
                    "path": document.path,
                    "chunks": chunk_entries,
                }
            )

    index_payload = {
        "chunk_index_version": CHUNK_INDEX_VERSION,
        "beacon_version": __version__,
        "snapshot": {
            "sha256": snapshot_sha256,
            "schema_version": snapshot.beacon_snapshot_version,
        },
        "item_url_template": "/v1/chunks/{id}",
        "count": chunk_count,
        "documents": document_entries,
    }
    index_body = dumps_canonical(index_payload, byte_ceiling=snapshot.byte_ceiling)
    return StaticChunkCatalog(
        index_body=index_body,
        index_sha256=hashlib.sha256(index_body).hexdigest(),
        resources=tuple(resources),
    )


def chunk_id_for(
    *,
    document_path: str,
    heading_path: tuple[str, ...],
    line_start: int,
    line_end: int,
) -> str:
    """The stable id of a heading chunk; the same id HTTP serves at ``/v1/chunks/{id}``."""
    return _chunk_id(
        document_path=document_path,
        heading_path=heading_path,
        line_start=line_start,
        line_end=line_end,
    )


def _chunk_id(
    *,
    document_path: str,
    heading_path: tuple[str, ...],
    line_start: int,
    line_end: int,
) -> str:
    identity = dumps_canonical(
        {
            "version": _CHUNK_ID_VERSION,
            "document_path": document_path,
            "heading_path": list(heading_path),
            "line_start": line_start,
            "line_end": line_end,
        }
    )
    return f"c1-{hashlib.sha256(identity).hexdigest()[:32]}"


__all__ = [
    "CHUNK_INDEX_VERSION",
    "CHUNK_RESOURCE_VERSION",
    "StaticChunkCatalog",
    "StaticChunkResource",
    "build_chunk_catalog",
]
