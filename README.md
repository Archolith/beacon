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

The package metadata uses the normal `archolith-mcp-framework>=0.3.0`
constraint. It does not contain a Git URL or depend on a private package index.

**Requires Python 3.12, 3.13, or 3.14.**

---

## Quick start

The product loop is: initialize, say what only you can say, build, validate strictly,
inspect with a task in mind, export a reviewable snapshot, then connect an agent.

```text
beacon init                      # beacon.yaml: the fields only maintainers can answer, empty
  -> fill purpose, non-goals, guardrails
  -> beacon build --repo .       # reads the rest from your files; writes beacon.generated.yaml
  -> beacon validate --strict-warnings beacon.generated.yaml
  -> beacon inspect --task-hint "..." beacon.generated.yaml
  -> beacon export
  -> connect MCP client / beacon serve
  -> optional plain JSON / beacon serve-http
```

**1. Add a `beacon.yaml` to your repo.**

`beacon.yaml` holds the project's judgment: purpose, non-goals, guardrails, review areas.
`init` writes those fields empty and nothing else: name, description, license, language,
commands, docs and releases are read from the project's own files by `beacon build` on every
run, so they never go stale in `beacon.yaml`. Check an overlay with
`beacon validate --intent beacon.yaml`. A complete hand-written manifest still validates and
serves directly, as below. See
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

**Streamable HTTP.** The same server also runs over MCP Streamable HTTP, from a
canonical snapshot:

```bash
beacon export                                  # writes beacon.snapshot.json
beacon serve --snapshot beacon.snapshot.json --transport http
# [beacon] MCP http listening on http://127.0.0.1:8766/mcp (pid=...)
```

`--transport http` requires `--snapshot`, serves the same seven tools at the `/mcp`
path, and `--host` (default `127.0.0.1`) and `--port` (default `8766`) apply to it
only. It binds loopback only, and it is direct, unverified access — no trust broker
or signing yet (see the [trust plan](.agent/plans/beacon-trust-hub-and-federation-plan-2026-08-09.md));
exposure beyond this machine goes through a TLS reverse proxy (see
[docs/deployment.md](docs/deployment.md)).
Loopback keeps other machines out but not other local users or processes, which can
read every served doc. Requests whose `Host` or browser `Origin` is not `127.0.0.1` or
`localhost` are refused (421/403), so a web page cannot reach it through DNS rebinding.
A port already in use fails with `http_bind_failed`.

**6. Optionally serve the snapshot as plain JSON.**

Clients that do not speak MCP can use the loopback-only HTTP compatibility surface. Like the MCP
HTTP transport, it refuses a non-loopback `Host` (421) or browser `Origin` (403), so a web page
cannot reach it through DNS rebinding:

```bash
beacon serve-http --manifest beacon.yaml
curl http://127.0.0.1:8765/.well-known/archolith-beacon
curl http://127.0.0.1:8765/v1/snapshot/identity
curl http://127.0.0.1:8765/v1/status
curl http://127.0.0.1:8765/v1/snapshot/orientation
curl http://127.0.0.1:8765/v1/concepts
curl http://127.0.0.1:8765/v1/guardrails
curl http://127.0.0.1:8765/v1/decisions
curl http://127.0.0.1:8765/v1/chunks
curl "http://127.0.0.1:8765/v1/search?q=namespace+isolation&types=decisions"
curl "http://127.0.0.1:8765/v1/read?chunk_id=c1-...&max_chars=4000"
curl "http://127.0.0.1:8765/v1/explain?concept=adr-0005"
curl http://127.0.0.1:8765/v1/snapshot
```

The surface is loopback-only; to publish it beyond this machine, put the TLS reverse proxy from
[docs/deployment.md](docs/deployment.md) in front.

Start with `/v1/snapshot/identity` for the project, purpose, audiences, and current focus, then read
`/v1/status` to see one explicit active-work item, recent completions, blockers, pending decisions,
and startup evidence. The status resource separates maintainer-declared claims from the commit,
dirty flag, and source-digest comparisons observed when the server started (branch names are never
published: they are free text from the checkout, outside the export filter). It also labels
that unsigned evidence as self-reported; it is not a live watcher or a remote trust proof. Move to
`/v1/snapshot/orientation` for concepts, guardrails, citations, document hashes, and chunk inventory
without chunk bodies. Fetch `/v1/snapshot` only when the agent needs the full published corpus;
`/beacon.json` is its permanent alias. To avoid fetching full, inspect `/v1/chunks`: each entry has a
stable ID, parent document role/status, exact UTF-8 text bytes, exact response bytes, and a shared URL
template for retrieving only that chunk. Each retrieved resource has its own SHA-256/ETag. Discovery
descriptor 1.7 also advertises the status resource, `/v1/concepts`, `/v1/guardrails`, `/v1/decisions`,
and the dynamic query routes. Each knowledge catalog is a cheap selector index; `/v1/concepts` and
`/v1/guardrails` use opaque resource IDs so a logical ID never becomes route structure, while
`/v1/decisions/{id}` addresses each record by its decision id. All four companion indexes publish
exact byte sizes and digests; `/healthz` returns redacted readiness metadata. The
server builds the embedded canonical snapshot once at startup, derives every lighter representation
and companion resource from that approved in-memory source set, and serves immutable bytes with
independent ETags. It accepts only `127.0.0.1`, sends no CORS or access-log output, and refuses to
start unless the same publication, path, resource, and secret gates as `beacon export` pass.
Documents with a `plan` or `*_plan` role are represented by title/path/role/status/hash only; their
body chunks remain private to the local MCP index. Question submission, remote binding,
authentication, and AI synthesis are not RC2 capabilities and are advertised as unavailable in
discovery.

**7. Query the same answers over plain HTTP.**

`/v1/search`, `/v1/read` and `/v1/explain` accept GET (and HEAD) query parameters and answer with
the same payloads as the `beacon_search`, `beacon_read` and `beacon_explain_concept` MCP tools —
one provider is built from the served snapshot at startup and every answer is the tool's exact
result rendered in the surface's canonical JSON. `/v1/search?q=...&types=...&limit=...` searches
docs, concepts, decisions and guardrails; `/v1/read?chunk_id=...|path=...&heading=...|line=...`
reads one section with its citation; `/v1/explain?concept=...&depth=...` explains a concept or an
ADR. Refusals keep the MCP error envelope (`{"ok": false, "tool": ..., "error": {...}}`): a
not-found code maps to HTTP 404 and other refusals (query over the byte cap, limit over the
ceiling) to 400, with the refused query text never echoed in any body, header, or log line.
Every answer carries an ETag; successful answers honour `If-None-Match` with 304, while
refusals always keep their error status. `types` is comma-separated (spaces are ignored), and a
trailing slash (`/v1/search/`) is a plain 404, never a redirect that would repeat the query. The
decisions family is static: `/v1/decisions` lists the decisions whose ADR the snapshot serves and
`/v1/decisions/{id}` returns one complete record (decision text verbatim, alternatives with
reasons, status, supersession, section spans, citations) with the same serving policy as search,
read, and explain — excluded, local-only, or withheld ADRs probe exactly like a nonexistent id.

**For LLM clients.** `/.well-known/archolith-beacon` is the entry point: each resource family and
dynamic route carries a one-line `use_when`, and `recommended_flow` lists the routes to walk in
order (identify, search decisions or keywords, read or explain, guardrails before changes). The
`freshness` block states how old the answers are — the snapshot SHA-256, the generator version,
and the repository commit/dirty state observed once at startup, with `observed_at` and a
pointer to `/v1/status` for the full evidence; the same facts ride on `/v1/snapshot/identity`
response headers (`x-beacon-observed-at`, `x-beacon-repository-commit`, and siblings). An
unobserved fact is `null` or `unavailable`, never invented at request time, and `trust` reads
`direct_unverified`: there is no signing and no trust broker yet.

---

## Building a beacon

Each project owns its own data. Beacon asks for it, merges it with what the repository and an
optional memory provider can prove, and writes the result:

```bash
beacon init                        # beacon.yaml with the judgment fields, empty
# edit beacon.yaml: purpose, non-goals, guardrails, review areas
beacon build --repo .              # writes beacon.generated.yaml and reports remaining gaps
```

Sources, from the project's words to guesses:

| Source | What it supplies |
|---|---|
| `intent` | `beacon.yaml`: judgment, and overrides |
| `declared` | Files the project already wrote: package manifest name, description and license; the license text (matched to SPDX); CI workflow install and test commands; the README lead paragraph; entry docs (`README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, ...) |
| `git` | Repository origin, recent release tags |
| `memory` | A memory provider's indexed evidence |
| `inferred` | Guesses, labelled low confidence: the conventional command for a build marker, the directory name |

For judgment (name, description, commands) `beacon.yaml` wins and the files fill what it leaves
empty. For facts about the code the checkout wins: a license the project's files state overrides
a different one in `beacon.yaml`, and the build reports the contradiction as drift. The build
report names the file and line each derived value came from.

Pin a citation so a stale claim is caught: `beacon digest AGENTS.md --lines 12-18` prints a
`sha256:` digest to store as `sources[].digest`; `beacon validate` warns `source_changed` when
the cited text later changes.

**Say it once, in your docs.** Judgment can also live in the documents agents already read.
Mark a span in `README.md`, `AGENTS.md`, `CONTRIBUTING.md` or `SECURITY.md` and the build cites
it by line and pins it automatically:

```markdown
<!-- beacon:guardrail id=no-writes severity=high -->
Never write files into indexed projects.
<!-- /beacon -->
```

Kinds: `purpose`, `non-goals`, `guardrail` (`id`, `severity`, `scope`), `concept` (`id`,
`name`), `command` (`for=setup|test`), `avoid`. Without markers the build falls back to
conventions: guardrail-like sections of `AGENTS.md`/`CONTRIBUTING.md`/`SECURITY.md` (one cited
entry per section), other `AGENTS.md` sections as pointers, a `Non-goals` section, a glossary,
`CODEOWNERS`, document frontmatter (`status`, `role`) and the `mkdocs.yml` nav. That works on
any repository; the build notes which fields came from conventions or guesses, because marked
docs give better results. Excerpts are capped at 300 characters: agents get pointers and pull
full text only when they need it. Agent-vendor files (`CLAUDE.md`, `.cursor/rules`) are never
read; point them at `AGENTS.md`.

**Architecture decision records.** The build reads ADRs from `docs/adr/`, `doc/adr/`,
`docs/decisions/`, `adr/` and `.agent/adr/`, plus any folder named by `adr_dir` in
`beacon.yaml` (one path or a list). An ADR is a decision the maintainers approved by committing
it, so it is published verbatim: each becomes a `decision` document and a `decisions[]` entry
holding its Decision section (capped at 4,000 characters), the alternatives it considered with
their reasons, its status and date, supersession links, and line spans for the other sections.
Nygard (`- **Status:**` bullets or a `## Status` section) and MADR (frontmatter, `Decision
Outcome`, `Considered Options`) are understood. The status keeps its own words (`status_text`);
its first word sets the served status (accepted -> `current`, proposed -> `planned`,
superseded/deprecated/rejected -> `superseded`), and an accepted decision that says it is a
target or not yet in effect is marked `implemented: false`. A file without a Decision section,
or with sensitive content, is reported and not published. A decision is served only where its
ADR file is: `serving.exclude` and `visibility: local` apply to both.

- `beacon build --repo R` reads `R/beacon.yaml` as the **intent** authority. When it exists it is
  the only intent that build may use: `--intent` may name it, or supply intent for a repository
  that has none, but never replace it (`intent_manifest_conflict`). A malformed or symlinked
  `beacon.yaml`, or one that changes during the build, refuses the build and nothing is written.
- `beacon build --repo R --gaps-only` writes nothing and reports, for every field, whether it was
  supplied, by which source, and what is still missing -- including when a required field (name,
  description, canonical docs) is unresolved and a real build would refuse. Inconsistent inputs
  (the indexed root differs from `--repo`, or the manifest cites a document missing on disk) are
  errors to fix first, not gaps.
- Without a `beacon.yaml` a build succeeds when the project's files (or a memory provider)
  supply a description and at least one entry document; the result is thin and lists every
  empty field as a gap. With none of them, the build refuses and points to `--gaps-only`.
- What Beacon asks for, and which source may supply each field (`intent`, `declared`, `git`,
  `memory`, `inferred`, `derived`; `forge` is catalogued for a later adapter), is published in
  [`docs/schemas/beacon-requirements-1.1.json`](docs/schemas/beacon-requirements-1.1.json).
  Guardrails, problem and non-goals come only from the project's own manifest. A description
  from the files or a memory provider also fills `purpose.one_sentence`; that is reported as a
  placeholder supplied by that source, never as the maintainers' words.

### Project state from the code host (opt-in)

`beacon build --repo . --forge` reads project state from GitHub for a checkout whose origin is
on GitHub: open milestones become the current focus (the earliest due is the active work),
open issues labelled `blocker`/`blocked` and `decision`/`needs-decision`/`rfc` become blockers
and pending decisions, `good first issue` issues become safe first tasks, and releases become
recently completed work. Each item cites its URL, capped at five per field. `beacon.yaml` wins
wherever it states a field. The token is read from `BEACON_FORGE_TOKEN` (else `GITHUB_TOKEN`)
and only sent as a header; public repositories work without one. A rate limit, refused access
or an unreachable host stops the forge source at once, without retrying, and the build
continues without it and reports why.

The label names are the project's call. Override any group in `beacon.yaml` (an empty list
turns that group off; groups you leave out keep the defaults):

```yaml
forge:
  labels:
    blockers: [P0, blocked]
    pending_decisions: [needs-decision]
    safe_first_tasks: []
```

This block configures the build and is never served to agents.

### What Beacon serves

Beacon serves only the documents listed in `canonical_docs` (and those found by convention or a
memory provider), and only within these rules:

- **Owner exclusions win.** `serving.exclude` lists path globs no surface serves, even when a
  convention or memory provider lists the document. `*` crosses directories; a trailing `/`
  excludes a whole directory.
- **Sensitive files are never served**: `.env` files, private keys, credential files and similar,
  even when listed. The build omits them and reports it.
- **Text documents only** (Markdown and plain text) reach MCP clients.
- **A document with a high-confidence secret** (a private key, a credential in a URL, a known
  token format) is withheld from MCP clients. Snapshot export keeps its blocking security gate
  with reviewed `CODE=REASON` overrides.
- **`visibility: local`** on a `canonical_docs` entry serves it to local MCP clients only; it is
  never exported to a snapshot, the HTTP API or the Hub.
- **`serving.traversal`** switches `beacon_catalog` and `beacon_read` on (the default) or off.

```yaml
canonical_docs:
  - path: docs/operations.md
    role: workflow
    visibility: local        # this machine's agents only; never published
serving:
  exclude: [deploy/, "*.secret.md"]
  traversal: true
```

A withheld document is never listed, searched, read or named; asking for it returns the same
`read_not_found` as a path that does not exist. The `serving` block configures Beacon and is
never served to agents.

### Memory providers

A memory provider reports what it has indexed about a project. Beacon defines the contract;
any platform can implement it (Menhir is one). A provider only answers: it never reads your
checkout or writes into your repository.

```bash
export BEACON_MEMORY_TOKEN=...          # read-only credential, sent as a bearer header
beacon build --repo . --memory https://memory.example.com/mcp --memory-project my-project
# or, offline, from a document the provider exported:
beacon build --repo . --memory-evidence evidence.json
```

- **Which project.** `--memory-project` is the project's id at the provider. Omit it and Beacon
  asks the provider by this checkout's `origin`; a provider that indexed several checkouts of
  the repository refuses and names them, so pass the one you mean.
- **Contract.** One MCP tool, `get_beacon_evidence(project_id)` or
  `get_beacon_evidence(repository)`, returning a
  [`beacon-memory-evidence-1.1`](docs/schemas/beacon-memory-evidence-1.1.schema.json) document.
  Its `binding` names the provider, the project's id there, the repository it indexed and the
  commit it indexed.
- **Freshness.** Beacon publishes only when this checkout is that repository at that commit.
  Uncommitted edits are allowed only to `beacon.yaml` and Beacon's own outputs; anything else
  refuses with `memory_stale`, so re-index or commit first.
- **Failures refuse; nothing is written.** `memory_unavailable` (unreachable or timed out),
  `memory_unauthorized` (credential rejected), `memory_invalid` (not usable evidence, including
  unbound 1.0 evidence), `memory_binding_mismatch` (another project or repository). There is no
  retry, cache or silent fallback; leave `--memory` off to build from the manifest and git alone.
- The URL must be `https` (plain `http` only on loopback) and may not carry credentials. A
  remote (`https`) provider needs `BEACON_MEMORY_TOKEN`; a loopback development provider may run
  without one.
- Legacy `beacon-menhir-evidence-1.0` documents are still read by `--gaps-only`; they have no
  binding, so they cannot publish. `--menhir-evidence` is a deprecated alias of
  `--memory-evidence`.

---

## What agents can ask

Beacon registers seven read-only MCP tools when the server starts. Search finds a section; `beacon_catalog` and `beacon_read` let an agent browse and read only the sections it needs.

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

Keyword search across docs, concepts, decisions (ADRs), and guardrails. Every result carries a status (`current`, `experimental`, `superseded`) and a `why_relevant` field; document and decision hits also carry a `chunk_id` for `beacon_read`. An unfiltered search returns at most three decisions; filter on `decisions` for more.

```
Inputs:
  query:        search string
  source_types: list of "docs" | "concepts" | "decisions" | "guardrails" (default: all)
  limit:        max results (default: 8)
```

### `beacon_explain_concept`

> *"What is blast_radius and where is it implemented?"* / *"Why adr-0005?"*

Looks up a project-specific term by id or name. Returns the definition, motivation, related concepts, and implementation locations. Given an ADR id (`adr-0005`) or title, it returns the decision verbatim, the alternatives considered with their reasons, and where to `beacon_read` the context and consequences.

```
Inputs:
  concept: concept id or display name, or an ADR id or title
  depth:   "simple" | "technical" | "implementation" (default: "technical")
```

### `beacon_guardrails`

> *"What should I avoid touching, and what checks are required?"*

Returns the full guardrail set, filtered to a task if a hint is provided. Includes risky files aggregated from `applies_to` fields and the project's required test/build commands.

```
Inputs:
  task_hint: description of planned work (optional)
```

### `beacon_catalog`

> *"Which documents can I read, and what sections do they have?"*

Lists the served documents in reading order, with role, title, status and each section's
heading, lines and `chunk_id`. Withheld documents are never listed.

```
Inputs:
  role, status:  filters (optional)
  offset, limit: paging (default limit: 50)
```

### `beacon_read`

> *"Show me that section."*

Returns one section's text with its citation (path, lines, status) and `next_chunk_id`, the
following section. At most 4,000 characters by default and 8,000 at most; a longer section is
marked `truncated` and carries `next_offset`: read the same `chunk_id` with that `offset` for the
rest of it. The `chunk_id` is the same one the HTTP API serves at `/v1/chunks/{id}`.

```
Inputs:
  chunk_id:  from beacon_catalog or beacon_search
  path:      with heading (a section title) or line (a line number), or alone for the first section
  max_chars: 200-8000 (default: 4000)
  offset:    character position inside the section (default: 0; from next_offset)
```

Both tools return `traversal_disabled` when the project sets `serving.traversal: false`.

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
2. Applies the serving rules (see [What Beacon serves](#what-beacon-serves)), then reads each served `canonical_docs` entry and chunks it at Markdown headings into an in-memory `DocIndex`.
3. Stores the resulting `ManifestBeaconProvider` in a module-level slot.

On each tool call, the provider reads from the in-memory index and returns a frozen answer dataclass. It does not call an LLM, access the network, or query a database.

`BeaconProvider` is a typed protocol, so another provider can supply the same tools without changing their answer contracts. A future Menhir-backed provider could add temporal memory, structure graphs, and Git history behind that interface.

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

`beacon export` writes `beacon.snapshot.json` by default; `--output PATH` picks
another file and `--output -` writes the snapshot to stdout. Re-running export
replaces a previous Beacon snapshot at the same path, but any other existing
path is refused with exit 2 (`export_output_exists`) unless you pass `--force`.
The manifest and canonical documents are never overwritten, even with `--force`
(`export_output_collision`).

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

Build-time memory evidence is available through the backend-neutral provider contract (see
[Memory providers](#memory-providers)); a live, query-time memory provider is later roadmap work,
not evidence that this v0.2 scope is unfinished. Beacon is static and has no outbound runtime network call: no database,
no LLM or embedding, no telemetry, and no update check. The optional HTTP compatibility process
listens only on loopback and serves the same startup snapshot. Beacon reads only the manifest and
the documents it lists.

Beacon aims to become an open standard: an MCP endpoint each project publishes so coding agents can
ask it, live and with citations, what the project is and how to work on it;
the direction, roles and track are in [`docs/beacon-open-standard.md`](docs/beacon-open-standard.md).
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

Please hold off on adding tools or expanding the manifest schema. The seven tools (the five v0 tools plus `beacon_catalog` and `beacon_read`, added so agents can read sections without file access) need clearer documentation and easier client setup before the interface grows further.

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
