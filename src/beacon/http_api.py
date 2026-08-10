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

* ``/.well-known/archolith-beacon`` -- deterministic discovery document;
* ``/v1/snapshot/identity`` -- minimal project identity representation;
* ``/v1/snapshot/orientation`` -- metadata-only orientation representation;
* ``/v1/snapshot`` -- the canonical snapshot payload;
* ``/beacon.json`` -- byte/header-identical alias of ``/v1/snapshot``;
* ``/v1/chunks`` -- companion chunk index with byte budgets;
* ``/v1/chunks/{id}`` -- one immutable published chunk resource;
* ``/v1/concepts`` / ``/v1/concepts/{id}`` -- concept index and resources;
* ``/v1/guardrails`` / ``/v1/guardrails/{id}`` -- guardrail index and resources;
* ``/healthz`` -- redacted readiness document.

All response bodies are canonical compact JSON ending in exactly one newline.
Unknown routes return a deterministic versioned Beacon error JSON with 404 and
unsupported methods return 405. No CORS is added and query strings are never
echoed.
"""

from __future__ import annotations

import hashlib
from typing import Any

from starlette.applications import Starlette
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
from beacon.core.snapshot import (
    CONTENT_EMBEDDED,
    Snapshot,
    identity_snapshot,
    metadata_only_snapshot,
    snapshot_bytes,
)

#: Discovery descriptor version.
_DESCRIPTOR_VERSION = "1.4"

#: Error envelope version shared by every error body.
_ERROR_VERSION = "1.0"

#: Redacted readiness mode.
_STARTUP_MODE = "immutable_snapshot"

#: Loopback scope reported by discovery.
_SCOPE = "loopback"

#: Discovery authentication model.
_AUTHENTICATION = "none"


def create_http_app(snapshot: Snapshot) -> Starlette:
    """Return a Starlette app serving an immutable view of *snapshot*.

    The snapshot is serialized to canonical bytes exactly once here; all
    requests thereafter serve that immutable payload. Discovery and health are
    likewise derived once and cached, so no request performs I/O or recomputes
    digests.
    """
    if snapshot.content_mode != CONTENT_EMBEDDED:
        raise ValueError("HTTP snapshot must use embedded content mode")

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
        schema_version=schema_version,
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
            Route("/healthz", health_route, methods=["GET", "HEAD"]),
        ],
    )
    app.state.beacon_snapshot_sha256 = sha256
    app.state.beacon_orientation_sha256 = orientation_sha256
    app.state.beacon_identity_sha256 = identity_sha256
    app.state.beacon_chunk_index_sha256 = chunk_catalog.index_sha256
    app.state.beacon_concept_index_sha256 = concept_catalog.index_sha256
    app.state.beacon_guardrail_index_sha256 = guardrail_catalog.index_sha256
    app.state.beacon_snapshot_schema_version = schema_version
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unexpected_exception_handler)
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
    schema_version: str,
) -> dict[str, Any]:
    """Return the deterministic, redacted discovery document."""
    return {
        "descriptor_version": _DESCRIPTOR_VERSION,
        "beacon_version": __version__,
        "scope": _SCOPE,
        "authentication": _AUTHENTICATION,
        "capabilities": {
            "snapshot": True,
            "chunks": True,
            "concepts": True,
            "guardrails": True,
            "query": False,
            "question_submission": False,
            "mcp_http": False,
        },
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
            "chunks": {
                "index_url": "/v1/chunks",
                "item_url_template": "/v1/chunks/{id}",
                "version": CHUNK_INDEX_VERSION,
                "count": chunk_count,
                "sha256": chunk_index_sha256,
                "bytes": chunk_index_byte_count,
            },
            "concepts": {
                "index_url": "/v1/concepts",
                "item_url_template": "/v1/concepts/{id}",
                "version": CONCEPT_INDEX_VERSION,
                "count": concept_count,
                "sha256": concept_index_sha256,
                "bytes": concept_index_byte_count,
            },
            "guardrails": {
                "index_url": "/v1/guardrails",
                "item_url_template": "/v1/guardrails/{id}",
                "version": GUARDRAIL_INDEX_VERSION,
                "count": guardrail_count,
                "sha256": guardrail_index_sha256,
                "bytes": guardrail_index_byte_count,
            },
        },
    }


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
