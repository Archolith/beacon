"""Parse ``beacon.yaml`` into the typed :class:`BeaconManifest`.

The loader is intentionally forgiving about *missing* keys (it fills defaults)
but strict about *types* (a mapping where a list is expected raises). Semantic
checks -- duplicate concept ids, missing canonical docs, dangling paths -- live
in :mod:`beacon.core.validator`, not here.
"""

from __future__ import annotations

import re
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
    BeaconProjectState,
    BeaconPurpose,
    BeaconSource,
    BeaconStateItem,
)

_MISSING = object()
_MAX_PROJECT_STATE_ITEMS = 64
_MAX_PROJECT_STATE_SOURCES = 64


class ManifestError(ValueError):
    """Raised when a manifest cannot be parsed into the typed schema.

    ``str(exc)`` keeps the full loader message for library callers. ``detail``
    is the user-facing diagnostic that is safe to print in CLI output: it names
    the field or YAML location and the error kind, but never the manifest path,
    a source snippet, or the offending value. When *detail* is omitted the
    message itself is the detail, which holds for every message built only from
    field names and Python type names.
    """

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = message if detail is None else detail


#: Quoted fragments in PyYAML problem text that are grammar tokens, not user data.
_YAML_TOKEN_RE = re.compile(r"^(?:<[a-z ]+>|[^A-Za-z0-9]{1,2}|\\[A-Za-z])$")
_YAML_QUOTED_RE = re.compile(r"'([^']*)'")


def _yaml_error_detail(exc: yaml.YAMLError) -> str:
    """Return a value-free description of a YAML parse error.

    Keeps the error kind, PyYAML's fixed problem wording, and the 1-based
    line/column. Quoted fragments that could carry manifest content (alias
    names, scalar text) are replaced by ``'<redacted>'``; only grammar tokens
    such as ``']'`` or ``'<stream end>'`` are kept. The source snippet PyYAML
    appends to ``str(exc)`` is never used.
    """
    kind = type(exc).__name__
    problem = getattr(exc, "problem", None)
    mark = getattr(exc, "problem_mark", None)
    text = kind
    if isinstance(problem, str) and problem.strip():

        def _keep_token(match: re.Match[str]) -> str:
            fragment = match.group(1)
            return match.group(0) if _YAML_TOKEN_RE.match(fragment) else "'<redacted>'"

        text = f"{kind}: {_YAML_QUOTED_RE.sub(_keep_token, problem.strip())}"
    if mark is not None:
        text = f"{text} at line {mark.line + 1}, column {mark.column + 1}"
    return f"invalid YAML ({text})"


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
        raise ManifestError(f"manifest not found: {manifest_path}", detail="manifest not found")
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
            f"invalid UTF-8 in {manifest_path}: {exc}",
            detail=f"invalid UTF-8 at byte offset {exc.start}",
        ) from exc
    try:
        # _BoundedSafeLoader subclasses yaml.SafeLoader, so this yaml.load call
        # never uses the unsafe DefaultLoader; the explicit Loader also enforces
        # the depth/node/alias ceilings. nosec B506: safe loader guaranteed.
        raw = yaml.load(text, Loader=lambda s: _BoundedSafeLoader(s, limits=active))  # nosec B506
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough detail
        raise ManifestError(
            f"invalid YAML in {manifest_path}: {exc}", detail=_yaml_error_detail(exc)
        ) from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest root must be a mapping, got {type(raw).__name__}")
    manifest = parse_manifest(raw)
    _enforce_manifest_limits(manifest, active)
    return manifest


def _enforce_manifest_limits(manifest: BeaconManifest, limits: ResourceLimits) -> None:
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
    project = _parse_project(_as_map(raw.get("project", _MISSING), "project"))
    return BeaconManifest(
        beacon_version=_opt_str(raw.get("beacon_version", _MISSING), "beacon_version", "0.1"),
        project=project,
        purpose=_parse_purpose(_as_map(raw.get("purpose", _MISSING), "purpose", optional=True)),
        audiences=_str_tuple(raw.get("audiences", _MISSING)),
        current_focus=_str_tuple(raw.get("current_focus", _MISSING)),
        core_concepts=tuple(
            _parse_concept(item)
            for item in _as_list(raw.get("core_concepts", _MISSING), "core_concepts")
        ),
        canonical_docs=tuple(
            _parse_doc(item)
            for item in _as_list(raw.get("canonical_docs", _MISSING), "canonical_docs")
        ),
        agent_guidance=_parse_guidance(
            _as_map(
                raw.get("agent_guidance", _MISSING),
                "agent_guidance",
                optional=True,
            )
        ),
        build_and_test=_parse_build_test(
            _as_map(
                raw.get("build_and_test", _MISSING),
                "build_and_test",
                optional=True,
            )
        ),
        guardrails=tuple(
            _parse_guardrail(item)
            for item in _as_list(raw.get("guardrails", _MISSING), "guardrails")
        ),
        project_state=_parse_project_state(
            _as_map(raw.get("project_state", _MISSING), "project_state", optional=True)
        ),
    )


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------


def _parse_project(data: dict[str, Any]) -> BeaconProjectInfo:
    return BeaconProjectInfo(
        name=_opt_str(data.get("name", _MISSING), "project.name"),
        tagline=_opt_str(data.get("tagline", _MISSING), "project.tagline"),
        description=_collapse(data.get("description", _MISSING), "project.description"),
        status=_opt_str(data.get("status", _MISSING), "project.status", "experimental"),
        repository=_opt_str(data.get("repository", _MISSING), "project.repository"),
        primary_language=_opt_str(
            data.get("primary_language", _MISSING), "project.primary_language"
        ),
        license=_opt_str(data.get("license", _MISSING), "project.license"),
    )


def _parse_purpose(data: dict[str, Any]) -> BeaconPurpose:
    return BeaconPurpose(
        one_sentence=_collapse(data.get("one_sentence", _MISSING), "purpose.one_sentence"),
        problem=_collapse(data.get("problem", _MISSING), "purpose.problem"),
        non_goals=_str_tuple(data.get("non_goals", _MISSING)),
    )


def _parse_concept(item: Any) -> BeaconConcept:
    data = _as_map(item, "core_concepts[]")
    if "id" not in data:
        raise ManifestError("each core_concepts entry needs an 'id'")
    concept_id = _opt_str(data["id"], "core_concepts[].id")
    definition = data["description"] if "description" in data else data.get("definition", _MISSING)
    return BeaconConcept(
        id=concept_id,
        name=_opt_str(data.get("name", _MISSING), "core_concepts[].name", concept_id),
        definition=_collapse(definition, "core_concepts[].definition"),
        why_it_exists=_collapse(
            data.get("why_it_exists", _MISSING), "core_concepts[].why_it_exists"
        ),
        status=_opt_str(data.get("status", _MISSING), "core_concepts[].status", "current"),
        related_concepts=_str_tuple(data.get("related_concepts", _MISSING)),
        implementation_locations=_str_tuple(data.get("implementation_locations", _MISSING)),
        sources=_parse_sources(data.get("sources", _MISSING)),
    )


def _parse_doc(item: Any) -> BeaconDoc:
    data = _as_map(item, "canonical_docs[]")
    if "path" not in data:
        raise ManifestError("each canonical_docs entry needs a 'path'")
    return BeaconDoc(
        path=_opt_str(data["path"], "canonical_docs[].path"),
        role=_opt_str(data.get("role", _MISSING), "canonical_docs[].role"),
        status=_opt_str(data.get("status", _MISSING), "canonical_docs[].status", "current"),
        title=_opt_str(data.get("title", _MISSING), "canonical_docs[].title"),
    )


def _parse_guardrail(item: Any) -> BeaconGuardrail:
    data = _as_map(item, "guardrails[]")
    if "id" not in data:
        raise ManifestError("each guardrails entry needs an 'id'")
    return BeaconGuardrail(
        id=_opt_str(data["id"], "guardrails[].id"),
        rule=_collapse(data.get("rule", _MISSING), "guardrails[].rule"),
        scope=_opt_str(data.get("scope", _MISSING), "guardrails[].scope"),
        severity=_opt_str(data.get("severity", _MISSING), "guardrails[].severity", "medium"),
        applies_to=_str_tuple(data.get("applies_to", _MISSING)),
        sources=_parse_sources(data.get("sources", _MISSING)),
    )


def _parse_guidance(data: dict[str, Any]) -> BeaconAgentGuidance:
    return BeaconAgentGuidance(
        read_first=_str_tuple(data.get("read_first", _MISSING)),
        safe_first_tasks=_str_tuple(data.get("safe_first_tasks", _MISSING)),
        avoid_without_review=_str_tuple(
            data["avoid_without_review"]
            if "avoid_without_review" in data
            else data.get("avoid_without_maintainer_review", _MISSING)
        ),
        expected_behavior=_str_tuple(data.get("expected_behavior", _MISSING)),
    )


def _parse_build_test(data: dict[str, Any]) -> BeaconBuildTest:
    return BeaconBuildTest(
        setup=_opt_str(data.get("setup", _MISSING), "build_and_test.setup"),
        test=_opt_str(data.get("test", _MISSING), "build_and_test.test"),
        benchmark=_opt_str(data.get("benchmark", _MISSING), "build_and_test.benchmark"),
    )


def _parse_project_state(data: dict[str, Any]) -> BeaconProjectState:
    active_raw = data.get("active_work", _MISSING)
    active_work = None
    if active_raw is not _MISSING:
        active_work = _parse_state_item(active_raw, "project_state.active_work")
    return BeaconProjectState(
        active_work=active_work,
        recently_completed=_parse_state_items(
            data.get("recently_completed", _MISSING),
            "project_state.recently_completed",
        ),
        blockers=_parse_state_items(
            data.get("blockers", _MISSING),
            "project_state.blockers",
        ),
        pending_decisions=_parse_state_items(
            data.get("pending_decisions", _MISSING),
            "project_state.pending_decisions",
        ),
    )


def _parse_state_items(value: Any, where: str) -> tuple[BeaconStateItem, ...]:
    items = _as_list(value, where)
    if len(items) > _MAX_PROJECT_STATE_ITEMS:
        raise ManifestError(f"{where} must contain at most {_MAX_PROJECT_STATE_ITEMS} items")
    return tuple(_parse_state_item(item, f"{where}[]") for item in items)


def _parse_state_item(item: Any, where: str) -> BeaconStateItem:
    data = _as_map(item, where)
    if "title" not in data:
        raise ManifestError(f"{where} needs a 'title'")
    sources = _parse_sources(data.get("sources", _MISSING))
    if len(sources) > _MAX_PROJECT_STATE_SOURCES:
        raise ManifestError(
            f"{where}.sources must contain at most {_MAX_PROJECT_STATE_SOURCES} items"
        )
    return BeaconStateItem(
        title=_bounded_state_text(data["title"], f"{where}.title", 512),
        summary=_bounded_state_text(data.get("summary", _MISSING), f"{where}.summary", 4096),
        next_step=_bounded_state_text(data.get("next_step", _MISSING), f"{where}.next_step", 4096),
        sources=sources,
    )


def _bounded_state_text(value: Any, field: str, maximum: int) -> str:
    text = _collapse(value, field)
    if len(text) > maximum:
        raise ManifestError(f"{field} must contain at most {maximum} characters")
    return text


def _parse_sources(value: Any) -> tuple[BeaconSource, ...]:
    if value is _MISSING:
        return ()
    sources: list[BeaconSource] = []
    for item in _as_list(value, "sources"):
        data = _as_map(item, "sources[]")
        line_start = _opt_line(data.get("line_start", _MISSING), "sources[].line_start")
        line_end = _opt_line(data.get("line_end", _MISSING), "sources[].line_end")
        if line_start is not None and line_end is not None and line_end < line_start:
            raise ManifestError("sources[].line_end must not precede line_start")
        sources.append(
            BeaconSource(
                type=_opt_str(data.get("type", _MISSING), "sources[].type", "doc"),
                title=_opt_str(data.get("title", _MISSING), "sources[].title"),
                path=_opt_str(data.get("path", _MISSING), "sources[].path"),
                url=_opt_str(data.get("url", _MISSING), "sources[].url"),
                line_start=line_start,
                line_end=line_end,
                status=_opt_str(data.get("status", _MISSING), "sources[].status", "current"),
            )
        )
    return tuple(sources)


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _as_map(value: Any, where: str, *, optional: bool = False) -> dict[str, Any]:
    if value is _MISSING:
        if optional:
            return {}
        raise ManifestError(f"missing required mapping: {where}")
    if not isinstance(value, dict):
        raise ManifestError(f"{where} must be a mapping, got {type(value).__name__}")
    return value


def _as_list(value: Any, where: str) -> list[Any]:
    if value is _MISSING:
        return []
    if not isinstance(value, list):
        raise ManifestError(f"{where} must be a list, got {type(value).__name__}")
    return value


def _str_tuple(value: Any) -> tuple[str, ...]:
    if value is _MISSING:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        if not all(isinstance(item, str) for item in value):
            raise ManifestError("expected a list of strings, got a non-string element")
        return tuple(value)
    raise ManifestError(f"expected a string or list of strings, got {type(value).__name__}")


def _opt_str(value: Any, field: str, default: str = "") -> str:
    """Require *value* to be a string when present; otherwise use *default*."""
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        raise ManifestError(f"{field} must be a string, got {type(value).__name__}")
    return value


def _collapse(value: Any, field: str) -> str:
    """Collapse YAML block-scalar whitespace into a single trimmed string.

    *value* must be a string when present. A missing field yields an empty
    string; an explicit YAML ``null`` is malformed.
    """
    if value is _MISSING:
        return ""
    if not isinstance(value, str):
        raise ManifestError(f"{field} must be a string, got {type(value).__name__}")
    return " ".join(value.split())


def _opt_line(value: Any, field: str) -> int | None:
    """Require *value* to be a positive integer when present (never a bool)."""
    if value is _MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"{field} must be a positive integer")
    if value <= 0:
        raise ManifestError(f"{field} must be a positive integer")
    return value
