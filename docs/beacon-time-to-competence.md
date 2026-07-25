# Beacon Philosophy: Optimizing for Time-to-Competence

## Status

Architecture proposal.

## Summary

A Beacon is not primarily a transport protocol, API endpoint, or permission wrapper around a Semantic Object.

A Beacon exists to minimize the amount of time required for another intelligence—human or artificial—to become competent about a subject.

Rather than exposing a database, a Beacon exposes understanding.

## Core Principle

> **A Beacon's primary objective is to minimize Time-to-Competence for an authorized consumer.**

Traditional knowledge systems optimize for storing information.

Search engines optimize for retrieving information.

Semantic databases optimize for connecting information.

A Beacon optimizes for transferring understanding.

The measure of success is not whether all facts are available.

The measure of success is how quickly a consumer can begin making correct decisions.

## The Wrong Mental Model

A conventional API exposes data.

```text
Projects
Views
Assertions
Episodes
Memories
Edges
History
```

An LLM connected to that interface must discover:

- what matters;
- how concepts relate;
- what is current;
- what is obsolete;
- what terminology is used;
- where to begin.

The database is complete.

The consumer is not.

## The Beacon Mental Model

A Beacon behaves like an experienced engineer onboarding a new teammate.

Instead of exposing everything immediately, it answers the questions an intelligent consumer naturally asks.

1. What is this?
2. Why does it exist?
3. What should I understand first?
4. What is currently true?
5. What has changed recently?
6. What should I explore next?
7. Where is the supporting evidence?

A Beacon is therefore an adaptive onboarding interface rather than a static data service.

## Orientation Before Detail

The first interaction with a Beacon should create orientation rather than exhaustively enumerate knowledge.

A typical onboarding sequence may resemble:

```text
Discover Beacon
    ↓
Identity
    ↓
Purpose
    ↓
Core Concepts
    ↓
Current State
    ↓
Recent Changes
    ↓
Suggested Next Topics
    ↓
Evidence on demand
```

Only after orientation should detailed retrieval begin.

## Competence over Completeness

Consumers rarely need complete knowledge.

They need sufficient understanding to perform useful work.

A Beacon should therefore prioritize:

- foundational concepts;
- current architectural decisions;
- active work;
- known constraints;
- common terminology;
- unresolved questions;
- important relationships.

Large historical archives remain available but should not dominate initial interactions.

## Adaptive Knowledge Transfer

Different consumers require different onboarding experiences.

A first-time visitor may require:

- project overview;
- glossary;
- major concepts;
- current priorities.

A returning consumer may instead require:

- what changed;
- new decisions;
- newly introduced concepts.

An expert consumer may request:

- implementation details;
- historical evidence;
- architecture discussions;
- dependency graphs.

An automated consumer may request a narrow machine-readable state package without explanatory prose.

The underlying Semantic Object remains identical.

Only the presentation adapts.

## Teaching Metadata

Semantic Objects should be able to expose information specifically intended to accelerate learning.

Examples include:

- canonical terminology;
- recommended learning order;
- foundational concepts;
- frequently confused concepts;
- common misconceptions;
- high-value reference documents;
- current priorities;
- architectural landmarks.

This metadata is not business state.

It exists to accelerate understanding.

## Progressive Disclosure

Information should expand naturally.

```text
Overview
    ↓
Concept
        ↓
View
            ↓
Evidence
                ↓
Raw Memory
```

Consumers request deeper information only when needed.

This reduces context usage while preserving explainability.

## Evidence Remains First-Class

Orientation must never come at the expense of traceability.

Every summary, concept, recommendation, or current-state claim should be expandable into:

- supporting Views;
- Typed Assertions;
- Episodes;
- original evidence.

Consumers should always be able to answer:

> Why should I believe this?

## Humans and LLMs Share the Same Problem

Although Beacons are designed with AI agents in mind, the same principles improve human onboarding.

A new engineer.

A new teammate.

A future version of yourself returning months later.

An autonomous coding agent.

Each has the same objective:

> Become competent as quickly as possible.

A Beacon should optimize for that shared experience.

## Architectural Consequences

A Beacon is more than a permissioned Semantic Object.

It is an adaptive knowledge interface that:

- establishes orientation;
- transfers concepts before details;
- emphasizes current understanding;
- teaches terminology;
- highlights recent changes;
- recommends productive exploration paths;
- exposes evidence when requested;
- adapts to the consumer's knowledge and intent.

Permissions, transport protocols, subscriptions, and serialization formats are implementation concerns.

Time-to-Competence is the architectural objective.

## Decision

Beacon should be designed as an adaptive onboarding interface for transferring understanding, not merely exposing stored knowledge.

Its success should be measured by how rapidly an authorized consumer becomes competent enough to perform useful work, while preserving the ability to inspect supporting evidence at every level of abstraction.
