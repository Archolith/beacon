"""Tests for the loopback HTTP surface over an immutable snapshot."""

from __future__ import annotations

import hashlib
import json

import pytest
from starlette.routing import Route
from starlette.testclient import TestClient

from beacon import __version__
from beacon.core.policy import PolicyEvaluation
from beacon.core.snapshot import (
    SNAPSHOT_VERSION,
    Snapshot,
    SnapshotChunk,
    SnapshotDocument,
    SnapshotGenerator,
    SnapshotManifest,
    SnapshotProject,
    SnapshotValidation,
    snapshot_bytes,
)
from beacon.http_api import create_http_app

#: A distinct body fragment that must only ever appear on snapshot routes.
DOC_TEXT = "the quick brown fox jumps over the lazy dog"


def _make_snapshot(
    *,
    document_text: str = DOC_TEXT,
    content_mode: str = "embedded",
) -> Snapshot:
    """Return a minimal, publishable snapshot carrying one embedded chunk."""
    return Snapshot(
        beacon_snapshot_version=SNAPSHOT_VERSION,
        generator=SnapshotGenerator(distribution="archolith-beacon", version=__version__),
        content_mode=content_mode,
        project=SnapshotProject(name="http-project", status="current", repository=""),
        manifest=SnapshotManifest(
            beacon_version="0.1",
            source_sha256="0" * 64,
            data={"project": {"name": "http-project"}},
        ),
        documents=(
            SnapshotDocument(
                path="docs/source.md",
                role="entrypoint",
                status="current",
                title="Source",
                source_sha256="1" * 64,
                chunks=(
                    SnapshotChunk(
                        heading_path=("Intro",),
                        line_start=1,
                        line_end=1,
                        text=document_text,
                    ),
                ),
            ),
        ),
        validation=SnapshotValidation(errors=0, warnings=0),
        policy=PolicyEvaluation(servable=True, publishable=True),
        security_findings=(),
    )


@pytest.fixture()
def snapshot() -> Snapshot:
    return _make_snapshot()


@pytest.fixture()
def payload(snapshot: Snapshot) -> bytes:
    return snapshot_bytes(snapshot)


@pytest.fixture()
def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture()
def etag(sha256: str) -> str:
    return f'"{sha256}"'


@pytest.fixture()
def client(snapshot: Snapshot) -> TestClient:
    return TestClient(create_http_app(snapshot))


# ---------------------------------------------------------------------------
# Route surface
# ---------------------------------------------------------------------------


def test_exact_route_set_get(client: TestClient, payload: bytes, sha256: str) -> None:
    for path in ("/.well-known/archolith-beacon", "/v1/snapshot", "/beacon.json", "/healthz"):
        response = client.get(path)
        assert response.status_code == 200, path
    # Unknown paths 404 with a Beacon error body.
    for path in ("/", "/v1/unknown", "/nope", "/favicon.ico"):
        response = client.get(path)
        assert response.status_code == 404, path
        body = response.json()
        assert body == {
            "error_version": "1.0",
            "error": {"code": "not_found", "message": "not found"},
        }


def test_snapshot_alias_byte_and_header_identity(client: TestClient, payload: bytes) -> None:
    a = client.get("/v1/snapshot")
    b = client.get("/beacon.json")
    assert a.status_code == 200
    assert b.status_code == 200
    assert a.content == payload
    assert b.content == a.content
    assert b.headers == a.headers


def test_snapshot_headers(client: TestClient, payload: bytes, sha256: str, etag: str) -> None:
    response = client.get("/v1/snapshot")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-length"] == str(len(payload))
    assert response.headers["etag"] == etag
    assert response.headers["x-beacon-snapshot-sha256"] == sha256
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_app_retains_snapshot_metadata(snapshot: Snapshot, sha256: str) -> None:
    app = create_http_app(snapshot)
    assert app.state.beacon_snapshot_sha256 == sha256
    assert app.state.beacon_snapshot_schema_version == SNAPSHOT_VERSION


def test_metadata_only_snapshot_is_rejected() -> None:
    with pytest.raises(ValueError, match="embedded content mode"):
        create_http_app(_make_snapshot(content_mode="metadata_only"))


def test_get_and_head_snapshot_equivalent_headers(client: TestClient, payload: bytes) -> None:
    get_response = client.get("/v1/snapshot")
    head_response = client.head("/v1/snapshot")
    assert head_response.status_code == 200
    assert head_response.content == b""
    assert head_response.headers["content-length"] == get_response.headers["content-length"]
    assert head_response.headers["content-length"] == str(len(payload))
    assert head_response.headers["etag"] == get_response.headers["etag"]
    assert head_response.headers["content-type"] == "application/json"


def test_get_and_head_health(client: TestClient) -> None:
    get_response = client.get("/healthz")
    head_response = client.head("/healthz")
    assert get_response.status_code == 200
    assert head_response.status_code == 200
    assert head_response.content == b""
    assert head_response.headers["content-length"] == get_response.headers["content-length"]
    assert get_response.headers["cache-control"] == "no-store"
    assert get_response.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------------------
# Conditional requests (If-None-Match)
# ---------------------------------------------------------------------------


def test_if_none_match_exact_304(client: TestClient, etag: str) -> None:
    response = client.get("/v1/snapshot", headers={"If-None-Match": etag})
    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == etag
    assert "content-length" not in response.headers


def test_if_none_match_wildcard_304(client: TestClient) -> None:
    response = client.get("/v1/snapshot", headers={"If-None-Match": "*"})
    assert response.status_code == 304
    assert response.content == b""


def test_if_none_match_list_304(client: TestClient, etag: str) -> None:
    listed = f'W/"deadbeef", {etag}, "another"'
    response = client.get("/v1/snapshot", headers={"If-None-Match": listed})
    assert response.status_code == 304
    assert response.content == b""


def test_if_none_match_nonmatching_200(client: TestClient, etag: str, payload: bytes) -> None:
    response = client.get("/v1/snapshot", headers={"If-None-Match": '"deadbeef"'})
    assert response.status_code == 200
    assert response.content == payload


def test_if_none_match_malformed_ignored_200(client: TestClient, payload: bytes) -> None:
    for malformed in (
        "not-a-token!!!",
        '"unterminated',
        "W/",
        "",
        ",",
        "*, ,",
    ):
        response = client.get("/v1/snapshot", headers={"If-None-Match": malformed})
        assert response.status_code == 200, repr(malformed)
        assert response.content == payload


def test_if_none_match_head_304(client: TestClient, etag: str) -> None:
    response = client.head("/v1/snapshot", headers={"If-None-Match": etag})
    assert response.status_code == 304
    assert response.content == b""


# ---------------------------------------------------------------------------
# Discovery document
# ---------------------------------------------------------------------------


def test_discovery_fields(client: TestClient, sha256: str) -> None:
    response = client.get("/.well-known/archolith-beacon")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "descriptor_version",
        "beacon_version",
        "scope",
        "authentication",
        "capabilities",
        "snapshot",
    }
    assert body["descriptor_version"] == "1.0"
    assert body["beacon_version"] == __version__
    assert body["scope"] == "loopback"
    assert body["authentication"] == "none"
    assert body["capabilities"] == {
        "snapshot": True,
        "query": False,
        "question_submission": False,
        "mcp_http": False,
    }
    assert body["snapshot"] == {
        "url": "/v1/snapshot",
        "mode": "embedded",
        "sha256": sha256,
        "schema_version": SNAPSHOT_VERSION,
    }


def test_discovery_canonical_newline(client: TestClient) -> None:
    response = client.get("/.well-known/archolith-beacon")
    assert response.content.endswith(b"\n")
    text = response.text[:-1]
    assert (
        json.dumps(json.loads(text), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        == text
    )


# ---------------------------------------------------------------------------
# Health document
# ---------------------------------------------------------------------------


def test_health_fields(client: TestClient, sha256: str) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"status", "beacon_version", "startup_mode", "snapshot"}
    assert body["status"] == "ready"
    assert body["beacon_version"] == __version__
    assert body["startup_mode"] == "immutable_snapshot"
    assert body["snapshot"] == {"sha256": sha256, "schema_version": SNAPSHOT_VERSION}


def test_health_canonical_newline(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.content.endswith(b"\n")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_unsupported_method_405(client: TestClient) -> None:
    for method in ("post", "put", "delete", "patch"):
        for path in ("/v1/snapshot", "/healthz"):
            response = client.request(method, path)
            assert response.status_code == 405, (method, path)
            body = response.json()
            assert body == {
                "error_version": "1.0",
                "error": {"code": "method_not_allowed", "message": "method not allowed"},
            }
            assert "GET" in response.headers["allow"]


def test_404_body_no_server_path_or_content(client: TestClient) -> None:
    response = client.get("/does/not/exist")
    assert response.status_code == 404
    assert "C:" not in response.text
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_no_cors_headers(client: TestClient) -> None:
    for method in ("get", "head", "options", "post"):
        for path in ("/v1/snapshot", "/healthz", "/nope"):
            response = client.request(method, path)
            assert "access-control-allow-origin" not in response.headers, (method, path)


def test_unusual_method_405(client: TestClient) -> None:
    response = client.request("BREW", "/v1/snapshot")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_unexpected_exception_is_redacted(snapshot: Snapshot) -> None:
    async def fail(_request) -> None:
        raise RuntimeError(DOC_TEXT)

    app = create_http_app(snapshot)
    app.routes.append(Route("/test-internal-error", fail, methods=["GET"]))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/test-internal-error?secret=do-not-echo")

    assert response.status_code == 500
    assert response.json() == {
        "error_version": "1.0",
        "error": {"code": "internal_error", "message": "internal error"},
    }
    assert DOC_TEXT not in response.text
    assert "do-not-echo" not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------------------
# Hostile inputs
# ---------------------------------------------------------------------------


def test_query_strings_do_not_echo(client: TestClient, payload: bytes) -> None:
    plain = client.get("/v1/snapshot").content
    with_query = client.get("/v1/snapshot?secret=leak&foo=bar").content
    assert with_query == plain == payload
    health_plain = client.get("/healthz").content
    assert client.get("/healthz?a=1").content == health_plain


def test_no_project_text_outside_snapshot_routes(client: TestClient) -> None:
    assert DOC_TEXT in client.get("/v1/snapshot").text
    for path in ("/.well-known/archolith-beacon", "/healthz", "/nope"):
        response = client.get(path)
        assert DOC_TEXT not in response.text, path


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_immutable_after_source_file_changes(tmp_path) -> None:
    source = tmp_path / "source.md"
    original_text = "original immutable text"
    source.write_text(original_text, encoding="utf-8")
    snapshot = _make_snapshot(document_text=original_text)
    app = create_http_app(snapshot)
    absolute = str(source.resolve())
    with TestClient(app) as test_client:
        before = test_client.get("/v1/snapshot").content
        assert original_text.encode("utf-8") in before
        # Overwrite the backing source file; the app must not reread it.
        source.write_text("tampered different content", encoding="utf-8")
        after = test_client.get("/v1/snapshot").content
        assert after == before
        # Discovery and health never expose the temporary path or doc text.
        assert original_text not in test_client.get("/healthz").text
        assert original_text not in test_client.get("/.well-known/archolith-beacon").text
        assert absolute not in test_client.get("/v1/snapshot").text
