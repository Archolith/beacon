"""Architecture decision records: read verbatim from the project's own files and served.

* The reader copies the Decision section, alternatives and status as written; status
  qualifiers ("target architecture") set ``implemented: false``; supersession comes
  from metadata only; files it cannot read fully are reported, never guessed.
* The build publishes each ADR as a ``decision`` document plus a ``decisions[]`` entry,
  and a decision is served only while its ADR file is (exclude, visibility, context).
* ``beacon_search`` finds decisions (filtered and unfiltered); ``beacon_explain_concept``
  explains one by id or title with its rejected alternatives.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from beacon.core.loader import ManifestError, parse_manifest
from beacon.core.schema import BeaconDoc
from beacon.core.serving_policy import CONTEXT_EXPORT, CONTEXT_LOCAL, manifest_for_context
from beacon.core.validator import CODE_DECISION_DOC_UNLISTED, validate_beacon_manifest
from beacon.provider.manifest_provider import ManifestBeaconProvider
from beacon.sources.adrs import collect_adrs, parse_adr
from tests.test_build_intent_and_gaps import _INTENT, _invoke, _manifest, _write_intent
from tests.test_build_pipeline import _fixture_repo

_MENHIR_STYLE = """# ADR 0005 \u2014 Core-Enforced Namespace Isolation

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

_TARGET = """# ADR 0010 \u2014 Canonical Self Identity

- **Status:** ACCEPTED as target architecture (2026-09-21). Enforcement remains default-off.
- **Date:** 2026-09-21

## Decision

One canonical identity per logical namespace.
"""

_NYGARD = """# 1. Use Postgres for events

Date: 2025-01-10

## Status

Superseded by ADR-0002

## Context

We need ordered events.

## Decision

Store events in Postgres.

## Consequences

One more service.
"""

_MADR = """---
status: accepted
date: 2025-03-02
supersedes: ADR-0001
---
# Use SQLite for events

## Context and Problem Statement

Postgres is more than a single node needs.

## Considered Options

* Postgres
* SQLite

## Decision Outcome

Chosen option: "SQLite", because it runs in-process.
"""


# -- the reader ---------------------------------------------------------------------------


def test_nygard_bullets_are_read_verbatim_with_alternatives_and_spans() -> None:
    record, gaps = parse_adr(".agent/adr/0005-isolation.md", _MENHIR_STYLE)
    assert record is not None and gaps == []
    assert record["id"] == "adr-0005" and record["title"] == "Core-Enforced Namespace Isolation"
    assert record["status"] == "current" and "implemented" not in record
    assert record["status_text"].startswith("ACCEPTED retrospectively (2026-09-21). This records")
    assert record["decision"] == "Namespace isolation is enforced below transport-specific code."
    assert record["alternatives"][1] == {
        "alternative": "Trust the caller's namespace argument",
        "reason": "Rejected. Authentication identifies the caller; it does not make target "
        "selection safe.",
    }
    lines = _MENHIR_STYLE.split("\n")
    context = record["sections"]["context"]
    assert lines[context["line_start"] - 1].startswith("")  # 1-based and inside the file
    assert "Checks were added" in "\n".join(lines[context["line_start"] - 1 : context["line_end"]])
    source = record["sources"][0]
    assert source["digest"].startswith("sha256:")
    assert "Namespace isolation" in "\n".join(lines[source["line_start"] - 1 : source["line_end"]])
    # Body prose that mentions another ADR is not a supersession claim.
    assert record["supersedes"] == [] and record["superseded_by"] == []


def test_an_accepted_target_is_marked_not_implemented() -> None:
    record, _ = parse_adr("docs/adr/0010-self.md", _TARGET)
    assert record is not None
    assert record["status"] == "current" and record["implemented"] is False


def test_classic_nygard_superseded_and_madr_frontmatter() -> None:
    old, _ = parse_adr("docs/adr/0001-postgres.md", _NYGARD)
    new, gaps = parse_adr("docs/adr/0002-sqlite.md", _MADR)
    assert old is not None and new is not None
    assert old["status"] == "superseded" and old["superseded_by"] == ["adr-0002"]
    assert old["date"] == "2025-01-10"
    assert new["id"] == "adr-0002" and new["status"] == "current"
    assert new["supersedes"] == ["adr-0001"] and new["date"] == "2025-03-02"
    assert [a["alternative"] for a in new["alternatives"]] == ["Postgres", "SQLite"]
    assert new["decision"].startswith('Chosen option: "SQLite"')
    assert [gap.code for gap in gaps] == ["adr_no_consequences"]


def test_unreadable_parts_are_gaps_not_guesses() -> None:
    record, gaps = parse_adr("docs/adr/0003-x.md", "# 3. X\n\n## Context\n\nNo decision.\n")
    assert record is None
    assert {gap.code for gap in gaps} == {"adr_status_unrecognised", "adr_no_decision"}
    record, gaps = parse_adr(
        "docs/adr/0004-y.md", "# 4. Y\n\nStatus: Pondering\n\n## Decision\n\nY.\n"
    )
    assert record is not None and record["status"] == "unknown"
    assert "adr_status_unrecognised" in {gap.code for gap in gaps}


def test_a_long_decision_is_capped_and_says_so() -> None:
    text = _TARGET.replace("One canonical identity", "word " * 2000)
    record, _ = parse_adr("docs/adr/0010-self.md", text)
    assert record is not None and record["truncated"] is True and len(record["decision"]) == 4000


def _read(root: Path, rel: str) -> str | None:
    path = root / rel
    return path.read_text(encoding="utf-8") if path.is_file() else None


def test_collect_reads_default_and_named_dirs_and_skips_indexes(tmp_path: Path) -> None:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "design" / "records").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "README.md").write_text("# Index\n", encoding="utf-8")
    (tmp_path / "docs" / "adr" / "0000-template.md").write_text(_TARGET, encoding="utf-8")
    (tmp_path / "docs" / "adr" / "0010-self.md").write_text(_TARGET, encoding="utf-8")
    (tmp_path / "design" / "records" / "0010-other.md").write_text(_TARGET, encoding="utf-8")
    default_only = collect_adrs(tmp_path, _read)
    assert default_only.paths == ("docs/adr/0010-self.md",)
    both = collect_adrs(tmp_path, _read, adr_dirs=("design/records",))
    # Named directories come first; a repeated number gets a stable suffix.
    assert [d["id"] for d in both.decisions] == ["adr-0010", "adr-0010-2"]


def test_an_adr_with_a_secret_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    key = (
        "-----BEGIN "
        + "PRIVATE KEY-----\nMIIBVQIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7\n-----END "
        + "PRIVATE KEY-----"
    )
    (tmp_path / "docs" / "adr" / "0001-keys.md").write_text(
        _TARGET.replace("One canonical identity per logical namespace.", key), encoding="utf-8"
    )
    facts = collect_adrs(tmp_path, _read)
    assert facts.decisions == () and [g.code for g in facts.gaps] == ["adr_sensitive_content"]


# -- manifest, validation and serving -----------------------------------------------------


def _decision_manifest(visibility: str = "public") -> Any:
    record, _ = parse_adr("docs/adr/0005-isolation.md", _MENHIR_STYLE)
    raw = dict(_INTENT)
    raw["canonical_docs"] = [
        {"path": "README.md", "role": "entrypoint"},
        {"path": "docs/adr/0005-isolation.md", "role": "decision", "visibility": visibility},
    ]
    raw["decisions"] = [record]
    return parse_manifest(raw)


def test_decisions_round_trip_and_must_cite_a_listed_document() -> None:
    manifest = _decision_manifest()
    decision = manifest.decisions[0]
    assert decision.alternatives[0].alternative == "Enforce the pin in every route"
    assert decision.sections["consequences"].line_start > decision.sections["context"].line_end
    unlisted = replace(manifest, canonical_docs=(BeaconDoc(path="README.md"),))
    codes = {issue.code for issue in validate_beacon_manifest(unlisted).issues}
    assert CODE_DECISION_DOC_UNLISTED in codes


@pytest.mark.parametrize("value", ["/etc/adr", "C:/adr", "../adr", ["a", 3]])
def test_adr_dir_must_be_repository_relative(value: Any) -> None:
    raw = dict(_INTENT)
    raw["adr_dir"] = value
    with pytest.raises(ManifestError):
        parse_manifest(raw)


def test_a_decision_is_served_only_where_its_adr_file_is() -> None:
    local_only = _decision_manifest(visibility="local")
    served, _ = manifest_for_context(local_only, context=CONTEXT_LOCAL)
    exported, withheld = manifest_for_context(local_only, context=CONTEXT_EXPORT)
    assert [d.id for d in served.decisions] == ["adr-0005"]
    assert exported.decisions == () and [w.path for w in withheld] == ["docs/adr/0005-isolation.md"]
    excluded = replace(
        _decision_manifest(),
        serving=replace(_decision_manifest().serving, exclude=("docs/adr/",)),
    )
    assert manifest_for_context(excluded, context=CONTEXT_LOCAL)[0].decisions == ()


# -- build and serve end to end -----------------------------------------------------------


def _commit(root: Path, *paths: str) -> None:
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "add", *paths], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-qm", "adrs"], check=True, capture_output=True)


def _adr_repo(tmp_path: Path, intent_extra: dict[str, Any] | None = None) -> Path:
    root = _fixture_repo(tmp_path)
    (root / "docs" / "adr").mkdir()
    (root / "docs" / "adr" / "0005-isolation.md").write_text(_MENHIR_STYLE, encoding="utf-8")
    (root / "docs" / "adr" / "0010-self.md").write_text(_TARGET, encoding="utf-8")
    (root / "records").mkdir()
    (root / "records" / "0001-postgres.md").write_text(_NYGARD, encoding="utf-8")
    _commit(root, "docs/adr", "records")
    _write_intent(root, {**_INTENT, **(intent_extra or {})})
    return root


def test_build_publishes_adrs_as_decisions_and_documents(tmp_path: Path) -> None:
    root = _adr_repo(tmp_path, {"adr_dir": "records"})
    code, payload = _invoke(root)
    assert code == 0, payload
    generated = _manifest(root)
    assert [d["id"] for d in generated["decisions"]] == ["adr-0001", "adr-0005", "adr-0010"]
    docs = {doc["path"]: doc for doc in generated["canonical_docs"]}
    assert docs["docs/adr/0005-isolation.md"]["role"] == "decision"
    assert docs["records/0001-postgres.md"]["status"] == "superseded"
    assert "adr_dir" not in generated  # build configuration is not published
    by_id = {d["id"]: d for d in generated["decisions"]}
    assert by_id["adr-0010"]["implemented"] is False
    assert "implemented" not in by_id["adr-0005"]


def test_build_leaves_out_an_excluded_adr(tmp_path: Path) -> None:
    root = _adr_repo(tmp_path, {"serving": {"exclude": ["docs/adr/0010-self.md"]}})
    code, payload = _invoke(root)
    assert code == 0, payload
    generated = _manifest(root)
    assert [d["id"] for d in generated["decisions"]] == ["adr-0005"]
    assert "docs/adr/0010-self.md" not in {d["path"] for d in generated["canonical_docs"]}


def test_search_and_explain_serve_decisions(tmp_path: Path) -> None:
    root = _adr_repo(tmp_path, {"adr_dir": "records"})
    assert _invoke(root)[0] == 0
    provider = ManifestBeaconProvider.from_paths(
        manifest_path=root / "beacon.generated.yaml", docs_root=root
    )
    filtered = provider.search(query="namespace isolation", source_types=("decisions",))
    assert [hit.title for hit in filtered.results][
        0
    ] == "adr-0005: Core-Enforced Namespace Isolation"
    hit = filtered.results[0]
    assert hit.source_type == "decision" and hit.chunk_id
    assert provider.read(chunk_id=hit.chunk_id).heading.endswith("> Decision")
    unfiltered = provider.search(query="namespace isolation", limit=3)
    assert "decision" in {h.source_type for h in unfiltered.results}

    explained = provider.explain_concept(concept="adr-0005")
    assert explained.definition == "Namespace isolation is enforced below transport-specific code."
    assert "Trust the caller's namespace argument: Rejected." in explained.why_it_exists
    assert any(
        note.startswith("context: beacon_read path=docs/adr/0005")
        for note in explained.next_actions
    )
    by_title = provider.explain_concept(concept="Canonical Self Identity")
    assert by_title.concept.startswith("adr-0010")
    assert by_title.next_actions[0].startswith("accepted but not in effect yet")
    superseded = provider.explain_concept(concept="adr-0001")
    assert superseded.status == "uncertain" and "superseded by adr-0002" in superseded.next_actions


def test_a_project_without_adrs_publishes_no_decisions_key(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    _write_intent(root)
    assert _invoke(root)[0] == 0
    assert "decisions" not in _manifest(root)
    assert yaml.safe_load((root / "beacon.generated.yaml").read_text(encoding="utf-8"))


def test_export_carries_public_decisions_and_drops_local_ones(tmp_path: Path) -> None:
    from beacon.core.snapshot import build_snapshot, snapshot_bytes

    local_adr = {"path": "docs/adr/0010-self.md", "role": "decision", "visibility": "local"}
    root = _adr_repo(
        tmp_path,
        {"canonical_docs": [*_INTENT["canonical_docs"], local_adr]},
    )
    assert _invoke(root)[0] == 0, "build failed"
    snapshot = build_snapshot(root / "beacon.generated.yaml", docs_root=root)
    body = snapshot_bytes(snapshot).decode("utf-8")
    assert "Namespace isolation is enforced" in body
    assert "One canonical identity" not in body and "0010-self" not in body
    served = ManifestBeaconProvider.from_snapshot(snapshot)
    assert [d.id for d in served.manifest.decisions] == ["adr-0005"]
    assert served.explain_concept(concept="adr-0005").why_it_exists.startswith(
        "Alternatives considered:"
    )
