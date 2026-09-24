"""Which canonical documents Beacon may serve, and to whom.

One decision, applied wherever documents leave Beacon: the MCP doc index, catalog and
reads (context ``local``), and snapshot export, HTTP and the Hub (context ``export``).
The rules, in order:

1. **Owner exclusions win.** A path matching ``serving.exclude`` in ``beacon.yaml`` is
   never served, whether the intent file, memory evidence or a convention listed it.
2. **Sensitive files are never served to MCP clients.** ``.env`` files, private keys,
   credential files and similar (:func:`beacon.core.security.classify_path`), even when
   listed; the build also omits them from the generated manifest.
3. **Text documents only** reach MCP clients: Markdown and plain text (:data:`TEXT_SUFFIXES`).
4. **High-confidence secrets withhold a document** from MCP clients
   (:func:`beacon.core.security.detect_sensitive_text`).
5. **Visibility.** ``visibility: local`` documents are served to local MCP clients and
   never exported.

Export (snapshot, HTTP, Hub) applies rules 1 and 5 here; its own security gate already
refuses sensitive files and content, with reviewed ``CODE=REASON`` overrides.

Path containment and size ceilings are enforced where documents are read
(:func:`beacon.core.paths.resolve_canonical_path`, :class:`beacon.core.limits.ResourceLimits`).
Nothing here records or returns document text or matched values: a withheld document is
reported by path and stable code only.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from beacon.core.limits import ResourceLimits
from beacon.core.paths import resolve_canonical_path
from beacon.core.schema import BeaconDoc, BeaconManifest
from beacon.core.security import classify_path, detect_sensitive_text

#: Served to local MCP clients (``beacon serve``).
CONTEXT_LOCAL = "local"
#: Leaves the machine: snapshot export, HTTP, Hub publication.
CONTEXT_EXPORT = "export"

VISIBILITY_PUBLIC = "public"
VISIBILITY_LOCAL = "local"
DOC_VISIBILITIES = (VISIBILITY_PUBLIC, VISIBILITY_LOCAL)

#: Stable codes for a withheld document (never the reason's content).
WITHHELD_EXCLUDED = "doc_excluded"
WITHHELD_SENSITIVE_FILE = "doc_sensitive_file"
WITHHELD_NOT_TEXT = "doc_not_text"
WITHHELD_SENSITIVE_CONTENT = "doc_sensitive_content"
WITHHELD_LOCAL_ONLY = "doc_local_only"

#: Document types Beacon serves. A name without a suffix (``README``, ``LICENSE``) is text.
TEXT_SUFFIXES = frozenset({"", ".md", ".markdown", ".mdx", ".txt", ".rst", ".adoc"})


class ServingRequestError(Exception):
    """A traversal request Beacon refuses; ``code`` is stable and the message holds no content."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


#: Stable request error codes.
TRAVERSAL_DISABLED = "traversal_disabled"
READ_NOT_FOUND = "read_not_found"
READ_TARGET_REQUIRED = "read_target_required"


@dataclass(frozen=True)
class WithheldDoc:
    """A listed document Beacon will not serve in a context: path and code only."""

    path: str
    code: str


def is_excluded(path: str, patterns: tuple[str, ...]) -> bool:
    """True when *path* matches an owner ``serving.exclude`` glob.

    Globs use :func:`fnmatch.fnmatchcase` on the POSIX path, so ``*`` also crosses
    directories (``deploy/*`` excludes ``deploy/a/b.md``); a pattern ending in ``/``
    excludes everything under that directory.
    """
    posix = PurePosixPath(path.replace("\\", "/")).as_posix()
    while posix.startswith("./"):  # only a leading "./"; dot-folders such as .agent/ stay
        posix = posix[2:]
    for pattern in patterns:
        pat = pattern.replace("\\", "/").strip()
        if not pat:
            continue
        if pat.endswith("/"):
            pat += "*"
        if fnmatch.fnmatchcase(posix, pat):
            return True
    return False


def _is_text_path(path: str) -> bool:
    return PurePosixPath(path.replace("\\", "/")).suffix.lower() in TEXT_SUFFIXES


def static_withhold_code(doc: BeaconDoc, *, exclude: tuple[str, ...], context: str) -> str | None:
    """The withhold code decided from the path and manifest alone, or None to serve.

    Export applies owner exclusions and visibility only: the snapshot security gate
    already refuses sensitive files and content, with reviewable ``CODE=REASON`` overrides.
    """
    if is_excluded(doc.path, exclude):
        return WITHHELD_EXCLUDED
    if context == CONTEXT_EXPORT:
        return WITHHELD_LOCAL_ONLY if doc.visibility == VISIBILITY_LOCAL else None
    if classify_path(doc.path) is not None:
        return WITHHELD_SENSITIVE_FILE
    if not _is_text_path(doc.path):
        return WITHHELD_NOT_TEXT
    return None


def served_docs(
    manifest: BeaconManifest,
    *,
    context: str,
    docs_root: str | Path | None = None,
    limits: ResourceLimits | None = None,
) -> tuple[tuple[BeaconDoc, ...], tuple[WithheldDoc, ...]]:
    """Split ``manifest.canonical_docs`` into those served in *context* and those withheld.

    With *docs_root*, local serving also reads each remaining document (within
    ``document_bytes``) and withholds any with high-confidence sensitive content.
    Export leaves content checks to the snapshot security gate, which blocks with
    reviewable overrides instead of silently dropping.
    """
    if context not in (CONTEXT_LOCAL, CONTEXT_EXPORT):
        raise ValueError(f"unknown serving context {context!r}")
    active = limits if limits is not None else ResourceLimits()
    exclude = manifest.serving.exclude
    served: list[BeaconDoc] = []
    withheld: list[WithheldDoc] = []
    for doc in manifest.canonical_docs:
        code = static_withhold_code(doc, exclude=exclude, context=context)
        if code is None and context == CONTEXT_LOCAL and docs_root is not None:
            code = _content_withhold_code(doc, Path(docs_root), active)
        if code is None:
            served.append(doc)
        else:
            withheld.append(WithheldDoc(path=doc.path, code=code))
    return tuple(served), tuple(withheld)


def _content_withhold_code(doc: BeaconDoc, root: Path, limits: ResourceLimits) -> str | None:
    try:
        target = resolve_canonical_path(root, doc.path)
    except Exception:  # noqa: BLE001 - containment failures are reported where docs are read
        return None
    if not target.is_file():
        return None
    try:
        with target.open("rb") as handle:
            raw = handle.read(limits.document_bytes + 1)
    except OSError:
        return None
    text = raw[: limits.document_bytes].decode("utf-8", errors="replace")
    return WITHHELD_SENSITIVE_CONTENT if detect_sensitive_text(text, path=doc.path) else None


def manifest_for_context(
    manifest: BeaconManifest,
    *,
    context: str,
    docs_root: str | Path | None = None,
    limits: ResourceLimits | None = None,
) -> tuple[BeaconManifest, tuple[WithheldDoc, ...]]:
    """*manifest* with only the documents served in *context*.

    Withheld paths are also dropped from ``agent_guidance.read_first`` so a surface
    never names a document it will not serve.
    """
    served, withheld = served_docs(manifest, context=context, docs_root=docs_root, limits=limits)
    if not withheld:
        return manifest, ()
    hidden = {item.path for item in withheld}
    guidance = replace(
        manifest.agent_guidance,
        read_first=tuple(path for path in manifest.agent_guidance.read_first if path not in hidden),
    )
    return replace(manifest, canonical_docs=served, agent_guidance=guidance), withheld


__all__ = [
    "READ_NOT_FOUND",
    "READ_TARGET_REQUIRED",
    "TRAVERSAL_DISABLED",
    "ServingRequestError",
    "CONTEXT_EXPORT",
    "CONTEXT_LOCAL",
    "DOC_VISIBILITIES",
    "TEXT_SUFFIXES",
    "VISIBILITY_LOCAL",
    "VISIBILITY_PUBLIC",
    "WITHHELD_EXCLUDED",
    "WITHHELD_LOCAL_ONLY",
    "WITHHELD_NOT_TEXT",
    "WITHHELD_SENSITIVE_CONTENT",
    "WITHHELD_SENSITIVE_FILE",
    "WithheldDoc",
    "is_excluded",
    "manifest_for_context",
    "served_docs",
    "static_withhold_code",
]
