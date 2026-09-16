# beacon — Agent Docs

Read everything in this directory before starting work.

## Files

| File | Purpose |
|------|---------|
| `architecture.md` | System design, data flow, tech stack, config/env reference |
| `data_models.md` | Entities, DTOs, enums, converters, repository reference |
| `CHANGELOG.md` | Running log of changes, most recent first |
| `workflows/code_conventions.md` | Language-specific style and formatting rules |
| `plans/beacon-v0.2-plan-2026-09-15.md` | The v0.2 release plan: maintainer journey, locked decisions, normative limits/validation/secret/privacy policy, schemas, work packages, merge order, and release gate |
| `plans/beacon-build-pipeline-and-source-adapters-plan-2026-09-15.md` | Draft plan for `beacon build`, multi-source adapters, merge precedence, and optional LLM drafting (v0.3) |
| `plans/beacon-multi-intent-beacons-plan-2026-09-15.md` | Draft plan for serving several intent-scoped beacons from one project |
| `plans/beacon-trust-hub-and-federation-plan-2026-08-09.md` | Approved hybrid Archolith Hub, self-hosting, trust handshake, private access, and federation plan |

## Maintenance Rules

- Update `data_models.md` when any entity, DTO, or enum changes.
- Update `architecture.md` when adding services, integrations, or structural changes.
- Update the relevant workflow file when operational behavior changes.
- Add a `CHANGELOG.md` entry at the end of every session with meaningful changes.
  Format: `## YYYY-MM-DD — <short description>` with bullet points per file changed.
- Push to git regularly — at minimum at the end of each working session.
- Use conventional commit messages: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`.
- Only commit files worked on this session. Run `git diff --name-only` and `git status` before staging. Add files explicitly by path — never `git add .` or `git add -A`.
