# Beacon Strategy Handoff

> Status: strategic handoff / product-research note  
> Scope: Beacon as an agent-accessible project knowledge capability contract, with Menhir as the richest reference provider  
> Origin: project planning discussion, June 2026

## 0. Core idea

**Beacon** is a capability contract for how software projects communicate with autonomous agents.

It is not just an MCP server. MCP is one transport.

It is not just `beacon.yaml`. The manifest is one bootstrap input.

The higher-level idea is:

> A Beacon lets a project answer standard questions that agents need before they can understand, query, and safely contribute to that project.

For Menhir and Archolith, Beacon serves three jobs at once:

1. **Demo surface** — people can connect an agent to the Menhir Beacon and ask questions about Menhir itself.
2. **Onboarding layer** — agents can quickly learn a project's purpose, architecture, current work, docs, risks, conventions, and relevant files.
3. **Reference implementation target** — Menhir becomes a rich implementation/provider for Beacon, while Beacon remains abstract enough to apply to many backends and organizational designs.

Strategic positioning:

> Beacon becomes the standard Agent-to-Project interface. Menhir becomes the richest way to generate and maintain one.

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

> A project should expose a standard, queryable understanding of itself.

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
- Beacon is the standard conversation between a project and an agent.

Internal distinction:

- **Beacon** — the capability contract / Agent-to-Project interface.
- **Menhir Beacon** — Menhir's implementation/provider for Beacon.
- **Beacon Manifest** — static project summary and bootstrap input.
- **Beacon MCP** — MCP transport exposing Beacon capabilities.
- **Beacon Snapshot** — exportable JSON/YAML representation of Beacon answers or metadata.
- **Beacon Provider** — backend-specific implementation that answers Beacon capabilities.

The name works best if it can become category language:

> Does this repository publish a Beacon?

That is stronger than:

> Does this repository have an MCP server?

## 3. Architectural principle

Beacon should be **backend-agnostic** and **transport-agnostic**.

Bad framing:

> Beacon is Menhir's MCP server.

Better framing:

> Beacon is a capability contract for project understanding. Menhir can answer that contract using temporal memory, structure graphs, git history, and documentation.

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

## 4. LSP-style mental model

A useful analogy is the Language Server Protocol.

LSP does not standardize compiler internals. It standardizes useful interactions between editors and language tooling:

- go to definition
- hover
- rename
- diagnostics
- completion

Beacon should follow a similar pattern for Agent-to-Project communication.

It should standardize useful project questions:

- project overview
- onboarding
- search
- concept explanation
- guardrails
- decision tracing
- change history
- file discovery

It should not require every implementation to store project knowledge the same way.

## 5. MVP goal

Build a public MCP transport that answers useful questions about a project, starting with Menhir itself.

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

This should feel meaningfully better than a README chatbot because it is structured, source-backed, status-aware, and oriented toward agent action.

## 6. Beacon v0 capabilities

Beacon v0 should support five core capabilities.

### 6.1 Identify / project overview

Answer:

- What is this project?
- What problem does it solve?
- Who is it for?
- What is explicitly out of scope?

### 6.2 Orient / agent onboarding

Answer:

- What should an agent read first?
- What are the major components?
- What is the current build/test flow?
- What docs are canonical?
- What is safe to do first?

### 6.3 Search

Answer:

- What sources discuss this topic?
- Which results are current, experimental, disputed, or superseded?
- What is the safest source-backed answer?

### 6.4 Explain concept

Answer:

- What does this project-specific term mean?
- Why does it exist?
- What concepts/files/docs are related?

### 6.5 Guardrails

Answer:

- What should an agent avoid doing?
- Which files are generated?
- Which APIs are unstable?
- What conventions must be followed?
- What changes require migration or benchmark updates?

## 7. Manifest strategy

A Beacon can have a manifest that gives agents a compact starting map.

The manifest does not need to contain everything. It should act as:

- project identity card
- bootstrap provider input
- table of contents
- safe starting context
- status map
- guardrail source

The manifest is not the whole Beacon.

The dynamic Beacon can expand from docs, code, git history, memory, benchmarks, and other sources.

## 8. Static vs dynamic Beacon

Beacon should support both static and dynamic forms.

### Static Beacon

A static `beacon.yaml` or `beacon.json` checked into the repo.

Advantages:

- easy to inspect
- works without a server
- version controlled
- simple for early users
- good fallback
- useful bootstrap for dumb providers

Risk:

- stale static files can destroy trust if presented as authoritative live truth.

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

1. `beacon.yaml` manifest as bootstrap input
2. local Beacon loader and validator
3. MCP tools over manifest + docs
4. richer provider responses
5. Menhir-backed dynamic answers
6. public hosted Menhir Beacon

## 9. Provider separation

Beacon should use a provider interface so the transport layer does not care where knowledge comes from.

Suggested providers:

- `ManifestBeaconProvider`
- `ManifestAndDocsBeaconProvider`
- `GitAwareBeaconProvider`
- `MenhirBeaconProvider`
- future GitHub-only provider
- future enterprise docs provider

This keeps Beacon from becoming inseparable from Menhir internals or from MCP specifically.

## 10. Declared vs observed knowledge

Beacon should eventually distinguish between two kinds of project knowledge.

### Declared knowledge

Maintainer intent:

- intended architecture
- documented conventions
- guardrails
- current roadmap
- design goals

### Observed knowledge

Evidence from the project:

- actual imports/dependencies
- implementation structure
- Git history
- benchmark results
- documentation drift
- contradictions between sources

A powerful Beacon should be able to report both:

> The declared architecture says A. The observed code currently does B. These diverged recently.

This distinction is a major reason Menhir can be valuable as a Beacon provider.

## 11. Answer contract

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

## 12. Important design warnings

### Do not make Beacon too abstract too early

Start concrete.

Bad early goal:

> Design a universal project-intelligence standard.

Good early goal:

> Make Menhir's own public Beacon genuinely useful.

The standard can emerge from repeated use.

### Do not make Beacon just chat

Beacon should expose structured capabilities, not only freeform Q&A.

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
  capability schemas
  manifest schema
  loader
  validator
  response types

beacon-mcp
  MCP transport exposing Beacon capabilities

menhir-beacon
  Menhir-backed provider with temporal/project graph power
```

Simple projects should eventually be able to publish a Beacon without adopting the full Menhir stack.

### Avoid the ontology trap

Beacon should not become RDF-for-agents.

Prefer standard questions and practical response contracts over rigid universal modeling of all project concepts and relationships.

## 13. Success criteria

Beacon v0 is successful if:

- A new agent can connect and orient itself using standard project capabilities.
- The endpoint gives safe, source-backed guidance.
- The project can answer "what is current?" better than a generic docs chatbot.
- The demo is understandable in under five minutes.
- The implementation does not overfit to Menhir internals.
- The abstraction remains clear enough to later support other backends and transports.

Beacon v1 is successful if:

- Other projects can publish simple Beacons without Menhir.
- Menhir can generate richer Beacons automatically.
- Agents begin asking for "the project Beacon" as an onboarding norm.
- Beacon becomes part of the pitch for serious agent-ready OSS projects.

## 14. Strategic thesis

Beacon should be positioned as:

> The missing handshake between software projects and coding agents.

Or, more specifically:

> Beacon standardizes Agent-to-Project communication.

Today, projects expose APIs for programs and READMEs for humans.

Beacon exposes project understanding for agents.

Menhir should use Beacon to prove its deeper thesis:

> Agents need temporal, source-backed, structure-aware memory to work safely on real software over time.

The public Menhir Beacon is not just a feature. It is the front door to the entire project.
