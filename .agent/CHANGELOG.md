# Changelog — beacon

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
- Tests: `tests/test_git_source.py` (20 tests over real fixture repositories: determinism,
  provenance, caps/truncation honesty, rename direction, sensitive exclusion, no repo mutation,
  init integration). Full suite: 718 passed, 8 skipped; ruff clean against framework 0.3.0.
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
