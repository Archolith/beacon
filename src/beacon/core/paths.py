"""Reusable canonical-document path boundary for Beacon.

A canonical doc path is a *relative forward-slash* path resolved against
``BEACON_DOCS_ROOT``. To keep the doc index (and therefore the server) from ever
reading outside the docs root, every canonical path is resolved through a single
strict boundary check that rejects:

* absolute paths (POSIX leading ``/``, Windows drive paths, and UNC ``\\\\``),
* ``..`` parent traversal, and
* symlink escapes whose resolved target lands outside the docs root.

The resolver emits a stable, non-secret diagnostic code and never includes the
escaped target path or any file content in an error.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Stable diagnostic code for an unsafe canonical document path.
CODE_UNSAFE_CANONICAL_PATH = "unsafe_canonical_path"

#: Segment splitter that recognises both POSIX and Windows separators.
_SEGMENT_SPLIT = re.compile(r"[\\/]+")


class UnsafeCanonicalPath(ValueError):
    """Raised when a canonical doc path could escape ``docs_root``.

    ``code`` is the stable, non-secret diagnostic code. The message never
    contains the offending path or any file content.
    """

    def __init__(self, *, code: str = CODE_UNSAFE_CANONICAL_PATH) -> None:
        self.code = code
        super().__init__("unsafe canonical path")


def is_unsafe_path(raw_path: str) -> bool:
    """Return True when *raw_path* is absolute or contains ``..`` traversal."""
    return _is_absolute_like(raw_path) or any(
        segment == ".." for segment in _split_segments(raw_path)
    )


def resolve_canonical_path(docs_root: str | Path, raw_path: str) -> Path:
    """Resolve *raw_path* against *docs_root* within a strict boundary.

    Rejects absolute paths, ``..`` traversal, and any symlink escape whose
    resolved target lies outside the (symlink-resolved) *docs_root*. Returns the
    resolved absolute :class:`~pathlib.Path` on success and raises
    :class:`UnsafeCanonicalPath` on any violation.
    """
    if is_unsafe_path(raw_path):
        raise UnsafeCanonicalPath()
    try:
        root = Path(docs_root).resolve()
        candidate = root.joinpath(raw_path)
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise UnsafeCanonicalPath() from exc
    if not resolved.is_relative_to(root):
        raise UnsafeCanonicalPath()
    return resolved


def _is_absolute_like(raw: str) -> bool:
    if raw.startswith(("/", "\\")):
        return True
    if len(raw) >= 2 and raw[0].isalpha() and raw[1] == ":":
        return True
    if raw.startswith("\\\\") or raw.startswith("//"):
        return True
    return False


def _split_segments(raw: str) -> list[str]:
    return [segment for segment in _SEGMENT_SPLIT.split(raw) if segment]


__all__ = [
    "CODE_UNSAFE_CANONICAL_PATH",
    "UnsafeCanonicalPath",
    "is_unsafe_path",
    "resolve_canonical_path",
]
