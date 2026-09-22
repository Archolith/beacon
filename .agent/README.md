# beacon — Agent Docs

This file is a router. Read it, then only the files your task needs; do not preload the rest.

## Where to start

| Task | Read |
|------|------|
| Any code change | `workflows/code_conventions.md`, then the code itself |
| Build pipeline (`beacon build`, sources, requirements catalogue) | the module docstrings in `src/beacon/build/` and `src/beacon/sources/`; the active plan in the root workspace `.agent/plans/beacon-ownership-and-expansion-plan-2026-09-22.md` |
| Manifest schema, loader, validator | `data_models.md` |
| MCP / HTTP serving | `architecture.md` |
| Release or packaging | `plans/beacon-v0.2-publishable-static-product-plan-2026-08-09.md` |

`for-review/`, `reports/` and older plans are history: read them only when a task points to them.

## Files

| File | Purpose |
|------|---------|
| `architecture.md` | System design, data flow, tech stack, config/env reference |
| `data_models.md` | Entities, DTOs, enums, converters, repository reference |
| `CHANGELOG.md` | Running log of changes, most recent first |
| `workflows/code_conventions.md` | Language-specific style and formatting rules |
| `plans/beacon-v0.2-publishable-static-product-plan-2026-08-09.md` | Executable plan for initialization, export, examples, packaging, and the v0.2 release gate |
| `plans/beacon-v0.2-implementation-readiness-addendum-2026-08-09.md` | Normative MCP baseline, limits, validation/secret/privacy policy, schemas, and release sequence for v0.2 |
| `plans/beacon-trust-hub-and-federation-plan-2026-08-09.md` | Approved hybrid Archolith Hub, self-hosting, trust handshake, private access, and federation plan |

## Maintenance Rules

- Update `data_models.md` when any entity, DTO, or enum changes.
- Update `architecture.md` when adding services, integrations, or structural changes.
- Update the relevant workflow file when operational behavior changes.
- Update `project_state` in `beacon.yaml` at task closeout when active work, recent completions,
  blockers, pending decisions, or the next step changed. Omission is allowed only when the task is
  proven `not_affected`; unresolved semantic state is `needs_review`.
- Add a `CHANGELOG.md` entry at the end of every session with meaningful changes.
  Format: `## YYYY-MM-DD — <short description>` with bullet points per file changed.
- Push to git regularly — at minimum at the end of each working session.
- Use conventional commit messages: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`.
- Only commit files worked on this session. Run `git diff --name-only` and `git status` before staging. Add files explicitly by path — never `git add .` or `git add -A`.
