# Beacon Demo Transcript

> This transcript shows a real agent session against the Beacon project's own
> `beacon.yaml`. All responses are produced by `ManifestBeaconProvider` — no
> LLM, no network, no external service. Every field is derived deterministically
> from the manifest and the in-memory doc index.
>
> The four queries follow a natural onboarding arc: identify the project,
> understand a key concept, get a task-scoped start, check what's off-limits.

---

## Setup

```
BEACON_MANIFEST_PATH=/path/to/beacon/beacon.yaml beacon
```

Client connects via stdio MCP. Five tools become available:
`beacon_project_overview`, `beacon_agent_onboarding`, `beacon_search`,
`beacon_explain_concept`, `beacon_guardrails`.

---

## Query 1 — "What is Beacon and what should I read first?"

**Tool:** `beacon_project_overview`  
**Inputs:** *(none)*

**Response:**

```json
{
  "summary": "Beacon lets coding agents identify, orient, explain, and safely
              contribute to a project through structured, source-cited tools
              instead of guessing from a README.",

  "problem": "LLM agents onboard to projects through ad-hoc context stuffing:
              READMEs, docs, issues, commits, and maintainer memory pasted into
              a context window. This is slow, stale, and non-deterministic.
              Beacon changes the model: a project publishes its own living,
              structured understanding, and agents query it directly.",

  "current_status": "experimental",

  "core_components": [
    "Beacon Manifest (current)",
    "Beacon Provider (current)",
    "Answer Contract (current)",
    "Doc Index (current)",
    "Guardrails (current)"
  ],

  "read_next": [
    ".agent/README.md",
    ".agent/architecture.md",
    ".agent/data_models.md",
    "README.md"
  ],

  "status": "mixed",
  "confidence": "high",
  "sources": [{ "type": "manifest", "path": "beacon.yaml" }],
  "next_actions": ["call beacon_agent_onboarding for a task-scoped start"]
}
```

**What this gives an agent that a README doesn't:**
- A structured read order — not a list of files to discover manually.
- Per-component status labels — the agent knows `core_components` are all `current`, not experimental guesses.
- A `next_actions` field that chains directly into the most useful follow-up call.
- A `confidence: high` signal derived from source count — the agent can calibrate how much to trust this.

---

## Query 2 — "Explain the answer contract and why it matters."

**Tool:** `beacon_explain_concept`  
**Inputs:** `concept: "answer_contract"`

**Response:**

```json
{
  "concept": "Answer Contract",

  "definition": "Every Beacon tool response carries status
                 (current/experimental/uncertain/mixed), confidence
                 (low/medium/high), sources (file + line citations), and
                 next_actions. This makes provenance and uncertainty
                 first-class — agents should not treat all generated text
                 equally.",

  "why_it_exists": "A system that returns text without provenance is a chatbot.
                    Beacon's answer contract makes every claim traceable and
                    every uncertainty explicit.",

  "related_concepts": ["beacon_provider"],
  "implementation_locations": [],

  "status": "current",
  "confidence": "high",
  "sources": [{ "type": "manifest", "path": "beacon.yaml" }],
  "next_actions": []
}
```

**What this gives an agent that a README doesn't:**
- A stable vocabulary entry, not a definition the agent reverse-engineered from prose.
- `related_concepts: ["beacon_provider"]` — the agent knows which concept to look up next if it needs depth.
- `implementation_locations` is empty here; when filled in, it hands the agent the exact files to read.
- `why_it_exists` is a first-class field — the agent gets the motivation, not just the definition.

---

## Query 3 — "I want to add an example manifest. Where do I start and what should I avoid?"

**Tool:** `beacon_agent_onboarding`  
**Inputs:** `task_hint: "add an example manifest"`, `risk_tolerance: "low"`

**Response:**

```json
{
  "orientation": "For 'add an example manifest': Beacon lets coding agents
                  identify, orient, explain, and safely contribute to a project
                  through structured, source-cited tools instead of guessing
                  from a README.",

  "relevant_docs": [
    ".agent/README.md",
    ".agent/architecture.md",
    ".agent/data_models.md",
    "README.md"
  ],

  "relevant_files": [
    "README.md",
    ".agent/data_models.md"
  ],

  "concepts_to_understand": [
    "Beacon Manifest",
    "Beacon Provider",
    "Answer Contract",
    "Doc Index",
    "Guardrails"
  ],

  "safe_first_steps": [
    "Add or improve docs in .agent/ or docs/.",
    "Add example manifests for a new project shape in docs/examples/.",
    "Write a golden-output test for an existing MCP tool.",
    "Extend docs/demo-transcript.md with a new query.",
    "Fix a warning in beacon validate output."
  ],

  "do_not_touch": [
    "Changing the BeaconProvider Protocol (breaks all provider implementations).",
    "Changing the answer-contract dataclasses (breaks MCP tool output shape).",
    "Changing the manifest schema (beacon_version stays '0.1' until a migration exists).",
    "Adding new MCP tools before the existing five are well-documented.",
    "Renaming core concepts (id, definition, status, confidence, sources)."
  ],

  "commands": [
    "pip install -e .",
    "python -m pytest tests/ -x --tb=short"
  ],

  "status": "experimental",
  "confidence": "high",
  "sources": [
    { "type": "manifest", "path": "beacon.yaml" },
    { "type": "doc",      "path": "README.md",           "title": "Quick start",       "line_start": 38,  "line_end": 108 },
    { "type": "doc",      "path": ".agent/data_models.md","title": "BeaconManifest",    "line_start": 11,  "line_end": 28  },
    { "type": "doc",      "path": "README.md",           "title": "Contributing",      "line_start": 329, "line_end": 353 }
  ],
  "next_actions": ["call beacon_guardrails before editing risky areas"]
}
```

**What this gives an agent that a README doesn't:**
- The task hint (`"add an example manifest"`) scopes the response — docs and files are filtered to what's relevant for this specific work, not a generic project dump.
- `relevant_files` pins the agent to `README.md` and `.agent/data_models.md` — the two files that actually matter for writing a new manifest.
- `do_not_touch` is explicit and machine-readable — the agent doesn't have to infer what's dangerous from prose warnings.
- `sources` carry line ranges — the agent can jump directly to `README.md:329–353` for the Contributing section rather than searching the file.
- `next_actions` chains to `beacon_guardrails`, which is exactly the right next call (see Query 4).

---

## Query 4 — "What guardrails apply if I want to add a new MCP tool?"

**Tool:** `beacon_guardrails`  
**Inputs:** `task_hint: "add a new MCP tool"`

**Response:**

```json
{
  "rules": [
    "[high]   Do not change the BeaconProvider Protocol or the answer-contract
              dataclasses without updating ManifestBeaconProvider, all tests,
              and incrementing the schema version. The tool output shape is
              part of the public interface.",

    "[high]   Do not add required manifest fields or change field names without
              a migration plan. Existing beacon.yaml files in the wild must
              still load. Use optional fields with defaults for additions.",

    "[medium] Do not add a sixth MCP tool until the existing five have a demo
              transcript, golden-output tests, and client setup docs. Interface
              clarity comes before surface area.",

    "[medium] Run the full offline test suite before committing. All tests run
              without Neo4j, network, or external services."
  ],

  "risky_files": [
    "src/beacon/provider/base.py",
    "src/beacon/core/schema.py",
    "src/beacon/core/loader.py",
    "src/beacon/core/validator.py",
    "src/beacon/mcp/tools/",
    "src/beacon/mcp/server.py",
    "tests/",
    "src/beacon/"
  ],

  "required_checks": [
    "python -m pytest tests/ -x --tb=short"
  ],

  "status": "current",
  "confidence": "high",
  "next_actions": ["run the required checks before committing"]
}
```

**What this gives an agent that a README doesn't:**
- Severity-labeled rules — the agent can see immediately which rules are blocking (`high`) versus advisory (`medium`).
- `risky_files` is an aggregated list the agent can use for blast-radius analysis before touching anything.
- The `[medium]` rule about "do not add a sixth tool until..." is a policy decision encoded as data — not buried in a contributing guide the agent may not have read.
- `required_checks` gives the exact command to run before committing. No interpretation required.

---

## What v0 doesn't do yet

These four queries demonstrate the manifest-driven v0 surface. A few things that would make this significantly better, planned for a Menhir-backed provider:

- **Temporal tracing** — "What changed in the answer contract since last month?" requires git history and decision records that v0 doesn't have.
- **Symbol-level citations** — `implementation_locations` is currently filled from the manifest by hand. A Menhir-backed provider would populate it from the live structure graph.
- **Freshness signals** — v0 can't tell an agent whether the manifest itself is stale relative to the code. Menhir's structure-time join would surface doc drift.
- **Semantic search** — `beacon_search` uses keyword overlap. A Menhir-backed provider would use embedding-based retrieval ranked by graph adjacency.

The answer contract (`status`, `confidence`, `sources`, `next_actions`) is already there. The provider is the only thing that gets richer.

---

## Running this yourself

```bash
git clone https://github.com/Archolith/beacon.git
cd beacon
pip install -e .

# Validate the manifest
beacon validate beacon.yaml

# Preview all tool outputs in the terminal
beacon inspect beacon.yaml

# Start the MCP server (configure your client to point at beacon.yaml)
BEACON_MANIFEST_PATH=$(pwd)/beacon.yaml beacon
```

Connect any MCP client using the configs in [README.md](../README.md#connecting-an-agent).
