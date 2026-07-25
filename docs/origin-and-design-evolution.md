# Beacon Origin and Design Evolution

**Date:** 2026-06-29  
**Status:** historical/design-context note  
**Scope:** how Beacon emerged and how its framing changed on day zero

## 0. Why this note exists

Beacon was created today, 2026-06-29.

Because the idea evolved quickly, it is easy to accidentally describe it as if it had been part of Menhir's earlier design for days or weeks. It was not.

Menhir had prior context around temporal memory, structure-aware project knowledge, Git-aware reasoning, benchmarked retrieval, and project self-understanding. Beacon emerged from that context, but Beacon itself is a new project created today.

This note preserves the actual sequence so future docs do not blur the timeline.

## 1. Actual origin

Beacon began as a practical Menhir idea:

> Add a public MCP endpoint inside Menhir so people and agents can connect to the project and ask questions about it.

The original framing was essentially:

> Menhir should expose a public MCP endpoint about itself.

That endpoint would serve both as:

- a demo of Menhir
- an onboarding interface for agents
- a way for outside users to query project knowledge

## 2. First abstraction jump

The idea then became:

> Maybe this endpoint should have its own name and identity.

The name **Beacon** was chosen because it suggests a public signal that agents can discover and orient around.

At this stage, Beacon was still mostly thought of as:

> Menhir's public MCP endpoint.

## 3. Second abstraction jump

The next realization was that Beacon should not be limited to Menhir.

A project should be able to publish a Beacon even if it does not use Menhir.

That changed the model from:

```text
Menhir -> public MCP endpoint
```

to:

```text
Project -> Beacon -> Agent
```

Menhir then became one possible implementation/provider.

## 4. Third abstraction jump

The next version separated several ideas that were initially mixed together:

- Beacon as concept
- Beacon manifest
- Beacon MCP transport
- Beacon provider
- Beacon registry/discovery
- Menhir as rich generator/provider

This made the architecture healthier.

The model became:

```text
Beacon specification / capability contract
        |
        v
Beacon provider
        |
        v
Beacon transport
        |
        v
Agent
```

## 5. Fourth abstraction jump

External review challenged the early manifest-heavy framing.

The main critique was:

> If Beacon is mainly `beacon.yaml`, it risks becoming another static AI-instructions file that rots.

This critique was accepted.

The project then reframed Beacon as a **capability contract** rather than a file format.

The key question changed from:

> What fields belong in `beacon.yaml`?

To:

> What standard questions should every project be able to answer for an autonomous agent?

## 6. Current day-zero framing

As of the end of 2026-06-29, the working framing is:

> Beacon standardizes Agent-to-Project communication.

More specifically:

> Beacon is a capability contract that lets a project answer standard questions agents need before safely understanding or modifying the project.

MCP is the first transport.

`beacon.yaml` is a bootstrap input.

Menhir is the rich provider that can generate and maintain high-quality Beacon answers from temporal, structural, and historical project knowledge.

## 7. Day-zero evolution summary

The idea evolved through these stages in a single day:

```text
v0: Menhir should expose a public MCP endpoint.

v1: That endpoint can be called Beacon.

v2: Beacon should be useful outside Menhir.

v3: Beacon should separate manifest, provider, transport, and registry/discovery.

v4: Beacon should be a capability contract, not primarily a file format or MCP server.

v5: Menhir should be positioned as the rich provider that generates and maintains Beacons.
```

None of these earlier versions were necessarily wrong. Each version peeled away implementation details until the stronger abstraction became clearer.

## 8. Important correction for future writing

Avoid writing as if Beacon has been an established part of Menhir for a long time.

Better:

> Beacon emerged from Menhir's project-understanding work on 2026-06-29.

Avoid:

> Beacon has been evolving for weeks alongside Menhir.

Better:

> Menhir provided the context that made Beacon obvious, but Beacon itself was created today.

## 9. What Menhir contributed before Beacon existed

Menhir's prior work matters because it shaped the idea.

Relevant Menhir concepts included:

- temporal memory
- valid time / learned time
- current vs superseded knowledge
- code structure memory
- Git-aware project reasoning
- benchmarked retrieval
- project decision history
- contradiction handling
- provenance-aware answers

Beacon did not create these ideas.

Beacon gives them a clearer public interface.

## 10. Why this timeline matters

The timeline matters because Beacon's strength is not that it has a long implementation history.

Its current strength is that it rapidly clarified a product/interface layer that makes Menhir easier to explain and evaluate.

The honest story is:

> Beacon is a new interface idea born from Menhir's existing research direction. It may become the front door through which users understand why Menhir matters.

That is stronger and more accurate than pretending Beacon was always there.
