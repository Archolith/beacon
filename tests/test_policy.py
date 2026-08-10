"""Focused tests for stable validation codes, serving/publication policy, and
explicit acknowledgement."""

from __future__ import annotations

from beacon.core.loader import parse_manifest
from beacon.core.policy import (
    ACK_DUPLICATE,
    ACK_MALFORMED,
    ACK_REASON_EMPTY,
    ACK_REASON_LONG,
    ACK_REASON_SHORT,
    ACK_UNALLOWLISTED_CODE,
    ACK_UNKNOWN_CODE,
    ACKNOWLEDGEABLE_CODES,
    MAX_ACKNOWLEDGEMENT_REASON_LENGTH,
    Acknowledgement,
    AcknowledgementError,
    evaluate_policy,
    parse_acknowledgement,
    parse_acknowledgements,
)
from beacon.core.validator import (
    CODE_GUARDRAILS_MISSING,
    CODE_TEST_COMMAND_MISSING,
    PUBLICATION_WARNING_CODES,
    ValidationIssue,
    ValidationReport,
    validate_beacon_manifest,
)

LONG_REASON = "Because we cannot run automated tests here yet."


# ---------------------------------------------------------------------------
# Manifest fixtures
# ---------------------------------------------------------------------------


def _report(**overrides: object) -> ValidationReport:
    raw: dict[str, object] = {
        "beacon_version": "0.1",
        "project": {"name": "x", "description": "desc", "status": "experimental"},
        "purpose": {"one_sentence": "a purpose for the fixture"},
        "canonical_docs": [{"path": "README.md", "status": "current"}],
        "core_concepts": [{"id": "c", "name": "C", "status": "current", "description": "def"}],
    }
    raw.update(overrides)
    return validate_beacon_manifest(parse_manifest(raw))


def _absent_test_guardrail_report() -> ValidationReport:
    """Servable report with exactly two publication warnings: absent test + guardrails."""
    return _report()


def test_report_emits_absent_test_and_guardrail_codes() -> None:
    report = _absent_test_guardrail_report()
    codes = {w.code for w in report.warnings}
    assert CODE_TEST_COMMAND_MISSING in codes
    assert CODE_GUARDRAILS_MISSING in codes
    assert report.ok
    assert report.errors == ()


def test_every_issue_has_a_stable_code() -> None:
    for report in (
        _report(),
        _report(project={"name": "", "description": ""}),
        _report(guardrails=[{"id": "g", "rule": "r", "severity": "banana"}]),
    ):
        assert report.issues
        assert all(i.code for i in report.issues)


# ---------------------------------------------------------------------------
# Acknowledgement parsing — every rejection path
# ---------------------------------------------------------------------------


def _assert_ack_error(raw: str, code: str) -> None:
    try:
        parse_acknowledgement(raw)
    except AcknowledgementError as exc:
        assert exc.code == code
    else:  # pragma: no cover - failure reporting
        raise AssertionError(f"expected {code} for {raw!r}")


def test_malformed_empty() -> None:
    _assert_ack_error("", ACK_MALFORMED)


def test_malformed_missing_equals() -> None:
    _assert_ack_error("test_command_missing", ACK_MALFORMED)


def test_malformed_empty_code() -> None:
    _assert_ack_error(f"= {LONG_REASON}", ACK_MALFORMED)


def test_unknown_code() -> None:
    _assert_ack_error(f"bogus_code={LONG_REASON}", ACK_UNKNOWN_CODE)


def test_unallowlisted_known_code() -> None:
    # purpose_missing is a real publication-warning code but not acknowledgeable.
    _assert_ack_error(f"purpose_missing={LONG_REASON}", ACK_UNALLOWLISTED_CODE)


def test_empty_reason() -> None:
    _assert_ack_error("test_command_missing=", ACK_REASON_EMPTY)
    _assert_ack_error("test_command_missing=   ", ACK_REASON_EMPTY)


def test_reason_too_short() -> None:
    _assert_ack_error("test_command_missing=too short", ACK_REASON_SHORT)


def test_reason_too_long() -> None:
    _assert_ack_error(
        f"test_command_missing={'x' * (MAX_ACKNOWLEDGEMENT_REASON_LENGTH + 1)}",
        ACK_REASON_LONG,
    )


def test_duplicate_detected_via_collection() -> None:
    try:
        parse_acknowledgements(
            [
                "test_command_missing=first reason text",
                "guardrails_missing=second reason text",
                "test_command_missing=third reason text",
            ]
        )
    except AcknowledgementError as exc:
        assert exc.code == ACK_DUPLICATE
    else:  # pragma: no cover - failure reporting
        raise AssertionError("expected ACK_DUPLICATE")


def test_policy_revalidates_direct_acknowledgements() -> None:
    report = _absent_test_guardrail_report()
    try:
        evaluate_policy(
            report,
            acknowledgements=[Acknowledgement("purpose_missing", LONG_REASON)],
        )
    except AcknowledgementError as exc:
        assert exc.code == ACK_UNALLOWLISTED_CODE
    else:  # pragma: no cover - failure reporting
        raise AssertionError("expected ACK_UNALLOWLISTED_CODE")


def test_policy_rejects_direct_duplicate_acknowledgements() -> None:
    report = _absent_test_guardrail_report()
    ack = Acknowledgement("test_command_missing", LONG_REASON)
    try:
        evaluate_policy(report, acknowledgements=[ack, ack])
    except AcknowledgementError as exc:
        assert exc.code == ACK_DUPLICATE
    else:  # pragma: no cover - failure reporting
        raise AssertionError("expected ACK_DUPLICATE")


def test_parses_and_trims_valid() -> None:
    ack = parse_acknowledgement(f"  test_command_missing =   {LONG_REASON}  ")
    assert ack == Acknowledgement(code="test_command_missing", reason=LONG_REASON)


def test_reason_exactly_minimum_length_ok() -> None:
    ack = parse_acknowledgement("test_command_missing=1234567890")
    assert ack.reason == "1234567890"


def test_acknowledgeable_codes_are_exact_subset() -> None:
    assert ACKNOWLEDGEABLE_CODES == {"test_command_missing", "guardrails_missing"}
    assert ACKNOWLEDGEABLE_CODES <= PUBLICATION_WARNING_CODES


def test_only_acknowledgeable_codes_parse() -> None:
    for code in PUBLICATION_WARNING_CODES:
        if code in ACKNOWLEDGEABLE_CODES:
            parse_acknowledgement(f"{code}={LONG_REASON}")
        else:
            try:
                parse_acknowledgement(f"{code}={LONG_REASON}")
            except AcknowledgementError as exc:
                assert exc.code == ACK_UNALLOWLISTED_CODE
            else:  # pragma: no cover - failure reporting
                raise AssertionError(f"{code} should not be acknowledgeable")


# ---------------------------------------------------------------------------
# Policy dispositions: normal / strict / serve / export
# ---------------------------------------------------------------------------


def test_clean_report_servable_and_publishable() -> None:
    report = _report(
        guardrails=[{"id": "g", "rule": "r", "severity": "high"}],
        build_and_test={"test": "python -m pytest"},
    )
    ev = evaluate_policy(report)
    assert ev.can_serve()
    assert ev.can_publish()
    assert ev.unresolved_publication_warnings == ()
    assert ev.acknowledged == ()


def test_warnings_do_not_block_serving() -> None:
    report = _absent_test_guardrail_report()
    ev = evaluate_policy(report)
    assert ev.can_serve()  # warnings are visible but serve continues
    assert ev.unresolved_publication_warnings  # still reported


def test_unresolved_publication_warnings_block_publication() -> None:
    report = _absent_test_guardrail_report()
    ev = evaluate_policy(report)
    assert ev.servable is True
    assert ev.publishable is False


def test_errors_block_both_serving_and_publication() -> None:
    report = _report(project={"name": "", "description": ""})
    ev = evaluate_policy(report)
    assert ev.can_serve() is False
    assert ev.can_publish() is False
    assert ev.errors


def test_acknowledgement_unblocks_publication() -> None:
    report = _absent_test_guardrail_report()
    acks = parse_acknowledgements(
        [
            f"test_command_missing={LONG_REASON}",
            f"guardrails_missing={LONG_REASON}",
        ]
    )
    ev = evaluate_policy(report, acknowledgements=acks)
    assert ev.can_serve()
    assert ev.can_publish()
    assert ev.unresolved_publication_warnings == ()


def test_non_publication_warning_does_not_block_publication() -> None:
    # guardrail_severity_invalid is a warning but not in PUBLICATION_WARNING_CODES.
    report = _report(
        guardrails=[{"id": "g", "rule": "r", "severity": "banana"}],
        build_and_test={"test": "python -m pytest"},
    )
    acks = parse_acknowledgements([f"test_command_missing={LONG_REASON}"])
    ev = evaluate_policy(report, acknowledgements=acks)
    assert ev.can_publish() is True


# ---------------------------------------------------------------------------
# Preserved facts / severity and recorded reason
# ---------------------------------------------------------------------------


def test_acknowledgement_preserves_original_issue_facts() -> None:
    report = _absent_test_guardrail_report()
    original = next(w for w in report.warnings if w.code == CODE_TEST_COMMAND_MISSING)
    acks = parse_acknowledgements([f"test_command_missing={LONG_REASON}"])
    ev = evaluate_policy(report, acknowledgements=acks)
    (issue, ack) = ev.acknowledged[0]
    assert issue is original
    assert issue.severity == "warning"
    assert issue.code == CODE_TEST_COMMAND_MISSING
    assert issue.where == "build_and_test.test"
    assert issue.message
    assert ack.reason == LONG_REASON
    # The underlying report is unchanged.
    assert CODE_TEST_COMMAND_MISSING in {w.code for w in report.warnings}


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


def test_acknowledged_and_unresolved_preserve_report_order() -> None:
    report = _absent_test_guardrail_report()  # guardrails_missing then test_command_missing
    expected_pub_codes = [w.code for w in report.warnings if w.code in PUBLICATION_WARNING_CODES]
    assert expected_pub_codes == [CODE_GUARDRAILS_MISSING, CODE_TEST_COMMAND_MISSING]
    acks = parse_acknowledgements(
        [
            f"test_command_missing={LONG_REASON}",
            f"guardrails_missing={LONG_REASON}",
        ]
    )
    ev = evaluate_policy(report, acknowledgements=acks)
    assert [issue.code for issue, _ in ev.acknowledged] == expected_pub_codes


def test_acknowledging_only_one_leaves_other_unresolved() -> None:
    report = _absent_test_guardrail_report()
    acks = parse_acknowledgements([f"test_command_missing={LONG_REASON}"])
    ev = evaluate_policy(report, acknowledgements=acks)
    assert [issue.code for issue, _ in ev.acknowledged] == [CODE_TEST_COMMAND_MISSING]
    assert [w.code for w in ev.unresolved_publication_warnings] == [CODE_GUARDRAILS_MISSING]
    assert ev.publishable is False


# ---------------------------------------------------------------------------
# Legacy consumer compatibility
# ---------------------------------------------------------------------------


def test_validation_issue_legacy_attributes_and_str() -> None:
    report = _absent_test_guardrail_report()
    for issue in report.issues:
        # Legacy fields/behaviour are unchanged by the new code field.
        assert isinstance(issue.severity, str)
        assert isinstance(issue.where, str)
        assert isinstance(issue.message, str)
        assert str(issue) == f"[{issue.severity}] {issue.where}: {issue.message}"
    assert report.ok  # legacy .ok still true with warnings only
    assert all(i.severity == "warning" for i in report.warnings)


def test_validation_issue_legacy_positional_constructor() -> None:
    issue = ValidationIssue("warning", "legacy.location", "legacy message")
    assert issue.severity == "warning"
    assert issue.where == "legacy.location"
    assert issue.message == "legacy message"
    assert issue.code == "legacy_issue"


def test_report_errors_warnings_properties_compatible() -> None:
    ok_report = _absent_test_guardrail_report()
    assert ok_report.errors == ()
    assert ok_report.warnings

    bad_report = _report(project={"name": "", "description": ""})
    assert bad_report.errors
    assert bad_report.ok is False


def test_acknowledgement_does_not_mutate_report_or_manifest() -> None:
    manifest = parse_manifest(
        {
            "beacon_version": "0.1",
            "project": {"name": "x", "description": "d"},
            "canonical_docs": [{"path": "README.md"}],
        }
    )
    before_issues = validate_beacon_manifest(manifest).issues
    acks = parse_acknowledgements([f"test_command_missing={LONG_REASON}"])
    evaluate_policy(validate_beacon_manifest(manifest), acknowledgements=acks)
    after_issues = validate_beacon_manifest(manifest).issues
    assert before_issues == after_issues  # frozen; nothing mutated
