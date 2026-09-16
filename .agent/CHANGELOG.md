# Changelog — beacon

## 2026-09-15 — Merge the v0.2 plan and its readiness addendum

- `.agent/plans/beacon-v0.2-plan-2026-09-15.md` — new single v0.2 plan. Three lists of decisions
  became one (`D1`-`D24`); two merge orders became one 14-unit order; the addendum's "normative where
  more specific" precedence rule is gone.
- Reconciliation fixed a real dependency defect and two duplications: the shared CLI envelope now
  lands before `beacon init` (whose report serializes through it), limits and diagnostic codes land
  before any reader, and high-confidence secret detection is one shared module instead of separate
  implementations inside `init` and `export`.
- Resolved the snapshot-writer overlap with the build-pipeline plan: v0.2 WP4 owns the digests and
  canonical writer (`beacon export`), the build-pipeline plan owns the reader and `beacon build`.
- `.agent/plans/archive/` — archived the 2026-08-09 product plan and readiness addendum with
  supersession banners.
- `docs/beacon-functional-product-roadmap.md`, `.agent/README.md`,
  `.agent/plans/beacon-multi-intent-beacons-plan-2026-09-15.md`,
  `.agent/plans/beacon-build-pipeline-and-source-adapters-plan-2026-09-15.md` — repointed references.
  Also corrected the multi-intent plan's citation of `no_manifest_schema_change`, which is a guardrail
  in `beacon.yaml`, not in the addendum.

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
