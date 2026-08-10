"""Frozen resource-limits model for Beacon v0.2.

The addendum (``.agent/plans/beacon-v0.2-implementation-readiness-addendum``,
§4) defines a small-to-medium repository profile with six *overridable* limits
(six byte/count ceilings) and a set of non-overridable safety ceilings (YAML
depth/node/alias, path bytes, query bytes, result limit). This module is the
single immutable home for those defaults and for safe parsing that rejects
negative and overflow values without silently truncating.

Precedence is ``CLI override > environment > default``. ``resource_limits_from_env``
applies the environment layer on top of the defaults; ``ResourceLimits.apply_overrides``
applies an explicit (e.g. CLI-provided) layer on top of an existing instance.

Every refusal here carries a stable, non-secret diagnostic ``code`` and never
embeds document contents or secret environment values.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Mapping

#: A byte is a byte; MiB = 1048576, KiB = 1024.
_MIB = 1024 * 1024
_KIB = 1024

# ---------------------------------------------------------------------------
# Stable diagnostic codes (never include document content or secret values)
# ---------------------------------------------------------------------------

LIMIT_MANIFEST_BYTES = "limit_manifest_bytes"
LIMIT_YAML_DEPTH = "limit_yaml_depth"
LIMIT_YAML_NODES = "limit_yaml_nodes"
LIMIT_YAML_ALIASES = "limit_yaml_aliases"
LIMIT_DOCUMENTS = "limit_documents"
LIMIT_DOCUMENT_BYTES = "limit_document_bytes"
LIMIT_TOTAL_DOCUMENT_BYTES = "limit_total_document_bytes"
LIMIT_PATH_BYTES = "limit_path_bytes"
LIMIT_CHUNKS = "limit_chunks"
LIMIT_QUERY_BYTES = "limit_query_bytes"
LIMIT_RESULT_LIMIT = "limit_result_limit"
LIMIT_SNAPSHOT_BYTES = "limit_snapshot_bytes"
LIMIT_INIT_REPORT_BYTES = "limit_init_report_bytes"
#: Raised when an override value is non-integer, negative, or overflows.
LIMIT_INVALID_VALUE = "limit_invalid_value"

#: Limit codes that a user may override via CLI/environment.
OVERRIDABLE_LIMIT_FIELDS = (
    "manifest_bytes",
    "documents",
    "document_bytes",
    "total_document_bytes",
    "chunks",
    "snapshot_bytes",
)

#: Canonical env-var name per overridable field (matches the addendum §4).
FIELD_ENV_VARS: Mapping[str, str] = {
    "manifest_bytes": "BEACON_MAX_MANIFEST_BYTES",
    "documents": "BEACON_MAX_DOCUMENTS",
    "document_bytes": "BEACON_MAX_DOCUMENT_BYTES",
    "total_document_bytes": "BEACON_MAX_TOTAL_DOCUMENT_BYTES",
    "chunks": "BEACON_MAX_CHUNKS",
    "snapshot_bytes": "BEACON_MAX_SNAPSHOT_BYTES",
}

#: Stable code reported when an overridable field's ceiling is hit.
FIELD_LIMIT_CODES: Mapping[str, str] = {
    "manifest_bytes": LIMIT_MANIFEST_BYTES,
    "documents": LIMIT_DOCUMENTS,
    "document_bytes": LIMIT_DOCUMENT_BYTES,
    "total_document_bytes": LIMIT_TOTAL_DOCUMENT_BYTES,
    "chunks": LIMIT_CHUNKS,
    "snapshot_bytes": LIMIT_SNAPSHOT_BYTES,
}


@dataclass(frozen=True)
class ResourceLimits:
    """Immutable ceiling model with the addendum's standard defaults.

    The six leading fields are overridable. The remaining six are fixed safety
    ceilings for v0.2 and are not overridable.
    """

    # -- overridable --------------------------------------------------------
    manifest_bytes: int = 1 * _MIB
    documents: int = 256
    document_bytes: int = 2 * _MIB
    total_document_bytes: int = 20 * _MIB
    chunks: int = 10_000
    snapshot_bytes: int = 50 * _MIB

    # -- fixed ceilings (not overridable in v0.2) ---------------------------
    yaml_depth: int = 32
    yaml_nodes: int = 50_000
    yaml_aliases: int = 50
    path_bytes: int = 1_024
    query_bytes: int = 4 * _KIB
    result_limit: int = 100
    init_report_bytes: int = 5 * _MIB

    def __post_init__(self) -> None:
        """Reject invalid values even for direct programmatic construction."""
        for item in fields(self):
            _validate_int(getattr(self, item.name), item.name, where="ResourceLimits")

    def apply_overrides(
        self, overrides: Mapping[str, Any], *, where: str = "override"
    ) -> "ResourceLimits":
        """Return a copy with the given overridable fields replaced.

        *overrides* keys are field names (e.g. ``"documents"``) and values are
        integer ceilings. Each value is validated: non-integer, negative, and
        overflow values raise :class:`LimitError` with ``limit_invalid_value``.
        Non-overridable fields and unknown keys are ignored so callers can pass
        a superset mapping safely.
        """
        if not overrides:
            return self
        changes: dict[str, int] = {}
        for name in OVERRIDABLE_LIMIT_FIELDS:
            if name not in overrides:
                continue
            changes[name] = _validate_int(overrides[name], name, where=where)
        return replace(self, **changes)

    def ceiling(self, field: str) -> int:
        """Return the ceiling for an overridable *field*."""
        return getattr(self, field)


class LimitError(Exception):
    """Raised when a resource ceiling is exceeded or an override is invalid.

    ``code`` is a stable, non-secret diagnostic string. ``limit`` names the
    ceiling and ``limit_value`` is its configured maximum. The message never
    contains document contents or secret values.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        limit: str | None = None,
        limit_value: int | None = None,
    ) -> None:
        self.code = code
        self.limit = limit
        self.limit_value = limit_value
        super().__init__(message)


def check_limit(field: str, actual: int, limits: ResourceLimits) -> None:
    """Raise a :class:`LimitError` when *actual* exceeds ``limits.<field>``."""
    ceiling = getattr(limits, field)
    if actual > ceiling:
        code = FIELD_LIMIT_CODES.get(field, LIMIT_INVALID_VALUE)
        raise LimitError(
            code,
            f"resource limit exceeded: {code} (field={field}, limit={ceiling}, actual={actual})",
            limit=field,
            limit_value=ceiling,
        )


def read_bytes_bounded(
    path: str | Path,
    *,
    ceiling: int,
    code: str,
    field: str,
) -> bytes:
    """Read at most *ceiling* bytes plus one sentinel byte from *path*.

    This keeps refusal bounded even when the source is much larger than the
    configured ceiling. The returned value is complete; content is never
    silently truncated.
    """
    data = bytearray()
    with Path(path).open("rb") as handle:
        while len(data) <= ceiling:
            remaining = ceiling + 1 - len(data)
            chunk = handle.read(min(64 * 1024, remaining))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
    raise LimitError(
        code,
        f"resource limit exceeded: {code} (field={field}, limit={ceiling}, "
        f"actual_at_least={len(data)})",
        limit=field,
        limit_value=ceiling,
    )


def resource_limits_from_env(env: Mapping[str, str] | None = None) -> ResourceLimits:
    """Return :class:`ResourceLimits` with environment overrides applied.

    Reads the six ``BEACON_MAX_*`` variables from *env* (defaults to
    ``os.environ``). Invalid values raise :class:`LimitError`.
    """
    if env is None:
        import os

        env = os.environ
    overrides: dict[str, int] = {}
    for field, var in FIELD_ENV_VARS.items():
        raw = env.get(var, "")
        if raw is None or str(raw).strip() == "":
            continue
        overrides[field] = _validate_int(raw, field, where=var)
    return _DEFAULTS.apply_overrides(overrides, where="environment")


def _validate_int(value: Any, field: str, *, where: str) -> int:
    """Coerce *value* to a non-negative, non-overflowing integer ceiling."""
    if isinstance(value, bool):
        parsed = None
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        try:
            parsed = int(raw) if raw and raw.isascii() else None
        except ValueError:
            parsed = None
    else:
        parsed = None
    if parsed is None:
        raise LimitError(
            LIMIT_INVALID_VALUE,
            f"invalid {field} ceiling from {where}: expected a positive integer",
            limit=field,
        )
    if parsed < 0:
        raise LimitError(
            LIMIT_INVALID_VALUE,
            f"invalid {field} ceiling from {where}: must not be negative",
            limit=field,
        ) from None
    if parsed > _MAX_LIMIT:
        raise LimitError(
            LIMIT_INVALID_VALUE,
            f"invalid {field} ceiling from {where}: value overflows supported range",
            limit=field,
        ) from None
    return parsed


#: Upper bound for any configured ceiling (rejects overflow-style values).
_MAX_LIMIT = 2**63 - 1

#: The canonical default instance (single source of truth).
_DEFAULTS = ResourceLimits()


def limit_field_names() -> tuple[str, ...]:
    """Return the field names of :class:`ResourceLimits` in definition order."""
    return tuple(f.name for f in fields(ResourceLimits))


__all__ = [
    "FIELD_ENV_VARS",
    "LIMIT_CHUNKS",
    "LIMIT_DOCUMENTS",
    "LIMIT_DOCUMENT_BYTES",
    "LIMIT_INVALID_VALUE",
    "LIMIT_INIT_REPORT_BYTES",
    "LIMIT_MANIFEST_BYTES",
    "LIMIT_PATH_BYTES",
    "LIMIT_QUERY_BYTES",
    "LIMIT_RESULT_LIMIT",
    "LIMIT_SNAPSHOT_BYTES",
    "LIMIT_TOTAL_DOCUMENT_BYTES",
    "LIMIT_YAML_ALIASES",
    "LIMIT_YAML_DEPTH",
    "LIMIT_YAML_NODES",
    "OVERRIDABLE_LIMIT_FIELDS",
    "LimitError",
    "ResourceLimits",
    "check_limit",
    "limit_field_names",
    "read_bytes_bounded",
    "resource_limits_from_env",
]
