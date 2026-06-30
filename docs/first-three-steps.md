# Beacon First Three Steps

**Date:** 2026-06-29  
**Status:** near-term execution plan  
**Scope:** smallest credible Beacon v0, two reference providers, and conformance/demo flow

## 0. Purpose

Beacon should not begin with the full vision.

The first implementation goal is to prove the neutral interface:

> Can an agent connect to a project, negotiate capabilities, receive proactive context signals, ask standard project-introspection questions, and get sourced, scoped, freshness-aware answers?

This document defines the first three steps.

## Step 1 — Write the smallest credible Beacon v0 spec

Define the core contract, not the full ecosystem.

Beacon v0 should specify five surfaces.

### 1.1 Handshake

What happens when an agent connects?

The handshake should answer:

- What project is this?
- What provider is serving this Beacon?
- What capabilities are supported?
- What provider tier is active?
- What visibility scope is the caller in?
- What freshness/indexing metadata is available?
- What immediate context signals should the agent see before acting?

Candidate capability:

```text
beacon.handshake
```

### 1.2 Capability negotiation

Agents need to know what this Beacon can and cannot answer.

Candidate capability:

```text
beacon.get_capabilities
```

This should expose:

- supported capabilities
- unsupported capabilities
- provider tier
- transport details
- known limitations
- freshness/indexing status

### 1.3 Context signals

Beacon should not only answer questions. It should be able to proactively surface important context at session start.

Candidate capability:

```text
beacon.get_context_signals
```

Examples:

- docs are stale relative to code
- ADR was superseded
- generated files should not be edited
- risky files require maintainer review
- build/test commands are known
- provider index is stale

This is the wedge that makes Beacon more than structured project instructions.

### 1.4 Core queries

The first query set should be small.

Recommended v0 capabilities:

```text
beacon.describe_project
beacon.get_onboarding_path
beacon.find_relevant_files
beacon.explain_architecture
beacon.get_guardrails
```

These are enough to demonstrate useful agent-project interaction without requiring Menhir.

### 1.5 Response envelope

Every response should carry enough metadata for an agent to calibrate trust.

Required envelope fields:

- answer
- sources
- confidence
- freshness
- authority
- scope
- provider metadata
- warnings
- next actions

Do not ship freeform answers without this envelope.

## Step 2 — Build two reference implementations

A standard becomes credible when it is not secretly designed around one implementation.

Build two providers early.

### 2.1 Static Beacon provider

The static provider should read:

- `beacon.yaml`
- `AGENTS.md`, if present
- core docs
- lightweight Git metadata, if available

Purpose:

> Prove Beacon can be adopted cheaply.

It does not need deep reasoning. It needs honest answers, provenance, limitations, and explicit unsupported-capability responses.

### 2.2 Menhir Beacon provider

The Menhir provider should answer the same contract using richer sources:

- graph memory
- observed code structure
- temporal memory
- Git history
- decision history
- drift detection
- supersession
- provenance

Purpose:

> Prove the same Beacon interface can support much richer intelligence.

Menhir should not define the v0 spec. It should compete by producing better answers to the same spec.

## Step 3 — Create a conformance harness and demo agent flow

Standards spread when people can test compatibility.

The conformance harness should verify that providers satisfy the same contract.

Candidate CLI:

```bash
beacon validate .
beacon handshake .
beacon ask . describe_project
beacon signals .
```

### 3.1 Harness requirements

The harness should verify:

- required methods exist
- response schemas are valid
- notifications/signals have severity, scope, and evidence
- sources are present where claims require support
- declared, observed, inferred, and generated claims are labeled
- provider capabilities are accurately advertised
- unsupported capabilities fail explicitly

### 3.2 Demo agent flow

The demo should show Beacon doing something static instructions cannot do.

Example session start:

```text
Agent connects to Beacon.

Beacon:
- Read these files first.
- Docs are stale relative to src/auth.
- ADR-004 was superseded yesterday.
- Avoid editing generated files.
```

This is stronger than asking the agent to read AGENTS.md.

Beacon initiates sourced, timely context before the agent makes a bad move.

## 4. What not to do first

Do not start with:

- full registry
- full URI scheme
- complete transport neutrality
- Menhir-only advanced features
- ten mandatory tools
- universal ontology
- SaaS positioning

Those may matter later.

The immediate goal is proving a minimal neutral interface.

## 5. Success criteria

The first phase succeeds when:

1. A static provider and Menhir provider both satisfy the same v0 tests.
2. Agents can discover provider capabilities at connection time.
3. Responses include sources, freshness, authority, scope, and warnings.
4. Context signals can proactively warn an agent before it acts.
5. Advanced Menhir answers appear richer without changing the client contract.

If those are true, Beacon starts looking like a standard instead of a Menhir product wrapper.
