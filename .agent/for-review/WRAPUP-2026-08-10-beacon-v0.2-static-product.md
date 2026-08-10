# WRAPUP — Beacon v0.2 static product

**Date:** 2026-08-10
**Agent:** Codex
**Model:** GPT-5
**Status:** PARTIAL
**Plan / Ticket:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\plans\beacon-v0.2-publishable-static-product-plan-2026-08-09.md`; `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\plans\beacon-v0.2-implementation-readiness-addendum-2026-08-09.md`
**Worktree:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0`
**Branch:** `release/v0.2.0`
**Commits:** `0cc63c550374937cbc2433f63fd3fdd649ddb110`, `8fe10c534b83f4f8f984f50568f7588f9c9b8a9d`, `04ebfc6df71c6503cebed60ea26088d53d9ea060`, `4bca71d9466cde17325dc76891df4b6fed8447f7`, `8459f106179610b2795128b1ffa59064ff7fd27e`, `215ad0d562524d57c2955d6f9abfc78346470e04`, `ca6dc9ecf5ea64c95a860e86a8e9374176060838`, `270fc459b14a24e1ccabd122a723687ffcba7792`, `7a593314200d1c1f5f1b2cec520e47a2584947d4`, `ff9fb8d2e77dcabd8b893a4b44842cf895b11356`, `766a3d8a601943589af7b82a5a14611d8e609ecc`, `9961285630771203a0289b211ab5445c4644026d`, `bf3af836d8fd8d1137ab71245e7956462b0c9ad6`, `137219f398e9e5f67a23f6c56c6b3f77bb5d0a8f`, `8f35b9d2fc0a7515b8d164ddb4dbc86858b4d97c`, `a8884e901c6f22cf4c02a0ecd0f200edd1b4668e`, `53e37caa0c4d593927a6039afea84e53364fdf65`, `c74c3afe803a91b122e20be86bdd204743d562b4`, `d348caf85524008835c858f2cc272d660df17e35`
**Verification Scope:** committed implementation range `0cc63c550374937cbc2433f63fd3fdd649ddb110^..d348caf85524008835c858f2cc272d660df17e35`; release tag `v0.2.0rc1` at `c74c3afe803a91b122e20be86bdd204743d562b4`; public `archolith-mcp-framework==0.2.0` and `archolith-beacon==0.2.0rc1` distributions; GitHub Actions runs `31404703007`, `31404704230`, `31405076870`, and `31405307364`
**Docs Updated:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\README.md`; `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\client-setup.md`; `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\demo-transcript.md`; `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\examples\README.md` and the three maintained example trees; `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\for-review\BEACON-v0.2-UNAIDED-TRIAL-SCORECARD.md`
**Changelog Updated:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\CHANGELOG.md`

---

## Before Writing

The two v0.2 plans were checked backwards from their release gates. The local static-product path is implemented: installable wheels, conservative init, review, strict validation, five-payload inspection, deterministic embedded and metadata-only export, and exact-five-tool stdio MCP all pass without runtime network access. Framework `0.2.0` was published first, then Beacon `0.2.0rc1`; both install from public PyPI. The pushed branch and draft PR passed the 3-OS/3-Python matrix. One genuinely unaided developer trial remains. Mechanical `artifact_validate` is unavailable in this Codex environment, so the wrapup remains `PARTIAL`.

## Summary

Beacon now has a functional, publicly installable v0.2 release-candidate loop rather than only a tool slice. It adds deterministic repository discovery and safe initialization, a versioned CLI result envelope, strict policy acknowledgements, bounded canonical snapshots, high-confidence secret blocking, full `init`/`validate`/`inspect`/`export`/`serve` CLI integration, three maintained examples, client setup documentation, cross-platform CI/release definitions, and an installed-wheel release journey. Independent review caught and fixed the migrated gateway exposing two extra meta-tools; the installed server now advertises and calls exactly the frozen five Beacon tools while retaining Archolith for server execution. The first remote matrix run also exposed a symlink-capable-runner mismatch, which is remediated. A deterministic negative-control mutation gate proves focused tests fail when token detection, strict-warning enforcement, manifest overwrite protection, or MCP tool registration is deliberately broken. Archolith MCP Framework `0.2.0` and Beacon `0.2.0rc1` are now on PyPI, the RC has checksummed GitHub release assets, and both branch and PR CI pass the full 3-by-3 matrix. The only product acceptance gate still open is the unaided-human trial.

## Files Changed

| File | Why |
|------|-----|
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\CHANGELOG.md` | Records the v0.2 implementation, documentation, and mutation gate. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\for-review\BEACON-v0.2-UNAIDED-TRIAL-SCORECARD.md` | Freezes the participant boundary, timed observations, and pass/fail criteria for the remaining external trial. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.github\workflows\ci.yml` | Adds the 3-OS/3-Python test matrix, quality/package gates, and negative-control mutations. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.github\workflows\release.yml` | Adds tagged build verification, trusted PyPI publication, checksums, and repository-explicit GitHub release creation. |
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
- `pip install --no-cache-dir --index-url https://pypi.org/simple archolith-mcp-framework==0.2.0` in a fresh environment — `PASS` — exact version installed from public PyPI; both current and compatibility imports passed; `pip check` reported no broken requirements.
- `pip install --no-cache-dir --index-url https://pypi.org/simple archolith-beacon==0.2.0rc1` in `C:\tmp\beacon-public-index-smoke-20260810` — `PASS` — exact Beacon RC and framework `0.2.0` installed from public PyPI; `pip check`, `import beacon`, `beacon --version`, and `beacon --help` passed.
- GitHub Actions runs `31404703007` and `31404704230` at tag commit `c74c3afe803a91b122e20be86bdd204743d562b4` — `PASS` — branch and PR runs each passed Linux/macOS/Windows on Python 3.12/3.13/3.14 plus package, installed-journey, quality, security, and mutation gates.
- GitHub Actions runs `31405076870` and `31405307364` at branch head `d348caf85524008835c858f2cc272d660df17e35` — `PASS` — the release-workflow fix also passed branch and PR CI, including the full 3-by-3 matrix.
- GitHub Actions release run `31404898850` — `PASS` for verified public-index build and trusted PyPI publication; `FAIL` for the original GitHub release-record job because it lacked repository context. The downloaded workflow artifacts matched `SHA256SUMS`, the prerelease was created manually without re-uploading PyPI, and commit `d348caf85524008835c858f2cc272d660df17e35` fixes future release creation with explicit repository context.
- Genuinely unaided developer trial — `NOT RUN` — requires an external participant; the scripted maintainer journey passed.
- `artifact_validate(artifact_type="wrapups", ...)` — `NOT RUN` — no artifact validator tool is available in this Codex environment; status therefore remains below `READY FOR REVIEW`.

## Claim Cross-Check

- Summary checked against actual code/diff: `yes`
- Files Changed checked against actual modified files: `yes`
- Commit list checked against actual commit hashes or working-tree state: `yes`
- Verification results copied from actual command output: `yes`

## Completion Checklist

- Plan / acceptance criteria completed: `partial` — implementation, scripted verification, public publication, and remote matrix execution are complete; the unaided trial remains.
- Docs updated as required: `yes`
- Changelog updated as required: `yes`
- Work committed: `yes`

## Assumptions

1. The release-candidate version remains `0.2.0rc1` until the prescribed framework-first public publication and RC smoke have occurred; the manifest schema remains `0.1` and snapshot/CLI schemas remain `1.0`.
2. The committed GitHub workflows are the authority for Python 3.12/3.13/3.14 on Windows, macOS, and Linux because only Python 3.12 was available locally.
3. Plain FastMCP registration plus Archolith `run_server` is the intentional boundary: Beacon keeps the migrated framework process path without inheriting gateway meta-tools that violate the frozen public surface.

## Risks / Gaps

1. No external developer has completed the required genuinely unaided trial.
2. The release run is red at the workflow level because the post-publication GitHub release-record job lacked repository context. Publication itself passed, the checksummed release record was recovered manually, and the workflow is fixed at branch head; the immutable tag correctly remains on the audited release commit.
3. Windows symlink-adversarial tests skip when the local account lacks symlink privilege; all three Windows matrix jobs execute them on symlink-capable runners and pass.
4. Mechanical wrapup validation is unavailable, which prevents an honest `READY FOR REVIEW` status under the wrapup skills.

## Follow-Up Tasks

1. Run one unaided developer trial from a fresh machine/account and record the scorecard and any blocking step.
2. Remediate any trial failure as a blocking v0.2 fix and repeat the unaided trial.
3. After the trial passes, merge the release PR, bump and publish final `archolith-beacon==0.2.0` without changing manifest schema `0.1`.

## Notes

- DeepSeek (`archolith/deepseek-v4-flash`) performed bounded implementation work through the harness; Codex retained architecture, diff review, integration, commits, and independent acceptance auditing.
- Archolith MCP Framework `0.2.0` was published first at `https://pypi.org/project/archolith-mcp-framework/`; Beacon `0.2.0rc1` followed at `https://pypi.org/project/archolith-beacon/`.
- Beacon prerelease `v0.2.0rc1` is at `https://github.com/Archolith/beacon/releases/tag/v0.2.0rc1` with wheel, sdist, and `SHA256SUMS` assets.
