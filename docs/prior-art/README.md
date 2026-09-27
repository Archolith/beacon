# Prior art

External systems compared with Beacon, for positioning, contract design and benchmark
planning. Each note is dated. It describes the other product as inspected on that date and
Beacon as it was then, so check "Beacon today" statements against
[`../design-principles.md`](../design-principles.md) and the current code.

| Note | Date | Compared | One-line verdict |
|---|---|---|---|
| [Graft](graft-beacon-context-comparison.md) | 2026-08-05 | Graft, a current-code context engine (symbol graph, ranking, bounded context packs) | Strongest prior art for code orientation and context efficiency. A specialized provider and a benchmark baseline, not a replacement for the Beacon contract. |
| [Atlaso](atlaso-ambient-memory-comparison.md) | 2026-08-06 | Atlaso Ambient Memory, session-start recall for coding agents | Direct prior art for automatic session-start orientation and cross-session continuity, so Beacon claims no novelty there. The overlap is bounded: Atlaso recalls memory bullets, while Beacon composes heterogeneous project sources with authority and freshness. |

Both notes list what Beacon should borrow, what it should not copy, and adversarial fixtures
for benchmarks. They were carried over verbatim from PRs #2 and #3.
