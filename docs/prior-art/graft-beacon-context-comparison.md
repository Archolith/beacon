# Graft vs Beacon — Prior-Art / Context-Composition Comparison

**Date:** 2026-08-05  
**Status:** External prior-art note; use for Beacon positioning, provider design, context-composition research, and benchmark planning.  
**Compared project:** [`NanoNets/Graft`](https://github.com/NanoNets/Graft)  
**Analyzed public state:** Graft `v0.8.2`; README through commit `c2cc532999b63330054dd255b1e89f670eaf43f4`, implementation inspected at `03faecb1d4f846f4426783ca56fe5d30666f99f6`.  
**Primary question:** Does Graft collapse Beacon's project-orientation/context layer, and which Graft mechanisms should Beacon adopt, integrate, benchmark against, or explicitly distinguish itself from?

---

## 1. Executive verdict

Graft is the strongest prior art reviewed so far for Beacon's **codebase-orientation** and **context-efficiency** lanes.

It is not a general project-knowledge contract, a longitudinal project-memory system, or a complete implementation of Beacon's newer context-composition direction. It is a focused current-code context engine:

```text
current source tree
-> deterministic symbol graph
-> optional LLM meaning layer
-> lexical + structural ranking
-> bounded source-grounded context pack
-> coding agent
```

Beacon's intended scope is broader:

```text
project knowledge providers
    manifest / docs / code / Git / decisions / benchmarks / memories
-> status, authority, freshness, provenance
-> Semantic Objects and Views
-> consumer-, purpose-, and budget-aware composition
-> Orientation or another Adaptive Semantic Object
-> agent handshake / task context
```

The overlap is substantial but bounded:

```text
code orientation overlap:              high
project-introspection contract overlap: medium
context-pack composition overlap:       medium
cross-source/temporal knowledge overlap: low
whole Beacon architecture overlap:      approximately 35–45%
```

The clearest classification is:

> Graft is a strong specialized provider and benchmark baseline for Beacon, not a replacement for the Beacon contract or its broader context-composition model.

Graft proves that a project map can materially reduce exploration cost and improve coding outcomes. Beacon must not claim novelty for that general result. Beacon's remaining differentiation must be demonstrated in the layers Graft does not attempt:

- provider-neutral project introspection
- cross-source status and authority
- current-versus-historical project understanding
- decisions, guardrails, constraints, and prior failures
- consumer- and purpose-aware composition
- disclosure and context-budget policy
- explicit Time-to-Competence optimization
- consistent contracts across static, structural, and Menhir-backed providers

---

## 2. Scope of this note

This document evaluates Graft against two related Beacon frames.

### 2.1 Beacon v0: the project-understanding handshake

Beacon v0 exposes a small MCP surface:

- `beacon_project_overview`
- `beacon_agent_onboarding`
- `beacon_search`
- `beacon_explain_concept`
- `beacon_guardrails`

The v0 architecture is provider-neutral. A deterministic manifest/docs provider establishes the low floor; richer providers can later use code structure, Git, decisions, benchmarks, or Menhir.

### 2.2 Beacon as the context-composition project

The broader architecture distinguishes:

```text
Views
    typed informational or calculated results

Semantic Objects
    typed, identity-bearing, compositional knowledge objects

Adaptive Semantic Objects
    derived Semantic Objects composed for a consumer, purpose,
    disclosure profile, context budget, and composition policy
```

The product objective is to reduce **Time-to-Competence**.

An **Orientation Semantic Object** is the cold-start specialization: it composes the minimum understanding an unfamiliar consumer needs to act safely and productively.

Graft is relevant to both frames:

- as prior art for a project-understanding provider
- as prior art for one narrow kind of task-specific context composition

It is not prior art for Menhir's evidence-to-belief memory architecture except where Beacon consumes Menhir as a provider.

---

## 3. What Graft actually is

Graft creates two related graph surfaces from a software repository.

### 3.1 Tier 1: deterministic structural graph

Tree-sitter parses the source tree into path-scoped code-symbol nodes.

Representative node identity:

```text
src/cache.ts#Cache.get
```

Node kinds include:

```text
file
class
function
method
interface
type
enum
struct
```

Relationship kinds include:

```text
contains
calls
imports
references
implements
extends
```

Each structural node carries fields such as:

```text
path
source span
signature
export status
body hash
optional searchable body text
```

This layer is deterministic, content-addressed, and regenerable. It requires no model and no network.

### 3.2 Tier 2: cached meaning layer

An optional model pass adds:

```text
summary
crux excerpt
summary state: pending | ready | stale
```

The meaning layer is cached by the symbol's body hash. Unchanged definitions retain their paid-for summaries; changed definitions are eligible for regeneration.

Graft also produces higher-level linked Markdown nodes describing systems, APIs, and concepts. Those nodes record source paths and hashes, generated prose, typed links, and a separately preserved human-notes region.

### 3.3 Retrieval and context packing

`graft ask` routes between two modes.

Structural query shapes such as:

```text
who calls X?
what does X import?
what depends on X?
```

resolve a symbol and traverse code-graph edges.

Other questions use a lexical pipeline over concept and symbol fields:

```text
query tokenization
-> IDF/BM25-style lexical scoring
-> lexical seeds
-> personalized PageRank over the code graph
-> fused ranking
-> bounded context pack
```

The implementation describes this as:

> Lexical proposes, graph disposes.

The result can include:

```text
plain-English explanation
exact file:line pointer
related symbols
bounded source span
estimated source-read savings
```

Graft v1 retrieval is deterministic and uses no embeddings.

### 3.4 Freshness model

Before serving a query, Graft checks the current source tree against its stored fingerprint. If code changed, it performs a cheap structural refresh.

The rebuild:

- reads and hashes current source files
- reuses cached parse results for unchanged files
- reparses changed files
- resolves edges over the resulting graph
- reuses LLM summaries when body hashes remain unchanged
- rewrites the current graph projection

This is a **current-state regeneration model**, not a historical event model.

### 3.5 Storage model

The generated `graft/` directory is a local, regenerable cache. It contains:

```text
linked Markdown cards
graph JSON
ask index
fingerprints and caches
```

The current implementation adds the generated graph directory to `.gitignore` while keeping it greppable through an `.ignore` rule. Agent wiring can be committed; each checkout rebuilds its own graph.

This matters for comparison: Graft's graph is not its canonical long-term project memory. The source tree is canonical; Graft is a projection.

---

## 4. Mapping Graft to Beacon's object model

| Graft construct | Beacon interpretation | Important limitation |
|---|---|---|
| Source file / definition text | Durable source reality | Code is only one project-knowledge source |
| Path-scoped symbol node | Derived Semantic Object anchored to code | Identity follows path/symbol shape and may not preserve conceptual continuity across moves/renames |
| LLM summary and crux | Derived explanatory projection | Not independently authority-governed; correctness inherits source and summarizer quality |
| Higher-level Markdown concept node | Derived Semantic Object | Generated grouping may change between builds; no broader decision or history semantics |
| Structural edge | Deterministic or inferred relation | Confidence is coarse (`extracted` or `inferred`), not a complete evidence model |
| `graft ask` result | Task-specific View / context pack | Query-aware, but not explicitly consumer-, disclosure-, or policy-aware |
| Pushed graph bundle | Static/pushed Orientation candidate | Risks over-injection and assumes one orientation shape fits the consumer |
| Pull tools | On-demand project-understanding provider | Agent must know when and what to ask |
| Query-time refresh | Freshness enforcement for a derived projection | Replaces current projection; does not expose historical project understanding |
| Token-savings ledger | Context-efficiency telemetry | Does not by itself measure Time-to-Competence or decision quality |

### 4.1 Why `graft ask` is not yet an Adaptive Semantic Object

It is tempting to call every query-specific context pack adaptive. That would weaken the term.

Graft adapts to:

```text
query words
structural intent
repository scope
source flag / output limit
```

An Adaptive Semantic Object is composed from a fuller input set:

```text
target
consumer
purpose
disclosure profile
context budget
composition policy
available knowledge
```

Graft's pack is therefore best described as:

> a strong task-specific View and a precursor/baseline for adaptive composition.

It does not yet model whether the consumer is:

- a new contributor
- a maintainer
- a security reviewer
- a migration agent
- a user who should not see sensitive project context
- a small-context local model
- a frontier model capable of pulling additional context itself

Nor does it explicitly choose among competing composition policies such as:

```text
minimum-safe orientation
exhaustive evidence bundle
change-impact brief
implementation-only context
decision-rationale-first context
```

---

## 5. Direct overlap with Beacon v0

Graft overlaps several current or planned Beacon capabilities.

### 5.1 Project overview

Graft's high-level Markdown nodes can explain major systems and concepts. This overlaps `beacon_project_overview`, although Graft's view is inferred primarily from code rather than declared project purpose, audience, status, and non-goals.

### 5.2 Agent onboarding and Orientation

A pushed Graft bundle gives a coding agent an immediate map of relevant code. This directly validates the `beacon_agent_onboarding` thesis:

> cold-start project understanding should be composed before the agent spends a turn rediscovering it.

Graft's package is narrower. It generally cannot provide authoritative answers to:

```text
What is safe to change?
Which decisions are still current?
Which behavior is intentionally weird?
What is experimental?
What should not be touched without review?
Which prior failures matter?
What does the maintainer want the system to become?
```

### 5.3 Search

Graft provides strong code-specific search and ranking. It is direct prior art for the code source type envisioned by `beacon_search` and for the planned `beacon_find_files` / `beacon_explain_symbol` capabilities.

Beacon's search contract remains broader because it must combine and label:

```text
docs
code
decisions
benchmarks
issues
commits
memories
guardrails
```

### 5.4 Concept explanation

Graft's higher-level nodes explain code concepts and connect them to symbols. This overlaps `beacon_explain_concept`.

Beacon should retain a distinction between:

```text
observed implementation concept
    inferred from current code

maintainer-defined project concept
    declared in canonical project knowledge

historical or disputed concept
    known through decisions, docs, and memory
```

Graft mostly covers the first.

### 5.5 Guardrails

Graft can identify structure, callers, dependencies, risky hubs, and relevant tests. These are useful inputs to guardrail composition.

It does not establish normative project rules by itself. Structural importance is not the same as permission, policy, or maintainer intent.

---

## 6. Where Graft is ahead of Beacon today

Beacon should be explicit about areas where Graft has already built and measured a stronger implementation.

### 6.1 Deterministic code graph

Graft has a focused, incremental tree-sitter pipeline with:

- path-scoped symbol identity
- multi-language parsing
- typed structural edges
- body-hash caching
- cold/incremental parity tests
- monorepo scope discovery
- worktree seeding
- query-time freshness

Beacon v0 has no native code graph.

### 6.2 Code-specific context retrieval

Graft has an integrated retrieval path combining:

- structural-intent routing
- exact symbol resolution
- lexical BM25/IDF
- graph-ranked expansion
- test-file de-ranking
- scope-aware fusion
- bounded source inlining

Beacon v0's deterministic document search is substantially simpler.

### 6.3 Substitutive context packs

Graft does not merely tell an agent which file to inspect. It can return the relevant source span directly, bounded to prevent one large definition from consuming the pack.

That is important. A context product only saves agent effort when its output can substitute for some exploratory reads, not when it creates another index the agent must inspect before doing the same work anyway.

### 6.4 Freshness as a query invariant

Graft treats current-code freshness as part of answering. A read checks whether the graph needs repair before trusting it.

Beacon v0 currently relies on manifest/docs freshness discipline. The future provider contract needs a stronger freshness envelope.

### 6.5 Public outcome benchmark

Graft benchmarks the effect of context on the agent, not merely retrieval scores.

Its public experiments compare:

```text
cold agent
pushed context
pull-only context tools
```

Reported metrics include:

```text
task correctness
tokens
tool calls
latency
cost
source reads
```

It also reports a small SWE-bench Verified comparison using the official test harness.

The sample sizes and implementation-specific choices should be scrutinized, but the benchmark target is correct:

> Does project understanding make the agent faster, cheaper, and more correct?

Beacon needs an equivalent or stronger outcome story.

---

## 7. Where Beacon remains materially different

### 7.1 Beacon is a contract; Graft is a product/provider

Graft owns an end-to-end implementation and file format.

Beacon's architecture separates:

```text
client-facing contract
provider implementation
knowledge substrates
composition policy
```

A Beacon client should be able to ask the same project-understanding questions regardless of whether answers come from:

```text
static manifest
canonical docs
Graft-like code graph
Git history
issue/decision store
Menhir
another project-intelligence provider
```

This provider neutrality remains valuable, but only if the contract is proved by multiple real providers rather than specified in isolation.

### 7.2 Beacon covers maintainer intent, not only code reality

Graft is strongest at explaining what the code currently does.

Beacon also needs to represent:

```text
why the project exists
who it serves
what is intentionally unsupported
what is experimental
what should happen next
which choices are constraints
which rules are normative
which code/doc divergences are known
```

Code is evidence of reality. It is not the complete project contract.

### 7.3 Beacon composes across knowledge classes

An Orientation object may need to combine:

```text
project purpose
current architecture
relevant code
current decisions
known hazards
required checks
recent changes
prior failed attempts
consumer permissions
next exploration steps
```

Graft primarily supplies current structural and derived code meaning.

### 7.4 Beacon has a temporal direction

Graft refreshes to current code. It does not attempt to answer:

```text
What did this architecture mean before the migration?
Why was this mechanism replaced?
Which assumptions were invalidated?
What changed in project understanding?
Which old instructions are superseded?
```

Beacon's planned Menhir-backed tools—decision tracing, what-changed, temporal blast radius—occupy this space.

### 7.5 Beacon's output should be consumer-aware

Two consumers asking about the same target may need different objects.

Example:

```text
new contributor
    architecture, read order, safe first task, commands, guardrails

security reviewer
    trust boundaries, auth paths, risky dependencies, open findings, evidence

migration agent
    current/target architecture, compatibility constraints, sequencing, rollback

local 8K model
    narrow source-grounded pack with explicit next pull actions

frontier 200K model
    broader map with decision history and optional evidence expansion
```

Graft adapts well to the query and repository, but not yet to this richer consumer model.

### 7.6 Beacon should expose authority and disclosure

A structurally relevant node is not automatically safe or appropriate to disclose.

Beacon's provider envelope should eventually support:

```text
source authority
freshness
status
scope
disclosure decision
omitted-by-policy signal
omitted-by-budget signal
composition rationale
```

Graft's local single-user codebase model does not need this boundary.

---

## 8. Graft's benchmark and what Beacon should learn from it

### 8.1 Graft's experimental shape

The most useful prior-art contribution may be the arm design:

```text
Cold
    no project context; agent explores from scratch

Push
    context bundle injected before work

Pull
    no injected bundle; project tools available on demand
```

This separates two questions:

1. Does the project knowledge help?
2. Is it better to push it, let the model pull it, or adapt between the two?

Beacon's newer composition model adds a fourth arm:

```text
Adaptive
    compose the minimum initial Orientation for this consumer/purpose/budget,
    then expose pull affordances for expansion
```

### 8.2 Recommended Beacon benchmark matrix

At minimum:

| Arm | Initial context | Pull tools | Composition |
|---|---|---|---|
| Cold | none beyond ordinary repo files | ordinary file tools | none |
| Static Beacon | v0 manifest/docs onboarding | Beacon tools | fixed manifest logic |
| Graft-like | structural code map / pushed pack | code graph tools | query + structural ranking |
| Beacon Push | full task Orientation injected | Beacon tools | policy-driven but push-first |
| Beacon Pull | handshake only | Beacon tools | agent-driven retrieval |
| Beacon Adaptive | minimum Orientation | Beacon tools | consumer/purpose/budget-aware |
| Menhir-backed Beacon | adaptive Orientation with history/decisions | Beacon + temporal tools | cross-source and temporal |

The Graft arm may use Graft directly rather than reimplementing it, subject to adapter cost and benchmark fairness.

### 8.3 Primary metric: Time-to-Competence

Task completion time alone is too coarse. Beacon's product objective should be measured more directly.

Candidate operational definition:

```text
Time-to-Competence = elapsed interaction cost until the agent has enough
correct, current, source-grounded understanding to choose a safe and
productive action path.
```

Observable proxies:

```text
time to first correct plan
time to first relevant file/symbol
time to identify required tests
time to identify a load-bearing guardrail
exploratory reads before productive action
incorrect assumptions before correction
plan revisions caused by missing context
```

### 8.4 Outcome metrics

Beacon should report:

```text
task correctness
regression/test success
plan correctness before editing
tokens
cost
tool calls
wall-clock time
number of full-file reads
number of irrelevant context items
```

### 8.5 Context-quality metrics

Add metrics Graft does not emphasize:

```text
source-span sufficiency
freshness violations
superseded guidance surfaced as current
guardrail recall
unsafe first actions
unsupported claims
abstention correctness
omitted-by-budget honesty
consumer-inappropriate disclosure
```

### 8.6 Composition metrics

For Adaptive Semantic Objects:

```text
initial-pack precision
initial-pack recall against task-required knowledge
expansion efficiency
duplicate information rate
context budget utilization
useful information per token
decision quality per token
```

### 8.7 Cross-model transfer

Because Beacon is a contract, evaluate the same project provider and task set across:

```text
small local model
mid-tier coding model
frontier coding model
multiple agent harnesses
```

A context composition that only helps one model may be an agent-specific prompt optimization rather than durable project infrastructure.

---

## 9. Recommended adversarial fixtures

### 9.1 Unfamiliar repository onboarding

Ask an agent to explain the project, identify the implementation entry points, name required tests, and propose a safe first contribution.

Measures basic Orientation quality.

### 9.2 Multi-file behavioral change

The requested change crosses implementation, configuration, tests, and documentation.

Graft should be strong at structural discovery. Beacon must additionally surface relevant decisions and guardrails.

### 9.3 Ambiguous symbol names

Several packages contain common names such as `get`, `run`, `handler`, or `config`.

Tests scope resolution, structural ranking, and false-hub control.

### 9.4 Stale generated explanation

Edit a function without regenerating its semantic summary.

The provider must either refresh, mark stale, omit the summary, or state uncertainty. It must not serve the old explanation as current.

### 9.5 Code versus canonical-doc disagreement

Current code and a declared architecture document disagree.

A code-only system may choose reality; a static manifest may choose intent. Beacon should return both with source type/status and avoid silently collapsing the disagreement.

### 9.6 Superseded decision

An old design decision remains highly searchable, but a later decision replaced it.

Graft does not target this. A Menhir-backed Beacon should surface the current position and preserve history.

### 9.7 Guardrail not inferable from structure

A file is structurally central but maintainers permit changes; another small file has a critical compliance rule.

Tests that structural prominence is not mistaken for normative risk.

### 9.8 Consumer-sensitive orientation

Run the same task with:

```text
new contributor
maintainer
security reviewer
restricted external agent
```

The composed object should differ appropriately.

### 9.9 Context-budget compression

Run under 4K, 8K, 32K, and large context budgets.

Measure whether composition preserves required understanding while clearly exposing what was omitted and how to retrieve it.

### 9.10 Non-code project target

Orient an agent to a policy, research, operations, or documentation-heavy project.

This is important because Graft's strongest lane is code. Beacon's contract should remain useful when code structure is not the primary substrate.

---

## 10. What Beacon should borrow

### 10.1 Deterministic-first, semantic-second construction

Use deterministic structure wherever the source permits it, then layer generated meaning on top.

```text
source reality
-> deterministic projection
-> optional semantic enrichment
-> composed Orientation
```

Do not ask a model to rediscover import/call/containment structure that a parser can establish.

### 10.2 Content-addressed semantic enrichment

Tie generated explanations to source hashes or semantic-version fingerprints.

A summary should be:

```text
ready
stale
pending
failed
```

never merely present.

### 10.3 Lexical seeds plus graph ranking

Test Graft's deterministic retrieval shape as a Beacon code-provider arm:

```text
lexical/BM25 candidates
-> personalized PageRank
-> bounded structurally coherent pack
```

This may outperform embeddings for code-navigation questions while remaining fast and inspectable.

### 10.4 Query-time freshness enforcement

A provider should not answer from a known-stale projection merely because refresh is scheduled later.

The provider response should include a freshness receipt such as:

```json
{
  "source_revision": "...",
  "checked_at": "...",
  "freshness": "current | stale | unknown",
  "refresh_performed": true
}
```

### 10.5 Bounded substitutive source spans

When a source span is sufficient, return it directly rather than forcing the consumer to spend another tool call reading an entire file.

Also state truncation and offer a continuation/pull path.

### 10.6 Extracted versus inferred relationships

Preserve Graft's useful confidence distinction and extend it:

```text
extracted
inferred
declared
derived
disputed
```

The edge's origin matters when composing high-stakes context.

### 10.7 Ranking scopes

Monorepos and multi-project workspaces require explicit scopes. Do not let common terms in one package dominate another package's Orientation.

### 10.8 Push/pull/adaptive benchmark arms

This should become a standard Beacon evaluation shape, not a one-off comparison.

### 10.9 Context-value telemetry

Borrow the discipline of reporting what the context replaced:

```text
whole-file reads avoided
tokens avoided
tool calls avoided
latency avoided
```

Extend it with Beacon-specific value:

```text
unsafe action prevented
stale assumption suppressed
current decision recovered
required check surfaced
orientation expansion avoided
```

---

## 11. What Beacon should not copy directly

### 11.1 Do not make the code map the project contract

Code structure is one evidence source. It cannot establish every purpose, guardrail, decision, status, or non-goal.

### 11.2 Do not treat generated summaries as authoritative facts

LLM prose should remain derived, source-linked, versioned, and freshness-gated.

### 11.3 Do not equate regeneration with history

Replacing a stale projection is correct for current-code navigation. It is insufficient for decision tracing and cognitive replay.

### 11.4 Do not push a large map by default

Graft's own benchmark distinction between push and pull shows that context-delivery policy matters.

Beacon should push only the minimum Orientation justified by consumer, purpose, safety, and budget, then expose expansion affordances.

### 11.5 Do not make path-scoped identity the only semantic identity

`path#symbol` is excellent structural identity. It is weak conceptual continuity across:

```text
renames
moves
splits
merges
rewrites
cross-language migrations
```

Beacon can consume structural identities without making them the only identity layer.

### 11.6 Do not hide provider disagreement

A Graft-like provider, static manifest provider, and Menhir provider may disagree.

Beacon should preserve source-specific claims and statuses rather than selecting one answer without an explicit composition rule.

### 11.7 Do not optimize only token savings

A tiny but misleading pack is worse than a larger correct one. Time-to-Competence and task correctness remain the primary objectives; token efficiency is constrained optimization beneath them.

---

## 12. Implications for the Beacon provider architecture

Graft suggests a concrete provider ladder.

```text
ManifestBeaconProvider
    declared purpose, concepts, guardrails, docs, commands

CodeGraphBeaconProvider
    deterministic symbols, relationships, source spans, freshness

GitBeaconProvider
    changes, ownership, commit history, branch state

DecisionBeaconProvider
    current and superseded project decisions

MenhirBeaconProvider
    memory, evidence, temporal state, prior failures, cross-source joins

CompositeBeaconProvider
    policy-governed composition across all available providers
```

Graft could support the `CodeGraphBeaconProvider` role in one of three ways:

1. **Direct adapter:** invoke Graft tools/CLI and translate results into Beacon answer contracts.
2. **Projection reader:** consume Graft's generated graph JSON/cards as a source.
3. **Benchmark-only baseline:** keep implementations independent and compare outputs/outcomes.

The first or third option is preferable initially. Copying Graft's implementation into Beacon would add maintenance burden before proving the Beacon-specific contract.

### 12.1 Provider response requirements

A richer provider response should carry:

```text
content
source identity
source type
authority/status
freshness
scope
confidence basis
exact pointers
composition contribution
```

A provider supplies evidence-bearing objects. The composer decides what becomes the Orientation.

### 12.2 Composition should not live inside every provider

Graft combines code retrieval and context packing in one product, which is reasonable for its focused scope.

Beacon should keep a boundary:

```text
provider retrieval / projection
-> normalized Semantic Objects and Views
-> composition policy
-> Adaptive Semantic Object
```

Otherwise each provider invents its own consumer model, budget logic, disclosure rules, and output shape.

---

## 13. Implications for the Orientation Semantic Object

Graft sharpens the minimum contract for Orientation.

An Orientation should not be a generic project summary. It should make a consumer competent for a purpose.

Recommended fields:

```text
target
consumer
purpose
current situation
required understanding
relevant systems/concepts
relevant source locations
current constraints and guardrails
known uncertainty or disagreement
safe first actions
suggested next exploration
available evidence expansions
freshness receipt
budget/disclosure omissions
```

Graft can supply strong values for:

```text
relevant systems
symbols/files
structural relationships
source spans
current-code freshness
```

Other providers must supply:

```text
purpose
maintainer intent
decisions
history
normative guardrails
prior failures
consumer/disclosure constraints
```

This supports a clean architectural sentence:

> Graft can provide a high-quality structural substrate for an Orientation; Beacon composes the Orientation.

---

## 14. Impact on Beacon's current roadmap

### Milestone 3 — useful for a real task

Graft is direct prior art for:

- task-specific onboarding
- file/path suggestions
- source-grounded context packs
- suggested read order
- code-risk hints

Milestone 3 should include a cold/push/pull outcome benchmark rather than only golden output tests.

### Planned `beacon_find_files`

This capability is already strongly occupied by Graft and other code-intelligence tools.

Beacon should not differentiate on finding files alone. Its stronger form is:

```text
find the files, decisions, guardrails, tests, and prior failures relevant
for this consumer's intended change, with source status and read order
```

### Planned `beacon_explain_symbol`

Graft is direct prior art. Beacon should treat symbol explanation as a provider capability, not a novel product center.

### Planned `beacon_temporal_blast_radius`

Graft covers current structural neighbourhood and impact inputs. Beacon's differentiated version must connect:

```text
code structure
current and historical decisions
docs and tests
known failures
memories and constraints
```

### Milestone 5 — Menhir-backed dynamic Beacon

Graft strengthens the case for a provider ladder rather than a single monolithic backend.

A Menhir-backed provider should not spend its differentiation budget rebuilding a commodity structural graph if a specialized provider can supply that layer cleanly.

---

## 15. Novelty and positioning discipline

Beacon should not claim novelty for any of the following by themselves:

- a codebase map for agents
- linked Markdown project nodes
- tree-sitter symbol graphs
- LLM summaries over code symbols
- content-hash incremental enrichment
- lexical/BM25 code retrieval
- graph-ranked retrieval
- exact source-span context packs
- push-versus-pull project context
- proving that better code orientation reduces tool calls and tokens

Graft and adjacent systems already occupy those claims.

Beacon may remain differentiated by the combination of:

- a provider-neutral project-understanding protocol
- stable answer contracts across heterogeneous providers
- explicit source/status/freshness/authority envelopes
- dynamic composition rather than one fixed project map
- consumer-, purpose-, disclosure-, and budget-aware Adaptive Semantic Objects
- Orientation optimized for Time-to-Competence
- cross-source project understanding beyond code
- current-versus-historical decision and knowledge state
- provider disagreement preserved and composed explicitly
- a low-floor static provider with an upgrade path to structural and Menhir-backed intelligence

Recommended positioning:

> Graft maps the current codebase so an agent can navigate it efficiently. Beacon is the project-understanding contract and composition layer that can use that map—alongside purpose, decisions, guardrails, history, and memory—to orient a particular agent for a particular job.

---

## 16. Recommended next experiment

Do not begin by recreating Graft.

Run a focused Beacon context experiment:

### Inputs

- one unfamiliar medium-size repository
- one multi-package repository
- a static Beacon manifest/docs provider
- Graft as the structural provider/baseline
- a small set of tasks requiring code plus project rules or rationale

### Arms

```text
cold
Graft push
Graft pull
Beacon static Orientation
Beacon + Graft structural Orientation
Beacon adaptive push/pull
```

### Questions

1. Does Beacon's declared purpose/guardrail context improve decisions beyond Graft's structural context?
2. Does composing Graft output into an Orientation outperform injecting Graft output directly?
3. Which information should be pushed versus left as a pull affordance?
4. Does consumer-aware composition help smaller models more than frontier models?
5. Can Beacon reduce unsafe or mis-scoped first actions without increasing context cost excessively?

### Promotion criterion

Advance a `CodeGraphBeaconProvider` or Graft adapter only if the combined arm demonstrates at least one measurable gain that the Graft-only arm cannot supply:

```text
higher task correctness
fewer unsafe first actions
better guardrail recall
fewer plan revisions
lower Time-to-Competence
better cross-model transfer
```

If no such gain appears, Beacon should consume Graft as an external tool and avoid adding a structural provider abstraction merely for completeness.

---

## 17. Final classification

```text
Graft
    current-code structural and semantic projection
    optimized for coding-agent navigation and context efficiency

Beacon v0
    provider-neutral project-introspection MCP contract
    currently manifest/docs driven

Beacon context-composition direction
    Semantic Objects + Views
    composed into consumer/purpose-aware Adaptive Semantic Objects
    Orientation minimizes Time-to-Competence

Menhir
    optional smart provider for evidence, temporal state, decisions,
    memory, prior failures, and cross-source project knowledge
```

The architectural conclusion is:

> Graft should influence Beacon's code provider, freshness contract, context packing, and benchmark design. It should not collapse Beacon into a code map or redefine Orientation as a ranked bundle of current symbols.

The product conclusion is:

> Graft already demonstrates the value of code orientation. Beacon must demonstrate the additional value of a standardized, cross-source, consumer-aware project-understanding layer.
