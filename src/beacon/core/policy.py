"""Publication/serving policy and explicit acknowledgement for validation.

The addendum (``.agent/plans/beacon-v0.2-implementation-readiness-addendum``, §5)
distinguishes *servable* from *publishable*:

* ``error`` issues always block serving and publication.
* ``warning`` issues are reported when serving; only those whose code is in
  :data:`beacon.core.validator.PUBLICATION_WARNING_CODES` block *publication*
  (strict validation / export) unless explicitly acknowledged.

An acknowledgement is an explicit, reasoned, in-memory override for one
allowlisted warning. It changes the *policy disposition* for that warning but
never mutates the underlying diagnostic severity, code, ``where``, or
``message``, and never modifies ``beacon.yaml``. Only ``test_command_missing``
and ``guardrails_missing`` are acknowledgeable in v0.2.

Syntax is ``CODE=REASON`` with a reason that is trimmed, non-empty, and at
least 10 characters. Unknown, duplicate, malformed, or unallowlisted codes are
input/user errors (``AcknowledgementError`` with a stable code).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from beacon.core.validator import (
    PUBLICATION_WARNING_CODES,
    VALIDATION_CODES,
    ValidationIssue,
    ValidationReport,
)

#: Only these warnings may be acknowledged in v0.2.
ACKNOWLEDGEABLE_CODES = frozenset({"test_command_missing", "guardrails_missing"})

#: Minimum length of an acknowledgement reason (after trimming).
MIN_ACKNOWLEDGEMENT_REASON_LENGTH = 10
MAX_ACKNOWLEDGEMENT_REASON_LENGTH = 1024

#: Stable acknowledgement error codes (input/user errors).
ACK_MALFORMED = "ack_malformed"
ACK_UNKNOWN_CODE = "ack_unknown_code"
ACK_UNALLOWLISTED_CODE = "ack_unallowlisted_code"
ACK_DUPLICATE = "ack_duplicate"
ACK_REASON_EMPTY = "ack_reason_empty"
ACK_REASON_SHORT = "ack_reason_short"
ACK_REASON_LONG = "ack_reason_long"


@dataclass(frozen=True)
class Acknowledgement:
    """An explicit, reasoned override for one allowlisted warning."""

    code: str
    reason: str


class AcknowledgementError(Exception):
    """Raised when an acknowledgement is malformed, unknown, duplicate,
    unallowlisted, or has an invalid reason.

    ``code`` is a stable, non-secret diagnostic string.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def parse_acknowledgement(raw: str) -> Acknowledgement:
    """Parse a single ``CODE=REASON`` string into an :class:`Acknowledgement`.

    Raises :class:`AcknowledgementError` on malformed syntax, an unknown code,
    an unallowlisted (known but not acknowledgeable) code, an empty reason, or
    a reason shorter than :data:`MIN_ACKNOWLEDGEMENT_REASON_LENGTH`.
    """
    value = raw.strip()
    if not value or "=" not in value:
        raise AcknowledgementError(ACK_MALFORMED, "acknowledgement must be in CODE=REASON form")
    code, _, reason = value.partition("=")
    code = code.strip()
    reason = reason.strip()
    if not code:
        raise AcknowledgementError(ACK_MALFORMED, "acknowledgement code must not be empty")
    if code not in VALIDATION_CODES:
        raise AcknowledgementError(ACK_UNKNOWN_CODE, f"unknown acknowledgement code: {code}")
    if code not in ACKNOWLEDGEABLE_CODES:
        raise AcknowledgementError(
            ACK_UNALLOWLISTED_CODE,
            f"code is not acknowledgeable in v0.2: {code}",
        )
    if not reason:
        raise AcknowledgementError(
            ACK_REASON_EMPTY, f"acknowledgement reason for {code} must not be empty"
        )
    if len(reason) < MIN_ACKNOWLEDGEMENT_REASON_LENGTH:
        raise AcknowledgementError(
            ACK_REASON_SHORT,
            f"acknowledgement reason for {code} must be at least "
            f"{MIN_ACKNOWLEDGEMENT_REASON_LENGTH} characters",
        )
    if len(reason) > MAX_ACKNOWLEDGEMENT_REASON_LENGTH:
        raise AcknowledgementError(
            ACK_REASON_LONG,
            f"acknowledgement reason for {code} must not exceed "
            f"{MAX_ACKNOWLEDGEMENT_REASON_LENGTH} characters",
        )
    return Acknowledgement(code=code, reason=reason)


def parse_acknowledgements(raws: Iterable[str]) -> tuple[Acknowledgement, ...]:
    """Parse a collection of ``CODE=REASON`` strings.

    Each item is validated by :func:`parse_acknowledgement`; an acknowledgement
    whose code was already accepted in the same collection is rejected as
    :data:`ACK_DUPLICATE`. Order of the returned tuple matches input order.
    """
    seen: set[str] = set()
    parsed: list[Acknowledgement] = []
    for raw in raws:
        ack = parse_acknowledgement(raw)
        if ack.code in seen:
            raise AcknowledgementError(ACK_DUPLICATE, f"duplicate acknowledgement code: {ack.code}")
        seen.add(ack.code)
        parsed.append(ack)
    return tuple(parsed)


@dataclass(frozen=True)
class PolicyEvaluation:
    """The result of applying a policy to a :class:`ValidationReport`.

    ``servable`` is true when there are no error issues. ``publishable`` is
    true when there are no error issues *and* no unresolved publication
    warnings. ``acknowledged`` records each publication warning that an
    acknowledgement resolved, alongside the original issue and its reason.
    """

    servable: bool
    publishable: bool
    errors: tuple[ValidationIssue, ...] = ()
    unresolved_publication_warnings: tuple[ValidationIssue, ...] = ()
    acknowledged: tuple[tuple[ValidationIssue, Acknowledgement], ...] = ()

    def can_serve(self) -> bool:
        """True when the manifest may be served (no errors)."""
        return self.servable

    def can_publish(self) -> bool:
        """True when the manifest may be published (no errors, no unresolved
        publication warnings)."""
        return self.publishable


def evaluate_policy(
    report: ValidationReport,
    *,
    acknowledgements: Iterable[Acknowledgement] = (),
) -> PolicyEvaluation:
    """Evaluate *report* under the v0.2 serving/publication policy.

    ``acknowledgements`` are validated even when callers construct the frozen
    dataclass directly instead of using :func:`parse_acknowledgements`. Each
    one may resolve the matching publication warning, preserving the issue's
    original severity/code/where/message. Results preserve the report's
    deterministic warning ordering.
    """
    validated_acks = parse_acknowledgements(f"{ack.code}={ack.reason}" for ack in acknowledgements)
    ack_by_code = {ack.code: ack for ack in validated_acks}
    errors = report.errors
    servable = not errors
    acknowledged: list[tuple[ValidationIssue, Acknowledgement]] = []
    unresolved: list[ValidationIssue] = []
    for warning in report.warnings:
        if warning.code not in PUBLICATION_WARNING_CODES:
            continue
        ack = ack_by_code.get(warning.code)
        if ack is not None:
            acknowledged.append((warning, ack))
        else:
            unresolved.append(warning)
    publishable = servable and not unresolved
    return PolicyEvaluation(
        servable=servable,
        publishable=publishable,
        errors=errors,
        unresolved_publication_warnings=tuple(unresolved),
        acknowledged=tuple(acknowledged),
    )


__all__ = [
    "ACK_DUPLICATE",
    "ACK_MALFORMED",
    "ACK_REASON_EMPTY",
    "ACK_REASON_SHORT",
    "ACK_REASON_LONG",
    "ACK_UNALLOWLISTED_CODE",
    "ACK_UNKNOWN_CODE",
    "ACKNOWLEDGEABLE_CODES",
    "Acknowledgement",
    "AcknowledgementError",
    "MIN_ACKNOWLEDGEMENT_REASON_LENGTH",
    "MAX_ACKNOWLEDGEMENT_REASON_LENGTH",
    "PolicyEvaluation",
    "evaluate_policy",
    "parse_acknowledgement",
    "parse_acknowledgements",
]
