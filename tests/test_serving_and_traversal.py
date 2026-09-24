"""Which documents Beacon serves, and how agents traverse them.

* One serving policy decides what each surface may serve: owner ``serving.exclude`` wins
  everywhere; sensitive files, non-text files and documents with high-confidence secrets
  are never served to MCP clients; ``visibility: local`` documents never leave the machine.
* ``beacon_catalog`` lists the served documents and their sections; ``beacon_read``
  returns one section with its citation; search hits carry the same ``chunk_id`` that
  HTTP serves at ``/v1/chunks/{id}``.
* ``serving.traversal: false`` switches catalog and read off without changing the surface.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
import yaml

from beacon.core.chunk_resources import build_chunk_catalog
from beacon.core.loader import ManifestError, load_beacon_manifest
from beacon.core.schema import BeaconDoc
from beacon.core.serving_policy import (
    CONTEXT_EXPORT,
    CONTEXT_LOCAL,
    READ_NOT_FOUND,
    READ_TARGET_REQUIRED,
    TRAVERSAL_DISABLED,
    WITHHELD_EXCLUDED,
    WITHHELD_LOCAL_ONLY,
    WITHHELD_NOT_TEXT,
    WITHHELD_SENSITIVE_CONTENT,
    WITHHELD_SENSITIVE_FILE,
    ServingRequestError,
    is_excluded,
    static_withhold_code,
)
from beacon.core.snapshot import build_snapshot, snapshot_bytes
from beacon.provider.manifest_provider import ManifestBeaconProvider
from tests.test_build_intent_and_gaps import _INTENT, _invoke, _manifest, _write_intent
from tests.test_build_pipeline import _fixture_repo

# Assembled at runtime so this file never contains a key-shaped block.
_FAKE_KEY = "\n".join(
    [
        "-----BEGIN " + "PRIVATE KEY-----",
        "MIIBVQIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7",
        "-----END " + "PRIVATE KEY-----",
    ]
)

_GUIDE = """# Guide

Intro paragraph about the guide.

## Setup

Install with pip install -e . and run the tests.

## Deploy

Deploy steps for the reference environment.
"""


def _repo(
    tmp_path: Path,
    *,
    serving: dict[str, Any] | None = None,
    extra_docs: list[dict[str, Any]] | None = None,
) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "notes").mkdir()
    (root / "deploy").mkdir()
    (root / "README.md").write_text("# Demo\n\nDemo explains serving rules.\n", encoding="utf-8")
    (root / "docs" / "guide.md").write_text(_GUIDE, encoding="utf-8")
    (root / "docs" / "local.md").write_text(
        "# Local\n\nOperator notes for this machine.\n", encoding="utf-8"
    )
    (root / "notes" / "keys.md").write_text("# Keys\n\n" + _FAKE_KEY + "\n", encoding="utf-8")
    (root / "deploy" / "RUNBOOK.md").write_text(
        "# Runbook\n\nProduction host steps.\n", encoding="utf-8"
    )
    (root / "data.json").write_text('{"a": 1}\n', encoding="utf-8")
    manifest = dict(_INTENT)
    manifest["canonical_docs"] = [
        {"path": "README.md", "role": "entrypoint"},
        {"path": "docs/guide.md", "role": "workflow"},
        {"path": "docs/local.md", "role": "reference", "visibility": "local"},
        {"path": "notes/keys.md", "role": "reference"},
        {"path": "deploy/RUNBOOK.md", "role": "workflow"},
        {"path": "data.json", "role": "reference"},
        *(extra_docs or []),
    ]
    manifest["serving"] = serving if serving is not None else {"exclude": ["deploy/"]}
    (root / "beacon.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return root


def _export_safe(root: Path, **extra: Any) -> None:
    """Keep only text docs without planted secrets: export has its own blocking security gate."""
    data = yaml.safe_load((root / "beacon.yaml").read_text(encoding="utf-8"))
    data["canonical_docs"] = [
        d for d in data["canonical_docs"] if d["path"] not in ("notes/keys.md", "data.json")
    ]
    data.update(extra)
    (root / "beacon.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _provider(root: Path) -> ManifestBeaconProvider:
    return ManifestBeaconProvider.from_paths(manifest_path=root / "beacon.yaml", docs_root=root)


# -- the policy ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "patterns", "expected"),
    [
        ("deploy/RUNBOOK.md", ("deploy/",), True),
        ("deploy/a/b.md", ("deploy/*",), True),
        ("./deploy/RUNBOOK.md", ("deploy/*",), True),
        (".agent/private.md", (".agent/private.md",), True),
        (".agent/README.md", ("agent/*",), False),  # dot-folders are not stripped
        ("docs/guide.md", ("deploy/", "*.json"), False),
        ("data.json", ("*.json",), True),
    ],
)
def test_exclude_globs(path: str, patterns: tuple[str, ...], expected: bool) -> None:
    assert is_excluded(path, patterns) is expected


def test_static_rules_differ_between_local_serving_and_export() -> None:
    def code(path: str, context: str, visibility: str = "public") -> str | None:
        doc = BeaconDoc(path=path, visibility=visibility)
        return static_withhold_code(doc, exclude=("deploy/",), context=context)

    assert code("deploy/RUNBOOK.md", CONTEXT_LOCAL) == WITHHELD_EXCLUDED
    assert code("deploy/RUNBOOK.md", CONTEXT_EXPORT) == WITHHELD_EXCLUDED
    assert code(".env", CONTEXT_LOCAL) == WITHHELD_SENSITIVE_FILE
    assert code("data.json", CONTEXT_LOCAL) == WITHHELD_NOT_TEXT
    assert code("docs/local.md", CONTEXT_LOCAL, "local") is None
    assert code("docs/local.md", CONTEXT_EXPORT, "local") == WITHHELD_LOCAL_ONLY
    # Export leaves sensitive files and content to the snapshot security gate.
    assert code(".env", CONTEXT_EXPORT) is None
    assert code("README", CONTEXT_LOCAL) is None  # a name without a suffix is text


def test_loader_validates_visibility_and_serving(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    manifest = load_beacon_manifest(root / "beacon.yaml")
    assert manifest.serving.exclude == ("deploy/",) and manifest.serving.traversal is True
    assert {d.path: d.visibility for d in manifest.canonical_docs}["docs/local.md"] == "local"

    def refused(**changes: Any) -> None:
        data = yaml.safe_load((root / "beacon.yaml").read_text(encoding="utf-8"))
        data.update(changes)
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.safe_dump(data), encoding="utf-8")
        with pytest.raises(ManifestError):
            load_beacon_manifest(bad)

    refused(serving={"exclude": ["/etc/passwd"]})
    refused(serving={"exclude": ["C:/secrets"]})
    refused(serving={"traversal": "yes"})
    refused(canonical_docs=[{"path": "README.md", "visibility": "private"}])


# -- local serving (MCP) ---------------------------------------------------------------


def test_mcp_serves_only_what_the_policy_allows(tmp_path: Path) -> None:
    provider = _provider(_repo(tmp_path))
    served = {doc.path for doc in provider.manifest.canonical_docs}
    indexed = {chunk.path for chunk in provider.doc_index.chunks}
    withheld = {item.path: item.code for item in provider.withheld}

    assert served == indexed == {"README.md", "docs/guide.md", "docs/local.md"}
    assert withheld == {
        "notes/keys.md": WITHHELD_SENSITIVE_CONTENT,
        "deploy/RUNBOOK.md": WITHHELD_EXCLUDED,
        "data.json": WITHHELD_NOT_TEXT,
    }
    # Nothing a reader can reach mentions a withheld document or its content.
    everything = json.dumps(
        [asdict(provider.catalog()), asdict(provider.search(query="keys runbook production"))]
    )
    for hidden in (
        "notes/keys.md",
        "deploy/RUNBOOK.md",
        "data.json",
        "PRIVATE KEY",
        "Production host",
    ):
        assert hidden not in everything


def test_a_listed_sensitive_file_is_never_served(tmp_path: Path) -> None:
    root = _repo(tmp_path, extra_docs=[{"path": ".env", "role": "reference"}])
    (root / ".env").write_text("# Env\n\nAPI_TOKEN=placeholder\n", encoding="utf-8")
    provider = _provider(root)
    assert ".env" not in {chunk.path for chunk in provider.doc_index.chunks}
    assert {item.path: item.code for item in provider.withheld}[".env"] == WITHHELD_SENSITIVE_FILE


def test_catalog_lists_documents_with_readable_sections_and_pages(tmp_path: Path) -> None:
    provider = _provider(_repo(tmp_path))
    catalog = provider.catalog()
    assert catalog.total == 3 and [doc.path for doc in catalog.docs] == [
        "README.md",
        "docs/guide.md",
        "docs/local.md",
    ]
    guide = catalog.docs[1]
    assert [section.heading for section in guide.sections] == [
        "Guide",
        "Guide > Setup",
        "Guide > Deploy",
    ]
    assert all(section.chunk_id.startswith("c1-") for section in guide.sections)

    first_page = provider.catalog(limit=2)
    assert len(first_page.docs) == 2 and first_page.next_offset == 2
    last_page = provider.catalog(offset=2, limit=2)
    assert [doc.path for doc in last_page.docs] == [
        "docs/local.md"
    ] and last_page.next_offset is None
    assert [doc.path for doc in provider.catalog(role="workflow").docs] == ["docs/guide.md"]


def test_read_by_chunk_id_heading_and_line(tmp_path: Path) -> None:
    provider = _provider(_repo(tmp_path))
    setup = provider.catalog().docs[1].sections[1]

    by_id = provider.read(chunk_id=setup.chunk_id)
    assert by_id.path == "docs/guide.md" and by_id.heading == "Guide > Setup"
    assert "pip install -e ." in by_id.text and not by_id.truncated
    assert (by_id.line_start, by_id.line_end) == (setup.line_start, setup.line_end)
    assert by_id.sources[0].path == "docs/guide.md"

    assert provider.read(path="docs/guide.md", heading="setup").chunk_id == setup.chunk_id
    assert provider.read(path="docs/guide.md", line=setup.line_start).chunk_id == setup.chunk_id
    assert (
        provider.read(path="docs/guide.md").heading == "Guide"
    )  # a path alone reads the first section
    deploy = provider.read(chunk_id=by_id.next_chunk_id)
    assert deploy.heading == "Guide > Deploy" and deploy.next_chunk_id == ""


def test_read_caps_the_text_it_returns(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "docs" / "guide.md").write_text("# Long\n\n" + "word " * 3000 + "\n", encoding="utf-8")
    section = _provider(root).read(path="docs/guide.md", max_chars=500)
    assert section.truncated and len(section.text) == 500
    assert len(_provider(root).read(path="docs/guide.md", max_chars=10**6).text) == 8000


def test_withheld_and_unknown_reads_look_the_same(tmp_path: Path) -> None:
    provider = _provider(_repo(tmp_path))
    codes = []
    for request in (
        {"path": "deploy/RUNBOOK.md"},
        {"path": "notes/keys.md"},
        {"path": "no/such.md"},
        {"chunk_id": "c1-" + "0" * 32},
    ):
        with pytest.raises(ServingRequestError) as caught:
            provider.read(**request)
        codes.append(caught.value.code)
        assert "PRIVATE" not in str(caught.value) and "RUNBOOK" not in str(caught.value)
    assert set(codes) == {READ_NOT_FOUND}
    with pytest.raises(ServingRequestError) as caught:
        provider.read()
    assert caught.value.code == READ_TARGET_REQUIRED


def test_search_hits_carry_chunk_ids_that_read_and_http_accept(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    provider = _provider(root)
    hits = [
        hit for hit in provider.search(query="install tests").results if hit.source_type == "doc"
    ]
    assert hits and all(hit.chunk_id for hit in hits)
    assert provider.read(chunk_id=hits[0].chunk_id).path == hits[0].path

    # The same id HTTP serves: build the export snapshot and its chunk catalog.
    _export_safe(root)
    snapshot = build_snapshot(root / "beacon.yaml", docs_root=root)
    catalog = build_chunk_catalog(snapshot, snapshot_sha256="0" * 64)
    http_ids = {resource.id for resource in catalog.resources}
    assert {hit.chunk_id for hit in hits if hit.path != "docs/local.md"} <= http_ids


def test_traversal_switched_off(tmp_path: Path) -> None:
    provider = _provider(_repo(tmp_path, serving={"exclude": ["deploy/"], "traversal": False}))
    for call in (provider.catalog, lambda: provider.read(path="README.md")):
        with pytest.raises(ServingRequestError) as caught:
            call()
        assert caught.value.code == TRAVERSAL_DISABLED
    hits = provider.search(query="install tests").results
    assert hits and all(hit.chunk_id == "" for hit in hits)


# -- export ----------------------------------------------------------------------------


def test_export_drops_excluded_and_local_documents(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _export_safe(
        root, agent_guidance={"read_first": ["README.md", "docs/local.md", "deploy/RUNBOOK.md"]}
    )

    snapshot = build_snapshot(root / "beacon.yaml", docs_root=root)
    assert {doc.path for doc in snapshot.documents} == {"README.md", "docs/guide.md"}
    body = snapshot_bytes(snapshot).decode("utf-8")
    for hidden in (
        "docs/local.md",
        "Operator notes",
        "deploy/RUNBOOK.md",
        "Production host",
        '"serving"',
    ):
        assert hidden not in body


# -- build ------------------------------------------------------------------------------


def test_build_drops_excluded_and_sensitive_docs_and_carries_serving(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    (root / ".env").write_text("TOKEN=placeholder\n", encoding="utf-8")
    (root / "docs" / "local.md").write_text("# Local\n\nOperator notes.\n", encoding="utf-8")
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "add", "-f", ".env", "docs/local.md"], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-qm", "docs"], check=True, capture_output=True)
    intent = dict(_INTENT)
    intent["canonical_docs"] = [
        {"path": "README.md", "role": "entrypoint"},
        {"path": "docs/architecture.md", "role": "architecture"},
        {"path": "docs/local.md", "role": "reference", "visibility": "local"},
        {"path": ".env", "role": "reference"},
    ]
    intent["serving"] = {"exclude": ["docs/architecture.md"], "traversal": False}
    _write_intent(root, intent)

    code, payload = _invoke(root)

    assert code == 0, payload
    generated = _manifest(root)
    docs = {doc["path"]: doc for doc in generated["canonical_docs"]}
    # Excluded even though memory evidence also cites it; the sensitive file is omitted.
    assert "docs/architecture.md" not in docs and ".env" not in docs
    assert docs["docs/local.md"]["visibility"] == "local"
    assert "visibility" not in docs["README.md"]  # the default is not written
    assert generated["serving"] == {"exclude": ["docs/architecture.md"], "traversal": False}


# -- MCP rendering ------------------------------------------------------------------------


async def test_mcp_tools_render_refusals_as_structured_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from beacon.mcp import contracts
    from beacon.mcp.tools.catalog import CatalogTool
    from beacon.mcp.tools.read import ReadTool

    provider = _provider(_repo(tmp_path))
    monkeypatch.setattr(contracts, "get_provider", lambda: provider)

    catalog = json.loads(await CatalogTool().execute())
    assert [doc["path"] for doc in catalog["docs"]] == [
        "README.md",
        "docs/guide.md",
        "docs/local.md",
    ]
    refused = json.loads(await ReadTool().execute(path="deploy/RUNBOOK.md"))
    assert refused == {
        "ok": False,
        "tool": "beacon_read",
        "error": {"code": READ_NOT_FOUND, "message": "no served section matches that request"},
    }
    section = json.loads(
        await ReadTool().execute(chunk_id=catalog["docs"][1]["sections"][1]["chunk_id"])
    )
    assert section["heading"] == "Guide > Setup" and section["status"] and section["sources"]
