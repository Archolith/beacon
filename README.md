# Beacon

> **Status: `0.2.0rc1` development checkout.**
> `archolith-beacon` is not on PyPI yet because its
> `archolith-mcp-framework` dependency must be published first. See
> [Install](#install) to run Beacon from a source checkout.

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

This checkout is `0.2.0rc1`. For now, install it from source. A normal
`pip install archolith-beacon` will not work until `archolith-mcp-framework`
has been published to PyPI.

The distribution name is `archolith-beacon`; the import package is `beacon` and
the CLI command is `beacon`.

Check out this repository and `archolith-mcp-framework` v0.2.0 side by side.
Install the framework first so Beacon resolves the local copy:

```bash
# 1. Check out the framework release and install it editable (must come first).
git clone https://github.com/Archolith/archolith-mcp-framework.git
cd archolith-mcp-framework
git checkout v0.2.0
pip install -e .

# 2. Back in this repository, install Beacon editable with dev tooling.
cd <path-to-this-beacon-checkout>
pip install -e ".[dev]"
```

The package metadata still uses the normal
`archolith-mcp-framework>=0.2,<0.3` constraint. It does not contain a Git URL
or depend on a private package index. Once the framework is on PyPI,
`pip install archolith-beacon` will become the standard installation path.

**Requires Python 3.12, 3.13, or 3.14.**

---

## Quick start

**1. Add a `beacon.yaml` to your repo.**

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
  problem: >
    What breaks or is painful without this project?
  non_goals:
    - Things this project explicitly will not do.

core_concepts:
  - id: key_concept
    name: Key Concept
    status: current
    description: What it is.
    why_it_exists: Why the project needs it.

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

See [`beacon.yaml`](beacon.yaml) in this repo for a full example (describing [Menhir](https://github.com/Archolith/menhir)).

**2. Validate the manifest.**

```bash
BEACON_MANIFEST_PATH=/absolute/path/to/beacon.yaml beacon validate
```

Fix any reported errors before connecting an agent. Warnings are informational.

**3. Inspect what the tools will return.**

```bash
BEACON_MANIFEST_PATH=/absolute/path/to/beacon.yaml beacon inspect
```

**4. Check the installed version.**

```bash
beacon --version
# beacon 0.2.0rc1
```

**5. Start the MCP server.**

```bash
BEACON_MANIFEST_PATH=/absolute/path/to/beacon.yaml beacon
```

The server speaks MCP over stdio. Configure your agent client to launch this command (see [Connecting an agent](#connecting-an-agent)).

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

Replace `/absolute/path/to/beacon.yaml` with the real path on your machine.

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
[mcp.beacon]
command = "beacon"

[mcp.beacon.env]
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

---

## How it works

Beacon v0 is deterministic. At startup it:

1. Loads and validates `beacon.yaml` into a typed `BeaconManifest`.
2. Reads every `canonical_docs` entry and chunks them at Markdown headings into an in-memory `DocIndex`.
3. Stores the resulting `ManifestBeaconProvider` in a module-level slot.

On each tool call, the provider reads from the in-memory index and returns a frozen answer dataclass. It does not call an LLM, access the network, or query a database.

`BeaconProvider` is a typed protocol, so another provider can supply the same five tools without changing their answer contracts. A future Menhir-backed provider could add temporal memory, structure graphs, and Git history behind that interface.

---

## Status

Beacon is experimental. The five tools and their answer contracts are usable now, but the v0.2 product is not finished:

- The manifest schema may gain new fields in v0.x releases.
- A `MenhirBeaconProvider` does not yet exist.
- `validate` and `inspect` are implemented and tested. `init`, `export`, and an
  explicit `serve` command are not yet shipped. Use the positional
  `beacon validate PATH` / `beacon inspect PATH` commands and the
  no-argument stdio server documented above.
- This checkout is `0.2.0rc1` development. Public PyPI publication is gated on
  first publishing the `archolith-mcp-framework` dependency; install from source
  as described under [Install](#install) for now.

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

All tests run offline. They do not require Neo4j, a network connection, or an external service.

---

## License

MIT. See [LICENSE](LICENSE).
