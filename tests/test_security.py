"""Focused tests for the v0.2 high-confidence sensitive-content policy.

Covers detection of private-key, credential-URL, and known-token material;
sensitive-file classification for discovery; the ``CODE=REASON`` security
override discipline; hard-block rules; and the no-leak / false-positive
resistance guarantees.
"""

from __future__ import annotations

from beacon.core.security import (
    ALL_SECURITY_CODES,
    CONTEXT_DISCOVERY,
    CONTEXT_EXPORT,
    CONTEXT_GIT_REMOTE,
    CONTEXT_PROCESS_ENV,
    HARD_BLOCKED_CODES,
    MAX_OVERRIDE_REASON_LENGTH,
    MIN_OVERRIDE_REASON_LENGTH,
    OVERRIDEABLE_SECURITY_CODES,
    SEC_DUPLICATE,
    SEC_HARD_BLOCKED,
    SEC_MALFORMED,
    SEC_REASON_EMPTY,
    SEC_REASON_LONG,
    SEC_REASON_SHORT,
    SEC_UNKNOWN_CODE,
    SENSITIVE_CREDENTIAL_URL,
    SENSITIVE_FILE_EXCLUDED,
    SENSITIVE_KNOWN_TOKEN,
    SENSITIVE_PRIVATE_KEY,
    SecurityFinding,
    SecurityOverride,
    SecurityOverrideError,
    classify_path,
    detect_sensitive_text,
    is_hard_blocked,
    is_known_sensitive_path,
    parse_security_override,
    parse_security_overrides,
    resolve_security_overrides,
)

LONG_REASON = "Because the values are example placeholders in fixtures."
GITHUB_TOKEN = "ghp_" + "A" * 36
OPENAI_LOOKING = "sk-" + "B" * 40  # must NOT be flagged (no fixed length prefix)


# ---------------------------------------------------------------------------
# Private-key detection
# ---------------------------------------------------------------------------


def test_detects_pem_private_key() -> None:
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA1NVdgV8HbF6E\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    findings = detect_sensitive_text(text, path="keys/server.pem")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.code == SENSITIVE_PRIVATE_KEY
    assert finding.path == "keys/server.pem"
    assert finding.line == 1
    assert finding.blocked is True


def test_detects_openssh_private_key() -> None:
    text = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n"
    findings = detect_sensitive_text(text, path=".ssh/id_ed25519")
    assert [f.code for f in findings] == [SENSITIVE_PRIVATE_KEY]
    assert findings[0].line == 1


def test_detects_encrypted_and_bare_private_key() -> None:
    for header in ("-----BEGIN ENCRYPTED PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----"):
        text = f"{header}\nabc\n-----END PRIVATE KEY-----\n"
        findings = detect_sensitive_text(text)
        assert [f.code for f in findings] == [SENSITIVE_PRIVATE_KEY], header


def test_header_without_footer_is_not_flagged() -> None:
    # Truncated paste: header alone is not a high-confidence private key.
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n"
    assert detect_sensitive_text(text) == ()


def test_public_key_not_flagged() -> None:
    text = "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----\n"
    assert detect_sensitive_text(text) == ()


def test_certificate_not_flagged_as_private_key() -> None:
    text = "-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----\n"
    assert detect_sensitive_text(text) == ()


def test_private_key_footer_on_any_line_counts() -> None:
    text = "intro\n-----BEGIN EC PRIVATE KEY-----\nbody\n-----END EC PRIVATE KEY-----\n"
    findings = detect_sensitive_text(text)
    assert [f.code for f in findings] == [SENSITIVE_PRIVATE_KEY]
    assert findings[0].line == 2


# ---------------------------------------------------------------------------
# Credential-bearing URL detection
# ---------------------------------------------------------------------------


def test_detects_non_placeholder_credential_url() -> None:
    text = "push to https://alice:s3cr3t@example.com/repo.git"
    findings = detect_sensitive_text(text, path="deploy.sh")
    assert [f.code for f in findings] == [SENSITIVE_CREDENTIAL_URL]
    finding = findings[0]
    assert finding.path == "deploy.sh"
    assert finding.line == 1


def test_detects_credential_url_on_non_first_line() -> None:
    text = "line one\nendpoint = https://user-x:pa55w0rd@api.example.com/v1\n"
    findings = detect_sensitive_text(text)
    assert [f.code for f in findings] == [SENSITIVE_CREDENTIAL_URL]
    assert findings[0].line == 2


def test_url_without_userinfo_not_flagged() -> None:
    text = "https://example.com/repo.git"
    assert detect_sensitive_text(text) == ()


def test_url_with_bare_userinfo_not_flagged() -> None:
    # user@host (no password) is not a high-confidence credential form.
    text = "https://git@example.com/repo.git"
    assert detect_sensitive_text(text) == ()


def test_placeholder_userinfo_not_flagged() -> None:
    for url in (
        "https://user:password@example.com",
        "https://username:yourpassword@example.com",
        "https://user:changeme@example.com",
        "https://demo:sample@example.com",
        "https://example:123456@example.com",
        "https://user:xxx@example.com",
        "https://user:********@example.com",
    ):
        assert detect_sensitive_text(url) == (), url


def test_placeholder_password_only_ignores() -> None:
    # User is real but the password is clearly a placeholder -> benign.
    text = "https://alice:yourpassword@example.com"
    assert detect_sensitive_text(text) == ()


# ---------------------------------------------------------------------------
# Known-token detection (conservative)
# ---------------------------------------------------------------------------


def test_detects_github_token() -> None:
    findings = detect_sensitive_text("token=" + GITHUB_TOKEN, path="config")
    assert [f.code for f in findings] == [SENSITIVE_KNOWN_TOKEN]
    assert findings[0].path == "config"
    assert findings[0].line == 1


def test_detects_known_provider_prefixes() -> None:
    samples = [
        "xoxb-" + "C" * 24,
        "xoxp-" + "D" * 24,
        "glpat-" + "E" * 16,
        "npm_" + "F" * 30,
        "AIza" + "G" * 30,
        "AKIA" + "H" * 16,
        "github_pat_" + "I" * 30,
    ]
    for token in samples:
        assert detect_sensitive_text(f"token={token}")[0].code == SENSITIVE_KNOWN_TOKEN, token


def test_short_token_after_prefix_not_flagged() -> None:
    # Strong prefix but too short to be a real token -> false-positive resistant.
    text = "ghp_short"
    assert detect_sensitive_text(text) == ()


def test_token_embedded_in_longer_identifier_not_flagged() -> None:
    # Lookbehind boundary: prefix must not be part of a longer identifier.
    text = "user_ghp_" + "A" * 36 + "_suffix"
    assert detect_sensitive_text(text) == ()


def test_broad_sk_string_not_flagged() -> None:
    # Generic short-prefix secrets must not trigger known-token detection.
    findings = detect_sensitive_text(OPENAI_LOOKING)
    assert [f.code for f in findings] == []


def test_generic_jwt_looking_string_not_flagged() -> None:
    # JWT-looking values carry no strong fixed provider prefix -> allowed.
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    assert detect_sensitive_text(jwt) == ()


def test_generic_hex_string_not_flagged() -> None:
    # 40-char hex (Heroku-like) has no strong fixed prefix -> allowed.
    hex_value = "a" * 40
    assert detect_sensitive_text(hex_value) == ()


def test_pypi_upload_token_detected() -> None:
    token = "pypi-AgEIcHlwaS5vcmc" + "J" * 40
    assert detect_sensitive_text(f"token={token}")[0].code == SENSITIVE_KNOWN_TOKEN


def test_multiple_detector_classes_on_one_line() -> None:
    text = f"BEGIN secret {GITHUB_TOKEN} then https://alice:s3cr3t@h"
    # Header without footer won't fire; expect both known-token and credential-URL.
    assert GITHUB_TOKEN in text
    findings = detect_sensitive_text(text)
    codes = {f.code for f in findings}
    assert codes == {SENSITIVE_KNOWN_TOKEN, SENSITIVE_CREDENTIAL_URL}


# ---------------------------------------------------------------------------
# Sensitive-file classification for discovery
# ---------------------------------------------------------------------------


def test_classifies_known_sensitive_files() -> None:
    for path in (
        ".env",
        ".env.local",
        ".env.production",
        ".netrc",
        "_netrc",
        ".git-credentials",
        "id_rsa",
        ".ssh/id_rsa",
        "config/id_ed25519",
        "keys/server.pem",
        "credentials.json",
        ".aws/credentials",
        "service-account.json",
    ):
        finding = classify_path(path)
        assert finding is not None, path
        assert finding.code == SENSITIVE_FILE_EXCLUDED
        assert finding.line is None
        assert finding.blocked is True


def test_classify_path_is_path_only_no_content() -> None:
    finding = classify_path(".env")
    assert finding is not None
    assert finding.code == SENSITIVE_FILE_EXCLUDED
    # No matched value field exists on a finding at all.
    assert "path" in finding.__dataclass_fields__


def test_classify_paths_that_are_not_sensitive() -> None:
    for path in (
        "README.md",
        "src/app.py",
        "docs/guide.md",
        "config/settings.yaml",
        ".gitignore",
        "id_rsa.pub",  # public key is not sensitive
        "credentials.example",  # example not real credentials store
    ):
        assert classify_path(path) is None, path
        assert is_known_sensitive_path(path) is False, path


def test_normalizes_paths_for_classification() -> None:
    finding = classify_path(".\\config\\.env.local")
    assert finding is not None
    assert finding.path == "config/.env.local"


def test_sensitive_filename_matching_is_case_insensitive() -> None:
    for path in (
        ".ENV",
        ".Env.Local",
        "ID_RSA",
        ".SSH/ID_RSA",
        "KEYS/SERVER.PEM",
        "CREDENTIALS.JSON",
        ".AWS/CREDENTIALS",
    ):
        finding = classify_path(path)
        assert finding is not None, path
        assert finding.code == SENSITIVE_FILE_EXCLUDED
        # The normalized path preserves the original case and separators.
        assert finding.path == path.replace("\\", "/")


def test_sensitive_file_excluded_is_hard_blocked() -> None:
    assert SENSITIVE_FILE_EXCLUDED in HARD_BLOCKED_CODES
    for context in (CONTEXT_EXPORT, CONTEXT_DISCOVERY):
        assert is_hard_blocked(SENSITIVE_FILE_EXCLUDED, context=context) is True


# ---------------------------------------------------------------------------
# Override discipline — every rejection path
# ---------------------------------------------------------------------------


def _assert_override_error(raw: str, code: str) -> None:
    try:
        parse_security_override(raw)
    except SecurityOverrideError as exc:
        assert exc.code == code
    else:  # pragma: no cover - failure reporting
        raise AssertionError(f"expected {code} for {raw!r}")


def test_override_malformed_empty() -> None:
    _assert_override_error("", SEC_MALFORMED)


def test_override_malformed_missing_equals() -> None:
    _assert_override_error(SENSITIVE_KNOWN_TOKEN, SEC_MALFORMED)


def test_override_malformed_empty_code() -> None:
    _assert_override_error(f"= {LONG_REASON}", SEC_MALFORMED)


def test_override_unknown_code() -> None:
    _assert_override_error(f"bogus_code={LONG_REASON}", SEC_UNKNOWN_CODE)


def test_override_hard_blocked_code_rejected() -> None:
    _assert_override_error(f"{SENSITIVE_FILE_EXCLUDED}={LONG_REASON}", SEC_HARD_BLOCKED)


def test_override_unallowlisted_code_rejected() -> None:
    # sensitive_file_excluded is the only non-overrideable code in v0.2.
    non_overrideable = ALL_SECURITY_CODES - OVERRIDEABLE_SECURITY_CODES
    assert non_overrideable == HARD_BLOCKED_CODES == {SENSITIVE_FILE_EXCLUDED}
    _assert_override_error(f"{SENSITIVE_FILE_EXCLUDED}={LONG_REASON}", SEC_HARD_BLOCKED)


def test_override_empty_reason() -> None:
    _assert_override_error(f"{SENSITIVE_KNOWN_TOKEN}=", SEC_REASON_EMPTY)
    _assert_override_error(f"{SENSITIVE_KNOWN_TOKEN}=   ", SEC_REASON_EMPTY)


def test_override_reason_too_short() -> None:
    _assert_override_error(f"{SENSITIVE_KNOWN_TOKEN}=too short", SEC_REASON_SHORT)


def test_override_reason_too_long() -> None:
    _assert_override_error(
        f"{SENSITIVE_KNOWN_TOKEN}={'x' * (MAX_OVERRIDE_REASON_LENGTH + 1)}",
        SEC_REASON_LONG,
    )


def test_override_duplicate_detected_via_collection() -> None:
    try:
        parse_security_overrides(
            [
                f"{SENSITIVE_KNOWN_TOKEN}=first reason text here",
                f"{SENSITIVE_CREDENTIAL_URL}=second reason text",
                f"{SENSITIVE_KNOWN_TOKEN}=third reason text",
            ]
        )
    except SecurityOverrideError as exc:
        assert exc.code == SEC_DUPLICATE
    else:  # pragma: no cover - failure reporting
        raise AssertionError("expected SEC_DUPLICATE")


def test_override_parses_and_trims_valid() -> None:
    override = parse_security_override(f"  {SENSITIVE_KNOWN_TOKEN} =   {LONG_REASON}  ")
    assert override == SecurityOverride(code=SENSITIVE_KNOWN_TOKEN, reason=LONG_REASON)


def test_override_reason_exactly_minimum_length_ok() -> None:
    override = parse_security_override(f"{SENSITIVE_KNOWN_TOKEN}=1234567890")
    assert len(override.reason) == MIN_OVERRIDE_REASON_LENGTH == 10


def test_only_overrideable_codes_parse() -> None:
    for code in ALL_SECURITY_CODES:
        if code in OVERRIDEABLE_SECURITY_CODES:
            parse_security_override(f"{code}={LONG_REASON}")
        else:
            _assert_override_error(f"{code}={LONG_REASON}", SEC_HARD_BLOCKED)


# ---------------------------------------------------------------------------
# Hard-block rules and override resolution
# ---------------------------------------------------------------------------


def _url_finding() -> SecurityFinding:
    return SecurityFinding(code=SENSITIVE_CREDENTIAL_URL, path="deploy.sh", line=1)


def test_credential_url_hard_blocked_in_git_remote_context() -> None:
    assert is_hard_blocked(SENSITIVE_CREDENTIAL_URL, context=CONTEXT_GIT_REMOTE) is True


def test_credential_url_overrideable_in_export_context() -> None:
    assert is_hard_blocked(SENSITIVE_CREDENTIAL_URL, context=CONTEXT_EXPORT) is False


def test_process_env_always_hard_blocked() -> None:
    for code in OVERRIDEABLE_SECURITY_CODES:
        assert is_hard_blocked(code, context=CONTEXT_PROCESS_ENV) is True


def test_unknown_context_rejected() -> None:
    try:
        is_hard_blocked(SENSITIVE_KNOWN_TOKEN, context="bogus")
    except ValueError:
        pass
    else:  # pragma: no cover - failure reporting
        raise AssertionError("expected ValueError for unknown context")


def test_override_unblocks_overrideable_finding_in_export() -> None:
    findings = detect_sensitive_text(f"token={GITHUB_TOKEN}", path="config")
    overrides = parse_security_overrides([f"{SENSITIVE_KNOWN_TOKEN}={LONG_REASON}"])
    result = resolve_security_overrides(findings, overrides, context=CONTEXT_EXPORT)
    assert result.allowed()
    assert result.blocked == ()
    assert len(result.overridden) == 1
    assert result.overridden[0][1].reason == LONG_REASON


def test_hard_blocked_file_cannot_be_overridden() -> None:
    finding = classify_path(".env")
    assert finding is not None
    try:
        parse_security_overrides([f"{SENSITIVE_FILE_EXCLUDED}={LONG_REASON}"])
    except SecurityOverrideError:
        pass
    else:  # pragma: no cover - failure reporting
        raise AssertionError("hard-blocked code must not parse as an override")


def test_credential_url_git_remote_cannot_be_overridden() -> None:
    findings = detect_sensitive_text("https://alice:s3cr3t@example.com/x.git")
    overrides = parse_security_overrides([f"{SENSITIVE_CREDENTIAL_URL}={LONG_REASON}"])
    result = resolve_security_overrides(findings, overrides, context=CONTEXT_GIT_REMOTE)
    assert result.allowed() is False
    assert [f.code for f in result.blocked] == [SENSITIVE_CREDENTIAL_URL]


def test_override_does_not_apply_to_process_env() -> None:
    findings = detect_sensitive_text(f"SECRET={GITHUB_TOKEN}", path="env")
    overrides = parse_security_overrides([f"{SENSITIVE_KNOWN_TOKEN}={LONG_REASON}"])
    result = resolve_security_overrides(findings, overrides, context=CONTEXT_PROCESS_ENV)
    assert result.allowed() is False
    assert len(result.blocked) == 1


def test_unoverridden_finding_stays_blocked() -> None:
    findings = detect_sensitive_text(f"token={GITHUB_TOKEN}", path="config")
    result = resolve_security_overrides(findings, (), context=CONTEXT_EXPORT)
    assert result.allowed() is False
    assert [f.code for f in result.blocked] == [SENSITIVE_KNOWN_TOKEN]


def test_resolve_revalidates_direct_override_objects() -> None:
    findings = detect_sensitive_text(f"token={GITHUB_TOKEN}", path="config")
    override = SecurityOverride(SENSITIVE_KNOWN_TOKEN, LONG_REASON)
    # Duplicate direct overrides are re-validated and rejected by raising.
    try:
        resolve_security_overrides(findings, [override, override], context=CONTEXT_EXPORT)
    except SecurityOverrideError as exc:
        assert exc.code == SEC_DUPLICATE
    else:  # pragma: no cover - failure reporting
        raise AssertionError("duplicate direct override must raise SEC_DUPLICATE")
    try:
        resolve_security_overrides(
            findings,
            [SecurityOverride(SENSITIVE_FILE_EXCLUDED, LONG_REASON)],
            context=CONTEXT_EXPORT,
        )
    except SecurityOverrideError as exc:
        assert exc.code == SEC_HARD_BLOCKED
    else:  # pragma: no cover - failure reporting
        raise AssertionError("hard-blocked direct override must be rejected")


def test_override_preserves_finding_metadata() -> None:
    findings = detect_sensitive_text(f"token={GITHUB_TOKEN}", path="config")
    original = findings[0]
    overrides = parse_security_overrides([f"{SENSITIVE_KNOWN_TOKEN}={LONG_REASON}"])
    result = resolve_security_overrides(findings, overrides, context=CONTEXT_EXPORT)
    (overridden_finding, _) = result.overridden[0]
    assert overridden_finding is original
    assert overridden_finding.code == SENSITIVE_KNOWN_TOKEN
    assert overridden_finding.path == "config"
    assert overridden_finding.line == 1


# ---------------------------------------------------------------------------
# No-leak guarantees
# ---------------------------------------------------------------------------


def test_finding_never_contains_matched_value() -> None:
    secret = "s3cr3t-password-value"
    text = f"https://alice:{secret}@example.com"
    findings = detect_sensitive_text(text, path="urls.txt")
    for finding in findings:
        assert secret not in repr(finding)
        assert secret not in str(finding)
    # The dataclass exposes only metadata fields.
    assert set(SecurityFinding.__dataclass_fields__) == {
        "code",
        "path",
        "line",
        "blocked",
    }


def test_detect_errors_do_not_leak_text() -> None:
    try:
        detect_sensitive_text(12345)  # type: ignore[arg-type]
    except TypeError as exc:
        assert "str" in str(exc)
        assert "12345" not in str(exc)
    else:  # pragma: no cover - failure reporting
        raise AssertionError("expected TypeError")


def test_override_errors_do_not_leak_reason() -> None:
    try:
        parse_security_override(f"{SENSITIVE_KNOWN_TOKEN}=short")
    except SecurityOverrideError as exc:
        # Error mentions the stable code, never the (truncated) reason value.
        assert SENSITIVE_KNOWN_TOKEN in str(exc)
        assert "short" not in str(exc)
    else:  # pragma: no cover - failure reporting
        raise AssertionError("expected SEC_REASON_SHORT")


def test_repr_of_override_leaks_reason_only() -> None:
    # The override reason is intended for human reporting, not a secret.
    override = SecurityOverride(SENSITIVE_KNOWN_TOKEN, LONG_REASON)
    assert "reason=" in repr(override)
    assert "=" in str(override)


def test_finding_blocked_flag_and_code_are_safe() -> None:
    finding = SecurityFinding(SENSITIVE_PRIVATE_KEY, path="k.pem", line=3)
    assert finding.blocked is True
    assert finding.code == SENSITIVE_PRIVATE_KEY
