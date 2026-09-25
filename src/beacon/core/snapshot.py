"""Canonical static snapshot core for Beacon v0.2 (WP3).

Builds the ``beacon-snapshot`` v1.0 JSON payload from an existing manifest and
its canonical docs, matching ``docs/schemas/beacon-snapshot-1.0.schema.json``.
This module is the export *core* only -- it does no CLI work and never touches
``main.py``.

It reuses the established machinery rather than re-parsing anything:

* :func:`beacon.core.loader.load_beacon_manifest` -- the only manifest parser;
* :func:`beacon.core.validator.validate_beacon_manifest` /
  :func:`beacon.core.policy.evaluate_policy` -- errors and unresolved publication
  warnings block before any output;
* :class:`beacon.core.doc_index.DocIndex` -- deterministic heading-chunk line
  ranges and embedded chunk text;
* :func:`beacon.core.paths.resolve_canonical_path` -- no escaping or dangling
  docs;
* :func:`beacon.core.limits.read_bytes_bounded` and
  :class:`beacon.core.limits.ResourceLimits` -- exact bounded source digests and
  every ceiling check;
* :mod:`beacon.core.security` -- high-confidence scan of manifest values/paths
  and (embedded mode only) full doc bodies, with export-context overrides;
* :mod:`beacon.core.canonical_json` -- deterministic bounded UTF-8 bytes and
  atomic file output.

The output is value-oriented and immutable. Canonical content never contains
timestamps, host identifiers, absolute paths, or environment values. Findings
return only metadata (code/path/line), never matched secret values.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from beacon import __version__
from beacon.core.canonical_json import dumps_canonical, write_atomic
from beacon.core.doc_index import DocIndex
from beacon.core.limits import (
    LIMIT_DOCUMENT_BYTES,
    LIMIT_MANIFEST_BYTES,
    LIMIT_TOTAL_DOCUMENT_BYTES,
    LimitError,
    ResourceLimits,
    read_bytes_bounded,
)
from beacon.core.loader import load_beacon_manifest
from beacon.core.paths import is_unsafe_path, resolve_canonical_path
from beacon.core.policy import Acknowledgement, PolicyEvaluation, evaluate_policy
from beacon.core.schema import BeaconDoc, BeaconManifest, served_manifest_payload
from beacon.core.security import (
    CONTEXT_EXPORT,
    SecurityFinding,
    SecurityOverride,
    classify_path,
    detect_sensitive_text,
    resolve_security_overrides,
)
from beacon.core.serving_policy import CONTEXT_EXPORT as SERVING_EXPORT
from beacon.core.serving_policy import manifest_for_context
from beacon.core.validator import validate_beacon_manifest

#: Canonical snapshot schema version (independent of product/manifest versions).
SNAPSHOT_VERSION = "1.0"

#: Standard snapshot byte ceiling (matches the frozen :class:`ResourceLimits`
#: default); used when a :class:`Snapshot` is constructed without an explicit one.
_STANDARD_SNAPSHOT_CEILING = ResourceLimits().snapshot_bytes

#: Fixed generator distribution name.
GENERATOR_DISTRIBUTION = "archolith-beacon"

#: ``content_mode``: embed each heading chunk's text once.
CONTENT_EMBEDDED = "embedded"

#: ``content_mode``: metadata, structure, and hashes, but no chunk text.
CONTENT_METADATA_ONLY = "metadata_only"

#: All recognised content modes.
CONTENT_MODES = frozenset({CONTENT_EMBEDDED, CONTENT_METADATA_ONLY})

#: Manifest fields sufficient to identify a project without loading concepts,
#: guardrails, document inventory, or document bodies.
_IDENTITY_MANIFEST_KEYS = ("project", "purpose", "audiences", "current_focus")

#: Stable snapshot-core error codes.
SNAPSHOT_INVALID_CONTENT_MODE = "snapshot_invalid_content_mode"
SNAPSHOT_BLOCKED_POLICY = "snapshot_blocked_policy"
SNAPSHOT_BLOCKED_SECURITY = "snapshot_blocked_security"
SNAPSHOT_UNSAFE_MANIFEST_PATH = "snapshot_unsafe_manifest_path"
SNAPSHOT_SOURCE_CHANGED = "snapshot_source_changed"


class SnapshotError(ValueError):
    """Raised when a snapshot cannot be built (policy, security, or input).

    ``code`` is a stable, non-secret diagnostic string. ``findings`` (when
    present) carries only :class:`SecurityFinding` metadata, never matched
    values or document content.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        findings: tuple[SecurityFinding, ...] = (),
    ) -> None:
        self.code = code
        self.findings = findings
        super().__init__(message)


# ---------------------------------------------------------------------------
# Immutable, value-oriented snapshot types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotGenerator:
    """The tool that produced the snapshot."""

    distribution: str
    version: str


@dataclass(frozen=True)
class SnapshotProject:
    """Project identity carried in the snapshot."""

    name: str
    status: str
    repository: str = ""


@dataclass(frozen=True)
class SnapshotManifest:
    """Canonical serialized manifest plus its exact source digest."""

    beacon_version: str
    source_sha256: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SnapshotChunk:
    """One heading-scoped chunk with a 1-based line range.

    ``text`` is ``None`` in metadata-only mode so serialization omits it.
    """

    heading_path: tuple[str, ...]
    line_start: int
    line_end: int
    text: str | None = None


@dataclass(frozen=True)
class SnapshotDocument:
    """One canonical document's metadata, digest, and chunks."""

    path: str
    role: str
    status: str
    title: str
    source_sha256: str
    chunks: tuple[SnapshotChunk, ...] = ()


@dataclass(frozen=True)
class PolicyRecord:
    """A recorded acknowledgement or security override (code + reason)."""

    code: str
    reason: str


@dataclass(frozen=True)
class SnapshotValidation:
    """Policy disposition recorded in the snapshot's ``validation`` block."""

    errors: int
    warnings: int
    acknowledgements: tuple[PolicyRecord, ...] = ()
    security_overrides: tuple[PolicyRecord, ...] = ()


@dataclass(frozen=True)
class Snapshot:
    """The complete immutable snapshot value.

    ``policy``, ``security_findings``, and ``byte_ceiling`` are non-serialized
    metadata for callers; they are never emitted by :meth:`to_payload`.
    """

    beacon_snapshot_version: str
    generator: SnapshotGenerator
    content_mode: str
    project: SnapshotProject
    manifest: SnapshotManifest
    documents: tuple[SnapshotDocument, ...]
    validation: SnapshotValidation
    policy: PolicyEvaluation
    security_findings: tuple[SecurityFinding, ...] = ()
    byte_ceiling: int = _STANDARD_SNAPSHOT_CEILING

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON-ready snapshot payload in schema shape."""
        manifest_data = _json_safe(self.manifest.data)
        acknowledgements = [
            {"code": a.code, "reason": a.reason} for a in self.validation.acknowledgements
        ]
        overrides = [
            {"code": o.code, "reason": o.reason} for o in self.validation.security_overrides
        ]
        return {
            "beacon_snapshot_version": self.beacon_snapshot_version,
            "generator": {
                "distribution": self.generator.distribution,
                "version": self.generator.version,
            },
            "content_mode": self.content_mode,
            "project": _project_payload(self.project),
            "manifest": {
                "beacon_version": self.manifest.beacon_version,
                "source_sha256": self.manifest.source_sha256,
                "data": manifest_data,
            },
            "documents": [_document_payload(d) for d in self.documents],
            "validation": {
                "errors": self.validation.errors,
                "warnings": self.validation.warnings,
                "acknowledgements": acknowledgements,
                "security_overrides": overrides,
            },
        }


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def build_snapshot(
    manifest_path: str | Path,
    *,
    docs_root: str | Path | None = None,
    content_mode: str = CONTENT_EMBEDDED,
    acknowledgements: Iterable[Acknowledgement] = (),
    security_overrides: Iterable[SecurityOverride] = (),
    limits: ResourceLimits | None = None,
) -> Snapshot:
    """Build a canonical static :class:`Snapshot` for *manifest_path*.

    Validation errors, unresolved publication warnings, escaping/dangling docs,
    and resource-limit breaches all refuse before any bytes are produced. All
    work is in-memory; nothing is written here. Use
    :func:`snapshot_bytes` / :func:`write_snapshot_atomic` to emit output.

    *content_mode* is ``embedded`` (default) or ``metadata_only``. In embedded
    mode the complete selected doc text is security-scanned; in metadata-only
    mode only manifest values/paths are scanned (doc bodies are still read for
    exact digests and chunk structure). *acknowledgements* and
    *security_overrides* are the v0.2 reasoned overrides (export context).
    """
    active = limits if limits is not None else ResourceLimits()
    _require_content_mode(content_mode)
    acknowledgements = tuple(acknowledgements)
    security_overrides = tuple(security_overrides)

    # -- read bounded manifest bytes, load, then verify the bytes are stable --
    # Guard against a TOCTOU change between the exact-digest read and the parse
    # so the recorded digest always matches the data we actually exported.
    manifest_path = Path(manifest_path)
    manifest_bytes = _read_manifest_bytes(manifest_path, active)
    manifest = load_beacon_manifest(manifest_path, limits=active)
    _ensure_unchanged(manifest_bytes, _read_manifest_bytes(manifest_path, active))
    manifest_sha = _source_sha256(manifest_bytes)

    root = Path(docs_root) if docs_root is not None else manifest_path.resolve().parent
    _refuse_unsafe_manifest_paths(manifest)
    # Owner exclusions and local-only documents never leave the machine.
    manifest, _withheld = manifest_for_context(manifest, context=SERVING_EXPORT)

    # -- policy gate: errors and unresolved publication warnings block ------
    report = validate_beacon_manifest(manifest, docs_root=root)
    policy = evaluate_policy(report, acknowledgements=acknowledgements)
    if not policy.publishable:
        raise SnapshotError(
            SNAPSHOT_BLOCKED_POLICY,
            "snapshot blocked: validation errors or unresolved publication warnings",
        )

    # -- read doc bytes, build the index, then verify each doc is stable -----
    # Enforce the aggregate total *before* retaining each additional body so a
    # many-document manifest cannot accumulate documents*document_bytes in memory.
    doc_bytes: dict[str, bytes] = {}
    cumulative_bytes = 0
    for doc in manifest.canonical_docs:
        data = _read_doc_bytes(doc.path, root, active)
        cumulative_bytes += len(data)
        if cumulative_bytes > active.total_document_bytes:
            raise LimitError(
                LIMIT_TOTAL_DOCUMENT_BYTES,
                "resource limit exceeded: "
                f"{LIMIT_TOTAL_DOCUMENT_BYTES} (limit={active.total_document_bytes}, "
                f"actual={cumulative_bytes})",
                limit="total_document_bytes",
                limit_value=active.total_document_bytes,
            )
        doc_bytes[doc.path] = data
    doc_index = DocIndex.from_docs(manifest.canonical_docs, docs_root=root, limits=active)
    for doc in manifest.canonical_docs:
        _ensure_unchanged(doc_bytes[doc.path], _read_doc_bytes(doc.path, root, active))
    doc_digests = {path: _source_sha256(data) for path, data in doc_bytes.items()}
    doc_texts = {path: data.decode("utf-8", errors="replace") for path, data in doc_bytes.items()}

    # -- security gate (metadata findings only) -----------------------------
    findings = _manifest_findings(manifest, manifest.canonical_docs)
    if content_mode == CONTENT_EMBEDDED:
        for doc in manifest.canonical_docs:
            if _snapshot_embeds_body(doc):
                findings.extend(detect_sensitive_text(doc_texts[doc.path], path=doc.path))
    security_result = resolve_security_overrides(
        findings, security_overrides, context=CONTEXT_EXPORT
    )
    if not security_result.allowed():
        raise SnapshotError(
            SNAPSHOT_BLOCKED_SECURITY,
            "snapshot blocked: high-confidence sensitive content requires an override",
            findings=security_result.blocked,
        )

    # -- assemble value -----------------------------------------------------
    applied_override_codes = {override.code for _, override in security_result.overridden}
    documents = _build_documents(
        manifest.canonical_docs,
        doc_index=doc_index,
        doc_digests=doc_digests,
        content_mode=content_mode,
    )
    validation = SnapshotValidation(
        errors=len(policy.errors),
        warnings=len(report.warnings),
        acknowledgements=tuple(
            PolicyRecord(code=ack.code, reason=ack.reason) for _, ack in policy.acknowledged
        ),
        security_overrides=tuple(
            PolicyRecord(code=override.code, reason=override.reason)
            for override in security_overrides
            if override.code in applied_override_codes
        ),
    )
    return Snapshot(
        beacon_snapshot_version=SNAPSHOT_VERSION,
        generator=SnapshotGenerator(distribution=GENERATOR_DISTRIBUTION, version=__version__),
        content_mode=content_mode,
        project=SnapshotProject(
            name=manifest.project.name,
            status=manifest.project.status,
            repository=manifest.project.repository,
        ),
        manifest=SnapshotManifest(
            beacon_version=manifest.beacon_version,
            source_sha256=manifest_sha,
            data=_json_safe(served_manifest_payload(manifest)),
        ),
        documents=documents,
        validation=validation,
        policy=policy,
        security_findings=tuple(findings),
        byte_ceiling=active.snapshot_bytes,
    )


def metadata_only_snapshot(snapshot: Snapshot) -> Snapshot:
    """Return a metadata-only representation derived from *snapshot* in memory.

    The returned value preserves project, manifest, document, validation,
    policy, digest, and line-range identity while removing every chunk body.
    No source path is opened and no security or publication decision is
    recomputed, so callers can safely precompute multiple representations from
    one approved startup source set.
    """
    _require_content_mode(snapshot.content_mode)
    if snapshot.content_mode == CONTENT_METADATA_ONLY:
        return snapshot

    documents = tuple(
        replace(
            document,
            chunks=tuple(replace(chunk, text=None) for chunk in document.chunks),
        )
        for document in snapshot.documents
    )
    return replace(snapshot, content_mode=CONTENT_METADATA_ONLY, documents=documents)


def identity_snapshot(snapshot: Snapshot) -> Snapshot:
    """Return the smallest project-identity representation of *snapshot*.

    Identity preserves the approved startup manifest/source digest and the
    project, purpose, audiences, and current-focus fields. Canonical document
    metadata and bodies are omitted. The transformation is deterministic and
    performs no file I/O.
    """
    _require_content_mode(snapshot.content_mode)
    identity_data = {
        key: _json_safe(snapshot.manifest.data[key])
        for key in _IDENTITY_MANIFEST_KEYS
        if key in snapshot.manifest.data
    }
    manifest = replace(snapshot.manifest, data=identity_data)
    return replace(
        snapshot,
        content_mode=CONTENT_METADATA_ONLY,
        manifest=manifest,
        documents=(),
    )


def snapshot_bytes(snapshot: Snapshot, *, byte_ceiling: int | None = None) -> bytes:
    """Serialize *snapshot* to deterministic bounded UTF-8 JSON + one newline.

    When *byte_ceiling* is ``None`` the snapshot's effective ``snapshot_bytes``
    ceiling is used.
    """
    ceiling = snapshot.byte_ceiling if byte_ceiling is None else byte_ceiling
    return dumps_canonical(snapshot.to_payload(), byte_ceiling=ceiling)


def write_snapshot_atomic(
    path: str | Path, snapshot: Snapshot, *, byte_ceiling: int | None = None
) -> None:
    """Atomically replace *path* with the canonical snapshot JSON.

    The payload is validated and size-checked before any file is created, so an
    oversized snapshot refuses without touching the destination and leaves no
    temporary artifact. When *byte_ceiling* is ``None`` the snapshot's effective
    ``snapshot_bytes`` ceiling is used.
    """
    ceiling = snapshot.byte_ceiling if byte_ceiling is None else byte_ceiling
    write_atomic(path, snapshot.to_payload(), byte_ceiling=ceiling)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_content_mode(content_mode: str) -> None:
    if content_mode not in CONTENT_MODES:
        raise SnapshotError(
            SNAPSHOT_INVALID_CONTENT_MODE,
            f"invalid content_mode: expected one of {sorted(CONTENT_MODES)}",
        )


def _source_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_manifest_bytes(path: Path, limits: ResourceLimits) -> bytes:
    return read_bytes_bounded(
        path,
        ceiling=limits.manifest_bytes,
        code=LIMIT_MANIFEST_BYTES,
        field="manifest_bytes",
    )


def _read_doc_bytes(path: str, root: Path, limits: ResourceLimits) -> bytes:
    """Read the exact bounded bytes of one canonical doc."""
    target = resolve_canonical_path(root, path)
    return read_bytes_bounded(
        target,
        ceiling=limits.document_bytes,
        code=LIMIT_DOCUMENT_BYTES,
        field="document_bytes",
    )


def _ensure_unchanged(before: bytes, after: bytes) -> None:
    """Refuse when a source file changed between two bounded reads.

    Raises :class:`SnapshotError` with the fixed ``snapshot_source_changed``
    code and no path or content detail.
    """
    if before != after:
        raise SnapshotError(
            SNAPSHOT_SOURCE_CHANGED,
            "snapshot source changed during read",
        )


def _manifest_findings(
    manifest: BeaconManifest, docs: tuple[BeaconDoc, ...]
) -> list[SecurityFinding]:
    """Scan canonical manifest values and doc paths for sensitive content.

    The canonical manifest is serialized deterministically and scanned for
    credential URLs / tokens / private keys; each doc path is classified and
    scanned. Returns only metadata (code/path/line), never matched values.
    """
    findings: list[SecurityFinding] = []
    manifest_text = json.dumps(
        asdict(manifest),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    findings.extend(detect_sensitive_text(manifest_text, path="beacon.yaml"))
    for doc in docs:
        classified = classify_path(doc.path)
        if classified is not None:
            findings.append(classified)
        findings.extend(detect_sensitive_text(doc.path, path=doc.path))
    return findings


def _build_documents(
    docs: tuple[BeaconDoc, ...],
    *,
    doc_index: DocIndex,
    doc_digests: dict[str, str],
    content_mode: str,
) -> tuple[SnapshotDocument, ...]:
    """Assemble snapshot documents in manifest order with chunk line ranges.

    Chunk order follows :class:`DocIndex` order (document order, then heading
    order). Embedded mode keeps each chunk's text; metadata-only drops it.
    Plan-role documents are intentionally title-only in either mode: their
    document metadata and source digest remain, but their chunks are omitted.
    """
    chunks_by_path: dict[str, list[SnapshotChunk]] = {}
    for chunk in doc_index.chunks:
        chunks_by_path.setdefault(chunk.path, []).append(
            SnapshotChunk(
                heading_path=chunk.heading_path,
                line_start=chunk.start_line,
                line_end=chunk.end_line,
                text=chunk.text if content_mode == CONTENT_EMBEDDED else None,
            )
        )
    documents: list[SnapshotDocument] = []
    for doc in docs:
        documents.append(
            SnapshotDocument(
                path=doc.path,
                role=doc.role,
                status=doc.status,
                title=doc.title,
                source_sha256=doc_digests[doc.path],
                chunks=(
                    tuple(chunks_by_path.get(doc.path, ())) if _snapshot_embeds_body(doc) else ()
                ),
            )
        )
    return tuple(documents)


def _snapshot_embeds_body(doc: BeaconDoc) -> bool:
    """Return whether a snapshot may carry *doc*'s body.

    Plan bodies remain available to the local MCP provider and its in-memory
    index. Static snapshots expose only plan metadata until a reviewed
    summarization/exposure policy replaces this conservative role boundary.
    """
    role = doc.role.strip().lower()
    return role != "plan" and not role.endswith("_plan")


def _refuse_unsafe_manifest_paths(manifest: BeaconManifest) -> None:
    """Refuse manifest path metadata that is absolute or escapes the root.

    Canonical snapshot content must never carry local absolute paths, so the
    path-bearing manifest fields (concept implementation locations, source
    paths, guardrail applies-to, guidance read/avoid paths), local ``file://``
    URLs in the project repository or source URLs, and absolute paths inside
    build/test command fields are all checked. A violation raises
    :class:`SnapshotError` with a stable code whose message names the manifest
    field (for example ``build_and_test.test``) but never the offending value.
    """
    candidates: list[tuple[str, str]] = []
    for concept in manifest.core_concepts:
        candidates.extend(
            ("core_concepts[].implementation_locations", value)
            for value in concept.implementation_locations
        )
        candidates.extend(("core_concepts[].sources[].path", s.path) for s in concept.sources)
        candidates.extend(("core_concepts[].sources[].url", s.url) for s in concept.sources)
    for guard in manifest.guardrails:
        candidates.extend(("guardrails[].applies_to", value) for value in guard.applies_to)
        candidates.extend(("guardrails[].sources[].path", s.path) for s in guard.sources)
        candidates.extend(("guardrails[].sources[].url", s.url) for s in guard.sources)
    state_items = (
        (
            ()
            if manifest.project_state.active_work is None
            else (manifest.project_state.active_work,)
        )
        + manifest.project_state.recently_completed
        + manifest.project_state.blockers
        + manifest.project_state.pending_decisions
    )
    for item in state_items:
        candidates.extend(("project_state.sources[].path", s.path) for s in item.sources)
        candidates.extend(("project_state.sources[].url", s.url) for s in item.sources)
    for decision in manifest.decisions:
        candidates.append(("decisions[].path", decision.path))
        candidates.extend(("decisions[].sources[].path", s.path) for s in decision.sources)
    candidates.extend(
        ("agent_guidance.read_first", value) for value in manifest.agent_guidance.read_first
    )
    candidates.extend(
        ("agent_guidance.avoid_without_review", value)
        for value in manifest.agent_guidance.avoid_without_review
    )
    for field_name, candidate in candidates:
        if is_unsafe_path(candidate) or _is_local_file_url(candidate):
            _raise_unsafe_manifest_path(field_name)
    if _is_local_file_url(manifest.project.repository) or is_unsafe_path(
        manifest.project.repository
    ):
        _raise_unsafe_manifest_path("project.repository")
    for field_name, command in (
        ("build_and_test.setup", manifest.build_and_test.setup),
        ("build_and_test.test", manifest.build_and_test.test),
        ("build_and_test.benchmark", manifest.build_and_test.benchmark),
    ):
        if _command_has_absolute_path(command):
            _raise_unsafe_manifest_path(field_name)


def _raise_unsafe_manifest_path(field_name: str) -> None:
    # *field_name* is a fixed manifest field name chosen by the caller, never a value.
    raise SnapshotError(
        SNAPSHOT_UNSAFE_MANIFEST_PATH,
        f"snapshot refused: absolute or escaping manifest path in {field_name}",
    )


def _is_local_file_url(value: str) -> bool:
    return value.lower().startswith("file://")


def _command_has_absolute_path(command: str) -> bool:
    for raw_token in command.split():
        token = _unquote(raw_token)
        if _is_absolute_like(token):
            return True
        if "=" in token:
            _, _, value = token.partition("=")
            if _is_absolute_like(value):
                return True
    return False


def _unquote(token: str) -> str:
    if token.startswith(("'", '"')):
        token = token[1:]
    if token.endswith(("'", '"')):
        token = token[:-1]
    return token


def _is_absolute_like(word: str) -> bool:
    """Return whether a command word is (or embeds) an absolute filesystem path.

    Refused: a Windows drive path (``C:\\x``, ``C:/x``), a UNC or rooted
    backslash path (``\\\\server\\share``, ``\\x``), a ``//`` network path,
    the POSIX root ``/``, and any POSIX path with at least two segments
    (``/usr/bin/python``). Not refused: switch-style tokens such as
    ``/t:Build``, ``/p:Configuration=Release``, ``/nologo`` or ``/m``, and
    non-path colons such as ``a:b`` or ``test:unit``. The value of a switch
    (after ``:`` and ``=``) is still checked, so ``/p:OutDir=C:\\out`` is
    refused.
    """
    if _WINDOWS_DRIVE_PATH_RE.match(word):
        return True
    if word.startswith("\\") or word.startswith("//") or word == "/":
        return True
    if not word.startswith("/"):
        return False
    switch = _SWITCH_RE.match(word)
    if switch is not None:
        value = switch.group("value") or ""
        _, _, assigned = value.partition("=")
        return any(_is_absolute_like(part) for part in (value, assigned) if part)
    return "/" in word[1:]


#: ``C:\\...`` or ``C:/...`` (a drive letter followed by a separator).
_WINDOWS_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
#: A ``/name`` or ``/name:value`` switch (MSBuild/dotnet/cmd style).
_SWITCH_RE = re.compile(r"^/(?P<name>[A-Za-z?][A-Za-z0-9_.?-]*)(?::(?P<value>.*))?$")


def _json_safe(data: Any) -> Any:
    """Return a JSON-serializable deep copy.

    ``dataclasses.asdict`` leaves tuples as tuples (it does not convert them to
    lists), so this recursively converts tuples to lists, lists to lists, and
    leaves every other JSON scalar untouched. Nested dataclasses are already
    expanded to dicts by the caller's ``asdict``.
    """
    if isinstance(data, dict):
        return {key: _json_safe(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_json_safe(item) for item in data]
    return data


def _project_payload(project: SnapshotProject) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": project.name, "status": project.status}
    if project.repository:
        payload["repository"] = project.repository
    return payload


def _document_payload(document: SnapshotDocument) -> dict[str, Any]:
    chunks: list[dict[str, Any]] = []
    for chunk in document.chunks:
        entry: dict[str, Any] = {
            "heading_path": list(chunk.heading_path),
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
        }
        if chunk.text is not None:
            entry["text"] = chunk.text
        chunks.append(entry)
    return {
        "path": document.path,
        "role": document.role,
        "status": document.status,
        "title": document.title,
        "source_sha256": document.source_sha256,
        "chunks": chunks,
    }


__all__ = [
    "CONTENT_EMBEDDED",
    "CONTENT_METADATA_ONLY",
    "CONTENT_MODES",
    "GENERATOR_DISTRIBUTION",
    "SNAPSHOT_BLOCKED_POLICY",
    "SNAPSHOT_BLOCKED_SECURITY",
    "SNAPSHOT_INVALID_CONTENT_MODE",
    "SNAPSHOT_SOURCE_CHANGED",
    "SNAPSHOT_UNSAFE_MANIFEST_PATH",
    "SNAPSHOT_VERSION",
    "PolicyRecord",
    "Snapshot",
    "SnapshotChunk",
    "SnapshotDocument",
    "SnapshotError",
    "SnapshotGenerator",
    "SnapshotManifest",
    "SnapshotProject",
    "SnapshotValidation",
    "build_snapshot",
    "identity_snapshot",
    "metadata_only_snapshot",
    "snapshot_bytes",
    "write_snapshot_atomic",
]
