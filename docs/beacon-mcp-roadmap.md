# Beacon MCP Roadmap

> Status: implementation roadmap  
> Scope: Beacon v0 MCP transport, demo flow, and next milestones

## 0. Framing

Beacon is not defined by MCP.

Beacon is a capability contract for Agent-to-Project communication. MCP is the first transport used to expose those capabilities.

This roadmap describes the MCP transport because it is the most practical initial way to let coding agents connect to a Beacon.

## 1. Current v0 MCP surface

Beacon v0 should keep the MCP surface intentionally small and always visible.

Initial tools:

- `beacon_project_overview`
- `beacon_agent_onboarding`
- `beacon_search`
- `beacon_explain_concept`
- `beacon_guardrails`

This is the right shape for a young project: enough to demonstrate the concept, not so much that the interface becomes mushy.

These tools are transport-specific names for the more general Beacon v0 capabilities:

- project overview
- agent onboarding
- search
- concept explanation
- guardrails

## 2. Tool intent

### `beacon_project_overview`

Purpose: Give a concise, current explanation of the project.

Questions it should answer:

- What is this project?
- What problem does it solve?
- Who is it for?
- What is its current status?
- What should someone read next?

Ideal output fields:

```json
{
  "summary": "...",
  "problem": "...",
  "current_status": "...",
  "core_components": [],
  "read_next": [],
  "sources": []
}
```

### `beacon_agent_onboarding`

Purpose: Give an agent the minimum context needed to begin safely.

This is likely the flagship tool.

Questions it should answer:

- What should I understand first?
- What files/docs matter for my task?
- What are safe first steps?
- What should I avoid?
- What commands should I run?

Ideal output fields:

```json
{
  "orientation": "...",
  "relevant_docs": [],
  "relevant_files": [],
  "concepts_to_understand": [],
  "safe_first_steps": [],
  "do_not_touch": [],
  "commands": [],
  "sources": []
}
```

### `beacon_search`

Purpose: Search project knowledge with structured source typing and status awareness.

Questions it should answer:

- What does the project know about this topic?
- Which docs/files/decisions are relevant?
- Is this knowledge current, experimental, disputed, or superseded?

Ideal input shape:

```json
{
  "query": "...",
  "source_types": ["docs", "code", "decisions", "benchmarks", "issues", "commits", "memories"],
  "time_mode": "current_only | include_superseded | history",
  "limit": 10
}
```

Ideal output shape:

```json
{
  "answer": "...",
  "results": [
    {
      "title": "...",
      "source_type": "doc | code | decision | benchmark | memory | commit",
      "path": "...",
      "snippet": "...",
      "status": "current | superseded | disputed | experimental",
      "confidence": 0.0,
      "why_relevant": "..."
    }
  ]
}
```

### `beacon_explain_concept`

Purpose: Explain project-specific vocabulary.

Questions it should answer:

- What does this term mean?
- Why does it exist?
- Where is it implemented or documented?
- What concepts are nearby?

Ideal output fields:

```json
{
  "concept": "...",
  "definition": "...",
  "why_it_exists": "...",
  "related_concepts": [],
  "implementation_locations": [],
  "sources": []
}
```

### `beacon_guardrails`

Purpose: Tell an agent how not to break the project.

Questions it should answer:

- What should I avoid changing?
- Which files are risky?
- What checks are required?
- Which decisions or conventions apply?
- What is the safest sequence of work?

Ideal output fields:

```json
{
  "rules": [],
  "risky_files": [],
  "required_checks": [],
  "related_decisions": [],
  "recommended_sequence": [],
  "sources": []
}
```

## 3. Near-future capabilities

Once the basic manifest/docs provider is stable, add Menhir-native power.

These capabilities may be exposed over MCP first, but they should be defined at the Beacon capability layer rather than only as MCP tool names.

### `beacon_trace_decision`

Purpose: Show why a decision exists and what led to it.

This is where Beacon should exceed normal RAG.

Input:

```json
{
  "decision_or_topic": "structure-time join",
  "include_superseded": true
}
```

Output:

```json
{
  "current_position": "...",
  "decision_history": [],
  "superseded_ideas": [],
  "supporting_docs": [],
  "open_questions": [],
  "sources": []
}
```

### `beacon_what_changed`

Purpose: Explain recent changes in project knowledge.

Input:

```json
{
  "topic": "oracle pipeline",
  "since": "2026-06-01",
  "change_types": ["docs", "code", "benchmarks", "decisions"]
}
```

Output:

```json
{
  "summary": "...",
  "changes": [],
  "new_decisions": [],
  "deprecated_assumptions": [],
  "files_changed": [],
  "sources": []
}
```

### `beacon_find_files`

Purpose: Structure-aware file discovery for a task.

Input:

```json
{
  "goal": "modify oracle benchmark runner",
  "include_tests": true,
  "include_docs": true
}
```

Output:

```json
{
  "files": [
    {
      "path": "...",
      "role": "...",
      "why_relevant": "...",
      "risk": "low | medium | high"
    }
  ],
  "suggested_read_order": []
}
```

### `beacon_explain_symbol`

Purpose: Explain a symbol/function/class/module in project context.

This should eventually be backed by a structure graph or code index.

### `beacon_temporal_blast_radius`

Purpose: Explain what related files, symbols, decisions, docs, tests, and memories may be affected by a change across time.

This should wait until Menhir-backed structure/git/memory joins are available.

## 4. Demo script

The public demo should be short and emotionally obvious.

### Prompt 1

```text
What is Menhir, and what should I read first if I want to understand the project?
```

Expected answer:

- one-paragraph explanation
- current focus
- read order
- core concepts
- citations

### Prompt 2

```text
Explain the structure-time join idea and why it matters.
```

Expected answer:

- explains structure x git/history x memory
- gives debugging use case
- links to docs/files
- marks current status

### Prompt 3

```text
I want to make a small safe contribution. What should I do?
```

Expected answer:

- suggests docs, fixtures, tests, examples
- avoids schema/core scoring changes
- gives exact files
- gives commands

### Prompt 4

```text
What changed recently in the oracle pipeline, and what assumptions are still experimental?
```

Expected answer:

- traces change history
- separates confirmed behavior from demo/harness numbers
- points to relevant docs
- flags uncertainty

This fourth prompt is the "normal RAG cannot do this cleanly" moment.

## 5. Milestones

### Milestone 0 — Beacon exists

Done when:

- manifest loader exists
- validator exists
- doc index exists
- deterministic provider exists
- five read-only MCP tools exist
- tests cover loader, validator, doc index, and tools

### Milestone 1 — Make it easy to understand

Add:

- stronger README
- demo transcript
- example client config
- example Menhir Beacon manifest
- screenshot or terminal transcript
- short positioning page

Success criterion:

> A new person understands why Beacon exists in under five minutes.

### Milestone 2 — Make it easy to connect

Add:

- `beacon --help`
- `beacon validate beacon.yaml`
- `beacon inspect beacon.yaml`
- copy/paste MCP client config examples
- local smoke test command

Success criterion:

> A user can connect an MCP client without asking the maintainer how.

### Milestone 3 — Make it useful for a real task

Add:

- task-specific onboarding
- better source citations
- file/path suggestions
- command suggestions
- risk labels
- canonical read order

Success criterion:

> An agent can use Beacon to prepare for a small docs/test/fixture PR.

### Milestone 4 — Add history and decision tracing

Add:

- decision records
- supersession metadata
- `beacon_trace_decision`
- `beacon_what_changed`
- declared-vs-observed divergence fields

Success criterion:

> Beacon can distinguish current decisions from older ideas, and can identify where declared intent diverges from observed project reality.

### Milestone 5 — Menhir-backed dynamic Beacon

Add:

- temporal memory provider
- structure graph provider
- git history provider
- benchmark provider
- richer project graph joins

Success criterion:

> Menhir can generate a richer Beacon than a static manifest/docs-only backend.

## 6. Recommended next repo work

The next highest-value work is not more abstraction. It is packaging and demonstration.

Priority order:

1. Write a public-facing README.
2. Add `docs/demo-transcript.md`.
3. Add `docs/client-setup.md`.
4. Add CLI commands for validation/inspection.
5. Add example manifests for at least two different project shapes:
   - Menhir-style research/code project
   - simple library or app project
6. Add a small golden-output test for each MCP tool.
7. Add `beacon_trace_decision` only after the current five tools are pleasant to use.

## 7. North-star product sentence

> Beacon is the missing handshake between software projects and coding agents.

More precisely:

> Beacon standardizes Agent-to-Project communication.

Today, projects expose APIs for programs and READMEs for humans.

Beacon exposes project understanding for agents.
