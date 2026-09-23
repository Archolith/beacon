"""Asking a memory provider by repository when the project's id is not known.

A provider owns its project ids and keeps them to itself (Menhir writes nothing into a checkout),
so ``beacon build --memory`` without ``--memory-project`` asks by this checkout's origin. The
evidence that comes back is still held to the same binding and freshness checks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.test_build_pipeline import _evidence_file, _fixture_repo
from tests.test_memory_provider import _build, _code, _git, _head, _serve

ORIGIN = "git@github.com:org/shop.git"


def _provider(calls: list[dict[str, str]], answer: Any) -> Any:
    """A provider that accepts either selector, as the contract allows."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("fake-lookup-provider")

    @server.tool(name="get_beacon_evidence")
    def get_beacon_evidence(project_id: str = "", repository: str = "") -> str:
        calls.append({"project_id": project_id, "repository": repository})
        return answer() if callable(answer) else answer

    return server.streamable_http_app()


def _bound_evidence(root: Path, tmp_path: Path) -> str:
    document = json.loads(_evidence_file(tmp_path, ["README.md"]).read_text(encoding="utf-8"))
    document["binding"]["indexed_commit"] = _head(root)
    document["binding"]["repository"] = "https://github.com/org/shop"
    document["binding"]["project_id"] = "menhir-uuid-1"
    return json.dumps(document)


def test_without_a_project_id_the_provider_is_asked_by_origin(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path / "repo")
    _git(root, "remote", "add", "origin", ORIGIN)
    calls: list[dict[str, str]] = []

    with _serve(_provider(calls, _bound_evidence(root, tmp_path))) as base:
        code, payload = _build(root, "--memory", f"{base}/mcp")

    assert code == 0, payload
    # Beacon's git tier reports the scp-style origin in https form; the provider compares
    # repository identity, not spelling.
    assert calls == [{"project_id": "", "repository": "https://github.com/org/shop.git"}]
    assert payload["result"]["memory"]["bound"] is True
    assert (root / "beacon.generated.yaml").is_file()


def test_evidence_found_by_origin_is_still_checked_against_this_checkout(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path / "repo")
    _git(root, "remote", "add", "origin", ORIGIN)
    document = json.loads(_bound_evidence(root, tmp_path))
    document["binding"]["repository"] = "https://github.com/org/other"
    calls: list[dict[str, str]] = []

    with _serve(_provider(calls, json.dumps(document))) as base:
        code, payload = _build(root, "--memory", f"{base}/mcp")

    assert code == 2
    assert _code(payload) == "memory_binding_mismatch"
    assert not (root / "beacon.generated.yaml").exists()


def test_a_provider_refusal_by_origin_writes_nothing(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path / "repo")
    _git(root, "remote", "add", "origin", ORIGIN)

    def several() -> str:
        raise ValueError("2 indexed projects recorded repository; name one with project_id")

    with _serve(_provider([], several)) as base:
        code, payload = _build(root, "--memory", f"{base}/mcp")

    assert code == 2
    assert _code(payload) == "memory_invalid"
    assert not (root / "beacon.generated.yaml").exists()


def test_no_project_id_and_no_origin_is_refused_before_asking(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path / "repo")
    calls: list[dict[str, str]] = []

    with _serve(_provider(calls, "{}")) as base:
        code, payload = _build(root, "--memory", f"{base}/mcp")

    assert code == 2
    assert _code(payload) == "build_memory_conflict"
    assert calls == []
