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

from beacon.core.schema import BeaconDoc, BeaconSource

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
    ) -> "DocIndex":
        root = Path(docs_root)
        chunks: list[DocChunk] = []
        for doc in docs:
            target = root / doc.path
            if not target.is_file():
                # Missing docs are a validator concern; index what exists.
                continue
            text = target.read_text(encoding="utf-8", errors="replace")
            chunks.extend(_chunk_markdown(doc.path, text, status=doc.status))
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
