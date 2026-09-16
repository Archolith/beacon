# Beacon v0.2 — Publishable Static Product

**Status:** READY FOR IMPLEMENTATION
**Date:** 2026-09-15
**Owner:** Beacon
**Parent roadmap:** `docs/beacon-functional-product-roadmap.md` — v0.2
**Plan anchor commit:** `77ad631` (originals authored); current `master` `77e341e`
**Target release:** `0.2.0`
**Supersedes:**
`.agent/plans/archive/beacon-v0.2-publishable-static-product-plan-2026-08-09.md`,
`.agent/plans/archive/beacon-v0.2-implementation-readiness-addendum-2026-08-09.md`
**Siblings:**
`.agent/plans/beacon-build-pipeline-and-source-adapters-plan-2026-09-15.md` (owns `beacon build`
and the multi-source pipeline — ownership boundary in §11),
`.agent/plans/beacon-multi-intent-beacons-plan-2026-09-15.md` (owns intent-scoped beacons),
`.agent/plans/beacon-trust-hub-and-federation-plan-2026-08-09.md` (v0.3+ trust/federation)

## 0. What this merge changed

This document replaces the 2026-08-09 product plan and its implementation-readiness addendum. The
content is preserved; the structure is not. Three substantive changes:

1. **One decisions list (§3).** The product plan's locked decisions, its approved release decisions,
   and the addendum's readiness decisions were three lists covering the same release. They are now
   `D1`–`D24` in one place. The addendum's "normative where it is more specific" precedence rule is
   gone, because there is nothing left to take precedence over.

2. **One merge order (§7), resequenced in three places.** The two documents carried different
   orderings of the same work. Reconciling them exposed a real defect and two duplications — see
   §7.1 for what moved and why.

3. **The snapshot-writer overlap is resolved (§11).** WP3 (`beacon export`) owns the canonical
   writer and source digests for v0.2. The build-pipeline plan's Step 1 does not re-implement it.

## 1. Outcome

Ship Beacon as a dependable local product that a maintainer can install, initialize, review, export,
and connect to a coding agent without editing Python or asking the Beacon maintainer for help.

The release is complete when a maintainer unfamiliar with Beacon can go from an existing repository
to a validated, inspected, source-cited local Beacon in 15 minutes, using only the CLI and docs.

v0.2 product loop:

```text
install wheel
  -> beacon init
  -> review beacon.yaml
  -> beacon validate --strict-warnings
  -> beacon inspect --task-hint "..."
  -> beacon export
  -> connect MCP client / beacon serve
  -> commit beacon.yaml + reviewed snapshot if desired
```

## 2. Current baseline

The release starts from a working manifest-driven product, not from zero.

| Capability | Current state | v0.2 disposition |
| --- | --- | --- |
| Manifest schema/loader/validator | Shipped, `beacon_version: "0.1"` | Preserve compatibility |
| Canonical Markdown doc index | Shipped, deterministic | Reuse in export and inspect |
| Five read-only MCP tools | Shipped | Freeze names, inputs, and answer dataclasses |
| `beacon` stdio server | Shipped as no-argument default | Preserve; add explicit `serve` alias |
| `beacon validate PATH` | Shipped | Add defaults, JSON, strict warnings |
| `beacon inspect PATH` | Shipped | Add defaults, task hint, JSON |
| Self-referential `beacon.yaml` | Shipped and clean | Keep as release smoke fixture |
| Offline tests | 59 passing at `77ad631` | Expand to CLI/export/init/package contracts |
| `beacon init` | Missing | Build safely and deterministically |
| Canonical export/snapshot | Missing | Build reviewable static export |
| Examples | Missing | Add library, service, monorepo/research examples |
| Dedicated client setup guide | README only | Add one tested guide |
| Golden CLI output contracts | Partial assertions only | Add JSON contract and stable fixture tests |
| Distribution/release metadata | Inconsistent/incomplete | Resolve before package publication |
| MCP framework dependency | Legacy `cth-mcp-framework` editable install | Migrate to public Archolith distribution |
| Release CI | Added `ruff` + `pytest` workflow (`382ed7b`) | Extend to build/wheel-smoke/matrix |
| Repository ignore rules | No `.gitignore` | Add Python/build/output hygiene |
| Git release tags | None | Create only after release gate passes |

**Known release-truth conflict.** README already uses the approved distribution name
`archolith-beacon`, while `pyproject.toml` still declares `name = "beacon"` at `version = "0.1.0"`.
WP0 must make the metadata consistent and successfully reserve/publish the distribution under
Archolith ownership before documenting installation as complete.

**Dependency release prerequisite.** Beacon still declares `cth-mcp-framework>=0.1.0` and imports
`cth_mcp_framework`. The framework has migrated to `Archolith/archolith-mcp-framework`,
distribution `archolith-mcp-framework`, import `archolith_mcp_framework`, tag `v0.2.0`, but is not
yet available from the public package index. WP0 must publish that framework first and must not put
a direct Git dependency in Beacon's public package metadata.

**Snapshot contract gap.** `docs/schemas/beacon-snapshot-1.0.schema.json` requires
`manifest.source_sha256` and a per-document `source_sha256`, and nothing in `src/beacon/` computes a
digest. The contract has required fields that no code produces. WP3 closes this.

## 3. Locked decisions

`D1`–`D24` are locked for v0.2. Changing one requires updating its fixtures, command examples,
acceptance checks, and this plan before implementation diverges.

### 3.1 Scope and behavior

- **D1 — Static and offline.** No database, network, external service, embeddings, or runtime LLM.
- **D2 — Read-only.** Beacon does not modify source files except the explicit `init` output selected
  by the maintainer.
- **D3 — Public MCP freeze.** No sixth tool and no incompatible change to the five tool names,
  inputs, provider methods, or answer dataclasses.
- **D4 — Manifest compatibility.** Generated manifests use `beacon_version: "0.1"`; no new required
  manifest field. (This is the manifest-stability commitment; the repository's own
  `no_manifest_schema_change` guardrail in `beacon.yaml` states the same rule for contributors.)
- **D5 — CLI compatibility.** Running `beacon` with no subcommand continues to start stdio. An
  explicit `beacon serve` command is additive.
- **D6 — Deterministic automation.** `init` is non-interactive by default; `export` is byte-stable
  for unchanged inputs; machine output is JSON on stdout with diagnostics on stderr.
- **D7 — Safe generation.** `init` never overwrites an existing file unless `--force` is explicit,
  and `--dry-run` performs no write.
- **D8 — Honest discovery.** Generated values come only from bounded repository evidence. Unknown
  setup, test, architecture, or guardrail values remain review items; Beacon does not invent
  commands.
- **D9 — Snapshot boundary.** The v0.2 export is a static, canonical source snapshot for review, CI,
  and future fallback. It does not introduce the v0.3 normalized multi-adapter knowledge envelope.
- **D10 — No release claim without a wheel.** Source-checkout success is insufficient; the built
  wheel must install and run in a clean environment.

### 3.2 Contracts

- **D11 — Unknown/review state.** Keep guesses out of the manifest. Omit optional unknowns; mark
  required unknown knowledge factually with `status: unknown`; expose a structured initialization
  report in text or the shared JSON envelope; persist it only through optional `--report PATH`. YAML
  comments may guide editing but are never authoritative review state. Strict warnings block
  publication.
- **D12 — Snapshot.** Use snapshot schema `1.0`, independent of product `0.2.0` and manifest `0.1`.
  Embed canonical heading-chunk text once by default; offer explicit `--metadata-only`; record the
  content mode and exact source digests.
- **D13 — CLI JSON.** Use shared envelope `beacon.cli-result` version `1.0` with `command`, `ok`,
  command-specific `result`, and stable diagnostics. Raw snapshot stdout and MCP stdio remain
  separately versioned streams. Exit codes: `0` success, `1` validation/policy failure, `2`
  user/input safety failure, `3` unexpected internal failure.
- **D14 — Overwrite.** `--force` is sufficient only for an existing recognizable Beacon manifest that
  is a regular file inside the repository root. Validate and atomically replace it. Never overwrite
  unrelated files, directories, symlinks, or path escapes, and provide no arbitrary-file escape
  hatch.

### 3.3 Platform and safety

- **D15 — MCP baseline.** v0.2 remains on stable FastMCP 3.x and stdio. FastMCP 4 and stateless MCP
  `2026-07-28` migration wait until FastMCP 4 is stable and the Archolith framework migrates.
- **D16 — Repository scale.** v0.2 supports small-to-medium repositories through conservative
  defaults with explicit overrides. Large-monorepo support requires later benchmark evidence.
- **D17 — Intentional absence.** Projects may publish without automated tests or guardrails only when
  each absence is explicitly acknowledged with a reason.
- **D18 — Secret safety.** High-confidence secret findings block `init`/`export` unless an explicit,
  reasoned override is recorded without echoing the secret.
- **D19 — Privacy.** v0.2 performs no telemetry, analytics, update checks, or outbound runtime
  network access. Manifest commands are inert data and are never executed.

### 3.4 Distribution and release

- **D20 — Distribution and ownership.** First publish `archolith-mcp-framework==0.2.0` from
  `Archolith/archolith-mcp-framework`; migrate Beacon to dependency
  `archolith-mcp-framework>=0.2,<0.3` and import `archolith_mcp_framework`; then publish
  `archolith-beacon` under Archolith ownership. Both public distributions use trusted GitHub
  publication and at least two maintainers. Keep `beacon` as Beacon's import and CLI name. Public
  metadata contains no direct Git dependency.
- **D21 — Supported matrix.** Support CPython 3.12, 3.13, and 3.14 on Windows, macOS, and Linux.
  Exclude Python 3.15 prereleases, PyPy, free-threaded builds, and mobile until separately tested.
- **D22 — Release order.** Publish `archolith-mcp-framework==0.2.0`, then
  `archolith-beacon==0.2.0rc1`, then `archolith-beacon==0.2.0`, with TestPyPI smoke before each
  applicable real-index release.
- **D23 — PyPI access.** Archolith account/organization and two-maintainer access are believed to
  exist but remain an explicit WP0 verification gate. No release relies on an assumption about
  access.
- **D24 — Release workflow.** Keep `master` as protected trunk. Implement on `release/v0.2.0`, merge
  by passing PR, annotate the exact merged commit as `v0.2.0`, and trigger GitHub Release/trusted
  package publication only from that tag. Delete the release branch after successful publication.

## 4. Supported maintainer journey

### Step 1 — Install and identify the binary

```text
python -m pip install archolith-beacon==0.2.0
beacon --version
beacon --help
```

Requirements:

- distribution `archolith-beacon`, import package `beacon`, and CLI command `beacon`;
- public dependency `archolith-mcp-framework>=0.2,<0.3`, imported as `archolith_mcp_framework`, with
  no legacy or direct-URL requirement;
- one version source used by package metadata and `beacon --version`;
- useful help without environment variables; and
- CPython `>=3.12,<3.15`, tested on 3.12, 3.13, and 3.14 across Windows, macOS, and Linux.

### Step 2 — Initialize

```text
cd existing-project
beacon init
beacon init --dry-run
beacon init path/to/project --output path/to/beacon.yaml
```

`init` discovers a conservative starter manifest from bounded signals:

- project name from the repository directory;
- repository URL from the configured git remote, with credentials/userinfo removed;
- language hints from known build files;
- license from a known license filename;
- canonical entry docs from an allowlist of files that exist;
- setup/test commands only when a supported build file provides an unambiguous command; and
- explicit review-report entries for unknown purpose, guardrails, and uncertain commands.

The discovery allowlist should include common agent/project entry points such as `README.md`,
`CONTRIBUTING.md`, `AGENTS.md`, `.agent/README.md`, and bounded architecture/index files under
`docs/`. It must exclude `.git`, virtual environments, build outputs, generated artifacts, hidden
secrets, and files outside the selected repository root.

`init` requirements:

- deterministic ordering and YAML output;
- relative, normalized manifest paths;
- no recursive content ingestion;
- no path escape through symlinks or `..`;
- no overwrite by default; `--force` replaces only an existing recognizable Beacon manifest;
- atomic write when it does write;
- an explicit structured summary of discovered, omitted, and review-required fields;
- `--format json` for the report and optional `--report PATH` persistence without a surprise second
  file by default;
- no authoritative review state stored only in YAML comments;
- optional unknown fields omitted or empty, and required unknown values stated factually with the
  enclosing knowledge status set to `unknown`; and
- generated output parses and has zero validation errors.

Warnings are acceptable immediately after generation when a real value is unknown. Publication is
gated by `validate --strict-warnings`, so the maintainer must resolve them rather than accept
guesses. Known sensitive files (§6.4) are never proposed as canonical documents.

### Step 3 — Validate and inspect

```text
beacon validate
beacon validate path/to/beacon.yaml --strict-warnings
beacon validate --acknowledge test_command_missing="research repo, no test suite yet"
beacon validate --format json
beacon inspect
beacon inspect --task-hint "add a parser regression test"
beacon inspect --format json
```

Both commands default to `./beacon.yaml` while retaining positional-path compatibility.

Shared CLI behavior:

- `--docs-root` overrides path resolution consistently;
- text is the human default;
- `--format json` emits one `beacon.cli-result` version `1.0` envelope on stdout;
- the envelope carries `command`, `ok`, command-specific `result`, and diagnostics with stable
  `severity`, `code`, `path`, and `message` fields;
- expected machine-mode outcomes produce exactly one JSON document and no human prose;
- stderr is reserved for logs and failures that occur before an envelope can be built;
- exit `0` means the command completed under the selected policy;
- exit `1` means validation or strict-warning failure;
- exit `2` means invalid arguments, missing inputs, unsafe paths, or refused overwrite;
- exit `3` means an unexpected internal failure; and
- Unicode output works on Windows without corrupting machine JSON.

`export --output -` emits the raw versioned snapshot rather than a CLI envelope, and `serve` emits
MCP stdio. These are protocol/artifact streams, not ordinary CLI results.

`inspect --task-hint` must exercise task-scoped onboarding and guardrails rather than only the
provider's no-argument defaults. JSON inspection returns the complete payload for all five tools,
not the truncated human presentation.

Validation policy, warning codes, and acknowledgement rules are normative in §6.3.

### Step 4 — Export

```text
beacon export
beacon export --output beacon.snapshot.json
beacon export --output -
beacon export --metadata-only
```

The canonical export is a self-contained JSON representation of the static Beacon inputs, suitable
for code review and CI diffing. It includes:

- `beacon_snapshot_version: "1.0"`;
- generator distribution/version and `content_mode: "embedded"` or `"metadata_only"`;
- project identity and `beacon_version`;
- canonical serialized manifest data;
- manifest SHA256;
- canonical docs with relative path, role, status, title, content SHA256, and heading chunks with
  line ranges and text; and
- source/build metadata required to explain how the snapshot was constructed, excluding volatile
  wall-clock fields from canonical content.

Canonicalization rules:

- UTF-8, final newline, sorted mapping keys, stable list ordering;
- repository-relative forward-slash paths;
- no absolute local paths, environment values, credentials, timestamps, or host identifiers;
- identical bytes for unchanged inputs; and
- atomic file replacement, with stdout mode performing no file write.

The default snapshot embeds each canonical heading chunk's text once. It does not also duplicate the
complete document body. `--metadata-only` emits document metadata, structure, and hashes without
text. Documentation must state plainly that the default snapshot contains the selected canonical
documents' content.

Export blocks on errors and unresolved publication warnings, and on high-confidence secret findings
(§6.4). Accepted acknowledgements and sensitive overrides are recorded in snapshot metadata.

The snapshot is a review/export artifact in v0.2. Loading and querying snapshots as a provider
fallback is v0.3 work and belongs to the build-pipeline plan (§11).

### Step 5 — Serve and connect

```text
beacon serve --manifest beacon.yaml
# compatibility path remains valid:
BEACON_MANIFEST_PATH=/absolute/path/to/beacon.yaml beacon
```

Requirements:

- explicit `serve` command with CLI path/docs-root options;
- no-argument environment-driven stdio remains byte/behavior compatible;
- startup reports project, manifest path, validation status, provider mode, and effective non-secret
  limits to stderr only;
- tool stdout remains reserved for MCP framing; and
- shutdown/invalid-manifest behavior is covered by a process smoke test.

## 5. Normative policies

These cut across work packages. A WP that touches a reader, a diagnostic, or an output artifact must
satisfy the policies here.

### 5.1 MCP and dependency compatibility

v0.2 contract:

- runtime framework `archolith-mcp-framework>=0.2,<0.3`, imported as `archolith_mcp_framework`;
- FastMCP stable `>=3.2.4,<4` as constrained by the framework;
- stdio only as the supported release transport;
- existing no-argument `beacon` stdio behavior remains compatible;
- five tool names, input shapes, answer dataclasses, and provider protocol remain frozen; and
- v0.2 does not claim support for MCP `2026-07-28` or the FastMCP 4 extension model.

Required evidence before release:

1. Record the actual MCP protocol version(s) negotiated by the installed FastMCP 3 stack.
2. Run a black-box stdio test through the packaged console command, not only direct Python calls.
3. Run the documented setup against each supported MCP client fixture.
4. Verify that stdout contains only MCP frames and stderr carries logs.
5. Record the framework and FastMCP versions in release diagnostics.

FastMCP 4 migration is a separate compatibility project. It must test old and current protocol-era
clients before Beacon changes its stated support.

### 5.2 Resource limits

| Limit | Default | Applies to |
| --- | ---: | --- |
| Manifest source bytes | 1 MiB | load, validate, inspect, export, serve |
| YAML nesting depth | 32 | manifest parsing |
| YAML parsed nodes | 50,000 | manifest parsing |
| YAML aliases | 50 | manifest parsing |
| Canonical documents | 256 | inspect, export, serve |
| One canonical document | 2 MiB | indexing/export |
| Total canonical source bytes | 20 MiB | indexing/export |
| Total heading chunks | 10,000 | indexing/export/search |
| One relative path | 1,024 UTF-8 bytes | manifest/init/export |
| Query text | 4 KiB | search and task hints |
| Search result limit | 100 | provider/tool calls |
| Snapshot output | 50 MiB | export |
| Initialization report | 5 MiB | init report/stdout |

`MiB` means 1,048,576 bytes. Byte limits are checked before decoding or parsing. Integer arithmetic
must reject overflow and negative configuration values.

Each limit has one explicit CLI option and matching environment setting. CLI overrides environment;
environment overrides defaults:

```text
--max-manifest-bytes       / BEACON_MAX_MANIFEST_BYTES
--max-documents            / BEACON_MAX_DOCUMENTS
--max-document-bytes       / BEACON_MAX_DOCUMENT_BYTES
--max-total-document-bytes / BEACON_MAX_TOTAL_DOCUMENT_BYTES
--max-chunks               / BEACON_MAX_CHUNKS
--max-snapshot-bytes       / BEACON_MAX_SNAPSHOT_BYTES
```

Parser depth/node/alias and path/query/result ceilings remain non-overridable safety limits in v0.2.
Server startup logs effective non-secret limits to stderr. CLI JSON results report effective limits
in command-specific `result` data where relevant.

An override does not establish large-repository support. Release notes describe only the standard
profile until a larger profile passes memory, time, and output-size benchmarks.

Failure behavior:

- limit checks happen before expensive work;
- exit code is `2` for user-configured/input safety refusal;
- stable diagnostic codes identify the exact limit;
- partial init/export artifacts are removed;
- diagnostics never include full document content; and
- no command silently truncates a canonical document or snapshot.

### 5.3 Validation and publication policy

```text
beacon validate
  errors block
  warnings are reported
  exit 0 when no errors

beacon validate --strict-warnings
  errors block
  unresolved publication warnings block
  explicitly permitted acknowledgements may resolve only allowlisted warnings

beacon serve
  errors block startup
  warnings are emitted and remain visible in diagnostics

beacon export
  errors and unresolved publication warnings block
  accepted acknowledgements are recorded in snapshot metadata
```

The validator must add stable codes, including:

| Code | Condition | Acknowledgeable in v0.2 |
| --- | --- | --- |
| `project_status_unknown` | `project.status` is `unknown` | No |
| `purpose_missing` | `purpose.one_sentence` is empty | No |
| `test_command_missing` | no automated test command is declared | Yes |
| `guardrails_missing` | no guardrail is declared | Yes |
| `concept_definition_missing` | concept has no definition | No |
| `related_concept_unknown` | related concept ID does not resolve | No |
| `knowledge_status_invalid` | status is outside controlled vocabulary | No |
| `canonical_doc_duplicate` | duplicate canonical path | No |

Existing error conditions retain error severity. Setup and benchmark commands are optional and do
not warn by themselves.

Explicit acknowledgement uses a repeatable option `--acknowledge CODE=REASON`:

- only `test_command_missing` and `guardrails_missing` are acknowledgeable in v0.2;
- reason is trimmed, non-empty, and at least 10 characters;
- unknown, duplicate, malformed, or unallowlisted codes cause exit `2`;
- acknowledgement changes policy disposition, not the underlying diagnostic severity or facts;
- text and JSON output label the diagnostic as acknowledged and preserve the reason;
- export records code and reason in `validation.acknowledgements`; and
- acknowledgements do not modify `beacon.yaml` or pretend a capability exists.

CI must include acknowledgements explicitly in its command or wrapper configuration. Comments and
empty strings are not acknowledgement mechanisms.

### 5.4 High-confidence secret policy

v0.2 blocks only high-confidence classes with bounded, deterministic detectors:

- PEM/OpenSSH private-key material;
- credential-bearing URLs with non-placeholder userinfo;
- supported provider token formats with strong fixed prefixes/check structure; and
- known sensitive files proposed by discovery, including `.env`, private key, credential, and
  netrc-style files.

Generic entropy guesses and broad words such as `password` do not block by themselves. This feature
is a safety backstop, not a replacement for a dedicated secret scanner.

Stable codes begin with:

```text
sensitive_private_key
sensitive_credential_url
sensitive_known_token
sensitive_file_excluded
```

Detection behavior:

- `init` never proposes known sensitive files as canonical documents;
- embedded `export` scans selected manifest/doc text before writing;
- metadata-only export still scans manifest values and paths but does not read doc bodies beyond
  bytes required for hashing/path validation;
- findings report code, relative path, and line when safe, but never the matched value;
- finding values and surrounding text are not logged; and
- detection is deterministic and offline.

An exceptional export accepts a repeatable `--allow-sensitive CODE=REASON` under the same reason and
validation rules as acknowledgements. The override is recorded in `validation.security_overrides`
and visible in human output. It never applies to credential-bearing git remotes discovered during
init, path escapes, private-key files selected by discovery, or Beacon's own process environment.

### 5.5 Privacy and network promise

For every v0.2 runtime command after installation:

- no telemetry or usage analytics;
- no update/version checks;
- no remote schema fetches;
- no HTTP, DNS, git fetch, registry, or external-service calls;
- no runtime LLM, embeddings, or hosted inference;
- no execution of manifest setup/test/benchmark commands; and
- no document bodies in ordinary logs.

Reading local git configuration to discover a sanitized remote URL is allowed; invoking networked
git operations is not.

Tests deny outbound socket creation for init/validate/inspect/export/serve startup paths. Any
optional dependency telemetry is disabled or excluded. Release documentation distinguishes package
installation network access from Beacon runtime behavior.

### 5.6 Executable JSON contracts

Three schemas are machine contracts. Implementation changes to them require fixture updates and
explicit plan review; prose examples alone do not change a machine contract.

- `docs/schemas/beacon-cli-result-1.0.schema.json` owns the common envelope and diagnostic shape.
  Command-specific `result` schemas may narrow it, but may not change envelope fields. Human output
  is not a machine contract. JSON mode emits one UTF-8 document plus a final newline.
- `docs/schemas/beacon-init-report-1.0.schema.json` owns persisted/dry-run report shape. Paths are
  repository-relative and forward-slash normalized. Evidence records describe bounded observations;
  they do not embed source documents or environment values.
- `docs/schemas/beacon-snapshot-1.0.schema.json` owns the static snapshot shape, requiring separate
  product/generator, manifest, and snapshot versions; exact source digests; explicit content mode;
  canonical manifest data; relative document paths and source line ranges; validation
  acknowledgements and sensitive overrides; and no timestamp or host identity in canonical content.
  Runtime checks enforce byte, path, aggregate chunk, canonicalization, and content-mode constraints
  that JSON Schema cannot fully express.

## 6. Work packages

### WP0 — Release truth and repository hygiene

Purpose: remove ambiguity before adding user-facing commands.

Files likely involved: `pyproject.toml`, `src/beacon/__init__.py`, `src/beacon/main.py`,
`src/beacon/mcp/server.py`, `README.md`, `LICENSE`, `.gitignore`, `.github/workflows/ci.yml`,
release documentation.

Tasks:

1. Change package metadata to the approved distribution `archolith-beacon`; retain import package
   and CLI name `beacon`; verify package-index availability and Archolith ownership before upload.
2. Publish `archolith-mcp-framework==0.2.0` from its canonical Archolith repository, then replace
   Beacon's legacy dependency/imports with `archolith-mcp-framework>=0.2,<0.3` and
   `archolith_mcp_framework`. Preserve the five-tool behavior through compatibility tests. Add the
   protocol-version diagnostic test required by §5.1.
3. Make version metadata single-source and expose `beacon --version`.
4. Add complete package metadata: README, license, repository/issues URLs, classifiers, and package
   inclusion checks.
5. Add `.gitignore` for Python bytecode, virtual environments, build outputs, coverage, local env,
   and generated snapshots while allowing committed example snapshots when explicitly located.
6. Declare CPython `>=3.12,<3.15` and test 3.12/3.13/3.14 on Windows, macOS, and Linux; do not claim
   PyPy, free-threaded, Python 3.15 prerelease, or mobile support.
7. Add build/test dependencies or documented tool installation for `python -m build` and package
   metadata validation.
8. Keep `master` as protected trunk; use `release/v0.2.0`, PR into `master`, annotated `v0.2.0`
   tagging after merge, and tag-triggered trusted publication. Correct the hook's stale message.

Acceptance:

- package name and install docs agree;
- the framework installs from the public index under its Archolith name and Beacon contains no
  legacy `cth-mcp-framework` or direct-URL dependency;
- `beacon --version` equals built metadata;
- the negotiated MCP protocol version is recorded by a test, not assumed;
- wheel/sdist contain expected code, README, and license only;
- no bytecode/build junk appears in `git status`; and
- a clean wheel install can run help, version, validate, and inspect.

### WP1 — Limits, diagnostics, and bounded readers

Purpose: establish the safety floor every later reader depends on. This WP exists because every
command in §4 reads repository bytes, and the limits in §5.2 must be enforced before the first
reader is written rather than retrofitted onto three of them.

Suggested modules: `src/beacon/core/limits.py`, `src/beacon/core/diagnostics.py`,
`src/beacon/config/settings.py`, `tests/test_limits.py`.

Tasks:

1. Implement the §5.2 limits model with CLI/environment/default precedence and overflow-safe
   arithmetic.
2. Implement bounded manifest and document readers that check byte limits before decoding or
   parsing, and bounded YAML parsing for depth, nodes, and aliases.
3. Implement the stable diagnostic code/severity registry covering §5.2 limit codes, §5.3 warning
   codes, and §5.4 sensitive codes.
4. Implement the strict-warnings policy and the `--acknowledge CODE=REASON` mechanism per §5.3.
5. Ensure failure paths remove partial artifacts and never emit document content in diagnostics.

Acceptance:

- each limit has a test that trips it before excessive allocation and leaves no partial output;
- every diagnostic code is stable, documented, and asserted by code rather than message text;
- strict validation distinguishes unresolved from explicitly acknowledged absence; and
- unallowlisted or malformed acknowledgement input exits `2`.

### WP2 — Coherent CLI and machine contracts

Purpose: make the current capabilities scriptable and consistent.

Files likely involved: `src/beacon/main.py`, a shared CLI result/render module under
`src/beacon/core/` or `src/beacon/cli/`, `src/beacon/config/settings.py`, `tests/test_cli.py`,
`.agent/architecture.md`.

Tasks:

1. Implement the shared `beacon.cli-result` `1.0` envelope against
   `docs/schemas/beacon-cli-result-1.0.schema.json`, with success and negative golden fixtures.
2. Centralize manifest loading, docs-root resolution, validation, and error normalization so
   commands do not drift, on top of WP1's bounded readers.
3. Add default manifest discovery (`./beacon.yaml`) to validate/inspect/export.
4. Add consistent `--docs-root`, `--format text|json`, and the approved 0/1/2/3 exit codes.
5. Add `--strict-warnings` to validation, wired to WP1's policy.
6. Add task-hint inspection that invokes task-scoped onboarding and guardrails.
7. Add an explicit `serve` command and `--version` while preserving no-argument stdio.
8. Keep stdout/stderr separation safe for MCP, snapshot, and JSON consumers.

Acceptance:

- old positional commands continue to pass;
- no-argument server behavior remains covered;
- every command has help, success, user-error, and JSON tests;
- JSON outputs are parsed and schema-asserted, not matched as prose; and
- Windows UTF-8 and path tests pass.

### WP3 — Secret detection, discovery, and `beacon init`

Purpose: create the first usable product entry point, on a detector that `export` also uses.

Suggested modules: `src/beacon/core/sensitive.py`, `src/beacon/core/discovery.py`,
`src/beacon/core/scaffold.py`, `src/beacon/main.py`, `tests/test_sensitive.py`, `tests/test_init.py`.

Tasks:

1. Implement the §5.4 high-confidence detectors and sensitive-file exclusion list as one shared
   module consumed by both `init` and `export`. Findings never carry the matched value.
2. Define frozen discovery/result dataclasses, including evidence and review-required fields, and
   serialize the initialization report through WP2's envelope against
   `docs/schemas/beacon-init-report-1.0.schema.json`.
3. Implement bounded marker/doc detection with normalized relative paths.
4. Sanitize git remote URLs and refuse paths outside the selected root.
5. Render deterministic YAML without mutating the existing manifest schema.
6. Implement default refusal, `--dry-run`, `--output`, and `--force` only for a recognizable Beacon
   manifest that is a regular in-root file; never provide a generic arbitrary-file overwrite flag.
7. Write atomically and clean temporary files on failure.
8. Report what was discovered, skipped, and left for review in text and JSON.

Negative tests:

- existing manifest remains byte-identical without `--force`;
- unrelated files, directories, symlinks, and path escapes are refused even with `--force`;
- dry run creates nothing;
- credential-bearing git remote is sanitized;
- symlink/path escape is rejected;
- secret/generated/venv files are not proposed as canonical docs;
- high-confidence secret fixtures block without leaking matched text;
- unknown build system does not generate a fake test command;
- interrupted write leaves no partial manifest; and
- repeated discovery returns the same output.

### WP4 — Canonical static snapshot and `beacon export`

Purpose: give maintainers a reviewable, diffable product artifact, and close the snapshot contract
gap in §2.

Suggested modules: `src/beacon/core/snapshot.py`, `src/beacon/core/canonical_json.py`,
`src/beacon/main.py`, `tests/test_snapshot.py`.

Tasks:

1. Define frozen snapshot dataclasses/schema with `beacon_snapshot_version: "1.0"`, independent
   generator/manifest versions, and explicit embedded/metadata-only content modes, against
   `docs/schemas/beacon-snapshot-1.0.schema.json`.
2. Reuse loader, validator, and `DocIndex` chunking; do not implement a second parser.
3. Compute source digests from exact bytes for the manifest and each canonical document, populating
   the `source_sha256` fields the schema already requires. Normalize only the exported
   representation.
4. Reject dangling/escaping docs before export.
5. Apply the WP3 secret gate before writing, and record `validation.acknowledgements` and
   `validation.security_overrides`.
6. Implement stable JSON serialization, default embedded chunk text, `--metadata-only`, and atomic
   output.
7. Document snapshot stability guarantees and deliberate non-guarantees.

Acceptance:

- two unchanged exports have identical SHA256;
- changing one canonical doc changes its digest and snapshot bytes;
- no absolute path, secret env value, timestamp, or hostname appears;
- line ranges resolve to the exported chunk text;
- invalid manifests/docs produce no output file;
- a golden snapshot fixture detects accidental schema drift; and
- all three schemas pass Draft 2020-12 meta-validation with success and negative fixtures.

### WP5 — Privacy proof and packaged stdio smoke

Purpose: prove the §5.5 promise mechanically rather than by assertion.

Tasks:

1. Deny outbound socket creation in tests covering init/validate/inspect/export/serve startup paths.
2. Run a black-box stdio MCP smoke through the packaged console command.
3. Assert stdout carries only MCP frames and stderr carries logs.
4. Disable or exclude any optional dependency telemetry.

Acceptance: socket-deny tests fail loudly if any path opens a socket; the packaged command serves
five tools and reports the tested framework/FastMCP versions.

### WP6 — Examples, setup docs, and five-minute demonstration

Purpose: prove Beacon is understandable outside its own repository.

Deliverables: `examples/library/`, `examples/service/`, `examples/monorepo-research/`,
`docs/client-setup.md`, updated `docs/demo-transcript.md`, updated README quick start.

Each example includes a valid manifest, minimal canonical docs, expected validation result, and a
small task hint that demonstrates onboarding and guardrails. Examples must use different project
shapes rather than three renamed copies of Beacon's own manifest.

Client setup documentation covers supported stdio clients from one canonical environment/command
model. Examples are tested for path validity and all five provider capabilities in CI.

Acceptance:

- every example validates with zero errors;
- strict-warnings policy is either clean or explicitly explains a deliberate warning;
- inspect/export succeed for every example;
- copy/paste client configurations use the canonical distribution and CLI; and
- the demo begins at installation/init, not from a preconfigured maintainer checkout.

### WP7 — Packaging, CI, and release candidate

Purpose: prove the product works outside the development checkout.

CI gates:

1. full offline tests;
2. self-manifest validation and inspection;
3. example validate/inspect/export matrix;
4. deterministic export comparison;
5. sdist/wheel build and metadata check;
6. clean-environment wheel install and CLI smoke;
7. the complete CPython 3.12/3.13/3.14 x Windows/macOS/Linux matrix; and
8. repository cleanliness after tests.

The release-candidate process follows the supply-chain sequence in §8. No secrets or publishing
credentials belong in ordinary pull-request CI.

### WP8 — Cold-start usability and release scorecard

Purpose: test the product claim, not only the code.

Run one scripted trial for each maintained example and at least one unaided trial with a developer
who did not write the implementation.

Measure: install success and time; time to a generated manifest; validation errors/warnings and time
to resolution; time to understand inspect output; time to connect an MCP client; whether the agent
identifies expected docs/files/commands/guardrails for the example task; and every point where the
user needs undocumented maintainer knowledge.

Exit target:

- complete local setup in 15 minutes;
- zero undocumented blocking step;
- zero unsupported high-confidence claim in maintained example outputs;
- all citations resolve;
- all five tools respond;
- init/export are deterministic and safe; and
- the wheel, not an editable checkout, passes the journey.

Usability failures create blocking v0.2 fixes, not post-release documentation TODOs.

## 7. Merge order

Each unit must leave the existing v0.1 manifests and all five MCP tools green. Do not combine all
commands into one unreviewable CLI rewrite.

| # | Merge unit | WP |
| ---: | --- | --- |
| M1 | Release metadata, distribution rename, framework migration, protocol-version test, `.gitignore` | WP0 |
| M2 | Shared limits model and bounded manifest/document readers | WP1 |
| M3 | Stable diagnostic codes, strict-warnings, and acknowledgement policy | WP1 |
| M4 | Shared CLI envelope + schema + golden fixtures; centralized loading; validate/inspect compatibility | WP2 |
| M5 | Explicit `serve` and `--version`; no-argument stdio compatibility preserved | WP2 |
| M6 | Shared high-confidence secret detectors and sensitive-file exclusions | WP3 |
| M7 | Pure discovery/scaffold core with URL sanitation and path-escape refusal | WP3 |
| M8 | `beacon init` CLI, init-report schema, atomic scaffold, negative paths | WP3 |
| M9 | Snapshot core: canonical JSON, source digests, content modes, golden fixture | WP4 |
| M10 | `beacon export` CLI with secret gate and acknowledgement/override recording | WP4 |
| M11 | Socket-deny privacy tests and black-box packaged stdio MCP smoke | WP5 |
| M12 | Examples, client setup docs, demo transcript | WP6 |
| M13 | CI matrix, build, wheel smoke, release-candidate workflow | WP7 |
| M14 | Cold-start scorecard, usability fixes, release notes | WP8 |

### 7.1 What the reconciliation changed

Three differences between the two original orderings had to be resolved rather than averaged:

1. **The CLI envelope moves ahead of `init` (M4 before M8).** The product plan sequenced `init`
   before the shared CLI work, but its own WP1 task 1 required the initialization report to be
   "serialized through the shared CLI envelope." The original order therefore contradicted its own
   dependency. The addendum's ordering was correct and is adopted.

2. **Limits and diagnostic codes move ahead of every reader (M2–M3 first).** Discovery, validation,
   inspection, and export all read repository bytes. Building the limits model after the first
   reader means retrofitting it onto three more.

3. **Secret detection becomes one unit shared by `init` and `export` (M6).** Both documents
   described detection inside the command that needed it — the product plan under init's negative
   tests, the addendum under both the init and snapshot units. Building it twice would produce two
   detectors with two code sets. It is now one module with one code set, landed before its first
   consumer.

## 8. Release and supply-chain sequence

Before any upload, verify rather than assume:

- Archolith controls both PyPI project namespaces or can register them;
- at least two maintainers have recoverable access to each distribution;
- GitHub Trusted Publishing is configured against the exact repository/workflow/environment;
- recovery contacts and account MFA are current; and
- licenses and repository URLs are present in both package metadata sets.

Current status is `believed available — unverified` until this checklist is recorded (D23).

Publication order:

1. Build, inspect, and TestPyPI-smoke `archolith-mcp-framework==0.2.0`.
2. Publish framework `0.2.0` to real PyPI through Trusted Publishing.
3. Install framework `0.2.0` from real PyPI in a clean environment.
4. Build, inspect, and TestPyPI-smoke `archolith-beacon==0.2.0rc1` while resolving the framework from
   real PyPI.
5. Publish Beacon `0.2.0rc1` to real PyPI and run the full clean-install maintainer journey against a
   temporary repository, recording artifact SHA256 values.
6. Fix any release-candidate defect in a later RC; never replace an uploaded artifact.
7. Build final Beacon `0.2.0` from the approved commit, verify artifact hashes, merge the passing
   `release/v0.2.0` PR into protected `master`, create annotated tag `v0.2.0` on the exact merged
   commit, publish through the tag-triggered workflow, and rerun installed-wheel smoke tests.

No production dependency uses TestPyPI or a direct Git URL. Build artifacts are promoted by exact
digest or rebuilt through a documented reproducible process; they are not hand-edited between checks.

## 9. Verification matrix

Minimum local commands at final review:

```text
python -m pytest -p no:cacheprovider -q
python -m ruff check src tests
python -m beacon --help
python -m beacon --version
python -m beacon validate beacon.yaml --strict-warnings
python -m beacon inspect beacon.yaml --format json
python -m beacon export beacon.yaml --output <temporary-path>
python -m beacon export beacon.yaml --output <second-temporary-path>
python -m build
python -m twine check dist/*
```

Then compare the two export hashes, install the built wheel in a fresh environment, and rerun
version/help/validate/inspect/export from outside the repository.

Test inventory must cover:

- unit: limits, discovery, scaffold rendering, URL/path sanitation, secret detectors, canonical JSON,
  snapshot digests;
- CLI: every command/flag/exit code/text/JSON path;
- schema: Draft 2020-12 meta-validation plus success and negative golden fixtures for all three
  contracts;
- compatibility: existing v0.1 manifest and five MCP tools;
- privacy: socket-deny on every entry path;
- examples: library/service/monorepo matrix;
- packaging: wheel contents and installed console script; and
- process: stdio startup, stderr/stdout separation, invalid startup.

The linter command is already a CI gate (`382ed7b`) and is recorded in
`.agent/workflows/code_conventions.md`. If a formatter or type checker is adopted in WP0, its exact
command becomes a required gate and is added there too.

## 10. Release acceptance checklist

### Product

- [ ] Fresh repository can initialize without source edits.
- [ ] Generated manifest has zero errors and clearly named review items.
- [ ] Strict validation can become clean without undocumented schema knowledge.
- [ ] Inspect exercises all five tools and task-scoped behavior.
- [ ] Export is canonical, source-cited, and byte-stable.
- [ ] Explicit serve and legacy no-argument stdio both work.
- [ ] Three project-shape examples pass in CI.
- [ ] Cold-start journey completes in 15 minutes from the wheel.

### Safety and compatibility

- [ ] Init refuses overwrite and path escape.
- [ ] `--force` replaces only a recognizable in-root Beacon manifest and replacement is atomic.
- [ ] Git remote credentials, environment secrets, and absolute local paths do not leak.
- [ ] High-confidence secret fixtures block without leaking matched text.
- [ ] Standard limits fail before excessive allocation and leave no partial output.
- [ ] Strict validation distinguishes unresolved from explicitly acknowledged absence.
- [ ] Socket-deny tests prove runtime offline behavior.
- [ ] v0.1 manifests and existing five-tool contracts remain compatible.
- [ ] Unknown facts remain warnings/review items rather than guesses.
- [ ] Failed init/export leaves no partial artifact.
- [ ] Tests leave the repository clean.

### Distribution

- [ ] All three schemas pass Draft 2020-12 meta-validation with success and negative fixtures.
- [ ] Packaged stdio reports the tested MCP/framework versions and serves five tools.
- [ ] `archolith-mcp-framework==0.2.0` is publicly installable from its Archolith release.
- [ ] Beacon depends on `archolith-mcp-framework>=0.2,<0.3` with the new import namespace.
- [ ] Beacon has no direct Git dependency or legacy `cth-mcp-framework` runtime requirement.
- [ ] Canonical distribution name is verified and consistent.
- [ ] Version is single-source and reports `0.2.0`.
- [ ] Wheel and sdist metadata pass validation.
- [ ] Framework and Beacon install from public indexes in clean environments.
- [ ] Release branch/tag workflow is documented and compatible with repository hooks.
- [ ] Release notes state actual supported platforms and remaining limitations.

## 11. Boundary with the build-pipeline plan

`beacon export` (WP4) and the build-pipeline plan's Step 1 both described computing source digests
and writing a schema-conforming snapshot. That overlap is resolved as follows:

- **v0.2 owns the writer.** WP4 implements the digests, the canonical serializer, the content modes,
  and the `beacon-snapshot-1.0` conformance, under the command name `beacon export`. It closes the
  contract gap where the schema requires `source_sha256` fields that no code produces.
- **The build-pipeline plan owns the reader and the pipeline.** Loading a snapshot instead of
  re-reading the repository, `beacon build` as the multi-source pipeline entry point, adapters,
  merge policy, and incremental invalidation remain that plan's Step 1 onward. Its Step 1 should
  consume WP4's writer rather than re-implement one.
- **Naming.** In v0.2 there is a single source, so build and export are the same operation and only
  `export` ships. When the pipeline lands, `build` becomes the command that runs adapters and
  produces a snapshot; `export` remains the command that emits one.

## 12. Explicitly deferred to v0.3+

- code/symbol/git/benchmark source adapters beyond conservative init discovery;
- `beacon build`, incremental refresh, and invalidation;
- querying a snapshot as a provider fallback;
- normalized multi-adapter knowledge/View envelope;
- lifecycle/time-mode search filters;
- Menhir or any dynamic provider;
- multiple intent-scoped beacons per project;
- remote transport/auth/operations;
- runtime LLM synthesis;
- durable agent-submitted unanswered-question storage and maintainer review workflow; and
- new MCP tools.

Deferral is important: v0.2 succeeds by making the static product installable and trustworthy, not by
beginning every later architecture layer.
