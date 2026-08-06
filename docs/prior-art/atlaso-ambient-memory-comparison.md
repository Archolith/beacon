# Atlaso Ambient Memory vs Beacon — Prior-Art / Orientation Comparison

**Date:** 2026-08-06  
**Status:** External prior-art note; use for Beacon positioning, Orientation design, provider contracts, context-delivery policy, and benchmark planning.  
**Compared product:** [Atlaso](https://www.atlaso.ai/)  
**Public implementation inspected:** Atlaso's Claude Code, Cursor, Codex, Antigravity, MCP, and CLI repositories.  
**Evidence boundary:** Atlaso's lifecycle integrations and memory rendering are public. Its hosted recall engine, background enrichment, and Ambient Memory composer are closed source.

---

## 1. Executive verdict

Atlaso is direct prior art for Beacon's **automatic session-start Orientation** concept.

Its product promise is nearly the same user-level outcome:

> Start a new agent session already knowing where work was heading, what changed, and what remains unsettled.

Atlaso calls this **Ambient Memory** and describes it as “the back of your mind.” It combines cross-tool memory with automatic session-start context so the user does not need to ask for a recap.

That overlap is important. Beacon should not claim novelty for:

- automatic session-start context
- cross-session continuity
- cross-tool shared memory
- recent/open/next-item orientation
- pushing context before the first user prompt
- conflict-aware memory bullets
- background enrichment into cleaner summaries

The architectural overlap remains bounded.

Atlaso's publicly observable session-start context is primarily:

```text
personal + project memory
-> broad fixed recall query
-> recent-memory fallback
-> project filtering
-> top memory bullets
-> always-applied agent context
```

Its richer Ambient Memory composer is not publicly inspectable.

Beacon's intended direction is broader:

```text
heterogeneous project providers
    purpose / docs / code / Git / decisions / benchmarks / guardrails / memory
-> source, authority, status, freshness, scope, disclosure
-> Views and Semantic Objects
-> consumer-, purpose-, budget-, and policy-aware composition
-> Orientation Adaptive Semantic Object
-> agent handshake with pull affordances
```

The clearest classification is:

> Atlaso productizes one valuable Orientation specialization: memory-first continuity for a returning user. Beacon aims to define the provider-neutral contract and composition model for many kinds of project competence.

Atlaso is therefore stronger Beacon prior art than it is inspectable Menhir prior art.

---

## 2. Two Atlaso context products must be distinguished

Atlaso exposes two related but different context surfaces.

### 2.1 Automatic recalled-memory block

The public connectors retrieve memory and inject it into the host tool.

Depending on the host:

- Claude Code can recall before each user prompt.
- Cursor writes a session-start `alwaysApply` rules file.
- other tool connectors use their available lifecycle hooks.

This surface is publicly inspectable.

### 2.2 Ambient Memory

Atlaso's paid product advertises a richer session-start brief containing signals such as:

```text
recurring topic
next action
recent changes
open question
current direction
unsettled conflict
```

This is closer to Beacon's Orientation object.

The public clients contain integration hooks and rendering support for “Atlaso Orientation,” but the code that chooses, groups, compresses, and phrases the Ambient Memory content is hosted and not open source.

The comparison must not use the simple public recall block as proof of the full Ambient Memory architecture.

---

## 3. Observable session-start pipeline

The public Cursor integration reveals the clearest concrete path.

```text
sessionStart event
-> determine workspace and project key
-> verify tool entitlement/credential
-> query hosted recall
-> fetch recent memories as fallback
-> remove duplicates
-> filter project visibility
-> render bullets and conflict markers
-> write .cursor/rules/atlaso-recall.mdc
-> rules engine injects it as alwaysApply context
```

### 3.1 Fixed broad seed

Because Cursor's session-start event has no task prompt, Atlaso uses the broad seed:

```text
recent work decisions preferences conventions gotchas project setup
```

It requests up to eight recalled memories.

If recall returns too few, it fetches recent deposits, over-fetches before project filtering, deduplicates by content, and fills the remaining slots.

This is a practical solution to a missing user query, but it is not deeply consumer- or purpose-aware.

### 3.2 Project visibility

The client ensures that:

- personal memory may follow the user
- project memory appears only in the matching repository
- recent-memory fallback applies the same visibility rule as server recall

This is important Orientation hygiene. A context system that leaks another project's state at session start destroys trust immediately.

### 3.3 Conflict rendering

A recalled bullet can be rendered as:

```text
[conflict] <memory> (conflicts with N other notes) [scope]
```

This gives the model a compact uncertainty signal.

It does not provide:

- the conflicting source content by default
- the reason the memories are considered peers
- current-versus-historical status
- exact source citations
- the reconciliation rule

### 3.4 Injection channel

Cursor's native session-start context channel was considered unreliable, so Atlaso writes an `alwaysApply` rules file into the workspace.

This demonstrates a useful product principle:

> Orientation needs a delivery mechanism the host actually honors, not only a clean abstract API.

It also introduces risks discussed later: persistent injection, repository-file mutation, and memory content entering a high-authority rules channel.

### 3.5 Fail-open behavior

Atlaso treats memory as best-effort:

- recall is timeout-bounded
- hook errors return no memory rather than blocking the session
- failures are generally silent
- the underlying agent remains usable

Beacon should preserve host safety while making missing or stale Orientation observable when appropriate.

---

## 4. Mapping Atlaso to Beacon's object model

| Atlaso construct | Beacon interpretation | Limitation |
|---|---|---|
| Raw captured exchange | Durable source/evidence from one provider | Not itself a curated project Semantic Object |
| Enriched memory | Derived Semantic Object candidate | Derivation, identity, and source relationship are closed |
| Personal/project scope | Provider scope metadata | Coarser than purpose, audience, authority, and disclosure policy |
| Recalled memory result | View over hosted memory | Mostly row-shaped; limited source/status envelope |
| Conflict marker | Compact epistemic status | Does not expose reconciliation receipt |
| Session-start memory bullets | Orientation fragment | Fixed memory-first selection, not a complete project Orientation |
| Ambient Memory brief | Orientation-like Adaptive Semantic Object | Consumer/purpose/budget/composition inputs are not public |
| `recall` tool | Pull context capability | Memory-specific, not a general project-understanding contract |
| Cross-tool account memory | Shared provider substrate | Product-controlled hosted service, not provider-neutral |

### 4.1 Is Ambient Memory an Adaptive Semantic Object?

At the product level, it is close.

It appears to be:

- derived rather than raw
- selected for a session
- composed from several memories
- intended to orient a consumer
- aware of recency and unresolved state

However, the public evidence does not establish the full Beacon input contract:

```text
target
consumer identity/capability
purpose or task
context budget
disclosure profile
composition policy
provider set
```

The public Cursor path has no task hint and uses a fixed broad seed. The hosted Ambient Memory path may be richer, but its inputs and policy are closed.

The conservative classification is:

> Ambient Memory is direct product prior art for Orientation and a likely narrow Adaptive Semantic Object, but its composition semantics cannot be audited.

---

## 5. Direct overlap with Beacon

### 5.1 Cold-start orientation

Both products reject the default agent workflow:

```text
open repo
-> start from zero
-> repeatedly scan README/docs/history
-> rediscover current work
```

Both aim for:

```text
session begins
-> relevant understanding already present
-> consumer can act sooner
```

### 5.2 Push before pull

Atlaso pushes memory automatically before the consumer asks.

Beacon's Orientation specialization makes the same bet:

> An unfamiliar consumer cannot reliably request context it does not yet know exists.

Atlaso validates that a push layer is useful. It does not prove that all useful context should be pushed.

### 5.3 Cross-tool continuity

Atlaso's memory belongs to the account/project rather than one model or host application.

Beacon similarly should remain independent of:

- Claude Code
- Cursor
- Codex
- one MCP client
- one model family

### 5.4 Scope-aware composition

Atlaso distinguishes personal and project memory and filters at session start.

Beacon needs the same baseline plus richer axes:

```text
project
repository/worktree
consumer role
task purpose
source authority
sensitivity/disclosure
current/historical mode
```

### 5.5 Uncertainty in context

Atlaso does not present every memory as equally reliable. Conflict flags and claimed thin/settled/contested verdicts are strong prior art for compact epistemic metadata in Orientation.

### 5.6 Background preparation

Atlaso advertises nightly enrichment and cached Ambient Memory. This supports a useful Beacon separation:

```text
background derivation/precomputation
    prepare reusable project Semantic Objects

request-time composition
    select and assemble an Orientation for this consumer/purpose
```

---

## 6. Where Atlaso is ahead of Beacon today

### 6.1 Shipping cross-tool integrations

Atlaso publishes maintained connectors for multiple coding-agent hosts and a remote MCP server.

Beacon has a clean provider abstraction but a much smaller deployed integration footprint.

### 6.2 Automatic lifecycle wiring

Atlaso already handles:

- session start
- before-prompt recall
- after-turn capture
- session-end sync
- tool-specific lifecycle differences
- timeout and failure behavior

This operational work is easy to underestimate and directly affects whether Orientation is actually delivered.

### 6.3 Durable cross-device state

Atlaso has a coherent cloud product around:

- account memory
- device/tool credentials
- synchronization
- local write-ahead queues
- project isolation
- dashboard management

Beacon currently defines a project-understanding surface, not a complete user-memory service.

### 6.4 Returning-user continuity

Atlaso is optimized for a user who returns to ongoing work and wants immediate continuity.

Beacon's original v0 was more project self-description than longitudinal work-state continuity. The Adaptive Semantic Object/Orientation direction closes that gap conceptually but is not yet shipped.

### 6.5 User-facing confidence language

`thin`, `settled`, and `contested` are understandable consumption labels.

Beacon's source/status/confidence envelope should preserve rigor while offering similarly usable summaries.

---

## 7. Where Beacon remains materially different

### 7.1 Beacon is a project-understanding contract

Atlaso is a hosted memory product.

Beacon separates:

```text
client-facing protocol
provider implementations
knowledge substrates
normalization
composition policy
output object
```

A Beacon client should receive the same class of answers whether the provider is:

- a static project manifest
- canonical docs
- a Graft-like code graph
- Git history
- decisions/issues
- Atlaso-like memory
- Menhir
- another knowledge system

### 7.2 Beacon is not memory-only

A strong project Orientation may need:

```text
what the project is
current architecture
relevant files and symbols
maintainer-defined guardrails
current decisions
known failure modes
required commands/checks
recent changes
open work
consumer-specific next steps
```

Atlaso's center is personal/project conversational memory. Even a perfect memory recap is not necessarily sufficient Orientation for an unfamiliar coding agent.

### 7.3 Beacon distinguishes declared intent from observed reality

Atlaso primarily composes from remembered work.

Beacon can preserve distinct source classes:

```text
maintainer-declared intent
current code reality
historical decision
benchmark result
agent memory
unresolved disagreement
```

The composer can present disagreement rather than flattening it.

### 7.4 Beacon is purpose-aware

The same repository needs different context for:

- onboarding
- a bug fix
- a security audit
- a migration
- documentation work
- release preparation
- architecture review

Atlaso's public session-start path uses a broad generic seed because the task is unknown.

Beacon's agent handshake should support both:

```text
purpose unknown
    minimum safe general Orientation

purpose known
    task-shaped Orientation
```

### 7.5 Beacon is consumer-aware

A local small model and a frontier model should not receive the same pack.

Nor should a new contributor and a maintainer.

Beacon's Adaptive Semantic Object inputs explicitly include the consumer, while Atlaso's public context shape is mostly host- and project-aware.

### 7.6 Beacon is budget- and disclosure-aware

Atlaso scopes personal/project visibility, but its public composition contract does not expose:

- token/context budget
- sensitivity classification
- omitted-by-policy status
- omitted-by-budget status
- disclosure rationale

These matter when Orientation becomes infrastructure rather than a single-user product feature.

### 7.7 Beacon should be source-grounded

Atlaso's public bullets contain memory content and conflict count, but not necessarily exact source citations.

Beacon's stronger contract should attach:

```text
source type
source identity
path/line or event pointer
status
freshness
authority
why included
```

### 7.8 Beacon supports pull after push

Atlaso's automatic memory is pushed, with explicit recall tools available separately.

Beacon should make the relationship explicit:

```text
initial Orientation
    minimum understanding required now

expansion affordances
    exact tools/resources for deeper evidence
```

The Orientation should tell the consumer what it does not contain and how to retrieve it.

---

## 8. Important product and security lessons

### 8.1 The first context must be trustworthy

Session-start context has disproportionate influence because it frames everything that follows.

A stale or poisoned Orientation can be worse than no Orientation.

Beacon should treat session-start context as a governed output with:

- freshness receipt
- source provenance
- conflict state
- disclosure policy
- injection safety
- deterministic escaping

### 8.2 Do not place untrusted memory in an instruction channel without labeling

Atlaso's Cursor renderer writes recalled memory into an `alwaysApply` rules file. The public code sanitizes frontmatter and Atlaso fence strings, but deliberately presents a plain branded block with no “untrusted data” warning or instruction boundary.

This can improve model uptake, but it raises a context-poisoning concern:

```text
stored memory content
-> high-authority always-applied rules channel
-> model may interpret data as instruction
```

Beacon should keep a hard distinction between:

```text
project instructions/guardrails
retrieved evidence or memory
composer commentary
```

Each should have a typed envelope even if the host ultimately receives Markdown.

### 8.3 Host adapters are part of the product

Atlaso's workaround for Cursor demonstrates that a theoretically correct context API is insufficient when the host ignores it.

Beacon needs tested host adapters and delivery receipts:

```text
Orientation composed
Orientation delivered
host accepted/injected it
consumer had access to it
```

### 8.4 Fail-open must not mean invisible degradation

A memory outage should not block work, but users and benchmarks still need to know whether Orientation was omitted.

Recommended Beacon status:

```text
complete
partial
stale
unavailable
omitted by policy
omitted by budget
```

### 8.5 Cache the expensive composition, validate freshness cheaply

Atlaso prepares background enrichment and session-start material before the user needs it.

Beacon should distinguish:

```text
reusable derived objects
    computed in background and versioned

final Orientation
    composed cheaply at handshake using current inputs
```

---

## 9. What Beacon should borrow

### 9.1 Lifecycle-first delivery

Define a cross-host lifecycle contract:

```text
session_start
before_prompt
after_turn
session_end
project_changed
tool_disconnected
```

Each adapter maps host-specific events to that contract.

### 9.2 Automatic minimum Orientation

A consumer should not need to know the name of the onboarding tool before receiving enough context to use it.

At session start, push a bounded minimum object and expose pull expansion.

### 9.3 Scope parity across all fallback paths

Atlaso fixed project leaks caused by applying scope filtering to primary recall but not recent-memory fallback.

Beacon invariant:

> Every provider, cache, fallback, and expansion path applies the same disclosure and scope policy.

### 9.4 Compact epistemic verdicts

Include a human/model-readable status such as:

```text
settled
contested
thin
historical
stale
unknown
```

Back it with source receipts.

### 9.5 Durable context-delivery telemetry

Measure:

- Orientation requested
- composed
- freshness checked
- delivered
- injected
- expanded
- ignored or unused
- task outcome

### 9.6 Cross-tool shared context substrate

Do not let project understanding become trapped in one IDE plugin.

Beacon should expose the same contract through:

- MCP
- CLI
- direct library/API
- host hooks

### 9.7 Background enrichment with immutable lineage

Atlaso's raw-to-enriched direction is useful. Beacon should preserve:

```text
raw source
-> derived Semantic Object
-> composition contribution
```

A generated summary must not erase its lineage.

### 9.8 Idempotent, durable sync for remote providers

When Beacon consumes hosted memory or project state, use Atlaso's operational pattern:

- local durable outbox for writes
- deterministic idempotency
- retry/quarantine
- per-tool credentials
- fail-open reads

---

## 10. What Beacon should not copy directly

### 10.1 Do not use one generic query as the Orientation policy

The seed:

```text
recent work decisions preferences conventions gotchas project setup
```

is a good fallback, not a complete composition model.

It cannot know whether the consumer needs:

- auth architecture
- a failing benchmark
- a release checklist
- a migration dependency
- a privacy restriction

### 10.2 Do not equate “recent” with “important now”

Recent deposits are a useful fallback. They can also crowd out stable load-bearing context.

Composition should balance:

```text
purpose relevance
safety relevance
current work
canonical project understanding
recent change
open uncertainty
```

### 10.3 Do not make memory bullets the only Orientation form

Different information benefits from different typed structures:

```text
read order
file map
decision summary
guardrail list
risk table
open questions
commands
source citations
```

A flat bullet list is a rendering, not the semantic object.

### 10.4 Do not hide composition behind a proprietary service boundary

Beacon should keep provider internals pluggable, but the final composition contract and receipts should remain inspectable.

### 10.5 Do not silently omit context on failure

Fail open at the host boundary, but record and optionally surface that the Orientation is unavailable or partial.

### 10.6 Do not mix recalled data with normative instructions

Guardrails and memory should be separately typed and rendered with clear authority boundaries.

### 10.7 Do not optimize only returning-user continuity

Atlaso's strongest use case is “pick up where I left off.”

Beacon must also orient:

- a completely unfamiliar contributor
- a different model
- an external reviewer
- an agent entering a project for the first time

---

## 11. Benchmark implications

Atlaso's LongMemEval benchmark evaluates question-triggered memory retrieval and QA. It does **not** validate Ambient Memory's session-start Orientation quality.

Beacon needs a different benchmark target:

> How quickly and reliably does the supplied context make the consumer competent to act?

### 11.1 Recommended arms

| Arm | Initial context | Pull capability |
|---|---|---|
| Cold | ordinary repository files only | normal file/tools |
| Recent-only | latest project memories | memory recall |
| Atlaso-like generic | broad fixed-seed memory bullets | memory recall |
| Static Beacon | manifest/docs onboarding | Beacon tools |
| Graft-like structural | current code map/context pack | code tools |
| Beacon Orientation | project-general composed object | Beacon expansion |
| Task-shaped Beacon | purpose-specific Orientation | Beacon expansion |
| Menhir-backed Beacon | Orientation with current decisions/history/failures | temporal/evidence tools |
| Adaptive Beacon | consumer/purpose/budget-aware minimum push | dynamic pull affordances |

### 11.2 Time-to-Competence metrics

Measure:

```text
time to first correct project model
time to first correct plan
time to identify relevant files
time to identify required checks
time to surface a load-bearing guardrail
time to distinguish current from superseded guidance
```

### 11.3 Context-quality metrics

Measure:

```text
required-knowledge recall
irrelevant-context rate
stale-context rate
false settled rate
conflict visibility
source citation correctness
unsafe instruction uptake
cross-project leakage
omission honesty
```

### 11.4 Outcome metrics

Measure:

```text
task success
regression rate
unsafe first actions
plan revisions
exploratory reads
tool calls
tokens
cost
latency
```

### 11.5 Push/pull/adaptive comparison

Atlaso reinforces the need for three distinct delivery modes:

```text
push
    initial context injected automatically

pull
    consumer requests project knowledge

adaptive
    minimum safe push + explicit expansion based on need
```

The adaptive arm should beat both extremes:

- less irrelevant context than full push
- fewer blind spots than pull-only

---

## 12. Recommended adversarial fixtures

### 12.1 Returning maintainer

A maintainer resumes work after several days.

Required context:

- where work stopped
- recent decision
- open blocker
- next safe action

Atlaso-like memory should be strong here.

### 12.2 First-time contributor

The consumer has no personal memory history.

Required context:

- project purpose
- architecture
- read order
- safe task
- guardrails

This exposes the limitation of memory-only Orientation.

### 12.3 Stale recent work

The most recent conversation pursued an approach later rejected in a decision document.

The Orientation must prefer the current decision while preserving the abandoned attempt as history.

### 12.4 Cross-project collision

Two repos use the same component names but different conventions.

No project memory may leak between them; personal preferences may still appear when appropriate.

### 12.5 Prompt-injection memory

A stored memory contains text resembling host instructions.

Expected behavior:

- rendered as data/evidence
- never promoted to a guardrail solely because of wording
- source and authority visible

### 12.6 Unknown task at session start

No task hint is available.

Compare:

- broad fixed seed
- recent-only
- minimum project Orientation
- adaptive handshake that asks or waits for purpose

### 12.7 Small-context consumer

The same project is opened by a local 8K model and a large-context frontier model.

The resulting Orientation should differ in size, compression, and pull affordances.

### 12.8 Contested current direction

Recent memories disagree about the next step.

The Orientation must not present one as settled without a receipt.

---

## 13. Implications for Beacon contracts

Atlaso suggests several additions to a future Orientation contract.

### 13.1 Orientation status envelope

```json
{
  "status": "complete | partial | stale | unavailable",
  "freshness_checked_at": "...",
  "source_revision": "...",
  "omissions": [],
  "warnings": []
}
```

### 13.2 Typed sections

```text
project_summary
current_direction
recent_changes
open_questions
relevant_concepts
relevant_files
current_decisions
guardrails
safe_first_steps
suggested_next_action
expansion_affordances
```

### 13.3 Per-item epistemic envelope

```json
{
  "content": "...",
  "status": "settled | contested | thin | historical | stale",
  "source_type": "memory | code | doc | decision | benchmark",
  "sources": [],
  "why_included": "..."
}
```

### 13.4 Composition receipt

```text
consumer
purpose
budget
disclosure profile
providers consulted
providers unavailable
policy used
items omitted by budget
items omitted by policy
```

This is the main architectural step beyond Atlaso's product-facing recap.

---

## 14. Positioning discipline

### Claims Beacon should avoid

- “The first session-start context for AI agents.”
- “The first system that lets agents pick up where they left off.”
- “The first cross-tool memory Orientation.”
- “The first automatic recap before the first prompt.”
- “The first conflict-aware ambient context.”

Atlaso already occupies those product claims.

### Stronger Beacon positioning

> Atlaso gives a returning user memory continuity across tools. Beacon is the provider-neutral project-understanding contract and composition layer that can combine memory with code, decisions, guardrails, Git, benchmarks, and documentation to orient a particular consumer for a particular purpose.

### Short contrast

> Atlaso remembers where you left off. Beacon composes what this agent needs to understand now.

### Architecture contrast

> Ambient Memory is one valuable Orientation provider and policy. Beacon defines the interoperable object, evidence envelope, and adaptive composition boundary.

---

## 15. Recommended next experiment

Run a small task-outcome study before expanding the Beacon schema further.

### Repositories

- one unfamiliar library
- one active multi-package project with decisions and guardrails

### Tasks

- first-time contribution
- returning-session continuation
- bug fix with a known prior failed attempt
- change governed by a non-code constraint

### Arms

```text
cold
recent memory only
Atlaso-like fixed-seed memory Orientation
static Beacon onboarding
Graft structural pack
Beacon + Graft
Menhir-backed Beacon
adaptive Beacon push/pull
```

### Promotion criterion

Beacon earns additional composition machinery only if it improves at least one outcome beyond memory-only and code-only baselines:

```text
lower Time-to-Competence
higher plan correctness
better guardrail recall
fewer unsafe first actions
fewer plan revisions
better task success per context token
```

---

## 16. Final classification

```text
Atlaso automatic recall
    memory-specific View injected through host lifecycle hooks

Atlaso Ambient Memory
    closed, session-start Orientation-like composition over personal/project memory

Beacon v0
    provider-neutral project-understanding MCP contract

Beacon context direction
    Views + Semantic Objects
    Adaptive Semantic Objects composed for consumer, purpose, disclosure, and budget
    Orientation minimizes Time-to-Competence

Menhir
    optional provider for current/historical knowledge, decisions, evidence,
    contradictions, prior failures, and cross-source state
```

The durable conclusion is:

> Atlaso validates automatic pushed Orientation and cross-tool continuity. Beacon must differentiate through interoperability, heterogeneous providers, evidence/source receipts, authority boundaries, and adaptive composition—not merely by producing a session-start recap.

---

## Sources

- Atlaso product and Ambient Memory description: <https://www.atlaso.ai/>
- Atlaso LongMemEval-S study: <https://www.atlaso.ai/research/memory-benchmark>
- Hosted MCP contract: <https://github.com/atlaso-labs/mcp>
- Claude Code connector: <https://github.com/atlaso-labs/claude-code>
- Cursor connector: <https://github.com/atlaso-labs/cursor>
- Cursor session-start recall pipeline: <https://github.com/atlaso-labs/cursor/blob/main/hooks/recall.ts>
- Cursor memory/conflict rendering: <https://github.com/atlaso-labs/cursor/blob/main/lib/render.ts>
- Cursor hosted client and recall result contract: <https://github.com/atlaso-labs/cursor/blob/main/lib/atlaso.ts>
- Cursor capture/scope/secret-scrub implementation: <https://github.com/atlaso-labs/cursor/blob/main/lib/capture.ts>
