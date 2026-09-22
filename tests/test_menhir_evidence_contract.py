"""Contract tests: the Menhir evidence adapter enforces the published schema.

``docs/schemas/beacon-menhir-evidence-1.0.schema.json`` is the boundary
Menhir writes against. These tests pin schema/adapter parity in both
directions that matter to the producer:

* a document Menhir's real generator emits (the checked-in fixture mirrors
  ``menhir.services.beacon_evidence.capture_evidence`` output) is valid under
  the schema *and* accepted by the adapter;
* every schema-invalid class is refused by the adapter with the stable
  ``memory_invalid`` CLI code, a JSON pointer naming the defect, and
  no raw evidence values, absolute paths, or exception text in the message.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from typer.testing import CliRunner

from beacon.main import app
from beacon.sources.menhir import (
    MenhirEvidenceError,
    MenhirSourceAdapter,
    parse_evidence_document,
)

runner = CliRunner()

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA = json.loads(
    (_ROOT / "docs" / "schemas" / "beacon-menhir-evidence-1.0.schema.json").read_text(
        encoding="utf-8"
    )
)
_FIXTURE = _ROOT / "tests" / "fixtures" / "menhir" / "evidence-1.0-menhir-dump.json"


def _fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _schema_errors(payload: Any) -> list[str]:
    validator = jsonschema.Draft202012Validator(_SCHEMA)
    return [error.message for error in validator.iter_errors(payload)]


def _encode(payload: Any) -> bytes:
    return json.dumps(payload).encode("utf-8")


def test_schema_is_valid_draft_2020_12() -> None:
    jsonschema.Draft202012Validator.check_schema(_SCHEMA)


def test_menhir_dump_fixture_is_schema_valid_and_accepted() -> None:
    payload = _fixture()
    assert _schema_errors(payload) == []
    evidence = parse_evidence_document(_encode(payload))
    assert evidence.project_name == "fixture"
    assert [row["path"] for row in evidence.documents] == ["README.md", "docs/architecture.md"]


def test_full_optional_sections_are_schema_valid_and_accepted() -> None:
    payload = _fixture()
    payload["decisions"] = [
        {
            "title": "Keep one root",
            "summary": "One root.",
            "status": "superseded",
            "implementation_locations": ["src/core.py"],
        }
    ]
    payload["lifecycle"] = [
        {"subject": "Keep one root", "status": "current", "superseded_by": "", "note": ""}
    ]
    assert _schema_errors(payload) == []
    parse_evidence_document(_encode(payload))


def _mutate(path: tuple[Any, ...], value: Any, *, delete: bool = False) -> dict[str, Any]:
    payload = copy.deepcopy(_fixture())
    payload["decisions"] = [
        {"title": "Keep one root", "summary": "s", "implementation_locations": ["src/core.py"]}
    ]
    payload["lifecycle"] = [{"subject": "Keep one root", "status": "current"}]
    target: Any = payload
    for key in path[:-1]:
        target = target[key]
    if delete:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return payload


#: (id, payload, expected JSON pointer). Every payload is schema-invalid.
_INVALID_CASES: list[tuple[str, dict[str, Any], str]] = [
    ("unknown-top-level-key", _mutate(("extra_top",), 1), "/extra_top"),
    ("unknown-project-key", _mutate(("project", "future_field"), 5), "/project/future_field"),
    ("unknown-document-string-key", _mutate(("documents", 0, "size"), "12"), "/documents/0/size"),
    ("unknown-document-int-key", _mutate(("documents", 0, "size"), 12), "/documents/0/size"),
    ("unknown-file-key", _mutate(("files", 0, "owner"), "x"), "/files/0/owner"),
    ("unknown-structure-key", _mutate(("structure", "nodes"), {}), "/structure/nodes"),
    ("unknown-decision-key", _mutate(("decisions", 0, "why"), "x"), "/decisions/0/why"),
    ("unknown-lifecycle-key", _mutate(("lifecycle", 0, "when"), "x"), "/lifecycle/0/when"),
    ("project-status-not-enumerated", _mutate(("project", "status"), "bogus"), "/project/status"),
    ("project-name-wrong-type", _mutate(("project", "name"), 7), "/project/name"),
    ("project-name-empty", _mutate(("project", "name"), ""), "/project/name"),
    (
        "project-description-missing",
        _mutate(("project", "description"), None, delete=True),
        "/project/description",
    ),
    ("project-root-null", _mutate(("project", "root"), None), "/project/root"),
    ("project-missing", _mutate(("project",), None, delete=True), "/project"),
    ("version-unsupported", _mutate(("evidence_version",), "2.0"), "/evidence_version"),
    ("document-title-null", _mutate(("documents", 0, "title"), None), "/documents/0/title"),
    ("document-path-empty", _mutate(("documents", 0, "path"), ""), "/documents/0/path"),
    (
        "document-path-missing",
        _mutate(("documents", 0, "path"), None, delete=True),
        "/documents/0/path",
    ),
    ("documents-not-array", _mutate(("documents",), {}), "/documents"),
    (
        "documents-over-max-items",
        _mutate(("documents",), [{"path": f"d{i}.md"} for i in range(65)]),
        "/documents",
    ),
    (
        "structure-count-negative",
        _mutate(("structure", "entities", "file"), -1),
        "/structure/entities/file",
    ),
    (
        "structure-count-bool",
        _mutate(("structure", "edges", "IMPORTS"), True),
        "/structure/edges/IMPORTS",
    ),
    (
        "decision-status-not-enumerated",
        _mutate(("decisions", 0, "status"), "planned"),
        "/decisions/0/status",
    ),
    (
        "decision-title-missing",
        _mutate(("decisions", 0, "title"), None, delete=True),
        "/decisions/0/title",
    ),
    (
        "decision-location-empty",
        _mutate(("decisions", 0, "implementation_locations"), [""]),
        "/decisions/0/implementation_locations/0",
    ),
    (
        "lifecycle-status-missing",
        _mutate(("lifecycle", 0, "status"), None, delete=True),
        "/lifecycle/0/status",
    ),
]


@pytest.mark.parametrize(
    ("payload", "pointer"),
    [pytest.param(payload, pointer, id=case_id) for case_id, payload, pointer in _INVALID_CASES],
)
def test_schema_invalid_classes_fail_closed_with_pointer(payload: Any, pointer: str) -> None:
    # The case really is schema-invalid (the adapter mirrors, never widens).
    assert _schema_errors(payload), "fixture case must be invalid under the published schema"
    with pytest.raises(MenhirEvidenceError) as err:
        parse_evidence_document(_encode(payload))
    assert err.value.pointer == pointer
    assert pointer in str(err.value)


def test_invalid_message_carries_no_raw_values() -> None:
    secret = "bogus-status-sk_live_do_not_echo"
    payload = _mutate(("project", "status"), secret)
    with pytest.raises(MenhirEvidenceError) as err:
        parse_evidence_document(_encode(payload))
    assert secret not in str(err.value)
    unknown = _mutate(("project", "future_field"), secret)
    with pytest.raises(MenhirEvidenceError) as err:
        parse_evidence_document(_encode(unknown))
    assert secret not in str(err.value)


def _cli_message(result: Any) -> str:
    envelope = json.loads(result.output)
    diagnostics = [d for d in envelope["diagnostics"] if d["code"] == "memory_invalid"]
    assert diagnostics, envelope
    return str(diagnostics[0]["message"])


def test_cli_unreadable_evidence_message_has_no_path_or_exception_text(tmp_path: Path) -> None:
    missing = tmp_path / "secret-dir" / "nope.json"
    result = runner.invoke(
        app,
        ["build", "--menhir-evidence", str(missing), "--out", "-", "--format", "json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 2
    message = _cli_message(result)
    assert "secret-dir" not in message
    assert str(tmp_path) not in message
    assert "Errno" not in message
    assert message == "evidence document unreadable"


def test_cli_malformed_json_message_has_no_exception_text(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"evidence_version": "1.0", "project": {"name": oops}}', encoding="utf-8")
    result = runner.invoke(
        app,
        ["build", "--menhir-evidence", str(broken), "--out", "-", "--format", "json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 2
    message = _cli_message(result)
    assert "Expecting" not in message and "line 1" not in message
    assert message == "evidence document is not valid JSON"


def test_cli_schema_invalid_names_pointer(tmp_path: Path) -> None:
    evidence = tmp_path / "ev.json"
    evidence.write_text(json.dumps(_mutate(("project", "status"), "bogus")), encoding="utf-8")
    result = runner.invoke(
        app,
        ["build", "--menhir-evidence", str(evidence), "--out", "-", "--format", "json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 2
    message = _cli_message(result)
    assert "/project/status" in message
    assert "bogus" not in message


def test_adapter_reads_fixture_file(tmp_path: Path) -> None:
    records = MenhirSourceAdapter(_FIXTURE).collect()
    assert records[0].payload["name"] == "fixture"
