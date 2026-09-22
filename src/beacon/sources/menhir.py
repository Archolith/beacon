"""Deprecated import path: the adapter is now :mod:`beacon.sources.memory`.

Kept for one release so existing imports keep working. Nothing here is
Menhir-specific any more; Menhir is one memory provider among any others.
"""

from __future__ import annotations

from beacon.sources.memory import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    SUPPORTED_EVIDENCE_VERSION,
    SUPPORTED_EVIDENCE_VERSIONS,
    MemoryEvidence,
    MemoryEvidenceCaps,
    MemoryEvidenceError,
    MemorySourceAdapter,
    parse_evidence_document,
    validate_evidence_payload,
)

MenhirEvidence = MemoryEvidence
MenhirEvidenceCaps = MemoryEvidenceCaps
MenhirEvidenceError = MemoryEvidenceError
MenhirSourceAdapter = MemorySourceAdapter

__all__ = [
    "ADAPTER_NAME",
    "ADAPTER_VERSION",
    "SUPPORTED_EVIDENCE_VERSION",
    "SUPPORTED_EVIDENCE_VERSIONS",
    "MenhirEvidence",
    "MenhirEvidenceCaps",
    "MenhirEvidenceError",
    "MenhirSourceAdapter",
    "parse_evidence_document",
    "validate_evidence_payload",
]
