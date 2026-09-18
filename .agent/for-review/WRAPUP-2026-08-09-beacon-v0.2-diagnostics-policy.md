# WRAPUP REVIEWED — Beacon v0.2 stable validation diagnostic codes and strict/acknowledgement policy

- **Agent:** opencode
- **Model:** archolith/deepseek-v4-flash
- **Date:** 2026-08-09
- **Status:** REVIEWED — APPROVED WITH REMEDIATION
- **Plan / ticket:** Merge-order unit 3 — "Stable diagnostic codes and strict/acknowledgement policy"
  (`.agent/plans/beacon-v0.2-publishable-static-product-plan-2026-08-09.md`, §11;
  `.agent/plans/beacon-v0.2-implementation-readiness-addendum-2026-08-09.md`, §10 step 3, §5 Validation and publication policy + Warning acknowledgement)
- **Worktree / branch:** `beacon-v0.2-wp0` / `release/v0.2.0`
- **Base commit:** `7d9833e` (working tree clean at start)
- **Commits:** `57c8229` (`feat: add Beacon publication diagnostics policy`)
- **Verification scope:** Executor verification plus independent Codex review, remediation, and
  acceptance testing against the worktree source with the worktree `src` first on `PYTHONPATH`.
- **Docs updated:** `.agent/architecture.md`, `.agent/data_models.md`, `.agent/CHANGELOG.md`
- **Changelog updated:** Yes (new entry at top of `.agent/CHANGELOG.md`)

## Summary

Implemented the Beacon v0.2 merge-order unit 3 slice: stable validation diagnostic codes and the
strict/acknowledgement serving-versus-publication policy. Gave every existing validation fact a
stable, non-secret diagnostic `code` on `ValidationIssue` (additive to the legacy
`severity`/`where`/`message` fields, so existing consumers are unchanged). The validator now emits
the addendum §5 publication-warning codes — including the acknowledgeable absent-test
(`test_command_missing`) and absent-guardrail (`guardrails_missing`) findings — plus stable codes for
all other current findings. The legacy three-positional-argument `ValidationIssue` constructor
remains compatible and receives the stable fallback code `legacy_issue`. Added
`beacon.core.policy` with reusable APIs for the next (CLI) unit:
`evaluate_policy()` returns a `PolicyEvaluation` that distinguishes `servable` (no errors) from
`publishable` (no errors *and* no unresolved publication warnings), and
`parse_acknowledgement()`/`parse_acknowledgements()` implement explicit acknowledgement exactly as
specified (`CODE=REASON`, reason trimmed/non-empty/≥10 chars; unknown, duplicate, malformed, and
unallowlisted codes are input errors with stable `AcknowledgementError` codes; only
`test_command_missing` and `guardrails_missing` are acknowledgeable in v0.2). Acknowledgements
change policy disposition but preserve the original diagnostic severity/facts and record the reason;
they never mutate `beacon.yaml`. Policy evaluation revalidates acknowledgement objects even when a
caller bypasses the text parser and constructs the dataclass directly. The full CLI JSON envelope, `--strict-warnings`, and
`--acknowledge` flags were intentionally NOT added (later merge unit); this slice provides only the
reusable core APIs.

## Files changed

1. `src/beacon/core/validator.py` — added stable diagnostic code constants, `VALIDATION_CODES`,
   and `PUBLICATION_WARNING_CODES` (exactly the addendum §5 set); added a `code` field to
   `ValidationIssue`; assigned codes to every existing finding; added the new publication-warning
   findings `project_status_unknown`, `purpose_missing`, and `guardrails_missing`; emitted
   `knowledge_status_invalid` from `_check_status`.
2. `src/beacon/core/policy.py` (new) — `Acknowledgement`, `AcknowledgementError` (stable codes),
   `ACKNOWLEDGEABLE_CODES`, `MIN_ACKNOWLEDGEMENT_REASON_LENGTH`, `parse_acknowledgement()`,
   `parse_acknowledgements()`, `PolicyEvaluation`, and `evaluate_policy()`.
3. `src/beacon/core/__init__.py` — re-exported the policy types/functions.
4. `tests/test_policy.py` (new) — 29 focused tests: every acknowledgement rejection path,
   direct-object revalidation, normal/strict/publish/export dispositions, preserved facts/severity,
   deterministic ordering, and legacy positional-constructor compatibility.
5. `.agent/architecture.md` — documented the stable codes, publication-warning set, policy module,
   and acknowledgement model; updated the package layout.
6. `.agent/data_models.md` — added a "Validation Diagnostics and Policy" section.
7. `.agent/CHANGELOG.md` — added a top entry for this slice.
8. `.agent/for-review/WRAPUP-2026-08-09-beacon-v0.2-diagnostics-policy.md` (new) — this document.

## Verification commands / results

All runs used `PYTHONPATH=<worktree>/src` so the worktree package (version `0.2.0rc1`) is imported
rather than a stray 0.1.0 checkout (the ambient environment resolves `import beacon` elsewhere; this
pre-existing quirk is disclosed and worked around with `PYTHONPATH`).

- Executor full suite before review — **PASS**: `141 passed`.
- Independent `python -m pytest -p no:cacheprovider -q` — **PASS**: `144 passed`.
- Independent focused `tests/test_policy.py` — **PASS**: `29 passed`.
- `python -m beacon validate beacon.yaml` (worktree src on path) — **PASS**: `✓ Valid — 0 errors,
  0 warnings`, exit 0.
- `python -m compileall -q src tests` — **PASS**.
- `git diff --check` — **PASS** (exit 0; LF→CRLF line-ending warnings only).
- No commit/push/publish/dependency-install/build-artifact performed (constraint honored).

## Claim cross-check

- Summary matches diff: **yes** — every listed change corresponds to an edit above.
- Files-changed list matches edits: **yes** — all named files touched; no plan files edited.
- Commit list matches: **yes** — implementation is anchored to `57c8229`.
- Verification lines honest: **yes** — all entries carry a PASS result; the ambient-import quirk and
  local-only verification are disclosed.
- No document content / secret values in diagnostic codes/messages: **yes** — codes are fixed
  strings; messages reuse existing non-secret text.
- Executor made no commits/pushes/publishes/dependency installs/build artifacts: **yes**; Codex
  committed the independently approved implementation afterward.

## Completion checklist

- [x] Every existing validation fact has a stable diagnostic code and structured immutable shape;
      legacy fields and three-argument positional construction remain compatible.
- [x] Policy evaluation distinguishes servable from publishable: errors block; strict warnings block
      publication; serve may continue with visible warnings; publication treats unresolved
      publication warnings as blocking.
- [x] Explicit acknowledgement parsing/model/evaluation exactly as specified: only
      `test_command_missing` and `guardrails_missing`; `CODE=REASON`; reason trimmed/non-empty/≥10;
      unknown/duplicate/malformed/unallowlisted codes are input errors; disposition changes but
      severity/facts preserved and reason recorded; `beacon.yaml` not mutated.
- [x] Validator emits at least the absent-test and absent-guardrail codes and stable codes for all
      other findings; no full CLI JSON envelope or broad command redesign; reusable core APIs provided.
- [x] Focused tests for every rejection path, normal/strict/publish/export dispositions, preserved
      facts/severity, deterministic ordering, and legacy compatibility.
- [x] `.agent/architecture.md`, `.agent/data_models.md`, `.agent/CHANGELOG.md` updated.
- [x] Truthful wrapup written.

## Assumptions

- `PUBLICATION_WARNING_CODES` is exactly the eight codes enumerated in the addendum §5 table.
  Non-publication warnings (e.g. `guardrail_severity_invalid`) are reported but do NOT block
  publication, matching the addendum's explicit enumeration rather than treating every warning as
  publication-blocking.
- `project_status_unknown` fires when `project.status` (lowercased/trimmed) equals `"unknown"`; all
  other manifest statuses (default `experimental`, `current`, etc.) do not.
- `guardrails_missing` fires when the manifest declares zero guardrails; `test_command_missing` when
  `build_and_test.test` is empty/blank. Both are v0.2 acknowledgeable publication warnings.
- Legacy callers may construct `ValidationIssue(severity, where, message)`; such externally-created
  findings receive `legacy_issue`, while every validator-generated finding passes a specific code.

## Risks / gaps

- Full CLI wiring (`--strict-warnings`, `--acknowledge`, exit-code mapping, and the
  `beacon.cli-result` JSON envelope) is intentionally deferred to the next merge unit; only the
  reusable core APIs are provided here.
- `PolicyEvaluation.acknowledged` records the reason for human/JSON output and future export
  metadata, but the export snapshot writer does not exist yet, so the
  `validation.acknowledgements` snapshot field is not yet produced (export is a later unit).
- `guardrail_severity_invalid` is treated as non-publication-blocking based on the addendum's
  explicit code list; if the plan later intends all warnings to block strict publication, the
  `PUBLICATION_WARNING_CODES` set is the single place to extend.
- Ambient `import beacon` resolves to a different 0.1.0 checkout unless the worktree `src` is first
  on `PYTHONPATH`; pre-existing environment quirk, disclosed and worked around in verification.
- Ambient source resolution still requires `PYTHONPATH=<worktree>/src` until project-level test
  path configuration is added.

## Follow-up tasks

- Wire `--strict-warnings` and `--acknowledge CODE=REASON` into `beacon validate`, map the
  acknowledged/unresolved disposition to the exit codes, and render acknowledgements in text/JSON
  (next merge unit).
- Record accepted acknowledgements in the export snapshot's `validation.acknowledgements` when WP3
  (`beacon export`) lands.
- Consider a `conftest.py`/`pythonpath` setting so the worktree `src` resolves regardless of the
  ambient environment's stray `beacon` install.

## Independent review

Codex reviewed the complete diff against the implementation addendum and remediated both findings
before approval:

- **P1 fixed — legacy constructor break:** placing `code` first made
  `ValidationIssue(severity, where, message)` fail or bind fields incorrectly for external
  consumers. The legacy fields are first again, `code` has a stable fallback, and a regression test
  exercises the original positional constructor.
- **P2 fixed — policy parser bypass:** `evaluate_policy()` trusted directly constructed
  `Acknowledgement` objects, allowing duplicate, unknown, or unallowlisted codes to bypass parser
  rules. Evaluation now normalizes and revalidates every object and has focused duplicate and
  unallowlisted-code tests.

**Implementation score:** 94/A
**Executor wrapup score:** 82/B
