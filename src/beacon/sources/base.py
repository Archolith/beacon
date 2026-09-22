"""Normalized source adapters for the v0.3 build pipeline.

An adapter turns one external evidence source (today: git; later: docs,
files, Menhir) into :class:`NormalizedRecord` values that both ``beacon init``
and ``beacon build`` consume. Adapters supply *reality and history*, never
intent: manifest meaning is decided by the merge policy (build) or the
maintainer (init), never by an adapter.

Shared rules for every adapter:

* deterministic output for a frozen input state (no wall-clock collection
  stamps, stable ordering, bounded sizes);
* every record carries provenance (citations to the concrete upstream objects
  it was derived from -- for git, the commit digest *is* the source digest);
* confidence is always stated with the reason for it; and
* nothing an adapter emits may be invented: absent evidence is omitted, and
  clipping is reported (``truncated``), never silent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: Citation kinds. A git commit digest is itself a content address, so a
#: ``commit`` citation doubles as the source digest the record was derived from.
CITATION_COMMIT = "commit"
CITATION_PATH = "path"
#: Citation to memory-provider knowledge: the value is the evidence object's
#: stable identifier (today the scan fingerprint, e.g. ``scan:<fingerprint>``).
CITATION_MEMORY = "memory"

#: Record kinds emitted by the git adapter.
KIND_GIT_HEAD = "git_head"
KIND_GIT_INVENTORY = "git_inventory"
KIND_GIT_TAG = "git_tag"
KIND_GIT_COMMIT = "git_commit"
KIND_GIT_FILE_HISTORY = "git_file_history"
KIND_GIT_ACTIVITY = "git_activity"
KIND_GIT_CO_CHANGE = "git_co_change"

#: Record kinds emitted by the memory evidence adapter (any memory provider).
KIND_MEMORY_IDENTITY = "memory_identity"
KIND_MEMORY_STRUCTURE = "memory_structure"
KIND_MEMORY_DOCUMENT = "memory_document"
KIND_MEMORY_FILE = "memory_file"
KIND_MEMORY_DECISION = "memory_decision"
KIND_MEMORY_LIFECYCLE = "memory_lifecycle"

#: Deprecated aliases from when Menhir was the only provider (one release).
KIND_MENHIR_IDENTITY = KIND_MEMORY_IDENTITY
KIND_MENHIR_STRUCTURE = KIND_MEMORY_STRUCTURE
KIND_MENHIR_DOCUMENT = KIND_MEMORY_DOCUMENT
KIND_MENHIR_FILE = KIND_MEMORY_FILE
KIND_MENHIR_DECISION = KIND_MEMORY_DECISION
KIND_MENHIR_LIFECYCLE = KIND_MEMORY_LIFECYCLE


@dataclass(frozen=True)
class Citation:
    """One concrete upstream object a record was derived from."""

    kind: str  # CITATION_*
    value: str


@dataclass(frozen=True)
class NormalizedRecord:
    """One normalized, provenance-carrying evidence record.

    ``payload`` is a JSON-ready mapping of plain values (str, int, bool, None,
    lists, dicts) with a fixed key order so equal evidence serializes to equal
    bytes. ``freshness`` is the evidence's own notion of recency (for git: an
    ISO-strict commit date or the walked window), never a collection timestamp.
    """

    identity: str
    kind: str
    payload: Mapping[str, object]
    citations: tuple[Citation, ...]
    adapter: str
    adapter_version: str
    confidence: str  # "high" | "medium" | "low"
    confidence_reason: str
    freshness: str | None = None


@runtime_checkable
class SourceAdapter(Protocol):
    """The one-method boundary every source adapter implements."""

    def collect(self) -> tuple[NormalizedRecord, ...]:
        """Return the adapter's deterministic, bounded evidence records."""
        ...


__all__ = [
    "CITATION_COMMIT",
    "CITATION_MEMORY",
    "CITATION_PATH",
    "KIND_GIT_ACTIVITY",
    "KIND_GIT_CO_CHANGE",
    "KIND_GIT_COMMIT",
    "KIND_GIT_FILE_HISTORY",
    "KIND_GIT_HEAD",
    "KIND_GIT_INVENTORY",
    "KIND_GIT_TAG",
    "KIND_MEMORY_DECISION",
    "KIND_MEMORY_DOCUMENT",
    "KIND_MEMORY_FILE",
    "KIND_MEMORY_IDENTITY",
    "KIND_MEMORY_LIFECYCLE",
    "KIND_MEMORY_STRUCTURE",
    "KIND_MENHIR_DECISION",
    "KIND_MENHIR_DOCUMENT",
    "KIND_MENHIR_FILE",
    "KIND_MENHIR_IDENTITY",
    "KIND_MENHIR_LIFECYCLE",
    "KIND_MENHIR_STRUCTURE",
    "Citation",
    "NormalizedRecord",
    "SourceAdapter",
]
