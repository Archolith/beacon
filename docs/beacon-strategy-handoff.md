# Beacon Strategy Handoff

> Status: strategic handoff / product-research note  
> Scope: Beacon as an agent-accessible project knowledge surface, with Menhir as the reference implementation  
> Origin: project planning discussion, June 2026
> Update 2026-09-22: the ownership model changed. Beacon builds every beacon; Menhir is one
> swappable memory provider behind a backend-neutral contract and never writes into a project.
> Where this note says Menhir "generates" a beacon, read it that way. The current direction is
> [`beacon-open-standard.md`](beacon-open-standard.md).

## 0. Core idea

**Beacon** is a public, agent-accessible representation of a software project.

It is not just an MCP server. MCP is one transport. Beacon is the higher-level concept:

> A Beacon is a self-describing, machine-readable project knowledge surface that lets LLM agents understand, query, and safely contribute to a project.

For Menhir and Archolith, Beacon serves three jobs at once:

1. **Demo surface** — people can connect an agent to the Menhir Beacon and ask questions about Menhir itself.
2. **Onboarding layer** — agents can quickly learn a project's purpose, architecture, current work, docs, risks, conventions, and relevant files.
3. **Reference implementation** — Menhir becomes the first rich implementation of Beacon, while Beacon remains abstract enough to apply to many backends and organizational designs.

Strategic positioning:

> Beacon becomes the standard interface. Menhir becomes the richest memory provider behind one.

## 1. Why this matters

Most projects onboard humans and agents through scattered artifacts:

- README files
- docs
- issues
- commits
- architecture notes
- PR discussions
- stale design docs
- benchmark scripts
- TODO comments
- maintainer memory

LLM agents currently reverse-engineer this through ad hoc context stuffing.

Beacon changes the model:

> A project should publish its own living, structured understanding.

An agent should be able to ask:

- What is this project?
- What should I read first?
- What is current versus outdated?
- What are the main architectural decisions?
- What changed recently?
- What should I avoid touching?
- What benchmarks prove this works?
- What files implement this feature?
- What assumptions are disputed?
- What is the next safe contribution?

Menhir is unusually well-suited to generate a rich Beacon because it is already designed to connect temporal memory, code structure, documentation, git history, decisions, contradictions, benchmarks, and project intent.

## 2. Naming thesis

Recommended public name: **Beacon**.

Useful language:

- Publish your project's Beacon.
- Connect your agent to the Menhir Beacon.
- Every serious OSS project should expose a Beacon.
- Beacon is the machine-readable source of truth for agent onboarding.

Internal distinction:

- **Beacon** — the public representation / endpoint / spec concept.
- **Menhir Beacon** — Menhir's implementation of Beacon.
- **Beacon Manifest** — static or semi-static project summary document.
- **Beacon MCP** — MCP transport exposing Beacon tools.
- **Beacon Snapshot** — exportable JSON/YAML representation.
- **Beacon Adapter** — backend-specific generator that produces Beacon-compatible data.

The name works best if it can become category language:

> Does this repository publish a Beacon?

That is stronger than:

> Does this repository have an MCP server?

## 3. Architectural principle

Beacon should be **backend-agnostic**.

Bad framing:

> Beacon is Menhir's MCP server.

Better framing:

> Beacon is a project knowledge interface. Menhir can generate one using temporal memory, structure graphs, git history, and documentation.

This lets Beacon eventually apply to:

- small GitHub-only projects
- docs-only projects
- companies with Confluence or Notion
- monorepos
- research labs
- agentic coding environments
- mature OSS projects
- private engineering organizations
- alternative memory backends

Menhir should produce the richest Beacon, but not be required for the basic concept.

## 4. MVP goal

Build a public MCP endpoint that answers useful questions about a project, starting with Menhir itself.

The first demo query should be:

> What is Menhir, what is the current architecture, what should I read first, and what is the safest next contribution?

The answer should return:

- concise project explanation
- current focus
- core concepts
- important docs
- relevant files
- open implementation rungs
- known risks
- recommended next actions
- citations/provenance

This should feel meaningfully better than a README chatbot.

## 5. Beacon v0 capabilities

Beacon v0 should support five core capabilities.

### 5.1 Identify

Answer:

- What is this project?
- What problem does it solve?
- Who is it for?
- What is explicitly out of scope?

### 5.2 Orient

Answer:

- What should an agent read first?
- What are the major components?
- What is the current build/test flow?
- What docs are canonical?

### 5.3 Explain

Answer:

- How does this architecture work?
- Why was this decision made?
- What terms mean what?
- How do components relate?

### 5.4 Trace

Answer:

- What changed recently?
- When did this idea appear?
- What superseded what?
- Which docs/files/commits relate to this feature?

### 5.5 Guardrail

Answer:

- What should an agent avoid doing?
- Which files are generated?
- Which APIs are unstable?
- What conventions must be followed?
- What changes require migration or benchmark updates?

## 6. Manifest strategy

A Beacon should have a manifest that gives agents a compact starting map.

The manifest does not need to contain everything. It should act as:

- table of contents
- project identity card
- safe starting context
- status map
- guardrail source

The dynamic Beacon can then expand from docs, code, git history, memory, benchmarks, and other sources.

## 7. Static vs dynamic Beacon

Beacon should support both static and dynamic forms.

### Static Beacon

A static `beacon.yaml` or `beacon.json` checked into the repo.

Advantages:

- easy to inspect
- works without a server
- version controlled
- simple for early users
- good fallback

### Dynamic Beacon

An MCP or HTTP endpoint backed by a provider.

Advantages:

- searchable
- current
- can answer complex questions
- can include git/doc/code/memory joins
- can expose temporal reasoning
- can produce agent-specific onboarding packs

Recommended order:

1. `beacon.yaml` manifest
2. local Beacon loader
3. MCP tools over manifest + docs
4. Menhir-backed dynamic answers
5. public hosted Menhir Beacon

## 8. Provider separation

Beacon should use a provider interface so the MCP layer does not care where knowledge comes from.

Suggested providers:

- `ManifestBeaconProvider`
- `ManifestAndDocsBeaconProvider`
- `MenhirBeaconProvider`
- future GitHub-only provider
- future enterprise docs provider

This keeps Beacon from becoming inseparable from Menhir internals.

## 9. Answer contract

Every Beacon response should try to include:

```json
{
  "answer": "...",
  "status": "current | experimental | uncertain | mixed",
  "confidence": "low | medium | high",
  "sources": [],
  "related": [],
  "next_actions": []
}
```

Agent-facing responses should also include:

```json
{
  "safe_next_steps": [],
  "risks": [],
  "commands": [],
  "files": []
}
```

The status and confidence fields matter because agents should not treat all generated text equally.

## 10. Important design warnings

### Do not make Beacon too abstract too early

Start concrete.

Bad early goal:

> Design a universal project-intelligence standard.

Good early goal:

> Make Menhir's own public Beacon genuinely useful.

The standard can emerge from repeated use.

### Do not make it just chat

Beacon should expose structured tools, not only freeform Q&A.

Agents need:

- read order
- file lists
- risks
- commands
- source-backed claims
- status labels
- confidence
- next actions

### Do not hide uncertainty

A Beacon should be allowed to say:

- unknown
- stale
- experimental
- disputed
- superseded
- not enough evidence

This is one of the key differences from normal project docs.

### Do not require Menhir for Beacon v0

Keep a clean boundary.

Suggested conceptual split:

```text
beacon-core
  manifest schema
  loader
  validator
  response types

beacon-mcp
  MCP server exposing Beacon tools

menhir-beacon
  Menhir-backed provider with temporal/project graph power
```

Simple projects should eventually be able to publish a Beacon without adopting the full Menhir stack.

## 11. Success criteria

Beacon v0 is successful if:

- A new agent can connect and understand the project faster than reading the README alone.
- The endpoint gives safe, source-backed guidance.
- The project can answer "what is current?" better than a generic docs chatbot.
- The demo is understandable in under five minutes.
- The implementation does not overfit to Menhir internals.
- The abstraction remains clear enough to later support other backends.

Beacon v1 is successful if:

- Other projects can publish simple Beacons without Menhir.
- Menhir can generate richer Beacons automatically.
- Agents begin asking for "the project Beacon" as an onboarding norm.
- Beacon becomes part of the pitch for serious agent-ready OSS projects.

## 12. Strategic thesis

Beacon should be positioned as:

> The missing handshake between software projects and coding agents.

Today, projects expose APIs for programs and READMEs for humans.

Beacon exposes project understanding for agents.

Menhir should use Beacon to prove its deeper thesis:

> Agents need temporal, source-backed, structure-aware memory to work safely on real software over time.

The public Menhir Beacon is not just a feature. It is the front door to the entire project.
