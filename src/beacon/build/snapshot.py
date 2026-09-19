"""Snapshot reader: load a canonical v1.0 snapshot instead of re-reading a repo.

This is the reverse of the v0.2 export path. The writer
(:mod:`beacon.core.snapshot`) reads a manifest plus its canonical documents,
computes exact digests, and emits canonical JSON; this reader loads those
bytes back into the same immutable :class:`~beacon.core.snapshot.Snapshot`
value so the server can run snapshot-only and an artifact stays portable.

The reader is deliberately strict:

* the payload must declare ``beacon_snapshot_version`` ``"1.0"`` and a known
  ``content_mode``;
* a snapshot carrying validation errors is refused (the schema makes
  ``validation.errors`` a ``0`` const; the reader enforces the same rule);
* digests must be 64-char hex strings;
* every document chunk must carry a text body in ``embedded`` mode and no
  text in ``metadata_only`` mode;
* the input is read under the ``snapshot_bytes`` ceiling and size-checked.

No digest is recomputed here: a snapshot is an immutable artifact whose
digests were computed at export time over the exact source bytes. Loading
verifies structure and consistency, not provenance.
"""

from __future__ import annotations

import json
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any

from beacon.core.canonical_json import dumps_canonical
from beacon.core.limits import ResourceLimits
from beacon.core.policy import PolicyEvaluation
from beacon.core.snapshot import (
    CONTENT_EMBEDDED,
    CONTENT_METADATA_ONLY,
    CONTENT_MODES,
    GENERATOR_DISTRIBUTION,
    SNAPSHOT_VERSION,
    PolicyRecord,
    Snapshot,
    SnapshotChunk,
    SnapshotDocument,
    SnapshotGenerator,
    SnapshotManifest,
    SnapshotProject,
    SnapshotValidation,
)

#: Stable reader refusal codes.
SNAPSHOT_READER_BAD_VERSION = "snapshot_reader_bad_version"
SNAPSHOT_READER_MALFORMED = "snapshot_reader_malformed"
SNAPSHOT_READER_CARRIES_ERRORS = "snapshot_reader_carries_errors"
SNAPSHOT_READER_TOO_LARGE = "snapshot_reader_too_large"
SNAPSHOT_READER_UNREADABLE = "snapshot_reader_unreadable"

_HEX = frozenset("0123456789abcdef")


class SnapshotReadError(ValueError):
    """A snapshot could not be loaded; ``code`` is a stable diagnostic."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def load_snapshot(
    path: str | Path,
    *,
    limits: ResourceLimits | None = None,
) -> Snapshot:
    """Load and structurally verify a canonical snapshot from *path*."""
    active = limits if limits is not None else ResourceLimits()
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise SnapshotReadError(SNAPSHOT_READER_UNREADABLE, "snapshot unreadable") from exc
    if len(raw) > active.snapshot_bytes:
        raise SnapshotReadError(
            SNAPSHOT_READER_TOO_LARGE,
            f"snapshot exceeds the byte ceiling ({len(raw)} > {active.snapshot_bytes})",
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotReadError(SNAPSHOT_READER_MALFORMED, "snapshot is not valid JSON") from exc
    snapshot = snapshot_from_payload(payload)
    if snapshot.byte_ceiling != active.snapshot_bytes:
        snapshot = dataclass_replace(snapshot, byte_ceiling=active.snapshot_bytes)
    return snapshot


def snapshot_from_payload(payload: Any) -> Snapshot:
    """Validate a decoded snapshot payload and reconstruct the Snapshot value."""
    if not isinstance(payload, dict):
        raise SnapshotReadError(SNAPSHOT_READER_MALFORMED, "snapshot must be a JSON object")

    version = payload.get("beacon_snapshot_version")
    if version != SNAPSHOT_VERSION:
        raise SnapshotReadError(
            SNAPSHOT_READER_BAD_VERSION,
            f"unsupported beacon_snapshot_version {version!r}; supported: {SNAPSHOT_VERSION!r}",
        )
    content_mode = payload.get("content_mode")
    if content_mode not in CONTENT_MODES:
        raise SnapshotReadError(
            SNAPSHOT_READER_MALFORMED,
            f"invalid content_mode: expected one of {sorted(CONTENT_MODES)}",
        )

    generator = payload.get("generator") or {}
    project = payload.get("project") or {}
    manifest = payload.get("manifest") or {}
    documents = payload.get("documents")
    validation = payload.get("validation") or {}
    if not isinstance(generator, dict) or not isinstance(project, dict):
        raise SnapshotReadError(SNAPSHOT_READER_MALFORMED, "invalid generator/project block")
    if not isinstance(manifest, dict) or not isinstance(documents, list):
        raise SnapshotReadError(SNAPSHOT_READER_MALFORMED, "invalid manifest/documents block")
    if not isinstance(validation, dict):
        raise SnapshotReadError(SNAPSHOT_READER_MALFORMED, "invalid validation block")
    if generator.get("distribution") != GENERATOR_DISTRIBUTION:
        raise SnapshotReadError(SNAPSHOT_READER_MALFORMED, "unexpected snapshot generator")

    errors = validation.get("errors")
    warnings = validation.get("warnings")
    if not isinstance(errors, int) or not isinstance(warnings, int):
        raise SnapshotReadError(SNAPSHOT_READER_MALFORMED, "invalid validation counters")
    if errors != 0:
        raise SnapshotReadError(
            SNAPSHOT_READER_CARRIES_ERRORS,
            "refusing to load a snapshot that carries validation errors",
        )

    manifest_data = manifest.get("data")
    if not isinstance(manifest_data, dict):
        raise SnapshotReadError(
            SNAPSHOT_READER_MALFORMED, "snapshot manifest data must be an object"
        )
    source_sha = str(manifest.get("source_sha256") or "")
    if len(source_sha) != 64 or any(char not in _HEX for char in source_sha):
        raise SnapshotReadError(SNAPSHOT_READER_MALFORMED, "invalid manifest source_sha256")

    name = str(project.get("name") or "")
    if not name:
        raise SnapshotReadError(SNAPSHOT_READER_MALFORMED, "snapshot project name is required")

    parsed_documents = tuple(
        _document(item, index, content_mode) for index, item in enumerate(documents)
    )

    distribution = str(generator.get("distribution") or GENERATOR_DISTRIBUTION)
    generator_version = str(generator.get("version") or "")
    return Snapshot(
        beacon_snapshot_version=SNAPSHOT_VERSION,
        generator=SnapshotGenerator(distribution=distribution, version=generator_version),
        content_mode=str(content_mode),
        project=SnapshotProject(
            name=name,
            status=str(project.get("status") or ""),
            repository=str(project.get("repository") or ""),
        ),
        manifest=SnapshotManifest(
            beacon_version=str(manifest.get("beacon_version") or ""),
            source_sha256=source_sha,
            data=manifest_data,
        ),
        documents=parsed_documents,
        validation=SnapshotValidation(
            errors=errors,
            warnings=warnings,
            acknowledgements=tuple(
                PolicyRecord(code=str(row.get("code") or ""), reason=str(row.get("reason") or ""))
                for row in validation.get("acknowledgements") or []
                if isinstance(row, dict)
            ),
            security_overrides=tuple(
                PolicyRecord(code=str(row.get("code") or ""), reason=str(row.get("reason") or ""))
                for row in validation.get("security_overrides") or []
                if isinstance(row, dict)
            ),
        ),
        policy=PolicyEvaluation(servable=True, publishable=True),
    )


def _strip_none_values(value: Any) -> Any:
    """Remove ``None``-valued mapping entries recursively (in place).

    The snapshot embeds the manifest via ``dataclasses.asdict``, which
    serializes absent optional fields (source line ranges, an absent
    ``project_state.active_work``) as explicit ``null``. The loader treats
    explicit nulls as malformed, so the reader adapts the embedded form to
    the loader's "absent key" convention before parsing.
    """
    if isinstance(value, dict):
        return {key: _strip_none_values(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_strip_none_values(item) for item in value]
    return value


def _document(item: Any, index: int, content_mode: str) -> SnapshotDocument:
    if not isinstance(item, dict):
        raise SnapshotReadError(SNAPSHOT_READER_MALFORMED, f"documents[{index}] must be an object")
    digest = str(item.get("source_sha256") or "")
    if len(digest) != 64 or any(char not in _HEX for char in digest):
        raise SnapshotReadError(
            SNAPSHOT_READER_MALFORMED, f"documents[{index}] has an invalid source_sha256"
        )
    chunks_raw = item.get("chunks") or []
    if not isinstance(chunks_raw, list):
        raise SnapshotReadError(
            SNAPSHOT_READER_MALFORMED, f"documents[{index}].chunks must be a list"
        )
    chunks: list[SnapshotChunk] = []
    for position, chunk in enumerate(chunks_raw):
        if not isinstance(chunk, dict):
            raise SnapshotReadError(
                SNAPSHOT_READER_MALFORMED,
                f"documents[{index}].chunks[{position}] must be an object",
            )
        heading = chunk.get("heading_path") or []
        if not isinstance(heading, list) or not all(isinstance(part, str) for part in heading):
            raise SnapshotReadError(
                SNAPSHOT_READER_MALFORMED,
                f"documents[{index}].chunks[{position}].heading_path must be a list of strings",
            )
        line_start = chunk.get("line_start")
        line_end = chunk.get("line_end")
        if not isinstance(line_start, int) or not isinstance(line_end, int):
            raise SnapshotReadError(
                SNAPSHOT_READER_MALFORMED,
                f"documents[{index}].chunks[{position}] has invalid line range",
            )
        text = chunk.get("text")
        if content_mode == CONTENT_EMBEDDED and not isinstance(text, str):
            raise SnapshotReadError(
                SNAPSHOT_READER_MALFORMED,
                f"documents[{index}].chunks[{position}] lacks embedded text",
            )
        if content_mode == CONTENT_METADATA_ONLY and text is not None:
            raise SnapshotReadError(
                SNAPSHOT_READER_MALFORMED,
                f"documents[{index}].chunks[{position}] carries text in metadata-only mode",
            )
        chunks.append(
            SnapshotChunk(
                heading_path=tuple(heading),
                line_start=line_start,
                line_end=line_end,
                text=text,
            )
        )
    return SnapshotDocument(
        path=str(item.get("path") or ""),
        role=str(item.get("role") or ""),
        status=str(item.get("status") or ""),
        title=str(item.get("title") or ""),
        source_sha256=digest,
        chunks=tuple(chunks),
    )


def reserialize_snapshot(snapshot: Snapshot) -> bytes:
    """Serialize a loaded snapshot back to canonical bytes (round-trip check)."""
    return dumps_canonical(snapshot.to_payload(), byte_ceiling=snapshot.byte_ceiling)


__all__ = [
    "SNAPSHOT_READER_BAD_VERSION",
    "SNAPSHOT_READER_CARRIES_ERRORS",
    "SNAPSHOT_READER_MALFORMED",
    "SNAPSHOT_READER_TOO_LARGE",
    "SNAPSHOT_READER_UNREADABLE",
    "SnapshotReadError",
    "load_snapshot",
    "reserialize_snapshot",
    "snapshot_from_payload",
]
