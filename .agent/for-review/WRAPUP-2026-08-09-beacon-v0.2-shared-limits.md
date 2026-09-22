# WRAPUP REVIEWED — Beacon v0.2 shared resource-limits model and bounded readers

- **Agent:** opencode
- **Model:** archolith/deepseek-v4-flash
- **Date:** 2026-08-09
- **Status:** REVIEWED — APPROVED WITH REMEDIATION
- **Plan / ticket:** Merge-order unit 2 — "Shared limits model and bounded manifest/document readers"
  (`.agent/plans/beacon-v0.2-publishable-static-product-plan-2026-08-09.md`, §11;
  `.agent/plans/beacon-v0.2-implementation-readiness-addendum-2026-08-09.md`, §10 step 2, §4 Resource limits)
- **Worktree / branch:** `beacon-v0.2-wp0` / `release/v0.2.0`
- **Base commit:** `38f640f`
- **Commits:** `7b3998c` (`feat: enforce Beacon resource limits`)
- **Verification scope:** Executor verification plus independent Codex review, remediation, and
  acceptance testing against the worktree source and a real stdio subprocess.
- **Docs updated:** `.agent/architecture.md`, `.agent/data_models.md`, `.agent/CHANGELOG.md`
- **Changelog updated:** Yes (new entry at top of `.agent/CHANGELOG.md`)

## Summary

Implemented the bounded Beacon v0.2 merge-order slice: a frozen/immutable shared resource-limits
model and bounded manifest/document readers. Added `beacon.core.limits.ResourceLimits` carrying the
addendum's exact standard defaults (six overridable ceilings plus seven fixed ceilings), stable
non-secret diagnostic `LimitError` codes, and reusable `CLI > environment > default` precedence via
`resource_limits_from_env()` and `ResourceLimits.apply_overrides()`. Invalid override values
(negative, non-integer, overflow) are rejected with `limit_invalid_value` rather than silently
truncated. Enforced manifest source bytes before decode, YAML depth/node/alias caps, canonical-doc
count, per-doc bytes, aggregate doc bytes, path UTF-8 bytes, chunk count, query/task-hint UTF-8
bytes, and the search result-limit ceiling at the earliest existing boundaries. Manifest and
document readers allocate no more than the active ceiling plus one sentinel byte. Valid inputs and
manifest 0.1 compatibility are preserved; init/export and the full CLI JSON envelope were not
introduced in this slice.

## Files changed

1. `src/beacon/core/limits.py` (new) — frozen `ResourceLimits` dataclass with the addendum's exact
   defaults, including the 5 MiB initialization-report ceiling; stable limit codes; `LimitError`;
   `resource_limits_from_env()` and
   `ResourceLimits.apply_overrides()`; `_validate_int()` rejecting negative/overflow/non-integer
   overrides.
2. `src/beacon/core/loader.py` — `load_beacon_manifest(path, *, limits=None)` now reads bytes,
   performs a bounded source read before decoding, decodes UTF-8, checks document count/path
   length before validator filesystem work, and parses through a bounded
   `_BoundedSafeLoader` that raises `limit_yaml_depth`/`limit_yaml_nodes`/`limit_yaml_aliases`.
3. `src/beacon/core/doc_index.py` — `DocIndex.from_docs(..., limits=None)` enforces
   `documents`, `path_bytes`, `document_bytes`, `total_document_bytes`, and `chunks` ceilings.
4. `src/beacon/provider/manifest_provider.py` — provider gains a `limits` field (default
   `ResourceLimits`); `from_paths`/`from_settings` thread it into loader + doc index; `search`,
   `agent_onboarding`, `explain_concept`, and `guardrails` enforce query/task-hint/concept UTF-8
   bytes (`limit_query_bytes`) and the result-limit ceiling (`limit_result_limit`).
5. `src/beacon/config/settings.py` — `BeaconSettings` exposes a frozen `limits` field populated
   from `BEACON_MAX_*` environment variables via `resource_limits_from_env()`.
6. `src/beacon/mcp/lifecycle.py` — threads settings limits into the provider and reports all
   effective non-secret ceilings to stderr at startup.
7. `tests/test_limits.py` (new) — 32 focused positive/negative tests covering every enforced
   boundary, pre-decode byte refusal, precedence, invalid overrides, aggregate accounting,
   no-leaked-content, and valid-input compatibility.
8. `.agent/architecture.md` — documented the six new `BEACON_MAX_*` env vars, the limits model, and
   the bounded readers.
9. `.agent/data_models.md` — added a Resource Limits section.
10. `.agent/CHANGELOG.md` — added a top entry for this slice.
11. `.agent/for-review/WRAPUP-2026-08-09-beacon-v0.2-shared-limits.md` (new) — this document.

## Verification commands / results

All runs used `PYTHONPATH=<worktree>/src` so the worktree package (version `0.2.0rc1`) is imported
rather than a stray 0.1.0 checkout. Note the ambient environment resolves `import beacon` to a
different 0.1.0 project unless the worktree `src` is explicitly on the path; that pre-existing
environment quirk is disclosed here and was worked around by setting `PYTHONPATH`.

- Executor full suite before review — **PASS**: `109 passed`.
- Independent `python -m pytest -p no:cacheprovider -q` — **PASS**: `115 passed in 0.50s`.
- Independent focused `tests/test_limits.py` — **PASS**: `32 passed in 0.14s`.
- `python -m beacon validate beacon.yaml` (worktree src on path) — **PASS**: `✓ Valid — 0 errors,
  0 warnings`, exit 0.
- `python -m beacon inspect beacon.yaml` (worktree src on path) — **PASS**: `✓ Inspect complete.
  5 tools responded.`
- Draft 2020-12 `check_schema` — **PASS** for all three executable Beacon schemas.
- Real FastMCP stdio subprocess with framework tag source and `BEACON_MAX_DOCUMENTS=17` —
  **PASS**: override reported on stderr and all five Beacon tools returned valid JSON.
- `python -m compileall -q src tests` and `git diff --check` — **PASS**.
- Baseline (worktree src on path, before changes) — **PASS**: `83 passed`.
- NOTE: without `PYTHONPATH=<worktree>/src`, the pre-existing suite resolves `beacon` to a 0.1.0
  checkout elsewhere and reports 4 version-related failures; this is an environment/import-path
  quirk independent of this slice, not a regression.

## Claim cross-check

- Summary matches diff: **yes** — every listed change corresponds to an edit above.
- Files-changed list matches edits: **yes** — all named files touched; no plan files edited.
- Commit list matches: **yes** — implementation is anchored to `7b3998c`.
- Verification lines honest: **yes** — all marked with actual PASS results and the NOT-RUN/NOTE
  caveats for environment path and orchestrator verification.
- No document content / secret values in messages: **yes** — verified by the no-leak tests and by
  message construction (lengths only, never the value).
- Executor made no commits/pushes/publishes/dependency installs/build artifacts: **yes**; Codex
  committed the independently approved implementation afterward.

## Completion checklist

- [x] Frozen/immutable shared limits model with exact standard defaults from the addendum.
- [x] Safe parsing/validation for the six overridable limits; CLI > environment > default precedence
      in a reusable form; no broad CLI redesign.
- [x] Manifest bytes enforced before decode; YAML depth/node/alias caps enforced.
- [x] Document count, per-doc bytes, aggregate doc bytes, path UTF-8 bytes, chunk count enforced at
      existing boundaries (doc index).
- [x] Query UTF-8 bytes and result limit enforced (provider/search + task hints).
- [x] Stable non-secret diagnostic codes; negative/overflow rejected; no silent truncation.
- [x] Current API/CLI/MCP behavior preserved for valid inputs; manifest 0.1 compatibility intact.
- [x] Focused positive/negative tests covering every boundary + compatibility.
- [x] `.agent/architecture.md`, `.agent/data_models.md`, `.agent/CHANGELOG.md` updated.
- [x] Truthful wrapup written.

## Assumptions

- `YAML parsed nodes` is implemented as a count of `compose_node` invocations (scalar, sequence,
  mapping, and root nodes each counted once) and `YAML aliases` as a count of alias events seen
  while composing; these match the addendum's "parsed nodes"/"aliases" wording with deterministic,
  bounded behavior.
- The `limit_result_limit` boundary refuses a requested search `limit` above the ceiling (raises a
  stable code) rather than silently capping, consistent with "do not silently truncate".
- `snapshot_bytes` and `init_report_bytes` are modelled but are not yet enforced because `export`
  and `init` are later merge units; this is disclosed as a gap, not a silent skip.
- Validate/inspect CLI `--max-*` flags were intentionally NOT added (CLI is a later merge unit); the
  reusable precedence API and env parsing are the deliverable for this slice.

## Risks / gaps

- `snapshot_bytes` ceiling is not yet enforced anywhere (no export path exists yet); enforced when
  WP3/export lands.
- `init_report_bytes` is not yet enforced because the init-report writer does not exist yet.
- CLI `--max-*` options are not wired into validate/inspect/serve; only `BEACON_MAX_*` environment
  overrides currently reach server startup via `BeaconSettings`. The reusable `apply_overrides()`
  path is ready for the CLI unit.
- Deep YAML nesting uses Python recursion through PyYAML's composer; the depth cap bounds the
  nesting ceiling but a pathological file still recurses up to `yaml_depth` frames (safe and
  bounded).
- Ambient `import beacon` resolves to a different 0.1.0 checkout unless the worktree `src` is first
  on `PYTHONPATH`; this is an environment/install-state quirk, disclosed and worked around in tests.
- Executor verification is local only; independent orchestrator verification and commit remain for
  Codex.

## Follow-up tasks

- Wire CLI `--max-*` options into validate/inspect/serve (merge-order unit 3+).
- Enforce `snapshot_bytes` when the export path (WP3) lands.
- Enforce `init_report_bytes` when the initialization report and atomic scaffold land.
- Consider a `conftest.py`/`pythonpath` setting so the worktree `src` is resolved regardless of the
  ambient environment's stray `beacon` install.

## Independent review

Codex reviewed the complete diff against the plan and addendum and remediated all findings before
approval:

- **P1 fixed — precedence corruption:** `apply_overrides()` rebuilt from defaults, so a partial CLI
  layer discarded unrelated environment overrides. It now uses immutable replacement and has a
  regression test preserving the unmentioned environment value.
- **P1 fixed — runtime overrides disconnected:** server startup parsed `BEACON_MAX_*` into settings
  but did not pass that profile into the provider. Lifespan wiring and effective-limit stderr
  diagnostics are now covered by an async regression test and stdio acceptance probe.
- **P2 fixed — post-allocation refusal:** manifest/document code used `read_bytes()` and checked the
  ceiling only after allocating the entire input. The shared bounded reader now consumes at most
  the ceiling plus one sentinel byte and never returns truncated content.
- **P2 fixed — incomplete defaults:** the 5 MiB initialization-report ceiling was missing from the
  shared model and docs. It is modelled now, with enforcement explicitly deferred to the init slice.
- **P2 fixed — lossy/negative input:** booleans/floats could coerce to integers and negative search
  limits fell through to Python slicing. Both are now rejected with `limit_invalid_value`.

**Implementation score:** 94/A
**Executor wrapup score:** 87/B
