"""Tests for the ``beacon.cli-result`` v1.0 envelope core and its golden fixtures."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import jsonschema
import pytest

from beacon.core.cli_result import (
    COMMAND_EXPORT,
    COMMAND_INIT,
    COMMAND_INSPECT,
    COMMAND_VALIDATE,
    COMMANDS,
    ERR_ACK_REASON_INVALID,
    ERR_ACK_REASON_MISSING,
    ERR_INVALID_COMMAND,
    ERR_INVALID_DIAGNOSTIC,
    ERR_INVALID_OK,
    ERR_INVALID_SEVERITY,
    ERR_INVALID_VERSION,
    INTERNAL_ERROR_CODE,
    INTERNAL_ERROR_MESSAGE,
    MAX_CODE,
    MAX_MESSAGE,
    MIN_ACKNOWLEDGEMENT_REASON,
    MIN_CODE,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    CliResult,
    CliResultError,
    Command,
    Severity,
    acknowledge,
    diagnostic,
    dumps,
    dumps_bytes,
    from_validation_issue,
    internal_error,
    result,
    to_payload,
)
from beacon.core.validator import ValidationIssue

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "beacon-cli-result-1.0.schema.json"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "schemas"


# ---------------------------------------------------------------------------
# Shared schema / fixture helpers
# ---------------------------------------------------------------------------


def _load_schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def cli_schema() -> dict:
    return _load_schema()


# ---------------------------------------------------------------------------
# Schema meta-validation and golden fixtures
# ---------------------------------------------------------------------------


def test_schema_is_valid_draft202012(cli_schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(cli_schema)


def test_positive_fixture_validates(cli_schema: dict) -> None:
    payload = _load_fixture("cli-result-valid.json")
    jsonschema.validate(payload, cli_schema)


def test_negative_fixture_fails(cli_schema: dict) -> None:
    payload = _load_fixture("cli-result-invalid.json")
    errors = sorted(
        jsonschema.Draft202012Validator(cli_schema).iter_errors(payload),
        key=lambda e: e.validator,
    )
    assert errors, "expected the negative fixture to violate the schema"
    codes = [e.validator for e in errors]
    assert "enum" in codes  # unknown command value / invalid severity
    assert "pattern" in codes  # invalid diagnostic code
    assert "minLength" in codes  # empty diagnostic message


def test_envelope_payload_matches_positive_fixture(cli_schema: dict) -> None:
    built = result(
        "validate",
        ok=False,
        result_payload={
            "servable": False,
            "publishable": False,
            "errors": 1,
            "warnings": 2,
            "acknowledged": 1,
        },
        diagnostics=(
            diagnostic(
                "error",
                "project_name_missing",
                "is required",
                path="project.name",
                line=3,
            ),
            diagnostic(
                "warning",
                "test_command_missing",
                "no test command declared",
                path="build_and_test.test",
                acknowledged=True,
                acknowledgement_reason="Manual smoke tests cover this package today.",
            ),
            diagnostic("info", "limit_result_limit", "search results capped at configured ceiling"),
        ),
    )
    jsonschema.validate(to_payload(built), cli_schema)


# ---------------------------------------------------------------------------
# Command enum enforcement
# ---------------------------------------------------------------------------


def test_commands_exact_set() -> None:
    # v0.3 adds the `build` command to the envelope contract (schema widened
    # in place; additive for consumers — old envelopes stay valid).
    assert COMMANDS == {"init", "validate", "inspect", "export", "build"}


@pytest.mark.parametrize("name", ["init", "validate", "inspect", "export", "build"])
def test_valid_command_accepted(name: str) -> None:
    envelope = result(name, ok=True)
    assert envelope.command.value == name


@pytest.mark.parametrize("bad", ["serve", "publish", "", "Validate", "init "])
def test_unknown_command_rejected(bad: str) -> None:
    with pytest.raises(CliResultError) as excinfo:
        result(bad, ok=True)
    assert excinfo.value.code == ERR_INVALID_COMMAND


def test_command_direct_construction_enforced() -> None:
    with pytest.raises(CliResultError) as excinfo:
        CliResult(command="serve", ok=True)  # type: ignore[arg-type]
    assert excinfo.value.code == ERR_INVALID_COMMAND


def test_ok_must_be_bool() -> None:
    with pytest.raises(CliResultError) as excinfo:
        CliResult(command=Command.VALIDATE, ok=1)  # type: ignore[arg-type]
    assert excinfo.value.code == ERR_INVALID_OK
    with pytest.raises(CliResultError) as excinfo:
        CliResult(command=Command.VALIDATE, ok="yes")  # type: ignore[arg-type]
    assert excinfo.value.code == ERR_INVALID_OK


def test_schema_and_version_constants_enforced() -> None:
    with pytest.raises(CliResultError) as excinfo:
        CliResult(command=Command.VALIDATE, ok=True, schema="other.schema")  # type: ignore[arg-type]
    assert excinfo.value.code == ERR_INVALID_VERSION
    with pytest.raises(CliResultError) as excinfo:
        CliResult(command=Command.VALIDATE, ok=True, schema_version="2.0")  # type: ignore[arg-type]
    assert excinfo.value.code == ERR_INVALID_VERSION


def test_every_diagnostic_must_be_a_diagnostic() -> None:
    with pytest.raises(CliResultError) as excinfo:
        CliResult(command=Command.VALIDATE, ok=True, diagnostics=("not-a-diagnostic",))  # type: ignore[arg-type]
    assert excinfo.value.code == ERR_INVALID_DIAGNOSTIC


# ---------------------------------------------------------------------------
# Immutable / value-oriented types
# ---------------------------------------------------------------------------


def test_diagnostic_is_frozen() -> None:
    d = diagnostic("error", "some_code", "boom")
    with pytest.raises(FrozenInstanceError):
        d.code = "other"  # type: ignore[misc]


def test_result_is_frozen() -> None:
    env = result(COMMAND_VALIDATE, ok=True)
    with pytest.raises(FrozenInstanceError):
        env.ok = False  # type: ignore[misc]


def test_severity_and_command_are_plain_enums() -> None:
    assert Severity.ERROR.value == "error"
    assert Command.INIT.value == COMMAND_INIT
    assert Command.EXPORT.value == COMMAND_EXPORT


def test_invalid_severity_rejected() -> None:
    with pytest.raises(CliResultError) as excinfo:
        diagnostic("critical", "some_code", "boom")
    assert excinfo.value.code == ERR_INVALID_SEVERITY


@pytest.mark.parametrize(
    "code",
    ["BROKEN_CODE", "1abc", "", "a", "valid_but_way_too_long_" + ("x" * 80), "has space"],
)
def test_invalid_code_rejected(code: str) -> None:
    with pytest.raises(CliResultError) as excinfo:
        diagnostic("error", code, "boom")
    assert excinfo.value.code == "cli_result_invalid_code"


def test_code_length_constants_match_regex() -> None:
    assert MIN_CODE == 2
    assert MAX_CODE == 64
    two_char = diagnostic("error", "ab", "boom")
    assert two_char.code == "ab"
    sixty_four = diagnostic("error", "a" + "x" * 63, "boom")
    assert len(sixty_four.code) == 64
    with pytest.raises(CliResultError):
        diagnostic("error", "a" + "x" * 64, "boom")


def test_message_length_enforced() -> None:
    with pytest.raises(CliResultError) as excinfo:
        diagnostic("error", "some_code", "x" * (MAX_MESSAGE + 1))
    assert excinfo.value.code == "cli_result_invalid_message"


def test_empty_message_rejected() -> None:
    with pytest.raises(CliResultError) as excinfo:
        diagnostic("error", "some_code", "   ")
    assert excinfo.value.code == "cli_result_invalid_message"


def test_invalid_line_rejected() -> None:
    with pytest.raises(CliResultError) as excinfo:
        diagnostic("error", "some_code", "boom", line=0)
    assert excinfo.value.code == "cli_result_invalid_line"


def test_boolean_line_rejected() -> None:
    # bool is an int subclass; it must not be accepted as a line number.
    with pytest.raises(CliResultError) as excinfo:
        diagnostic("error", "some_code", "boom", line=True)  # type: ignore[arg-type]
    assert excinfo.value.code == "cli_result_invalid_line"


# ---------------------------------------------------------------------------
# Acknowledgement reason support
# ---------------------------------------------------------------------------


def test_acknowledge_preserves_fields() -> None:
    d = diagnostic("warning", "test_command_missing", "no test command", path="build_and_test.test")
    acked = acknowledge(d, "Manual smoke tests cover this package today.")
    assert acked is not d
    assert acked.acknowledged is True
    assert acked.acknowledgement_reason == "Manual smoke tests cover this package today."
    assert acked.severity == d.severity
    assert acked.code == d.code
    assert acked.path == d.path
    assert acked.message == d.message
    assert d.acknowledged is False
    assert d.acknowledgement_reason is None


def test_acknowledged_requires_reason() -> None:
    with pytest.raises(CliResultError) as excinfo:
        diagnostic("warning", "test_command_missing", "no test command", acknowledged=True)
    assert excinfo.value.code == ERR_ACK_REASON_MISSING


def test_acknowledgement_reason_min_length() -> None:
    with pytest.raises(CliResultError) as excinfo:
        diagnostic(
            "warning",
            "test_command_missing",
            "no test command",
            acknowledged=True,
            acknowledgement_reason="too short",
        )
    assert excinfo.value.code == ERR_ACK_REASON_INVALID


def test_acknowledgement_reason_is_trimmed() -> None:
    reason = "  " + "m" * MIN_ACKNOWLEDGEMENT_REASON + "  "
    acked = diagnostic(
        "warning",
        "test_command_missing",
        "no test command",
        acknowledged=True,
        acknowledgement_reason=reason,
    )
    assert acked.acknowledgement_reason == "m" * MIN_ACKNOWLEDGEMENT_REASON


def test_reason_without_acknowledgement_rejected() -> None:
    with pytest.raises(CliResultError) as excinfo:
        diagnostic(
            "warning",
            "test_command_missing",
            "no test command",
            acknowledgement_reason="m" * 20,
        )
    assert excinfo.value.code == ERR_ACK_REASON_INVALID


# ---------------------------------------------------------------------------
# Conversion of validation issues (no mutation of severity/code/path/message)
# ---------------------------------------------------------------------------


def test_from_validation_issue_preserves_fields() -> None:
    issue = ValidationIssue(
        "warning", "build_and_test.test", "no test command", "test_command_missing"
    )
    d = from_validation_issue(issue)
    assert d.severity == Severity.WARNING
    assert d.code == "test_command_missing"
    assert d.path == "build_and_test.test"
    assert d.message == "no test command"
    assert d.acknowledged is False
    # the source issue is untouched
    assert issue.severity == "warning"
    assert issue.where == "build_and_test.test"
    assert issue.message == "no test command"


def test_from_validation_issue_error_severity() -> None:
    issue = ValidationIssue("error", "project.name", "is required", "project_name_missing")
    d = from_validation_issue(issue)
    assert d.severity == Severity.ERROR


def test_from_validation_issue_acknowledged() -> None:
    issue = ValidationIssue(
        "warning", "guardrails", "no guardrail is declared", "guardrails_missing"
    )
    d = from_validation_issue(
        issue, acknowledged=True, acknowledgement_reason="Guardrails live in the agent handbook."
    )
    assert d.acknowledged is True
    assert d.acknowledgement_reason == "Guardrails live in the agent handbook."
    assert d.severity == Severity.WARNING
    assert d.code == "guardrails_missing"


# ---------------------------------------------------------------------------
# Safe internal-error diagnostics
# ---------------------------------------------------------------------------


def test_internal_error_is_error_severity() -> None:
    d = internal_error()
    assert d.severity == Severity.ERROR
    assert d.code == INTERNAL_ERROR_CODE
    assert d.message == INTERNAL_ERROR_MESSAGE


def test_internal_error_does_not_expose_exception_details() -> None:
    secret = "token=SUPER_SECRET_VALUE"
    exc = RuntimeError(f"failed to read {secret}")
    d = internal_error(exc)
    payload = to_payload(result(COMMAND_INIT, False, diagnostics=(d,)))
    assert payload["diagnostics"][0]["code"] == INTERNAL_ERROR_CODE
    assert payload["diagnostics"][0]["message"] == INTERNAL_ERROR_MESSAGE
    serialized = dumps(result(COMMAND_INIT, False, diagnostics=(d,)))
    assert "SUPER_SECRET_VALUE" not in serialized
    assert "RuntimeError" not in serialized


# ---------------------------------------------------------------------------
# Deterministic serialization: one document, final newline, UTF-8, stable
# ---------------------------------------------------------------------------


def test_dumps_is_exactly_one_document_plus_newline() -> None:
    env = result(COMMAND_VALIDATE, ok=True, result_payload={"n": 1})
    text = dumps(env)
    assert text.endswith("\n")
    assert text.count("\n") == 1
    assert not text.startswith("\n")
    # re-parsing yields exactly one JSON value
    loaded = json.loads(text)
    assert loaded["ok"] is True


def test_dumps_unicode_utf8_safe() -> None:
    env = result(
        COMMAND_INSPECT,
        ok=True,
        result_payload={"note": "日本語 café — ✓"},
        diagnostics=(diagnostic("info", "some_code", "héllo — ünïcode"),),
    )
    text = dumps(env)
    assert "日本語" in text
    assert "café" in text
    assert "\\u" not in text  # no ASCII escaping
    json.loads(text)
    dumps_bytes(env).decode("utf-8")


def test_dumps_is_deterministic() -> None:
    env = result(
        COMMAND_EXPORT,
        ok=True,
        result_payload={"z": 1, "a": 2, "m": {"y": 1, "b": 2}},
        diagnostics=(
            diagnostic("error", "some_code", "m", path="p", line=2),
            diagnostic("info", "other_code", "n"),
        ),
    )
    assert dumps(env) == dumps(env)
    first = dumps(env)
    second = dumps(env, sort_keys=True)
    assert first == second


def test_dumps_rejects_non_finite_numbers() -> None:
    env = result(COMMAND_EXPORT, ok=True, result_payload={"bad": float("nan")})
    with pytest.raises(ValueError):
        dumps(env)


def test_to_payload_field_order_matches_schema() -> None:
    payload = to_payload(result(COMMAND_INIT, ok=True, result_payload={}))
    assert list(payload) == ["schema", "schema_version", "command", "ok", "result", "diagnostics"]


def test_dumps_envelope_round_trips() -> None:
    env = result(
        COMMAND_VALIDATE,
        ok=False,
        result_payload={"errors": 1},
        diagnostics=(diagnostic("error", "some_code", "boom", path="x", line=1),),
    )
    loaded = json.loads(dumps(env))
    assert loaded["schema"] == SCHEMA_NAME
    assert loaded["schema_version"] == SCHEMA_VERSION
    assert loaded["command"] == COMMAND_VALIDATE
    assert loaded["ok"] is False
    assert loaded["result"] == {"errors": 1}
    assert loaded["diagnostics"][0]["severity"] == "error"
