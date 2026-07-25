# Beacon Design Review Response

**Date:** 2026-06-29  
**Status:** response to external architecture review  
**Scope:** Beacon/Menhir boundary, protocol framing, manifest role, and next design direction

## 0. Purpose

This document records a response to an external architecture review of Beacon and Menhir. The review raised several useful criticisms, especially around static manifests, standardization fatigue, and the risk of framing Beacon too narrowly as another documentation file.

The goal of this response is not to defend every original assumption. It is to clarify what the review changed, what we agree with, what we disagree with, and how the Beacon design should evolve.

Important timeline note: Beacon was created on 2026-06-29. It emerged from Menhir's prior project-understanding work, but it was not an established Menhir component before today.

## 1. Executive summary

The review correctly identified the most important architectural boundary:

> Beacon should be an interface. Menhir should be an implementation.

We consider this foundational.

However, we do **not** want to define Beacon primarily as an MCP profile or a static manifest format. MCP is an important first transport, and `beacon.yaml` is an important bootstrap artifact, but neither one should fully define Beacon.

The revised view is:

> Beacon is a capability contract for how software projects communicate with autonomous agents.

Menhir is one implementation that can answer that contract using temporal, structural, and historical reasoning.

## 2. What the review got right

### 2.1 Beacon and Menhir must stay separate

We agree completely.

Beacon should remain lightweight and implementation-independent. Menhir can be opinionated, powerful, and complex, but Beacon should not require users to adopt Menhir.

The intended relationship is:

```text
Beacon
  capability contract / project-agent interface

Menhir
  rich provider / engine that generates and maintains high-quality Beacon answers
```

This separation preserves:

- lightweight adoption
- multiple providers
- backend independence
- room for non-Menhir implementations
- a clearer ecosystem story

### 2.2 Static manifests alone are not enough

We agree.

If Beacon is only `beacon.yaml`, it risks becoming another passive repo file next to `AGENTS.md`, `CLAUDE.md`, `llms.txt`, or a long README section. Static files rot. If agents learn to distrust Beacon because the first Beacons they encounter are stale, the project fails.

Beacon must be queryable and status-aware.

### 2.3 The LSP analogy is useful

The review introduced a strong analogy:

> Beacon is like LSP for Agent-to-Project communication.

This is more useful than the earlier OpenAPI-only analogy in some contexts.

LSP does not standardize compiler internals. It standardizes useful questions an IDE can ask a language server.

Likewise, Beacon should not standardize every internal representation of project knowledge. It should standardize useful questions an agent can ask a project.

Examples:

- What is this project?
- What should I read first?
- What are the guardrails?
- What files are relevant to this task?
- What decisions are current?
- What changed recently?

### 2.4 Standardization fatigue is a real risk

We agree.

Beacon should not be presented as yet another file format competing for attention. The world does not need one more passive AI-instructions file unless it creates a materially better interaction model.

The way to avoid this is to make Beacon capability-first and provider-backed.

## 3. Where we disagree or refine the review

### 3.1 Beacon should not be only an MCP profile

The review recommends framing Beacon as an MCP profile or convention.

We agree that MCP is the best first transport, but we do not want Beacon's identity to depend on MCP.

The preferred layering is:

```text
Beacon Specification
  defines capability contract

Beacon Providers
  answer capabilities from different backends

Beacon Transports
  expose capabilities over MCP, HTTP, CLI, static export, or future protocols
```

MCP is a transport. It should be first-class, but not exclusive.

### 3.2 `beacon.yaml` is not Beacon, but it still matters

The review warns that the static manifest may rot. That is correct.

However, manifests still have value as bootstrap artifacts.

They provide:

- offline availability
- version control
- inspectability
- portability
- basic provider input
- simple adoption path

The right analogy is not:

> `beacon.yaml` is the whole product.

The better analogy is:

> `beacon.yaml` is more like `package.json`, `Cargo.toml`, or `go.mod`.

It bootstraps the ecosystem. It does not replace the live provider.

### 3.3 Beacon should expose declared and observed knowledge

The review proposes that Beacon should represent maintainer intent rather than actual project reality.

We think the stronger model is to distinguish both.

#### Declared knowledge

Maintainer intent:

- intended architecture
- documented conventions
- safe edit boundaries
- current roadmap
- design goals

#### Observed knowledge

Evidence from the project:

- actual dependencies
- implementation structure
- Git history
- benchmark results
- drift from docs
- contradictions between sources

A powerful Beacon should be able to say:

> The declared architecture says A. The observed code currently does B. These diverged recently.

This is exactly where Menhir becomes valuable.

## 4. Revised architecture model

The revised model is:

```text
Beacon Specification
  |
  v
Beacon Capability Contract
  |
  |-- project_overview
  |-- agent_onboarding
  |-- search
  |-- explain_concept
  |-- guardrails
  |-- trace_decision
  |-- what_changed
  |-- find_files
  |
  v
Beacon Provider
  |
  |-- Manifest provider
  |-- Manifest + docs provider
  |-- Git-aware provider
  |-- Menhir provider
  |-- Enterprise docs provider
  |
  v
Beacon Transport
  |
  |-- MCP
  |-- HTTP
  |-- CLI
  |-- static JSON/YAML export
```

This keeps the core idea independent of any single backend or transport.

## 5. Capability-first design

Beacon should define the questions, not the storage model.

This is the key change from early manifest-centered thinking.

### Early framing

> What fields should exist in `beacon.yaml`?

### Better framing

> What questions should every project be able to answer for an autonomous agent?

The manifest can help answer those questions, but it is not the abstraction.

## 6. Proposed required v0 capabilities

Beacon v0 should remain small.

Initial required capabilities:

1. `project_overview`
2. `agent_onboarding`
3. `search`
4. `explain_concept`
5. `guardrails`

These are already enough to demonstrate the concept without requiring a complex ontology or Menhir-backed project graph.

## 7. Proposed future capabilities

Future capabilities should be optional until proven useful:

- `trace_decision`
- `what_changed`
- `find_files`
- `explain_symbol`
- `temporal_blast_radius`

These are where Menhir should differentiate itself.

A simple provider may only answer the first five capabilities.

Menhir should eventually answer the advanced capabilities with stronger temporal and structural evidence.

## 8. Design warning: avoid ontology trap

The review correctly warns against over-defining concepts and relationships in a rigid semantic ontology.

Beacon should avoid becoming RDF-for-agents.

The system should prefer:

- practical capability responses
- source-backed claims
- status/confidence labels
- simple extensible schemas
- implementation freedom

It should avoid:

- exhaustive project ontologies
- excessive type hierarchies
- fragile universal abstractions
- requiring every project to model itself the same way

## 9. Design warning: trust and staleness

Beacon must take staleness seriously.

Every response should ideally expose:

- status
- confidence
- sources
- freshness metadata where available
- uncertainty when appropriate

A Beacon that confidently returns stale information is worse than no Beacon.

This is another reason Menhir matters: temporal validity, supersession, and contradiction handling are not nice-to-have features for long-lived Beacons. They become core quality differentiators.

## 10. Menhir's role after this review

The review strengthens the case for Menhir, but changes how it should be introduced.

Do not lead with:

> Menhir is a temporal memory system.

Lead with:

> Menhir generates and maintains rich Beacons automatically.

Then explain that Menhir can do this because it models:

- temporal memory
- provenance
- code structure
- Git history
- project decisions
- documentation drift
- current vs superseded knowledge
- contradictions
- benchmark evidence

Beacon is the interface. Menhir is the engine.

## 11. Updated thesis

Beacon is not intended to replace documentation.

Beacon is not intended to replace MCP.

Beacon is not intended to replace code search.

Beacon defines a common capability contract through which software projects communicate their knowledge, intent, guardrails, and current state to autonomous agents.

Menhir is an implementation that can answer those capabilities using temporal, structural, and historical reasoning that extends beyond static documentation.

## 12. Immediate doc changes implied by this review

The documentation should be adjusted to:

1. Stop centering the project around `beacon.yaml`.
2. Describe `beacon.yaml` as one bootstrap provider input.
3. Present MCP as the first transport, not the whole concept.
4. Add the LSP-style analogy: Beacon standardizes Agent-to-Project communication.
5. Emphasize capability contracts over data schemas.
6. Separate declared knowledge from observed knowledge.
7. Treat Menhir as the rich provider, not the required backend.
8. Preserve the historical note that Beacon was created on 2026-06-29 from Menhir's prior project-understanding work.

## 13. Open questions after the review

1. Which capabilities are required for Beacon v0 compliance?
2. Which capabilities should remain optional extensions?
3. How should provider quality be advertised?
4. How should Beacon responses expose freshness and confidence?
5. Should Beacon have a registry later, or only discovery conventions?
6. Should transports be versioned independently from capability schemas?
7. How should declared-vs-observed divergence be represented?
8. What is the smallest useful `beacon-serve` implementation?
9. What does a Beacon client handshake look like?
10. What would cause an agent to distrust or ignore a Beacon?
