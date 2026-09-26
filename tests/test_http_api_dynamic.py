"""The loopback HTTP dynamic routes answer exactly like the MCP tools.

* ``/v1/search``, ``/v1/read`` and ``/v1/explain`` call the same tool classes the
  MCP server registers, over one ``ManifestBeaconProvider`` built from the served
  snapshot, so each success and each refusal has the same body as the matching
  MCP tool output (in the surface's canonical JSON form).
* ``/v1/decisions`` and ``/v1/decisions/{id}`` serve the snapshot's already
  filtered decisions statically; a decision whose ADR is withheld probes exactly
  like a nonexistent id.
* Refusals keep the MCP envelope and map not-found codes to 404 and other
  refusals to 400; the refused query text never reaches a body or header.
* A snapshot whose manifest is not servable keeps its static surface and fails
  the query routes closed with the ordinary 404 body.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
import yaml
from starlette.testclient import TestClient

from beacon import __version__
from beacon.core.canonical_json import dumps_canonical
from beacon.core.limits import ResourceLimits
from beacon.core.policy import PolicyEvaluation
from beacon.core.snapshot import (
    CONTENT_EMBEDDED,
    SNAPSHOT_VERSION,
    Snapshot,
    SnapshotGenerator,
    SnapshotManifest,
    SnapshotProject,
    SnapshotValidation,
    build_snapshot,
)
from beacon.http_api import create_http_app
from beacon.mcp import contracts
from beacon.mcp.tools.explain_concept import ExplainConceptTool
from beacon.mcp.tools.read import ReadTool
from beacon.mcp.tools.search import SearchTool
from beacon.provider.manifest_provider import ManifestBeaconProvider

#: A distinctive fragment that exists only inside the local-only document, so
#: any surface that leaks withheld content must contain it.
LOCAL_MARKER = "ZEBRA-ONLY-LOCAL-CONTENT"

#: Unique probe marker embedded in refused queries (never echoed back).
QUERY_MARKER = "QQ-UNIQUE-QUERY-MARKER-QQ"

#: Padding that pushes a probe query past the fixed 4096-byte query ceiling.
_OVER_CAP_PAD = " pad" * 1100

_ADR_0005 = """# ADR 0005 \u2014 Core-Enforced Namespace Isolation

- **Status:** ACCEPTED retrospectively (2026-09-21). This records the namespace boundary
  enforced by the current backend.
- **Date:** 2026-09-21
- **Deciders:** a maintainer

## Context

Checks were added per route. See ADR 0003, which this does not supersede.

## Decision

Namespace isolation is enforced below transport-specific code.

## Considered alternatives

### Enforce the pin in every route

Rejected. Every new surface was another chance to omit the guard.

### Trust the caller's namespace argument

Rejected. Authentication identifies the caller; it does not make target selection safe.

## Consequences

New operations classify namespace inputs.
"""

_ADR_0010 = """# ADR 0010 \u2014 Canonical Self Identity

- **Status:** ACCEPTED as target architecture (2026-09-21). Enforcement remains default-off.
- **Date:** 2026-09-21

## Decision

One canonical identity per logical namespace.
"""


def _manifest_data() -> dict[str, Any]:
    """A servable manifest with one served ADR, one withheld ADR, one local doc."""
    citation_0005 = {
        "type": "file",
        "title": "ADR 0005",
        "path": "docs/adr/0005-isolation.md",
        "line_start": 14,
        "line_end": 14,
        "status": "current",
    }
    return {
        "beacon_version": "0.1",
        "project": {
            "name": "http-parity",
            "description": "Fixture project for HTTP dynamic route tests.",
            "status": "current",
        },
        "purpose": {"one_sentence": "Exercise the HTTP dynamic routes."},
        "audiences": ["coding_agent"],
        "core_concepts": [
            {
                "id": "namespace_isolation",
                "name": "Namespace Isolation",
                "definition": "Isolation enforced below transport-specific code.",
                "why_it_exists": "One boundary instead of per-route checks.",
                "status": "current",
                "related_concepts": [],
                "sources": [citation_0005],
                "implementation_locations": ["src/ns.py"],
            }
        ],
        "canonical_docs": [
            {"path": "README.md", "role": "entrypoint", "title": "Demo"},
            {"path": "docs/guide.md", "role": "workflow", "title": "Guide"},
            {"path": "docs/local.md", "role": "reference", "visibility": "local"},
            {
                "path": "docs/adr/0005-isolation.md",
                "role": "decision",
                "title": "Core-Enforced Namespace Isolation",
            },
            {
                "path": "docs/adr/0010-self.md",
                "role": "decision",
                "title": "Canonical Self Identity",
            },
        ],
        "build_and_test": {"test": "pytest -q"},
        "guardrails": [
            {
                "id": "keep_isolation",
                "rule": "Keep namespace isolation below transport-specific code.",
                "scope": "src",
                "severity": "high",
                "applies_to": ["src/ns.py"],
                "sources": [citation_0005],
            }
        ],
        "decisions": [
            {
                "id": "adr-0005",
                "title": "Core-Enforced Namespace Isolation",
                "path": "docs/adr/0005-isolation.md",
                "status": "current",
                "status_text": "ACCEPTED retrospectively (2026-09-21)",
                "date": "2026-09-21",
                "decision": "Namespace isolation is enforced below transport-specific code.",
                "alternatives": [
                    {
                        "alternative": "Enforce the pin in every route",
                        "reason": "Rejected. Every new surface was another chance to omit "
                        "the guard.",
                    },
                    {
                        "alternative": "Trust the caller's namespace argument",
                        "reason": "Rejected. Authentication identifies the caller; it does not "
                        "make target selection safe.",
                    },
                ],
                "sections": {
                    "context": {"line_start": 10, "line_end": 10},
                    "decision": {"line_start": 14, "line_end": 14},
                    "consequences": {"line_start": 28, "line_end": 28},
                },
                "sources": [citation_0005],
            },
            {
                "id": "adr-0010",
                "title": "Canonical Self Identity",
                "path": "docs/adr/0010-self.md",
                "status": "current",
                "status_text": "ACCEPTED as target architecture (2026-09-21)",
                "date": "2026-09-21",
                "decision": "One canonical identity per logical namespace.",
                "implemented": False,
                "sources": [
                    {
                        "type": "file",
                        "title": "ADR 0010",
                        "path": "docs/adr/0010-self.md",
                        "line_start": 6,
                        "line_end": 6,
                        "status": "current",
                    }
                ],
            },
        ],
        "serving": {"exclude": ["docs/adr/0010-self.md"]},
    }


def _write_repo(root: Path) -> None:
    (root / "docs" / "adr").mkdir(parents=True)
    (root / "README.md").write_text("# Demo\n\nDemo project for HTTP parity.\n", encoding="utf-8")
    (root / "docs" / "guide.md").write_text(
        "# Guide\n\nIntro paragraph about the guide.\n\n## Setup\n\nInstall with pip install -e .\n",
        encoding="utf-8",
    )
    (root / "docs" / "local.md").write_text(
        f"# Local\n\nOperator notes mention {LOCAL_MARKER}.\n", encoding="utf-8"
    )
    (root / "docs" / "adr" / "0005-isolation.md").write_text(_ADR_0005, encoding="utf-8")
    (root / "docs" / "adr" / "0010-self.md").write_text(_ADR_0010, encoding="utf-8")
    (root / "beacon.yaml").write_text(
        yaml.safe_dump(_manifest_data(), sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _write_repo(root)
    return root


@pytest.fixture()
def snapshot(repo: Path) -> Snapshot:
    return build_snapshot(repo / "beacon.yaml", docs_root=repo, content_mode=CONTENT_EMBEDDED)


@pytest.fixture()
def provider(snapshot: Snapshot) -> ManifestBeaconProvider:
    """The MCP-side provider: the same construction the HTTP app performs."""
    return ManifestBeaconProvider.from_snapshot(snapshot)


@pytest.fixture()
def mcp_provider(
    provider: ManifestBeaconProvider, monkeypatch: pytest.MonkeyPatch
) -> ManifestBeaconProvider:
    """Install *provider* so direct MCP tool ``execute`` calls use one snapshot."""
    monkeypatch.setattr(contracts, "get_provider", lambda: provider)
    return provider


@pytest.fixture()
def client(snapshot: Snapshot) -> TestClient:
    return TestClient(create_http_app(snapshot))


def _mcp_payload(tool: Any, **kwargs: Any) -> dict[str, Any]:
    """The exact payload an MCP tool returns for *kwargs*."""
    return json.loads(asyncio.run(tool.execute(**kwargs)))


def _canonical(payload: dict[str, Any]) -> bytes:
    """The canonical body form of an MCP tool payload (the dynamic route form)."""
    return dumps_canonical(payload)


# ---------------------------------------------------------------------------
# Parity: one success and one refusal per dynamic route
# ---------------------------------------------------------------------------


def test_search_success_matches_mcp(
    client: TestClient, mcp_provider: ManifestBeaconProvider
) -> None:
    expected = _canonical(
        _mcp_payload(SearchTool(), query="namespace isolation", source_types=("decisions",))
    )
    response = client.get("/v1/search", params={"q": "namespace isolation", "types": "decisions"})
    assert response.status_code == 200
    assert response.content == expected
    assert response.headers["content-type"] == "application/json"


def test_read_success_matches_mcp(
    client: TestClient,
    provider: ManifestBeaconProvider,
    mcp_provider: ManifestBeaconProvider,
) -> None:
    section = provider.read(path="docs/guide.md", heading="Setup")
    expected = _canonical(_mcp_payload(ReadTool(), chunk_id=section.chunk_id))
    response = client.get("/v1/read", params={"chunk_id": section.chunk_id})
    assert response.status_code == 200
    assert response.content == expected


def test_explain_success_matches_mcp(
    client: TestClient, mcp_provider: ManifestBeaconProvider
) -> None:
    expected = _canonical(_mcp_payload(ExplainConceptTool(), concept="adr-0005"))
    response = client.get("/v1/explain", params={"concept": "adr-0005"})
    assert response.status_code == 200
    assert response.content == expected


def test_decision_record_matches_the_shared_manifest_data(
    client: TestClient, provider: ManifestBeaconProvider
) -> None:
    response = client.get("/v1/decisions/adr-0005")
    assert response.status_code == 200
    served = {decision.id: decision for decision in provider.manifest.decisions}
    assert response.json() == json.loads(json.dumps(asdict(served["adr-0005"])))


def test_search_refusal_matches_mcp_and_hides_the_query(
    client: TestClient, mcp_provider: ManifestBeaconProvider
) -> None:
    query = QUERY_MARKER + _OVER_CAP_PAD
    expected = _canonical(_mcp_payload(SearchTool(), query=query))
    response = client.get("/v1/search", params={"q": query})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "limit_query_bytes"
    assert response.content == expected
    assert QUERY_MARKER not in response.text
    assert QUERY_MARKER not in str(response.headers)


def test_search_limit_refusal_matches_mcp(
    client: TestClient, mcp_provider: ManifestBeaconProvider
) -> None:
    query = QUERY_MARKER + "-limit-probe"
    expected = _canonical(_mcp_payload(SearchTool(), query=query, limit=101))
    response = client.get("/v1/search", params={"q": query, "limit": "101"})
    assert response.status_code == 400
    assert response.content == expected
    assert response.json()["error"]["code"] == "limit_result_limit"
    assert QUERY_MARKER not in response.text
    assert QUERY_MARKER not in str(response.headers)


def test_read_unknown_and_withheld_share_one_refusal(client: TestClient) -> None:
    unknown = client.get("/v1/read", params={"chunk_id": "c1-does-not-exist"})
    withheld = client.get("/v1/read", params={"path": "docs/local.md"})
    assert unknown.status_code == withheld.status_code == 404
    assert unknown.content == withheld.content
    assert unknown.json()["error"]["code"] == "read_not_found"


def test_read_offset_refusal_matches_mcp(
    client: TestClient,
    provider: ManifestBeaconProvider,
    mcp_provider: ManifestBeaconProvider,
) -> None:
    section = provider.read(path="docs/guide.md", heading="Setup")
    expected = _canonical(_mcp_payload(ReadTool(), chunk_id=section.chunk_id, offset=-3))
    response = client.get("/v1/read", params={"chunk_id": section.chunk_id, "offset": "-3"})
    assert response.status_code == 400
    assert response.content == expected
    assert response.json()["error"]["code"] == "limit_invalid_value"


def test_explain_refusal_matches_mcp(
    client: TestClient, mcp_provider: ManifestBeaconProvider
) -> None:
    concept = QUERY_MARKER + _OVER_CAP_PAD
    expected = _canonical(_mcp_payload(ExplainConceptTool(), concept=concept))
    response = client.get("/v1/explain", params={"concept": concept})
    assert response.status_code == 400
    assert response.content == expected
    assert response.json()["error"]["code"] == "limit_query_bytes"


def test_unknown_decision_refusal(client: TestClient) -> None:
    response = client.get("/v1/decisions/adr-9999")
    assert response.status_code == 404
    assert response.json() == {
        "error_version": "1.0",
        "error": {"code": "not_found", "message": "not found"},
    }


# ---------------------------------------------------------------------------
# Serving policy: withheld documents and decisions are absent everywhere
# ---------------------------------------------------------------------------


def test_withheld_decision_probes_like_a_bogus_id(client: TestClient) -> None:
    withheld = client.get("/v1/decisions/adr-0010")
    bogus = client.get("/v1/decisions/zzz-bogus")
    assert withheld.status_code == bogus.status_code == 404
    assert withheld.content == bogus.content
    index = client.get("/v1/decisions")
    assert index.status_code == 200
    assert [entry["id"] for entry in index.json()["decisions"]] == ["adr-0005"]
    assert "adr-0010" not in index.text
    assert "Canonical Self Identity" not in index.text
    assert "docs/adr/0010-self.md" not in index.text


def test_withheld_document_is_absent_from_every_dynamic_answer(client: TestClient) -> None:
    # A word that occurs only in the local-only document matches nothing at all:
    # the export left the document out of the index entirely.
    search = client.get("/v1/search", params={"q": "operator", "types": "docs"})
    assert search.status_code == 200
    assert search.json()["results"] == []
    probes = (
        ("/v1/search", {"q": "operator", "types": "docs"}),
        ("/v1/read", {"path": "docs/guide.md", "heading": "Setup"}),
        ("/v1/explain", {"concept": "namespace_isolation"}),
        ("/v1/decisions", None),
        ("/v1/decisions/adr-0005", None),
    )
    for path, params in probes:
        response = client.get(path, params=params)
        assert response.status_code == 200, path
        assert LOCAL_MARKER not in response.text, path
        assert "docs/local.md" not in response.text, path


def test_search_finds_the_served_decision_and_read_reaches_it(client: TestClient) -> None:
    search = client.get("/v1/search", params={"q": "namespace isolation", "types": "decisions"})
    hits = search.json()["results"]
    assert hits[0]["source_type"] == "decision"
    assert hits[0]["chunk_id"]
    section = client.get("/v1/read", params={"chunk_id": hits[0]["chunk_id"]})
    assert section.status_code == 200
    assert section.json()["heading"].endswith("> Decision")
    assert "Namespace isolation is enforced below transport-specific code." in section.text


# ---------------------------------------------------------------------------
# Limits, parameters and methods
# ---------------------------------------------------------------------------


def test_bad_parameter_types_are_deterministic_400s(client: TestClient) -> None:
    missing_q = client.get("/v1/search")
    assert missing_q.status_code == 400
    assert missing_q.json() == {
        "error_version": "1.0",
        "error": {"code": "missing_parameter", "message": "missing required parameter: q"},
    }
    assert client.get("/v1/search").content == missing_q.content

    bad_limit = client.get("/v1/search", params={"q": "guide", "limit": "abc"})
    assert bad_limit.status_code == 400
    assert bad_limit.json()["error"]["code"] == "invalid_parameter"
    # Any rejected value yields the same body: the value is never echoed.
    assert client.get("/v1/search", params={"q": "guide", "limit": "not-a-number"}).content == (
        bad_limit.content
    )

    for params in (
        {"chunk_id": "c1-x", "offset": "abc"},
        {"chunk_id": "c1-x", "max_chars": "abc"},
        {"chunk_id": "c1-x", "line": "1.5"},
    ):
        response = client.get("/v1/read", params=params)
        assert response.status_code == 400, params
        assert response.json()["error"]["code"] == "invalid_parameter", params

    missing_concept = client.get("/v1/explain")
    assert missing_concept.status_code == 400
    assert missing_concept.json()["error"]["code"] == "missing_parameter"


def test_dynamic_routes_support_get_and_head_only(client: TestClient) -> None:
    get_response = client.get("/v1/search", params={"q": "guide"})
    head_response = client.head("/v1/search", params={"q": "guide"})
    assert head_response.status_code == 200
    assert head_response.content == b""
    assert head_response.headers["content-length"] == get_response.headers["content-length"]
    assert head_response.headers["etag"] == get_response.headers["etag"]
    for method in ("post", "put", "delete"):
        for path in ("/v1/search", "/v1/read", "/v1/explain", "/v1/decisions"):
            response = client.request(method, path)
            assert response.status_code == 405, (method, path)
            assert response.json()["error"]["code"] == "method_not_allowed"


def test_unservable_manifest_fails_closed() -> None:
    """A snapshot with no servable manifest keeps static routes, 404s the queries."""
    snapshot = Snapshot(
        beacon_snapshot_version=SNAPSHOT_VERSION,
        generator=SnapshotGenerator(distribution="archolith-beacon", version=__version__),
        content_mode=CONTENT_EMBEDDED,
        project=SnapshotProject(name="unservable", status="current", repository=""),
        manifest=SnapshotManifest(
            beacon_version="0.1",
            source_sha256="0" * 64,
            data={"project": {"name": "unservable"}},
        ),
        documents=(),
        validation=SnapshotValidation(errors=0, warnings=0),
        policy=PolicyEvaluation(servable=True, publishable=True),
        security_findings=(),
    )
    client = TestClient(create_http_app(snapshot))
    assert client.get("/v1/snapshot").status_code == 200
    assert client.get("/v1/search", params={"q": "anything"}).status_code == 404
    assert client.get("/v1/decisions").status_code == 404
    assert client.get("/v1/decisions/adr-0005").status_code == 404
    discovery = client.get("/.well-known/archolith-beacon").json()
    assert discovery["capabilities"]["query"] is False
    assert "decisions" not in discovery["resources"]
    assert "dynamic" not in discovery


def test_cli_limits_thread_into_the_query_routes(snapshot: Snapshot) -> None:
    narrow = ResourceLimits(query_bytes=16)
    client = TestClient(create_http_app(snapshot, limits=narrow))
    refused = client.get("/v1/search", params={"q": "a query longer than sixteen bytes"})
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "limit_query_bytes"
    default_client = TestClient(create_http_app(snapshot))
    assert (
        default_client.get(
            "/v1/search", params={"q": "a query longer than sixteen bytes"}
        ).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# ETag and If-None-Match
# ---------------------------------------------------------------------------


def test_dynamic_etags_are_stable_and_conditionally_served(client: TestClient) -> None:
    cases: tuple[tuple[str, dict[str, str] | None], ...] = (
        ("/v1/search", {"q": "namespace isolation"}),
        ("/v1/read", {"path": "docs/guide.md", "heading": "Setup"}),
        ("/v1/explain", {"concept": "namespace_isolation"}),
        ("/v1/decisions", None),
        ("/v1/decisions/adr-0005", None),
    )
    for url, params in cases:
        first = client.get(url, params=params)
        second = client.get(url, params=params)
        assert first.status_code == second.status_code == 200, url
        assert first.headers["etag"] == second.headers["etag"], url
        assert first.headers["etag"] == f'"{hashlib.sha256(first.content).hexdigest()}"', url
        matched = client.get(url, params=params, headers={"If-None-Match": first.headers["etag"]})
        assert matched.status_code == 304, url
        assert matched.content == b""
        stale = client.get(url, params=params, headers={"If-None-Match": '"different"'})
        assert stale.status_code == 200, url


def test_decision_index_headers_support_head_and_etag(client: TestClient) -> None:
    index_get = client.get("/v1/decisions")
    index_head = client.head("/v1/decisions")
    assert index_head.content == b""
    assert index_head.headers["content-length"] == index_get.headers["content-length"]
    assert index_head.headers["etag"] == index_get.headers["etag"]
    assert (
        client.get(
            "/v1/decisions", headers={"If-None-Match": index_get.headers["etag"]}
        ).status_code
        == 304
    )
    entry = index_get.json()["decisions"][0]
    item_url = index_get.json()["item_url_template"].replace("{id}", entry["id"])
    item = client.get(item_url)
    assert item.headers["x-beacon-decision-sha256"] == entry["sha256"]
    assert item.headers["etag"] == f'"{entry["sha256"]}"'
    assert client.get(item_url, headers={"If-None-Match": item.headers["etag"]}).status_code == 304


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discovery_lists_the_dynamic_surface(client: TestClient) -> None:
    body = client.get("/.well-known/archolith-beacon").json()
    assert body["descriptor_version"] == "1.7"
    assert body["capabilities"]["query"] is True
    assert body["capabilities"]["decisions"] is True

    index = client.get("/v1/decisions")
    assert body["resources"]["decisions"] == {
        "index_url": "/v1/decisions",
        "item_url_template": "/v1/decisions/{id}",
        "version": "1.0",
        "count": 1,
        "sha256": hashlib.sha256(index.content).hexdigest(),
        "bytes": len(index.content),
        "use_when": "why the project is built this way",
    }
    assert body["dynamic"] == {
        "search": {
            "url": "/v1/search",
            "method": "GET",
            "parameters": ["q", "types", "limit"],
            "use_when": "find documents, concepts, decisions or guardrails by keywords",
        },
        "read": {
            "url": "/v1/read",
            "method": "GET",
            "parameters": ["chunk_id", "path", "heading", "line", "max_chars", "offset"],
            "use_when": "read one section by chunk id, path or heading; continue with offset",
        },
        "explain": {
            "url": "/v1/explain",
            "method": "GET",
            "parameters": ["concept", "depth"],
            "use_when": "explain one concept in depth",
        },
    }


# ---------------------------------------------------------------------------
# No query echo on successful answers either
# ---------------------------------------------------------------------------


def test_successful_answers_never_echo_the_query(client: TestClient) -> None:
    hit = client.get("/v1/search", params={"q": f"namespace isolation {QUERY_MARKER}"})
    assert hit.status_code == 200
    assert hit.json()["results"], "the probe must exercise the with-results answer"
    miss = client.get("/v1/search", params={"q": QUERY_MARKER})
    assert miss.status_code == 200
    assert not miss.json()["results"]
    unknown = client.get("/v1/explain", params={"concept": QUERY_MARKER})
    assert unknown.status_code == 200
    for response in (hit, miss, unknown):
        assert QUERY_MARKER.lower() not in response.text.lower()
        assert QUERY_MARKER.lower() not in str(response.headers).lower()


# ---------------------------------------------------------------------------
# Review fixes (astra, PR #28)
# ---------------------------------------------------------------------------


def test_trailing_slash_is_a_plain_404_that_never_echoes_the_query(snapshot: Snapshot) -> None:
    client = TestClient(create_http_app(snapshot), follow_redirects=False)
    for route in ("/v1/search/", "/v1/read/", "/v1/explain/", "/v1/decisions/", "/v1/concepts/"):
        response = client.get(route, params={"q": QUERY_MARKER, "concept": QUERY_MARKER})
        assert response.status_code == 404, route
        assert "location" not in response.headers, route
        assert QUERY_MARKER not in response.text and QUERY_MARKER not in str(response.headers)


def test_types_filter_ignores_spaces_and_empty_items(client: TestClient) -> None:
    exact = client.get("/v1/search", params={"q": "namespace isolation", "types": "docs,decisions"})
    spaced = client.get(
        "/v1/search", params={"q": "namespace isolation", "types": " docs , decisions ,, "}
    )
    assert exact.status_code == spaced.status_code == 200
    assert spaced.content == exact.content
    assert "decision" in {hit["source_type"] for hit in spaced.json()["results"]}


def test_decisions_filter_returns_only_decisions(client: TestClient) -> None:
    decisions = client.get("/v1/search", params={"q": "namespace isolation", "types": "decisions"})
    hits = decisions.json()["results"]
    assert hits and {hit["source_type"] for hit in hits} == {"decision"}
    guardrails = client.get(
        "/v1/search", params={"q": "namespace isolation", "types": "guardrails"}
    )
    assert {hit["source_type"] for hit in guardrails.json()["results"]} == {"guardrail"}
