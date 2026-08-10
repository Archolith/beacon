"""Focused tests for the reusable v0.2 CLI support layer.

Covers limits precedence, manifest/docs-root path defaults, exit-code
classification, acknowledgement labelling, provider construction, safe internal
normalization/no-leak behaviour, and immutability.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from beacon.core import cli_result
from beacon.core.cli_support import (
    CODE_INVALID_DOCS_ROOT,
    CODE_MANIFEST_INVALID,
    CODE_MANIFEST_NOT_FOUND,
    CODE_NOT_SERVABLE,
    EXIT_INPUT,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_VALIDATION,
    CliFailure,
    CommandContext,
    build_command_context,
    build_resource_limits,
    effective_limits_mapping,
    normalize_internal,
    report_to_diagnostics,
    resolve_docs_root,
    resolve_manifest_path,
)
from beacon.core.limits import (
    FIELD_ENV_VARS,
    LIMIT_INVALID_VALUE,
    LIMIT_MANIFEST_BYTES,
    OVERRIDABLE_LIMIT_FIELDS,
    LimitError,
    ResourceLimits,
)
from beacon.core.policy import parse_acknowledgements
from beacon.core.validator import (
    CODE_GUARDRAILS_MISSING,
    CODE_TEST_COMMAND_MISSING,
)

LONG_REASON = "Because we cannot run automated tests here yet."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _manifest_yaml(with_test: bool = True) -> str:
    test_block = '  test: "python -m pytest"\n' if with_test else ""
    build_block = "build_and_test:\n" + test_block if with_test else ""
    return (
        'beacon_version: "0.1"\n'
        "project:\n"
        "  name: x\n"
        "  description: desc\n"
        "  status: experimental\n"
        "purpose:\n"
        '  one_sentence: "a purpose for the fixture"\n'
        "canonical_docs:\n"
        "  - path: README.md\n"
        "    status: current\n" + build_block
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "beacon.yaml").write_text(_manifest_yaml(), encoding="utf-8")
    (tmp_path / "README.md").write_text("# Fixture doc\ncontent\n", encoding="utf-8")
    return tmp_path


def _manif_ok_ctx(repo: Path, **kw: object) -> CommandContext:
    return build_command_context(manifest_path=repo / "beacon.yaml", **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Resource limits precedence
# ---------------------------------------------------------------------------


def test_limits_default_when_no_overrides() -> None:
    limits = build_resource_limits(None, {})
    assert limits == ResourceLimits()
    assert limits.manifest_bytes == ResourceLimits().manifest_bytes


def test_limits_env_over_default() -> None:
    env = {FIELD_ENV_VARS["manifest_bytes"]: "2048"}
    limits = build_resource_limits(None, env)
    assert limits.manifest_bytes == 2048


def test_limits_cli_over_env_over_default() -> None:
    env = {FIELD_ENV_VARS["manifest_bytes"]: "2048"}
    cli = {"manifest_bytes": 4096}
    limits = build_resource_limits(cli, env)
    assert limits.manifest_bytes == 4096


def test_limits_all_six_overridable_fields() -> None:
    env = {FIELD_ENV_VARS[f]: str(100 * i + 1) for i, f in enumerate(OVERRIDABLE_LIMIT_FIELDS)}
    limits = build_resource_limits(None, env)
    for i, field in enumerate(OVERRIDABLE_LIMIT_FIELDS):
        assert limits.ceiling(field) == 100 * i + 1


def test_limits_cli_ignores_non_overridable_fields() -> None:
    # yaml_depth and path_bytes are fixed safety ceilings, never overridable.
    cli = {"manifest_bytes": 4096, "yaml_depth": 1, "path_bytes": 2}
    limits = build_resource_limits(cli, {})
    assert limits.manifest_bytes == 4096
    assert limits.yaml_depth == ResourceLimits().yaml_depth
    assert limits.path_bytes == ResourceLimits().path_bytes


def test_limits_none_cli_overrides_let_env_win() -> None:
    # Typer passes unset options as None; those must not override the env layer.
    env = {FIELD_ENV_VARS["documents"]: "33"}
    cli = {"documents": None, "manifest_bytes": None}
    limits = build_resource_limits(cli, env)  # type: ignore[dict-item]
    assert limits.documents == 33
    assert limits.manifest_bytes == ResourceLimits().manifest_bytes


def test_limits_all_none_cli_returns_env_layer() -> None:
    env = {FIELD_ENV_VARS["documents"]: "33"}
    limits = build_resource_limits({"documents": None, "chunks": None}, env)  # type: ignore[dict-item]
    assert limits.documents == 33
    assert limits.chunks == ResourceLimits().chunks


def test_limits_invalid_cli_value_raises_limit_error() -> None:
    with pytest.raises(LimitError) as info:
        build_resource_limits({"manifest_bytes": -1}, {})
    assert info.value.code == LIMIT_INVALID_VALUE


def test_limits_invalid_env_value_raises_limit_error() -> None:
    with pytest.raises(LimitError) as info:
        build_resource_limits(None, {FIELD_ENV_VARS["documents"]: "not-a-number"})
    assert info.value.code == LIMIT_INVALID_VALUE


def test_effective_limits_mapping_is_json_ready() -> None:
    limits = build_resource_limits({"documents": 17}, {})
    mapping = effective_limits_mapping(limits)
    assert set(mapping) == set(OVERRIDABLE_LIMIT_FIELDS)
    assert mapping["documents"] == 17
    assert all(isinstance(v, int) for v in mapping.values())


# ---------------------------------------------------------------------------
# Manifest path / docs-root resolution
# ---------------------------------------------------------------------------


def test_manifest_path_defaults_to_beacon_yaml_in_cwd(tmp_path: Path) -> None:
    (tmp_path / "beacon.yaml").write_text(_manifest_yaml(), encoding="utf-8")
    resolved = resolve_manifest_path(None, cwd=tmp_path)
    assert resolved == tmp_path / "beacon.yaml"


def test_missing_manifest_is_exit_2_without_path(tmp_path: Path) -> None:
    with pytest.raises(CliFailure) as info:
        resolve_manifest_path(None, cwd=tmp_path)
    failure = info.value
    assert failure.exit_code == EXIT_INPUT
    assert failure.code == CODE_MANIFEST_NOT_FOUND
    assert str(tmp_path) not in failure.message
    assert failure.to_diagnostic().code == CODE_MANIFEST_NOT_FOUND


def test_non_file_manifest_path_is_exit_2(tmp_path: Path) -> None:
    (tmp_path / "beacon.yaml").mkdir()
    with pytest.raises(CliFailure) as info:
        resolve_manifest_path(tmp_path / "beacon.yaml")
    assert info.value.exit_code == EXIT_INPUT
    assert info.value.code == CODE_MANIFEST_NOT_FOUND


def test_docs_root_defaults_to_manifest_parent(repo: Path) -> None:
    root = resolve_docs_root(None, manifest_path=repo / "beacon.yaml")
    assert root == repo


def test_invalid_docs_root_is_exit_2_without_path(repo: Path) -> None:
    with pytest.raises(CliFailure) as info:
        resolve_docs_root(repo / "does-not-exist", manifest_path=repo / "beacon.yaml")
    failure = info.value
    assert failure.exit_code == EXIT_INPUT
    assert failure.code == CODE_INVALID_DOCS_ROOT
    assert str(repo) not in failure.message


def test_valid_docs_root_is_resolved(repo: Path) -> None:
    root = resolve_docs_root(repo, manifest_path=repo / "beacon.yaml")
    assert root == repo


# ---------------------------------------------------------------------------
# Exit classification on build_command_context
# ---------------------------------------------------------------------------


def test_bad_acknowledgement_is_exit_2(repo: Path) -> None:
    with pytest.raises(CliFailure) as info:
        _manif_ok_ctx(repo, acknowledgements=[f"{CODE_TEST_COMMAND_MISSING}=short"])
    assert info.value.exit_code == EXIT_INPUT


def test_unknown_acknowledgement_code_is_exit_2(repo: Path) -> None:
    with pytest.raises(CliFailure) as info:
        _manif_ok_ctx(repo, acknowledgements=[f"bogus_code={LONG_REASON}"])
    assert info.value.exit_code == EXIT_INPUT


def test_missing_manifest_is_exit_2(tmp_path: Path) -> None:
    with pytest.raises(CliFailure) as info:
        build_command_context(manifest_path=tmp_path / "beacon.yaml")
    assert info.value.exit_code == EXIT_INPUT
    assert info.value.code == CODE_MANIFEST_NOT_FOUND


def test_invalid_docs_root_is_exit_2(repo: Path) -> None:
    with pytest.raises(CliFailure) as info:
        build_command_context(manifest_path=repo / "beacon.yaml", docs_root=repo / "nope")
    assert info.value.exit_code == EXIT_INPUT
    assert info.value.code == CODE_INVALID_DOCS_ROOT


def test_malformed_yaml_is_exit_2(repo: Path) -> None:
    (repo / "beacon.yaml").write_text("project: [unclosed\n", encoding="utf-8")
    with pytest.raises(CliFailure) as info:
        build_command_context(manifest_path=repo / "beacon.yaml")
    assert info.value.exit_code == EXIT_INPUT
    assert info.value.code == CODE_MANIFEST_INVALID


def test_manifest_too_large_is_exit_2(repo: Path) -> None:
    (repo / "beacon.yaml").write_text("x: y\n", encoding="utf-8")
    with pytest.raises(CliFailure) as info:
        build_command_context(
            manifest_path=repo / "beacon.yaml",
            cli_limits={"manifest_bytes": 1},
        )
    assert info.value.exit_code == EXIT_INPUT
    assert info.value.code == LIMIT_MANIFEST_BYTES


def test_validation_errors_are_stored_not_raised(repo: Path) -> None:
    (repo / "beacon.yaml").write_text(
        'beacon_version: "0.1"\nproject:\n  name: ""\n  description: ""\n',
        encoding="utf-8",
    )
    ctx = build_command_context(manifest_path=repo / "beacon.yaml")
    assert ctx.report.ok is False
    assert ctx.report.errors
    assert ctx.policy.servable is False


def test_build_provider_requires_servable_manifest(repo: Path) -> None:
    (repo / "beacon.yaml").write_text(
        'beacon_version: "0.1"\nproject:\n  name: ""\n  description: ""\n',
        encoding="utf-8",
    )
    with pytest.raises(CliFailure) as info:
        build_command_context(manifest_path=repo / "beacon.yaml", build_provider=True)
    assert info.value.exit_code == EXIT_VALIDATION
    assert info.value.code == CODE_NOT_SERVABLE


# ---------------------------------------------------------------------------
# Successful context / provider construction
# ---------------------------------------------------------------------------


def test_context_builds_shared_snapshot(repo: Path) -> None:
    ctx = _manif_ok_ctx(repo)
    assert isinstance(ctx, CommandContext)
    assert ctx.limits == ResourceLimits()
    assert ctx.manifest_path == repo / "beacon.yaml"
    assert ctx.docs_root == repo
    assert ctx.manifest.project.name == "x"
    assert ctx.report.ok is True
    assert ctx.provider is None


def test_context_builds_provider(repo: Path) -> None:
    ctx = _manif_ok_ctx(repo, build_provider=True)
    assert ctx.provider is not None
    overview = ctx.provider.project_overview()
    assert overview.summary


def test_provider_reuses_loaded_manifest_snapshot(repo: Path) -> None:
    ctx = _manif_ok_ctx(repo, build_provider=True)
    # The provider is built from the same manifest object already in the
    # context (one snapshot), not a fresh re-read from disk.
    assert ctx.provider.manifest is ctx.manifest
    assert ctx.provider.docs_root == ctx.docs_root
    assert ctx.provider.limits is ctx.limits


def test_context_acknowledgements_recorded(repo: Path) -> None:
    acks = [f"{CODE_GUARDRAILS_MISSING}={LONG_REASON}"]
    ctx = _manif_ok_ctx(repo, acknowledgements=acks)
    assert ctx.acknowledgements == parse_acknowledgements(acks)
    assert ctx.policy.acknowledged


def test_context_builds_without_network_or_print(repo: Path, capsys) -> None:
    _manif_ok_ctx(repo, build_provider=True)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# ---------------------------------------------------------------------------
# Acknowledgement labelling
# ---------------------------------------------------------------------------


def _servable_with_warnings(repo: Path) -> CommandContext:
    # No test command and no guardrails -> two publication warnings.
    (repo / "beacon.yaml").write_text(_manifest_yaml(with_test=False), encoding="utf-8")
    return build_command_context(manifest_path=repo / "beacon.yaml")


def test_report_to_diagnostics_marks_acknowledged_with_reason(repo: Path) -> None:
    ctx = _servable_with_warnings(repo)
    acks = parse_acknowledgements([f"{CODE_GUARDRAILS_MISSING}={LONG_REASON}"])
    diags = report_to_diagnostics(ctx.report, acknowledgements=acks)
    by_code = {d.code: d for d in diags}
    assert by_code[CODE_GUARDRAILS_MISSING].acknowledged is True
    assert by_code[CODE_GUARDRAILS_MISSING].acknowledgement_reason == LONG_REASON
    # Unacknowledged warnings stay plain.
    assert by_code[CODE_TEST_COMMAND_MISSING].acknowledged is False
    assert by_code[CODE_TEST_COMMAND_MISSING].acknowledgement_reason is None


def test_report_to_diagnostics_preserves_original_facts(repo: Path) -> None:
    ctx = _servable_with_warnings(repo)
    original = next(i for i in ctx.report.issues if i.code == CODE_TEST_COMMAND_MISSING)
    diags = report_to_diagnostics(ctx.report)
    diag = next(d for d in diags if d.code == CODE_TEST_COMMAND_MISSING)
    assert diag.severity == cli_result.Severity.WARNING
    assert diag.path == original.where
    assert diag.message == original.message
    # The underlying report is unchanged.
    assert CODE_TEST_COMMAND_MISSING in {i.code for i in ctx.report.issues}


def test_report_to_diagnostics_no_acknowledgements_marks_nothing(repo: Path) -> None:
    ctx = _servable_with_warnings(repo)
    diags = report_to_diagnostics(ctx.report)
    assert all(d.acknowledged is False for d in diags)


# ---------------------------------------------------------------------------
# Safe internal normalization / no leaks
# ---------------------------------------------------------------------------


def test_normalize_internal_is_safe_and_exit_3() -> None:
    failure = normalize_internal(RuntimeError("path=/etc/passwd SECRET=abc"))
    assert failure.exit_code == EXIT_INTERNAL
    assert failure.code == cli_result.INTERNAL_ERROR_CODE
    assert failure.message == cli_result.INTERNAL_ERROR_MESSAGE
    assert "etc/passwd" not in failure.message
    assert "SECRET" not in failure.message
    assert failure.to_diagnostic().code == cli_result.INTERNAL_ERROR_CODE


def test_normalize_internal_ignores_exception_text() -> None:
    failure = normalize_internal(ValueError("leakme"))
    assert "leakme" not in failure.message
    assert "ValueError" not in failure.message


def test_cli_failure_str_is_meaningful_and_safe() -> None:
    failure = CliFailure(EXIT_INPUT, CODE_MANIFEST_NOT_FOUND, "manifest not found")
    text = str(failure)
    assert CODE_MANIFEST_NOT_FOUND in text
    assert "manifest not found" in text


def test_cli_failure_to_diagnostic_coerces_severity_safely() -> None:
    # Unknown severity strings fall back to error rather than raising.
    failure = CliFailure(EXIT_INPUT, CODE_MANIFEST_NOT_FOUND, "manifest not found", severity="nope")
    diag = failure.to_diagnostic()
    assert diag.severity == cli_result.Severity.ERROR
    assert diag.code == CODE_MANIFEST_NOT_FOUND


def test_failure_diagnostics_never_leak_paths(repo: Path) -> None:
    for failure in (
        resolve_manifest_path_raises(repo),
        resolve_docs_root_raises(repo),
    ):
        diag = failure.to_diagnostic()
        assert str(repo) not in diag.message
        assert str(repo) not in failure.message


def resolve_manifest_path_raises(repo: Path) -> CliFailure:
    try:
        resolve_manifest_path(repo / "missing.yaml")
    except CliFailure as exc:
        return exc
    raise AssertionError("expected CliFailure")


def resolve_docs_root_raises(repo: Path) -> CliFailure:
    try:
        resolve_docs_root(repo / "missing", manifest_path=repo / "beacon.yaml")
    except CliFailure as exc:
        return exc
    raise AssertionError("expected CliFailure")


def test_build_context_unexpected_error_normalized_to_3(repo: Path, monkeypatch) -> None:
    import beacon.core.cli_support as support

    def boom(*_a, **_k):
        raise RuntimeError("path=/secret")

    monkeypatch.setattr(support, "load_beacon_manifest", boom)
    with pytest.raises(CliFailure) as info:
        build_command_context(manifest_path=repo / "beacon.yaml")
    assert info.value.exit_code == EXIT_INTERNAL
    assert info.value.code == cli_result.INTERNAL_ERROR_CODE
    assert "secret" not in info.value.message


# ---------------------------------------------------------------------------
# No mutation
# ---------------------------------------------------------------------------


def test_build_context_does_not_mutate_inputs(repo: Path) -> None:
    env = {FIELD_ENV_VARS["documents"]: "33"}
    cli = {"documents": 44}
    acks = [f"{CODE_GUARDRAILS_MISSING}={LONG_REASON}"]
    ctx = build_command_context(
        manifest_path=repo / "beacon.yaml",
        cli_limits=cli,
        env=env,
        acknowledgements=acks,
        build_provider=True,
    )
    assert env == {FIELD_ENV_VARS["documents"]: "33"}
    assert cli == {"documents": 44}
    assert ctx.limits.documents == 44
    # Re-running is deterministic and unchanged.
    again = build_command_context(
        manifest_path=repo / "beacon.yaml",
        cli_limits={"documents": 44},
        env=env,
        acknowledgements=acks,
        build_provider=True,
    )
    assert again.report == ctx.report
    assert again.policy == ctx.policy


def test_context_is_immutable(repo: Path) -> None:
    ctx = _manif_ok_ctx(repo, build_provider=True)
    with pytest.raises(FrozenInstanceError):
        ctx.manifest_path = repo / "other.yaml"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ctx.limits = ResourceLimits(manifest_bytes=1)  # type: ignore[misc]


def test_exit_constants_are_stable() -> None:
    assert (EXIT_OK, EXIT_VALIDATION, EXIT_INPUT, EXIT_INTERNAL) == (0, 1, 2, 3)
