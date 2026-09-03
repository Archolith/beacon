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
│  archolith_mcp_framework gateway                     │
│  5 tools · all readonly · all always_visible   │
├────────────────────────────────────────────────┤
│  Beacon Tools                                  │
│  ProjectOverview · AgentOnboarding · Search    │
│  ExplainConcept · Guardrails                   │
├────────────────────────────────────────────────┤
│  BeaconProvider Protocol                       │
│  ManifestBeaconProvider (v0)                   │
│  ← future: MenhirBeaconProvider               │
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
| MCP framework | archolith_mcp_framework (create_gateway_server) + fastmcp ≥3.2.4 |
| YAML parsing | PyYAML ≥6 |
| Settings | frozen dataclass + from_env() pattern (no Pydantic) |
| Tests | pytest + pytest-asyncio |
| Entry point | `python -m beacon` → `beacon.main:main` |

## Package Layout

```
src/beacon/
├── __init__.py          version
├── __main__.py          python -m beacon entry
├── main.py              typer CLI: serve (default) / validate / inspect subcommands
├── config/
│   └── settings.py      BeaconSettings (frozen dataclass, from_env)
├── core/
│   ├── schema.py        BeaconManifest + all answer-contract frozen dataclasses
│   ├── loader.py        load_beacon_manifest(path) → BeaconManifest (PyYAML)
│   ├── validator.py     validate_beacon_manifest(), require_valid_manifest()
│   └── doc_index.py     DocIndex, DocChunk — heading-chunked, keyword search
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

## Config / Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `BEACON_MANIFEST_PATH` | **yes** | — | Absolute path to `beacon.yaml` |
| `BEACON_DOCS_ROOT` | no | dir of manifest | Root for resolving canonical doc paths |
| `BEACON_VALIDATE_ON_LOAD` | no | `true` | Hard-fail at startup on manifest errors |
| `BEACON_LOG_LEVEL` | no | `WARNING` | Python logging level |
| `BEACON_HOST` | no | `127.0.0.1` | Remote transport host (stdio ignores) |
| `BEACON_PORT` | no | `8788` | Remote transport port (stdio ignores) |

## CLI

`src/beacon/main.py` is a `typer` app with one default action and two subcommands:

| Command | Purpose |
|---------|---------|
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

v0 ships `ManifestBeaconProvider`. Future `MenhirBeaconProvider` plugs in here.

## Manifest Schema (beacon.yaml)

Top-level sections:

| Key | Purpose |
|-----|---------|
| `beacon_version` | Schema version (currently `"0.1"`) |
| `project` | name, tagline, description, status, repository, language, license |
| `purpose` | one_sentence, problem, non_goals |
| `audiences` | list of target user types |
| `current_focus` | active work areas |
| `core_concepts` | id, name, definition, why_it_exists, status, related_concepts |
| `canonical_docs` | path, role, status, title — resolved against BEACON_DOCS_ROOT |
| `agent_guidance` | read_first, safe_first_tasks, avoid_without_review |
| `build_and_test` | setup, test, benchmark commands |
| `guardrails` | id, rule, scope, severity, applies_to |

## Validation

`validate_beacon_manifest()` catches:
- missing `project.name` / `project.description` (error)
- empty `canonical_docs` (error)
- duplicate concept ids (error)
- duplicate guardrail ids (error)
- dangling canonical doc paths when `docs_root` is provided (error)
- unknown status vocabulary (warning)
- concept referencing unknown related id (warning)
- missing `build_and_test.test` command (warning)

`require_valid_manifest()` raises `ManifestValidationError` on any error — used at startup.

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

## Future: MenhirBeaconProvider

A Menhir-backed provider would implement the same `BeaconProvider` Protocol but answer
queries using:
- `recall_memories` for semantic search over project memories
- `query_structure` for file/symbol/blast-radius data
- temporal reasoning (Chronostratum) for "what changed" and "what is current"
- decision history and superseded-fact tracking

The MCP tools and answer contract stay unchanged.
