# Changelog — beacon

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
