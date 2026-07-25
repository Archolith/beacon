# Beacon Provider Maturity Model

**Date:** 2026-06-29  
**Status:** roadmap/design note  
**Scope:** progressive adoption path from static Beacon to Menhir-backed dynamic Beacon

## 0. Purpose

Beacon should not be an all-or-nothing system.

A project should be able to start with a simple manifest and improve its Beacon over time without changing the client-facing capability contract.

This document defines a provider maturity model so Beacon adoption can progress from lightweight to powerful:

```text
Manifest
  -> Manifest + Docs
  -> Manifest + Git
  -> Manifest + Local Index
  -> Menhir Provider
```

The client continues to ask the same Beacon capabilities. The provider becomes more capable over time.

## 1. Why this matters

The static Beacon tier is useful but modest. It competes with existing project-level instruction files such as `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, and similar conventions.

The differentiated Beacon experience depends on dynamic capabilities:

- decision tracing
- change history
- structure-aware file discovery
- symbol explanation
- temporal blast radius
- declared-vs-observed divergence
- current vs superseded knowledge

Those capabilities should not require every adopter to immediately run a full Menhir stack.

The maturity model provides intermediate steps.

## 2. Provider tiers

| Tier | Provider | Primary value | Typical capabilities |
| --- | --- | --- | --- |
| 0 | Manifest | Bootstrap project identity and guardrails | overview, onboarding, basic guardrails |
| 1 | Manifest + Docs | Source-backed project search and concept explanations | search, explain_concept, citations |
| 2 | Manifest + Git | Recent change context and lightweight history | what_changed, freshness hints, stale-file detection |
| 3 | Manifest + Local Index | Structure-aware code understanding | find_files, explain_symbol, dependency hints |
| 4 | Menhir Provider | Temporal, structural, historical project reasoning | trace_decision, temporal_blast_radius, contradiction handling |

## 3. Tier 0 — Manifest Provider

Tier 0 uses only `beacon.yaml` or equivalent static project metadata.

### Strengths

- zero service dependency
- easy to inspect
- version controlled
- works for small projects
- cheap to adopt

### Weaknesses

- can silently rot
- limited search quality
- little or no observed knowledge
- cannot reason about code reality
- cannot trace decisions over time

### Expected capabilities

- `project_overview`
- `agent_onboarding`
- `guardrails`

## 4. Tier 1 — Manifest + Docs Provider

Tier 1 adds indexed documentation.

### Strengths

- source-backed answers
- line citations
- better concept explanations
- useful project search
- still lightweight

### Weaknesses

- docs can be stale
- cannot reliably detect architecture drift
- weak history
- weak code structure awareness

### Expected capabilities

- `project_overview`
- `agent_onboarding`
- `search`
- `explain_concept`
- `guardrails`

## 5. Tier 2 — Manifest + Git Provider

Tier 2 adds Git metadata and lightweight history.

### Strengths

- recent change awareness
- freshness signals
- stale doc detection hints
- simple `what_changed` support
- better provenance

### Weaknesses

- commit history alone does not explain intent
- weak semantic understanding
- limited decision tracing unless decisions are explicitly recorded

### Expected capabilities

- all Tier 1 capabilities
- lightweight `what_changed`
- freshness and staleness checks
- changed-file summaries

## 6. Tier 3 — Manifest + Local Index Provider

Tier 3 adds local code indexing such as file structure, symbol extraction, imports, and possibly tree-sitter parsing.

### Strengths

- structure-aware file discovery
- symbol explanation
- dependency hints
- observed code structure
- declared-vs-observed comparison begins to become possible

### Weaknesses

- still limited temporal reasoning
- cannot fully explain why decisions changed
- may require language-specific parsers

### Expected capabilities

- all Tier 2 capabilities
- `find_files`
- `explain_symbol`
- dependency and structure hints
- basic declared-vs-observed drift checks

## 7. Tier 4 — Menhir Provider

Tier 4 is the rich provider backed by Menhir.

Menhir can combine:

- temporal memory
- code structure graph
- Git history
- decision records
- documentation history
- benchmark evidence
- contradiction handling
- current vs superseded facts
- project memory

### Strengths

- decision tracing
- temporal reasoning
- contradiction detection
- supersession handling
- temporal blast radius
- richer declared/observed/derived knowledge
- best answer quality

### Weaknesses

- more operational complexity
- requires ingestion and maintenance
- may need local services or hosted deployment
- must earn trust with setup simplicity and observability

### Expected capabilities

- all Tier 3 capabilities
- `trace_decision`
- `temporal_blast_radius`
- strong `what_changed`
- contradiction handling
- current vs superseded knowledge

## 8. Progressive adoption principle

A project should be able to improve its Beacon without changing the client.

The client asks:

```text
project_overview
agent_onboarding
search
explain_concept
guardrails
trace_decision
what_changed
find_files
```

A low-tier provider may answer simply or return `unsupported` for advanced capabilities.

A high-tier provider answers with richer evidence.

This preserves a stable Agent-to-Project interface while allowing provider implementations to mature.

## 9. Provider quality metadata

Beacon responses should eventually expose provider quality metadata.

Example:

```json
{
  "provider": {
    "tier": 2,
    "name": "ManifestGitBeaconProvider",
    "supports": ["project_overview", "agent_onboarding", "search", "what_changed"],
    "unsupported": ["temporal_blast_radius"],
    "last_indexed_at": "2026-06-29T18:00:00-05:00"
  }
}
```

This lets agents calibrate trust.

## 10. Design implication

Do not make the static manifest carry the whole product story.

Beacon's strongest story is:

> Start simple. Keep the same interface. Upgrade the provider when the project needs richer answers.

Menhir then becomes the high-end provider, not a prerequisite for Beacon adoption.
