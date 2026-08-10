"""Canonical JSON for Beacon v0.2 snapshots, reports, and envelopes.

Provides a single bounded, deterministic JSON pipeline: recursive value
validation, mapping-key ordering, compact UTF-8 serialization ending in exactly
one trailing newline, and byte-ceiling refusal with atomic file replacement and
temporary-artifact cleanup on every failure path. Normalizes nothing
domain-specific.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from beacon.core.limits import (
    LIMIT_INVALID_VALUE,
    LIMIT_SNAPSHOT_BYTES,
    LimitError,
    ResourceLimits,
)


class InvalidJsonValue(ValueError):
    """Raised when a value is not representable as canonical JSON.

    Non-JSON types, non-string mapping keys, and non-finite numbers (NaN,
    infinity) are refused. ``path`` names the offending location in the value
    tree but the message never embeds document or secret content.
    """

    def __init__(self, *, path: str) -> None:
        self.path = path
        super().__init__(f"non-JSON value at {path or '$'}")


#: Default byte ceiling when none is supplied: the frozen snapshot ceiling.
_DEFAULT_CEILING = ResourceLimits().snapshot_bytes

#: Compact, deterministic separators (no whitespace between tokens).
_JSON_SEPARATORS = (",", ":")


def validate_json_value(value: Any) -> None:
    """Recursively refuse values that canonical JSON cannot represent.

    Accepts ``None``, ``bool``, ``int``, finite ``float``, ``str``, ``list``,
    and ``dict`` (with string keys). Refuses non-finite floats, non-string
    mapping keys, tuples, bytes, sets, and any other object type.
    """
    _validate(value, "$")


def dumps_canonical(value: Any, *, byte_ceiling: int | None = None) -> bytes:
    """Return canonical compact UTF-8 JSON bytes ending in exactly one newline.

    Mapping keys are sorted for determinism, non-JSON values are refused, and
    the serialized size is bounded by *byte_ceiling* (defaults to
    ``ResourceLimits.snapshot_bytes``). Raises :class:`InvalidJsonValue` for
    non-JSON input and :class:`LimitError` with ``limit_snapshot_bytes`` when
    the payload exceeds the ceiling. A non-integer or negative *byte_ceiling*
    is refused with ``limit_invalid_value`` rather than treated as a payload.
    """
    ceiling = _validate_ceiling(byte_ceiling)
    validate_json_value(value)
    text = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=_JSON_SEPARATORS,
    )
    payload = (text + "\n").encode("utf-8")
    if len(payload) > ceiling:
        raise LimitError(
            LIMIT_SNAPSHOT_BYTES,
            f"resource limit exceeded: {LIMIT_SNAPSHOT_BYTES} "
            f"(field=snapshot_bytes, limit={ceiling}, actual={len(payload)})",
            limit="snapshot_bytes",
            limit_value=ceiling,
        )
    return payload


def write_atomic(path: str | Path, value: Any, *, byte_ceiling: int | None = None) -> None:
    """Atomically replace *path* with canonical JSON for *value*.

    The payload is validated and size-checked *before* any file is created, so
    an oversized or invalid value refuses without touching the destination. The
    replacement is written to a same-directory temporary file, flushed and
    fsynced, then atomically renamed over the destination. On any write or
    replace failure the temporary file is removed and no partial artifact is
    left behind.
    """
    payload = dumps_canonical(value, byte_ceiling=byte_ceiling)
    destination = Path(path)
    fd = -1
    tmp_path = ""
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=destination.name + ".", suffix=".tmp", dir=destination.parent
        )
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, destination)
        tmp_path = ""
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _validate(value: Any, path: str) -> None:
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidJsonValue(path=path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidJsonValue(path=f"{path}.<key>")
            _validate(item, _join(path, key))
        return
    raise InvalidJsonValue(path=path)


def _join(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent != "$" else f"$.{key}"


def _validate_ceiling(byte_ceiling: int | None) -> int:
    """Coerce *byte_ceiling* to a valid positive ceiling.

    ``None`` maps to the frozen snapshot ceiling. Negative, boolean, and
    non-integer values raise :class:`LimitError` with ``limit_invalid_value``
    so an explicit bad ceiling is never silently treated as an oversized payload.
    """
    if byte_ceiling is None:
        return _DEFAULT_CEILING
    if isinstance(byte_ceiling, bool) or not isinstance(byte_ceiling, int):
        raise LimitError(
            LIMIT_INVALID_VALUE,
            "invalid snapshot byte ceiling: expected a positive integer",
            limit="snapshot_bytes",
        )
    if byte_ceiling < 0:
        raise LimitError(
            LIMIT_INVALID_VALUE,
            "invalid snapshot byte ceiling: must not be negative",
            limit="snapshot_bytes",
        )
    return byte_ceiling


__all__ = [
    "InvalidJsonValue",
    "dumps_canonical",
    "validate_json_value",
    "write_atomic",
]
