"""Memory provider contract: backend-neutral evidence, bound to this checkout.

* A fake provider (a real MCP server on loopback, nothing Menhir-specific)
  supplies evidence through the same transport Beacon uses for any provider.
* The plan's Phase 2 acceptance rows each refuse before any write:
  unavailable, unauthorized, invalid (incl. unbound 1.0 evidence on a
  publishing build), binding mismatch, stale checkout.
* The published 1.1 schema and the adapter agree.
"""

from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from typer.testing import CliRunner

from beacon.main import app
from beacon.sources.memory import MemoryEvidenceError, parse_evidence_document
from tests.test_build_pipeline import _evidence_file, _fixture_repo

runner = CliRunner()
_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_1_1 = json.loads(
    (_ROOT / "docs" / "schemas" / "beacon-memory-evidence-1.1.schema.json").read_text(
        encoding="utf-8"
    )
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


def _build(root: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    result = runner.invoke(
        app, ["build", "--repo", str(root), "--format", "json", *extra], catch_exceptions=False
    )
    return result.exit_code, json.loads(result.output)


def _code(payload: dict[str, Any]) -> str:
    return str(payload["diagnostics"][0]["code"])


# ---------------------------------------------------------------------------
# A loopback server helper
# ---------------------------------------------------------------------------


@contextmanager
def _serve(asgi_app: Any) -> Iterator[str]:
    """Run *asgi_app* on a free loopback port; yield its base URL."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(asgi_app, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "test server did not start"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _fake_provider(evidence_for: Callable[[str], str]) -> Any:
    """A minimal memory provider: one read-only tool, no Menhir code."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("fake-memory-provider")

    @server.tool(name="get_beacon_evidence")
    def get_beacon_evidence(project_id: str) -> str:
        return evidence_for(project_id)

    return server.streamable_http_app()


# ---------------------------------------------------------------------------
# Fake provider end to end
# ---------------------------------------------------------------------------


def test_fake_provider_supplies_evidence_over_mcp(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path / "repo")
    document = _evidence_file(tmp_path, ["README.md"])  # outside the repo
    bound = json.loads(document.read_text(encoding="utf-8"))
    bound["binding"]["indexed_commit"] = _head(root)
    text = json.dumps(bound)  # its root is another directory: never compared

    with _serve(_fake_provider(lambda _project: text)) as base:
        code, payload = _build(root, "--memory", f"{base}/mcp", "--memory-project", "fixture")

    assert code == 0, payload
    result = payload["result"]
    assert result["memory"]["provider"] == "fixture-provider"
    assert result["memory"]["bound"] is True
    rows = {row["field"]: row for row in result["requirements"]}
    assert rows["project.name"]["supplied_by"] == ["memory"]
    assert (root / "beacon.generated.yaml").is_file()


def test_provider_evidence_for_another_project_is_refused(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path / "repo")
    document = _evidence_file(tmp_path, ["README.md"])
    bound = json.loads(document.read_text(encoding="utf-8"))
    bound["binding"]["indexed_commit"] = _head(root)
    bound["binding"]["project_id"] = "someone-else"
    text = json.dumps(bound)

    with _serve(_fake_provider(lambda _project: text)) as base:
        code, payload = _build(root, "--memory", f"{base}/mcp", "--memory-project", "fixture")

    assert code == 2
    assert _code(payload) == "memory_binding_mismatch"
    assert not (root / "beacon.generated.yaml").exists()


# ---------------------------------------------------------------------------
# Acceptance rows: each refuses before any write
# ---------------------------------------------------------------------------


def test_unreachable_provider_is_memory_unavailable(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    code, payload = _build(
        root, "--memory", f"http://127.0.0.1:{closed_port}/mcp", "--memory-project", "fixture"
    )

    assert code == 2
    assert _code(payload) == "memory_unavailable"
    assert not (root / "beacon.generated.yaml").exists()


def test_rejected_credential_is_memory_unauthorized(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)

    async def deny(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("unauthorized", status_code=401)

    denying = Starlette(routes=[Route("/mcp", deny, methods=["GET", "POST", "DELETE"])])
    with _serve(denying) as base:
        code, payload = _build(root, "--memory", f"{base}/mcp", "--memory-project", "fixture")

    assert code == 2
    assert _code(payload) == "memory_unauthorized"
    assert not (root / "beacon.generated.yaml").exists()


def test_credential_never_travels_in_the_url(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    code, payload = _build(
        root, "--memory", "https://user:secret@example.com/mcp", "--memory-project", "fixture"
    )
    assert code == 2
    assert _code(payload) == "memory_invalid"
    assert "secret" not in json.dumps(payload)


def test_unbound_legacy_evidence_cannot_publish(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    legacy = json.loads(evidence.read_text(encoding="utf-8"))
    legacy["evidence_version"] = "1.0"
    del legacy["binding"]
    evidence.write_text(json.dumps(legacy), encoding="utf-8")

    code, payload = _build(root, "--memory-evidence", str(evidence))
    assert code == 2
    assert _code(payload) == "memory_invalid"
    assert not (root / "beacon.generated.yaml").exists()

    # ...but a gap report may still read it.
    code, payload = _build(root, "--memory-evidence", str(evidence), "--gaps-only")
    assert code == 0, payload
    assert payload["result"]["buildable"] is True


def test_evidence_for_another_repository_is_refused(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _git(root, "remote", "add", "origin", "git@github.com:someone/other.git")
    evidence = _evidence_file(root, ["README.md"])

    code, payload = _build(root, "--memory-evidence", str(evidence))

    assert code == 2
    assert _code(payload) == "memory_binding_mismatch"


def test_repository_identity_ignores_spelling(tmp_path: Path) -> None:
    """ssh vs https, trailing .git and case do not make a different repository."""
    root = _fixture_repo(tmp_path)
    _git(root, "remote", "add", "origin", "git@github.com:Archolith/Beacon.git")
    evidence = _evidence_file(root, ["README.md"])
    bound = json.loads(evidence.read_text(encoding="utf-8"))
    bound["binding"]["repository"] = "https://github.com/archolith/beacon"
    evidence.write_text(json.dumps(bound), encoding="utf-8")

    code, payload = _build(root, "--memory-evidence", str(evidence))
    assert code == 0, payload


def test_a_commit_after_indexing_is_stale(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    (root / "NEW.md").write_text("new\n", encoding="utf-8")
    _git(root, "add", "NEW.md")
    _git(root, "commit", "-q", "-m", "after indexing")

    code, payload = _build(root, "--memory-evidence", str(evidence))

    assert code == 2
    assert _code(payload) == "memory_stale"
    assert not (root / "beacon.generated.yaml").exists()


def test_uncommitted_changes_outside_the_build_are_stale(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    (root / "README.md").write_text("# Fixture\nEdited after indexing.\n", encoding="utf-8")

    code, payload = _build(root, "--memory-evidence", str(evidence))

    assert code == 2
    assert _code(payload) == "memory_stale"
    assert "README.md" in payload["diagnostics"][0]["message"]


def test_editing_beacon_yaml_after_indexing_is_allowed(tmp_path: Path) -> None:
    """The project's own manifest and Beacon's outputs may change: that is the workflow."""
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    code, payload = _build(root, "--memory-evidence", str(evidence))
    assert code == 0, payload  # the first build's output is now an uncommitted file

    (root / "beacon.yaml").write_text(
        "beacon_version: '0.1'\n"
        "project: {name: fixture, description: Written after indexing.}\n"
        "canonical_docs: [{path: README.md, role: entrypoint}]\n",
        encoding="utf-8",
    )
    code, payload = _build(root, "--memory-evidence", str(evidence), "--force")

    assert code == 0, payload
    assert payload["result"]["intent"]["source"] == "repo_default"


def test_a_commit_during_the_build_is_caught_at_the_last_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import beacon.build.policy as policy_mod

    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    original = policy_mod.resolve_project_facts

    def commit_then_resolve(**kwargs: Any) -> Any:
        (root / "LATE.md").write_text("late\n", encoding="utf-8")
        _git(root, "add", "LATE.md")
        _git(root, "commit", "-q", "-m", "during the build")
        return original(**kwargs)

    monkeypatch.setattr(policy_mod, "resolve_project_facts", commit_then_resolve)
    code, payload = _build(root, "--memory-evidence", str(evidence))

    assert code == 2
    assert _code(payload) == "memory_stale"
    assert not (root / "beacon.generated.yaml").exists()


# ---------------------------------------------------------------------------
# Schema 1.1 and the adapter agree
# ---------------------------------------------------------------------------


def _document(tmp_path: Path) -> dict[str, Any]:
    root = _fixture_repo(tmp_path)
    return json.loads(_evidence_file(root, ["README.md"]).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("binding"),
        lambda d: d["binding"].pop("indexed_commit"),
        lambda d: d["binding"].__setitem__("indexed_commit", "not-a-commit"),
        lambda d: d["binding"].__setitem__("extra", "x"),
        lambda d: d["binding"].__setitem__("provider", ""),
    ],
    ids=["no-binding", "no-commit", "bad-commit", "unknown-key", "blank-provider"],
)
def test_schema_and_adapter_reject_the_same_bindings(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], Any]
) -> None:
    document = _document(tmp_path)
    mutate(document)
    assert list(jsonschema.Draft202012Validator(_SCHEMA_1_1).iter_errors(document))
    with pytest.raises(MemoryEvidenceError):
        parse_evidence_document(json.dumps(document).encode("utf-8"))


def test_schema_and_adapter_accept_a_bound_document(tmp_path: Path) -> None:
    document = _document(tmp_path)
    jsonschema.Draft202012Validator.check_schema(_SCHEMA_1_1)
    assert not list(jsonschema.Draft202012Validator(_SCHEMA_1_1).iter_errors(document))
    evidence = parse_evidence_document(json.dumps(document).encode("utf-8"))
    assert evidence.bound
    assert evidence.binding == document["binding"]


def _head(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_remote_provider_without_a_credential_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture_repo(tmp_path)
    monkeypatch.delenv("BEACON_MEMORY_TOKEN", raising=False)

    code, payload = _build(
        root, "--memory", "https://memory.example.invalid/mcp", "--memory-project", "fixture"
    )

    assert code == 2
    assert _code(payload) == "memory_unauthorized"
    assert "BEACON_MEMORY_TOKEN" in payload["diagnostics"][0]["message"]


def test_a_provider_side_root_path_is_not_compared(tmp_path: Path) -> None:
    """Bound evidence made on another machine carries that machine's path."""
    root = _fixture_repo(tmp_path)
    evidence = _evidence_file(root, ["README.md"])
    bound = json.loads(evidence.read_text(encoding="utf-8"))
    bound["project"]["root"] = "/srv/provider/checkouts/fixture"
    evidence.write_text(json.dumps(bound), encoding="utf-8")

    code, payload = _build(root, "--memory-evidence", str(evidence))

    assert code == 0, payload


def test_different_ports_are_different_repositories(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _git(root, "remote", "add", "origin", "https://git.example:8443/org/repo.git")
    evidence = _evidence_file(root, ["README.md"])
    bound = json.loads(evidence.read_text(encoding="utf-8"))
    bound["binding"]["repository"] = "https://git.example:9443/org/repo.git"
    evidence.write_text(json.dumps(bound), encoding="utf-8")

    code, payload = _build(root, "--memory-evidence", str(evidence))

    assert code == 2
    assert _code(payload) == "memory_binding_mismatch"
