"""Deterministic companion indexes and static resources for manifest knowledge."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from beacon import __version__
from beacon.core.canonical_json import dumps_canonical
from beacon.core.snapshot import CONTENT_EMBEDDED, Snapshot

CONCEPT_INDEX_VERSION = "1.0"
CONCEPT_RESOURCE_VERSION = "1.0"
GUARDRAIL_INDEX_VERSION = "1.0"
GUARDRAIL_RESOURCE_VERSION = "1.0"
_RESOURCE_ID_VERSION = "1"
_CONCEPT_FIELDS = frozenset(
    {
        "id",
        "name",
        "definition",
        "why_it_exists",
        "status",
        "related_concepts",
        "implementation_locations",
        "sources",
    }
)
_GUARDRAIL_FIELDS = frozenset({"id", "rule", "scope", "severity", "applies_to", "sources"})
_SOURCE_FIELDS = frozenset({"type", "title", "path", "url", "line_start", "line_end", "status"})


@dataclass(frozen=True)
class StaticKnowledgeResource:
    """One precomputed concept or guardrail response."""

    id: str
    body: bytes
    sha256: str


@dataclass(frozen=True)
class StaticKnowledgeCatalog:
    """One precomputed knowledge index and its addressable resources."""

    index_body: bytes
    index_sha256: str
    resources: tuple[StaticKnowledgeResource, ...]


@dataclass(frozen=True)
class StaticKnowledgeCatalogs:
    """The concept and guardrail catalogs derived from one snapshot."""

    concepts: StaticKnowledgeCatalog
    guardrails: StaticKnowledgeCatalog


def build_knowledge_catalogs(
    snapshot: Snapshot, *, snapshot_sha256: str
) -> StaticKnowledgeCatalogs:
    """Build bounded concept and guardrail catalogs from an embedded snapshot.

    The catalogs use only the approved in-memory manifest projection. Logical
    manifest IDs remain data; opaque hashes form the URL-addressable resource
    IDs so arbitrary manifest values never become route structure.
    """
    if snapshot.content_mode != CONTENT_EMBEDDED:
        raise ValueError("knowledge resources require embedded content mode")
    if snapshot.beacon_snapshot_version != "1.0":
        raise ValueError("knowledge resources require snapshot schema 1.0")
    _require_snapshot_sha256(snapshot_sha256)
    manifest_data = snapshot.manifest.data
    if not isinstance(manifest_data, dict):
        raise ValueError("manifest data must be a mapping")

    concepts = _build_catalog(
        snapshot=snapshot,
        snapshot_sha256=snapshot_sha256,
        manifest_data=manifest_data,
        collection_key="core_concepts",
        kind="concept",
        id_prefix="k1-",
        index_version_key="concept_index_version",
        index_version=CONCEPT_INDEX_VERSION,
        resource_version_key="concept_resource_version",
        resource_version=CONCEPT_RESOURCE_VERSION,
        item_url_template="/v1/concepts/{id}",
        entries_key="concepts",
        selectors=("id", "name", "status"),
    )
    guardrails = _build_catalog(
        snapshot=snapshot,
        snapshot_sha256=snapshot_sha256,
        manifest_data=manifest_data,
        collection_key="guardrails",
        kind="guardrail",
        id_prefix="g1-",
        index_version_key="guardrail_index_version",
        index_version=GUARDRAIL_INDEX_VERSION,
        resource_version_key="guardrail_resource_version",
        resource_version=GUARDRAIL_RESOURCE_VERSION,
        item_url_template="/v1/guardrails/{id}",
        entries_key="guardrails",
        selectors=("id", "severity", "scope"),
        # ``scope`` is optional in the manifest contract (loader default ``""``),
        # so an empty scope is a valid selector value; ``id``/``severity`` are not.
        optional_selectors=frozenset({"scope"}),
    )
    return StaticKnowledgeCatalogs(concepts=concepts, guardrails=guardrails)


def _build_catalog(
    *,
    snapshot: Snapshot,
    snapshot_sha256: str,
    manifest_data: dict[str, Any],
    collection_key: str,
    kind: str,
    id_prefix: str,
    index_version_key: str,
    index_version: str,
    resource_version_key: str,
    resource_version: str,
    item_url_template: str,
    entries_key: str,
    selectors: tuple[str, ...],
    optional_selectors: frozenset[str] = frozenset(),
) -> StaticKnowledgeCatalog:
    raw_records = manifest_data.get(collection_key, [])
    if not isinstance(raw_records, list):
        raise ValueError(f"{collection_key} must be a list")

    resources: list[StaticKnowledgeResource] = []
    entries: list[dict[str, object]] = []
    logical_ids: set[str] = set()
    resource_ids: set[str] = set()
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            raise ValueError(f"{kind} record must be a mapping")
        _validate_record(kind, raw_record)
        selector_values: dict[str, str] = {}
        for selector in selectors:
            value = raw_record.get(selector)
            if not isinstance(value, str):
                raise ValueError(f"{kind} {selector} must be a string")
            if selector not in optional_selectors and not value.strip():
                raise ValueError(f"{kind} {selector} must be a non-empty string")
            selector_values[selector] = value

        logical_id = selector_values["id"]
        if logical_id in logical_ids:
            raise ValueError(f"duplicate {kind} logical id")
        logical_ids.add(logical_id)
        resource_id = _resource_id(kind=kind, logical_id=logical_id, prefix=id_prefix)
        if resource_id in resource_ids:
            raise ValueError(f"duplicate {kind} resource id")
        resource_ids.add(resource_id)

        resource_payload = {
            resource_version_key: resource_version,
            "beacon_version": __version__,
            "snapshot_sha256": snapshot_sha256,
            "resource_id": resource_id,
            kind: raw_record,
        }
        resource_body = dumps_canonical(
            resource_payload,
            byte_ceiling=snapshot.byte_ceiling,
        )
        resource_sha256 = hashlib.sha256(resource_body).hexdigest()
        resources.append(
            StaticKnowledgeResource(
                id=resource_id,
                body=resource_body,
                sha256=resource_sha256,
            )
        )
        entries.append(
            {
                "resource_id": resource_id,
                **selector_values,
                "bytes": len(resource_body),
                "sha256": resource_sha256,
            }
        )

    index_payload = {
        index_version_key: index_version,
        "beacon_version": __version__,
        "snapshot": {
            "sha256": snapshot_sha256,
            "schema_version": snapshot.beacon_snapshot_version,
        },
        "item_url_template": item_url_template,
        "count": len(entries),
        entries_key: entries,
    }
    index_body = dumps_canonical(index_payload, byte_ceiling=snapshot.byte_ceiling)
    return StaticKnowledgeCatalog(
        index_body=index_body,
        index_sha256=hashlib.sha256(index_body).hexdigest(),
        resources=tuple(resources),
    )


def _resource_id(*, kind: str, logical_id: str, prefix: str) -> str:
    identity = dumps_canonical(
        {
            "version": _RESOURCE_ID_VERSION,
            "kind": kind,
            "logical_id": logical_id,
        }
    )
    return f"{prefix}{hashlib.sha256(identity).hexdigest()[:32]}"


def _require_snapshot_sha256(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("snapshot sha256 must be 64 lowercase hexadecimal characters")


def _validate_record(kind: str, record: dict[str, Any]) -> None:
    expected = _CONCEPT_FIELDS if kind == "concept" else _GUARDRAIL_FIELDS
    if set(record) != expected:
        raise ValueError(f"{kind} record has invalid fields")
    if kind == "concept":
        for field in ("id", "name", "definition", "why_it_exists", "status"):
            _require_string(record[field], kind=kind, field=field)
        _require_string_list(record["related_concepts"], kind=kind, field="related_concepts")
        _require_string_list(
            record["implementation_locations"],
            kind=kind,
            field="implementation_locations",
        )
    else:
        for field in ("id", "rule", "scope", "severity"):
            _require_string(record[field], kind=kind, field=field)
        _require_string_list(record["applies_to"], kind=kind, field="applies_to")
    _validate_sources(record["sources"], kind=kind)


def _require_string(value: Any, *, kind: str, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{kind} {field} must be a string")


def _require_string_list(value: Any, *, kind: str, field: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{kind} {field} must be a list of strings")


def _validate_sources(value: Any, *, kind: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{kind} sources must be a list")
    for source in value:
        if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
            raise ValueError(f"{kind} source has invalid fields")
        for field in ("type", "title", "path", "url", "status"):
            if not isinstance(source[field], str):
                raise ValueError(f"{kind} source {field} must be a string")
        line_start = _optional_positive_int(source["line_start"], kind=kind, field="line_start")
        line_end = _optional_positive_int(source["line_end"], kind=kind, field="line_end")
        if line_start is not None and line_end is not None and line_end < line_start:
            raise ValueError(f"{kind} source line range is invalid")


def _optional_positive_int(value: Any, *, kind: str, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{kind} source {field} must be a positive integer or null")
    return value


__all__ = [
    "CONCEPT_INDEX_VERSION",
    "CONCEPT_RESOURCE_VERSION",
    "GUARDRAIL_INDEX_VERSION",
    "GUARDRAIL_RESOURCE_VERSION",
    "StaticKnowledgeCatalog",
    "StaticKnowledgeCatalogs",
    "StaticKnowledgeResource",
    "build_knowledge_catalogs",
]
