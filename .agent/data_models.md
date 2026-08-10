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

Convenience method: `manifest.concept_by_id(id)` — case-insensitive lookup by id or name.

### BeaconProjectInfo

| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | Required — validator errors if empty |
| `tagline` | `str` | One-line pitch |
| `description` | `str` | Required — validator errors if empty |
| `status` | `str` | `experimental` \| `current` \| `stable` \| … |
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
| `path` | `str` | Relative to `BEACON_DOCS_ROOT` — validator checks existence |
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
| `line_start` | `int \| None` | 1-based start line |
| `line_end` | `int \| None` | 1-based end line |
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

---

## Validation Vocabulary

`KNOWLEDGE_STATUSES` (validator.py) — valid values for manifest `status` fields:
`current`, `experimental`, `planned`, `superseded`, `disputed`, `unknown`

`ANSWER_STATUSES` (schema.py) — valid values for answer `status` fields:
`current`, `experimental`, `uncertain`, `mixed`

`CONFIDENCE_LEVELS` (schema.py):
`low`, `medium`, `high`

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
