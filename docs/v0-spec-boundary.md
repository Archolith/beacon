# Beacon v0 Spec Boundary

**Date:** 2026-06-29  
**Status:** exploratory specification boundary  
**Scope:** v0 handshake, capability list, signals, response envelope, failure modes, and compliance expectations

## 0. Purpose

Beacon should not begin as a broad ecosystem push.

The v0 goal is smaller:

> Define a small, testable contract for project-context and project-introspection questions, then prove that two very different providers can answer those questions consistently.

This document draws the v0 boundary.

## 1. Non-goals for v0

Beacon v0 should not try to standardize everything.

Non-goals:

- universal project ontology
- full registry/discovery system
- hosted SaaS
- complete security model
- full Menhir temporal graph integration
- every possible MCP tool
- dependency-chain Beacon federation
- final protocol governance

The v0 should be a working contract, not a manifesto.

## 2. Required v0 capabilities

A Beacon v0 provider should implement these core capabilities.

### 2.1 `beacon.handshake`

Start-of-session handshake between an agent and a project Beacon.

Answers:

- What project is this?
- What provider is answering?
- What provider tier is active?
- What capabilities are supported?
- What visibility scope applies to this caller?
- What freshness/indexing metadata exists?
- Are there immediate warnings before the agent acts?

This is the first capability an agent should call.

### 2.2 `beacon.get_capabilities`

Return provider capability metadata.

Answers:

- Which capabilities are supported?
- Which are unsupported?
- Which are degraded or partial?
- Which provider tier is active?
- What are the known limitations?

This prevents agents from assuming every Beacon supports every possible operation.

### 2.3 `beacon.get_context_signals`

Return proactive context signals that should be surfaced before an agent starts work.

Examples:

- docs are stale relative to code
- ADR was superseded
- generated files should not be edited
- risky files require maintainer review
- provider index is stale
- build/test commands are known

Signals should include severity, scope, evidence, and suggested action.

This is the wedge that makes Beacon more than structured project instructions.

### 2.4 `beacon.describe_project`

Describe the project at a high level.

Answers:

- What is this project?
- What problem does it solve?
- Who is it for?
- What is in scope and out of scope?

### 2.5 `beacon.get_onboarding_path`

Provide task-aware or default onboarding guidance.

Answers:

- What should an agent read first?
- What commands should it know?
- What safe first steps exist?

### 2.6 `beacon.get_guardrails`

Return project rules and constraints for safe work.

Answers:

- What should not be touched?
- Which changes require review?
- Which files are generated or sensitive?
- Which conventions matter?

## 3. Recommended v0 capabilities

These are recommended but may be unsupported by the simplest providers.

### 3.1 `beacon.search_project_context`

Search project context with source attribution.

Answers:

- What does the project say about this topic?
- Which sources support the answer?
- What is current, experimental, stale, or uncertain?

### 3.2 `beacon.explain_architecture`

Explain the architecture at the appropriate depth.

### 3.3 `beacon.find_relevant_files`

Find files relevant to a task or topic.

### 3.4 `beacon.get_change_summary`

Summarize recent changes for a topic or time range.

### 3.5 `beacon.report_declared_vs_observed_drift`

Compare declared project intent against observed repository reality.

## 4. Optional advanced capabilities

These should not be required for v0 compliance.

They are where richer providers, especially Menhir-backed providers, can differentiate.

- `beacon.get_decision_history`
- `beacon.explain_symbol`
- `beacon.get_dependency_graph`
- `beacon.get_temporal_blast_radius`
- `beacon.trace_supersession`
- `beacon.report_contradictions`
- `beacon.federate_dependency_beacons`

## 5. Standard response envelope

Every Beacon response should use a standard envelope.

```json
{
  "capability": "beacon.describe_project",
  "answer": "...",
  "sources": [],
  "source_type": "declared | observed | inferred | generated | mixed",
  "confidence": "low | medium | high",
  "authority": "maintainer-authored | repository-observed | provider-inferred | generated-summary | external-source | unknown",
  "freshness": {
    "checked_at": "...",
    "source_modified_at": "...",
    "indexed_at": "..."
  },
  "scope": {
    "project": "...",
    "paths": [],
    "time_range": null,
    "visibility": "public | authenticated | organization | maintainer | local"
  },
  "provider": {
    "name": "...",
    "tier": 0,
    "supports": [],
    "unsupported": []
  },
  "warnings": [],
  "next_actions": []
}
```

The envelope is as important as the capability list. It lets agents calibrate trust and avoid treating every answer as equally authoritative.

## 6. Signal envelope

Context signals should use a structured envelope.

```json
{
  "signal_id": "docs-stale-auth",
  "severity": "info | warning | error | critical",
  "summary": "Docs are stale relative to src/auth.",
  "scope": {
    "paths": ["docs/auth.md", "src/auth/**"],
    "visibility": "authenticated"
  },
  "evidence": [],
  "source_type": "inferred",
  "authority": "provider-inferred",
  "confidence": "medium",
  "suggested_action": "Verify docs/auth.md before editing auth code."
}
```

Signals are not commands. They are prioritized evidence or warnings that should shape the agent's next actions.

## 7. Failure modes

A compliant provider should fail explicitly.

Examples:

```json
{
  "capability": "beacon.get_change_summary",
  "answer": null,
  "error": {
    "code": "unsupported_capability",
    "message": "This provider does not index Git history."
  },
  "provider": {
    "name": "ManifestBeaconProvider",
    "tier": 0
  },
  "warnings": ["Try a Git-aware or Menhir-backed provider for change history."]
}
```

Do not fake advanced answers from weak providers.

A weak honest answer is better than a confident fabricated answer.

## 8. Trust requirements

Every response should distinguish at least:

- maintainer-authored guidance
- observed repository facts
- inferred conclusions
- generated summaries
- executable instructions
- safety/guardrail policy

These do not have the same authority.

A Beacon client should be able to tell whether an answer is evidence, policy, inference, or instruction.

## 9. Compliance principle

A capability belongs in Beacon v0 only if at least two materially different providers can answer it.

Recommended proof set:

1. Static manifest provider
2. Manifest + docs provider or Menhir provider

If only Menhir can answer a capability, it should be an extension, not part of mandatory v0.

## 10. Reference implementation plan

Ship three things before claiming a broader standard:

1. Minimal static manifest provider.
2. MCP reference transport exposing Beacon v0 capabilities.
3. Compliance harness that asks the same questions of multiple providers.

This gives Beacon something concrete to standardize without trapping it inside MCP or Menhir.

## 11. Positioning constraint

Avoid leading v0 with vague phrases like "standard conversation" unless the concrete capabilities are listed immediately.

Preferred:

> Beacon is a capability contract for project context and project introspection. It lets autonomous agents ask consistent questions about a software project and receive sourced, scoped, freshness-aware answers.
