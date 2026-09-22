"""Immutable CLI result envelope for the ``beacon.cli-result`` v1.0 schema.

This module is the single implementation of the machine-mode CLI contract
(``docs/schemas/beacon-cli-result-1.0.schema.json``). Every JSON CLI outcome is
one envelope: ``schema`` / ``schema_version``, a ``command`` drawn from the
fixed v0.2 set, an ``ok`` flag, an optional command-specific ``result`` object,
and an ordered list of diagnostics.

Values are immutable and value-oriented. Diagnostic *validation issues* are
converted from :class:`beacon.core.validator.ValidationIssue` without ever
mutating their ``severity``, ``code``, ``where`` (mapped to ``path``), or
``message``; acknowledgement only attaches an ``acknowledged`` flag and a
reason. Internal-error diagnostics never surface exception details.

Serialization is deterministic and compact: mappings are key-sorted, non-ASCII
characters pass through as UTF-8, ``NaN``/``Infinity`` are rejected, and the
output is exactly one JSON document plus a single trailing newline.

Nothing here touches ``main.py``, MCP, or the filesystem; it is pure data so
the CLI wrapper, init report, and snapshot writers can share it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from beacon.core.validator import ValidationIssue

#: Machine name and version from the canonical schema ``$id``.
SCHEMA_NAME = "beacon.cli-result"
SCHEMA_VERSION = "1.0"

#: The four commands v0.2 CLI results may carry.
COMMAND_INIT = "init"
COMMAND_VALIDATE = "validate"
COMMAND_INSPECT = "inspect"
COMMAND_EXPORT = "export"
COMMAND_BUILD = "build"
COMMANDS = frozenset(
    {COMMAND_INIT, COMMAND_VALIDATE, COMMAND_INSPECT, COMMAND_EXPORT, COMMAND_BUILD}
)

#: Diagnostic severities allowed by the schema.
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
SEVERITIES = frozenset({SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR})

#: Stable code used for unexpected internal failures (exit-3 class).
INTERNAL_ERROR_CODE = "internal_error"

#: Fixed, safe message for internal-error diagnostics (never exception-derived).
INTERNAL_ERROR_MESSAGE = "unexpected internal failure"

#: Minimum reason length for an acknowledgement (matches the addendum §5 and
#: :data:`beacon.core.policy.MIN_ACKNOWLEDGEMENT_REASON_LENGTH`).
MIN_ACKNOWLEDGEMENT_REASON = 10

#: Field ceilings mirrored from the schema.
MAX_MESSAGE = 4096
MAX_PATH = 1024
MAX_ACK_REASON = 1024
#: ``code`` is ``^[a-z][a-z0-9_]{1,63}$``: one leading lowercase letter plus
#: 1..63 of ``[a-z0-9_]``, for a total length of 2..64.
MAX_CODE = 64
MIN_CODE = 2

#: ``code`` must match ``^[a-z][a-z0-9_]{1,63}$``.
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class Command(StrEnum):
    """The fixed set of commands an envelope may describe."""

    INIT = COMMAND_INIT
    VALIDATE = COMMAND_VALIDATE
    INSPECT = COMMAND_INSPECT
    EXPORT = COMMAND_EXPORT
    BUILD = COMMAND_BUILD


class Severity(StrEnum):
    """Diagnostic severity levels allowed by the schema."""

    INFO = SEVERITY_INFO
    WARNING = SEVERITY_WARNING
    ERROR = SEVERITY_ERROR


class CliResultError(ValueError):
    """Raised when constructing an invalid diagnostic or envelope.

    ``code`` is a stable, non-secret diagnostic string.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


#: Stable codes for the envelope's own construction errors.
ERR_INVALID_COMMAND = "cli_result_invalid_command"
ERR_INVALID_VERSION = "cli_result_invalid_version"
ERR_INVALID_OK = "cli_result_invalid_ok"
ERR_INVALID_RESULT = "cli_result_invalid_result"
ERR_INVALID_DIAGNOSTIC = "cli_result_invalid_diagnostic"
ERR_INVALID_SEVERITY = "cli_result_invalid_severity"
ERR_INVALID_CODE = "cli_result_invalid_code"
ERR_INVALID_MESSAGE = "cli_result_invalid_message"
ERR_INVALID_PATH = "cli_result_invalid_path"
ERR_INVALID_LINE = "cli_result_invalid_line"
ERR_ACK_REASON_MISSING = "cli_result_ack_reason_missing"
ERR_ACK_REASON_INVALID = "cli_result_ack_reason_invalid"


@dataclass(frozen=True)
class Diagnostic:
    """An immutable diagnostic within a CLI result.

    ``acknowledged`` and ``acknowledgement_reason`` are purely presentational:
    they label a finding resolved by policy but never change the underlying
    ``severity``, ``code``, ``path``, or ``message``.
    """

    severity: Severity
    code: str
    message: str
    path: str | None = None
    line: int | None = None
    acknowledged: bool = False
    acknowledgement_reason: str | None = None

    def __post_init__(self) -> None:
        """Validate every field so direct construction is also checked."""
        if not isinstance(self.severity, Severity):
            raise CliResultError(
                ERR_INVALID_SEVERITY,
                f"invalid diagnostic severity: {self.severity!r}",
            )
        if not isinstance(self.code, str) or not _CODE_RE.match(self.code):
            raise CliResultError(
                ERR_INVALID_CODE,
                "diagnostic code must match ^[a-z][a-z0-9_]{1,63}$",
            )
        if not isinstance(self.message, str) or not self.message.strip():
            raise CliResultError(ERR_INVALID_MESSAGE, "diagnostic message must not be empty")
        if len(self.message) > MAX_MESSAGE:
            raise CliResultError(ERR_INVALID_MESSAGE, "diagnostic message exceeds 4096 characters")
        if self.path is not None:
            if not isinstance(self.path, str):
                raise CliResultError(ERR_INVALID_PATH, "diagnostic path must be a string")
            if len(self.path) > MAX_PATH:
                raise CliResultError(ERR_INVALID_PATH, "diagnostic path exceeds 1024 characters")
        if self.line is not None and (
            isinstance(self.line, bool) or not isinstance(self.line, int) or self.line < 1
        ):
            raise CliResultError(ERR_INVALID_LINE, "diagnostic line must be a positive integer")
        if self.acknowledged:
            reason = self.acknowledgement_reason
            if not isinstance(reason, str) or not reason.strip():
                raise CliResultError(
                    ERR_ACK_REASON_MISSING,
                    "an acknowledged diagnostic requires an acknowledgement_reason",
                )
            reason = reason.strip()
            if len(reason) < MIN_ACKNOWLEDGEMENT_REASON:
                raise CliResultError(
                    ERR_ACK_REASON_INVALID,
                    "acknowledgement_reason must be at least 10 characters",
                )
            if len(reason) > MAX_ACK_REASON:
                raise CliResultError(
                    ERR_ACK_REASON_INVALID,
                    "acknowledgement_reason exceeds 1024 characters",
                )
            object.__setattr__(self, "acknowledgement_reason", reason)
        elif self.acknowledgement_reason is not None:
            raise CliResultError(
                ERR_ACK_REASON_INVALID,
                "acknowledgement_reason is only allowed on acknowledged diagnostics",
            )


@dataclass(frozen=True)
class CliResult:
    """The immutable ``beacon.cli-result`` v1.0 envelope."""

    command: Command
    ok: bool
    result: dict[str, Any] | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    schema: str = SCHEMA_NAME
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.command, Command):
            raise CliResultError(
                ERR_INVALID_COMMAND,
                f"command must be one of {sorted(COMMANDS)}",
            )
        if self.schema != SCHEMA_NAME or self.schema_version != SCHEMA_VERSION:
            raise CliResultError(
                ERR_INVALID_VERSION,
                f"envelope must declare schema={SCHEMA_NAME!r} version={SCHEMA_VERSION!r}",
            )
        if not isinstance(self.ok, bool):
            raise CliResultError(ERR_INVALID_OK, "ok must be a boolean")
        if not isinstance(self.result, dict) and self.result is not None:
            raise CliResultError(
                ERR_INVALID_RESULT,
                "result must be an object or null",
            )
        if not isinstance(self.diagnostics, tuple):
            object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if not all(isinstance(d, Diagnostic) for d in self.diagnostics):
            raise CliResultError(
                ERR_INVALID_DIAGNOSTIC,
                "every diagnostics item must be a Diagnostic",
            )


def diagnostic(
    severity: str | Severity,
    code: str,
    message: str,
    *,
    path: str | None = None,
    line: int | None = None,
    acknowledged: bool = False,
    acknowledgement_reason: str | None = None,
) -> Diagnostic:
    """Build a validated :class:`Diagnostic` from a ``severity`` name or enum."""
    if not isinstance(severity, Severity):
        try:
            severity = Severity(severity)
        except ValueError:
            raise CliResultError(
                ERR_INVALID_SEVERITY, f"invalid diagnostic severity: {severity!r}"
            ) from None
    return Diagnostic(
        severity=severity,
        code=code,
        message=message,
        path=path,
        line=line,
        acknowledged=acknowledged,
        acknowledgement_reason=acknowledgement_reason,
    )


def acknowledge(diag: Diagnostic, reason: str) -> Diagnostic:
    """Return a copy of *diag* marked acknowledged with a validated *reason*.

    The original ``severity``, ``code``, ``path``, and ``message`` are preserved
    untouched; only the acknowledgement fields change.
    """
    return Diagnostic(
        severity=diag.severity,
        code=diag.code,
        message=diag.message,
        path=diag.path,
        line=diag.line,
        acknowledged=True,
        acknowledgement_reason=reason,
    )


#: Marker inserted where :func:`_elide_middle` removed characters.
_ELISION = "..."


def _elide_middle(text: str, limit: int) -> str:
    """Return *text* unchanged if it fits *limit*, else keep its head and tail.

    Keeping both ends preserves the location wrapper (``canonical_docs[``) and
    the suffix (``].status``, file extension) that make the location useful.
    """
    if len(text) <= limit:
        return text
    keep = limit - len(_ELISION)
    head = keep // 2
    tail = keep - head
    return f"{text[:head]}{_ELISION}{text[-tail:]}"


def from_validation_issue(
    issue: ValidationIssue,
    *,
    acknowledged: bool = False,
    acknowledgement_reason: str | None = None,
) -> Diagnostic:
    """Convert a :class:`ValidationIssue` into a :class:`Diagnostic`.

    The issue's ``severity`` and ``code`` are carried through verbatim; its
    ``where`` location becomes the diagnostic ``path``. Because ``where`` and
    ``message`` embed manifest values (for example a document path that is
    legal up to the ``path_bytes`` limit plus a ``canonical_docs[...]``
    wrapper), they are bounded to :data:`MAX_PATH` / :data:`MAX_MESSAGE` with a
    middle ellipsis instead of failing, so the real finding still surfaces.
    Nothing is mutated. ``acknowledged``/``acknowledgement_reason`` optionally
    label the finding without altering its facts.
    """
    return Diagnostic(
        severity=Severity(issue.severity),
        code=issue.code,
        message=_elide_middle(issue.message, MAX_MESSAGE),
        path=_elide_middle(issue.where, MAX_PATH),
        acknowledged=acknowledged,
        acknowledgement_reason=acknowledgement_reason,
    )


def internal_error(exc: BaseException | None = None) -> Diagnostic:
    """Build a safe ``error`` diagnostic for an unexpected internal failure.

    The returned diagnostic has a fixed code (:data:`INTERNAL_ERROR_CODE`) and a
    generic, non-secret message (:data:`INTERNAL_ERROR_MESSAGE`). *exc* is
    intentionally ignored: it is accepted only to make call sites explicit that
    an exception was caught, but neither its type nor its ``str()`` text is ever
    placed into the envelope, so paths, environment values, and secrets cannot
    leak.
    """
    return Diagnostic(
        severity=Severity.ERROR, code=INTERNAL_ERROR_CODE, message=INTERNAL_ERROR_MESSAGE
    )


def result(
    command: str | Command,
    ok: bool,
    *,
    result_payload: dict[str, Any] | None = None,
    diagnostics: tuple[Diagnostic, ...] = (),
) -> CliResult:
    """Build a :class:`CliResult`, coercing ``command`` and rejecting others."""
    if not isinstance(command, Command):
        try:
            command = Command(command)
        except ValueError:
            raise CliResultError(
                ERR_INVALID_COMMAND, f"command must be one of {sorted(COMMANDS)}"
            ) from None
    return CliResult(command=command, ok=ok, result=result_payload, diagnostics=diagnostics)


def to_payload(envelope: CliResult) -> dict[str, Any]:
    """Return a JSON-ready dict for the envelope (enums resolved to strings).

    Mapping ordering follows the schema's property order for readability and is
    re-sorted by :func:`dumps` for byte-for-byte deterministic output.
    """
    return {
        "schema": envelope.schema,
        "schema_version": envelope.schema_version,
        "command": envelope.command.value,
        "ok": envelope.ok,
        "result": envelope.result,
        "diagnostics": [_diagnostic_payload(d) for d in envelope.diagnostics],
    }


def _diagnostic_payload(d: Diagnostic) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "severity": d.severity.value,
        "code": d.code,
        "message": d.message,
    }
    if d.path is not None:
        payload["path"] = d.path
    if d.line is not None:
        payload["line"] = d.line
    payload["acknowledged"] = d.acknowledged
    if d.acknowledged:
        payload["acknowledgement_reason"] = d.acknowledgement_reason
    return payload


def dumps(envelope: CliResult, *, sort_keys: bool = True) -> str:
    """Serialize *envelope* to one compact UTF-8 JSON document plus one newline.

    Mappings are key-sorted (deterministic), separators are compact, non-ASCII
    characters pass through as literal Unicode, and non-finite numbers are
    rejected. The result is exactly one JSON document terminated by a single
    trailing newline and carries no other prose.
    """
    text = json.dumps(
        to_payload(envelope),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=sort_keys,
        separators=(",", ":"),
    )
    return text + "\n"


def dumps_bytes(envelope: CliResult, *, sort_keys: bool = True) -> bytes:
    """Return the UTF-8 encoding of :func:`dumps` output."""
    return dumps(envelope, sort_keys=sort_keys).encode("utf-8")


__all__ = [
    "COMMAND_EXPORT",
    "COMMAND_INIT",
    "COMMAND_INSPECT",
    "COMMAND_VALIDATE",
    "COMMANDS",
    "ERR_ACK_REASON_INVALID",
    "ERR_ACK_REASON_MISSING",
    "ERR_INVALID_CODE",
    "ERR_INVALID_COMMAND",
    "ERR_INVALID_DIAGNOSTIC",
    "ERR_INVALID_LINE",
    "ERR_INVALID_MESSAGE",
    "ERR_INVALID_OK",
    "ERR_INVALID_PATH",
    "ERR_INVALID_RESULT",
    "ERR_INVALID_SEVERITY",
    "ERR_INVALID_VERSION",
    "INTERNAL_ERROR_CODE",
    "INTERNAL_ERROR_MESSAGE",
    "MAX_ACK_REASON",
    "MAX_CODE",
    "MAX_MESSAGE",
    "MAX_PATH",
    "MIN_ACKNOWLEDGEMENT_REASON",
    "MIN_CODE",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "SEVERITY_ERROR",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "SEVERITIES",
    "CliResult",
    "CliResultError",
    "Command",
    "Diagnostic",
    "Severity",
    "acknowledge",
    "diagnostic",
    "dumps",
    "dumps_bytes",
    "from_validation_issue",
    "internal_error",
    "result",
    "to_payload",
]
