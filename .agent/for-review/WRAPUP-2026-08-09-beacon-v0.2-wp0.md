# WRAPUP REVIEWED — Beacon v0.2 WP0 local migration

- **Agent:** opencode
- **Model:** archolith/deepseek-v4-flash
- **Date:** 2026-08-09
- **Status:** REVIEWED — APPROVED WITH REMEDIATION
- **Plan / ticket:** WP0 — Release truth and repository hygiene (`.agent/plans/beacon-v0.2-publishable-static-product-plan-2026-08-09.md`), `.agent/plans/beacon-v0.2-implementation-readiness-addendum-2026-08-09.md`
- **Worktree / branch:** `beacon-v0.2-wp0` / `release/v0.2.0`
- **Base commit:** `9e67fad`
- **Commits:** `ec5edb2`
- **Verification scope:** Executor verification NOT RUN by contract; independent orchestrator verification PASS
- **Docs updated:** README.md
- **Changelog updated:** Yes, by the orchestrator before commit

## Summary

Implemented the bounded Beacon v0.2 WP0 local package-migration patch on the
`release/v0.2.0` branch. Package metadata now describes the approved
`archolith-beacon` distribution with single-source dynamic version, an MIT
license/readme, Archolith identity, repository/issues URLs, and the migrated
`archolith-mcp-framework>=0.2,<0.3` runtime dependency (legacy
`cth-mcp-framework`, direct `pydantic`, and direct `fastmcp` removed). Exposed
an eager `beacon --version` that prints `beacon 0.2.0rc1` without starting the
MCP server or loading the manifest, while preserving no-argument stdio startup.
Added focused CLI version tests and a stdlib-only packaging-contract test suite.
Added a `.gitignore`, corrected the `.githooks/pre-push` message, and updated
README truth (gated PyPI, source-development setup, supported CPython range,
no stale validate/inspect claims). The public-index blocker is reported, not
concealed.

## Files changed

1. `pyproject.toml` — renamed distribution to `archolith-beacon`; `dynamic = ["version"]`
   read from `beacon.__version__`; `requires-python = ">=3.12,<3.15"`; MIT SPDX license +
   `license-files`; readme; Archolith authors/maintainers; keywords/classifiers; Homepage/
   Repository/Issues URLs; runtime deps `archolith-mcp-framework>=0.2,<0.3`, `PyYAML`,
   `python-dotenv`, `typer`; removed `cth-mcp-framework`, `pydantic`, `fastmcp`; dev tools moved
   to `[project.optional-dependencies] dev` (`pytest`, `pytest-asyncio`, `build`, `twine`,
   `jsonschema`) so `pip install -e ".[dev]"` works; removed the invalid `Framework :: MCP`
   classifier; bumped `setuptools>=77` for standards-compliant PEP 639 license metadata.
2. `src/beacon/__init__.py` — `__version__` changed `0.1.0` → `0.2.0rc1`.
3. `src/beacon/main.py` — added eager `_version_callback` and `--version` option on the `serve`
   callback; switched `cth_mcp_framework` → `archolith_mcp_framework` import for `run_server`.
4. `src/beacon/mcp/server.py` — switched to `from archolith_mcp_framework import
   create_gateway_server`; removed the now-unused `run_server` import.
5. `tests/test_cli.py` — added `TestVersion` (exact output, no-server-start via `sys.modules`
   blocking, no startup text).
6. `tests/test_packaging.py` (new) — stdlib `tomllib`/`pathlib` contract tests for metadata,
   version source, dependencies, URLs/readme/license, and source hygiene.
7. `.gitignore` (new) — Python/build/test/venv/coverage/IDE/OS junk, `.env` secrets, generated
   `*.snapshot.json` artifacts, with committed `examples/**` snapshots explicitly allowed.
8. `.githooks/pre-push` — corrected stale "Use main or a feature branch" message to point at
   `release/v0.2.0` or a feature branch; `master` remains blocked.
9. `README.md` — removed unpublished PyPI badges; documented the gated public index and a truthful
   source-development setup (editable installs of a separately checked-out
   `archolith-mcp-framework` v0.2.0); stated CPython 3.12–3.14; added a `beacon --version` quick-start
   step; corrected the stale "validate/inspect unimplemented" bullet; kept five-tool/product
   positioning intact.
10. `.agent/for-review/WRAPUP-2026-08-09-beacon-v0.2-wp0.md` (new) — this document.

## Verification commands / results

All verification intentionally **NOT RUN** — the task fence forbids running
git/build/test/pytest/pip.

- `python -m pytest -p no:cacheprovider -q` — **NOT RUN**
- `python -m build` — **NOT RUN**
- `python -m twine check dist/*` — **NOT RUN**
- `beacon --version` / `python -m beacon --version` — **NOT RUN**

## Claim cross-check

- Summary matches diff: **yes** — every listed change corresponds to an actual edit above.
- Files-changed list matches edits: **yes** — all 10 named files touched; no files outside the
  allowed list modified.
- Commit list matches: **yes** — approved implementation committed as `ec5edb2`.
- Verification lines honest: **yes** — all marked NOT RUN; nothing claimed to pass.
- Final public signatures listed: **yes** — see "Final signatures" below.
- No legacy `cth` text remains in executable source or pyproject: **yes** (grep confirms).

## Completion checklist

- [x] Distribution name `archolith-beacon`, `>=3.12,<3.15`, single-source dynamic version.
- [x] Dev tools under `[project.optional-dependencies] dev` (`pip install -e ".[dev]"`).
- [x] Valid classifiers only; Homepage/Repository/Issues URLs present.
- [x] Framework import migrated to `archolith_mcp_framework`; unused `run_server` removed from server.
- [x] Eager `beacon --version` → `beacon 0.2.0rc1`, exit 0, no manifest/server/env/startup text.
- [x] No-argument stdio startup path preserved.
- [x] Packaging-contract tests added (semantic assertions).
- [x] `.gitignore`, pre-push message, README truth.
- [x] Executor wrapup recorded NOT RUN honestly; orchestrator verification and commit appended below.

## Assumptions

- `archolith_mcp_framework` exports `create_gateway_server` and `run_server` with the same shapes
  as the legacy `cth_mcp_framework` names used here, per task context. (STOP conditions did not
  trigger; no incompatible export observed from the worktree.)
- `fastmcp` and `pydantic` were removed as direct dependencies because all `fastmcp` imports are
  `TYPE_CHECKING`-only and `pydantic` is not imported anywhere in `src`. Independent wheel
  installation verified that framework `0.2.0` supplies `fastmcp>=3.2.4,<4` transitively.
- License/ownership fact uses only "Archolith" + MIT already established in `LICENSE`; no
  invented people/emails.
- `setuptools>=77` raised purely to support the PEP 639 SPDX license string + `license-files`.

## Risks / gaps

- **Public-index blocker:** PyPI has no matching `archolith-mcp-framework` distribution as of this
  run. `pip install archolith-beacon` will not work until the framework is published. This remains
  an orchestrator gate and is not worked around with a direct Git URL.
- The `--version` option renders as `--version`/`--no-version` (Typer bool default) on the top-level
  callback; acceptable and does not change validate/inspect or no-arg behavior.
- Version eager path imports `beacon.__version__` only on `--version`; the server/manifest imports
  remain lazy inside the stdio branch. The reviewer verified this through source tests and the
  installed console command.
- README quick-start shows env-var-driven `beacon validate`/`inspect` while the implemented commands
  take a positional PATH; pre-existing inconsistency left unchanged per scope (validate/inspect
  semantics frozen).
- `_version_callback` uses `typer.echo` (stdout + newline) — matches required `beacon 0.2.0rc1\n`.

## Follow-up tasks

- Publish `archolith-mcp-framework==0.2.0` to PyPI, then repeat the clean install using only public
  indexes instead of the locally built framework wheel.
- Add the full Python 3.12/3.13/3.14 and Windows/macOS/Linux CI matrix in the later WP5 gate.

## Review Findings — 2026-08-09

**Reviewer:** Codex (GPT-5)

**Final result:** APPROVED. No open code or reporting findings remain in the bounded WP0 scope.

Remediation applied during review:

- **P1 fixed:** the first build rejected the legacy MIT Trove classifier because the package uses
  the PEP 639 `license = "MIT"` expression. The classifier was removed, a packaging regression test
  was added, and the rebuilt wheel/sdist passed metadata checks.
- **P2 fixed before central verification:** dev tooling was moved from `[dependency-groups]` to the
  real `[project.optional-dependencies].dev` extra used by `pip install -e ".[dev]"`.
- **P3 fixed before central verification:** removed the invalid `Framework :: MCP` classifier,
  added the Homepage URL, corrected the exact harness model, and removed harness task residue.

Plans checked:

- `.agent/plans/beacon-v0.2-publishable-static-product-plan-2026-08-09.md` — WP0
- `.agent/plans/beacon-v0.2-implementation-readiness-addendum-2026-08-09.md`

Independent verification:

- Archolith framework tag `v0.2.0`: `83 passed`.
- Beacon full suite: `83 passed`.
- Draft 2020-12 meta-validation: all three Beacon JSON Schemas passed.
- `python -m build --no-isolation`: wheel and sdist built successfully.
- `python -m twine check dist/*`: both artifacts passed.
- Wheel inspection: expected package/license/metadata present; tests absent from wheel.
- Fresh virtual environment: locally built framework `0.2.0` wheel plus Beacon `0.2.0rc1` wheel
  installed with public transitive dependencies; version/help/validate/inspect passed.
- Packaged stdio subprocess: all five Beacon MCP tools listed and returned success.
- `git diff --check`: passed before commit.

External gate still open: neither `archolith-mcp-framework` nor `archolith-beacon` resolved from
PyPI during review. No direct Git dependency was added.

**Implementation score:** 94/A
**Wrapup score:** 91/A
