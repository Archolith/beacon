"""Index canonical docs into heading-pathed chunks with line ranges.

Chunking is deliberately simple (handoff Phase 3: "Do not overcomplicate
chunking early"): a Markdown file is split at ATX headings (``#``..``######``).
Each chunk records the heading stack that contains it and the 1-based line range
of its body, so any search hit can be cited as ``path:start-end``.

The index also provides a dependency-free keyword ``search`` used by the v0
manifest provider -- no embeddings, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from beacon.core.limits import (
    LIMIT_CHUNKS,
    LIMIT_DOCUMENT_BYTES,
    LIMIT_DOCUMENTS,
    LIMIT_PATH_BYTES,
    LIMIT_TOTAL_DOCUMENT_BYTES,
    LimitError,
    ResourceLimits,
    read_bytes_bounded,
)
from beacon.core.paths import resolve_canonical_path
from beacon.core.schema import BeaconDoc, BeaconSource

if TYPE_CHECKING:
    from beacon.core.snapshot import SnapshotDocument

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class DocChunk:
    """A heading-scoped slice of a document."""

    path: str
    heading_path: tuple[str, ...]
    text: str
    start_line: int
    end_line: int
    status: str = "current"

    @property
    def heading(self) -> str:
        return self.heading_path[-1] if self.heading_path else ""

    def to_source(self, doc_type: str = "doc") -> BeaconSource:
        title = " > ".join(self.heading_path) if self.heading_path else self.path
        return BeaconSource(
            type=doc_type,
            title=title,
            path=self.path,
            line_start=self.start_line,
            line_end=self.end_line,
            status=self.status,
        )

    def snippet(self, limit: int = 240) -> str:
        body = " ".join(self.text.split())
        if len(body) <= limit:
            return body
        return body[: limit - 1].rstrip() + "…"


@dataclass
class DocIndex:
    """An in-memory index over the manifest's canonical docs."""

    chunks: tuple[DocChunk, ...] = field(default_factory=tuple)

    @classmethod
    def from_docs(
        cls,
        docs: tuple[BeaconDoc, ...] | list[BeaconDoc],
        *,
        docs_root: str | Path,
        limits: ResourceLimits | None = None,
    ) -> DocIndex:
        root = Path(docs_root)
        active = limits if limits is not None else ResourceLimits()
        if len(docs) > active.documents:
            raise LimitError(
                LIMIT_DOCUMENTS,
                "resource limit exceeded: "
                f"{LIMIT_DOCUMENTS} (limit={active.documents}, actual={len(docs)})",
                limit="documents",
                limit_value=active.documents,
            )
        chunks: list[DocChunk] = []
        total_bytes = 0
        for doc in docs:
            doc_path = doc.path.encode("utf-8")
            if len(doc_path) > active.path_bytes:
                raise LimitError(
                    LIMIT_PATH_BYTES,
                    "resource limit exceeded: "
                    f"{LIMIT_PATH_BYTES} (limit={active.path_bytes}, "
                    f"actual={len(doc_path)})",
                    limit="path_bytes",
                    limit_value=active.path_bytes,
                )
            target = resolve_canonical_path(root, doc.path)
            if not target.is_file():
                # Missing docs are a validator concern; index what exists.
                continue
            aggregate_remaining = active.total_document_bytes - total_bytes
            read_ceiling = min(active.document_bytes, max(aggregate_remaining, 0))
            raw = read_bytes_bounded(
                target,
                ceiling=read_ceiling,
                code=(
                    LIMIT_TOTAL_DOCUMENT_BYTES
                    if read_ceiling < active.document_bytes
                    else LIMIT_DOCUMENT_BYTES
                ),
                field=(
                    "total_document_bytes"
                    if read_ceiling < active.document_bytes
                    else "document_bytes"
                ),
            )
            total_bytes += len(raw)
            if total_bytes > active.total_document_bytes:
                raise LimitError(
                    LIMIT_TOTAL_DOCUMENT_BYTES,
                    "resource limit exceeded: "
                    f"{LIMIT_TOTAL_DOCUMENT_BYTES} (limit={active.total_document_bytes}, "
                    f"actual={total_bytes})",
                    limit="total_document_bytes",
                    limit_value=active.total_document_bytes,
                )
            text = raw.decode("utf-8", errors="replace")
            doc_chunks = _chunk_markdown(doc.path, text, status=doc.status)
            if len(chunks) + len(doc_chunks) > active.chunks:
                raise LimitError(
                    LIMIT_CHUNKS,
                    f"resource limit exceeded: {LIMIT_CHUNKS} (limit={active.chunks})",
                    limit="chunks",
                    limit_value=active.chunks,
                )
            chunks.extend(doc_chunks)
        return cls(tuple(chunks))

    @classmethod
    def from_snapshot_documents(
        cls,
        documents: tuple[SnapshotDocument, ...],
        *,
        limits: ResourceLimits | None = None,
    ) -> DocIndex:
        """Rebuild the index from a canonical snapshot's embedded documents.

        This is the snapshot-serving path: the chunk text ships inside the
        snapshot, so no source file is read. Chunk identity (path, heading
        path, line range, status) is exactly what the export path recorded.
        """
        active = limits if limits is not None else ResourceLimits()
        chunks: list[DocChunk] = []
        for document in documents:
            for chunk in document.chunks:
                if chunk.text is None:
                    # Plan-role documents are title-only in a snapshot (the
                    # writer's policy), so snapshot-served search cannot hit
                    # plan text; every other document is indexed identically.
                    continue
                if len(chunks) >= active.chunks:
                    raise LimitError(
                        LIMIT_CHUNKS,
                        f"resource limit exceeded: {LIMIT_CHUNKS} (limit={active.chunks})",
                        limit="chunks",
                        limit_value=active.chunks,
                    )
                chunks.append(
                    DocChunk(
                        path=document.path,
                        heading_path=chunk.heading_path,
                        text=chunk.text,
                        start_line=chunk.line_start,
                        end_line=chunk.line_end,
                        status=document.status,
                    )
                )
        return cls(tuple(chunks))

    def search(self, query: str, *, limit: int = 8) -> list[tuple[DocChunk, float]]:
        """Return ``(chunk, score)`` pairs ranked by keyword overlap.

        Scoring is bag-of-words overlap with a small boost when query terms
        appear in the chunk's heading path. Deterministic and offline.
        """
        terms = _tokenize(query)
        if not terms:
            return []
        scored: list[tuple[DocChunk, float]] = []
        for chunk in self.chunks:
            body_tokens = _tokenize(chunk.text)
            if not body_tokens:
                continue
            heading_tokens = _tokenize(" ".join(chunk.heading_path))
            body_set = set(body_tokens)
            heading_set = set(heading_tokens)
            score = 0.0
            for term in terms:
                if term in body_set:
                    score += 1.0
                if term in heading_set:
                    score += 1.5  # heading match is a stronger signal
            if score > 0:
                # Normalize lightly by chunk size so huge chunks do not dominate.
                score = score / (1.0 + len(body_set) / 400.0)
                scored.append((chunk, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_markdown(path: str, text: str, *, status: str) -> list[DocChunk]:
    lines = text.splitlines()
    chunks: list[DocChunk] = []
    heading_stack: list[tuple[int, str]] = []  # (level, title)
    body: list[str] = []
    body_start = 1  # 1-based line of first body line in the current section

    def flush(end_line: int) -> None:
        body_text = "\n".join(body).strip()
        if body_text:
            chunks.append(
                DocChunk(
                    path=path,
                    heading_path=tuple(title for _, title in heading_stack),
                    text=body_text,
                    start_line=body_start,
                    end_line=end_line,
                    status=status,
                )
            )

    in_fence = False
    for idx, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        heading = None if in_fence else _HEADING_RE.match(line)
        if heading:
            flush(idx - 1)
            level = len(heading.group(1))
            title = heading.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            body = []
            body_start = idx + 1
        else:
            body.append(line)
    flush(len(lines))
    return chunks


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())
