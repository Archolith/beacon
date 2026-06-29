"""Parse ``beacon.yaml`` into the typed :class:`BeaconManifest`.

The loader is intentionally forgiving about *missing* keys (it fills defaults)
but strict about *types* (a mapping where a list is expected raises). Semantic
checks -- duplicate concept ids, missing canonical docs, dangling paths -- live
in :mod:`beacon.core.validator`, not here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from beacon.core.schema import (
    BeaconAgentGuidance,
    BeaconBuildTest,
    BeaconConcept,
    BeaconDoc,
    BeaconGuardrail,
    BeaconManifest,
    BeaconProjectInfo,
    BeaconPurpose,
    BeaconSource,
)


class ManifestError(ValueError):
    """Raised when a manifest cannot be parsed into the typed schema."""


def load_beacon_manifest(path: str | Path) -> BeaconManifest:
    """Load and parse a ``beacon.yaml`` file into a :class:`BeaconManifest`.

    Raises :class:`ManifestError` if the file is missing, is not a mapping, or
    has a structurally invalid shape.
    """
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ManifestError(f"manifest not found: {manifest_path}")
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough detail
        raise ManifestError(f"invalid YAML in {manifest_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest root must be a mapping, got {type(raw).__name__}")
    return parse_manifest(raw)


def parse_manifest(raw: dict[str, Any]) -> BeaconManifest:
    """Parse an already-loaded mapping into a :class:`BeaconManifest`."""
    project = _parse_project(_as_map(raw.get("project"), "project"))
    return BeaconManifest(
        beacon_version=str(raw.get("beacon_version", "0.1")),
        project=project,
        purpose=_parse_purpose(_as_map(raw.get("purpose"), "purpose", optional=True)),
        audiences=_str_tuple(raw.get("audiences")),
        current_focus=_str_tuple(raw.get("current_focus")),
        core_concepts=tuple(
            _parse_concept(item) for item in _as_list(raw.get("core_concepts"), "core_concepts")
        ),
        canonical_docs=tuple(
            _parse_doc(item) for item in _as_list(raw.get("canonical_docs"), "canonical_docs")
        ),
        agent_guidance=_parse_guidance(
            _as_map(raw.get("agent_guidance"), "agent_guidance", optional=True)
        ),
        build_and_test=_parse_build_test(
            _as_map(raw.get("build_and_test"), "build_and_test", optional=True)
        ),
        guardrails=tuple(
            _parse_guardrail(item) for item in _as_list(raw.get("guardrails"), "guardrails")
        ),
    )


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------


def _parse_project(data: dict[str, Any]) -> BeaconProjectInfo:
    return BeaconProjectInfo(
        name=str(data.get("name", "")),
        tagline=str(data.get("tagline", "")),
        description=_collapse(data.get("description", "")),
        status=str(data.get("status", "experimental")),
        repository=str(data.get("repository", "")),
        primary_language=str(data.get("primary_language", "")),
        license=str(data.get("license", "")),
    )


def _parse_purpose(data: dict[str, Any]) -> BeaconPurpose:
    return BeaconPurpose(
        one_sentence=_collapse(data.get("one_sentence", "")),
        problem=_collapse(data.get("problem", "")),
        non_goals=_str_tuple(data.get("non_goals")),
    )


def _parse_concept(item: Any) -> BeaconConcept:
    data = _as_map(item, "core_concepts[]")
    if "id" not in data:
        raise ManifestError("each core_concepts entry needs an 'id'")
    return BeaconConcept(
        id=str(data["id"]),
        name=str(data.get("name", data["id"])),
        definition=_collapse(data.get("description", data.get("definition", ""))),
        why_it_exists=_collapse(data.get("why_it_exists", "")),
        status=str(data.get("status", "current")),
        related_concepts=_str_tuple(data.get("related_concepts")),
        implementation_locations=_str_tuple(data.get("implementation_locations")),
        sources=_parse_sources(data.get("sources")),
    )


def _parse_doc(item: Any) -> BeaconDoc:
    data = _as_map(item, "canonical_docs[]")
    if "path" not in data:
        raise ManifestError("each canonical_docs entry needs a 'path'")
    return BeaconDoc(
        path=str(data["path"]),
        role=str(data.get("role", "")),
        status=str(data.get("status", "current")),
        title=str(data.get("title", "")),
    )


def _parse_guardrail(item: Any) -> BeaconGuardrail:
    data = _as_map(item, "guardrails[]")
    if "id" not in data:
        raise ManifestError("each guardrails entry needs an 'id'")
    return BeaconGuardrail(
        id=str(data["id"]),
        rule=_collapse(data.get("rule", "")),
        scope=str(data.get("scope", "")),
        severity=str(data.get("severity", "medium")),
        applies_to=_str_tuple(data.get("applies_to")),
        sources=_parse_sources(data.get("sources")),
    )


def _parse_guidance(data: dict[str, Any]) -> BeaconAgentGuidance:
    return BeaconAgentGuidance(
        read_first=_str_tuple(data.get("read_first")),
        safe_first_tasks=_str_tuple(data.get("safe_first_tasks")),
        avoid_without_review=_str_tuple(
            data.get("avoid_without_review", data.get("avoid_without_maintainer_review"))
        ),
        expected_behavior=_str_tuple(data.get("expected_behavior")),
    )


def _parse_build_test(data: dict[str, Any]) -> BeaconBuildTest:
    return BeaconBuildTest(
        setup=str(data.get("setup", "")),
        test=str(data.get("test", "")),
        benchmark=str(data.get("benchmark", "")),
    )


def _parse_sources(value: Any) -> tuple[BeaconSource, ...]:
    if value is None:
        return ()
    sources: list[BeaconSource] = []
    for item in _as_list(value, "sources"):
        data = _as_map(item, "sources[]")
        sources.append(
            BeaconSource(
                type=str(data.get("type", "doc")),
                title=str(data.get("title", "")),
                path=str(data.get("path", "")),
                url=str(data.get("url", "")),
                line_start=_opt_int(data.get("line_start")),
                line_end=_opt_int(data.get("line_end")),
                status=str(data.get("status", "current")),
            )
        )
    return tuple(sources)


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _as_map(value: Any, where: str, *, optional: bool = False) -> dict[str, Any]:
    if value is None:
        if optional:
            return {}
        raise ManifestError(f"missing required mapping: {where}")
    if not isinstance(value, dict):
        raise ManifestError(f"{where} must be a mapping, got {type(value).__name__}")
    return value


def _as_list(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ManifestError(f"{where} must be a list, got {type(value).__name__}")
    return value


def _str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    raise ManifestError(f"expected a string or list of strings, got {type(value).__name__}")


def _collapse(value: Any) -> str:
    """Collapse YAML block-scalar whitespace into a single trimmed string."""
    return " ".join(str(value).split())


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
