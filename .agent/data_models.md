# beacon — Data Models

All types live in `src/beacon/core/schema.py` as frozen dataclasses.
Nothing here uses Pydantic or ORM — pure Python, JSON-serializable via `to_payload()`.

## Manifest Types (input)

Parsed from `beacon.yaml` by `beacon.core.loader`.

### BeaconManifest

Top-level container. One per loaded manifest.

| Field | Type | Notes |
|-------|------|-------|
| `beacon_version` | `str` | Schema version, e.g. `"0.1"` |
| `project` | `BeaconProjectInfo` | Identity block |
| `purpose` | `BeaconPurpose` | Why it exists, non-goals |
| `audiences` | `tuple[str, ...]` | Target user types |
| `current_focus` | `tuple[str, ...]` | Active work areas |
| `core_concepts` | `tuple[BeaconConcept, ...]` | Registered vocabulary |
| `canonical_docs` | `tuple[BeaconDoc, ...]` | Docs an agent should read |
| `agent_guidance` | `BeaconAgentGuidance` | Read order, safe tasks, avoid list |
| `build_and_test` | `BeaconBuildTest` | Setup/test/benchmark commands |
| `guardrails` | `tuple[BeaconGuardrail, ...]` | How not to break the project |
| `project_state` | `BeaconProjectState` | Optional source-cited current-work state |

Convenience method: `manifest.concept_by_id(id)` — case-insensitive lookup by id or name.

### BeaconProjectState and BeaconStateItem

`BeaconProjectState` has zero or one `active_work` item plus bounded tuples for
`recently_completed`, `blockers`, and `pending_decisions`. Each `BeaconStateItem` carries `title`,
`summary`, `next_step`, and source citations. The whole section is optional-with-defaults, preserving
existing manifest `0.1` inputs. When an item is present without a citation, strict publication emits
the blocking `project_state_sources_missing` warning.

HTTP `/v1/status` publishes these declared values beside a separate immutable startup observation:
snapshot lineage, Git commit/branch/dirty state when available, source digest comparisons, and
observation time. Status companion schema `1.0` does not change snapshot schema `1.0`.

### BeaconProjectInfo

| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | Required — validator errors if empty |
| `tagline` | `str` | One-line pitch |
| `description` | `str` | Required — validator errors if empty |
| `status` | `str` | Controlled knowledge status; defaults to `experimental` |
| `repository` | `str` | URL or empty |
| `primary_language` | `str` | |
| `license` | `str` | |

### BeaconConcept

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Stable machine id — validator enforces uniqueness |
| `name` | `str` | Human display name |
| `definition` | `str` | What it is |
| `why_it_exists` | `str` | Motivation |
| `status` | `str` | `current` \| `experimental` \| `planned` \| `superseded` \| … |
| `related_concepts` | `tuple[str, ...]` | Other concept ids |
| `implementation_locations` | `tuple[str, ...]` | File paths where implemented |
| `sources` | `tuple[BeaconSource, ...]` | Citations |

### BeaconDoc

| Field | Type | Notes |
|-------|------|-------|
| `path` | `str` | Relative to `BEACON_DOCS_ROOT`; absolute, parent-traversing, and symlink-escaping paths are rejected before reads |
| `role` | `str` | `entrypoint` \| `architecture` \| `reference` \| `backlog` \| … |
| `status` | `str` | Knowledge status |
| `title` | `str` | Human title |

### BeaconGuardrail

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Stable id — validator enforces uniqueness |
| `rule` | `str` | The rule text |
| `scope` | `str` | Area it applies to (e.g. `database_schema`) |
| `severity` | `str` | `low` \| `medium` \| `high` |
| `applies_to` | `tuple[str, ...]` | File paths or module names |
| `sources` | `tuple[BeaconSource, ...]` | |

### BeaconSource

Traceable reference backing a claim. Used in both manifest types and answer responses.

| Field | Type | Notes |
|-------|------|-------|
| `type` | `str` | `doc` \| `file` \| `symbol` \| `commit` \| `manifest` \| `memory` \| … |
| `title` | `str` | Human-readable label |
| `path` | `str` | Relative file path |
| `url` | `str` | URL if applicable |
| `line_start` | `int \| None` | Positive, 1-based start line |
| `line_end` | `int \| None` | Positive end line; cannot precede `line_start` |
| `status` | `str` | Knowledge status at citation point |

### BeaconAgentGuidance

| Field | Type |
|-------|------|
| `read_first` | `tuple[str, ...]` — doc paths in suggested order |
| `safe_first_tasks` | `tuple[str, ...]` — low-risk contribution ideas |
| `avoid_without_review` | `tuple[str, ...]` — things not to touch casually |
| `expected_behavior` | `tuple[str, ...]` — norms for agent behavior |

### BeaconBuildTest

| Field | Type |
|-------|------|
| `setup` | `str` — install/env command |
| `test` | `str` — test command |
| `benchmark` | `str` — benchmark command |

---

## Answer-Contract Types (output)

Returned by `BeaconProvider` methods and serialized to JSON by the MCP tools via
`to_payload(obj)` → `render_json(payload)`.

Every answer type carries the same four top-level provenance fields:

| Field | Type | Values |
|-------|------|--------|
| `status` | `str` | `current` \| `experimental` \| `uncertain` \| `mixed` |
| `confidence` | `str` | `low` \| `medium` \| `high` |
| `sources` | `tuple[BeaconSource, ...]` | citations for claims made |
| `next_actions` | `tuple[str, ...]` | suggested follow-up queries |

### ProjectOverview

| Field | Type |
|-------|------|
| `summary` | `str` — one-paragraph project explanation |
| `problem` | `str` — the problem it solves |
| `current_status` | `str` — project lifecycle status |
| `core_components` | `tuple[str, ...]` — "Name (status)" strings |
| `read_next` | `tuple[str, ...]` — doc paths to read |
| + provenance fields | |

### AgentOnboarding

| Field | Type |
|-------|------|
| `orientation` | `str` — project summary, optionally scoped to task |
| `relevant_docs` | `tuple[str, ...]` — canonical docs to read first |
| `relevant_files` | `tuple[str, ...]` — specific files for the task hint |
| `concepts_to_understand` | `tuple[str, ...]` — concept names |
| `safe_first_steps` | `tuple[str, ...]` — low-risk starting actions |
| `do_not_touch` | `tuple[str, ...]` — avoid-without-review list |
| `commands` | `tuple[str, ...]` — setup and test commands |
| + provenance fields | |

### SearchResult + SearchHit

`SearchResult`:

| Field | Type |
|-------|------|
| `answer` | `str` — summary of results |
| `results` | `tuple[SearchHit, ...]` |
| + provenance fields | |

`SearchHit`:

| Field | Type |
|-------|------|
| `title` | `str` |
| `source_type` | `str` — `concept` \| `doc` \| `guardrail` |
| `path` | `str` |
| `snippet` | `str` — up to 240 chars |
| `status` | `str` |
| `confidence` | `str` |
| `why_relevant` | `str` |

### ConceptExplanation

| Field | Type |
|-------|------|
| `concept` | `str` — resolved display name |
| `definition` | `str` |
| `why_it_exists` | `str` |
| `related_concepts` | `tuple[str, ...]` — concept ids |
| `implementation_locations` | `tuple[str, ...]` — file paths |
| + provenance fields | |

### GuardrailResponse

| Field | Type |
|-------|------|
| `rules` | `tuple[str, ...]` — "[severity] rule text" strings |
| `risky_files` | `tuple[str, ...]` — applies_to aggregated |
| `required_checks` | `tuple[str, ...]` — test/benchmark commands |
| `related_guardrails` | `tuple[str, ...]` — avoid_without_review list |
| + provenance fields | |

---

## Doc Index Types

Defined in `src/beacon/core/doc_index.py`.

### DocChunk

| Field | Type | Notes |
|-------|------|-------|
| `path` | `str` | Source file path (relative) |
| `heading_path` | `tuple[str, ...]` | Heading stack, e.g. `("Architecture", "Retrieval")` |
| `text` | `str` | Raw text of the chunk body |
| `start_line` | `int` | 1-based first line of body |
| `end_line` | `int` | 1-based last line of body |
| `status` | `str` | Inherited from the `BeaconDoc.status` |

Methods:
- `chunk.heading` — last element of `heading_path`
- `chunk.snippet(limit=240)` — truncated text for display
- `chunk.to_source()` — converts to `BeaconSource` with line range

### DocIndex

| Field | Type |
|-------|------|
| `chunks` | `tuple[DocChunk, ...]` |

Methods:
- `DocIndex.from_docs(docs, *, docs_root)` — build from manifest canonical docs
- `index.search(query, *, limit=8)` — returns `list[tuple[DocChunk, float]]` ranked by score

---

## Serialization

`to_payload(obj)` in `schema.py` calls `dataclasses.asdict()` which recursively
converts nested frozen dataclasses and tuples to dicts/lists ready for `json.dumps`.

`render_json(payload)` in `mcp/contracts.py` serializes with compact separators,
sorted keys, and a `datetime.isoformat()` fallback.

## Static HTTP Companion Catalogs

`src/beacon/core/knowledge_resources.py` derives two immutable companion catalogs from the
approved embedded snapshot's in-memory manifest data. `StaticKnowledgeCatalogs` contains
`concepts` and `guardrails`; each `StaticKnowledgeCatalog` carries canonical index bytes, its
SHA-256, and frozen `StaticKnowledgeResource` values containing opaque ID, canonical response
bytes, and response SHA-256.

Concept resource IDs use `k1-<32 hex>` and guardrail IDs use `g1-<32 hex>`, derived from kind plus
logical manifest ID. Logical IDs remain response data and never become route structure. Index
entries publish selector metadata, exact response bytes, and digest before retrieval. All index and
resource responses are version 1.0, bounded by the snapshot byte ceiling, independently cacheable,
and tied to a validated full-snapshot SHA-256 without changing snapshot schema 1.0. Construction
requires the exact typed concept/guardrail/source record shapes, so every served record conforms to
its published Draft 2020-12 resource schema.

---

## Validation Vocabulary

`KNOWLEDGE_STATUSES` (validator.py) — valid values for manifest `status` fields:
`current`, `experimental`, `planned`, `superseded`, `disputed`, `unknown`

The same vocabulary is checked on project, canonical-document, concept, and nested source status
fields. Explicit YAML `null` is not an alias for an omitted field: wrong scalar/container types
raise `ManifestError` during parsing.

Canonical document resolution is centralized in `core.paths.resolve_canonical_path()`. It returns
an absolute resolved path only when the target remains under the resolved docs root; otherwise it
raises `UnsafeCanonicalPath` with code `unsafe_canonical_path` and no target-path or file-content
detail.

`ANSWER_STATUSES` (schema.py) — valid values for answer `status` fields:
`current`, `experimental`, `uncertain`, `mixed`

`CONFIDENCE_LEVELS` (schema.py):
`low`, `medium`, `high`

---

## Validation Diagnostics and Policy

Defined in `src/beacon/core/validator.py` and `src/beacon/core/policy.py`.

### ValidationIssue

| Field | Type | Notes |
|-------|------|-------|
| `severity` | `str` | `error` \| `warning` |
| `where` | `str` | Manifest location of the finding |
| `message` | `str` | Human-readable description |
| `code` | `str` | Stable diagnostic code (e.g. `test_command_missing`); defaults to `legacy_issue` for legacy three-argument construction |

The `code` field is additive; legacy `severity` / `where` / `message` consumers are
unchanged. `ValidationReport` still exposes `errors`, `warnings`, and `ok`.

Recognized stable codes: `project_name_missing`, `project_description_missing`,
`beacon_version_missing`, `canonical_docs_missing`, `canonical_doc_duplicate`,
`canonical_doc_missing_file`, `concept_id_duplicate`, `concept_definition_missing`,
`related_concept_unknown`, `guardrail_id_duplicate`, `guardrail_severity_invalid`,
`guardrails_missing`, `test_command_missing`, `knowledge_status_invalid`,
`project_status_unknown`, `purpose_missing`, `legacy_issue`.

`PUBLICATION_WARNING_CODES` is the exact addendum §5 set of warnings that block
publication (strict validation / export) unless acknowledged. `VALIDATION_CODES` is every
emittable code.

### Acknowledgement (policy.py)

| Field | Type |
|-------|------|
| `code` | `str` — allowlisted code being acknowledged |
| `reason` | `str` — trimmed, non-empty, ≥10 characters |

- `parse_acknowledgement(raw)` / `parse_acknowledgements(raws)` parse `CODE=REASON` and
  reject malformed, unknown, duplicate, or unallowlisted codes via `AcknowledgementError`
  with a stable code (`ack_malformed`, `ack_unknown_code`, `ack_unallowlisted_code`,
  `ack_duplicate`, `ack_reason_empty`, `ack_reason_short`).
- Only `test_command_missing` and `guardrails_missing` are acknowledgeable in v0.2.
- Acknowledgements are in-memory only; they never modify `beacon.yaml`.

### PolicyEvaluation (policy.py)

| Field | Type |
|-------|------|
| `servable` | `bool` — no errors |
| `publishable` | `bool` — no errors and no unresolved publication warnings |
| `errors` | `tuple[ValidationIssue, ...]` |
| `unresolved_publication_warnings` | `tuple[ValidationIssue, ...]` |
| `acknowledged` | `tuple[tuple[ValidationIssue, Acknowledgement], ...]` |

`evaluate_policy(report, *, acknowledgements=())` computes the disposition; acknowledged
warnings preserve their original severity/code/where/message while recording the reason.

---

## Resource Limits

Defined in `src/beacon/core/limits.py`. `ResourceLimits` is a frozen dataclass with the six
overridable ceilings (`manifest_bytes`, `documents`, `document_bytes`,
`total_document_bytes`, `chunks`, `snapshot_bytes`) plus seven fixed ceilings
(`yaml_depth`, `yaml_nodes`, `yaml_aliases`, `path_bytes`, `query_bytes`, `result_limit`,
`init_report_bytes`).

- `resource_limits_from_env(env=None)` — defaults plus `BEACON_MAX_*` environment overrides.
- `ResourceLimits.apply_overrides(mapping, where=...)` — returns a new instance with explicit
  (e.g. CLI) overrides applied last (highest precedence).
- `LimitError` — carries a stable non-secret `code` (e.g. `limit_manifest_bytes`,
  `limit_yaml_nodes`, `limit_query_bytes`) and never embeds document content or secrets.
- Invalid override values (negative, non-integer, overflowing) raise `LimitError` with
  code `limit_invalid_value` instead of being silently truncated.
