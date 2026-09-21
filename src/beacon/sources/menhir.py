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
* **Schema-enforced.** The published schema is enforced rule for rule
  before any record is built (:func:`validate_evidence_payload`); unknown
  keys are refused everywhere (``additionalProperties: false``) and a
  failure names the JSON pointer of the defect, never its value.
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


#: Project statuses the schema enumerates (the manifest knowledge vocabulary).
_PROJECT_STATUSES = frozenset(
    {"current", "experimental", "planned", "superseded", "disputed", "unknown"}
)

#: Allowed keys per object (the schema sets ``additionalProperties: false``).
_ROOT_KEYS = frozenset(
    {"evidence_version", "project", "documents", "files", "structure", "decisions", "lifecycle"}
)
_PROJECT_KEYS = frozenset(
    {"name", "description", "primary_language", "root", "status", "scan_fingerprint"}
)
_STRUCTURE_KEYS = frozenset({"entities", "edges"})
_DECISION_KEYS = frozenset({"title", "summary", "status", "implementation_locations"})
_LIFECYCLE_KEYS = frozenset({"subject", "status", "superseded_by", "note"})

#: ``maxItems`` the schema declares per section.
_SCHEMA_MAX_DOCUMENTS = 64
_SCHEMA_MAX_FILES = 512
_SCHEMA_MAX_DECISIONS = 32
_SCHEMA_MAX_LIFECYCLE = 64

#: Longest key echoed into a JSON pointer.
_POINTER_TOKEN_MAX = 64


class MenhirEvidenceError(ValueError):
    """The evidence document is unusable (unreadable, malformed, or invalid).

    The message is safe for the CLI envelope: a fixed text per failure class
    plus, for schema defects, the JSON ``pointer`` of the defect. It never
    carries evidence values, filesystem paths, or exception text.
    ``reason`` is a short stable classifier (``unreadable``, ``too_large``,
    ``malformed``, or the violated rule).
    """

    def __init__(self, message: str, *, pointer: str = "", reason: str = "invalid") -> None:
        self.pointer = pointer
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True)
class MenhirEvidenceCaps:
    """Fixed evidence bounds. Raising one is a deliberate, reviewed change."""

    evidence_bytes: int = 4 * 1024 * 1024
    documents: int = 64
    files: int = 512
    decisions: int = 32
    lifecycle: int = 64
    implementation_locations: int = 64
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


def _pointer_token(key: object) -> str:
    """Return one RFC 6901 token for *key*, bounded and printable.

    Unknown keys come from the evidence document, so the token is clipped and
    restricted to printable ASCII: the pointer names *where* a defect is, it
    never becomes a channel for echoing arbitrary document content.
    """
    text = str(key)
    safe = "".join(char if " " <= char <= "~" else "?" for char in text[:_POINTER_TOKEN_MAX])
    if len(text) > _POINTER_TOKEN_MAX:
        safe += "..."
    return safe.replace("~", "~0").replace("/", "~1")


def _join(pointer: str, key: object) -> str:
    return f"{pointer}/{_pointer_token(key)}"


def _invalid(pointer: str, reason: str) -> MenhirEvidenceError:
    return MenhirEvidenceError(
        f"evidence document invalid at {pointer or '/'}: {reason}",
        pointer=pointer,
        reason=reason,
    )


def _object(
    value: Any,
    pointer: str,
    *,
    required: tuple[str, ...] = (),
    allowed: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Check a schema ``object`` node: type, ``required``, ``additionalProperties: false``."""
    if not isinstance(value, dict):
        raise _invalid(pointer, "must be an object")
    for key in required:
        if key not in value:
            raise _invalid(_join(pointer, key), "is required")
    if allowed is not None:
        for key in sorted(value, key=str):
            if key not in allowed:
                raise _invalid(_join(pointer, key), "is not an allowed property")
    return value


def _string(
    value: Any,
    pointer: str,
    *,
    min_length: int = 0,
    enum: frozenset[str] | None = None,
) -> str:
    """Check a schema ``string`` node (``null`` is a type error, as in the schema)."""
    if not isinstance(value, str):
        raise _invalid(pointer, "must be a string")
    if len(value) < min_length:
        raise _invalid(pointer, "must be a non-empty string")
    if enum is not None and value not in enum:
        raise _invalid(pointer, f"must be one of {sorted(enum)}")
    return value


def _array(value: Any, pointer: str, *, max_items: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        raise _invalid(pointer, "must be an array")
    if max_items is not None and len(value) > max_items:
        raise _invalid(pointer, f"exceeds the schema maximum of {max_items} items")
    return value


def _counts(value: Any, pointer: str) -> dict[str, int]:
    """Check a ``{name: non-negative integer}`` map (booleans are not integers)."""
    mapping = _object(value, pointer)
    counts: dict[str, int] = {}
    for key in sorted(mapping, key=str):
        item = mapping[key]
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise _invalid(_join(pointer, key), "must be a non-negative integer")
        counts[str(key)] = item
    return counts


def _optional_strings(row: dict[str, Any], pointer: str, keys: tuple[str, ...]) -> None:
    for key in keys:
        if key in row:
            _string(row[key], _join(pointer, key))


def validate_evidence_payload(payload: Any) -> None:
    """Enforce ``beacon-menhir-evidence`` 1.0 exactly as the published schema states.

    This mirrors ``docs/schemas/beacon-menhir-evidence-1.0.schema.json`` rule
    for rule (``tests/test_menhir_evidence_contract.py`` proves the parity
    against the schema file with ``jsonschema``). The schema is enforced in
    code because it ships in the source tree, not the wheel, and Beacon keeps
    no runtime JSON Schema dependency.

    Unknown-key policy: the schema sets ``additionalProperties: false`` on
    every object, so an unknown key anywhere is refused (fail closed). A
    producer that adds a field must bump ``evidence_version``. Raises
    :class:`MenhirEvidenceError` naming the first defect's JSON pointer
    (deterministic: required keys, then unknown keys in sorted order, then
    properties in schema order).
    """
    root = _object(payload, "", required=("evidence_version", "project"), allowed=_ROOT_KEYS)
    if root["evidence_version"] != SUPPORTED_EVIDENCE_VERSION:
        raise _invalid(
            "/evidence_version",
            f"unsupported version; this adapter supports {SUPPORTED_EVIDENCE_VERSION!r} only",
        )

    project = _object(
        root["project"],
        "/project",
        required=("name", "description", "scan_fingerprint"),
        allowed=_PROJECT_KEYS,
    )
    for key in ("name", "description", "scan_fingerprint"):
        _string(project[key], f"/project/{key}", min_length=1)
    _optional_strings(project, "/project", ("primary_language", "root"))
    if "status" in project:
        _string(project["status"], "/project/status", enum=_PROJECT_STATUSES)

    for section, max_items, keys in (
        ("documents", _SCHEMA_MAX_DOCUMENTS, ("title", "document_type")),
        ("files", _SCHEMA_MAX_FILES, ("role", "description")),
    ):
        if section not in root:
            continue
        rows = _array(root[section], f"/{section}", max_items=max_items)
        allowed = frozenset(("path", *keys))
        for index, item in enumerate(rows):
            pointer = f"/{section}/{index}"
            row = _object(item, pointer, required=("path",), allowed=allowed)
            _string(row["path"], f"{pointer}/path", min_length=1)
            _optional_strings(row, pointer, keys)

    if "structure" in root:
        structure = _object(root["structure"], "/structure", allowed=_STRUCTURE_KEYS)
        for key in ("entities", "edges"):
            if key in structure:
                _counts(structure[key], f"/structure/{key}")

    if "decisions" in root:
        rows = _array(root["decisions"], "/decisions", max_items=_SCHEMA_MAX_DECISIONS)
        for index, item in enumerate(rows):
            pointer = f"/decisions/{index}"
            row = _object(item, pointer, required=("title",), allowed=_DECISION_KEYS)
            _string(row["title"], f"{pointer}/title", min_length=1)
            _optional_strings(row, pointer, ("summary",))
            if "status" in row:
                _string(row["status"], f"{pointer}/status", enum=_DECISION_STATUSES)
            if "implementation_locations" in row:
                locations = _array(
                    row["implementation_locations"], f"{pointer}/implementation_locations"
                )
                for position, location in enumerate(locations):
                    _string(
                        location,
                        f"{pointer}/implementation_locations/{position}",
                        min_length=1,
                    )

    if "lifecycle" in root:
        rows = _array(root["lifecycle"], "/lifecycle", max_items=_SCHEMA_MAX_LIFECYCLE)
        for index, item in enumerate(rows):
            pointer = f"/lifecycle/{index}"
            row = _object(item, pointer, required=("subject", "status"), allowed=_LIFECYCLE_KEYS)
            _string(row["subject"], f"{pointer}/subject", min_length=1)
            _string(row["status"], f"{pointer}/status", enum=_DECISION_STATUSES)
            _optional_strings(row, pointer, ("superseded_by", "note"))


def _cap(count: int, cap: int, pointer: str) -> None:
    if count > cap:
        raise _invalid(pointer, f"exceeds the adapter cap of {cap} items")


def _path_cap(path: str, pointer: str, caps: MenhirEvidenceCaps) -> None:
    if len(path.encode("utf-8")) > caps.path_max_bytes:
        raise _invalid(pointer, "exceeds the path byte cap")


def _rows(
    rows: list[dict[str, Any]], pointer: str, cap: int, caps: MenhirEvidenceCaps
) -> tuple[dict[str, str], ...]:
    _cap(len(rows), cap, pointer)
    for index, row in enumerate(rows):
        _path_cap(row["path"], f"{pointer}/{index}/path", caps)
    return tuple(sorted((dict(row) for row in rows), key=lambda row: row["path"]))


def parse_evidence_document(
    raw: bytes, *, caps: MenhirEvidenceCaps | None = None
) -> MenhirEvidence:
    """Parse, schema-validate, and bound one evidence document; fail closed.

    The published schema is enforced first (:func:`validate_evidence_payload`);
    the adapter's own bounds (section caps, path bytes, summary length,
    whitespace-only identity) apply on top and can only narrow what the
    schema accepts.
    """
    active = caps if caps is not None else MenhirEvidenceCaps()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MenhirEvidenceError(
            "evidence document is not valid JSON", reason="malformed"
        ) from exc
    validate_evidence_payload(payload)

    project = payload["project"]
    name = project["name"].strip()
    if not name:
        raise _invalid("/project/name", "must not be blank")
    description = project["description"].strip()
    if not description:
        raise _invalid(
            "/project/description",
            "must not be blank (refusing to serve an unidentified project)",
        )
    fingerprint = project["scan_fingerprint"].strip()
    if not fingerprint:
        raise _invalid("/project/scan_fingerprint", "must not be blank")

    documents = _rows(payload.get("documents", []), "/documents", active.documents, active)
    files = _rows(payload.get("files", []), "/files", active.files, active)

    structure = payload.get("structure", {})
    entities = _counts(structure.get("entities", {}), "/structure/entities")
    edges = _counts(structure.get("edges", {}), "/structure/edges")

    decisions_raw = payload.get("decisions", [])
    _cap(len(decisions_raw), active.decisions, "/decisions")
    decisions = tuple(
        _decision(row, f"/decisions/{index}", active) for index, row in enumerate(decisions_raw)
    )

    lifecycle_raw = payload.get("lifecycle", [])
    _cap(len(lifecycle_raw), active.lifecycle, "/lifecycle")
    lifecycle = tuple(
        {
            "subject": row["subject"].strip(),
            "status": row["status"],
            "superseded_by": row.get("superseded_by", ""),
            "note": row.get("note", ""),
        }
        for row in lifecycle_raw
    )
    for index, row in enumerate(lifecycle):
        if not row["subject"]:
            raise _invalid(f"/lifecycle/{index}/subject", "must not be blank")

    return MenhirEvidence(
        version=payload["evidence_version"],
        project_name=name,
        description=description,
        primary_language=project.get("primary_language", ""),
        root=project.get("root", ""),
        scan_fingerprint=fingerprint,
        project_status=project.get("status", "experimental"),
        documents=documents,
        files=files,
        entities=entities,
        edges=edges,
        decisions=decisions,
        lifecycle=lifecycle,
    )


def _decision(row: dict[str, Any], pointer: str, caps: MenhirEvidenceCaps) -> dict[str, Any]:
    title = row["title"].strip()
    if not title:
        raise _invalid(f"{pointer}/title", "must not be blank")
    summary = row.get("summary", "")
    if len(summary) > caps.definition_max_chars:
        raise _invalid(f"{pointer}/summary", "exceeds the definition cap")
    locations = tuple(row.get("implementation_locations", []))
    _cap(len(locations), caps.implementation_locations, f"{pointer}/implementation_locations")
    for position, location in enumerate(locations):
        _path_cap(location, f"{pointer}/implementation_locations/{position}", caps)
    return {
        "title": title,
        "summary": summary,
        "status": row.get("status", "current"),
        "implementation_locations": locations,
    }


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
            raise MenhirEvidenceError(
                "evidence document exceeds the byte ceiling", reason="too_large"
            ) from exc
        except OSError as exc:
            raise MenhirEvidenceError("evidence document unreadable", reason="unreadable") from exc
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
    "parse_evidence_document",
    "validate_evidence_payload",
]
