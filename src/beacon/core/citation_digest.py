"""Content digests for citations: detect when cited text changed after a claim was written.

A hand-written claim (a guardrail, a concept, a project-state item) cites a file and
optionally a line range. Pinning the citation stores ``sha256:<hex>`` of that text in
``sources[].digest``; the validator and the build recompute it and report a mismatch
as drift, so a stale claim is found instead of served silently.

The digest is over normalized text so that it is stable across platforms:

* bytes are decoded as UTF-8 (invalid sequences replaced);
* CRLF and CR line endings become LF;
* trailing whitespace is stripped from every line;
* with a line range, only lines ``line_start..line_end`` (1-based, inclusive) are
  hashed; ``line_end`` alone is ignored and ``line_start`` alone means that one line;
* the selected lines are joined with ``\\n`` and hashed as UTF-8.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from beacon.core.limits import LIMIT_DOCUMENT_BYTES, ResourceLimits, read_bytes_bounded
from beacon.core.paths import resolve_canonical_path

DIGEST_PREFIX = "sha256:"


class CitationUnavailable(ValueError):
    """The cited file cannot be read, or the line range lies outside it."""


def digest_text(text: str, line_start: int | None = None, line_end: int | None = None) -> str:
    """Return the ``sha256:<hex>`` digest of *text* (optionally a line range of it)."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    if line_start is not None:
        end = line_end if line_end is not None else line_start
        if line_start < 1 or end < line_start or end > len(lines):
            raise CitationUnavailable("the cited line range lies outside the file")
        lines = lines[line_start - 1 : end]
    payload = "\n".join(lines).encode("utf-8")
    return DIGEST_PREFIX + hashlib.sha256(payload).hexdigest()


def digest_citation(
    root: str | Path,
    path: str,
    line_start: int | None = None,
    line_end: int | None = None,
    *,
    limits: ResourceLimits | None = None,
) -> str:
    """Digest the cited *path* (repository-relative, under *root*).

    Raises :class:`CitationUnavailable` when the path is unsafe, missing, too large,
    or the line range does not fit the file.
    """
    active = limits if limits is not None else ResourceLimits()
    try:
        target = resolve_canonical_path(root, path)
        if not target.is_file():
            raise CitationUnavailable("the cited file does not exist")
        raw = read_bytes_bounded(
            target,
            ceiling=active.document_bytes,
            code=LIMIT_DOCUMENT_BYTES,
            field="document_bytes",
        )
    except CitationUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - any read failure means "cannot check"
        raise CitationUnavailable("the cited file cannot be read") from exc
    return digest_text(raw.decode("utf-8", errors="replace"), line_start, line_end)


__all__ = ["DIGEST_PREFIX", "CitationUnavailable", "digest_citation", "digest_text"]
