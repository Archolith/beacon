"""Tests for the loopback HTTP surface over an immutable snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
    build_snapshot,
    identity_snapshot,
    metadata_only_snapshot,
    snapshot_bytes,
)
from beacon.http_api import create_http_app

#: A distinct body fragment that must only ever appear on snapshot routes.
DOC_TEXT = "the quick brown fox jumps over the lazy dog"
REPO_ROOT = Path(__file__).resolve().parents[1]


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
            data={
                "project": {"name": "http-project"},
                "purpose": {"one_sentence": "Exercise HTTP snapshot representations."},
                "core_concepts": [
                    {
                        "id": "answer_contract",
                        "name": "Answer Contract",
                        "sources": [{"path": "src/contracts.py", "line_start": 1}],
                        "implementation_locations": ["src/contracts.py"],
                    }
                ],
            },
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
def orientation_payload(snapshot: Snapshot) -> bytes:
    return snapshot_bytes(metadata_only_snapshot(snapshot))


@pytest.fixture()
def identity_payload(snapshot: Snapshot) -> bytes:
    return snapshot_bytes(identity_snapshot(snapshot))


@pytest.fixture()
def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture()
def etag(sha256: str) -> str:
    return f'"{sha256}"'


@pytest.fixture()
def orientation_sha256(orientation_payload: bytes) -> str:
    return hashlib.sha256(orientation_payload).hexdigest()


@pytest.fixture()
def orientation_etag(orientation_sha256: str) -> str:
    return f'"{orientation_sha256}"'


@pytest.fixture()
def identity_sha256(identity_payload: bytes) -> str:
    return hashlib.sha256(identity_payload).hexdigest()


@pytest.fixture()
def identity_etag(identity_sha256: str) -> str:
    return f'"{identity_sha256}"'


@pytest.fixture()
def client(snapshot: Snapshot) -> TestClient:
    return TestClient(create_http_app(snapshot))


# ---------------------------------------------------------------------------
# Route surface
# ---------------------------------------------------------------------------


def test_exact_route_set_get(client: TestClient, payload: bytes, sha256: str) -> None:
    for path in (
        "/.well-known/archolith-beacon",
        "/v1/snapshot/identity",
        "/v1/snapshot/orientation",
        "/v1/snapshot",
        "/beacon.json",
        "/healthz",
    ):
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


def test_orientation_is_exact_metadata_only_representation(
    client: TestClient,
    payload: bytes,
    orientation_payload: bytes,
) -> None:
    response = client.get("/v1/snapshot/orientation")
    assert response.status_code == 200
    assert response.content == orientation_payload
    assert len(response.content) < len(payload)
    body = response.json()
    assert body["content_mode"] == "metadata_only"
    assert body["project"]["name"] == "http-project"
    assert body["manifest"]["data"]["core_concepts"][0]["sources"]
    assert body["manifest"]["data"]["core_concepts"][0]["implementation_locations"]
    assert all("text" not in chunk for doc in body["documents"] for chunk in doc["chunks"])


def test_identity_is_exact_minimal_snapshot(
    client: TestClient,
    identity_payload: bytes,
    orientation_payload: bytes,
) -> None:
    response = client.get("/v1/snapshot/identity")
    assert response.status_code == 200
    assert response.content == identity_payload
    assert len(response.content) < len(orientation_payload)
    body = response.json()
    assert body["content_mode"] == "metadata_only"
    assert body["project"]["name"] == "http-project"
    assert set(body["manifest"]["data"]) == {"project", "purpose"}
    assert body["documents"] == []


def test_snapshot_headers(client: TestClient, payload: bytes, sha256: str, etag: str) -> None:
    response = client.get("/v1/snapshot")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-length"] == str(len(payload))
    assert response.headers["etag"] == etag
    assert response.headers["x-beacon-snapshot-sha256"] == sha256
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_orientation_headers(
    client: TestClient,
    orientation_payload: bytes,
    orientation_sha256: str,
    orientation_etag: str,
) -> None:
    response = client.get("/v1/snapshot/orientation")
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-length"] == str(len(orientation_payload))
    assert response.headers["etag"] == orientation_etag
    assert response.headers["x-beacon-snapshot-sha256"] == orientation_sha256
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["link"] == '</v1/snapshot>; rel="alternate"; title="full snapshot"'


def test_identity_headers(
    client: TestClient,
    identity_payload: bytes,
    identity_sha256: str,
    identity_etag: str,
) -> None:
    response = client.get("/v1/snapshot/identity")
    assert response.headers["content-length"] == str(len(identity_payload))
    assert response.headers["etag"] == identity_etag
    assert response.headers["x-beacon-snapshot-sha256"] == identity_sha256
    assert response.headers["link"] == (
        '</v1/snapshot/orientation>; rel="alternate"; title="orientation snapshot"'
    )


def test_app_retains_snapshot_metadata(snapshot: Snapshot, sha256: str) -> None:
    app = create_http_app(snapshot)
    assert app.state.beacon_snapshot_sha256 == sha256
    assert (
        app.state.beacon_orientation_sha256
        == hashlib.sha256(snapshot_bytes(metadata_only_snapshot(snapshot))).hexdigest()
    )
    assert (
        app.state.beacon_identity_sha256
        == hashlib.sha256(snapshot_bytes(identity_snapshot(snapshot))).hexdigest()
    )
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


def test_get_and_head_orientation_equivalent_headers(client: TestClient) -> None:
    get_response = client.get("/v1/snapshot/orientation")
    head_response = client.head("/v1/snapshot/orientation")
    assert head_response.status_code == 200
    assert head_response.content == b""
    for header in ("content-length", "etag", "content-type", "x-beacon-snapshot-sha256"):
        assert head_response.headers[header] == get_response.headers[header]


def test_get_and_head_identity_equivalent_headers(client: TestClient) -> None:
    get_response = client.get("/v1/snapshot/identity")
    head_response = client.head("/v1/snapshot/identity")
    assert head_response.status_code == 200
    assert head_response.content == b""
    for header in ("content-length", "etag", "content-type", "x-beacon-snapshot-sha256", "link"):
        assert head_response.headers[header] == get_response.headers[header]


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


def test_orientation_if_none_match_uses_its_own_etag(
    client: TestClient, etag: str, orientation_etag: str, orientation_payload: bytes
) -> None:
    matched = client.get("/v1/snapshot/orientation", headers={"If-None-Match": orientation_etag})
    assert matched.status_code == 304
    assert matched.content == b""
    assert matched.headers["link"] == '</v1/snapshot>; rel="alternate"; title="full snapshot"'

    other_tier = client.get("/v1/snapshot/orientation", headers={"If-None-Match": etag})
    assert other_tier.status_code == 200
    assert other_tier.content == orientation_payload


def test_identity_if_none_match_uses_its_own_etag(
    client: TestClient,
    identity_etag: str,
    orientation_etag: str,
    identity_payload: bytes,
) -> None:
    matched = client.get("/v1/snapshot/identity", headers={"If-None-Match": identity_etag})
    assert matched.status_code == 304
    assert matched.headers["link"] == (
        '</v1/snapshot/orientation>; rel="alternate"; title="orientation snapshot"'
    )
    other_tier = client.get("/v1/snapshot/identity", headers={"If-None-Match": orientation_etag})
    assert other_tier.status_code == 200
    assert other_tier.content == identity_payload


# ---------------------------------------------------------------------------
# Discovery document
# ---------------------------------------------------------------------------


def test_discovery_fields(
    client: TestClient,
    payload: bytes,
    sha256: str,
    orientation_payload: bytes,
    orientation_sha256: str,
    identity_payload: bytes,
    identity_sha256: str,
) -> None:
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
        "representations",
    }
    assert body["descriptor_version"] == "1.2"
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
    assert body["representations"] == {
        "identity": {
            "url": "/v1/snapshot/identity",
            "mode": "metadata_only",
            "sha256": identity_sha256,
            "bytes": len(identity_payload),
            "schema_version": SNAPSHOT_VERSION,
        },
        "orientation": {
            "url": "/v1/snapshot/orientation",
            "mode": "metadata_only",
            "sha256": orientation_sha256,
            "bytes": len(orientation_payload),
            "schema_version": SNAPSHOT_VERSION,
        },
        "full": {
            "url": "/v1/snapshot",
            "mode": "embedded",
            "sha256": sha256,
            "bytes": len(payload),
            "schema_version": SNAPSHOT_VERSION,
        },
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
        for path in (
            "/v1/snapshot/identity",
            "/v1/snapshot/orientation",
            "/v1/snapshot",
            "/healthz",
        ):
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
        for path in (
            "/v1/snapshot/identity",
            "/v1/snapshot/orientation",
            "/v1/snapshot",
            "/healthz",
            "/nope",
        ):
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
    orientation_plain = client.get("/v1/snapshot/orientation").content
    assert client.get("/v1/snapshot/orientation?secret=leak").content == orientation_plain
    identity_plain = client.get("/v1/snapshot/identity").content
    assert client.get("/v1/snapshot/identity?secret=leak").content == identity_plain


def test_no_project_text_outside_snapshot_routes(client: TestClient) -> None:
    assert DOC_TEXT in client.get("/v1/snapshot").text
    for path in (
        "/.well-known/archolith-beacon",
        "/v1/snapshot/identity",
        "/v1/snapshot/orientation",
        "/healthz",
        "/nope",
    ):
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
        assert original_text not in test_client.get("/v1/snapshot/identity").text
        assert original_text not in test_client.get("/v1/snapshot/orientation").text
        assert absolute not in test_client.get("/v1/snapshot").text


def test_dogfood_orientation_is_materially_smaller_and_traceable() -> None:
    snapshot = build_snapshot(REPO_ROOT / "beacon.yaml")
    with TestClient(create_http_app(snapshot)) as test_client:
        full = test_client.get("/v1/snapshot")
        orientation = test_client.get("/v1/snapshot/orientation")
        identity = test_client.get("/v1/snapshot/identity")

    assert len(orientation.content) <= len(full.content) / 2
    assert len(identity.content) <= len(orientation.content) / 5
    identity_body = identity.json()
    assert set(identity_body["manifest"]["data"]) == {
        "project",
        "purpose",
        "audiences",
        "current_focus",
    }
    assert identity_body["documents"] == []
    body = orientation.json()
    assert body["project"]["name"] == "beacon"
    concept = next(
        item
        for item in body["manifest"]["data"]["core_concepts"]
        if item["id"] == "answer_contract"
    )
    assert concept["sources"]
    assert concept["implementation_locations"]
    assert all("text" not in chunk for doc in body["documents"] for chunk in doc["chunks"])
