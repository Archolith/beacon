# Changelog — beacon

## 2026-09-25 — Streamable HTTP as a second MCP transport (issue #26, phase 1)

`beacon serve --snapshot S --transport http` serves the same seven tools over
Streamable HTTP at `/mcp` from a canonical snapshot; stdio stays the default and
every existing stdio path is unchanged.

- `src/beacon/main.py`: `serve` gains `--transport` (`stdio` | `http`), `--host`
  (default `127.0.0.1`) and `--port` (default `8766`, both http-only). `--transport http`
  requires `--snapshot` (`serve_http_requires_snapshot`, exit 2, before anything starts);
  manifest mode stays stdio-only. The serve-http host/port gate moved into a shared
  `_require_loopback(host, port, *, allow_port_zero)` (`http_host_not_loopback`,
  `http_port_invalid`); `serve-http` keeps port 0, `serve --transport http` needs 1-65535.
  `_run_mcp_server(transport, host, port)` runs the same `mcp` object: http prints
  `[beacon] MCP http starting on http://<host>:<port>/mcp (pid=...)` to stderr and calls
  `mcp.run(transport="http", ..., path="/mcp")`; `_serve_with_env` threads the three
  keyword-only parameters through with stdio defaults.
- `README.md`: documents `beacon serve --snapshot S --transport http` (loopback only,
  direct/unverified until the trust plan's broker and signing land, reverse proxy later).
- Tests: `tests/test_mcp_http.py` (new) — CLI refusal cases, plus a black-box parity test
  that starts both a stdio and an HTTP server on one snapshot and asserts identical tool
  lists and identical parsed payloads for all seven tools. Existing tests untouched.

## 2026-09-24 — architecture decision records become served decisions

Plan: workspace `.agent/plans/beacon-why-decisions-design-2026-09-24.md` (owner-approved, Phase 1).
The P3 "why" evaluation found Beacon served no reasons; ADRs are the project's own reviewed ones.

- `src/beacon/sources/adrs.py` (new): reads ADRs from `docs/adr`, `doc/adr`, `docs/decisions`,
  `adr`, `.agent/adr` and `adr_dir`; Nygard and MADR; Decision text verbatim (capped), alternatives
  with reasons, status mapped from its first word with `status_text` kept, `implemented: false`
  for accepted targets, supersession from metadata only, section spans, digest-pinned source.
  Missing Decision sections, unrecognised statuses and sensitive content are reported gaps.
- `src/beacon/sources/declared.py`, `main.py`: `collect_declared_adrs`, run after the intent is
  loaded so `adr_dir` applies.
- `src/beacon/build/policy.py`, `project.py`, `requirements.py`: ADR files join the canonical
  docs (role `decision`, same exclude/sensitive rules) and publish `decisions[]`; `decisions` is
  catalogued (declared) and `adr_dir` is build configuration. `beacon-requirements-1.1.json`
  regenerated (additive).
- `src/beacon/core/schema.py`, `loader.py`, `validator.py`: `BeaconDecision`, `BeaconAlternative`,
  `BeaconSectionSpan`, `decisions` and `adr_dir`; bounded parsing; `decision_id_duplicate`,
  `decision_doc_unlisted`; decision citations join digest drift checks. `beacon_version` stays
  `0.1` (snapshot 1.0 pins it); the section is additive and absent when empty.
- `src/beacon/core/serving_policy.py`, `snapshot.py`: a decision is served only while its ADR file
  is (local and export); decision paths join the unsafe-path check.
- `src/beacon/provider/manifest_provider.py`, `mcp/`: `beacon_search` searches decisions (at most
  three in an unfiltered search, all with `source_types=["decisions"]`); `beacon_explain_concept`
  explains an ADR by id or title with its alternatives and where to read its context.
- Tests: `tests/test_adr_decisions.py` (18).

## 2026-09-24 — beacon_read can finish a long section

Found in review of #21: sections are cut by heading with no size bound, and the only
continuation was `next_chunk_id` (the following section), so text past the 8,000-character cap
could never be read.

- `src/beacon/provider/*`, `src/beacon/mcp/tools/read.py`: `beacon_read` takes `offset`, a
  character position inside the section; an offset outside the section is refused with
  `limit_invalid_value`.
- `src/beacon/core/schema.py`: `DocSection` gains `offset` and `next_offset` (set only when the
  result is truncated). `next_chunk_id` keeps its meaning, the following section, so a client that
  ignores `next_offset` cannot loop on one page.
- `README.md`: the tool reference documents both.
- Tests: paging a long section reassembles it and ends at the following section; bad offsets are
  refused.

## 2026-09-23 — traversable docs over MCP, with serving guards

Plan: workspace `.agent/plans/beacon-doc-traversal-and-guards-plan-2026-09-23.md` (owner-approved,
plus the owner's `serving.traversal` toggle). Found by the P3 agent-task evaluation: with Beacon's
tools alone an agent could find snippets but not read a section, and saw only four documents.

- `src/beacon/core/serving_policy.py` (new): one decision about what each surface serves. Owner
  `serving.exclude` globs win everywhere; sensitive files, non-text files and documents with
  high-confidence secrets are never served to MCP clients; `visibility: local` documents are never
  exported. Withheld documents are reported by path and code only.
- `src/beacon/core/schema.py`, `loader.py`: `canonical_docs[].visibility` (`public` | `local`),
  a `serving` block (`exclude`, `traversal`) that is build configuration and never served, search
  hits' `chunk_id`, and the catalog and read answer types.
- `src/beacon/build/policy.py`, `project.py`, `requirements.py`: excluded and sensitive documents
  are dropped from every source at build; `visibility` and `serving` reach the generated manifest;
  `serving` is catalogued as build configuration.
- `src/beacon/provider/*`, `src/beacon/mcp/*`: `beacon_catalog` and `beacon_read` (5 -> 7 tools),
  refusals rendered as stable error codes (`traversal_disabled`, `read_not_found`,
  `read_target_required`), connect instructions point to catalog and read.
- `src/beacon/core/snapshot.py`, `chunk_resources.py`: export drops excluded and local documents;
  MCP chunk ids are the ids HTTP serves at `/v1/chunks/{id}`.
- `src/beacon/main.py` (`inspect`), `scripts/release_check.py`, `scripts/run_mutation_tests.py`,
  README, `docs/client-setup.md`: seven tools.
- `tests/test_serving_and_traversal.py` (new, 20 tests); the surface tests now expect seven tools.

## 2026-09-23 — near-zero authoring P2: project state from the code host

- `src/beacon/sources/forge.py` (new): opt-in GitHub source. Open milestones -> current focus and
  active work; issues labelled blocker/blocked and decision/needs-decision/rfc -> blockers and pending
  decisions; `good first issue` -> safe first tasks; releases (not drafts) -> recently completed.
  Bounded (one page per request, at most five items per field), read-only, token from
  `BEACON_FORGE_TOKEN`/`GITHUB_TOKEN` sent only as a header, titles the secret detector flags dropped,
  every item cites its URL. Rate limit, 401/403, 404 or an unreachable host stop it at once (no retry).
- `src/beacon/build/policy.py`: forge fills current focus, safe first tasks and each project-state
  group that `beacon.yaml` leaves empty; releases from the host are preferred over git tags.
- `src/beacon/build/requirements.py` + catalogue 1.1 (unreleased, updated in place): `forge` allowed
  for current focus, safe first tasks and project state.
- `src/beacon/main.py`: `beacon build --forge`; the report carries `forge` (ok with the fields it
  supplied, or the error code); a forge failure never fails the build.
- Label names are configurable in `beacon.yaml` (`forge.labels` for blockers, pending_decisions,
  safe_first_tasks; an empty list disables a group; omitted groups keep the defaults). Validated
  by the loader (known groups, at most 10 one-line labels of 50 characters), stripped from served
  output, and exempt from the requirements catalogue as build configuration (`BUILD_CONFIG_FIELDS`).
- Tests: `tests/test_forge_source.py` (new; HTTP always mocked). Docs: README.

## 2026-09-23 — near-zero authoring P1: markers, conventions, lazy loading

- `src/beacon/sources/conventions.py` (new): `<!-- beacon:<kind> -->` markers in README/AGENTS/
  CONTRIBUTING/SECURITY (purpose, non-goals, guardrail, concept, command, avoid), cited by line and
  digest-pinned; fallback conventions (guardrail-like sections as one cited entry each, other AGENTS.md
  sections as pointers, Non-goals, glossary, CODEOWNERS, mkdocs nav); frontmatter `status`/`role`
  (including Menhir `artifact_status`). Excerpts capped at 300 chars. Vendor files never read.
- `src/beacon/sources/declared.py`: carries `conventions`; marked commands win over CI; nav docs added.
- `src/beacon/build/policy.py`: marked purpose is the maintainers' words (not a placeholder); declared
  non-goals, guardrails (after intent, intent wins on id), concepts, review areas and expected behaviour
  fill what intent leaves empty; frontmatter refines non-intent docs; `marked_fields`/`convention_fields`.
- `src/beacon/build/requirements.py` + catalogue 1.1: `declared` allowed for non-goals, concepts,
  guardrails, review areas, expected behaviour.
- `src/beacon/main.py`: build and gaps report `conformance` (marked, by convention, inferred) with a
  hint that conforming docs give better results -- a note, never an error.
- `src/beacon/mcp/server.py`: connect-time instructions ask agents to load lazily (overview first,
  task_hint, pull on demand).
- Tests: `tests/test_conventions.py` (new). Docs: README, `.agent/data_models.md`.

## 2026-09-23 — near-zero authoring P0: declared sources, overlay init, citation digests

- `src/beacon/sources/declared.py` (new): the `declared` source reads the project's own files on every build --
  package manifest name/description/license, the LICENSE text matched to SPDX, CI install and test commands with
  file:line citations, the README lead paragraph, and entry docs (README, AGENTS, CONTRIBUTING, SECURITY, ...).
  Guesses (a build marker's conventional command, a license named only by filename) are labelled `inferred`.
  Agent-vendor files (`CLAUDE.md`, `.cursor/rules`) are never read.
- `src/beacon/build/policy.py`: precedence -- intent wins for judgment and declared fills the gaps; the checkout
  wins for the license (a contradicting intent license is drift `intent_contradicts_checkout`). Name falls back to
  the git origin, then the directory (`inferred`). Recent git tags become `project_state.recently_completed` when
  intent states none. An explicit intent `unknown` status yields to memory. `field_citations` records file:line.
- `src/beacon/build/requirements.py`: catalogue 1.1 with tiers `declared`, `inferred`, `forge` (planned);
  `docs/schemas/beacon-requirements-1.1.json` published (1.0 kept).
- `src/beacon/core/scaffold.py`: `beacon init` writes only the judgment fields, empty; discovered values stay in
  the init report and are never frozen into `beacon.yaml`.
- `src/beacon/core/citation_digest.py` (new), `schema.py`, `loader.py`, `validator.py`: `sources[].digest`
  pins cited text; validation warns `source_changed` / `source_unavailable`. `beacon digest PATH --lines A-B`
  prints a digest. Served snapshots drop digests (`served_manifest_payload`).
- `validator.py`, `cli_support.py`, `main.py`: `beacon validate --intent` checks a `beacon.yaml` overlay (name,
  description, docs and test command may be absent). `BeaconProjectInfo.status` defaults to `unknown`.
- `main.py`: `beacon build --repo` reads the declared source and reports citations in text and JSON output.
- Tests: `tests/test_declared_sources.py` (new); build, init and git-source tests updated for the new
  behaviour (repo-only builds now succeed from the README; refusal cases use a repo with no prose).
- Docs: README quick start and build sections, `docs/beacon-open-standard.md` (catalogue 1.1, settled decision
  on declared sources), `.agent/data_models.md`.
- `scripts/release_check.py`: the installed-wheel journey now runs init -> fill judgment fields in `beacon.yaml`
  -> `build` -> strict validate / inspect / export / serve on `beacon.generated.yaml`.

## 2026-09-22 — memory providers: find the project by repository

- `beacon build --memory URL` no longer requires `--memory-project`: without it Beacon asks the provider by
  this checkout's `origin` (`get_beacon_evidence(repository=...)`), so a provider that keeps its ids to itself
  (Menhir writes nothing into a checkout) still works. Needs `--repo` with a git origin, else
  `build_memory_conflict` before any request. The evidence is held to the same binding and freshness checks.
- `src/beacon/sources/memory_client.py`: `fetch_evidence(url, project_id="", *, repository="")` sends exactly one
  selector. `src/beacon/main.py`: the git tier is read before the provider call.
- `tests/test_memory_lookup.py`: lookup by origin, mismatched evidence still refused, provider refusal, no origin.

## 2026-09-22 — memory providers: show the provider's reason for a refusal

- `src/beacon/sources/memory_client.py`: a provider refusal (MCP error result) and a text that is not an
  evidence document are both `memory_invalid` with the provider's own reason, reduced to one printable line of at
  most 300 characters. Before, a refusal sent as plain text surfaced as "evidence document is not valid JSON".
- `tests/test_memory_provider.py`: both cases, including control characters and truncation.

## 2026-09-22 — docs: Beacon as an open standard

- `docs/beacon-open-standard.md` (new): Beacon as an MCP endpoint that answers agents live with citations (static,
  live and later LLM-synthesized answer modes); the gap next to AGENTS.md, llms.txt, doc servers and generated wikis;
  the standard's layers and schemas; roles; principles; proposed conformance and versioning; direct mode vs the
  optional Hub; evidence needed before claiming a standard; the S0-S7 track; open decisions.
- `docs/beacon-strategy-handoff.md`, `docs/beacon-functional-product-roadmap.md`, `.agent/architecture.md`,
  `README.md`: Menhir is one swappable memory provider behind the backend-neutral contract, not the beacon generator.
- `.agent/README.md`: router row for the standard doc.

## 2026-09-22 — memory providers: a backend-neutral contract, bound to the checkout

Menhir is now one memory provider among any others; nothing in Beacon depends on it.

- History tier renamed: `memory_*` record kinds, authority `memory` (was `menhir`), adapter
  `beacon.sources.memory` (`MemorySourceAdapter`). `beacon.sources.menhir` and the `KIND_MENHIR_*`
  names remain as deprecated aliases for one release.
- Evidence `beacon-memory-evidence-1.1` (`docs/schemas/`) adds a required `binding`: provider,
  provider project id, repository, indexed commit. The adapter enforces it rule for rule, and a
  test proves schema/adapter parity.
- `beacon build --memory URL --memory-project ID` fetches evidence from a provider over MCP (tool
  `get_beacon_evidence`); the credential comes from `BEACON_MEMORY_TOKEN` as a bearer header.
  `--memory-evidence FILE` reads an exported document (`--menhir-evidence` is a deprecated alias).
- Freshness: a publishing build refuses unless the checkout is the bound repository (identity
  compared as host + path, so ssh/https, `.git` and case do not matter) at the indexed commit,
  with uncommitted changes only in `beacon.yaml` and Beacon's own outputs and staging files.
  Checked before projection and again immediately before any output.
- Failures refuse before any write: `memory_unavailable`, `memory_unauthorized`, `memory_invalid`
  (was `menhir_evidence_invalid`; now also unbound 1.0 evidence on a publishing build),
  `memory_binding_mismatch`, `memory_stale`. No retry, cache or silent fallback. `--gaps-only`
  still reads 1.0 evidence.
- Bound evidence is identified by its binding only: a provider-side `project.root` is not
  compared (legacy 1.0 evidence keeps the root check). Repository identity keeps non-default
  ports. A remote provider without `BEACON_MEMORY_TOKEN` is `memory_unauthorized` before
  connecting.
- Tests: a fake provider (a real MCP server on loopback, no Menhir code) drives the same transport;
  one test per failure code; a commit during the build is caught at the last fence.
- Behaviour change: builds that published from 1.0 (Menhir) evidence now refuse. Menhir's pinned
  integration (`1cc3352b`) is unaffected until it implements the provider tool (plan Phase 3A).
- New direct dependencies `mcp>=1.30` and `httpx>=0.27` (both already installed via `fastmcp`).

## 2026-09-22 — build provenance recorded by policy; indexed docs not claimed current

- `resolve_project_facts` records which authority supplied every catalogued field
  (`MergedProjectFacts.field_authority`) where it chooses the value; the requirements report reads
  that instead of inferring a source from value presence.
- Documents that come only from memory evidence publish with `status: unknown`: being indexed is
  not a claim that a document is current. Intent-listed documents keep the maintainers' status.
- A published value that is only a placeholder -- Beacon's status default, `beacon init`'s
  `status: unknown`, or a description standing in for a purpose the maintainers never stated --
  is reported with `status: placeholder` and still counts as a gap, while keeping the source that
  supplied it. Provenance and completeness are separate.
- Not changed: a memory description still fills `purpose.one_sentence` (reported as a `memory`
  placeholder). Keeping it maintainer-only would need `purpose_missing` to become acknowledgeable
  for snapshot publication, which would loosen `beacon export` for everyone.

## 2026-09-22 — `beacon build` reads the project's own beacon.yaml; gap report

Each project owns its own beacon data; Beacon asks for it. Until now `beacon build` merged a
project's `beacon.yaml` only when a caller passed `--intent`, and the only caller (Menhir) never
did, so purpose, guardrails and commands never reached the build and generated manifests were
nearly empty.

- `beacon build --repo R` uses `R/beacon.yaml` as the intent authority. When it exists it is the
  only intent that build may use: `--intent` may name it or serve a repository without one, but
  a different file is refused (`intent_manifest_conflict`). There is deliberately no opt-out:
  ignoring the project's own manifest would publish a beacon without its guardrails.
- The own manifest refuses the build when malformed (`intent_manifest_invalid`), symlinked or not
  a regular file (`intent_manifest_unsafe`), or changed during the build
  (`intent_manifest_changed`: its sha256 is taken before parsing, re-checked after parsing,
  before the gap report is emitted, and immediately before any output -- stdout included, and
  after the snapshot is built for snapshot builds). Nothing is written on refusal.
- If replacing the manifest fails after the snapshot was written, the previous snapshot is
  restored (or the new one removed): `build_manifest_write_failed`. A process killed between the
  two renames can still leave them mismatched (pre-existing since the two-file build).
- Requirements catalogue (`src/beacon/build/requirements.py`, published as
  `docs/schemas/beacon-requirements-1.0.json`, kept identical by a test): every manifest field
  except the Beacon-owned `beacon_version`, the tiers allowed to supply it (`intent` / `git` /
  `memory` / `derived`), required or optional, and its gap code. Required codes are the build's
  refusal codes; codes shared with `beacon init` are init's.
- Build results carry `intent` (`path`, `source`), `requirements` (one row per field: `status`
  supplied / missing / default, `supplied_by` the tier that actually supplied it,
  `allowed_sources`) and `gaps`. Beacon's status default -- including an intent manifest that
  omits `project.status` -- and init placeholders (starter description, `status: unknown`)
  count as gaps. Conformance tests check every manifest field is
  catalogued and every supplied value came from an allowed tier.
- `beacon build --gaps-only` writes nothing and reports the same rows even when a required field
  is unresolved (`buildable: false`); a refused build points to it. Inconsistent inputs (root
  mismatch, intent citing a missing document) remain errors.
- `concepts` in the build result is now the published concept count (it omitted intent concepts).
  Canonical-doc authority names only sources whose documents survived.
- Behaviour change for callers that pass `--repo` without `--intent` into a repo that has a
  `beacon.yaml`: that file now takes intent authority (or refuses the build if malformed).
  Menhir's pinned integration (`1cc3352b`) is unaffected while the pin stays; its E2E-6 and E2E-8
  lanes plant a `beacon.yaml` and must be rewritten before that pin can move.

## 2026-09-21 — v0.3 build pipeline review fixes (PR #10)

- `beacon build` output safety — `--snapshot-out` is contained within the output root
  (`--repo`, or `--docs-root`) on the resolved path, refuses an existing file without
  `--force` (`build_snapshot_output_exists`), and with `--force` replaces only a recognizable
  Beacon snapshot (`build_snapshot_not_replaceable`); canonical-doc collisions resolve against
  the manifest's directory (the root the projection uses). `--force` on `--out` replaces only a
  recognizable Beacon manifest (`build_output_not_manifest`); the evidence input, the intent
  input, and any projected canonical document are never output targets
  (`build_output_protected`). The build is transactional: every gate (including the snapshot
  policy gate and the reader check) runs before any write, so a refused build leaves the
  previous manifest and snapshot untouched. `--out -` is unchanged.
- Menhir evidence — the adapter enforces `beacon-menhir-evidence-1.0.schema.json` rule for
  rule (unknown keys refused everywhere, `project.status` enum, `minLength`, `null` as a type
  error, `maxItems`) and `menhir_evidence_invalid` messages name the JSON pointer of the
  defect without values, paths, or exception text. `tests/fixtures/menhir/` carries a
  document in Menhir's real dump shape; `tests/test_menhir_evidence_contract.py` proves
  schema/adapter parity with `jsonschema`.
- Provenance — an absent evidence `project.status` is reported as authority `default`
  (Beacon's own fallback), never attributed to Menhir; `audiences` is published only from an
  intent manifest (`authorities.audiences` added to the build report). For an evidence-only
  build the manifest's `audiences` is now `[]` instead of the synthesized `[coding-agents]`.
- Intent authority — an `--intent` manifest's concepts, agent guidance, tagline, license,
  project_state, `project.description` and canonical-doc status are carried verbatim
  (a superseded doc is no longer republished as current).
- Decision concept ids never collide: non-ASCII titles get a stable content-derived id, the
  structure id is reserved, and remaining case-insensitive collisions get a stable `-2`, `-3`
  suffix in sorted order.
- `beacon serve` — explicit `-m` clears an inherited `BEACON_SNAPSHOT_PATH` (and `--snapshot`
  clears the manifest variables) for the run; `--snapshot` with `-m`/`--docs-root` is refused
  (`serve_source_conflict`); `serve --snapshot` exports the CLI `--max-*` ceilings to the
  server.

## 2026-09-18 — v0.3 build pipeline: `beacon build`, snapshot reader, Menhir evidence adapter, deterministic projection

- `beacon build` (new command) — the v0.3 pipeline entry point: collects the git tier
  (`GitSourceAdapter`, reused from `beacon init`), the Menhir tier (evidence document, below),
  and an optional hand-authored `--intent` manifest; merges them under the authority policy
  (intent = what should be true, git/files = what is true, Menhir = what was decided);
  projects the resolved facts deterministically into a manifest (no LLM); validates it through
  the one loader/validator pair; writes it atomically; and optionally emits the canonical
  snapshot through the unchanged v0.2 writer (`--snapshot-out`, byte-identical rebuilds).
  Known-absent intent (guardrails, test command) is recorded as acknowledged publication
  warnings with fixed reasons — never synthesized. Divergence (an indexed doc or decision
  location missing on disk) becomes a reported drift record and the claim is omitted;
  unresolvable required fields fail closed with stable `build_*` codes.
- `src/beacon/build/` (new package) — `policy.py` (authority resolution, drift, fail-closed
  rules), `project.py` (deterministic projection + byte-stable YAML rendering with optional
  provenance comment), `snapshot.py` (the snapshot reader: loads and structurally verifies
  canonical snapshot v1.0 artifacts, refuses foreign versions and snapshots carrying errors).
- `src/beacon/sources/menhir.py` (new) — `MenhirSourceAdapter` consumes the versioned Menhir
  evidence document (`docs/schemas/beacon-menhir-evidence-1.0.schema.json`): identity,
  structure, documents, files, and optional decisions/lifecycle as normalized records citing
  the scan fingerprint. Bounded, deterministic, fail-closed on any defect; Menhir is never
  imported (process/env boundary stays intact) and the built artifact never needs it again.
- Snapshot-only serving — `beacon serve --snapshot` (and `BEACON_SNAPSHOT_PATH`) runs the MCP
  stdio server from a canonical snapshot with zero source-file reads;
  `ManifestBeaconProvider.from_snapshot` parses the embedded manifest through the one loader
  and rebuilds the doc index from embedded chunks; `DocIndex.from_snapshot_documents` is the
  snapshot-fed index constructor. Snapshot-served answers are verified identical to
  manifest-served answers, with one documented exception: the v0.2 writer embeds no
  plan-role document body (title-only by policy), so a snapshot-served search cannot hit
  plan text that a manifest-served search finds (pinned by
  `test_snapshot_served_plan_docs_are_title_only_by_policy`). The loader accepts explicit `null` line fields (the snapshot's
  embedded asdict form); mappings stay strict and the provider adapts the embedded form.
- `beacon-cli-result` envelope: the `build` command joins the fixed command set (schema enum
  widened in place — additive; existing envelopes stay valid).
- The deterministic projection + Menhir adapter are the MVP path that lets Menhir delete its
  bespoke manifest-mapping bridge (planned gate recorded in the v0.3 plan: no LLM drafting
  before this passes Menhir MVP E2E-6).

## 2026-09-17 — GitSourceAdapter: first v0.3 repository-source slice

- `src/beacon/sources/` (new package) — `NormalizedRecord`/`SourceAdapter` boundary and
  `GitSourceAdapter`: deterministic, bounded, local-only git evidence (HEAD state, inventory
  summary, tags, recent commits, per-file history with renames/introduction/removal, bounded
  co-change pairs, activity by top-level directory). Fixed argv commands with no shell, hard
  output caps, `--no-optional-locks` (never writes the repo), `GIT_TERMINAL_PROMPT=0`, commit
  digests as provenance, and sensitive-path exclusion before anything path-bearing is emitted.
- `beacon init` now consumes the adapter: the sanitized origin URL comes from `git remote
  get-url origin` (the pure `.git/config` read remains the fallback when git is unavailable),
  and the init report gains the additive, optional `git_evidence` section. Git supplies
  reality/history only — no intent-bearing manifest field is derived from git statistics.
- `docs/schemas/beacon-init-report-1.1.schema.json` (new) — additive schema evolution from 1.0:
  same shape plus optional `git_evidence`; emitted reports declare version `1.1`. The 1.0
  schema and its golden fixtures remain valid compatibility fixtures.
- Tests: `tests/test_git_source.py` (36 tests over real fixture repositories: determinism,
  provenance, caps/truncation honesty, rename direction, sensitive exclusion, no repo mutation,
  init integration, SHA-256 repository support, annotated-tag peeling, subject-secret
  redaction, plus the review-fix regressions below) and 3 schema tests in
  `tests/test_init_core.py`; 39 new tests (40 test items: one is parametrized). Full suite:
  735 passed, 8 skipped (base branch: 695 passed, 8 skipped); ruff check, ruff format,
  mypy and bandit clean against framework 0.3.0. Review fixes: git object ids are accepted in
  both SHA-1 (40) and SHA-256 (64) hex, mirroring the v0.2 verified-status policy; annotated
  tags are peeled to their target commit before any digest is cited; commit subjects pass
  Beacon's high-confidence secret detector and unsafe ones are redacted instead of reproduced.
- PR #9 review fixes (safety contract now enforced by code and tests): a wall-clock deadline
  covers the whole git command and kills the process tree (`taskkill /T` on Windows, session
  group on POSIX); inherited `GIT_*` variables are stripped (allowlist: `GIT_EXEC_PATH`);
  `GIT_NO_LAZY_FETCH=1` plus `-c protocol.allow=never`, and partial clones are walked with
  `--no-renames` (marked truncated); repository config cannot run programs (`core.fsmonitor`,
  `core.hooksPath`, `log.showSignature` overridden, repository-scoped filter drivers emptied
  for `status`); the walk uses NUL-only positional framing so no subject can break it; a byte
  cap drops the partial trailing record instead of inventing a path; shallow clones are marked
  truncated and boundary additions are never claimed as introductions; the full subject and
  every branch/tag name are secret-scanned before any cut; tags on non-commit objects are
  omitted (report always validates against 1.1); init keeps the adapter's credential-URL
  findings (linked worktrees); the "adapter URL beats config" test uses a linked worktree so
  the two sources genuinely differ.
- Branch `v03/git-source-adapter`, stacked on `release/v0.2.0`; the v0.2 release branch and
  PR #4 are unchanged. `beacon build` will consume these same records in the merge-policy step.

## 2026-08-10 — Verified project-status companion

- Added optional source-cited `project_state` declarations with exactly zero or one active work item,
  bounded recent-completion/blocker/decision lists, strict typing, path safety, and publication
  warnings for unsourced state.
- Added immutable `GET|HEAD /v1/status` with snapshot lineage, startup Git commit/branch/dirty
  evidence, per-source freshness comparisons, observation time, ETag/304 support, and an explicit
  unsigned self-reported trust statement.
- Upgraded discovery to descriptor 1.5 with exact status bytes and digest while preserving manifest
  0.1, snapshot 1.0, the five MCP tools, loopback-only operation, and no outbound network.
- Made `project_state` maintenance part of task closeout and recorded the remaining orientation,
  automation, refresh, and signed-trust work in the product roadmap.

## 2026-08-10 — Targeted static concept and guardrail retrieval

- Added versioned concept and guardrail companion indexes plus individually addressable immutable
  resources, preserving complete citations and implementation/applicability metadata.
- Upgraded discovery to descriptor 1.4 with exact counts, bytes, digests, and URL templates for all
  three companion catalogs while leaving snapshot 1.0 and the five MCP tools unchanged.
- Added opaque stable resource IDs so arbitrary manifest IDs never become route structure, with
  schema, hostile-input, cache, dogfood, and installed-wheel journey coverage.
- Tightened full-record and snapshot-lineage validation, rejected lone Unicode surrogates through
  the canonical JSON error contract, and schema-validated installed companion responses.

## 2026-08-10 — Selective static chunk retrieval

- Added versioned `/v1/chunks` and `/v1/chunks/{id}` companion contracts without changing snapshot
  1.0, with published Draft 2020-12 JSON Schemas for both response shapes.
- Added stable location-derived chunk IDs, inlined parent role/status, exact UTF-8 text and canonical
  response byte costs, response SHA-256, snapshot lineage, and individual ETag/HEAD/304 support.
- Upgraded discovery to descriptor 1.3 with chunk capability and index count/URL/size/digest, while
  retaining identity/orientation/full representations and all existing loopback/security boundaries.
- Extended source, hostile-input, dogfood, schema, and installed-wheel journey coverage.

## 2026-08-10 — Minimal HTTP identity tier

- Added immutable `GET`/`HEAD /v1/snapshot/identity` with project, purpose, audiences, and current
  focus, no document inventory, and snapshot-1.0-compatible metadata-only shape.
- Upgraded discovery to descriptor 1.2 with identity/orientation/full routes, exact byte sizes, and
  independent SHA-256 digests; identity links progressively to orientation.
- Added derivation, schema, route/header/cache, hostile-input, dogfood size, and installed-wheel
  journey coverage, and documented identity as the cheapest project-orientation read.

## 2026-08-10 — Agent-first HTTP orientation tier

- Added immutable `GET`/`HEAD /v1/snapshot/orientation`, derived in memory from the approved full
  startup snapshot without rereading repository files.
- Upgraded discovery to descriptor 1.1 and advertised orientation/full routes, modes, schema
  versions, independent SHA-256 digests, and exact byte sizes while retaining the legacy `snapshot`
  discovery entry.
- Reused full-route ETag, conditional request, loopback, CORS, error-redaction, publication, resource,
  and secret boundaries for the orientation representation without changing `/v1/snapshot` or its
  `/beacon.json` alias.
- Added snapshot derivation, route/header/cache, no-body, source-identity, dogfood provenance, and
  material-size-reduction tests plus agent-first client documentation.

## 2026-08-10 — Agent-first tiered consumption and dogfood provenance

- Measured the existing metadata-only export against the full HTTP snapshot and recorded tiered
  discovery, orientation/index, and full-snapshot consumption as the v0.3 direction.
- Added roadmap requirements for representation byte budgets, per-chunk UTF-8 sizes, provenance
  completeness, and metadata-first task evaluation without silently changing snapshot 1.0.
- Defined the tiers as a linked progressive-disclosure chain—discovery, orientation/index, then
  full—using semantic contract names instead of ambiguous size labels.
- Added source citations and implementation locations for all five dogfood concepts, source
  citations for all four dogfood guardrails, and a CI gate that verifies those references resolve.
- Selected `/v1/snapshot/orientation` for the medium-cost representation while preserving
  `/v1/snapshot` as the backward-compatible full representation; the companion-index-versus-schema
  decision remains open.

## 2026-08-10 — Automated Beacon freshness contract roadmap

- Added a mandatory automated task-closeout disposition: `updated`, `not_affected`, or
  `needs_review`.
- Routed deterministic source/document synchronization checks before conditional LLM semantic
  review, with canonical writes requiring cited evidence and authority-sensitive changes requiring
  explicit review.
- Added v0.3 deliverables, CI fixtures, wrapup receipts, and an immediate planning package for
  diff classification, freshness verification, restart evidence, and fail-closed enforcement.

## 2026-08-10 — RC2 loopback HTTP snapshot

- Added `beacon serve-http`, restricted to `127.0.0.1`, with immutable startup snapshot bytes,
  well-known discovery, versioned snapshot and convenience routes, and redacted health.
- Added SHA-256 ETag/conditional requests, deterministic Beacon error envelopes, GET/HEAD-only
  routing, no CORS, no access logs, and suppressed server/date headers.
- Reused export's publication, path, resource, and secret gates before binding; non-loopback,
  invalid, and occupied bind targets fail closed with stable redacted diagnostics.
- Added direct Starlette/Uvicorn dependencies and a real installed-process HTTP release journey
  under outbound-socket denial.
- Reduced snapshot size and internal-plan exposure by emitting `plan` and `*_plan` documents as
  title/path/role/status/hash metadata only; the private local MCP index still reads their bodies.
- Recorded the first HTTP-only orientation trial: the snapshot successfully oriented a fresh
  consumer but required ad-hoc local ranking and exposed two documentation-currency defects, now
  corrected in the architecture/version and README configuration tables.
- Bumped the release candidate to `0.2.0rc2`; RC1 remains immutable.

## 2026-08-10 — Future AI answer-broker boundary

- Recorded the optional AI answer broker as a future layer over canonical Beacon knowledge, with
  Beacon-shaped responses, strict schema/citation validation, provenance, bounded capabilities,
  secret filtering, and fail-closed unanswered/refused/error behavior.

## 2026-08-10 — Public release candidate

- Published `archolith-beacon==0.2.0rc1` through PyPI trusted publishing after the public
  `archolith-mcp-framework==0.2.0` dependency was available and verified.
- Added checksummed wheel and source artifacts to the `v0.2.0rc1` GitHub prerelease.
- Made GitHub release creation repository-explicit so the no-checkout release job works in future
  tag workflows.
- Added an observer scorecard for the remaining genuinely unaided 15-minute developer trial.

## 2026-08-10 — Release-candidate publication docs

- Updated installation and client setup guidance for the public `archolith-mcp-framework==0.2.0`
  dependency and pinned `archolith-beacon==0.2.0rc1` release candidate.
- Narrowed the remaining v0.2 gate to the genuinely unaided developer trial.

## 2026-08-10 — Cross-platform init symlink refusal

- Fixed `beacon init` to preserve an existing final-target symlink long enough for the overwrite
  classifier to return the documented refusal report instead of raising during path containment.
- Kept direct output-path resolution strict for final symlinks that escape the repository, and added
  regression coverage for that boundary.

## 2026-08-10 — Negative-control mutation gate

- Added a deterministic mutation runner covering known-token detection, strict-warning
  enforcement, manifest export collision protection, and exact-five MCP tool registration.
- Each mutant runs against a temporary package copy and is accepted only when its focused pytest
  test exits with `TESTS_FAILED`; collection and infrastructure failures cannot count as kills.
- Added contract tests for the runner and wired the four-mutant gate into the CI quality job.

## 2026-08-10 — WP4 examples and documentation

- Added three maintained, self-contained example repositories under `examples/` — `library` (a small
  Python package), `service` (a long-running background service), and `monorepo-research` (a
  research/analysis monorepo). Each ships a `beacon_version: "0.1"` manifest, real referenced
  canonical docs, meaningful concepts/guardrails/build-and-test metadata, and validates with zero
  errors and a clean publication policy.
- Added `examples/README.md` as the examples index, with per-shape guidance and maintenance notes.
- Added `tests/test_examples.py`: an example-matrix test that enumerates exactly the maintained set,
  validates each with the public core APIs, executes all five provider methods, and builds and
  schema-validates both embedded and metadata-only snapshots against the snapshot v1.0 schema. It
  exercises the shipped v0.2 behavior without coupling to the CLI wrapper.
- Added `docs/client-setup.md`: an install-first, copy-paste client setup guide covering the v0.2
  product loop, static/offline behavior, MCP client configuration for Claude/Cursor/Codex/Gemini/
  OpenCode and generic stdio, an examples index, the manifest-0.1 / product-0.2 / snapshot-1.0
  version model, and honest limitations.
- Updated `README.md` (product-loop quick start, an Examples section, a Versions section,
  static/offline statement, and a release-state Status) and `docs/demo-transcript.md`
  (Running-this-yourself now uses the explicit `beacon serve --manifest` form and the v0.2 loop).

## 2026-08-09 — Release-readiness audit and trust-boundary hardening

- Added one canonical-document path resolver used by validation and indexing. Absolute POSIX,
  Windows-drive, and UNC paths, parent traversal, resolution failures, and symlink escapes are
  rejected with the stable non-secret `unsafe_canonical_path` code before any document is read.
- Made manifest parsing type-strict: explicit `null`, non-string text/list members, booleans or
  non-positive source line numbers, and inverted line ranges now raise `ManifestError` rather than
  being coerced or leaking raw conversion errors. Project, document, concept, and nested source
  statuses use the same controlled vocabulary.
- Forced FastMCP update checks and the server banner off after dotenv loading and before framework
  import. Unexpected MCP tool failures now return a generic `internal_error`; stable resource-limit
  refusals remain visible without exposing private exception text.
- Added a real stdio MCP regression test that lists and calls all five tools under an outbound-socket
  guard, plus path, parsing, provider-default, privacy-order, Windows-stdio, and error-redaction tests.
- Expanded CI to the full Linux/macOS/Windows × Python 3.12/3.13/3.14 matrix and added lint,
  formatting, type, Bandit, dependency, and wheel-content gates. The audited wheel passed the full
  tests on Python 3.12, 3.13, and 3.14.

## 2026-08-09 — Public GitHub project infrastructure

- Added SHA-pinned cross-platform CI for Python 3.12–3.14, package validation, installed-wheel
  smoke testing, and retained build artifacts.
- Added a tag-gated, environment-protected PyPI trusted-publishing workflow that verifies the
  tag/version pair and release artifact before publishing or creating a GitHub release.
- Added Dependabot, CODEOWNERS, pull-request and issue templates, contribution guidance, and a
  security policy. The release workflow intentionally requires the Archolith MCP framework to be
  available from a public package index before publication can succeed.
- The GitHub repository is public with squash-only merging, automatic branch deletion, security
  alerts/fixes, private vulnerability reporting, and protected `master`. Required CI status checks
  will be attached after the workflows have run once and stable check names exist.

## 2026-08-09 — Stable validation codes and strict/acknowledgement policy

- `src/beacon/core/validator.py` — `ValidationIssue` now carries a stable, non-secret
  diagnostic `code` in addition to the legacy `severity`/`where`/`message` fields (additive;
  existing consumers unchanged). Added the addendum §5 publication-warning codes
  (`project_status_unknown`, `purpose_missing`, `test_command_missing`, `guardrails_missing`,
  `concept_definition_missing`, `related_concept_unknown`, `knowledge_status_invalid`,
  `canonical_doc_duplicate`), new absent-test/absent-guardrail findings, stable codes for all
  other error/warning findings, and the `PUBLICATION_WARNING_CODES` / `VALIDATION_CODES` sets.
- `src/beacon/core/policy.py` (new) — reusable serving/publication policy: `evaluate_policy()`
  returns `PolicyEvaluation` distinguishing `servable` (no errors) from `publishable` (no errors
  and no unresolved publication warnings). Added explicit acknowledgement parsing/model:
  `parse_acknowledgement()` / `parse_acknowledgements()` validate `CODE=REASON` (reason trimmed,
  non-empty, ≥10 chars) and reject malformed/unknown/duplicate/unallowlisted codes with stable
  `AcknowledgementError` codes. Only `test_command_missing` and `guardrails_missing` are
  acknowledgeable in v0.2; acknowledgements change policy disposition but preserve diagnostic
  severity/facts and never mutate `beacon.yaml`.
- `src/beacon/core/__init__.py` — re-exported the policy types/functions.
- `tests/test_policy.py` (new) — 29 focused tests covering every acknowledgement rejection path,
  direct-object revalidation, normal/strict/publish/export dispositions, preserved facts/severity,
  deterministic ordering, and legacy positional-constructor compatibility.
- `.agent/architecture.md`, `.agent/data_models.md` — documented the stable diagnostic codes,
  serving/publication policy, and acknowledgement model.
- The full CLI JSON envelope and `--strict-warnings` / `--acknowledge` flags are a later merge
  unit; this slice provides the reusable core APIs only.

## 2026-08-09 — Shared resource-limits model and bounded readers

- `src/beacon/core/limits.py` — added the frozen immutable `ResourceLimits` model with the
  addendum's exact standard defaults: six overridable ceilings
  (`manifest_bytes`/`documents`/`document_bytes`/`total_document_bytes`/`chunks`/`snapshot_bytes`)
  and seven fixed ceilings (`yaml_depth`/`yaml_nodes`/`yaml_aliases`/`path_bytes`/
  `query_bytes`/`result_limit`/`init_report_bytes`). Added stable non-secret diagnostic codes,
  `LimitError`, and
  `resource_limits_from_env()` + `apply_overrides()` for `CLI > environment > default`
  precedence. Invalid override values (negative, non-integer, overflow) are rejected with
  `limit_invalid_value` rather than truncated.
- `src/beacon/core/loader.py` — `load_beacon_manifest` now checks manifest source bytes
  *before* decoding (raises `limit_manifest_bytes`) and parses through a bounded
  `yaml.SafeLoader` subclass that refuses excessive YAML depth, node, and alias counts.
- `src/beacon/core/doc_index.py` — `DocIndex.from_docs` now enforces canonical-document
  count, per-document bytes, aggregate document bytes, relative-path UTF-8 bytes, and total
  heading-chunk count, raising the corresponding stable limit codes.
- `src/beacon/provider/manifest_provider.py` — the provider now carries a `limits` profile and
  enforces query/task-hint/concept UTF-8 bytes (`limit_query_bytes`) and the search
  result-limit ceiling (`limit_result_limit`).
- `src/beacon/config/settings.py` — `BeaconSettings` now exposes a frozen `limits` profile
  populated from `BEACON_MAX_*` environment variables at startup.
- `tests/test_limits.py` — added focused positive/negative tests covering every enforced
  boundary, pre-decode byte refusal, precedence, invalid overrides, aggregate accounting,
  no-leaked-content, and valid-input compatibility.
- `.agent/architecture.md`, `.agent/data_models.md` — documented the resource-limits model,
  bounded readers, and the six new `BEACON_MAX_*` environment variables.

## 2026-08-09 — Begin v0.2 release-package migration

- `pyproject.toml`, `src/beacon/__init__.py` — changed the distribution to `archolith-beacon`,
  single-sourced release-candidate version `0.2.0rc1`, declared CPython 3.12–3.14 support, completed
  package metadata, and migrated the runtime dependency to `archolith-mcp-framework>=0.2,<0.3`.
- `src/beacon/main.py`, `src/beacon/mcp/server.py` — migrated to the
  `archolith_mcp_framework` import and added eager `beacon --version` without changing no-argument
  stdio startup or the five-tool surface.
- `tests/test_cli.py`, `tests/test_packaging.py` — added version and package-contract coverage.
- `.gitignore`, `.githooks/pre-push`, `README.md`, `.agent/architecture.md` — added repository
  hygiene, corrected branch guidance, and documented truthful source installation while both
  public PyPI distributions remain gated.

## 2026-08-09 — Lock v0.2 implementation readiness contracts

- `.agent/plans/beacon-v0.2-implementation-readiness-addendum-2026-08-09.md` — locked stable
  FastMCP 3.x/stdio for v0.2, conservative configurable repository limits, explicit
  absent-test/guardrail acknowledgements, high-confidence secret blocking/overrides, an
  offline/telemetry-free runtime promise, public release order, and PyPI-access verification.
- `docs/schemas/beacon-*-1.0.schema.json` — added Draft 2020-12 machine contracts for the shared
  CLI envelope, initialization report, and canonical static snapshot.
- `.agent/plans/beacon-v0.2-publishable-static-product-plan-2026-08-09.md`,
  `docs/beacon-functional-product-roadmap.md`, `.agent/README.md`, `beacon.yaml` — linked and indexed
  the readiness addendum as normative v0.2 implementation guidance.

## 2026-08-09 — Define the Archolith Hub and federated trust product

- `.agent/plans/beacon-trust-hub-and-federation-plan-2026-08-09.md` — locked the approved hybrid
  product shape: Archolith as the default directory, trust service, and optional public/private
  host; conforming direct/self-hosted operation; a local trust broker and stateless signed preflight;
  portable identity, descriptors, trust receipts, OAuth scopes, custody disclosures, question
  review, threat gates, and phased v0.3/v0.5/v0.8/v1 delivery.
- `docs/beacon-functional-product-roadmap.md`, `.agent/README.md`, `beacon.yaml` — integrated and
  indexed the Hub/federation plan across users, v1 boundaries, architecture, milestones,
  evaluation, immediate planning, and open security/operations decisions.

## 2026-08-09 — Plan the v0.2 publishable static product

- `.agent/plans/beacon-v0.2-publishable-static-product-plan-2026-08-09.md` — converted the
  roadmap's v0.2 release into an executable product plan. Audited the current baseline, locked the
  static/offline compatibility boundaries, specified init/validate/inspect/export/serve contracts,
  split implementation into six work packages, and defined safety, packaging, deterministic export,
  cold-start usability, and wheel-based release gates.
- `docs/beacon-functional-product-roadmap.md`, `.agent/README.md`, `beacon.yaml` — linked and indexed
  the v0.2 plan as the active implementation plan.
- Approved all seven v0.2 release decisions: `archolith-beacon` ownership, the CPython/platform
  matrix, structured initialization review reports, snapshot schema/content policy, shared CLI JSON
  envelope and exit codes, bounded `--force`, and protected-`master` release/tag workflow. Added a
  future durable unanswered-question review queue to the v0.3 roadmap.
- Clarified the approved public dependency chain after the MCP framework's Archolith migration:
  publish `archolith-mcp-framework==0.2.0`, migrate Beacon from the legacy dependency/import to
  `archolith-mcp-framework>=0.2,<0.3` / `archolith_mcp_framework`, and only then publish
  `archolith-beacon`, with no direct Git dependency in public package metadata.

## 2026-08-09 — Define the functional Beacon product roadmap

- `docs/beacon-functional-product-roadmap.md` — added the canonical roadmap from the shipped static
  v0 through publishable static, repository-aware, dynamic/temporal, operable remote, and stable v1
  releases. Defined users, product workflows, architecture, trust gates, project-task evaluation,
  Menhir/full-500 boundaries, workstreams, and open decisions.
- `docs/beacon-mcp-roadmap.md` — narrowed to the interface-level history/backlog and linked the
  canonical product roadmap so the two documents do not compete.
- `README.md`, `beacon.yaml` — made the product roadmap discoverable to people and through Beacon's
  own canonical document index.

## 2026-08-07 — Doc sweep: fix stale CLI description, fill in code conventions

- `.agent/architecture.md` — Package Layout's `main.py` row still described the pre-CLI
  `configure_logging + run_server` shape; updated to reflect the typer app (`serve` default
  + `validate`/`inspect` subcommands) added 2026-06-30. Added a `## CLI` section documenting
  all three commands — this surface had no `.agent/` coverage at all before now.
- `.agent/workflows/code_conventions.md` — was four empty TODO headers; filled in with
  conventions actually observed in `src/beacon/` (frozen-dataclass-only data types, `Beacon`-
  prefixed manifest types vs. unprefixed answer types, one-test-file-per-layer, no
  linter/formatter configured yet).
- `.agent/data_models.md`, root `README.md` — checked against `schema.py`/`main.py`; both
  accurate, no changes.

## 2026-06-30 — CLI subcommands, self-referential manifest, demo transcript

- `src/beacon/main.py` — restructured with typer; `beacon validate` and `beacon inspect` subcommands added. `beacon` with no args still starts MCP stdio server. Windows UTF-8 output fix.
- `beacon.yaml` — rewritten to describe the beacon project itself (was describing menhir, referencing docs that don't exist here). Self-referential manifest makes `validate`/`inspect` work out of the box.
- `tests/test_cli.py` — 19 offline tests for both CLI subcommands.
- `README.md` — public-facing README added; MIT LICENSE added. Stale CLI status note removed after commands shipped.
- `docs/demo-transcript.md` — four-query agent session transcript using real provider output. Covers project_overview, explain_concept, agent_onboarding (task-scoped), and guardrails.

## 2026-06-29 — Beacon v0 initial implementation

- `src/beacon/core/schema.py` — BeaconManifest + all answer-contract frozen dataclasses
- `src/beacon/core/loader.py` — YAML loader with structural validation
- `src/beacon/core/validator.py` — semantic validator (dup ids, dangling paths, missing fields)
- `src/beacon/core/doc_index.py` — heading-chunked doc index with keyword search
- `src/beacon/provider/base.py` — BeaconProvider Protocol (5 methods)
- `src/beacon/provider/manifest_provider.py` — ManifestBeaconProvider v0 impl
- `src/beacon/mcp/` — cth_mcp_framework gateway server, 5 readonly tools
- `beacon.yaml` — demo manifest describing menhir (corrected to reality)
- `tests/` — 35 offline tests covering all layers
- `.agent/architecture.md` + `.agent/data_models.md` — filled in with real content
- Registered in `cth.agentsmith/mcp-registry.json`; `sync.py generate` run
