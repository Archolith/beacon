# beacon — Architecture

## Overview

Beacon is a self-describing, machine-readable project knowledge surface for coding agents.
Instead of stuffing a README into a context window, a project publishes a `beacon.yaml`
manifest and an MCP endpoint that agents can query with structured tools: project overview,
agent onboarding, concept explanation, document search, and guardrails.

Beacon v0 is **manifest-driven**: all answers derive deterministically from the parsed
`beacon.yaml` + an in-memory index of the project's canonical docs. No LLM generation, no
Neo4j, no external service dependency. The design stays honest — every response carries
`status` (current|experimental|uncertain|mixed), `confidence`, and `sources`.

The provider boundary is explicit so a richer Menhir-backed implementation (temporal memory,
structure graph, git history) can be swapped in later without touching the tools.

```
┌────────────────────────────────────────────────┐
│  MCP Server (stdio)                            │
│  archolith_mcp_framework gateway               │
│  5 tools · all readonly · all always_visible   │
├────────────────────────────────────────────────┤
│  Beacon Tools                                  │
│  ProjectOverview · AgentOnboarding · Search    │
│  ExplainConcept · Guardrails                   │
├────────────────────────────────────────────────┤
│  BeaconProvider Protocol                       │
│  ManifestBeaconProvider (v0)                   │
│  ← future: live memory provider (Menhir first) │
├────────────────────────────────────────────────┤
│  beacon-core                                   │
│  BeaconManifest schema · YAML loader           │
│  Validator · DocIndex (heading-chunked)        │
└────────────────────────────────────────────────┘
         ↑
   beacon.yaml + canonical docs on disk
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| MCP framework | archolith_mcp_framework (create_gateway_server) + FastMCP 3.x |
| YAML parsing | PyYAML ≥6 |
| Settings | frozen dataclass + from_env() pattern (no Pydantic) |
| Loopback HTTP | Starlette + Uvicorn; immutable GET/HEAD representations |
| Tests | pytest + pytest-asyncio |
| Entry point | `python -m beacon` / `beacon` → `beacon.main:main` |

## Distribution

- Distribution: `archolith-beacon`
- Import package and console command: `beacon`
- Current release-branch version: `0.2.0rc2`, single-sourced from `beacon.__version__`
- Supported interpreters: CPython 3.12, 3.13, and 3.14
- Runtime framework dependency: `archolith-mcp-framework>=0.2,<0.3`
- `archolith-mcp-framework==0.2.0` is available from PyPI; Beacon RC2 publication remains pending.

## Package Layout

```
src/beacon/
├── __init__.py          single-source package version
├── __main__.py          python -m beacon entry
├── main.py              typer CLI: init / validate / inspect / export / serve / serve-http
├── http_api.py          immutable discovery, identity, orientation, full snapshot, and health routes
├── config/
│   └── settings.py      BeaconSettings (frozen dataclass, from_env)
├── core/
│   ├── schema.py        BeaconManifest + all answer-contract frozen dataclasses
│   ├── limits.py        frozen ResourceLimits model + stable limit error codes
│   ├── loader.py        load_beacon_manifest(path) → BeaconManifest (bounded PyYAML)
│   ├── paths.py         canonical-doc containment boundary + unsafe-path diagnostic
│   ├── validator.py     validate_beacon_manifest(), require_valid_manifest(), stable diagnostic codes
│   ├── citation_digest.py  sha256 digests that pin cited text; drift is `source_changed`
│   ├── policy.py        serving/publication policy + explicit acknowledgement (parse/evaluate)
│   ├── snapshot.py      static snapshot build + in-memory metadata-only derivation
│   ├── chunk_resources.py  versioned chunk index, stable IDs, budgets, static resources
│   ├── knowledge_resources.py  concept/guardrail indexes and static resources
│   └── doc_index.py     DocIndex, DocChunk — heading-chunked, keyword search
├── build/               `beacon build`: policy.py (source precedence), requirements.py (catalogue), project.py, snapshot.py
├── sources/             build sources: git.py, memory.py + memory_client.py, declared.py (the project's own files)
├── provider/
│   ├── base.py          @runtime_checkable BeaconProvider Protocol (5 methods)
│   └── manifest_provider.py  ManifestBeaconProvider — v0 deterministic impl
└── mcp/
    ├── contracts.py     BeaconBaseTool base class (register/execute/render)
    ├── lifecycle.py     beacon_lifespan — loads manifest at startup, module-level slot
    ├── server.py        create_gateway_server("beacon", always_visible=[...])
    └── tools/
        ├── __init__.py              ALL_TOOLS + register_all_tools
        ├── project_overview.py      beacon_project_overview
        ├── agent_onboarding.py      beacon_agent_onboarding
        ├── search.py                beacon_search
        ├── explain_concept.py       beacon_explain_concept
        └── guardrails.py            beacon_guardrails
```

## Data Flow

```
startup:
  BeaconSettings.from_env()
    → load BEACON_MANIFEST_PATH (YAML → BeaconManifest)
    → require_valid_manifest() [hard fail if errors]
    → DocIndex.from_docs(canonical_docs, docs_root=BEACON_DOCS_ROOT)
    → ManifestBeaconProvider stored in module-level _provider slot

tool call:
  MCP client → tool handler
    → BeaconBaseTool.execute()
    → tool.endpoint(...) → provider.<method>(...)
    → ManifestBeaconProvider reads manifest + doc_index (in-memory, sync)
    → returns frozen answer-contract dataclass
    → render_json(to_payload(result)) → JSON string to client
```

The stdio entry point loads dotenv first, then forces
`FASTMCP_CHECK_FOR_UPDATES=off` and `FASTMCP_SHOW_SERVER_BANNER=false` before importing the
framework. Runtime startup therefore performs no update check and emits no FastMCP banner.
Expected resource refusals preserve their stable public limit code. Any other tool exception is
logged server-side and reduced to a generic `internal_error` response so private paths or secrets in
exception text never cross the MCP boundary.

`beacon serve --snapshot S --transport http` runs the same FastMCP server object over
Streamable HTTP at `http://<host>:<port>/mcp` (`--host` default `127.0.0.1`, `--port`
default `8766`). It is snapshot-only (`serve_http_requires_snapshot` otherwise) and
loopback-only through the `_require_loopback` gate shared with `serve-http`; it is
direct, unverified serving until the trust plan's broker and signing phases land.
`_run_mcp_http` pre-binds the socket (`http_bind_failed`), runs uvicorn without an access
log, and wraps the app in `beacon.loopback_guard.LoopbackGuard`, which refuses a
non-loopback `Host` (421) or browser `Origin` (403) against DNS rebinding.

### Loopback HTTP data flow

`beacon serve-http` applies the export publication, path, resource, and secret gates, then builds one
embedded snapshot. `http_api.create_http_app()` serializes that full representation and derives
identity and metadata-only orientation representations from the same approved in-memory value.
Before binding, the CLI separately captures bounded Git and source-digest evidence for the immutable
status companion. Discovery descriptor 1.5 advertises `/v1/snapshot/identity`, `/v1/status`,
`/v1/snapshot/orientation`, and `/v1/snapshot` with independent SHA-256 digests and exact byte sizes.
All representations are immutable for the process lifetime, support GET/HEAD plus `If-None-Match`,
and use snapshot schema 1.0. Identity carries only project, purpose, audiences, and current focus;
orientation adds manifest knowledge, citations, document hashes, and chunk inventory without chunk
bodies. Status separates source-cited maintainer declarations from startup-observed evidence and
states that it is unsigned and self-reported. Each lighter tier links forward. `/beacon.json`
remains byte-identical to the full route.
The versioned `/v1/chunks` companion index adds stable location-derived IDs, parent role/status,
exact text/response byte costs, resource hashes, and individual `/v1/chunks/{id}` retrieval without
changing snapshot 1.0. Index and resource bytes are bounded, precomputed, independently cacheable,
and tied to the full snapshot digest. The listener is restricted to `127.0.0.1`, has no CORS or
access logs, and exposes no free-text query capability. Companion `/v1/concepts` and
`/v1/guardrails` indexes map manifest logical IDs to opaque stable resource IDs, exact byte costs,
and independent digests; their item routes return one complete source-cited record without changing
snapshot 1.0 or rereading source files.

## Config / Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `BEACON_MANIFEST_PATH` | **yes** | — | Absolute path to `beacon.yaml` |
| `BEACON_DOCS_ROOT` | no | dir of manifest | Root for resolving canonical doc paths |
| `BEACON_VALIDATE_ON_LOAD` | no | `true` | Hard-fail at startup on manifest errors |
| `BEACON_LOG_LEVEL` | no | `WARNING` | Python logging level |
| `BEACON_HOST` | no | `127.0.0.1` | Remote transport host (stdio ignores) |
| `BEACON_PORT` | no | `8788` | Remote transport port (stdio ignores) |
| `BEACON_MAX_MANIFEST_BYTES` | no | `1048576` | Manifest source byte ceiling |
| `BEACON_MAX_DOCUMENTS` | no | `256` | Canonical document count ceiling |
| `BEACON_MAX_DOCUMENT_BYTES` | no | `2097152` | One canonical document byte ceiling |
| `BEACON_MAX_TOTAL_DOCUMENT_BYTES` | no | `20971520` | Aggregate canonical doc byte ceiling |
| `BEACON_MAX_CHUNKS` | no | `10000` | Total heading chunk ceiling |
| `BEACON_MAX_SNAPSHOT_BYTES` | no | `52428800` | Snapshot output byte ceiling (export) |

## Resource Limits

`beacon.core.limits.ResourceLimits` is the frozen, immutable ceiling model. Its standard
defaults (addendum §4) describe a small-to-medium repository profile; the six byte/count
ceilings above are overridable via `BEACON_MAX_*` environment variables, while the YAML
depth (`32`), parsed-node (`50 000`), and alias (`50`) ceilings and the path-UTF-8-byte
(`1024`), query-UTF-8-byte (`4096`), search-result (`100`), and initialization-report
(`5 MiB`) ceilings are fixed for v0.2. `beacon init` enforces the initialization-report ceiling
before its atomic JSON report write.

Precedence is `CLI override > environment > default`, exposed reusably through
`resource_limits_from_env(env)` and `ResourceLimits.apply_overrides(...)`. Every refused
value carries a stable, non-secret diagnostic `code` (e.g. `limit_manifest_bytes`,
`limit_yaml_depth`, `limit_documents`, `limit_query_bytes`) and never embeds document
content or secret values. Override values that are negative, non-integer, or overflowing are
rejected with `limit_invalid_value` rather than truncated.

The bounded readers enforce ceilings at the earliest existing boundary:

- `core/loader.py` — checks manifest source bytes *before* decoding, then enforces YAML
  depth/node/alias caps via a bounded `yaml.SafeLoader` subclass.
- `core/doc_index.py` — enforces canonical-document count, per-document bytes, aggregate
  document bytes, relative-path UTF-8 bytes, canonical-path containment, and total heading-chunk
  count. Containment is enforced even when semantic validation is disabled.
- `provider/manifest_provider.py` — enforces query/task-hint UTF-8 bytes and the search
  result-limit ceiling on free-text tool inputs.

`BeaconSettings` carries a `limits` profile so server startup honours environment overrides;
`ManifestBeaconProvider` threads it into the loader and doc index. Valid inputs and existing
manifest 0.1 behavior are unchanged.

## CLI

`src/beacon/main.py` is a `typer` app with one eager option, one default action, and two subcommands:

| Command | Purpose |
|---------|---------|
| `beacon --version` | Prints the single-source package version without loading a manifest or importing/starting the MCP server. |
| `beacon` (no subcommand) | Starts the MCP stdio server — loads `.env` via `ENV_FILE`, configures logging, calls `run_server(mcp)`. |
| `beacon validate PATH` | Loads and validates a `beacon.yaml`; exits 0 with 0 errors, exits 1 on parse failure or any error-level issue. Warnings print but don't fail the exit code. |
| `beacon inspect PATH` | Loads a manifest, validates it (hard-fails on errors), then calls all five `ManifestBeaconProvider` methods directly and prints a human-readable summary of each — a local smoke test before wiring an MCP client. |

`validate`/`inspect` construct a `ManifestBeaconProvider` in-process (no MCP transport, no server startup) and reuse the same `validate_beacon_manifest()` used at server startup.

## MCP Tools

All five tools are `required_tier="readonly"` and `always_visible`.

| Tool | Purpose | Key inputs |
|------|---------|-----------|
| `beacon_project_overview` | What is this project, what's current | `audience`, `depth` |
| `beacon_agent_onboarding` | Minimum context to start safely | `task_hint`, `risk_tolerance` |
| `beacon_search` | Keyword search over docs + concepts + guardrails | `query`, `source_types`, `limit` |
| `beacon_explain_concept` | Explain project-specific vocabulary | `concept`, `depth` |
| `beacon_guardrails` | Rules and risky files for a given task | `task_hint` |

Every response includes `status`, `confidence`, `sources[]`, and `next_actions[]`.

## Answer Contract

Every provider method returns a frozen dataclass from `beacon.core.schema`:

```python
@dataclass(frozen=True)
class ProjectOverview:
    summary: str
    status: str          # current | experimental | uncertain | mixed
    confidence: str      # low | medium | high
    sources: tuple[BeaconSource, ...]
    next_actions: tuple[str, ...]
    ...
```

`BeaconSource` carries `type`, `path`, `line_start`, `line_end`, `status` so every
claim is traceable to a file + line range.

## Provider Interface

```python
@runtime_checkable
class BeaconProvider(Protocol):
    def project_overview(self, *, audience, depth) -> ProjectOverview: ...
    def agent_onboarding(self, *, task_hint, risk_tolerance) -> AgentOnboarding: ...
    def search(self, *, query, source_types, limit) -> SearchResult: ...
    def explain_concept(self, *, concept, depth) -> ConceptExplanation: ...
    def guardrails(self, *, task_hint) -> GuardrailResponse: ...
```

v0 ships `ManifestBeaconProvider`. A future live memory provider plugs in here.

## Manifest Schema (beacon.yaml)

Top-level sections:

| Key | Purpose |
|-----|---------|
| `beacon_version` | Schema version (currently `"0.1"`) |
| `project` | name, tagline, description, status, repository, language, license |
| `purpose` | one_sentence, problem, non_goals |
| `audiences` | list of target user types |
| `current_focus` | active work areas |
| `project_state` | optional source-cited active work, recent completions, blockers, and pending decisions |
| `core_concepts` | id, name, definition, why_it_exists, status, related_concepts |
| `canonical_docs` | path, role, status, title — resolved against BEACON_DOCS_ROOT |
| `agent_guidance` | read_first, safe_first_tasks, avoid_without_review |
| `build_and_test` | setup, test, benchmark commands |
| `guardrails` | id, rule, scope, severity, applies_to |

The loopback HTTP companion `/v1/status` keeps this declared state separate from startup-observed
evidence. At process start Beacon compares the approved manifest and canonical-document digests,
records Git commit/branch/dirty state when Git is available, and timestamps that observation. The
payload is immutable until restart and explicitly remains self-reported and unsigned; remote trust
and signed attestation are later protocol layers.

## Validation

`validate_beacon_manifest()` catches:
- missing `project.name` / `project.description` (error)
- empty `canonical_docs` (error)
- duplicate concept ids (error)
- duplicate guardrail ids (error)
- dangling canonical doc paths when `docs_root` is provided (error)
- absolute/traversing canonical paths and symlink escapes (error; `unsafe_canonical_path`)
- unknown status vocabulary (warning)
- concept referencing unknown related id (warning)
- missing `build_and_test.test` command (warning)

Every finding carries a stable, non-secret diagnostic `code` on `ValidationIssue`
alongside the legacy `severity` / `where` / `message` fields, so existing consumers are
unaffected. The addendum's publication-warning codes are emitted, including the
acknowledgeable absent-test (`test_command_missing`) and absent-guardrail
(`guardrails_missing`) codes, plus `project_status_unknown`, `purpose_missing`,
`concept_definition_missing`, `related_concept_unknown`, `knowledge_status_invalid`, and
`canonical_doc_duplicate`. Error findings keep error severity and their own stable codes.

`require_valid_manifest()` raises `ManifestValidationError` on any error — used at startup.

The loader is type-strict. Missing optional fields receive their documented defaults, while an
explicit YAML `null` or another wrong scalar/container type is malformed and raises
`ManifestError`. Source line numbers must be positive integers and `line_end` cannot precede
`line_start`.

### Serving/publication policy and acknowledgement

`beacon.core.policy` provides the reusable policy evaluation that the CLI unit will wire up:

- `evaluate_policy(report, *, acknowledgements=())` returns a `PolicyEvaluation` with
  `servable` (no errors) and `publishable` (no errors *and* no unresolved publication
  warnings). Normal `validate` uses `servable`; strict `validate` and `export` use
  `publishable`; `serve` uses `servable` while warnings stay visible.
- Only warnings whose code is in `PUBLICATION_WARNING_CODES` block publication. Warnings
  such as `guardrail_severity_invalid` are reported but do not block publication.
- An acknowledgement is an explicit, reasoned, in-memory override for one allowlisted
  warning (`test_command_missing`, `guardrails_missing`). `parse_acknowledgement(raw)` /
  `parse_acknowledgements(raws)` validate `CODE=REASON` (reason trimmed, non-empty,
  ≥10 characters) and reject malformed, unknown, duplicate, or unallowlisted codes with a
  stable `AcknowledgementError`. An acknowledgement changes the policy disposition but
  never mutates the diagnostic severity/facts or `beacon.yaml`; the reason is recorded on
  `PolicyEvaluation.acknowledged` for reporting and future export metadata.

## Doc Index

`DocIndex.from_docs()` chunks Markdown files at ATX headings, producing `DocChunk` records:

```python
@dataclass(frozen=True)
class DocChunk:
    path: str
    heading_path: tuple[str, ...]   # ["Architecture", "Retrieval"]
    text: str
    start_line: int
    end_line: int
    status: str
```

`DocIndex.search(query)` scores chunks by bag-of-words overlap with a 1.5× boost for
heading matches, normalized by chunk size. Deterministic, no embeddings.

## Adding a New Tool

1. Create `src/beacon/mcp/tools/<name>.py` — subclass `BeaconBaseTool`, set `name` +
   `description`, implement `async endpoint(...)`.
2. Add the new method to `BeaconProvider` Protocol in `provider/base.py`.
3. Implement it in `ManifestBeaconProvider`.
4. Import and add to `ALL_TOOLS` in `mcp/tools/__init__.py`.
5. Add to `always_visible` in `mcp/server.py` if it should be pinned.
6. Add offline tests in `tests/`.

## Future: live memory provider

A live provider (Menhir first) would implement the same `BeaconProvider` Protocol through the
backend-neutral memory-provider contract, never Menhir internals, and answer queries using what
Menhir offers through that contract, for example:
- `recall_memories` for semantic search over project memories
- `query_structure` for file/symbol/blast-radius data
- temporal reasoning (Chronostratum) for "what changed" and "what is current"
- decision history and superseded-fact tracking

The MCP tools and answer contract stay unchanged.
