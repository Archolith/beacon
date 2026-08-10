# Beacon

> **Status: `0.2.0rc2` release candidate, pending publication.**
> Use a source checkout until RC2 is published; then install the pinned release candidate from PyPI.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Beacon gives software projects a consistent way to explain themselves to coding agents.

Add a `beacon.yaml` to a repository and run the local MCP server. A connected
agent can then ask:

- *What is this project, and what is it trying to do?*
- *What should I read before touching any code?*
- *What does this term mean, and where is it implemented?*
- *What should I avoid changing without a senior review?*
- *What is the safest first contribution I can make?*

Beacon returns structured answers with source citations instead of handing the agent a pile of raw text.

The current release is manifest-driven. It reads `beacon.yaml` and the documents listed there. It
does not need an external service, database, runtime LLM call, telemetry, or update check.

---

## Install

After RC2 is published, install it and its published framework dependency from PyPI:

```bash
python -m pip install "archolith-beacon==0.2.0rc2"
```

The distribution name is `archolith-beacon`; the import package is `beacon` and
the CLI command is `beacon`.

For development, check out this repository and install its dev dependencies:

```bash
git clone https://github.com/Archolith/beacon.git
cd beacon
pip install -e ".[dev]"
```

The package metadata uses the normal `archolith-mcp-framework>=0.2,<0.3`
constraint. It does not contain a Git URL or depend on a private package index.

**Requires Python 3.12, 3.13, or 3.14.**

---

## Quick start

The v0.2 product loop is: initialize, review, validate strictly, inspect with a
task in mind, export a reviewable snapshot, then connect an agent.

```text
beacon init
  -> review beacon.yaml
  -> beacon validate --strict-warnings
  -> beacon inspect --task-hint "..."
  -> beacon export
  -> connect MCP client / beacon serve
  -> optional plain JSON / beacon serve-http
```

**1. Add a `beacon.yaml` to your repo.**

The manifest is the source of truth. `init` generates a conservative starter from
bounded repository evidence; you can also write one by hand. See
[`beacon.yaml`](beacon.yaml) in this repo for a full example (describing [Menhir](https://github.com/Archolith/menhir)), and the
[`examples/`](examples/README.md) index for ready-to-run manifests in three
different project shapes.

A minimal manifest declares identity, purpose, and the canonical docs:

```yaml
beacon_version: "0.1"

project:
  name: my-project
  tagline: One sentence that explains what this is.
  status: experimental
  description: >
    Two to three sentences. What the project does, what problem
    it solves, and who it is for.

purpose:
  one_sentence: >
    What is the core job this project does for its users?

core_concepts:
  - id: key_concept
    name: Key Concept
    status: current
    description: What it is.

canonical_docs:
  - path: .agent/README.md
    role: entrypoint
    status: current
    title: Agent entry point

guardrails:
  - id: no_unsafe_change
    scope: core
    severity: high
    rule: >
      Do not change X without running the test suite and updating the docs.
    applies_to:
      - src/myproject/core/
```

**2. Validate the manifest.**

```bash
beacon validate path/to/beacon.yaml
```

Fix any reported errors before connecting an agent. Warnings are informational;
under `--strict-warnings`, unresolved publication warnings block the export path.

**3. Inspect what the tools will return.**

```bash
beacon inspect path/to/beacon.yaml
```

Pass a task hint to see task-scoped onboarding and guardrails rather than only
the no-argument defaults.

**4. Check the installed version.**

```bash
beacon --version
# beacon 0.2.0rc2
```

**5. Start the MCP server.**

Start stdio explicitly with `serve`, or rely on the environment-driven
no-argument form. Both run the same MCP-over-stdio server:

```bash
beacon serve --manifest beacon.yaml
# or the compatible no-argument form, driven by the environment:
BEACON_MANIFEST_PATH=/absolute/path/to/beacon.yaml beacon
```

`beacon serve` also accepts `--docs-root DIR` and the six `--max-*` limit flags.
Configure your agent client to launch one of these commands (see
[Connecting an agent](#connecting-an-agent) and the maintained
[docs/client-setup.md](docs/client-setup.md)).

**6. Optionally serve the snapshot as plain JSON.**

Clients that do not speak MCP can use the loopback-only HTTP compatibility surface:

```bash
beacon serve-http --manifest beacon.yaml
curl http://127.0.0.1:8765/.well-known/archolith-beacon
curl http://127.0.0.1:8765/v1/snapshot/identity
curl http://127.0.0.1:8765/v1/snapshot/orientation
curl http://127.0.0.1:8765/v1/snapshot
```

Start with `/v1/snapshot/identity` for the project, purpose, audiences, and current focus. Move to
`/v1/snapshot/orientation` for concepts, guardrails, citations, document hashes, and chunk inventory
without chunk bodies. Fetch `/v1/snapshot` only when the agent needs the full published corpus;
`/beacon.json` is its permanent alias. Discovery descriptor 1.2 advertises all three representations
with their exact byte sizes and SHA-256 digests, and `/healthz` returns redacted readiness metadata.
The server builds the embedded canonical snapshot once at startup, derives identity and orientation
from that approved in-memory source set, and serves all three as immutable bytes with independent
SHA-256 ETags and links to the next richer tier. It accepts only `127.0.0.1`, sends no CORS or
access-log output, and refuses to start unless the same publication, path, resource, and secret gates
as `beacon export` pass. Documents with a `plan` or `*_plan` role are represented by
title/path/role/status/hash only; their body chunks remain private to the local MCP index. Querying,
question submission, remote binding, authentication, and AI synthesis are not RC2 capabilities and
are advertised as unavailable in discovery.

---

## What agents can ask

Beacon registers five read-only MCP tools when the server starts.

### `beacon_project_overview`

> *"What is this project and what should I read next?"*

Returns a structured summary: project description, problem statement, current status, core components, and a canonical read order.

```
Inputs:
  audience: "new_contributor" | "coding_agent" | "researcher" | "maintainer"
            (default: "coding_agent")
  depth:    "short" | "standard" | "deep" (default: "standard")
```

### `beacon_agent_onboarding`

> *"I am about to work on X. What do I need to know?"*

Returns a task-specific onboarding pack: docs to read first, relevant files, concepts to understand, safe first steps, and a do-not-touch list.

```
Inputs:
  task_hint:      description of what you plan to do (optional)
  risk_tolerance: "low" | "medium" | "high" (default: "low")
```

### `beacon_search`

> *"What does this project know about temporal memory?"*

Keyword search across docs, concepts, and guardrails. Every result carries a status (`current`, `experimental`, `superseded`) and a `why_relevant` field.

```
Inputs:
  query:        search string
  source_types: list of "docs" | "concepts" | "guardrails" (default: all)
  limit:        max results (default: 8)
```

### `beacon_explain_concept`

> *"What is blast_radius and where is it implemented?"*

Looks up a project-specific term by id or name. Returns the definition, motivation, related concepts, and implementation locations.

```
Inputs:
  concept: concept id or display name
  depth:   "simple" | "technical" | "implementation" (default: "technical")
```

### `beacon_guardrails`

> *"What should I avoid touching, and what checks are required?"*

Returns the full guardrail set, filtered to a task if a hint is provided. Includes risky files aggregated from `applies_to` fields and the project's required test/build commands.

```
Inputs:
  task_hint: description of planned work (optional)
```

---

Every response includes:

```json
{
  "status":       "current | experimental | uncertain | mixed",
  "confidence":   "low | medium | high",
  "sources":      [{ "type": "doc", "path": "...", "line_start": 12, "line_end": 34 }],
  "next_actions": ["Call beacon_agent_onboarding with task_hint=..."]
}
```

Agents should respect `status` and `confidence`. A response marked `experimental` or `low` confidence is a signal to verify, not to treat as ground truth.

---

## Connecting an agent

Replace `/absolute/path/to/beacon.yaml` with the real path on your machine. The
maintained, install-first guide is [`docs/client-setup.md`](docs/client-setup.md);
the ready-to-connect configs below are also reproduced there.

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
`%APPDATA%\Claude\claude_desktop_config.json` (Windows)

```json
{
  "mcpServers": {
    "beacon": {
      "command": "beacon",
      "env": {
        "BEACON_MANIFEST_PATH": "/absolute/path/to/beacon.yaml"
      }
    }
  }
}
```

### Cursor

`.cursor/mcp.json` in your project root, or `~/.cursor/mcp.json` globally:

```json
{
  "mcpServers": {
    "beacon": {
      "command": "beacon",
      "env": {
        "BEACON_MANIFEST_PATH": "/absolute/path/to/beacon.yaml"
      }
    }
  }
}
```

### Codex

`~/.codex/config.toml`:

```toml
[mcp_servers.beacon]
command = "beacon"

[mcp_servers.beacon.env]
BEACON_MANIFEST_PATH = "/absolute/path/to/beacon.yaml"
```

### Gemini CLI

`~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "beacon": {
      "command": "beacon",
      "env": {
        "BEACON_MANIFEST_PATH": "/absolute/path/to/beacon.yaml"
      }
    }
  }
}
```

### OpenCode

`opencode.json` in your project root:

```json
{
  "mcp": {
    "beacon": {
      "type": "local",
      "command": ["beacon"],
      "environment": {
        "BEACON_MANIFEST_PATH": "/absolute/path/to/beacon.yaml"
      }
    }
  }
}
```

### Generic stdio

Any MCP client that accepts a stdio server can use this shape:

```json
{
  "command": "beacon",
  "env": {
    "BEACON_MANIFEST_PATH": "/absolute/path/to/beacon.yaml"
  }
}
```

---

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BEACON_MANIFEST_PATH` | **yes** | none | Absolute path to `beacon.yaml` |
| `BEACON_DOCS_ROOT` | no | directory of manifest | Root for resolving canonical doc paths |
| `BEACON_VALIDATE_ON_LOAD` | no | `true` | Hard-fail at startup if the manifest has errors |
| `BEACON_LOG_LEVEL` | no | `WARNING` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `BEACON_HOST` | no | `127.0.0.1` | Reserved runtime transport host; current stdio and `serve-http` paths use stdio or explicit CLI flags |
| `BEACON_PORT` | no | `8788` | Reserved runtime transport port; current stdio and `serve-http` paths use stdio or explicit CLI flags |
| `BEACON_MAX_MANIFEST_BYTES` | no | `1048576` | Manifest source byte ceiling |
| `BEACON_MAX_DOCUMENTS` | no | `256` | Canonical document count ceiling |
| `BEACON_MAX_DOCUMENT_BYTES` | no | `2097152` | Per-document byte ceiling |
| `BEACON_MAX_TOTAL_DOCUMENT_BYTES` | no | `20971520` | Aggregate canonical-document byte ceiling |
| `BEACON_MAX_CHUNKS` | no | `10000` | Total indexed heading-chunk ceiling |
| `BEACON_MAX_SNAPSHOT_BYTES` | no | `52428800` | Exported/served snapshot byte ceiling |

The six `BEACON_MAX_*` values use the same precedence as their CLI equivalents:
`CLI override > environment > default`.

---

## How it works

Beacon v0 is deterministic. At startup it:

1. Loads and validates `beacon.yaml` into a typed `BeaconManifest`.
2. Reads every `canonical_docs` entry and chunks them at Markdown headings into an in-memory `DocIndex`.
3. Stores the resulting `ManifestBeaconProvider` in a module-level slot.

On each tool call, the provider reads from the in-memory index and returns a frozen answer dataclass. It does not call an LLM, access the network, or query a database.

`BeaconProvider` is a typed protocol, so another provider can supply the same five tools without changing their answer contracts. A future Menhir-backed provider could add temporal memory, structure graphs, and Git history behind that interface.

---

## Examples

Three small, self-contained example repositories live under
[`examples/`](examples/README.md), one per project shape:

| Example | Shape |
| --- | --- |
| [`examples/library`](examples/library) | A small Python package |
| [`examples/service`](examples/service) | A long-running background service |
| [`examples/monorepo-research`](examples/monorepo-research) | A research/analysis monorepo |

Each has a valid `beacon.yaml`, real canonical docs, and meaningful
concepts/guardrails/build-and-test metadata, and is checked automatically by
`tests/test_examples.py` for validation, all five provider tools, and clean
embedded/metadata-only snapshot export. Use the closest match as a starting
point for your own manifest.

## Versions

Beacon tracks three independent version numbers:

| Name | Value | What it versions |
| --- | --- | --- |
| Manifest schema | `0.1` | The `beacon.yaml` shape; stays `0.1` so existing manifests keep loading. |
| Product | `0.2.0` | The Beacon distribution and its CLI/MCP behavior. |
| Snapshot schema | `1.0` | The exported snapshot shape (`beacon_snapshot_version`). |

A snapshot records its generator (product) version, the manifest schema version
it came from, and its own snapshot version separately. The default snapshot
**embeds** each non-plan canonical document's heading-chunk text once. Documents
whose role is `plan` or ends in `_plan` remain title-only in snapshots while the
private MCP index retains their full text. `--metadata-only` emits structure and
hashes without any document text.

---

## Status

Beacon is experimental, and this checkout is the `0.2.0rc2` release candidate. The v0.2
local functionality is implemented: `beacon init`, `validate`, `inspect`,
`export`, `serve`, and loopback-only `serve-http` (plus the no-argument stdio server) are shipped and
tested, and the maintained examples pass their validation/provider/snapshot
matrix. One release gate remains, not missing feature scope:

- **Unaided developer trial.** The 15-minute cold-start claim is a separate
  acceptance gate to be measured with a developer who did not write the
  implementation; documentation does not assert that it has passed.

A `MenhirBeaconProvider` is a deferred v0.3 limitation, not evidence that this
v0.2 scope is unfinished. Beacon is static and has no outbound runtime network call: no database,
no LLM or embedding, no telemetry, and no update check. The optional HTTP compatibility process
listens only on loopback and serves the same startup snapshot. Beacon reads only the manifest and
the documents it lists.

Track the product path in
[`docs/beacon-functional-product-roadmap.md`](docs/beacon-functional-product-roadmap.md). The
tool-level interface history and backlog remain in
[`docs/beacon-mcp-roadmap.md`](docs/beacon-mcp-roadmap.md).

---

## Contributing

Read [`docs/beacon-strategy-handoff.md`](docs/beacon-strategy-handoff.md) for the positioning rationale before proposing new features.

Useful contributions at this stage include:

- Adding example manifests for different project shapes (library, research project, monorepo service).
- Adding `docs/demo-transcript.md` showing a real agent session.
- Writing golden-output tests for each MCP tool.

Please hold off on adding tools or expanding the manifest schema. The current five tools need clearer documentation and easier client setup before the interface grows.

Development setup:

```bash
git clone https://github.com/Archolith/beacon.git
cd beacon
pip install -e ".[dev]"
python -m pytest tests/ -x --tb=short
```

All tests run without outbound network access. They do not require Neo4j or an external service;
the HTTP integration check uses only an ephemeral loopback socket.

The negative-control mutation gate deliberately breaks four release-critical
behaviors in temporary package copies and requires the focused tests to fail:

```bash
python scripts/run_mutation_tests.py
```

The command succeeds only when every mutant is caught. The real checkout is not
modified.

---

## License

MIT. See [LICENSE](LICENSE).
