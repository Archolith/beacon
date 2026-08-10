# Beacon v0.2 HTTP-only orientation trial — 2026-08-10

## Boundary

- Input: `GET http://127.0.0.1:8765/v1/snapshot`
- Snapshot: `beacon_snapshot_version=1.0`, generator `archolith-beacon 0.2.0rc2`
- Snapshot size observed by the consumer: approximately 91 KB
- MCP access: none
- Repository-file access: none during orientation
- Source report: `C:\Users\thron\.codex\attachments\2c534e18-3fd7-4aa3-8954-215a40694c82\pasted-text.txt`
- Gate status: this is product evidence, not the required unaided developer trial. It did not test
  public-index installation, manifest creation, validation repair, or MCP client setup.

## Result

The consumer built an accurate high-level account of Beacon's purpose, four-layer architecture,
five tools, provider boundary, deterministic v0 behavior, RC2 release state, and product roadmap
from the snapshot alone. Per-document role, status, digest, heading path, and line ranges made the
corpus self-describing and citation-ready. Plan privacy also behaved as intended: all three
plan-role documents retained identity metadata and exposed no chunks.

The HTTP link worked well as an orientation and evaluation surface. It did not reproduce MCP's
answer behavior. The consumer pulled the full snapshot and made four ad-hoc analysis passes to
enumerate structure, inspect the manifest, choose headings, and read selected bodies. Roughly
45–50 KB of document text entered context for a general orientation question. Task-scoping inputs
such as `task_hint`, `source_types`, and `limit` have no expression in the static HTTP contract.

## Findings

1. `C:\Users\thron\IdeaProjects\.agent\worktrees\beacon-v0.2-wp0\.agent\architecture.md`
   still named RC1 while the generator and README named RC2.
2. The architecture configuration table documented all runtime environment variables, while the
   README table omitted `BEACON_HOST`, `BEACON_PORT`, and the six `BEACON_MAX_*` ceilings.
3. Snapshot validation correctly reported zero structural errors and warnings but cannot establish
   semantic freshness. The version drift is concrete evidence for the roadmap's stale-citation
   diagnostics.
4. With plan bodies withheld, the HTTP snapshot is deliberately weaker than private MCP search for
   implementation commitments and rationale.

## Actions taken

1. Updated architecture release state from RC1 to RC2 and corrected stale framework/init wording.
2. Expanded the README configuration table to match the twelve environment variables implemented
   by runtime settings, logging, and resource-limit loading.
3. Updated the unaided-trial brief from RC1 to RC2 without claiming this HTTP-only exercise passed
   that gate.
4. Kept HTTP query/ranking and guarded LLM summarization as future work. RC2 remains a static,
   immutable snapshot surface.

## Product framing

The trial supports a precise distinction: `/v1/snapshot` is a strong low-dependency orientation,
evaluation, and fallback surface; MCP remains the task-scoped answer surface. The HTTP snapshot can
sell and explain the project. The MCP tools do the repo-specific work.
