"""Tests for core WP1 init: discovery, scaffold, and the init-report contract."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from beacon.core import scaffold as scaffold_mod
from beacon.core.discovery import (
    DiscoveryError,
    DiscoveryResult,
    discover,
    sanitize_remote_url,
)
from beacon.core.limits import LimitError, ResourceLimits
from beacon.core.loader import load_beacon_manifest
from beacon.core.paths import UnsafeCanonicalPath
from beacon.core.scaffold import (
    DEFAULT_MANIFEST_NAME,
    OPERATION_CREATE,
    OPERATION_DRY_RUN,
    OPERATION_REFUSED,
    OPERATION_REPLACE,
    REFUSED_NO_CANONICAL_DOC,
    REVIEW_CANONICAL_DOCS_MISSING,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    init,
    render_manifest_yaml,
    resolve_output_path,
    to_payload,
    write_report,
)
from beacon.core.validator import validate_beacon_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "beacon-init-report-1.0.schema.json"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "schemas"

SHA256_HEX = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


# ---------------------------------------------------------------------------
# Repo fixtures
# ---------------------------------------------------------------------------


def _repo(
    tmp_path: Path,
    *,
    name: str = "acme",
    docs: bool = True,
    license_: bool = True,
    py: bool = True,
    git_remote: str | None = None,
) -> Path:
    root = tmp_path / name
    root.mkdir()
    if docs:
        (root / "README.md").write_text("# Acme\n\nDocs.", encoding="utf-8")
    if license_:
        (root / "LICENSE").write_text("MIT License", encoding="utf-8")
    if py:
        (root / "pyproject.toml").write_text(
            '[project]\nname = "acme"\n\n[tool.pytest.ini_options]\n', encoding="utf-8"
        )
    if git_remote is not None:
        git_dir = root / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            f'[remote "origin"]\n\turl = {git_remote}\n', encoding="utf-8"
        )
    return root


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


def _schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def init_schema() -> dict:
    return _schema()


# ---------------------------------------------------------------------------
# Schema meta-validation and golden fixtures
# ---------------------------------------------------------------------------


def test_schema_is_valid_draft202012(init_schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(init_schema)


def test_positive_fixture_validates(init_schema: dict) -> None:
    with (FIXTURE_DIR / "init-report-valid.json").open(encoding="utf-8") as fh:
        payload = json.load(fh)
    jsonschema.validate(payload, init_schema)


def test_negative_fixture_fails(init_schema: dict) -> None:
    with (FIXTURE_DIR / "init-report-invalid.json").open(encoding="utf-8") as fh:
        payload = json.load(fh)
    errors = list(jsonschema.Draft202012Validator(init_schema).iter_errors(payload))
    assert errors, "expected the negative fixture to violate the schema"
    validators = {e.validator for e in errors}
    assert {"const", "enum", "type", "minItems", "minimum", "pattern"}.issubset(validators)


def test_discovered_value_is_literal_true(init_schema: dict) -> None:
    with (FIXTURE_DIR / "init-report-valid.json").open(encoding="utf-8") as fh:
        payload = json.load(fh)
    for field in payload["discovered"]:
        assert field["value"] is True


# ---------------------------------------------------------------------------
# Discovery: deterministic, name from directory, docs/license/language/build
# ---------------------------------------------------------------------------


def test_discovery_deterministic(tmp_path: Path) -> None:
    root = _repo(tmp_path, git_remote="https://github.com/acme/acme")
    first = discover(root)
    second = discover(root)
    assert first == second


def test_discovery_root_must_be_directory(tmp_path: Path) -> None:
    with pytest.raises(DiscoveryError):
        discover(tmp_path / "missing")


def test_discovery_basic_signals(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = discover(root)
    assert result.name == "acme"
    assert result.primary_language == "Python"
    assert result.license_name == "unknown"
    assert result.canonical_docs == ("README.md",)
    assert result.setup_command == "pip install -e ."
    assert result.test_command == "python -m pytest tests/ -x --tb=short"
    assert result.build_evidence is not None
    assert result.build_evidence.kind == "build_file"
    assert result.build_evidence.path == "pyproject.toml"
    assert result.security_findings == ()


def test_discovery_license_mapping(tmp_path: Path) -> None:
    root = _repo(tmp_path, license_=True)
    (root / "LICENSE").unlink()
    (root / "LICENSE-MIT").write_text("MIT", encoding="utf-8")
    assert discover(root).license_name == "MIT"


def test_python_without_pytest_has_no_test_command(tmp_path: Path) -> None:
    root = _repo(tmp_path, py=True)
    (root / "pyproject.toml").write_text('[project]\nname = "acme"\n', encoding="utf-8")
    result = discover(root)
    assert result.primary_language == "Python"
    assert result.setup_command == "pip install -e ."
    assert result.test_command is None


def test_package_json_without_lockfile_omits_commands(tmp_path: Path) -> None:
    root = _repo(tmp_path, py=False)
    (root / "package.json").write_text('{"scripts": {"test": "mocha"}}', encoding="utf-8")
    result = discover(root)
    assert result.primary_language == "JavaScript"
    assert result.setup_command is None
    assert result.test_command is None
    assert result.build_commands_unknown is True


def test_package_json_npm_lockfile(tmp_path: Path) -> None:
    root = _repo(tmp_path, py=False)
    (root / "package.json").write_text('{"scripts": {"test": "mocha"}}', encoding="utf-8")
    (root / "package-lock.json").write_text("{}", encoding="utf-8")
    result = discover(root)
    assert result.primary_language == "JavaScript"
    assert result.setup_command == "npm install"
    assert result.test_command == "npm test"
    assert result.build_commands_unknown is False


def test_package_json_pnpm_and_yarn(tmp_path: Path) -> None:
    pnpm = _repo(tmp_path, name="p", py=False)
    (pnpm / "package.json").write_text('{"scripts": {"test": "vitest"}}', encoding="utf-8")
    (pnpm / "pnpm-lock.yaml").write_text("lockfileVersion: '6.0'\n", encoding="utf-8")
    r = discover(pnpm)
    assert r.setup_command == "pnpm install"
    assert r.test_command == "pnpm test"

    yarn = _repo(tmp_path, name="y", py=False)
    (yarn / "package.json").write_text('{"scripts": {"test": "jest"}}', encoding="utf-8")
    (yarn / "yarn.lock").write_text("# yarn lockfile\n", encoding="utf-8")
    r2 = discover(yarn)
    assert r2.setup_command == "yarn install"
    assert r2.test_command == "yarn test"


def test_package_json_multiple_lockfiles_ambiguous(tmp_path: Path) -> None:
    root = _repo(tmp_path, py=False)
    (root / "package.json").write_text('{"scripts": {"test": "mocha"}}', encoding="utf-8")
    (root / "package-lock.json").write_text("{}", encoding="utf-8")
    (root / "yarn.lock").write_text("# yarn\n", encoding="utf-8")
    result = discover(root)
    assert result.primary_language == "JavaScript"
    assert result.setup_command is None
    assert result.test_command is None
    assert result.build_commands_unknown is True


def test_package_json_no_test_script_omits_test(tmp_path: Path) -> None:
    root = _repo(tmp_path, py=False)
    (root / "package.json").write_text('{"name": "x"}', encoding="utf-8")
    (root / "package-lock.json").write_text("{}", encoding="utf-8")
    result = discover(root)
    assert result.setup_command == "npm install"
    assert result.test_command is None
    assert result.build_commands_unknown is False


def test_cargo_and_go(tmp_path: Path) -> None:
    cargo = _repo(tmp_path, name="c", py=False)
    (cargo / "Cargo.toml").write_text("[package]\nname = 'c'\n", encoding="utf-8")
    r = discover(cargo)
    assert r.primary_language == "Rust"
    assert r.test_command == "cargo test"

    go = _repo(tmp_path, name="g", py=False)
    (go / "go.mod").write_text("module example/g\n", encoding="utf-8")
    r2 = discover(go)
    assert r2.primary_language == "Go"
    assert r2.test_command == "go test ./..."


def test_doc_evidence_sha256(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = discover(root)
    assert len(result.doc_evidence) == 1
    assert result.doc_evidence[0].kind == "document"
    assert result.doc_evidence[0].path == "README.md"
    assert len(result.doc_evidence[0].sha256 or "") == 64


def test_no_allowlisted_doc(tmp_path: Path) -> None:
    root = _repo(tmp_path, docs=False)
    assert discover(root).canonical_docs == ()


# ---------------------------------------------------------------------------
# Git remote sanitization (no credential leak, SCP conversion)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_url", "has_finding"),
    [
        ("https://github.com/acme/acme.git", "https://github.com/acme/acme.git", False),
        ("git@github.com:acme/acme.git", "https://github.com/acme/acme.git", False),
        ("git@gitlab.com:/group/repo", "https://gitlab.com/group/repo", False),
        ("https://alice:hunter2@github.com/acme/acme", "https://github.com/acme/acme", True),
        ("ssh://git@github.com/acme/acme.git", "https://github.com/acme/acme.git", False),
        ("git://github.com/acme/acme.git", "https://github.com/acme/acme.git", False),
        ("/abs/local/path", None, False),
        ("https://demo:demo@github.com/acme/acme", "https://github.com/acme/acme", False),
        ("https://user:password@github.com/acme/acme", "https://github.com/acme/acme", False),
    ],
)
def test_sanitize_remote_url(raw: str, expected_url: str | None, has_finding: bool) -> None:
    url, findings = sanitize_remote_url(raw)
    assert url == expected_url
    assert bool(findings) is has_finding
    if has_finding:
        assert findings[0].blocked is False


def test_credential_remote_reported_in_discovery(tmp_path: Path) -> None:
    root = _repo(tmp_path, git_remote="https://user:sekrit@github.com/acme/acme")
    result = discover(root)
    assert result.repository == "https://github.com/acme/acme"
    assert "sekrit" not in (result.repository or "")
    assert len(result.security_findings) == 1
    assert result.security_findings[0].code == "sensitive_credential_url"
    assert result.security_findings[0].blocked is False


def test_token_only_userinfo_flagged_and_stripped() -> None:
    url, findings = sanitize_remote_url("https://secret_token@github.com/acme/acme")
    assert url == "https://github.com/acme/acme"
    assert "secret_token" not in (url or "")
    assert len(findings) == 1
    assert findings[0].code == "sensitive_credential_url"
    assert findings[0].blocked is False


def test_remote_drops_query_and_fragment() -> None:
    url, findings = sanitize_remote_url("https://github.com/acme/acme?token=abc#section")
    assert url == "https://github.com/acme/acme"
    assert "token=abc" not in (url or "")
    assert findings == ()


def test_remote_empty_host_rejected() -> None:
    url, _ = sanitize_remote_url("https://@")
    assert url is None
    url2, _ = sanitize_remote_url("https:///path")
    assert url2 is None or not url2.startswith("https:///")


@pytest.mark.parametrize(
    "bad_remote",
    [
        "https://in valid.com/x",  # whitespace in host
        "https://example.com:abc/x",  # malformed (non-numeric) port
        "https://example.com:99999/x",  # out-of-range port
        "https://example..com/x",  # empty label
        "https://-bad.example/x",  # leading hyphen label
        "https://exa mple.com/x",  # interior space
        "https://:8080/x",  # empty host with port
        "https://[not-an-ipv6]/x",  # malformed IPv6 literal
        "https://exa\u0007mple.com/x",  # control char in host
    ],
)
def test_invalid_remote_hosts_rejected(bad_remote: str) -> None:
    url, _ = sanitize_remote_url(bad_remote)
    assert url is None
    # raw remote must never appear in any result
    assert bad_remote.split("://")[1].split("/")[0] not in str(url)


def test_ipv6_and_dns_literals_accepted() -> None:
    url, findings = sanitize_remote_url("https://[2001:db8::1]/repo")
    assert url == "https://[2001:db8::1]/repo"
    assert findings == ()
    url2, _ = sanitize_remote_url("https://192.168.0.1:8443/repo")
    assert url2 == "https://192.168.0.1:8443/repo"
    url3, _ = sanitize_remote_url("https://localhost/repo")
    assert url3 == "https://localhost/repo"


def test_scp_host_validated() -> None:
    url, _ = sanitize_remote_url("git@bad host:repo.git")
    assert url is None
    url2, _ = sanitize_remote_url("git@[2001:db8::1]:repo.git")
    # SCP-style regex does not accept a bracketed IPv6 (no colon in host group),
    # so it is refused rather than mis-parsed.
    assert url2 is None


def test_symlinked_parent_escape_not_discovered(tmp_path: Path) -> None:
    root = _repo(tmp_path, docs=False, license_=False, py=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "README.md").write_text("secret", encoding="utf-8")
    agent = root / ".agent"
    try:
        agent.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    result = discover(root)
    assert ".agent/README.md" not in result.canonical_docs
    assert result.canonical_docs == ()


def test_path_bytes_limit_raises(tmp_path: Path) -> None:
    root = _repo(tmp_path)  # README.md + pyproject.toml present
    with pytest.raises(LimitError):
        discover(root, limits=ResourceLimits(path_bytes=3))


def test_absent_long_candidates_do_not_fail_discovery(tmp_path: Path) -> None:
    # Only README.md is present. A custom path_bytes admitting README.md (9
    # bytes) but shorter than the absent CONTRIBUTING.md/.agent paths must not
    # fail discovery -- absent fixed candidates are simply skipped.
    root = _repo(tmp_path, py=False, license_=False)
    result = discover(root, limits=ResourceLimits(path_bytes=10))
    assert result.canonical_docs == ("README.md",)


def test_manifest_path_bytes_refused_no_artifact(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    long_name = "m" * 100 + ".yaml"
    with pytest.raises(LimitError):
        init(root, manifest_path=long_name, limits=ResourceLimits(path_bytes=10))
    assert not (root / long_name).exists()
    assert [p for p in root.rglob("*.tmp")] == []


def test_no_doc_overlong_manifest_path_refused(tmp_path: Path) -> None:
    # Even without a canonical doc, the manifest target must be validated: an
    # over-long path fails closed with LimitError and leaves no artifact.
    root = _repo(tmp_path, docs=False, license_=False, py=False)
    long_name = "m" * 100 + ".yaml"
    with pytest.raises(LimitError):
        init(root, manifest_path=long_name, limits=ResourceLimits(path_bytes=10))
    assert not (root / long_name).exists()
    assert [p for p in root.rglob("*.tmp")] == []


# ---------------------------------------------------------------------------
# Symlink / escape rejection
# ---------------------------------------------------------------------------


def test_symlink_root_rejected(tmp_path: Path) -> None:
    real = _repo(tmp_path, name="real", docs=False, license_=False, py=False)
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(DiscoveryError):
        discover(link)


def test_fail_closed_oversized_marker(tmp_path: Path) -> None:
    root = _repo(tmp_path, py=True)
    (root / "pyproject.toml").write_text("#" * 10_000, encoding="utf-8")
    with pytest.raises(LimitError):
        discover(root, limits=ResourceLimits(document_bytes=100))


def test_total_document_bytes_enforced(tmp_path: Path) -> None:
    root = _repo(tmp_path, py=False)
    (root / "README.md").write_text("# Acme\n" + ("x" * 2000), encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "index.md").write_text("# Index\n" + ("y" * 2000), encoding="utf-8")
    with pytest.raises(LimitError):
        discover(root, limits=ResourceLimits(total_document_bytes=1500))


def test_symlinked_entry_doc_not_discovered(tmp_path: Path) -> None:
    root = _repo(tmp_path, docs=False)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    try:
        (root / "README.md").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    result = discover(root)
    assert result.canonical_docs == ()


def test_path_escape_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with pytest.raises(UnsafeCanonicalPath):
        init(root, manifest_path="../evil.yaml")
    assert not (root.parent / "evil.yaml").exists()


def test_resolve_output_path_escape(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with pytest.raises(UnsafeCanonicalPath):
        resolve_output_path(root, "..\\escape.yaml")
    with pytest.raises(UnsafeCanonicalPath):
        resolve_output_path(root, "C:\\windows\\evil.yaml")


def test_resolve_output_path_rejects_final_symlink_escape(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    outside = tmp_path / "outside.yaml"
    outside.write_text("x", encoding="utf-8")
    try:
        (root / DEFAULT_MANIFEST_NAME).symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(UnsafeCanonicalPath):
        resolve_output_path(root, DEFAULT_MANIFEST_NAME)


# ---------------------------------------------------------------------------
# Init: create / dry-run / replace / refused
# ---------------------------------------------------------------------------


def test_init_create_writes_manifest(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    report = init(root)
    assert report.operation == OPERATION_CREATE
    assert report.would_write is True
    assert report.written is True
    assert report.replaced is False
    assert report.manifest_path == DEFAULT_MANIFEST_NAME
    target = root / DEFAULT_MANIFEST_NAME
    assert target.is_file()


def test_init_dry_run_creates_nothing(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    report = init(root, dry_run=True)
    assert report.operation == OPERATION_DRY_RUN
    assert report.would_write is True
    assert report.written is False
    assert not (root / DEFAULT_MANIFEST_NAME).exists()


def test_init_default_no_overwrite(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    existing = "beacon_version: 0.1\nproject:\n  name: original\n  description: keep\n"
    (root / DEFAULT_MANIFEST_NAME).write_text(existing, encoding="utf-8")
    report = init(root)
    assert report.operation == OPERATION_REFUSED
    assert report.would_write is False
    assert report.written is False
    assert (root / DEFAULT_MANIFEST_NAME).read_text(encoding="utf-8") == existing


def test_init_force_replaces_recognizable_manifest(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    existing = 'beacon_version: "0.1"\nproject:\n  name: original\n  description: keep\n'
    (root / DEFAULT_MANIFEST_NAME).write_text(existing, encoding="utf-8")
    report = init(root, force=True)
    assert report.operation == OPERATION_REPLACE
    assert report.replaced is True
    assert report.written is True
    assert "acme" in (root / DEFAULT_MANIFEST_NAME).read_text(encoding="utf-8")


def test_init_force_refuses_non_manifest_file(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / DEFAULT_MANIFEST_NAME).write_text("this is not a beacon manifest", encoding="utf-8")
    report = init(root, force=True)
    assert report.operation == OPERATION_REFUSED
    assert (root / DEFAULT_MANIFEST_NAME).read_text(
        encoding="utf-8"
    ) == "this is not a beacon manifest"


def test_init_refuses_directory_target(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / DEFAULT_MANIFEST_NAME).mkdir()
    report = init(root)
    assert report.operation == OPERATION_REFUSED
    assert (root / DEFAULT_MANIFEST_NAME).is_dir()


def test_init_refuses_symlink_target(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    outside = tmp_path / "outside.yaml"
    outside.write_text("x", encoding="utf-8")
    try:
        (root / DEFAULT_MANIFEST_NAME).symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    report = init(root)
    assert report.operation == OPERATION_REFUSED
    assert (root / DEFAULT_MANIFEST_NAME).is_symlink()


def test_in_root_target_symlink_not_overwritten_under_force(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    referent = root / "real.yaml"
    original = b'beacon_version: "0.1"\nproject:\n  name: r\n  description: d\n'
    referent.write_bytes(original)
    try:
        (root / DEFAULT_MANIFEST_NAME).symlink_to(referent)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    report = init(root, force=True)
    assert report.operation == OPERATION_REFUSED
    assert (root / DEFAULT_MANIFEST_NAME).is_symlink()
    # the in-root target is a symlink; its referent must not be replaced
    assert referent.read_bytes() == original
    assert referent.read_text(encoding="utf-8").startswith("beacon_version")


def test_in_root_parent_symlink_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    real_dir = root / "real_dir"
    real_dir.mkdir()
    try:
        (root / "sub").symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    report = init(root, manifest_path="sub/beacon.yaml", force=True)
    assert report.operation == OPERATION_REFUSED
    assert not (real_dir / "beacon.yaml").exists()
    assert (root / "sub").is_symlink()


def test_init_refuses_when_no_canonical_doc(tmp_path: Path) -> None:
    root = _repo(tmp_path, docs=False, license_=False, py=False)
    report = init(root)
    assert report.operation == OPERATION_REFUSED
    assert report.would_write is False
    assert report.written is False
    assert not (root / DEFAULT_MANIFEST_NAME).exists()
    codes = {item.code for item in report.review_required}
    assert REVIEW_CANONICAL_DOCS_MISSING in codes
    assert REFUSED_NO_CANONICAL_DOC == REVIEW_CANONICAL_DOCS_MISSING


def test_init_cleanup_after_write_failure(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(scaffold_mod.os, "replace", boom)
    try:
        with pytest.raises(OSError):
            init(root)
    finally:
        monkey.undo()
    assert not (root / DEFAULT_MANIFEST_NAME).exists()
    leftovers = [p for p in root.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Rendered manifest: deterministic, zero errors, warnings expected
# ---------------------------------------------------------------------------


def test_render_yaml_is_deterministic(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = discover(root)
    assert render_manifest_yaml(result) == render_manifest_yaml(result)


def test_render_yaml_field_order(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = discover(root)
    rendered = render_manifest_yaml(result)
    parsed = yaml.safe_load(rendered)
    order = list(parsed)
    expected = [
        "beacon_version",
        "project",
        "purpose",
        "audiences",
        "current_focus",
        "core_concepts",
        "canonical_docs",
        "agent_guidance",
        "build_and_test",
        "guardrails",
    ]
    assert order == expected


def test_generated_manifest_validates_zero_errors(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    report = init(root)
    assert report.written is True
    manifest = load_beacon_manifest(root / DEFAULT_MANIFEST_NAME)
    validation = validate_beacon_manifest(manifest, docs_root=root)
    assert validation.ok is True, validation.errors
    assert validation.warnings  # unknown status / purpose / guardrails expected


def test_generated_manifest_project_fields(tmp_path: Path) -> None:
    root = _repo(tmp_path, git_remote="https://github.com/acme/acme")
    init(root)
    manifest = load_beacon_manifest(root / DEFAULT_MANIFEST_NAME)
    assert manifest.project.name == "acme"
    assert manifest.project.status == "unknown"
    assert manifest.project.repository == "https://github.com/acme/acme"
    assert manifest.project.primary_language == "Python"
    assert manifest.project.description.strip()
    assert manifest.build_and_test.test == "python -m pytest tests/ -x --tb=short"
    assert manifest.canonical_docs[0].path == "README.md"


# ---------------------------------------------------------------------------
# Report payload and report writing
# ---------------------------------------------------------------------------


def test_report_payload_matches_schema(tmp_path: Path, init_schema: dict) -> None:
    root = _repo(tmp_path, git_remote="https://user:sekrit@github.com/acme/acme")
    report = init(root)
    payload = to_payload(report)
    assert payload["beacon_init_report_version"] == "1.0"
    assert payload["repository_root"] == "."
    jsonschema.validate(payload, init_schema)
    for field in payload["discovered"]:
        assert field["value"] is True


def test_report_constants(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    report = init(root)
    assert report.schema == SCHEMA_NAME
    assert report.schema_version == SCHEMA_VERSION
    assert to_payload(report)["beacon_init_report_version"] == SCHEMA_VERSION


def test_write_report_writes_canonical_json(tmp_path: Path, init_schema: dict) -> None:
    root = _repo(tmp_path)
    report = init(root)
    out = tmp_path / "report.json"
    write_report(report, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    jsonschema.validate(payload, init_schema)
    assert payload["operation"] == OPERATION_CREATE


def test_refused_existing_target_reports_manifest_exists(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / DEFAULT_MANIFEST_NAME).write_text("not a beacon manifest", encoding="utf-8")
    report = init(root)
    assert report.operation == OPERATION_REFUSED
    codes = {item.code for item in report.review_required}
    from beacon.core.scaffold import REVIEW_MANIFEST_EXISTS

    assert REVIEW_MANIFEST_EXISTS in codes


def test_no_doc_refusal_retains_discovered_fields(tmp_path: Path) -> None:
    root = _repo(
        tmp_path, docs=False, license_=False, py=False, git_remote="https://github.com/acme/acme"
    )
    report = init(root)
    assert report.operation == OPERATION_REFUSED
    payload = to_payload(report)
    names = {f["manifest_path"] for f in payload["discovered"]}
    assert "project.name" in names
    assert "project.repository" in names
    assert "canonical_docs" not in names


def test_force_recognition_requires_typed_manifest(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    # beacon_version present but not a typed, valid v0.1 manifest.
    (root / DEFAULT_MANIFEST_NAME).write_text(
        "beacon_version: 0.1\nnot_project: [1, 2, 3]\n", encoding="utf-8"
    )
    report = init(root, force=True)
    assert report.operation == OPERATION_REFUSED
    assert (root / DEFAULT_MANIFEST_NAME).read_text(encoding="utf-8").startswith("beacon_version")


def test_force_recognition_rejects_wrong_version(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / DEFAULT_MANIFEST_NAME).write_text(
        'beacon_version: "9.9"\nproject:\n  name: x\n  description: y\ncanonical_docs:\n  - path: README.md\n',
        encoding="utf-8",
    )
    report = init(root, force=True)
    assert report.operation == OPERATION_REFUSED


def test_force_recognizes_valid_typed_manifest(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / DEFAULT_MANIFEST_NAME).write_text(
        'beacon_version: "0.1"\nproject:\n  name: original\n  description: keep\ncanonical_docs:\n  - path: README.md\n',
        encoding="utf-8",
    )
    report = init(root, force=True)
    assert report.operation == OPERATION_REPLACE


def test_init_refuses_missing_parent_directory(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    report = init(root, manifest_path="nested/deep/beacon.yaml")
    assert report.operation == OPERATION_REFUSED
    assert not (root / "nested").exists()


def test_manifest_path_normalized_to_forward_slashes(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "sub").mkdir()
    report = init(root, manifest_path="sub\\beacon.yaml")
    assert report.manifest_path == "sub/beacon.yaml"
    assert report.operation == OPERATION_CREATE
    assert (root / "sub" / "beacon.yaml").is_file()


def test_generated_guidance_read_first_is_canonical_docs(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    init(root)
    manifest = load_beacon_manifest(root / DEFAULT_MANIFEST_NAME)
    assert manifest.agent_guidance.read_first == ("README.md",)


def test_expected_result_is_immutable(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = discover(root)
    assert isinstance(result, DiscoveryResult)
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        result.name = "other"  # type: ignore[misc]


def test_scaffold_review_for_ambiguous_node(tmp_path: Path) -> None:
    from beacon.core.scaffold import REVIEW_BUILD_COMMANDS_UNKNOWN

    root = _repo(tmp_path, py=False)
    (root / "package.json").write_text('{"scripts": {"test": "mocha"}}', encoding="utf-8")
    report = init(root)
    codes = {item.code for item in report.review_required}
    assert REVIEW_BUILD_COMMANDS_UNKNOWN in codes
    assert "test_command_missing" not in codes
