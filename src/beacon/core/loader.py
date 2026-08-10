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

from beacon.core.limits import (
    LIMIT_DOCUMENTS,
    LIMIT_MANIFEST_BYTES,
    LIMIT_PATH_BYTES,
    LIMIT_YAML_ALIASES,
    LIMIT_YAML_DEPTH,
    LIMIT_YAML_NODES,
    LimitError,
    ResourceLimits,
    read_bytes_bounded,
)
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


class _BoundedSafeLoader(yaml.SafeLoader):
    """A ``SafeLoader`` that refuses excessive depth, node, and alias counts.

    Ceilings come from a :class:`~beacon.core.limits.ResourceLimits` instance so
    the manifest parser cannot be forced into unbounded recursion or expansion.
    """

    def __init__(self, stream: Any, *, limits: ResourceLimits) -> None:
        super().__init__(stream)
        self._limits = limits
        self._node_count = 0
        self._depth = 0
        self._alias_count = 0

    def compose_node(self, parent: Any, index: Any) -> Any:  # noqa: ANN401
        if self.check_event(yaml.events.AliasEvent):
            self._alias_count += 1
            if self._alias_count > self._limits.yaml_aliases:
                _raise_yaml_limit(LIMIT_YAML_ALIASES, self._limits.yaml_aliases)
        self._node_count += 1
        if self._node_count > self._limits.yaml_nodes:
            _raise_yaml_limit(LIMIT_YAML_NODES, self._limits.yaml_nodes)
        return super().compose_node(parent, index)

    def compose_sequence_node(self, anchor: Any) -> Any:  # noqa: ANN401
        self._depth += 1
        if self._depth > self._limits.yaml_depth:
            _raise_yaml_limit(LIMIT_YAML_DEPTH, self._limits.yaml_depth)
        try:
            return super().compose_sequence_node(anchor)
        finally:
            self._depth -= 1

    def compose_mapping_node(self, anchor: Any) -> Any:  # noqa: ANN401
        self._depth += 1
        if self._depth > self._limits.yaml_depth:
            _raise_yaml_limit(LIMIT_YAML_DEPTH, self._limits.yaml_depth)
        try:
            return super().compose_mapping_node(anchor)
        finally:
            self._depth -= 1


def _raise_yaml_limit(code: str, ceiling: int) -> None:
    raise LimitError(
        code,
        f"resource limit exceeded: {code} (limit={ceiling})",
        limit=code,
        limit_value=ceiling,
    )


def load_beacon_manifest(
    path: str | Path, *, limits: ResourceLimits | None = None
) -> BeaconManifest:
    """Load and parse a ``beacon.yaml`` file into a :class:`BeaconManifest`.

    Raises :class:`ManifestError` if the file is missing, is not a mapping, or
    has a structurally invalid shape. Raises :class:`LimitError` if the manifest
    source exceeds ``limits.manifest_bytes`` or the YAML exceeds the depth,
    node, or alias ceilings. Byte ceilings are checked *before* decoding so a
    large file is refused without parsing.
    """
    active = limits if limits is not None else ResourceLimits()
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ManifestError(f"manifest not found: {manifest_path}")
    raw_bytes = read_bytes_bounded(
        manifest_path,
        ceiling=active.manifest_bytes,
        code=LIMIT_MANIFEST_BYTES,
        field="manifest_bytes",
    )
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ManifestError(
            f"invalid UTF-8 in {manifest_path}: {exc}"
        ) from exc
    try:
        raw = yaml.load(text, Loader=lambda s: _BoundedSafeLoader(s, limits=active))
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough detail
        raise ManifestError(f"invalid YAML in {manifest_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest root must be a mapping, got {type(raw).__name__}")
    manifest = parse_manifest(raw)
    _enforce_manifest_limits(manifest, active)
    return manifest


def _enforce_manifest_limits(
    manifest: BeaconManifest, limits: ResourceLimits
) -> None:
    """Refuse bounded manifest fields before validation performs filesystem work."""
    if len(manifest.canonical_docs) > limits.documents:
        raise LimitError(
            LIMIT_DOCUMENTS,
            f"resource limit exceeded: {LIMIT_DOCUMENTS} "
            f"(limit={limits.documents}, actual={len(manifest.canonical_docs)})",
            limit="documents",
            limit_value=limits.documents,
        )
    for doc in manifest.canonical_docs:
        path_size = len(doc.path.encode("utf-8"))
        if path_size > limits.path_bytes:
            raise LimitError(
                LIMIT_PATH_BYTES,
                f"resource limit exceeded: {LIMIT_PATH_BYTES} "
                f"(limit={limits.path_bytes}, actual={path_size})",
                limit="path_bytes",
                limit_value=limits.path_bytes,
            )


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
