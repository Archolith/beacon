# WRAPUP — Beacon v0.2 static product

**Date:** 2026-08-10
**Agent:** Codex
**Model:** GPT-5
**Status:** PARTIAL
**Plan / Ticket:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\plans\beacon-v0.2-publishable-static-product-plan-2026-08-09.md`; `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\plans\beacon-v0.2-implementation-readiness-addendum-2026-08-09.md`
**Worktree:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0`
**Branch:** `release/v0.2.0`
**Commits:** `0cc63c550374937cbc2433f63fd3fdd649ddb110`, `8fe10c534b83f4f8f984f50568f7588f9c9b8a9d`, `04ebfc6df71c6503cebed60ea26088d53d9ea060`, `4bca71d9466cde17325dc76891df4b6fed8447f7`, `8459f106179610b2795128b1ffa59064ff7fd27e`, `215ad0d562524d57c2955d6f9abfc78346470e04`, `ca6dc9ecf5ea64c95a860e86a8e9374176060838`, `270fc459b14a24e1ccabd122a723687ffcba7792`, `7a593314200d1c1f5f1b2cec520e47a2584947d4`, `ff9fb8d2e77dcabd8b893a4b44842cf895b11356`, `766a3d8a601943589af7b82a5a14611d8e609ecc`, `9961285630771203a0289b211ab5445c4644026d`, `bf3af836d8fd8d1137ab71245e7956462b0c9ad6`, `137219f398e9e5f67a23f6c56c6b3f77bb5d0a8f`, `8f35b9d2fc0a7515b8d164ddb4dbc86858b4d97c`, `a8884e901c6f22cf4c02a0ecd0f200edd1b4668e`
**Verification Scope:** committed implementation range `0cc63c550374937cbc2433f63fd3fdd649ddb110^..a8884e901c6f22cf4c02a0ecd0f200edd1b4668e`; clean `release/v0.2.0` worktree; locally built `C:\Users\thron\Documents\Codex\2026-08-09\c-users-thron-documents-codex-2026\work\beacon-v02-finish\remediation\archolith_beacon-0.2.0rc1-py3-none-any.whl` (SHA-256 `9411a48ecccf20540ad5ea143b0c8e1419f330d81427da7b478572d070e13df7`, 91,355 bytes)
**Docs Updated:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\README.md`; `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\client-setup.md`; `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\demo-transcript.md`; `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\README.md` and the three maintained example trees
**Changelog Updated:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\CHANGELOG.md`

---

## Before Writing

The two v0.2 plans were checked backwards from their release gates. The local static-product path is implemented: installable local wheels, conservative init, review, strict validation, five-payload inspection, deterministic embedded and metadata-only export, and exact-five-tool stdio MCP all pass without runtime network access. The remaining plan gates require external state that this implementation run cannot manufacture: publication of both distributions to a public index, execution of the remote 3-OS/3-Python matrix after push, and one genuinely unaided developer trial. Mechanical `artifact_validate` was unavailable in this Codex environment, so the wrapup remains `PARTIAL` as required by the wrapup skills even though the local implementation and audits are complete.

## Summary

Beacon now has a functional v0.2 release-candidate loop rather than only a tool slice. It adds deterministic repository discovery and safe initialization, a versioned CLI result envelope, strict policy acknowledgements, bounded canonical snapshots, high-confidence secret blocking, full `init`/`validate`/`inspect`/`export`/`serve` CLI integration, three maintained examples, client setup documentation, cross-platform CI/release definitions, and an installed-wheel release journey. Independent review caught and fixed the migrated gateway exposing two extra meta-tools; the installed server now advertises and calls exactly the frozen five Beacon tools while retaining Archolith for server execution. The first remote matrix run also exposed a symlink-capable-runner mismatch: init raised for a final target symlink instead of returning its documented refusal report. That boundary is remediated while direct path resolution remains strict. A deterministic negative-control mutation gate additionally proves that focused tests fail when token detection, strict-warning enforcement, manifest overwrite protection, or MCP tool registration is deliberately broken. The final local wheel passed the full scripted product journey, typing, lint, security, schema, package, wheel-content, dependency-consistency, and vulnerability gates. Public-index publication and the unaided-human trial remain open; remote CI is handled after this local closeout is committed.

## Files Changed

| File | Why |
|------|-----|
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\CHANGELOG.md` | Records the v0.2 implementation, documentation, and mutation gate. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.github\workflows\ci.yml` | Adds the 3-OS/3-Python test matrix, quality/package gates, and negative-control mutations. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.github\workflows\release.yml` | Adds tagged build verification, trusted PyPI publication, checksums, and GitHub release creation. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.gitignore` | Ignores bounded local build, CI, environment, and snapshot scratch. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\README.md` | Documents the implemented product loop, examples, versions, clients, and honest publication state. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\client-setup.md` | Adds install-first client configuration for Claude, Cursor, Codex, Gemini, OpenCode, and generic stdio. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\demo-transcript.md` | Aligns the runnable demo with the v0.2 CLI loop. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\README.md` | Indexes the maintained example matrix. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\library\README.md` | Documents the library example. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\library\beacon.yaml` | Provides a valid library manifest. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\library\docs\format.md` | Supplies canonical library documentation. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\service\README.md` | Documents the service example. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\service\beacon.yaml` | Provides a valid service manifest. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\service\docs\architecture.md` | Supplies canonical service architecture documentation. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\service\docs\operations.md` | Supplies canonical service operations documentation. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\monorepo-research\README.md` | Documents the research-monorepo example. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\monorepo-research\beacon.yaml` | Provides a valid research-monorepo manifest. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\monorepo-research\docs\data.md` | Supplies canonical data documentation. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\monorepo-research\docs\methodology.md` | Supplies canonical methodology documentation. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\pyproject.toml` | Declares release dependencies, including direct FastMCP use for the exact-five server. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\scripts\check_repo_clean.py` | Adds a cross-platform cleanliness gate. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\scripts\release_check.py` | Adds the clean installed-wheel product journey and socket-denial audit. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\scripts\run_mutation_tests.py` | Applies four deliberate regressions in temporary package copies and requires focused pytest failures. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\scripts\write_sha256sums.py` | Adds deterministic external distribution checksums. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\core\canonical_json.py` | Adds bounded canonical JSON encoding and atomic writing. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\core\cli_result.py` | Defines the versioned CLI envelope and diagnostics. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\core\cli_support.py` | Centralizes command context, limits, validation, policy, and provider construction. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\core\discovery.py` | Implements bounded repository discovery and sanitized git metadata. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\core\policy.py` | Enforces bounded, reasoned warning acknowledgements. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\core\scaffold.py` | Implements deterministic manifests, reports, safe overwrite, and atomic init writes. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\core\security.py` | Adds non-leaking high-confidence secret detection and controlled overrides. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\core\snapshot.py` | Implements canonical embedded and metadata-only snapshots. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\main.py` | Implements the complete v0.2 CLI while preserving no-argument stdio. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\mcp\server.py` | Preserves the exact five-tool public surface without gateway meta-tools. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\fixtures\schemas\cli-result-invalid.json` | Adds a negative CLI-envelope schema fixture. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\fixtures\schemas\cli-result-valid.json` | Adds a positive CLI-envelope schema fixture. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\fixtures\schemas\init-report-invalid.json` | Adds a negative init-report schema fixture. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\fixtures\schemas\init-report-valid.json` | Adds a positive init-report schema fixture. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\fixtures\schemas\snapshot-invalid.json` | Adds a negative snapshot schema fixture. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\fixtures\schemas\snapshot-valid.json` | Adds a positive snapshot schema fixture. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_canonical_json.py` | Tests canonical bytes, limits, and atomic writes. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_ci_tools.py` | Tests cross-platform CI helpers. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_cli.py` | Tests full CLI behavior, output contracts, collisions, limits, and failures. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_cli_result.py` | Tests envelope schema and canonical serialization. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_cli_support.py` | Tests shared context and failure normalization. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_examples.py` | Validates all examples, five provider calls, and both export modes. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_init_core.py` | Tests discovery, init determinism, paths, reports, and overwrite rules. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_mcp_contracts.py` | Tests non-leaking errors and exact five-tool registration. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_mcp_stdio.py` | Tests exact-five black-box stdio calls under socket denial. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_mutation_runner.py` | Tests mutation definitions, source anchors, selection, and checkout isolation. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_packaging.py` | Tests package metadata and direct runtime dependencies. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_policy.py` | Tests bounded acknowledgement behavior. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_release_check.py` | Tests the release-journey planner, checkers, and failure normalization. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_security.py` | Tests secret classes, overrides, and non-leaking diagnostics. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_snapshot.py` | Tests snapshot schemas, determinism, limits, policy, security, and paths. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\for-review\WRAPUP-2026-08-10-beacon-v0.2-static-product.md` | Records this diff-backed closeout. |

## Verification

- `$env:PYTHONPATH=(Resolve-Path 'src').Path; python -m pytest -p no:cacheprovider -q` — `PASS` — 572 passed, 9 skipped; the skips were one source-environment framework integration and Windows symlink-privilege cases, both covered by the accepted wheel journey or CI matrix.
- `python -m ruff check src tests scripts` — `PASS` — all checks passed.
- `python -m ruff format --check src tests scripts` — `PASS` — 56 files already formatted.
- `mypy --no-incremental src` from the clean audit environment — `PASS` — no issues in 33 source files.
- `bandit -r src -q` from the clean audit environment — `PASS` — no findings; one existing targeted B506 suppression was reported as a warning.
- `validate-pyproject pyproject.toml` — `PASS` — valid file.
- `python -m twine check C:\Users\thron\Documents\Codex\2026-08-09\c-users-thron-documents-codex-2026\work\beacon-v02-finish\remediation\archolith_beacon-0.2.0rc1-py3-none-any.whl` — `PASS`.
- `check-wheel-contents C:\Users\thron\Documents\Codex\2026-08-09\c-users-thron-documents-codex-2026\work\beacon-v02-finish\remediation\archolith_beacon-0.2.0rc1-py3-none-any.whl` — `PASS` — wheel contents OK.
- `pip check` in the clean audit environment — `PASS` — no broken requirements.
- `pip-audit --progress-spinner off` in the clean audit environment — `PASS` — no known vulnerabilities; the two unpublished local Archolith distributions were skipped by name.
- `python scripts/release_check.py --framework-wheel <local-v0.2.0-wheel> --beacon-wheel <remediated-rc1-wheel>` — `PASS` — framework-first clean install, version/help, init/report, review edit, strict JSON validate, exact five-payload inspect, deterministic embedded export, metadata-only export, exact-five real stdio enumeration/calls, and no socket-guard marker.
- `python scripts/run_mutation_tests.py` — `PASS` — 4 of 4 deliberate mutants killed; each focused pytest invocation exited with `TESTS_FAILED` as required.
- `python scripts/check_repo_clean.py .` — `PASS` — clean repository after implementation commits.
- `gh repo view Archolith/beacon ...` and `gh repo view Archolith/archolith-mcp-framework ...` — `PASS` — both repositories report `PUBLIC`.
- Public-index install of `archolith-mcp-framework==0.2.0` and `archolith-beacon==0.2.0rc1` — `NOT RUN` — both PyPI project JSON endpoints currently return 404.
- GitHub Actions 3-OS/3-Python matrix on these commits — `NOT RUN` in local verification — requires the committed branch to be pushed; remote status is checked separately after closeout.
- Genuinely unaided developer trial — `NOT RUN` — requires an external participant; the scripted maintainer journey passed.
- `artifact_validate(artifact_type="wrapups", ...)` — `NOT RUN` — no artifact validator tool is available in this Codex environment; status therefore remains below `READY FOR REVIEW`.

## Claim Cross-Check

- Summary checked against actual code/diff: `yes`
- Files Changed checked against actual modified files: `yes`
- Commit list checked against actual commit hashes or working-tree state: `yes`
- Verification results copied from actual command output: `yes`

## Completion Checklist

- Plan / acceptance criteria completed: `partial` — all local implementation and scripted verification are complete; publication, remote matrix execution, and the unaided trial are external gates.
- Docs updated as required: `yes`
- Changelog updated as required: `yes`
- Work committed: `yes`

## Assumptions

1. The release-candidate version remains `0.2.0rc1` until the prescribed framework-first public publication and RC smoke have occurred; the manifest schema remains `0.1` and snapshot/CLI schemas remain `1.0`.
2. The committed GitHub workflows are the authority for Python 3.12/3.13/3.14 on Windows, macOS, and Linux because only Python 3.12 was available locally.
3. Plain FastMCP registration plus Archolith `run_server` is the intentional boundary: Beacon keeps the migrated framework process path without inheriting gateway meta-tools that violate the frozen public surface.

## Risks / Gaps

1. Neither Archolith distribution exists on PyPI yet, so a public-index-only installation cannot pass today.
2. The 3-by-3 GitHub Actions matrix must pass on the pushed release branch; its result is tracked separately from this local artifact verification.
3. No external developer has completed the required genuinely unaided trial.
4. Windows symlink-adversarial tests skip when the local account lacks symlink privilege; symlink-capable CI runners execute them and exposed the final-target refusal mismatch remediated in this closeout.
5. Mechanical wrapup validation was unavailable, which prevents an honest `READY FOR REVIEW` status under the wrapup skills.

## Follow-Up Tasks

1. Require the pushed `release/v0.2.0` branch and draft pull request checks to pass before tagging.
2. Publish and public-index-smoke `archolith-mcp-framework==0.2.0`, then publish/TestPyPI-smoke `archolith-beacon==0.2.0rc1` through the committed trusted-publishing workflow.
3. Run one unaided developer trial from a fresh machine/account and record the scorecard and any blocking step.
4. After those gates pass, bump and publish final `archolith-beacon==0.2.0` without changing manifest schema `0.1`.

## Notes

- DeepSeek (`archolith/deepseek-v4-flash`) performed bounded implementation work through the harness; Codex retained architecture, diff review, integration, commits, and independent acceptance auditing.
- No package was published and no release tag was created in this run.
