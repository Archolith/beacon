"""Pure, bounded, offline repository observation for ``beacon init``.

Discovery never runs git, never touches the network, and never recurses the
filesystem. It reads only a finite set of fixed in-root regular files (entry
documents, build markers, license files, ``.git/config``) and derives a
deterministic starter manifest signal set: the project name from the directory,
a sanitized origin repository URL, language/build/test hints from supported
markers, a license identifier from a known license filename, and allowlisted
entry documents.

Safety invariants:

* the root must be a real existing directory that is not itself a symlink;
* every file read is a regular in-root file, resolved under the resolved root
  (symlinks, escapes, and non-regular files are refused);
* resource limits fail *closed*: a selected marker/config/document that exceeds
  a ceiling raises :class:`LimitError` -- it is never silently skipped;
* path-byte limits are applied to repository-relative paths, not machine paths;
* git remotes are sanitized (userinfo stripped, query/fragment dropped, hostname
  validated) and never expose credentials; a credential-bearing remote is
  recorded as a non-blocked (``blocked=False``) security finding because its raw
  value is excluded and init may proceed;
* no test command is ever invented -- each is emitted only when an unambiguous
  signal is present, and an ambiguous Node package manager omits commands and
  flags ``build_commands_unknown`` for review; and
* all reads and counts are bounded by :class:`ResourceLimits`.

The module is pure data (no MCP, no CLI, no side effects) so the scaffold and
CLI wrapper can share it.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from beacon.core.limits import (
    LIMIT_DOCUMENT_BYTES,
    LIMIT_DOCUMENTS,
    LIMIT_PATH_BYTES,
    LIMIT_TOTAL_DOCUMENT_BYTES,
    LimitError,
    ResourceLimits,
    read_bytes_bounded,
)
from beacon.core.paths import is_unsafe_path
from beacon.core.security import (
    SENSITIVE_CREDENTIAL_URL,
    SecurityFinding,
    classify_path,
)

#: Kind values the init-report ``evidence`` schema permits.
KIND_DIRECTORY_NAME = "directory_name"
KIND_GIT_REMOTE = "git_remote"
KIND_BUILD_FILE = "build_file"
KIND_LICENSE_FILE = "license_file"
KIND_DOCUMENT = "document"

#: Fixed allowlist of entry-document relative paths, in deterministic order.
ENTRY_DOC_PATHS: tuple[str, ...] = (
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    ".agent/README.md",
    "docs/README.md",
    "docs/index.md",
    "docs/architecture.md",
)

#: Known license filenames -> SPDX-style identifier. Generic files map to
#: ``unknown`` (the presence of a license file is detected, its type is not).
_LICENSE_FILENAME_MAP: dict[str, str] = {
    "mit": "MIT",
    "mit.txt": "MIT",
    "license-mit": "MIT",
    "license-mit.txt": "MIT",
    "apache": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "apache-2.0.txt": "Apache-2.0",
    "license-apache": "Apache-2.0",
    "license-apache-2.0": "Apache-2.0",
    "license-apache-2.0.txt": "Apache-2.0",
    "bsd-3-clause": "BSD-3-Clause",
    "bsd-3-clause.txt": "BSD-3-Clause",
    "license-bsd": "BSD-3-Clause",
    "license-bsd-3-clause": "BSD-3-Clause",
    "unlicense": "Unlicense",
    "unlicense.txt": "Unlicense",
    "gpl-3.0": "GPL-3.0",
    "gpl-3.0.txt": "GPL-3.0",
    "license-gpl-3.0": "GPL-3.0",
    "mpl-2.0": "MPL-2.0",
    "mpl-2.0.txt": "MPL-2.0",
    "license-mpl-2.0": "MPL-2.0",
    # Generic -- detected but type unknown.
    "license": "unknown",
    "license.md": "unknown",
    "license.txt": "unknown",
    "copying": "unknown",
    "copying.md": "unknown",
    "copying.txt": "unknown",
}

#: Known license filenames (any case), in deterministic order.
LICENSE_FILENAMES: tuple[str, ...] = (
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "LICENSE-MIT",
    "LICENSE-MIT.txt",
    "MIT",
    "MIT.txt",
    "LICENSE-APACHE",
    "LICENSE-APACHE-2.0",
    "LICENSE-APACHE-2.0.txt",
    "APACHE-2.0",
    "APACHE-2.0.txt",
    "LICENSE-BSD-3-CLAUSE",
    "LICENSE-BSD-3-CLAUSE.txt",
    "UNLICENSE",
    "UNLICENSE.txt",
    "LICENSE-GPL-3.0",
    "LICENSE-GPL-3.0.txt",
    "LICENSE-MPL-2.0",
    "LICENSE-MPL-2.0.txt",
    "COPYING",
    "COPYING.md",
    "COPYING.txt",
)

#: Supported build markers, in deterministic precedence order.
_BUILD_MARKERS: tuple[str, ...] = ("pyproject.toml", "package.json", "Cargo.toml", "go.mod")

#: Python: an unambiguous test command requires pytest tool configuration.
_PYTEST_TOOL_RE = re.compile(r"^\[tool\.pytest(?:\.|,\]|\s)", re.MULTILINE)

#: Lockfile -> package manager, in deterministic order.
_LOCKFILES: tuple[tuple[str, str], ...] = (
    ("package-lock.json", "npm"),
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
)

#: Deterministic per-manager install/test commands.
_PKG_MANAGER_COMMANDS: dict[str, tuple[str, str]] = {
    "npm": ("npm install", "npm test"),
    "pnpm": ("pnpm install", "pnpm test"),
    "yarn": ("yarn install", "yarn test"),
}

#: Placeholder userinfo values that should not be flagged as credentials,
#: aligned with :mod:`beacon.core.security` placeholder policy.
_PLACEHOLDER_USERINFO = frozenset(
    {
        "user:password",
        "user:pass",
        "user:secret",
        "demo:demo",
        "sample:sample",
        "example:example",
        "username:password",
        "changeme:changeme",
        "token:token",
        "xxx:xxx",
        "user:yourpassword",
        "youruser:yourpassword",
        "yourusername:yourpassword",
    }
)

#: SCP-style ``user@host:path`` (no scheme).
_SCP_RE = re.compile(r"^([^@\s:/]+)@([^:\s/]+):(.+)$")


class DiscoveryError(ValueError):
    """Raised when a discovery precondition is violated (e.g. non-directory root)."""


@dataclass(frozen=True)
class Evidence:
    """One bounded observation backing a discovered field."""

    kind: str  # one of KIND_*
    path: str  # repository-relative, forward-slash
    sha256: str | None = None  # lowercase hex digest (documents only)


@dataclass(frozen=True)
class DiscoveryResult:
    """Deterministic, offline observations about a repository.

    ``name`` is always present. Optional string fields are ``None`` when no
    safe evidence was found (they are omitted, not guessed). ``doc_evidence``
    carries one :class:`Evidence` per ``canonical_docs`` entry, in the same
    order. ``build_commands_unknown`` is set when a language is detected but
    its build/test commands cannot be established unambiguously.
    """

    name: str
    repository: str | None
    primary_language: str | None
    license_name: str | None
    canonical_docs: tuple[str, ...]
    setup_command: str | None
    test_command: str | None
    name_evidence: Evidence
    git_evidence: Evidence | None = None
    build_evidence: Evidence | None = None
    license_evidence: Evidence | None = None
    doc_evidence: tuple[Evidence, ...] = ()
    security_findings: tuple[SecurityFinding, ...] = ()
    build_commands_unknown: bool = False


def discover(root: str | Path, *, limits: ResourceLimits | None = None) -> DiscoveryResult:
    """Discover starter-manifest signals from the repository at *root*.

    Raises :class:`DiscoveryError` when *root* is not a real (non-symlink)
    directory and :class:`LimitError` when a bounded read/count ceiling is
    exceeded. Limits fail closed: no selected file is silently skipped. The
    result is deterministic for unchanged inputs.
    """
    active = limits if limits is not None else ResourceLimits()
    root_path = _require_directory(root)

    name = _project_name(root_path)
    name_evidence = Evidence(kind=KIND_DIRECTORY_NAME, path=".")

    repository, git_evidence, git_findings = _discover_remote(root_path, active)

    language, build_evidence, setup_cmd, test_cmd, commands_unknown = _discover_build(
        root_path, active
    )

    license_name, license_evidence = _discover_license(root_path, active)

    docs, doc_evidence = _discover_entry_docs(root_path, active)

    return DiscoveryResult(
        name=name,
        repository=repository,
        primary_language=language,
        license_name=license_name,
        canonical_docs=docs,
        setup_command=setup_cmd,
        test_command=test_cmd,
        name_evidence=name_evidence,
        git_evidence=git_evidence,
        build_evidence=build_evidence,
        license_evidence=license_evidence,
        doc_evidence=doc_evidence,
        security_findings=git_findings,
        build_commands_unknown=commands_unknown,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_directory(root: str | Path) -> Path:
    raw = Path(root)
    if raw.is_symlink() or not raw.is_dir():
        raise DiscoveryError(f"repository root is not a real directory: {root}")
    return raw.resolve()


def _project_name(root: Path) -> str:
    return root.name


def _safe_regular(root: Path, candidate: Path, limits: ResourceLimits) -> bool:
    """Return True only for a regular file under the resolved *root*.

    An *absent* fixed allowlist candidate is simply refused (``False``) -- it
    does not fail merely because its fixed name exceeds a custom path limit.
    A *present, selected* regular file whose repository-relative path exceeds
    ``path_bytes`` raises :class:`LimitError` (``limit_path_bytes``): limits
    fail closed on files we actually read. Symlinks (including a symlinked
    parent that resolves outside *root*), non-regular files, and escapes are
    refused with ``False``.
    """
    try:
        rel = candidate.relative_to(root)
    except ValueError:
        return False
    if candidate.is_symlink() or not candidate.is_file():
        return False
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return False
    if not resolved.is_relative_to(root):
        return False
    rel_str = rel.as_posix()
    rel_bytes = len(rel_str.encode("utf-8"))
    if rel_bytes > limits.path_bytes:
        raise LimitError(
            LIMIT_PATH_BYTES,
            f"resource limit exceeded: {LIMIT_PATH_BYTES} "
            f"(limit={limits.path_bytes}, actual={rel_bytes})",
            limit="path_bytes",
            limit_value=limits.path_bytes,
        )
    return True


def _read_bounded(path: Path, limits: ResourceLimits) -> bytes:
    return read_bytes_bounded(
        path,
        ceiling=limits.document_bytes,
        code=LIMIT_DOCUMENT_BYTES,
        field="document_bytes",
    )


def _discover_remote(
    root: Path, limits: ResourceLimits
) -> tuple[str | None, Evidence | None, tuple[SecurityFinding, ...]]:
    config = root / ".git" / "config"
    if not _safe_regular(root, config, limits):
        return None, None, ()
    raw = _read_bounded(config, limits)
    url = _read_origin_url(raw.decode("utf-8", errors="replace"))
    if url is None:
        return None, None, ()
    sanitized, findings = sanitize_remote_url(url)
    if sanitized is None:
        return None, None, ()
    return sanitized, Evidence(kind=KIND_GIT_REMOTE, path=".git/config"), findings


def _read_origin_url(config_text: str) -> str | None:
    section: str | None = None
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            continue
        if section == 'remote "origin"':
            key, _, value = stripped.partition("=")
            if key.strip().lower() == "url":
                candidate = _strip_quotes(value.strip())
                if candidate:
                    return candidate
    return None


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def sanitize_remote_url(raw: str) -> tuple[str | None, tuple[SecurityFinding, ...]]:
    """Sanitize *raw* to a credential-free https URL (or ``None``).

    HTTP(S) remotes have any non-placeholder userinfo (including a bare
    ``token@host``) stripped and flagged as a ``sensitive_credential_url``
    finding with ``blocked=False`` (the raw value is excluded, so init may
    proceed); query and fragment are dropped. The hostname must be a valid DNS
    name, ``localhost``, IPv4, or bracketed IPv6 literal, and any port must
    parse to 1..65535; invalid hosts or malformed/out-of-range ports yield
    ``None``. SCP-style ``user@host:path`` (and ssh/git schemes) become
    ``https://host/path``. The returned URL never contains the credential.
    Non-remote values (local paths, unknown schemes) yield ``(None, ())``. The
    raw value is never placed into a result or error.
    """
    value = raw.strip()
    if not value:
        return None, ()
    if "://" in value:
        try:
            parts = urlsplit(value)
        except ValueError:
            return None, ()
        if parts.scheme not in ("http", "https", "ssh", "git"):
            return None, ()
        try:
            port = parts.port
        except ValueError:
            return None, ()
        host = parts.hostname
        if not _valid_remote_host(host):
            return None, ()
        if port is not None and not (1 <= port <= 65535):
            return None, ()
        userinfo, sep, hostport = parts.netloc.rpartition("@")
        # Brackets are only valid around an IPv6 literal; a bracketed DNS-like
        # host is malformed and refused.
        if "[" in hostport and ":" not in (host or ""):
            return None, ()
        findings: tuple[SecurityFinding, ...] = ()
        if (
            sep
            and not _is_placeholder_userinfo(userinfo)
            and (parts.scheme in ("http", "https") or ":" in userinfo)
        ):
            # The raw credential is stripped from the returned URL and never
            # stored, so init may proceed: the finding is recorded as not
            # blocked.
            findings = (
                SecurityFinding(code=SENSITIVE_CREDENTIAL_URL, path=".git/config", blocked=False),
            )
        if parts.scheme in ("ssh", "git"):
            netloc = f"[{host}]" if host is not None and ":" in host else host
            scheme = "https"
        else:
            netloc = hostport
            scheme = parts.scheme
        return urlunsplit((scheme, netloc, parts.path or "", "", "")), findings
    match = _SCP_RE.match(value)
    if match:
        host = match.group(2)
        if not _valid_remote_host(host):
            return None, ()
        return f"https://{host}/{match.group(3).lstrip('/')}", ()
    return None, ()


def _valid_remote_host(host: str | None) -> bool:
    """Return True when *host* is a conservative valid DNS/IPv6/IPv4 literal.

    Rejects empty hosts, surrounding or interior whitespace/control characters,
    and malformed literals. Accepts ``localhost``, normal DNS names, IPv4, and
    IPv6 literals (any zone index ignored).
    """
    if not host:
        return False
    if host != host.strip():
        return False
    if any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in host):
        return False
    if host.lower() == "localhost":
        return True
    if ":" in host:
        try:
            ipaddress.IPv6Address(host.split("%")[0])
            return True
        except ValueError:
            return False
    try:
        ipaddress.IPv4Address(host)
        return True
    except ValueError:
        pass
    if not all(ord(ch) < 128 for ch in host):
        return False
    labels = host.split(".")
    if any(not label for label in labels):
        return False
    for label in labels:
        if len(label) > 63 or label.startswith("-") or label.endswith("-"):
            return False
        if not all(ch.isalnum() or ch == "-" for ch in label):
            return False
    return True


def _is_placeholder_userinfo(userinfo: str) -> bool:
    return userinfo.strip().lower() in _PLACEHOLDER_USERINFO


def _discover_build(
    root: Path, limits: ResourceLimits
) -> tuple[str | None, Evidence | None, str | None, str | None, bool]:
    for marker in _BUILD_MARKERS:
        marker_path = root / marker
        if not _safe_regular(root, marker_path, limits):
            continue
        evidence = Evidence(kind=KIND_BUILD_FILE, path=marker)
        if marker == "package.json":
            return _detect_node(root, marker_path, evidence, limits)
        content = _read_bounded(marker_path, limits).decode("utf-8", errors="replace")
        language, setup_cmd, test_cmd, unknown = _detect_from_marker(marker, content)
        return language, evidence, setup_cmd, test_cmd, unknown
    return None, None, None, None, False


def _detect_from_marker(
    marker: str, content: str
) -> tuple[str | None, str | None, str | None, bool]:
    if marker == "pyproject.toml":
        test = "python -m pytest tests/ -x --tb=short" if _PYTEST_TOOL_RE.search(content) else None
        return "Python", "pip install -e .", test, False
    if marker == "Cargo.toml":
        return "Rust", "cargo build", "cargo test", False
    if marker == "go.mod":
        return "Go", "go mod download", "go test ./...", False
    return None, None, None, False


def _detect_node(
    root: Path, package_json: Path, evidence: Evidence, limits: ResourceLimits
) -> tuple[str | None, Evidence | None, str | None, str | None, bool]:
    content = _read_bounded(package_json, limits).decode("utf-8", errors="replace")
    has_test = _package_json_has_test_script(content)
    managers = [
        manager for lockfile, manager in _LOCKFILES if _safe_regular(root, root / lockfile, limits)
    ]
    manager = managers[0] if len(managers) == 1 else None
    if manager is None:
        # Ambiguous (none or multiple lockfiles): retain language, omit commands.
        return "JavaScript", evidence, None, None, True
    setup, test_cmd = _PKG_MANAGER_COMMANDS[manager]
    test = test_cmd if has_test else None
    return "JavaScript", evidence, setup, test, False


def _package_json_has_test_script(content: str) -> bool:
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return False
    test = scripts.get("test")
    return isinstance(test, str) and bool(test.strip())


def _discover_license(root: Path, limits: ResourceLimits) -> tuple[str | None, Evidence | None]:
    for filename in LICENSE_FILENAMES:
        candidate = root / filename
        if not _safe_regular(root, candidate, limits):
            continue
        key = filename.lower()
        identifier = _LICENSE_FILENAME_MAP.get(key, "unknown")
        return identifier, Evidence(kind=KIND_LICENSE_FILE, path=filename)
    return None, None


def _discover_entry_docs(
    root: Path, limits: ResourceLimits
) -> tuple[tuple[str, ...], tuple[Evidence, ...]]:
    docs: list[str] = []
    evidence: list[Evidence] = []
    total_bytes = 0
    for rel_path in ENTRY_DOC_PATHS:
        if is_unsafe_path(rel_path):
            continue
        candidate = root / rel_path
        if not _safe_regular(root, candidate, limits):
            continue
        if classify_path(rel_path) is not None:
            continue
        raw = _read_bounded(candidate, limits)
        total_bytes += len(raw)
        if total_bytes > limits.total_document_bytes:
            raise LimitError(
                LIMIT_TOTAL_DOCUMENT_BYTES,
                f"resource limit exceeded: {LIMIT_TOTAL_DOCUMENT_BYTES} "
                f"(limit={limits.total_document_bytes}, actual={total_bytes})",
                limit="total_document_bytes",
                limit_value=limits.total_document_bytes,
            )
        docs.append(rel_path)
        evidence.append(
            Evidence(kind=KIND_DOCUMENT, path=rel_path, sha256=hashlib.sha256(raw).hexdigest())
        )
    if len(docs) > limits.documents:
        raise LimitError(
            LIMIT_DOCUMENTS,
            f"resource limit exceeded: {LIMIT_DOCUMENTS} "
            f"(limit={limits.documents}, actual={len(docs)})",
            limit="documents",
            limit_value=limits.documents,
        )
    return tuple(docs), tuple(evidence)


__all__ = [
    "ENTRY_DOC_PATHS",
    "KIND_BUILD_FILE",
    "KIND_DIRECTORY_NAME",
    "KIND_DOCUMENT",
    "KIND_GIT_REMOTE",
    "KIND_LICENSE_FILE",
    "LICENSE_FILENAMES",
    "DiscoveryError",
    "DiscoveryResult",
    "Evidence",
    "discover",
    "sanitize_remote_url",
]
