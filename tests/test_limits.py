"""Focused tests for the shared resource-limits model and bounded readers."""

from __future__ import annotations

import textwrap
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from beacon.core.doc_index import DocIndex
from beacon.core.limits import (
    LIMIT_CHUNKS,
    LIMIT_DOCUMENT_BYTES,
    LIMIT_DOCUMENTS,
    LIMIT_INVALID_VALUE,
    LIMIT_MANIFEST_BYTES,
    LIMIT_PATH_BYTES,
    LIMIT_QUERY_BYTES,
    LIMIT_RESULT_LIMIT,
    LIMIT_TOTAL_DOCUMENT_BYTES,
    LIMIT_YAML_ALIASES,
    LIMIT_YAML_DEPTH,
    LIMIT_YAML_NODES,
    LimitError,
    ResourceLimits,
    resource_limits_from_env,
)
from beacon.core.loader import load_beacon_manifest
from beacon.core.schema import BeaconDoc
from beacon.provider.manifest_provider import ManifestBeaconProvider

MIB = 1024 * 1024
KIB = 1024

MINIMAL_RAW = {
    "beacon_version": "0.1",
    "project": {"name": "limits-project", "description": "Limits tests."},
    "canonical_docs": [{"path": "README.md", "role": "entrypoint", "status": "current"}],
}

SAMPLE_MD = textwrap.dedent("""\
    # One

    body one.

    ## Two

    body two.

    ### Three

    body three.
""")


def _write_manifest(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "beacon.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def _provider(tmp_path: Path, *, limits: ResourceLimits | None = None) -> ManifestBeaconProvider:
    (tmp_path / "README.md").write_text(SAMPLE_MD, encoding="utf-8")
    manifest_file = _write_manifest(tmp_path, MINIMAL_RAW)
    return ManifestBeaconProvider.from_paths(
        manifest_path=manifest_file, docs_root=tmp_path, limits=limits
    )


# ---------------------------------------------------------------------------
# Standard defaults match the addendum exactly
# ---------------------------------------------------------------------------


def test_standard_defaults_exact() -> None:
    limits = ResourceLimits()
    assert limits.manifest_bytes == 1 * MIB
    assert limits.documents == 256
    assert limits.document_bytes == 2 * MIB
    assert limits.total_document_bytes == 20 * MIB
    assert limits.chunks == 10_000
    assert limits.snapshot_bytes == 50 * MIB
    assert limits.yaml_depth == 32
    assert limits.yaml_nodes == 50_000
    assert limits.yaml_aliases == 50
    assert limits.path_bytes == 1_024
    assert limits.query_bytes == 4 * KIB
    assert limits.result_limit == 100
    assert limits.init_report_bytes == 5 * MIB


def test_defaults_are_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        ResourceLimits().manifest_bytes = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Precedence: CLI > environment > default, in a reusable form
# ---------------------------------------------------------------------------


def test_env_override_applies_over_default() -> None:
    limits = resource_limits_from_env({"BEACON_MAX_DOCUMENTS": "500"})
    assert limits.documents == 500
    assert limits.manifest_bytes == 1 * MIB  # untouched


def test_cli_override_wins_over_environment() -> None:
    from_env = resource_limits_from_env(
        {
            "BEACON_MAX_DOCUMENTS": "500",
            "BEACON_MAX_CHUNKS": "700",
        }
    )
    cli = from_env.apply_overrides({"documents": 10}, where="cli")
    assert cli.documents == 10
    assert cli.chunks == 700


def test_empty_env_uses_defaults() -> None:
    limits = resource_limits_from_env({})
    assert limits == ResourceLimits()


# ---------------------------------------------------------------------------
# Invalid override values are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [-1, 0 - 5, -100])
def test_negative_override_rejected(value: int) -> None:
    with pytest.raises(LimitError) as excinfo:
        ResourceLimits().apply_overrides({"documents": value})
    assert excinfo.value.code == LIMIT_INVALID_VALUE


def test_overflow_override_rejected() -> None:
    with pytest.raises(LimitError) as excinfo:
        ResourceLimits().apply_overrides({"documents": 2**63})
    assert excinfo.value.code == LIMIT_INVALID_VALUE


def test_non_integer_override_rejected() -> None:
    with pytest.raises(LimitError) as excinfo:
        resource_limits_from_env({"BEACON_MAX_CHUNKS": "not-a-number"})
    assert excinfo.value.code == LIMIT_INVALID_VALUE


@pytest.mark.parametrize("value", [True, 1.5, "1.5"])
def test_lossy_or_boolean_override_rejected(value: object) -> None:
    with pytest.raises(LimitError) as excinfo:
        ResourceLimits().apply_overrides({"documents": value})
    assert excinfo.value.code == LIMIT_INVALID_VALUE


def test_direct_invalid_limit_construction_rejected() -> None:
    with pytest.raises(LimitError) as excinfo:
        ResourceLimits(document_bytes=-1)
    assert excinfo.value.code == LIMIT_INVALID_VALUE


# ---------------------------------------------------------------------------
# Manifest byte ceiling is enforced before decode/parse
# ---------------------------------------------------------------------------


def test_manifest_bytes_exceeded_refused(tmp_path: Path) -> None:
    manifest_file = _write_manifest(tmp_path, MINIMAL_RAW)
    limits = ResourceLimits(manifest_bytes=10)
    with pytest.raises(LimitError) as excinfo:
        load_beacon_manifest(manifest_file, limits=limits)
    assert excinfo.value.code == LIMIT_MANIFEST_BYTES
    # Message must not include manifest contents.
    assert "limits-project" not in str(excinfo.value)


def test_manifest_bytes_within_limit_loads(tmp_path: Path) -> None:
    manifest_file = _write_manifest(tmp_path, MINIMAL_RAW)
    manifest = load_beacon_manifest(manifest_file)
    assert manifest.project.name == "limits-project"


# ---------------------------------------------------------------------------
# YAML depth / node / alias ceilings
# ---------------------------------------------------------------------------


def test_yaml_depth_exceeded(tmp_path: Path) -> None:
    p = tmp_path / "beacon.yaml"
    nested = {"beacon_version": "0.1"}
    node = {"project": {"name": "x", "description": "y"}}
    cur = node
    for _ in range(40):
        cur = {"next": cur}
    nested["extra"] = cur
    p.write_text(yaml.dump(nested), encoding="utf-8")
    limits = ResourceLimits(yaml_depth=8)
    with pytest.raises(LimitError) as excinfo:
        load_beacon_manifest(p, limits=limits)
    assert excinfo.value.code == LIMIT_YAML_DEPTH


def test_yaml_nodes_exceeded(tmp_path: Path) -> None:
    p = tmp_path / "beacon.yaml"
    p.write_text(yaml.dump({f"k{i}": {"v": i} for i in range(200)}), encoding="utf-8")
    limits = ResourceLimits(yaml_nodes=20)
    with pytest.raises(LimitError) as excinfo:
        load_beacon_manifest(p, limits=limits)
    assert excinfo.value.code == LIMIT_YAML_NODES


def test_yaml_aliases_exceeded(tmp_path: Path) -> None:
    p = tmp_path / "beacon.yaml"
    p.write_text("a: &x {k: v}\nb: *x\nc: *x\nd: *x\n", encoding="utf-8")
    limits = ResourceLimits(yaml_aliases=2)
    with pytest.raises(LimitError) as excinfo:
        load_beacon_manifest(p, limits=limits)
    assert excinfo.value.code == LIMIT_YAML_ALIASES


# ---------------------------------------------------------------------------
# Document count / per-doc bytes / aggregate bytes / path bytes
# ---------------------------------------------------------------------------


def test_document_count_exceeded(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(SAMPLE_MD, encoding="utf-8")
    (tmp_path / "b.md").write_text(SAMPLE_MD, encoding="utf-8")
    (tmp_path / "c.md").write_text(SAMPLE_MD, encoding="utf-8")
    docs = [
        BeaconDoc(path="a.md"),
        BeaconDoc(path="b.md"),
        BeaconDoc(path="c.md"),
    ]
    with pytest.raises(LimitError) as excinfo:
        DocIndex.from_docs(docs, docs_root=tmp_path, limits=ResourceLimits(documents=2))
    assert excinfo.value.code == LIMIT_DOCUMENTS


def test_document_bytes_exceeded(tmp_path: Path) -> None:
    (tmp_path / "big.md").write_text("# Big\n\n" + "x" * 5000, encoding="utf-8")
    docs = [BeaconDoc(path="big.md")]
    with pytest.raises(LimitError) as excinfo:
        DocIndex.from_docs(docs, docs_root=tmp_path, limits=ResourceLimits(document_bytes=100))
    assert excinfo.value.code == LIMIT_DOCUMENT_BYTES


def test_aggregate_document_bytes_exceeded(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# A\n\n" + "x" * 1000, encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n\n" + "y" * 1000, encoding="utf-8")
    docs = [BeaconDoc(path="a.md"), BeaconDoc(path="b.md")]
    with pytest.raises(LimitError) as excinfo:
        DocIndex.from_docs(
            docs,
            docs_root=tmp_path,
            limits=ResourceLimits(total_document_bytes=1500),
        )
    assert excinfo.value.code == LIMIT_TOTAL_DOCUMENT_BYTES


def test_path_bytes_exceeded(tmp_path: Path) -> None:
    long_name = "d" * 3000 + ".md"
    docs = [BeaconDoc(path=long_name)]
    with pytest.raises(LimitError) as excinfo:
        DocIndex.from_docs(docs, docs_root=tmp_path, limits=ResourceLimits(path_bytes=100))
    assert excinfo.value.code == LIMIT_PATH_BYTES
    # Message must not include the path itself.
    assert long_name not in str(excinfo.value)


def test_chunk_count_exceeded(tmp_path: Path) -> None:
    (tmp_path / "many.md").write_text(SAMPLE_MD * 4, encoding="utf-8")
    docs = [BeaconDoc(path="many.md")]
    with pytest.raises(LimitError) as excinfo:
        DocIndex.from_docs(docs, docs_root=tmp_path, limits=ResourceLimits(chunks=5))
    assert excinfo.value.code == LIMIT_CHUNKS


# ---------------------------------------------------------------------------
# Query bytes and result limit on the provider
# ---------------------------------------------------------------------------


def test_query_bytes_exceeded_on_search(tmp_path: Path) -> None:
    provider = _provider(tmp_path, limits=ResourceLimits(query_bytes=16))
    with pytest.raises(LimitError) as excinfo:
        provider.search(query="a very long query string that is far over sixteen bytes")
    assert excinfo.value.code == LIMIT_QUERY_BYTES


def test_query_bytes_exceeded_on_task_hint(tmp_path: Path) -> None:
    provider = _provider(tmp_path, limits=ResourceLimits(query_bytes=16))
    with pytest.raises(LimitError) as excinfo:
        provider.agent_onboarding(task_hint="x" * 100)
    assert excinfo.value.code == LIMIT_QUERY_BYTES


def test_result_limit_exceeded(tmp_path: Path) -> None:
    provider = _provider(tmp_path)  # default result_limit = 100
    with pytest.raises(LimitError) as excinfo:
        provider.search(query="body", limit=101)
    assert excinfo.value.code == LIMIT_RESULT_LIMIT


def test_negative_result_limit_rejected(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    with pytest.raises(LimitError) as excinfo:
        provider.search(query="body", limit=-1)
    assert excinfo.value.code == LIMIT_INVALID_VALUE


def test_valid_query_and_limit_pass(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    result = provider.search(query="body", limit=2)
    assert result.results
    onboarding = provider.agent_onboarding(task_hint="body")
    assert onboarding.orientation


# ---------------------------------------------------------------------------
# No leaked content in any diagnostic message
# ---------------------------------------------------------------------------


def test_errors_never_leak_content_or_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "secret.md").write_text("SUPER_SECRET_TOKEN_XYZ\n", encoding="utf-8")
    docs = [BeaconDoc(path="secret.md")]
    try:
        DocIndex.from_docs(docs, docs_root=tmp_path, limits=ResourceLimits(document_bytes=5))
    except LimitError as exc:
        assert "SUPER_SECRET_TOKEN" not in str(exc)
        assert "TOKEN" not in str(exc)

    monkeypatch.setenv("BEACON_MAX_MANIFEST_BYTES", "999999")
    manifest_file = _write_manifest(tmp_path, MINIMAL_RAW)
    limits = resource_limits_from_env()
    assert limits.manifest_bytes == 999999
    try:
        load_beacon_manifest(manifest_file, limits=ResourceLimits(manifest_bytes=5))
    except LimitError as exc:
        assert "999999" not in str(exc)


# ---------------------------------------------------------------------------
# Valid-input compatibility preserved
# ---------------------------------------------------------------------------


def test_valid_manifest_and_docs_under_defaults(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    assert provider.doc_index.chunks
    ov = provider.project_overview()
    assert ov.summary


@pytest.mark.asyncio
async def test_lifespan_threads_and_logs_effective_limits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from beacon.mcp import lifecycle

    limits = ResourceLimits(documents=17)
    settings = SimpleNamespace(
        manifest_path="beacon.yaml",
        validate_on_load=True,
        limits=limits,
        resolved_docs_root=lambda: ".",
    )
    captured: dict[str, object] = {}
    provider = SimpleNamespace(
        limits=limits,
        doc_index=SimpleNamespace(chunks=()),
        manifest=SimpleNamespace(core_concepts=(), project=SimpleNamespace(name="test-project")),
    )

    monkeypatch.setattr(lifecycle.BeaconSettings, "from_env", lambda: settings)

    def fake_from_paths(**kwargs: object) -> object:
        captured.update(kwargs)
        return provider

    monkeypatch.setattr(lifecycle.ManifestBeaconProvider, "from_paths", fake_from_paths)

    async with lifecycle.beacon_lifespan(object()):
        assert captured["limits"] is limits

    stderr = capsys.readouterr().err
    assert "documents=17" in stderr
    assert "init_report_bytes=5242880" in stderr
