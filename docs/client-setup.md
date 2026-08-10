# Beacon client setup guide

This guide takes a maintainer from a fresh machine to a coding agent connected to
a local Beacon instance. It is written to be copy-pasted, and it assumes nothing
about the machine beyond Python 3.12, 3.13, or 3.14.

Beacon is a **local, static, no-outbound-network** knowledge server. It reads a `beacon.yaml` and
the Markdown documents it lists, and it answers the five read-only Beacon tools
from that in-memory index. It can also serve the canonical snapshot as plain JSON on loopback.
There is no database, outbound network call, runtime LLM, telemetry, or update check. Everything
runs on your machine.

---

## 1. Install Beacon

> **Status note.** This guide targets the unpublished `0.2.0rc2` release candidate.

After RC2 is published, install the pinned release candidate from PyPI. Its framework dependency
resolves from the public index automatically. Until then, use the source-checkout instructions
below.

```bash
python -m pip install "archolith-beacon==0.2.0rc2"
```

Check the CLI is present:

```bash
beacon --version
beacon --help
```

---

## 2. The v0.2 product loop

After installing, walk a project through the full loop:

```text
install
  -> beacon init
  -> review beacon.yaml
  -> beacon validate --strict-warnings
  -> beacon inspect --task-hint "..."
  -> beacon export
  -> connect MCP client / beacon serve
```

`init` writes a conservative starter `beacon.yaml` from bounded repository
evidence and never overwrites an existing file unless you pass `--force`. Review
the generated file, resolve the review items it flagged, then validate strictly.

```bash
cd /path/to/your/project
beacon init
beacon validate --strict-warnings
beacon inspect --task-hint "add a regression test"
beacon export
```

If validation reports warnings, they are honest "needs a real answer" items, not
guesses to silence. Publication is gated on a clean strict validation.

The no-argument server remains the compatible way to start stdio; `beacon serve`
is the explicit form with manifest/docs-root/limit options:

```bash
# explicit: point at a manifest, optionally a docs root, and any of six limits
beacon serve --manifest beacon.yaml --docs-root .
beacon serve --manifest beacon.yaml --max-documents 500

# or the environment-driven, no-argument form
BEACON_MANIFEST_PATH=/absolute/path/to/beacon.yaml beacon
```

`serve` accepts `--manifest PATH` (default `./beacon.yaml`), `--docs-root DIR`,
and the six overridable limit flags: `--max-manifest-bytes`,
`--max-documents`, `--max-document-bytes`, `--max-total-document-bytes`,
`--max-chunks`, and `--max-snapshot-bytes`.

For a client that does not speak MCP, start the immutable loopback HTTP surface:

```bash
beacon serve-http --manifest beacon.yaml
curl http://127.0.0.1:8765/.well-known/archolith-beacon
curl http://127.0.0.1:8765/v1/snapshot/identity
curl http://127.0.0.1:8765/v1/snapshot/orientation
curl http://127.0.0.1:8765/v1/snapshot
```

Use `/v1/snapshot/identity` as the cheapest project read, then
`/v1/snapshot/orientation` when concepts, guardrails, citations, or document inventory are needed.
Use `/v1/snapshot` for the full corpus; `/beacon.json` is its identical alias. Discovery descriptor
1.2 advertises all three representations with exact byte sizes, modes, schema versions, and SHA-256
digests. Only `GET` and `HEAD` are supported. Each representation has its own ETag and supports
`If-None-Match`; all are precomputed from one approved startup source set, and identity/orientation
include HTTP `Link` headers to the next richer representation. The command rejects every host except
`127.0.0.1`, disables CORS and access logs, and applies the same strict publication and secret gates
as export. Plan-role documents carry only title/path/role/status/hash in the snapshot; their body
remains available only through the private local MCP index. Remote access, query, and question
submission remain disabled.

---

## 3. Start a Beacon instance

Beacon must be able to find its manifest. Either point the explicit `serve`
command at it, or set `BEACON_MANIFEST_PATH` for the no-argument form:

```bash
beacon serve --manifest /absolute/path/to/beacon.yaml
# or
BEACON_MANIFEST_PATH=/absolute/path/to/beacon.yaml beacon
```

The server writes its startup note and logs to **stderr**. Its **stdout** carries
only MCP framing, so a client can connect over stdio without contamination.

Use the **examples** as a quick way to try this on a known-good project:

| Example | Shape |
| --- | --- |
| [`examples/library`](../examples/library) | A small Python package |
| [`examples/service`](../examples/service) | A long-running service |
| [`examples/monorepo-research`](../examples/monorepo-research) | A research monorepo |

See the [`examples/README.md`](../examples/README.md) index for details.

---

## 4. Connect an MCP client

Every client below launches the local `beacon` command over stdio. Replace
`/absolute/path/to/beacon.yaml` with a real path on your machine.

Reference links for the official client configuration formats:

- Cursor — [Model Context Protocol](https://docs.cursor.com/context/model-context-protocol)
- OpenCode — [MCP servers](https://opencode.ai/docs/mcp-servers/)
- Gemini CLI — [MCP server](https://google-gemini.github.io/gemini-cli/docs/tools/mcp-server.html)
- MCP spec — [Connecting local servers](https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers)

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
`%APPDATA%\Claude\claude_desktop_config.json` (Windows)

```json
{
  "mcpServers": {
    "beacon": {
      "command": "beacon",
      "env": { "BEACON_MANIFEST_PATH": "/absolute/path/to/beacon.yaml" }
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
      "env": { "BEACON_MANIFEST_PATH": "/absolute/path/to/beacon.yaml" }
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
      "env": { "BEACON_MANIFEST_PATH": "/absolute/path/to/beacon.yaml" }
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
      "environment": { "BEACON_MANIFEST_PATH": "/absolute/path/to/beacon.yaml" }
    }
  }
}
```

### Generic stdio

Any MCP client that accepts a stdio server:

```json
{
  "command": "beacon",
  "env": { "BEACON_MANIFEST_PATH": "/absolute/path/to/beacon.yaml" }
}
```

---

## 5. What the agent can ask

Once connected, the agent sees five read-only tools:

- `beacon_project_overview` — identify the project and what to read next.
- `beacon_agent_onboarding` — task-scoped start pack and do-not-touch list.
- `beacon_search` — keyword search over docs, concepts, and guardrails.
- `beacon_explain_concept` — what a project-specific term means and where it lives.
- `beacon_guardrails` — what not to change and which checks are required.

Every answer carries `status`, `confidence`, `sources`, and `next_actions`, so
an agent can tell current knowledge from experimental or uncertain.

---

## 6. Versions

Beacon tracks three independent version numbers. Keep them separate in your head:

| Name | Value | What it versions |
| --- | --- | --- |
| Manifest schema | `0.1` | The `beacon.yaml` shape. `0.1` stays the same across product releases so existing manifests keep loading. |
| Product | `0.2.0` | The Beacon distribution. The CLI, MCP surface, and product behavior ship under this version. |
| Snapshot schema | `1.0` | The exported snapshot shape (`beacon_snapshot_version`). Independent so a snapshot can evolve without touching the manifest. |

A snapshot records its generator version (the product), the manifest schema
version it came from, and its own snapshot version — three separate fields, so
each can change on its own cadence.

---

## 7. Limitations

- **Static and no outbound network.** Beacon reads only what is on disk. It performs no outbound
  runtime network I/O, update check, telemetry, runtime LLM, or embedding call. `serve-http` uses
  only an explicitly requested loopback listener. A file not listed in `beacon.yaml` is invisible.
- **Manifest-driven.** Everything an agent can learn is bounded by what the
  maintainer put in `beacon.yaml` and its canonical docs. A thin or stale
  manifest means a thin or stale Beacon.
- **Keyword search.** `beacon_search` uses deterministic keyword overlap over
  Markdown headings and bodies. It is not semantic/embedding search.
- **No git, symbol, or benchmark adapters.** v0.2 ships the conservative init
  discovery and the manifest provider only. Code-level and Git-history
  knowledge is deferred to v0.3.
- **Snapshots are exports, not a query provider.** The v0.2 snapshot is a static, reviewable
  artifact for CI diffing and optional loopback HTTP retrieval. Loading or querying it as a
  provider fallback is deferred.
- **Not an unaided-trial guarantee.** Documentation keeps example commands
  honest, but it does not claim a scripted cold-start time for every machine.
  Measure your own journey and report any undocumented blocking step.
