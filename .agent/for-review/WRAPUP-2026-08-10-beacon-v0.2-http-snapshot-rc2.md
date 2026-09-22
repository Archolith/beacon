# WRAPUP — Beacon v0.2 RC2 loopback HTTP snapshot

**Date:** 2026-08-10
**Agent:** Codex
**Model:** GPT-5
**Status:** PARTIAL
**Plan / Ticket:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\plans\beacon-v0.2-http-snapshot-rc2-plan-2026-08-10.md`
**Worktree:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0`
**Branch:** `release/v0.2.0`
**Commits:** `34368ab5077e8d4a1984154181c0e58a3cc261ef`, `3d3db88c145947d3fba2fb7c307d968f43bcc33c`, `ddf39c9e76b8184222b1603024502bc63d53b661`
**Verification Scope:** commits `34368ab5077e8d4a1984154181c0e58a3cc261ef`, `3d3db88c145947d3fba2fb7c307d968f43bcc33c`, and `ddf39c9e76b8184222b1603024502bc63d53b661`; wheel `C:\tmp\beacon-http-rc2-title-only-build-20260810\archolith_beacon-0.2.0rc2-py3-none-any.whl` (SHA-256 `0314F9A7EF047C3FA72669047C1A4A804F0AFF14767E2979C7F919B15FC09C0D`); sdist `C:\tmp\beacon-http-rc2-title-only-build-20260810\archolith_beacon-0.2.0rc2.tar.gz` (SHA-256 `8B3487F0CC6139E729A44D73DC3BABFBCF9CC736EB8B9FBADE22BA5ECE244C4E`)
**Docs Updated:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\README.md`, `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\client-setup.md`, `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\demo-transcript.md`, `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\beacon-functional-product-roadmap.md`, `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\plans\beacon-v0.2-http-snapshot-rc2-plan-2026-08-10.md`
**Changelog Updated:** `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\CHANGELOG.md`

---

## Summary

Beacon now has an RC2 `serve-http` command for non-MCP local clients. It builds one embedded canonical snapshot through the existing publication and secret gates, binds only to `127.0.0.1`, and serves immutable discovery, snapshot, alias, and health responses with deterministic JSON, SHA-256 identity, ETag/304 support, redacted errors, and no CORS, access logs, or server/date headers. The installed-wheel release journey proves that HTTP bytes match `beacon export` while the runtime outbound-socket guard remains active.

After live exposure review, plan-role documents were reduced to title/path/role/status/hash metadata in snapshots; their chunks are empty and their bodies remain available only to the private local MCP index. On Beacon's own manifest this reduced the live snapshot from 169,049 bytes to roughly 91.6 KB while preserving all three plan titles.

The implementation is committed and locally release-ready. The wrapup remains `PARTIAL` because the required `artifact_validate` tool is unavailable, the branch has not been pushed for the hosted 3-by-3 matrix, RC2 has not been tagged or published, and the explicitly deferred unaided owner trial has not been conducted.

## Files Changed

| File | Why |
|------|-----|
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\http_api.py` | Implements the immutable Starlette discovery, snapshot, health, conditional-request, and error contracts. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\main.py` | Adds the loopback-only `serve-http` CLI, export-gate reuse, socket binding, and redacted startup contract. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\core\snapshot.py` | Keeps `plan` and `*_plan` bodies out of static snapshots while retaining metadata and private MCP indexing. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\src\beacon\__init__.py` | Bumps the package version to `0.2.0rc2`. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\pyproject.toml` | Declares direct Starlette and Uvicorn runtime dependencies. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\scripts\release_check.py` | Adds a real installed-process HTTP journey under the outbound-socket guard. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_http_api.py` | Covers routes, byte identity, HEAD, ETag including wildcard, errors, leakage, hostile input, and immutability. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_snapshot.py` | Locks title-only plan serialization and proves omitted plan bodies are not scanned as exported content. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_cli.py` | Covers CLI startup gates, host/port failures, warnings, secrets, occupied ports, and redacted exceptions. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_packaging.py` | Locks RC2 version and direct dependency metadata. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\tests\test_release_check.py` | Locks the HTTP journey into release-check ordering. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\README.md` | Documents RC2 status, plain-JSON operation, limits, and pending publication accurately. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\client-setup.md` | Adds non-MCP client setup and the loopback security boundary. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\demo-transcript.md` | Adds the optional `serve-http` product-loop step. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\docs\beacon-functional-product-roadmap.md` | Records HTTP snapshot retrieval as a v0.2 deliverable. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\plans\beacon-v0.2-http-snapshot-rc2-plan-2026-08-10.md` | Freezes the RC2 contract, acceptance matrix, future boundary, and remaining release gates. |
| `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\CHANGELOG.md` | Records the RC2 HTTP surface and release-journey coverage. |

## Verification

- `$env:PYTHONPATH=(Resolve-Path src).Path; python -m pytest -p no:cacheprovider -q` — `PASS` — 611 passed, 9 skipped on Python 3.12.
- `python -m ruff check src tests scripts` — `PASS` — all checks passed.
- `python -m ruff format --check src tests scripts` — `PASS` — 58 files already formatted.
- `C:\tmp\beacon-http-rc2-audit-20260810-2\Scripts\mypy.exe --no-incremental src` — `PASS` — no issues in 34 source files after remediation.
- `C:\tmp\beacon-http-rc2-audit-20260810-2\Scripts\bandit.exe -r src -q` — `PASS` — no security findings; the existing reviewed `B506` nosec annotation was recognized.
- `C:\tmp\beacon-http-rc2-audit-20260810-2\Scripts\validate-pyproject.exe pyproject.toml` — `PASS` — valid project metadata.
- `python scripts/run_mutation_tests.py` — `PASS` — all 4 deliberately broken release-critical mutants were killed.
- `python -m build --outdir C:\tmp\beacon-http-rc2-title-only-build-20260810` — `PASS` — built the title-only-policy RC2 wheel and sdist from the sdist path.
- `python -m twine check C:\tmp\beacon-http-rc2-title-only-build-20260810\*` — `PASS` — wheel and sdist metadata passed.
- `C:\tmp\beacon-http-rc2-audit-20260810-2\Scripts\check-wheel-contents.exe C:\tmp\beacon-http-rc2-title-only-build-20260810\archolith_beacon-0.2.0rc2-py3-none-any.whl` — `PASS` — wheel contents OK.
- `C:\tmp\beacon-http-rc2-audit-20260810-2\Scripts\pip-audit.exe --progress-spinner off --skip-editable` — `PASS` — no known vulnerabilities after updating the disposable environment's seeded pip; unpublished local RC2 was reported as unauditable by package name.
- `python scripts/release_check.py --framework-wheel C:\tmp\beacon-http-rc2-title-only-build-20260810\archolith_mcp_framework-0.2.0-py3-none-any.whl --beacon-wheel C:\tmp\beacon-http-rc2-title-only-build-20260810\archolith_beacon-0.2.0rc2-py3-none-any.whl --workdir C:\tmp\beacon-http-rc2-title-only-journey-20260810` — `PASS` — clean framework-first install, deterministic exports, real loopback HTTP, MCP stdio, and no outbound runtime attempt.
- Live Beacon comparison on `beacon.yaml` — `PASS` — three plan documents retained their titles with zero chunks; snapshot size fell 46.1% in the pre-documentation comparison and the restarted endpoint contains no sampled plan-body phrase.
- Independent DeepSeek hostile audit through harness session `beacon-http-rc2-independent-audit-deepseek-20260810` — `PASS` — no actionable P0-P2 findings; wildcard ETag hardening was applied and regression-tested.
- `py -3.13 -m pytest ...` and `py -3.14 -m pytest ...` — `NOT RUN` — those runtimes are not installed on this machine; the hosted matrix is the gate.
- GitHub Actions 3-by-3 matrix for commits `34368ab` and `3d3db88` — `NOT RUN` — branch not pushed in this implementation turn.
- `python C:\Users\thron\IdeaProjects\projects\ctharvey\cth.agentsmith\scripts\wrapup_validator.py .agent\for-review\WRAPUP-2026-08-10-beacon-v0.2-http-snapshot-rc2.md --repo . --workspace-root C:\Users\thron\IdeaProjects --json` — `PASS` — 0 failures across 14 checks; one warning because the standalone parser treats the comma-separated `Docs Updated` path list as one path.
- `artifact_validate(artifact_type="wrapups", filename="WRAPUP-2026-08-10-beacon-v0.2-http-snapshot-rc2.md")` — `NOT RUN` — the artifact validator is not exposed in this session, so this wrapup cannot honestly be marked `READY FOR REVIEW`.
- Genuinely unaided owner trial against RC2 — `NOT RUN` — explicitly deferred until RC2 publication.

## Claim Cross-Check

- Summary checked against actual code/diff: `yes`
- Files Changed checked against actual modified files: `yes`
- Commit list checked against actual commit hashes or working-tree state: `yes`
- Verification results copied from actual command output: `yes`

## Completion Checklist

- Plan / acceptance criteria completed: `partial` — implementation criteria are complete; hosted matrix, publication, and unaided trial remain release gates.
- Docs updated as required: `yes`
- Changelog updated as required: `yes`
- Work committed: `yes`

## Assumptions

1. RC2 intentionally accepts only the exact IPv4 loopback string `127.0.0.1`; alternate loopback names and IPv6 are deferred until the trust model expands.
2. Local no-auth access is acceptable only because the listener is explicit, loopback-only, read-only, short-lived, and protected by export's publication and secret gates.
3. RC2 serves one startup snapshot by design; refresh, query, question submission, remote trust, and AI-shaped synthesis remain later protocol layers.

## Risks / Gaps

1. Any process on the same host can read the snapshot while `serve-http` is running. Browser JavaScript cannot read it cross-origin because Beacon sends no CORS headers, but local-process isolation is outside RC2.
2. Conditional GET supports `If-None-Match` exact, weak/list, and wildcard matching. Other HTTP preconditions such as `If-Match` and date validators are outside the frozen RC2 contract.
3. Python 3.13/3.14 and hosted Linux/macOS/Windows behavior are not yet proven for these commits.
4. RC2 is not yet tagged or published; docs explicitly label publication as pending.
5. Mechanical wrapup validation is unavailable in this session, which is the direct reason for `PARTIAL` status.
6. The title-only rule currently depends on the document role being `plan` or ending in `_plan`; a mislabeled plan could still be embedded.

## Follow-Up Tasks

1. Push `release/v0.2.0` and require the hosted Python 3.12/3.13/3.14 by Linux/macOS/Windows matrix to pass.
2. Run `artifact_validate` when the workspace-artifacts tool is available and resolve every failure before changing this wrapup to `READY FOR REVIEW`.
3. With explicit release authorization, tag and publish `v0.2.0rc2`, then run the public-index smoke journey.
4. Conduct one genuinely unaided owner/developer trial against the published RC2 before final `0.2.0`.
5. Design explicit private/shared/public exposure profiles and evaluate an offline, cited LLM plan-summary mode before exposing any synthesized plan text.

## Notes

- DeepSeek performed the bounded implementation grunt work and a separate read-only hostile audit. Codex retained architecture, integration, diff review, remediation, release checks, and acceptance responsibility under the updated orchestrated-delegation workflow.
