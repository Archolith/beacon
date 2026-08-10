"""High-confidence sensitive-content detection and security overrides for Beacon.

This module implements the v0.2 secret-safety backstop (addendum §6) as pure,
deterministic, dependency-free logic. It is deliberately *not* a general secret
scanner: it only reports bounded, high-confidence classes that carry strong fixed
structural signals:

* private-key material (PEM/OpenSSH ``BEGIN ... PRIVATE KEY`` blocks),
* credential-bearing URLs with a non-placeholder ``user:password@`` userinfo, and
* known provider token formats with a strong fixed prefix plus length/charset.

It also classifies known sensitive file paths for discovery (``.env``, private
keys, credentials, netrc-style files).

Critical invariant: a :class:`SecurityFinding` stores only metadata — the stable
``code``, the relative ``path``, an optional 1-based ``line``, and a ``blocked``
flag. It never stores the matched value, and neither findings nor the errors and
``repr`` emitted here echo a matched value or surrounding secret context.

Overrides follow the same ``CODE=REASON`` discipline as
:class:`beacon.core.policy.Acknowledgement` (trimmed, non-empty, at least 10
characters; unknown, duplicate, malformed, or unallowlisted inputs rejected with a
stable code). Hard-block classes cannot be overridden: credential-bearing git
remotes during init, path escapes (``unsafe_canonical_path`` is outside this
module and therefore never overridable here), private-key files selected by
discovery, and Beacon's own process environment.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

#: Stable diagnostic code: PEM/OpenSSH private-key material.
SENSITIVE_PRIVATE_KEY = "sensitive_private_key"

#: Stable diagnostic code: credential-bearing URL with non-placeholder userinfo.
SENSITIVE_CREDENTIAL_URL = "sensitive_credential_url"

#: Stable diagnostic code: known provider token prefix/structure.
# This is a public diagnostic code string, not a credential value.
SENSITIVE_KNOWN_TOKEN = "sensitive_known_token"  # nosec B105

#: Stable diagnostic code: known sensitive file excluded from discovery.
SENSITIVE_FILE_EXCLUDED = "sensitive_file_excluded"

#: Every stable sensitive code emitted by this module.
ALL_SECURITY_CODES = frozenset(
    {
        SENSITIVE_PRIVATE_KEY,
        SENSITIVE_CREDENTIAL_URL,
        SENSITIVE_KNOWN_TOKEN,
        SENSITIVE_FILE_EXCLUDED,
    }
)

#: Sensitive codes an exceptional export may override.
OVERRIDEABLE_SECURITY_CODES = frozenset(
    {SENSITIVE_CREDENTIAL_URL, SENSITIVE_KNOWN_TOKEN, SENSITIVE_PRIVATE_KEY}
)

#: Sensitive codes that are never overrideable (always hard-blocked).
HARD_BLOCKED_CODES = frozenset({SENSITIVE_FILE_EXCLUDED})

#: Minimum length of a security-override reason (after trimming).
MIN_OVERRIDE_REASON_LENGTH = 10
MAX_OVERRIDE_REASON_LENGTH = 1024

#: Context for a text/body scan during export.
CONTEXT_EXPORT = "export"

#: Context for discovery of candidate canonical files.
CONTEXT_DISCOVERY = "discovery"

#: Context for credential-bearing git remotes read during init.
CONTEXT_GIT_REMOTE = "git_remote"

#: Context for Beacon's own process environment.
CONTEXT_PROCESS_ENV = "process_env"

#: All recognised security-override contexts.
ALL_CONTEXTS = frozenset(
    {CONTEXT_EXPORT, CONTEXT_DISCOVERY, CONTEXT_GIT_REMOTE, CONTEXT_PROCESS_ENV}
)

# Stable security-override error codes (input/user errors).
SEC_MALFORMED = "security_override_malformed"
SEC_UNKNOWN_CODE = "security_override_unknown_code"
SEC_UNALLOWLISTED_CODE = "security_override_unallowlisted_code"
SEC_DUPLICATE = "security_override_duplicate"
SEC_REASON_EMPTY = "security_override_reason_empty"
SEC_REASON_SHORT = "security_override_reason_short"
SEC_REASON_LONG = "security_override_reason_long"
SEC_HARD_BLOCKED = "security_override_hard_blocked"

# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

# PEM/OpenSSH private-key block delimiters. The optional prefix group covers
# "RSA ", "EC ", "DSA ", "OPENSSH ", "ENCRYPTED " and bare "PRIVATE KEY".
_PRIVATE_KEY_HEADER = re.compile(r"^-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----$")
_PRIVATE_KEY_FOOTER = re.compile(r"^-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----$")

# scheme://user:pass@host — userinfo with a colon. Password excludes '/', '@',
# whitespace, and ':' so a second ':' does not break the match.
_CREDENTIAL_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://([^/@\s:]+):([^/@\s]*)@")

# Known provider token prefixes plus the minimum run length of the token body
# that must follow the prefix. Order matters only for readability; the combined
# regex alternates longest prefixes first so longer, more specific prefixes win.
_TOKEN_PREFIX_SPECS: tuple[tuple[str, int], ...] = (
    ("github_pat_", 30),  # GitHub fine-grained PATs
    ("ghp_", 36),  # GitHub classic personal access tokens
    ("gho_", 36),  # GitHub OAuth tokens
    ("ghu_", 36),  # GitHub user-to-server tokens
    ("ghs_", 36),  # GitHub server-to-server tokens
    ("ghr_", 36),  # GitHub refresh tokens
    ("pypi-AgEIcHlwaS5vcmc", 40),  # PyPI upload tokens
    ("glpat-", 16),  # GitLab personal access tokens
    ("npm_", 30),  # npm access tokens
    ("AIza", 30),  # Google API keys
    ("AKIA", 16),  # AWS access key id (AKIA + 16)
    ("ASIA", 16),  # AWS temporary access key id (ASIA + 16)
    ("xoxb-", 24),  # Slack bot tokens
    ("xoxp-", 24),  # Slack user tokens
    ("xoxa-", 24),  # Slack app tokens
    ("xoxr-", 24),  # Slack refresh tokens
)

# Token body charset. '-' sits last so it is literal inside the character class.
_TOKEN_ALT_RE = re.compile(
    "|".join(
        rf"(?<![A-Za-z0-9_]){re.escape(prefix)}[A-Za-z0-9_-]{{{min_len},}}"
        for prefix, min_len in sorted(_TOKEN_PREFIX_SPECS, key=lambda spec: -len(spec[0]))
    )
)

# Placeholder user names / passwords that indicate an example, not a real secret.
_PLACEHOLDER_USER = re.compile(
    r"^(?:user|username|youruser|yourusername|login|demo|sample|example|changeme"
    r"|xxx|x|name|me)$",
    re.IGNORECASE,
)
_PLACEHOLDER_PASSWORD = re.compile(
    r"^(?:password|pass|yourpassword|yourpasswordhere|changeme|changemeplease"
    r"|secret|yoursecret|token|yourtoken|apikey|api_key|api-key|placeholder"
    r"|replaceme|example|demo|sample|123456|12345678|password123|letmein|qwerty"
    r"|xxx|x|XXXX|\*+)$",
    re.IGNORECASE,
)

# Known sensitive file names (exact) used by discovery classification.
_SENSITIVE_FILE_NAMES = frozenset(
    {
        ".env",
        ".netrc",
        "_netrc",
        ".git-credentials",
        ".htpasswd",
        ".pgpass",
        ".pypirc",
        ".npmrc",
        "credentials",
        "credentials.json",
        "service-account.json",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    }
)


@dataclass(frozen=True)
class SecurityFinding:
    """One high-confidence sensitive-content finding.

    Stores *only* metadata — ``code``, relative ``path``, optional 1-based
    ``line``, and ``blocked``. It never stores the matched value, so its
    ``repr`` and any serialization cannot leak secret content.
    """

    code: str
    path: str | None = None
    line: int | None = None
    blocked: bool = True

    def __post_init__(self) -> None:
        if self.code not in ALL_SECURITY_CODES:
            raise ValueError(f"unknown sensitive code: {self.code}")
        if self.line is not None and self.line < 1:
            raise ValueError("line must be a positive 1-based index")


@dataclass(frozen=True)
class SecurityOverride:
    """An explicit, reasoned override for one overrideable sensitive code."""

    code: str
    reason: str


@dataclass(frozen=True)
class SecurityOverrideResult:
    """Result of resolving a set of findings against security overrides.

    ``blocked`` holds findings that may not proceed (hard-blocked, or not
    covered by an override). ``overridden`` records each finding that an
    override permitted, alongside its override. Order is deterministic and
    matches the input finding order.
    """

    blocked: tuple[SecurityFinding, ...] = ()
    overridden: tuple[tuple[SecurityFinding, SecurityOverride], ...] = ()

    def allowed(self) -> bool:
        """True when nothing remains blocked after applying overrides."""
        return not self.blocked


class SecurityOverrideError(Exception):
    """Raised when a security override is malformed, unknown, duplicate,
    unallowlisted, hard-blocked, or has an invalid reason.

    ``code`` is a stable, non-secret diagnostic string.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _normalize_path(raw_path: str) -> str:
    """Normalize *raw_path* to a repository-relative, forward-slash path."""
    normalized = raw_path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def _is_placeholder_user(value: str) -> bool:
    return bool(_PLACEHOLDER_USER.fullmatch(value))


def _is_placeholder_password(value: str) -> bool:
    return bool(_PLACEHOLDER_PASSWORD.fullmatch(value))


def detect_sensitive_text(text: str, *, path: str | None = None) -> tuple[SecurityFinding, ...]:
    """Scan *text* for high-confidence sensitive content.

    Reports at most one finding per stable code per line, in deterministic
    order. ``path`` (when given) is a repository-relative forward-slash path
    attached to every finding; it is metadata, not matched content. Returns a
    tuple of :class:`SecurityFinding` objects that never include the matched
    value.
    """
    if not isinstance(text, str):
        raise TypeError("detect_sensitive_text expects a str")

    findings: list[SecurityFinding] = []
    lines = text.splitlines()
    has_private_key_footer = any(_PRIVATE_KEY_FOOTER.match(line) for line in lines)

    for index, line in enumerate(lines, start=1):
        if has_private_key_footer and _PRIVATE_KEY_HEADER.match(line):
            findings.append(
                SecurityFinding(code=SENSITIVE_PRIVATE_KEY, path=path, line=index, blocked=True)
            )
        for match in _CREDENTIAL_URL.finditer(line):
            user, password = match.group(1), match.group(2)
            if (
                user
                and password
                and not _is_placeholder_user(user)
                and not _is_placeholder_password(password)
            ):
                findings.append(
                    SecurityFinding(
                        code=SENSITIVE_CREDENTIAL_URL,
                        path=path,
                        line=index,
                        blocked=True,
                    )
                )
                break
        if _TOKEN_ALT_RE.search(line):
            findings.append(
                SecurityFinding(code=SENSITIVE_KNOWN_TOKEN, path=path, line=index, blocked=True)
            )
    return tuple(findings)


def is_known_sensitive_path(raw_path: str) -> bool:
    """Return True when *raw_path* names a known sensitive file type.

    Filename matching is case-insensitive (``.ENV``, ``ID_RSA``, ``.Env.Local``
    all match) so discovery is conservative regardless of case conventions.
    """
    normalized = _normalize_path(raw_path)
    if not normalized or normalized == ".":
        return False
    name = normalized.rsplit("/", 1)[-1]
    name_lower = name.lower()
    if name_lower in _SENSITIVE_FILE_NAMES:
        return True
    if name_lower.startswith(".env."):
        return True
    if name_lower.endswith(".pem"):
        return True
    if name_lower.startswith(".secret") or name_lower.startswith("secrets."):
        return True
    if normalized.lower().startswith(".aws/") and name_lower == "credentials":
        return True
    return False


def classify_path(raw_path: str) -> SecurityFinding | None:
    """Classify *raw_path* as a known sensitive file for discovery.

    Returns a ``sensitive_file_excluded`` finding (blocked, no line) when
    *raw_path* is a known sensitive file, otherwise ``None``. Used by discovery
    so ``init`` never proposes such files as canonical documents.
    """
    if is_known_sensitive_path(raw_path):
        return SecurityFinding(
            code=SENSITIVE_FILE_EXCLUDED, path=_normalize_path(raw_path), blocked=True
        )
    return None


def is_hard_blocked(code: str, *, context: str) -> bool:
    """Return True when *code* may never be overridden in *context*.

    Hard-block rules:

    * ``sensitive_file_excluded`` is never overrideable (private-key files and
      known sensitive files selected by discovery);
    * nothing in Beacon's own process environment is overrideable;
    * a credential-bearing URL inside a git remote read during init is never
      overrideable.
    """
    if context not in ALL_CONTEXTS:
        raise ValueError(f"unknown security context: {context}")
    if code in HARD_BLOCKED_CODES:
        return True
    if context == CONTEXT_PROCESS_ENV:
        return True
    if context == CONTEXT_GIT_REMOTE and code == SENSITIVE_CREDENTIAL_URL:
        return True
    return False


def parse_security_override(raw: str) -> SecurityOverride:
    """Parse a single ``CODE=REASON`` string into a :class:`SecurityOverride`.

    Raises :class:`SecurityOverrideError` on malformed syntax, an unknown code,
    a hard-blocked code, an unallowlisted code, an empty reason, or a reason
    shorter than :data:`MIN_OVERRIDE_REASON_LENGTH`.
    """
    value = raw.strip()
    if not value or "=" not in value:
        raise SecurityOverrideError(SEC_MALFORMED, "security override must be in CODE=REASON form")
    code, _, reason = value.partition("=")
    code = code.strip()
    reason = reason.strip()
    if not code:
        raise SecurityOverrideError(SEC_MALFORMED, "security override code must not be empty")
    if code not in ALL_SECURITY_CODES:
        raise SecurityOverrideError(SEC_UNKNOWN_CODE, f"unknown security code: {code}")
    if code in HARD_BLOCKED_CODES:
        raise SecurityOverrideError(
            SEC_HARD_BLOCKED, f"security code is hard-blocked and cannot be overridden: {code}"
        )
    if code not in OVERRIDEABLE_SECURITY_CODES:
        raise SecurityOverrideError(
            SEC_UNALLOWLISTED_CODE, f"security code is not overrideable: {code}"
        )
    if not reason:
        raise SecurityOverrideError(
            SEC_REASON_EMPTY, f"security override reason for {code} must not be empty"
        )
    if len(reason) < MIN_OVERRIDE_REASON_LENGTH:
        raise SecurityOverrideError(
            SEC_REASON_SHORT,
            f"security override reason for {code} must be at least "
            f"{MIN_OVERRIDE_REASON_LENGTH} characters",
        )
    if len(reason) > MAX_OVERRIDE_REASON_LENGTH:
        raise SecurityOverrideError(
            SEC_REASON_LONG,
            f"security override reason for {code} must not exceed "
            f"{MAX_OVERRIDE_REASON_LENGTH} characters",
        )
    return SecurityOverride(code=code, reason=reason)


def parse_security_overrides(raws: Iterable[str]) -> tuple[SecurityOverride, ...]:
    """Parse a collection of ``CODE=REASON`` strings.

    Each item is validated by :func:`parse_security_override`; an override
    whose code was already accepted in the same collection is rejected as
    :data:`SEC_DUPLICATE`. Returned order matches input order.
    """
    seen: set[str] = set()
    parsed: list[SecurityOverride] = []
    for raw in raws:
        override = parse_security_override(raw)
        if override.code in seen:
            raise SecurityOverrideError(
                SEC_DUPLICATE, f"duplicate security override code: {override.code}"
            )
        seen.add(override.code)
        parsed.append(override)
    return tuple(parsed)


def resolve_security_overrides(
    findings: Iterable[SecurityFinding],
    overrides: Iterable[SecurityOverride],
    *,
    context: str,
) -> SecurityOverrideResult:
    """Apply *overrides* to *findings* within *context*.

    Overrides are re-validated (even when callers construct the frozen
    dataclass directly). A finding remains blocked when its code is
    hard-blocked in *context* or when no override covers it; otherwise it is
    recorded as overridden. The result preserves the input finding order.
    """
    validated = parse_security_overrides(f"{o.code}={o.reason}" for o in overrides)
    override_by_code = {o.code: o for o in validated}
    blocked: list[SecurityFinding] = []
    overridden: list[tuple[SecurityFinding, SecurityOverride]] = []
    for finding in findings:
        if is_hard_blocked(finding.code, context=context):
            blocked.append(finding)
            continue
        override = override_by_code.get(finding.code)
        if override is None:
            blocked.append(finding)
        else:
            overridden.append((finding, override))
    return SecurityOverrideResult(blocked=tuple(blocked), overridden=tuple(overridden))


__all__ = [
    "ALL_CONTEXTS",
    "ALL_SECURITY_CODES",
    "CONTEXT_DISCOVERY",
    "CONTEXT_EXPORT",
    "CONTEXT_GIT_REMOTE",
    "CONTEXT_PROCESS_ENV",
    "HARD_BLOCKED_CODES",
    "MIN_OVERRIDE_REASON_LENGTH",
    "MAX_OVERRIDE_REASON_LENGTH",
    "OVERRIDEABLE_SECURITY_CODES",
    "SEC_DUPLICATE",
    "SEC_HARD_BLOCKED",
    "SEC_MALFORMED",
    "SEC_REASON_EMPTY",
    "SEC_REASON_SHORT",
    "SEC_REASON_LONG",
    "SEC_UNALLOWLISTED_CODE",
    "SEC_UNKNOWN_CODE",
    "SENSITIVE_CREDENTIAL_URL",
    "SENSITIVE_FILE_EXCLUDED",
    "SENSITIVE_KNOWN_TOKEN",
    "SENSITIVE_PRIVATE_KEY",
    "SecurityFinding",
    "SecurityOverride",
    "SecurityOverrideError",
    "SecurityOverrideResult",
    "classify_path",
    "detect_sensitive_text",
    "is_hard_blocked",
    "is_known_sensitive_path",
    "parse_security_override",
    "parse_security_overrides",
    "resolve_security_overrides",
]
