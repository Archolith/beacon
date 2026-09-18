"""Menhir evidence adapter: indexed-project evidence as normalized records.

Menhir owns its indexed knowledge; Beacon never imports Menhir (the two
projects pin incompatible framework versions). The boundary is a **versioned
evidence document** (``docs/schemas/beacon-menhir-evidence-1.0.schema.json``):
Menhir dumps what it indexed about one project, and this adapter turns that
document into :class:`~beacon.sources.base.NormalizedRecord` values for the
build pipeline's tier-2 (history/currentness) merge.

Safety contract (mirrors :mod:`beacon.sources.git`):

* **History and identity only.** Menhir supplies what it indexed -- project
  identity, structure, documents, indexed files, and (when present) decisions
  and lifecycle state. It never supplies intent: guardrails and other
  maintainer decisions stay with the intent manifest.
* **No invented facts.** Every emitted record is a verbatim projection of an
  evidence field; absent sections emit no records. Nothing is synthesized to
  fill manifest fields -- that is the projection stage's fail-closed job.
* **Deterministic.** For a frozen evidence document, ``collect()`` returns
  identical records: fixed caps, stable sort orders, no wall-clock stamps.
* **Bounded.** The evidence document is read under a byte ceiling and each
  section under a count cap; overflow is refused (fail closed), never
  silently clipped -- Menhir controls its own dump size, so overflow means a
  broken dump, not a big repository.
* **Portable output.** The records derive entirely from the document; the
  built snapshot never needs Menhir again.

The evidence document's own integrity is Menhir's responsibility; the scan
fingerprint doubles as the citation value so built claims remain traceable to
the exact indexed state they were derived from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from beacon.core.limits import LimitError, read_bytes_bounded
from beacon.sources.base import (
    CITATION_MEMORY,
    CITATION_PATH,
    KIND_MENHIR_DECISION,
    KIND_MENHIR_DOCUMENT,
    KIND_MENHIR_FILE,
    KIND_MENHIR_IDENTITY,
    KIND_MENHIR_LIFECYCLE,
    KIND_MENHIR_STRUCTURE,
    Citation,
    NormalizedRecord,
)

ADAPTER_NAME = "menhir"
ADAPTER_VERSION = "1"

#: Supported evidence document version. An unknown version fails closed:
#: field semantics may have changed and guessing would risk invented facts.
SUPPORTED_EVIDENCE_VERSION = "1.0"

#: Statuses a decision/lifecycle entry may carry; anything else is refused.
#: The set mirrors the manifest's knowledge vocabulary minus the values Menhir
#: cannot assert about a decision it did not judge (``experimental``,
#: ``planned``, ``disputed`` are maintainer judgments, not indexed history).
_DECISION_STATUSES = frozenset({"current", "superseded"})


class MenhirEvidenceError(ValueError):
    """The evidence document is unusable (unreadable, malformed, or invalid)."""


@dataclass(frozen=True)
class MenhirEvidenceCaps:
    """Fixed evidence bounds. Raising one is a deliberate, reviewed change."""

    evidence_bytes: int = 4 * 1024 * 1024
    documents: int = 64
    files: int = 512
    decisions: int = 32
    lifecycle: int = 64
    definition_max_chars: int = 4000
    path_max_bytes: int = 1024

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"MenhirEvidenceCaps.{item.name} must be a positive integer")


@dataclass(frozen=True)
class MenhirEvidence:
    """One parsed, validated evidence document (already bounded)."""

    version: str
    project_name: str
    description: str
    primary_language: str
    root: str
    scan_fingerprint: str
    project_status: str
    documents: tuple[dict[str, str], ...] = ()
    files: tuple[dict[str, str], ...] = ()
    entities: dict[str, int] = field(default_factory=dict)
    edges: dict[str, int] = field(default_factory=dict)
    decisions: tuple[dict[str, Any], ...] = ()
    lifecycle: tuple[dict[str, Any], ...] = ()


def _require_str(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise MenhirEvidenceError(f"{where} must be a string")
    return value


def _require_str_map_list(
    value: Any, where: str, cap: int, caps: MenhirEvidenceCaps
) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        raise MenhirEvidenceError(f"{where} must be a list")
    if len(value) > cap:
        raise MenhirEvidenceError(f"{where} exceeds the evidence cap ({len(value)} > {cap})")
    rows: list[dict[str, str]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise MenhirEvidenceError(f"{where}[{index}] must be an object")
        clean = {
            str(key): _require_str(item, f"{where}[{index}].{key}")
            for key, item in row.items()
            if item is not None
        }
        path = clean.get("path", "")
        if len(path.encode("utf-8")) > caps.path_max_bytes:
            raise MenhirEvidenceError(f"{where}[{index}].path exceeds the path byte cap")
        rows.append(clean)
    return tuple(rows)


def parse_evidence_document(
    raw: bytes, *, caps: MenhirEvidenceCaps | None = None
) -> MenhirEvidence:
    """Parse and validate one evidence document; fail closed on any defect."""
    active = caps if caps is not None else MenhirEvidenceCaps()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MenhirEvidenceError(f"evidence document is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise MenhirEvidenceError("evidence document must be a JSON object")

    version = _require_str(payload.get("evidence_version"), "evidence_version")
    if version != SUPPORTED_EVIDENCE_VERSION:
        raise MenhirEvidenceError(
            f"unsupported evidence_version {version!r}; this adapter supports "
            f"{SUPPORTED_EVIDENCE_VERSION!r} only"
        )

    project = payload.get("project")
    if not isinstance(project, dict):
        raise MenhirEvidenceError("project must be an object")
    name = _require_str(project.get("name"), "project.name").strip()
    if not name:
        raise MenhirEvidenceError("project.name must be a non-empty string")
    description = _require_str(project.get("description"), "project.description").strip()
    if not description:
        raise MenhirEvidenceError(
            "project.description must be a non-empty string (refusing to serve an unidentified project)"
        )
    fingerprint = _require_str(project.get("scan_fingerprint"), "project.scan_fingerprint").strip()
    if not fingerprint:
        raise MenhirEvidenceError("project.scan_fingerprint must be a non-empty string")

    documents = _require_str_map_list(
        payload.get("documents", []), "documents", active.documents, active
    )
    documents = tuple(sorted(documents, key=lambda row: row.get("path", "")))
    files = _require_str_map_list(payload.get("files", []), "files", active.files, active)
    files = tuple(sorted(files, key=lambda row: row.get("path", "")))

    structure = payload.get("structure", {})
    if not isinstance(structure, dict):
        raise MenhirEvidenceError("structure must be an object")
    entities = _require_counts(structure.get("entities", {}), "structure.entities")
    edges = _require_counts(structure.get("edges", {}), "structure.edges")

    decisions_raw = payload.get("decisions", [])
    if not isinstance(decisions_raw, list) or len(decisions_raw) > active.decisions:
        raise MenhirEvidenceError("decisions must be a list within the evidence cap")
    decisions = tuple(
        _require_decision(row, index, active) for index, row in enumerate(decisions_raw)
    )

    lifecycle_raw = payload.get("lifecycle", [])
    if not isinstance(lifecycle_raw, list) or len(lifecycle_raw) > active.lifecycle:
        raise MenhirEvidenceError("lifecycle must be a list within the evidence cap")
    lifecycle = tuple(_require_lifecycle(row, index) for index, row in enumerate(lifecycle_raw))

    return MenhirEvidence(
        version=version,
        project_name=name,
        description=description,
        primary_language=_require_str(
            project.get("primary_language", ""), "project.primary_language"
        ),
        root=_require_str(project.get("root", ""), "project.root"),
        scan_fingerprint=fingerprint,
        project_status=_require_str(project.get("status", "experimental"), "project.status"),
        documents=documents,
        files=files,
        entities=entities,
        edges=edges,
        decisions=decisions,
        lifecycle=lifecycle,
    )


def _require_counts(value: Any, where: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise MenhirEvidenceError(f"{where} must be an object")
    counts: dict[str, int] = {}
    for key, item in sorted(value.items()):
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise MenhirEvidenceError(f"{where}.{key} must be a non-negative integer")
        counts[str(key)] = item
    return counts


def _require_decision(row: Any, index: int, caps: MenhirEvidenceCaps) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise MenhirEvidenceError(f"decisions[{index}] must be an object")
    title = _require_str(row.get("title"), f"decisions[{index}].title").strip()
    if not title:
        raise MenhirEvidenceError(f"decisions[{index}].title must be a non-empty string")
    summary = _require_str(row.get("summary", ""), f"decisions[{index}].summary")
    if len(summary) > caps.definition_max_chars:
        raise MenhirEvidenceError(f"decisions[{index}].summary exceeds the definition cap")
    status = _require_str(row.get("status", "current"), f"decisions[{index}].status")
    if status not in _DECISION_STATUSES:
        raise MenhirEvidenceError(
            f"decisions[{index}].status must be one of {sorted(_DECISION_STATUSES)}"
        )
    locations_raw = row.get("implementation_locations", [])
    if not isinstance(locations_raw, list):
        raise MenhirEvidenceError(f"decisions[{index}].implementation_locations must be a list")
    locations = tuple(
        _require_str(item, f"decisions[{index}].implementation_locations") for item in locations_raw
    )
    return {
        "title": title,
        "summary": summary,
        "status": status,
        "implementation_locations": locations,
    }


def _require_lifecycle(row: Any, index: int) -> dict[str, str]:
    if not isinstance(row, dict):
        raise MenhirEvidenceError(f"lifecycle[{index}] must be an object")
    subject = _require_str(row.get("subject"), f"lifecycle[{index}].subject").strip()
    if not subject:
        raise MenhirEvidenceError(f"lifecycle[{index}].subject must be a non-empty string")
    status = _require_str(row.get("status"), f"lifecycle[{index}].status")
    if status not in _DECISION_STATUSES:
        raise MenhirEvidenceError(
            f"lifecycle[{index}].status must be one of {sorted(_DECISION_STATUSES)}"
        )
    superseded_by = _require_str(row.get("superseded_by", ""), f"lifecycle[{index}].superseded_by")
    note = _require_str(row.get("note", ""), f"lifecycle[{index}].note")
    return {"subject": subject, "status": status, "superseded_by": superseded_by, "note": note}


class MenhirSourceAdapter:
    """Turn one Menhir evidence document into normalized records."""

    def __init__(
        self,
        evidence_path: str | Path,
        *,
        caps: MenhirEvidenceCaps | None = None,
        limits: Any = None,
    ) -> None:
        self._path = Path(evidence_path)
        self._caps = caps if caps is not None else MenhirEvidenceCaps()
        self._limits = limits

    def load(self) -> MenhirEvidence:
        """Read and parse the evidence document under the byte ceiling."""
        try:
            raw = read_bytes_bounded(
                self._path,
                ceiling=self._caps.evidence_bytes,
                code="menhir_evidence_bytes",
                field="evidence_bytes",
            )
        except LimitError as exc:
            raise MenhirEvidenceError(str(exc)) from exc
        except OSError as exc:
            raise MenhirEvidenceError(f"evidence document unreadable: {exc}") from exc
        return parse_evidence_document(raw, caps=self._caps)

    def collect(self) -> tuple[NormalizedRecord, ...]:
        """Return the deterministic, bounded records for this evidence document."""
        evidence = self.load()
        citation = Citation(CITATION_MEMORY, f"scan:{evidence.scan_fingerprint}")
        records: list[NormalizedRecord] = [
            NormalizedRecord(
                identity=f"menhir:identity:{evidence.project_name}",
                kind=KIND_MENHIR_IDENTITY,
                payload={
                    "name": evidence.project_name,
                    "description": evidence.description,
                    "primary_language": evidence.primary_language,
                    "root": evidence.root,
                    "status": evidence.project_status,
                    "scan_fingerprint": evidence.scan_fingerprint,
                },
                citations=(citation,),
                adapter=ADAPTER_NAME,
                adapter_version=ADAPTER_VERSION,
                confidence="high",
                confidence_reason="indexed project identity from the Menhir evidence document",
                freshness=None,
            )
        ]
        if evidence.entities or evidence.edges:
            records.append(
                NormalizedRecord(
                    identity=f"menhir:structure:{evidence.project_name}",
                    kind=KIND_MENHIR_STRUCTURE,
                    payload={
                        "entities": dict(sorted(evidence.entities.items())),
                        "edges": dict(sorted(evidence.edges.items())),
                        "scan_fingerprint": evidence.scan_fingerprint,
                    },
                    citations=(citation,),
                    adapter=ADAPTER_NAME,
                    adapter_version=ADAPTER_VERSION,
                    confidence="high",
                    confidence_reason="indexed structure counts from the Menhir evidence document",
                    freshness=None,
                )
            )
        for row in evidence.documents:
            path = row.get("path", "")
            records.append(
                NormalizedRecord(
                    identity=f"menhir:document:{path}",
                    kind=KIND_MENHIR_DOCUMENT,
                    payload={
                        "path": path,
                        "title": row.get("title", ""),
                        "document_type": row.get("document_type", "generic"),
                        "scan_fingerprint": evidence.scan_fingerprint,
                    },
                    citations=(Citation(CITATION_PATH, path), citation),
                    adapter=ADAPTER_NAME,
                    adapter_version=ADAPTER_VERSION,
                    confidence="high",
                    confidence_reason="indexed document from the Menhir evidence document",
                    freshness=None,
                )
            )
        for row in evidence.files:
            path = row.get("path", "")
            records.append(
                NormalizedRecord(
                    identity=f"menhir:file:{path}",
                    kind=KIND_MENHIR_FILE,
                    payload={
                        "path": path,
                        "role": row.get("role", ""),
                        "description": row.get("description", ""),
                        "scan_fingerprint": evidence.scan_fingerprint,
                    },
                    citations=(Citation(CITATION_PATH, path), citation),
                    adapter=ADAPTER_NAME,
                    adapter_version=ADAPTER_VERSION,
                    confidence="high",
                    confidence_reason="indexed file from the Menhir evidence document",
                    freshness=None,
                )
            )
        for row in evidence.decisions:
            records.append(
                NormalizedRecord(
                    identity=f"menhir:decision:{row['title']}",
                    kind=KIND_MENHIR_DECISION,
                    payload={
                        "title": row["title"],
                        "summary": row["summary"],
                        "status": row["status"],
                        "implementation_locations": list(row["implementation_locations"]),
                        "scan_fingerprint": evidence.scan_fingerprint,
                    },
                    citations=(citation,),
                    adapter=ADAPTER_NAME,
                    adapter_version=ADAPTER_VERSION,
                    confidence="medium",
                    confidence_reason=(
                        "indexed decision history; Menhir asserts outcome, not maintainer judgment"
                    ),
                    freshness=None,
                )
            )
        for row in evidence.lifecycle:
            records.append(
                NormalizedRecord(
                    identity=f"menhir:lifecycle:{row['subject']}",
                    kind=KIND_MENHIR_LIFECYCLE,
                    payload=dict(sorted(row.items())),
                    citations=(citation,),
                    adapter=ADAPTER_NAME,
                    adapter_version=ADAPTER_VERSION,
                    confidence="medium",
                    confidence_reason="indexed lifecycle state from the Menhir evidence document",
                    freshness=None,
                )
            )
        return tuple(records)


__all__ = [
    "ADAPTER_NAME",
    "ADAPTER_VERSION",
    "MenhirEvidence",
    "MenhirEvidenceCaps",
    "MenhirEvidenceError",
    "MenhirSourceAdapter",
    "SUPPORTED_EVIDENCE_VERSION",
]
