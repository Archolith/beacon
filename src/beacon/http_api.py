"""Loopback HTTP surface for an immutable Beacon snapshot.

Builds a small :class:`starlette.applications.Starlette` ASGI app over an
already-built :class:`beacon.core.snapshot.Snapshot`. The canonical embedded,
orientation, and identity representations are each serialized exactly once
(via :func:`beacon.core.snapshot.snapshot_bytes`) and their SHA-256 digests are
computed once. Chunk index and resource responses are also precomputed. All are
retained as immutable state for the life of the app.
No source file is ever reread and no snapshot is rebuilt after construction, so
every request serves byte-identical payloads.

The module owns only the HTTP contract. It does no access logging, no socket
binding, no Uvicorn configuration, no host validation, and no CLI or network
work -- those boundaries belong to the caller.

Routes (GET and HEAD):

* ``/.well-known/archolith-beacon`` -- deterministic discovery document with
  per-route usage guidance, a recommended flow, freshness, and a trust label;
* ``/v1/snapshot/identity`` -- minimal project identity representation;
* ``/v1/snapshot/orientation`` -- metadata-only orientation representation;
* ``/v1/snapshot`` -- the canonical snapshot payload;
* ``/beacon.json`` -- byte/header-identical alias of ``/v1/snapshot``;
* ``/v1/status`` -- declared work state plus startup-observed evidence;
* ``/v1/chunks`` -- companion chunk index with byte budgets;
* ``/v1/chunks/{id}`` -- one immutable published chunk resource;
* ``/v1/concepts`` / ``/v1/concepts/{id}`` -- concept index and resources;
* ``/v1/guardrails`` / ``/v1/guardrails/{id}`` -- guardrail index and resources;
* ``/v1/decisions`` / ``/v1/decisions/{id}`` -- served-decision index and records;
* ``/v1/search``, ``/v1/read``, ``/v1/explain`` -- dynamic query routes;
* ``/healthz`` -- redacted readiness document.

The dynamic query routes call the same MCP tool classes over one
:class:`~beacon.provider.manifest_provider.ManifestBeaconProvider` built from
the snapshot, so their answers are byte-comparable to the MCP tools (rendered
in the surface's canonical JSON form). They exist only when the snapshot's
embedded manifest is servable; snapshots that carry no servable manifest keep
their static representations unchanged and the query routes fail closed with
the ordinary 404 error body.

All response bodies are canonical compact JSON ending in exactly one newline.
Unknown routes return a deterministic versioned Beacon error JSON with 404 and
unsupported methods return 405. No CORS is added and query strings are never
echoed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import Any

import anyio
import anyio.to_thread
from starlette.applications import Starlette
from starlette.datastructures import QueryParams
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from beacon import __version__
from beacon.core.canonical_json import dumps_canonical
from beacon.core.chunk_resources import CHUNK_INDEX_VERSION, build_chunk_catalog
from beacon.core.knowledge_resources import (
    CONCEPT_INDEX_VERSION,
    GUARDRAIL_INDEX_VERSION,
    build_knowledge_catalogs,
)
from beacon.core.limits import ResourceLimits
from beacon.core.loader import ManifestError
from beacon.core.snapshot import (
    CONTENT_EMBEDDED,
    Snapshot,
    SnapshotGenerator,
    identity_snapshot,
    metadata_only_snapshot,
    snapshot_bytes,
)
from beacon.core.status import STATUS_VERSION, StatusObservation, build_status_payload
from beacon.core.validator import ManifestValidationError
from beacon.mcp.contracts import BeaconBaseTool
from beacon.mcp.tools.explain_concept import ExplainConceptTool
from beacon.mcp.tools.read import ReadTool
from beacon.mcp.tools.search import SearchTool
from beacon.provider.manifest_provider import ManifestBeaconProvider

#: Discovery descriptor version.
_DESCRIPTOR_VERSION = "1.7"

#: Error envelope version shared by every error body.
_ERROR_VERSION = "1.0"

#: Decision index version.
_DECISION_INDEX_VERSION = "1.0"

#: Redacted readiness mode.
_STARTUP_MODE = "immutable_snapshot"

#: Loopback scope reported by discovery.
_SCOPE = "loopback"

#: Discovery authentication model.
_AUTHENTICATION = "none"

#: Trust level reported by discovery: direct access with nothing verified yet.
_TRUST = "direct_unverified"

#: One-line trust note accompanying :data:`_TRUST`.
_TRUST_NOTE = "direct, unverified access: no signing and no trust broker yet"

#: One-line usage guidance per resource family (static and factual).
_FAMILY_USE_WHEN = {
    "status": "check how fresh the snapshot and repository evidence are",
    "chunks": "read document text in heading-sized chunks by stable id",
    "concepts": "list core concepts and find their ids",
    "guardrails": "read the rules to respect before making changes",
    "decisions": "why the project is built this way",
}

#: One-line usage guidance per dynamic query route.
_DYNAMIC_USE_WHEN = {
    "search": "find documents, concepts, decisions or guardrails by keywords",
    "read": "read one section by chunk id, path or heading; continue with offset",
    "explain": "explain one concept in depth",
}

#: The first recommended step, served whether or not the manifest is servable.
_FLOW_IDENTIFY = {
    "step": "identify",
    "url": "/v1/snapshot/identity",
    "use_when": "start here: learn which project and snapshot this is",
}

#: The final recommended step, served whether or not the manifest is servable.
_FLOW_GUARDRAILS = {
    "step": "guardrails",
    "url": "/v1/guardrails",
    "use_when": "before making changes: read the guardrails",
}

#: Middle steps served only when the dynamic routes exist.
_FLOW_SERVABLE_STEPS = (
    {
        "step": "why_search",
        "url": "/v1/search",
        "use_when": "for a why question: search with types=decisions",
    },
    {
        "step": "why_decision",
        "url": "/v1/decisions/{id}",
        "use_when": "read the decision the why search found",
    },
    {
        "step": "search",
        "url": "/v1/search",
        "use_when": "for any other question: search by keywords",
    },
    {
        "step": "read",
        "url": "/v1/read",
        "use_when": "read the section a search hit points to; pass offset to continue",
    },
    {
        "step": "explain",
        "url": "/v1/explain",
        "use_when": "alternative to read or the decision record: explain one concept",
    },
)


def create_http_app(
    snapshot: Snapshot,
    *,
    status_observation: StatusObservation | None = None,
    limits: ResourceLimits | None = None,
) -> Starlette:
    """Return a Starlette app serving an immutable view of *snapshot*.

    The snapshot is serialized to canonical bytes exactly once here; all
    requests thereafter serve that immutable payload. Discovery and health are
    likewise derived once and cached, so no request performs I/O or recomputes
    digests. One provider is built from the same snapshot with *limits* (the
    CLI ceilings) and backs the dynamic query routes; it reuses
    :meth:`ManifestBeaconProvider.from_snapshot`, exactly as MCP-over-HTTP
    serving does.
    """
    if snapshot.content_mode != CONTENT_EMBEDDED:
        raise ValueError("HTTP snapshot must use embedded content mode")

    try:
        provider = ManifestBeaconProvider.from_snapshot(snapshot, limits=limits)
    except (ManifestError, ManifestValidationError):
        # A snapshot whose embedded manifest is not servable keeps its static
        # representations and fails the query routes closed (404). Snapshots
        # built by ``build_snapshot`` always validate; this only guards
        # synthetic snapshots, and the reason is never reported (the refusal
        # body names nothing).
        provider = None

    payload = snapshot_bytes(snapshot)
    sha256 = hashlib.sha256(payload).hexdigest()
    etag = f'"{sha256}"'
    orientation_payload = snapshot_bytes(metadata_only_snapshot(snapshot))
    orientation_sha256 = hashlib.sha256(orientation_payload).hexdigest()
    orientation_etag = f'"{orientation_sha256}"'
    identity_payload = snapshot_bytes(identity_snapshot(snapshot))
    identity_sha256 = hashlib.sha256(identity_payload).hexdigest()
    identity_etag = f'"{identity_sha256}"'
    chunk_catalog = build_chunk_catalog(snapshot, snapshot_sha256=sha256)
    chunk_index_etag = f'"{chunk_catalog.index_sha256}"'
    knowledge_catalogs = build_knowledge_catalogs(snapshot, snapshot_sha256=sha256)
    concept_catalog = knowledge_catalogs.concepts
    concept_index_etag = f'"{concept_catalog.index_sha256}"'
    guardrail_catalog = knowledge_catalogs.guardrails
    guardrail_index_etag = f'"{guardrail_catalog.index_sha256}"'
    schema_version = snapshot.beacon_snapshot_version
    status_payload = dumps_canonical(
        build_status_payload(
            snapshot,
            snapshot_sha256=sha256,
            observation=status_observation,
        )
    )
    status_sha256 = hashlib.sha256(status_payload).hexdigest()
    status_etag = f'"{status_sha256}"'
    observed = status_observation or StatusObservation.unavailable()
    freshness = _freshness_block(snapshot.generator, observed, sha256)

    decision_index_body: bytes | None = None
    decision_index_headers: dict[str, str] = {}
    decision_index_etag = ""
    decision_index_sha256 = ""
    decision_resources: dict[str, tuple[bytes, dict[str, str], str]] = {}
    if provider is not None:
        (
            decision_index_body,
            decision_index_headers,
            decision_index_etag,
            decision_index_sha256,
            decision_resources,
        ) = _decision_catalog(provider, snapshot_sha256=sha256, schema_version=schema_version)

    discovery = _discovery_payload(
        sha256=sha256,
        byte_count=len(payload),
        orientation_sha256=orientation_sha256,
        orientation_byte_count=len(orientation_payload),
        identity_sha256=identity_sha256,
        identity_byte_count=len(identity_payload),
        chunk_index_sha256=chunk_catalog.index_sha256,
        chunk_index_byte_count=len(chunk_catalog.index_body),
        chunk_count=len(chunk_catalog.resources),
        concept_index_sha256=concept_catalog.index_sha256,
        concept_index_byte_count=len(concept_catalog.index_body),
        concept_count=len(concept_catalog.resources),
        guardrail_index_sha256=guardrail_catalog.index_sha256,
        guardrail_index_byte_count=len(guardrail_catalog.index_body),
        guardrail_count=len(guardrail_catalog.resources),
        decision_count=len(decision_resources) if decision_index_body is not None else None,
        decision_index_sha256=decision_index_sha256 or None,
        decision_index_byte_count=len(decision_index_body) if decision_index_body else None,
        status_sha256=status_sha256,
        status_byte_count=len(status_payload),
        schema_version=schema_version,
        freshness=freshness,
    )
    discovery_body = dumps_canonical(discovery)
    health = _health_payload(sha256=sha256, schema_version=schema_version)
    health_body = dumps_canonical(health)

    snapshot_headers = _representation_headers(payload, sha256, etag)
    orientation_headers = _representation_headers(
        orientation_payload, orientation_sha256, orientation_etag
    )
    orientation_headers["link"] = '</v1/snapshot>; rel="alternate"; title="full snapshot"'
    identity_headers = _representation_headers(identity_payload, identity_sha256, identity_etag)
    identity_headers["link"] = (
        '</v1/status>; rel="status"; title="project status", '
        '</v1/snapshot/orientation>; rel="alternate"; title="orientation snapshot"'
    )
    identity_headers.update(_freshness_headers(snapshot.generator, observed, sha256))
    status_headers = _representation_headers(
        status_payload,
        status_sha256,
        status_etag,
        digest_header="x-beacon-status-sha256",
    )
    status_headers["x-beacon-snapshot-sha256"] = sha256
    status_headers["link"] = (
        '</v1/snapshot/orientation>; rel="alternate"; title="orientation snapshot"'
    )
    chunk_index_headers = _representation_headers(
        chunk_catalog.index_body,
        chunk_catalog.index_sha256,
        chunk_index_etag,
        digest_header="x-beacon-chunk-index-sha256",
    )
    chunk_index_headers["x-beacon-snapshot-sha256"] = sha256
    chunk_index_headers["link"] = (
        '</v1/snapshot/orientation>; rel="alternate"; title="orientation snapshot"'
    )
    chunk_resources: dict[str, tuple[bytes, dict[str, str], str]] = {}
    for chunk_resource in chunk_catalog.resources:
        resource_etag = f'"{chunk_resource.sha256}"'
        resource_headers = _representation_headers(
            chunk_resource.body,
            chunk_resource.sha256,
            resource_etag,
            digest_header="x-beacon-chunk-sha256",
        )
        resource_headers["x-beacon-snapshot-sha256"] = sha256
        resource_headers["link"] = '</v1/chunks>; rel="index"; title="chunk index"'
        chunk_resources[chunk_resource.id] = (
            chunk_resource.body,
            resource_headers,
            resource_etag,
        )

    concept_index_headers = _representation_headers(
        concept_catalog.index_body,
        concept_catalog.index_sha256,
        concept_index_etag,
        digest_header="x-beacon-concept-index-sha256",
    )
    concept_index_headers["x-beacon-snapshot-sha256"] = sha256
    concept_resources: dict[str, tuple[bytes, dict[str, str], str]] = {}
    for concept_resource in concept_catalog.resources:
        resource_etag = f'"{concept_resource.sha256}"'
        resource_headers = _representation_headers(
            concept_resource.body,
            concept_resource.sha256,
            resource_etag,
            digest_header="x-beacon-concept-sha256",
        )
        resource_headers["x-beacon-snapshot-sha256"] = sha256
        resource_headers["link"] = '</v1/concepts>; rel="index"; title="concept index"'
        concept_resources[concept_resource.id] = (
            concept_resource.body,
            resource_headers,
            resource_etag,
        )

    guardrail_index_headers = _representation_headers(
        guardrail_catalog.index_body,
        guardrail_catalog.index_sha256,
        guardrail_index_etag,
        digest_header="x-beacon-guardrail-index-sha256",
    )
    guardrail_index_headers["x-beacon-snapshot-sha256"] = sha256
    guardrail_resources: dict[str, tuple[bytes, dict[str, str], str]] = {}
    for guardrail_resource in guardrail_catalog.resources:
        resource_etag = f'"{guardrail_resource.sha256}"'
        resource_headers = _representation_headers(
            guardrail_resource.body,
            guardrail_resource.sha256,
            resource_etag,
            digest_header="x-beacon-guardrail-sha256",
        )
        resource_headers["x-beacon-snapshot-sha256"] = sha256
        resource_headers["link"] = '</v1/guardrails>; rel="index"; title="guardrail index"'
        guardrail_resources[guardrail_resource.id] = (
            guardrail_resource.body,
            resource_headers,
            resource_etag,
        )

    search_tool = _ServedSearchTool(provider) if provider is not None else None
    read_tool = _ServedReadTool(provider) if provider is not None else None
    explain_tool = _ServedExplainTool(provider) if provider is not None else None

    async def decisions_index_route(request: Request) -> Response:
        if decision_index_body is None:
            raise HTTPException(status_code=404)
        return _snapshot_response(
            request,
            decision_index_body,
            decision_index_headers,
            decision_index_etag,
        )

    async def decision_resource_route(request: Request) -> Response:
        resource = decision_resources.get(str(request.path_params["decision_id"]).strip().lower())
        if resource is None:
            raise HTTPException(status_code=404)
        body, headers, resource_etag = resource
        return _snapshot_response(request, body, headers, resource_etag)

    async def search_route(request: Request) -> Response:
        if search_tool is None:
            raise HTTPException(status_code=404)
        params = request.query_params
        query = params.get("q")
        if query is None:
            return _missing_parameter_response(request, "q")
        limit, problem = _int_query(params, "limit", default=8)
        if problem is not None:
            return _parameter_error_response(request, problem)
        # "docs, decisions" and "docs,,decisions" mean the same as "docs,decisions".
        wanted = [t.strip() for t in (params.get("types") or "").split(",") if t.strip()]
        source_types = wanted or None
        return await _tool_response(
            request,
            search_tool,
            query=query,
            source_types=source_types,
            limit=limit,
        )

    async def read_route(request: Request) -> Response:
        if read_tool is None:
            raise HTTPException(status_code=404)
        params = request.query_params
        line, problem = _int_query(params, "line", default=0)
        if problem is None:
            max_chars, problem = _int_query(params, "max_chars", default=4000)
        if problem is None:
            offset, problem = _int_query(params, "offset", default=0)
        if problem is not None:
            return _parameter_error_response(request, problem)
        return await _tool_response(
            request,
            read_tool,
            chunk_id=params.get("chunk_id") or "",
            path=params.get("path") or "",
            heading=params.get("heading") or "",
            line=line,
            max_chars=max_chars,
            offset=offset,
        )

    async def explain_route(request: Request) -> Response:
        if explain_tool is None:
            raise HTTPException(status_code=404)
        params = request.query_params
        concept = params.get("concept")
        if concept is None:
            return _missing_parameter_response(request, "concept")
        return await _tool_response(
            request,
            explain_tool,
            concept=concept,
            depth=params.get("depth") or "technical",
        )

    async def snapshot_route(request: Request) -> Response:
        return _snapshot_response(request, payload, snapshot_headers, etag)

    async def beacon_json_route(request: Request) -> Response:
        return _snapshot_response(request, payload, snapshot_headers, etag)

    async def orientation_route(request: Request) -> Response:
        return _snapshot_response(
            request,
            orientation_payload,
            orientation_headers,
            orientation_etag,
        )

    async def identity_route(request: Request) -> Response:
        return _snapshot_response(
            request,
            identity_payload,
            identity_headers,
            identity_etag,
        )

    async def chunk_index_route(request: Request) -> Response:
        return _snapshot_response(
            request,
            chunk_catalog.index_body,
            chunk_index_headers,
            chunk_index_etag,
        )

    async def status_route(request: Request) -> Response:
        return _snapshot_response(
            request,
            status_payload,
            status_headers,
            status_etag,
        )

    async def chunk_resource_route(request: Request) -> Response:
        resource = chunk_resources.get(request.path_params["chunk_id"])
        if resource is None:
            raise HTTPException(status_code=404)
        body, headers, resource_etag = resource
        return _snapshot_response(request, body, headers, resource_etag)

    async def concept_index_route(request: Request) -> Response:
        return _snapshot_response(
            request,
            concept_catalog.index_body,
            concept_index_headers,
            concept_index_etag,
        )

    async def concept_resource_route(request: Request) -> Response:
        resource = concept_resources.get(request.path_params["concept_id"])
        if resource is None:
            raise HTTPException(status_code=404)
        body, headers, resource_etag = resource
        return _snapshot_response(request, body, headers, resource_etag)

    async def guardrail_index_route(request: Request) -> Response:
        return _snapshot_response(
            request,
            guardrail_catalog.index_body,
            guardrail_index_headers,
            guardrail_index_etag,
        )

    async def guardrail_resource_route(request: Request) -> Response:
        resource = guardrail_resources.get(request.path_params["guardrail_id"])
        if resource is None:
            raise HTTPException(status_code=404)
        body, headers, resource_etag = resource
        return _snapshot_response(request, body, headers, resource_etag)

    async def discovery_route(request: Request) -> Response:
        return _static_response(
            request.method,
            discovery_body,
            _json_headers(discovery_body),
        )

    async def health_route(request: Request) -> Response:
        return _static_response(
            request.method,
            health_body,
            _json_headers(health_body, cache_control="no-store"),
        )

    app = Starlette(
        routes=[
            Route("/.well-known/archolith-beacon", discovery_route, methods=["GET", "HEAD"]),
            Route("/v1/snapshot/identity", identity_route, methods=["GET", "HEAD"]),
            Route("/v1/snapshot/orientation", orientation_route, methods=["GET", "HEAD"]),
            Route("/v1/snapshot", snapshot_route, methods=["GET", "HEAD"]),
            Route("/beacon.json", beacon_json_route, methods=["GET", "HEAD"]),
            Route("/v1/status", status_route, methods=["GET", "HEAD"]),
            Route("/v1/chunks", chunk_index_route, methods=["GET", "HEAD"]),
            Route("/v1/chunks/{chunk_id:str}", chunk_resource_route, methods=["GET", "HEAD"]),
            Route("/v1/concepts", concept_index_route, methods=["GET", "HEAD"]),
            Route("/v1/concepts/{concept_id:str}", concept_resource_route, methods=["GET", "HEAD"]),
            Route("/v1/guardrails", guardrail_index_route, methods=["GET", "HEAD"]),
            Route(
                "/v1/guardrails/{guardrail_id:str}",
                guardrail_resource_route,
                methods=["GET", "HEAD"],
            ),
            Route("/v1/decisions", decisions_index_route, methods=["GET", "HEAD"]),
            Route(
                # :path, not :str: decision ids may contain "/" (ADRs in nested directories).
                "/v1/decisions/{decision_id:path}",
                decision_resource_route,
                methods=["GET", "HEAD"],
            ),
            Route("/v1/search", search_route, methods=["GET", "HEAD"]),
            Route("/v1/read", read_route, methods=["GET", "HEAD"]),
            Route("/v1/explain", explain_route, methods=["GET", "HEAD"]),
            Route("/healthz", health_route, methods=["GET", "HEAD"]),
        ],
    )
    app.state.beacon_snapshot_sha256 = sha256
    app.state.beacon_orientation_sha256 = orientation_sha256
    app.state.beacon_identity_sha256 = identity_sha256
    app.state.beacon_chunk_index_sha256 = chunk_catalog.index_sha256
    app.state.beacon_concept_index_sha256 = concept_catalog.index_sha256
    app.state.beacon_guardrail_index_sha256 = guardrail_catalog.index_sha256
    app.state.beacon_status_sha256 = status_sha256
    app.state.beacon_snapshot_schema_version = schema_version
    app.state.beacon_provider = provider
    if decision_index_body is not None:
        app.state.beacon_decision_index_sha256 = decision_index_sha256
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unexpected_exception_handler)
    # A trailing-slash redirect would copy the query string into Location; answer 404 instead.
    app.router.redirect_slashes = False
    return app


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _snapshot_response(
    request: Request, payload: bytes, headers: dict[str, str], etag: str
) -> Response:
    """Serve the snapshot payload honoring ``If-None-Match``.

    A matching ``If-None-Match`` (exact quoted ETag, or a token inside a
    comma-separated list) yields a 304 with no body. A malformed header is
    ignored safely and the full 200 payload is returned. HEAD returns no body
    while keeping the same representation headers as GET.
    """
    inm = request.headers.get("if-none-match")
    if inm and _etag_matches(inm, etag):
        reduced = {key: value for key, value in headers.items() if key != "content-length"}
        return Response(content=b"", status_code=304, headers=reduced)
    body = payload if request.method == "GET" else b""
    return Response(content=body, status_code=200, headers=dict(headers))


def _static_response(method: str, body: bytes, headers: dict[str, str]) -> Response:
    """Serve a fixed body for GET and the same representation headers for HEAD."""
    response_body = body if method == "GET" else b""
    return Response(content=response_body, status_code=200, headers=headers)


def _json_headers(body: bytes, *, cache_control: str | None = None) -> dict[str, str]:
    """Common JSON response headers with an exact content length."""
    headers = {
        "content-type": "application/json",
        "content-length": str(len(body)),
        "x-content-type-options": "nosniff",
    }
    if cache_control is not None:
        headers["cache-control"] = cache_control
    return headers


def _representation_headers(
    payload: bytes,
    sha256: str,
    etag: str,
    *,
    digest_header: str = "x-beacon-snapshot-sha256",
) -> dict[str, str]:
    """Return immutable-representation headers for a snapshot tier."""
    return {
        "content-type": "application/json",
        "content-length": str(len(payload)),
        "etag": etag,
        digest_header: sha256,
        "cache-control": "no-cache",
        "x-content-type-options": "nosniff",
    }


# ---------------------------------------------------------------------------
# Dynamic query routes (same answers as the MCP tools)
# ---------------------------------------------------------------------------


class _ServedSearchTool(SearchTool):
    """``beacon_search`` bound to the app's provider instead of the MCP lifecycle."""

    def __init__(self, provider: ManifestBeaconProvider) -> None:
        self._provider = provider

    def get_provider(self) -> ManifestBeaconProvider:
        return self._provider


class _ServedReadTool(ReadTool):
    """``beacon_read`` bound to the app's provider instead of the MCP lifecycle."""

    def __init__(self, provider: ManifestBeaconProvider) -> None:
        self._provider = provider

    def get_provider(self) -> ManifestBeaconProvider:
        return self._provider


class _ServedExplainTool(ExplainConceptTool):
    """``beacon_explain_concept`` bound to the app's provider, not the lifecycle."""

    def __init__(self, provider: ManifestBeaconProvider) -> None:
        self._provider = provider

    def get_provider(self) -> ManifestBeaconProvider:
        return self._provider


#: Refusal codes that mean "no such served item" and map to HTTP 404. Unknown
#: and withheld share one code, so a client cannot probe for hidden documents.
_NOT_FOUND_REFUSAL_CODES = frozenset({"read_not_found"})

_INTERNAL_ERROR_CODE = "internal_error"


def _json_safe(data: Any) -> Any:
    """Return a JSON-serializable deep copy (``asdict`` leaves tuples as tuples)."""
    if isinstance(data, dict):
        return {key: _json_safe(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_json_safe(item) for item in data]
    return data


def _decision_catalog(
    provider: ManifestBeaconProvider,
    *,
    snapshot_sha256: str,
    schema_version: str,
) -> tuple[bytes, dict[str, str], str, str, dict[str, tuple[bytes, dict[str, str], str]]]:
    """Precompute the decision index and one immutable record per served decision.

    Decisions come from the provider manifest, which the snapshot export
    already filtered to served ADRs; no second serving policy is applied. The
    record body is the served ``BeaconDecision`` itself -- id, title, path,
    decision text, status, status_text, date, truncated, implemented,
    alternatives, section spans, supersession, and citations -- with no fields
    added or removed.
    """
    entries: list[dict[str, Any]] = []
    resources: dict[str, tuple[bytes, dict[str, str], str]] = {}
    for decision in provider.manifest.decisions:
        body = dumps_canonical(_json_safe(asdict(decision)))
        decision_sha256 = hashlib.sha256(body).hexdigest()
        etag = f'"{decision_sha256}"'
        headers = _representation_headers(
            body,
            decision_sha256,
            etag,
            digest_header="x-beacon-decision-sha256",
        )
        headers["link"] = '</v1/decisions>; rel="index"; title="decision index"'
        resources[decision.id.lower()] = (body, headers, etag)
        entries.append(
            {
                "id": decision.id,
                "title": decision.title,
                "status": decision.status,
                "date": decision.date,
                "bytes": len(body),
                "sha256": decision_sha256,
            }
        )
    index_body = dumps_canonical(
        {
            "decision_index_version": _DECISION_INDEX_VERSION,
            "beacon_version": __version__,
            "snapshot": {
                "sha256": snapshot_sha256,
                "schema_version": schema_version,
            },
            "item_url_template": "/v1/decisions/{id}",
            "count": len(entries),
            "decisions": entries,
        }
    )
    index_sha256 = hashlib.sha256(index_body).hexdigest()
    index_etag = f'"{index_sha256}"'
    index_headers = _representation_headers(
        index_body,
        index_sha256,
        index_etag,
        digest_header="x-beacon-decision-index-sha256",
    )
    index_headers["link"] = (
        '</v1/snapshot/orientation>; rel="alternate"; title="orientation snapshot"'
    )
    return index_body, index_headers, index_etag, index_sha256, resources


def _dynamic_response(request: Request, body: bytes, *, status: int = 200) -> Response:
    """Serve a deterministic dynamic answer with a body-derived ETag.

    A matching ``If-None-Match`` yields a 304 with no body. HEAD returns no
    body while keeping the representation headers. The query string is never
    part of the body or the headers.
    """
    etag = f'"{hashlib.sha256(body).hexdigest()}"'
    headers = _json_headers(body)
    headers["etag"] = etag
    headers["cache-control"] = "no-cache"
    if status == 200:
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and _etag_matches(if_none_match, etag):
            reduced = {key: value for key, value in headers.items() if key != "content-length"}
            return Response(content=b"", status_code=304, headers=reduced)
    response_body = body if request.method != "HEAD" else b""
    return Response(content=response_body, status_code=status, headers=headers)


#: Dynamic queries run at once on worker threads; more wait their turn off the event loop.
_TOOL_CONCURRENCY = 4


def _execute_tool(tool: BeaconBaseTool, kwargs: dict[str, Any]) -> str:
    """Run the tool's async ``execute`` to completion on this worker thread's own loop."""
    return asyncio.run(tool.execute(**kwargs))


async def _tool_response(request: Request, tool: BeaconBaseTool, /, **kwargs: Any) -> Response:
    """Run one MCP tool and answer with its exact payload in canonical form.

    The payload is whatever the tool's ``execute`` returns: the rendered
    answer contract on success, or the shared refusal envelope
    ``{"ok": false, "tool": ..., "error": {...}}`` on a refusal. Refusal codes
    that mean not-found map to 404, other refusals to 400, and the tool's own
    ``internal_error`` payload to 500; the tool logs unexpected exceptions
    without the query.
    """
    # Provider search/read/explain are synchronous; run them on a worker thread so one slow
    # query cannot stall every other request (health, static routes) on the event loop.
    limiter = getattr(request.app.state, "beacon_tool_limiter", None)
    if limiter is None:
        limiter = anyio.CapacityLimiter(_TOOL_CONCURRENCY)
        request.app.state.beacon_tool_limiter = limiter
    payload = json.loads(
        await anyio.to_thread.run_sync(_execute_tool, tool, kwargs, limiter=limiter)
    )
    status = 200
    if isinstance(payload, dict) and payload.get("ok") is False:
        code = str(payload.get("error", {}).get("code", ""))
        if code == _INTERNAL_ERROR_CODE:
            status = 500
        elif code in _NOT_FOUND_REFUSAL_CODES:
            status = 404
        else:
            status = 400
    return _dynamic_response(request, dumps_canonical(payload), status=status)


def _parameter_error_response(request: Request, message: str) -> Response:
    """A deterministic 400 for an invalid query-parameter type (value not echoed)."""
    body = dumps_canonical(
        {
            "error_version": _ERROR_VERSION,
            "error": {"code": "invalid_parameter", "message": message},
        }
    )
    return _dynamic_response(request, body, status=400)


def _missing_parameter_response(request: Request, name: str) -> Response:
    """A deterministic 400 for a required query parameter that is absent."""
    body = dumps_canonical(
        {
            "error_version": _ERROR_VERSION,
            "error": {
                "code": "missing_parameter",
                "message": f"missing required parameter: {name}",
            },
        }
    )
    return _dynamic_response(request, body, status=400)


def _int_query(params: QueryParams, name: str, *, default: int) -> tuple[int | None, str | None]:
    """Parse an integer query parameter; ``(None, message)`` marks a bad type."""
    raw = params.get(name)
    if raw is None or raw == "":
        return default, None
    try:
        return int(raw), None
    except ValueError:
        return None, f"parameter must be an integer: {name}"


def _http_exception_handler(request: Request, exc: Exception) -> Response:
    """Map routing HTTP errors to a deterministic versioned Beacon body."""
    if not isinstance(exc, HTTPException):
        return _unexpected_exception_handler(request, exc)
    status = exc.status_code
    if status == 404:
        code = "not_found"
        message = "not found"
    elif status == 405:
        code = "method_not_allowed"
        message = "method not allowed"
    else:
        code = "http_error"
        message = "http error"
    body = dumps_canonical(
        {"error_version": _ERROR_VERSION, "error": {"code": code, "message": message}}
    )
    headers = _json_headers(body)
    allow = next(
        (value for key, value in (exc.headers or {}).items() if key.lower() == "allow"), None
    )
    if allow:
        headers["allow"] = allow
    response_body = body if request.method != "HEAD" else b""
    return Response(content=response_body, status_code=status, headers=headers)


def _unexpected_exception_handler(request: Request, exc: Exception) -> Response:
    """Fail closed with a redacted Beacon error envelope."""
    del exc
    body = dumps_canonical(
        {
            "error_version": _ERROR_VERSION,
            "error": {"code": "internal_error", "message": "internal error"},
        }
    )
    response_body = body if request.method != "HEAD" else b""
    return Response(content=response_body, status_code=500, headers=_json_headers(body))


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _freshness_block(
    generator: SnapshotGenerator,
    observed: StatusObservation,
    snapshot_sha256: str,
) -> dict[str, Any]:
    """Freshness facts from data that already exists; never request-time I/O.

    The repository shape mirrors the ``observed.repository`` block that
    ``/v1/status`` serves. Facts the observation did not capture stay ``null``
    or the existing ``unavailable`` state; nothing is invented.
    """
    repository: dict[str, Any] = {"state": observed.repository.state}
    if observed.repository.state == "observed":
        repository.update(
            {
                "commit": observed.repository.commit,
                "branch": observed.repository.branch,
                "dirty": observed.repository.dirty,
            }
        )
    return {
        "snapshot_sha256": snapshot_sha256,
        "generator": {
            "distribution": generator.distribution,
            "version": generator.version or None,
        },
        "repository": repository,
        "observed_at": observed.observed_at,
        "status_url": "/v1/status",
    }


def _freshness_headers(
    generator: SnapshotGenerator,
    observed: StatusObservation,
    snapshot_sha256: str,
) -> dict[str, str]:
    """Mirror the freshness facts on identity response headers, not its body.

    A fact the observation did not capture is omitted from the headers rather
    than emptied; branch names that cannot cross a header are omitted too.
    """
    headers: dict[str, str] = {
        "x-beacon-repository-state": observed.repository.state,
        "x-beacon-full-snapshot-sha256": snapshot_sha256,
    }
    if generator.version:
        headers["x-beacon-generator-version"] = generator.version
    if observed.observed_at:
        headers["x-beacon-observed-at"] = observed.observed_at
    if observed.repository.state == "observed":
        headers["x-beacon-repository-commit"] = observed.repository.commit
        if observed.repository.branch and observed.repository.branch.isascii():
            headers["x-beacon-repository-branch"] = observed.repository.branch
        if observed.repository.dirty is not None:
            headers["x-beacon-repository-dirty"] = "true" if observed.repository.dirty else "false"
    return headers


def _discovery_payload(
    *,
    sha256: str,
    byte_count: int,
    orientation_sha256: str,
    orientation_byte_count: int,
    identity_sha256: str,
    identity_byte_count: int,
    chunk_index_sha256: str,
    chunk_index_byte_count: int,
    chunk_count: int,
    concept_index_sha256: str,
    concept_index_byte_count: int,
    concept_count: int,
    guardrail_index_sha256: str,
    guardrail_index_byte_count: int,
    guardrail_count: int,
    decision_count: int | None,
    decision_index_sha256: str | None,
    decision_index_byte_count: int | None,
    status_sha256: str,
    status_byte_count: int,
    schema_version: str,
    freshness: dict[str, Any],
) -> dict[str, Any]:
    """Return the deterministic, redacted discovery document.

    The document is the LLM entry point: every resource family and dynamic
    route carries a one-line ``use_when``, ``recommended_flow`` lists the
    routes an agent should walk in order, ``freshness`` states how old the
    served knowledge is, and ``trust`` labels the access model.

    The decision resource family, the ``query`` capability, the dynamic route
    listing, and their flow steps appear only when the snapshot's manifest is
    servable; a snapshot without a servable manifest advertises the static
    surface only. The dynamic entry is a listing of route names, parameters,
    and usage guidance.
    """
    capabilities: dict[str, Any] = {
        "snapshot": True,
        "chunks": True,
        "concepts": True,
        "guardrails": True,
        "status": True,
        "query": False,
        "question_submission": False,
        "mcp_http": False,
    }
    payload: dict[str, Any] = {
        "descriptor_version": _DESCRIPTOR_VERSION,
        "beacon_version": __version__,
        "scope": _SCOPE,
        "authentication": _AUTHENTICATION,
        "trust": _TRUST,
        "trust_note": _TRUST_NOTE,
        "capabilities": capabilities,
        "freshness": freshness,
        "recommended_flow": [_FLOW_IDENTIFY, _FLOW_GUARDRAILS],
        "snapshot": {
            "url": "/v1/snapshot",
            "mode": "embedded",
            "sha256": sha256,
            "schema_version": schema_version,
        },
        "representations": {
            "identity": {
                "url": "/v1/snapshot/identity",
                "mode": "metadata_only",
                "sha256": identity_sha256,
                "bytes": identity_byte_count,
                "schema_version": schema_version,
            },
            "orientation": {
                "url": "/v1/snapshot/orientation",
                "mode": "metadata_only",
                "sha256": orientation_sha256,
                "bytes": orientation_byte_count,
                "schema_version": schema_version,
            },
            "full": {
                "url": "/v1/snapshot",
                "mode": "embedded",
                "sha256": sha256,
                "bytes": byte_count,
                "schema_version": schema_version,
            },
        },
        "resources": {
            "status": {
                "url": "/v1/status",
                "version": STATUS_VERSION,
                "sha256": status_sha256,
                "bytes": status_byte_count,
                "use_when": _FAMILY_USE_WHEN["status"],
            },
            "chunks": {
                "index_url": "/v1/chunks",
                "item_url_template": "/v1/chunks/{id}",
                "version": CHUNK_INDEX_VERSION,
                "count": chunk_count,
                "sha256": chunk_index_sha256,
                "bytes": chunk_index_byte_count,
                "use_when": _FAMILY_USE_WHEN["chunks"],
            },
            "concepts": {
                "index_url": "/v1/concepts",
                "item_url_template": "/v1/concepts/{id}",
                "version": CONCEPT_INDEX_VERSION,
                "count": concept_count,
                "sha256": concept_index_sha256,
                "bytes": concept_index_byte_count,
                "use_when": _FAMILY_USE_WHEN["concepts"],
            },
            "guardrails": {
                "index_url": "/v1/guardrails",
                "item_url_template": "/v1/guardrails/{id}",
                "version": GUARDRAIL_INDEX_VERSION,
                "count": guardrail_count,
                "sha256": guardrail_index_sha256,
                "bytes": guardrail_index_byte_count,
                "use_when": _FAMILY_USE_WHEN["guardrails"],
            },
        },
    }
    if decision_count is not None and decision_index_sha256 and decision_index_byte_count:
        capabilities["decisions"] = True
        capabilities["query"] = True
        payload["resources"]["decisions"] = {
            "index_url": "/v1/decisions",
            "item_url_template": "/v1/decisions/{id}",
            "version": _DECISION_INDEX_VERSION,
            "count": decision_count,
            "sha256": decision_index_sha256,
            "bytes": decision_index_byte_count,
            "use_when": _FAMILY_USE_WHEN["decisions"],
        }
        payload["dynamic"] = {
            "search": {
                "url": "/v1/search",
                "method": "GET",
                "parameters": ["q", "types", "limit"],
                "use_when": _DYNAMIC_USE_WHEN["search"],
            },
            "read": {
                "url": "/v1/read",
                "method": "GET",
                "parameters": ["chunk_id", "path", "heading", "line", "max_chars", "offset"],
                "use_when": _DYNAMIC_USE_WHEN["read"],
            },
            "explain": {
                "url": "/v1/explain",
                "method": "GET",
                "parameters": ["concept", "depth"],
                "use_when": _DYNAMIC_USE_WHEN["explain"],
            },
        }
        payload["recommended_flow"] = [
            _FLOW_IDENTIFY,
            *_FLOW_SERVABLE_STEPS,
            _FLOW_GUARDRAILS,
        ]
    return payload


def _health_payload(*, sha256: str, schema_version: str) -> dict[str, Any]:
    """Return the redacted readiness document."""
    return {
        "status": "ready",
        "beacon_version": __version__,
        "startup_mode": _STARTUP_MODE,
        "snapshot": {
            "sha256": sha256,
            "schema_version": schema_version,
        },
    }


# ---------------------------------------------------------------------------
# Conditional-request parsing
# ---------------------------------------------------------------------------


def _etag_matches(if_none_match: str, etag: str) -> bool:
    """Return True when *if_none_match* lists the exact quoted *etag*.

    Tokens are split on commas, trimmed, and any weak prefix (``W/``) is
    stripped before comparison. Anything that cannot be parsed simply does not
    match, so malformed headers are ignored safely.
    """
    if if_none_match.strip() == "*":
        return True
    target = etag.strip()
    for raw in if_none_match.split(","):
        token = raw.strip()
        lowered = token[:2].lower()
        if lowered == "w/":
            token = token[2:].strip()
        if token == target:
            return True
    return False


__all__ = ["create_http_app"]
