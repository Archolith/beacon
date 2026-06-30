# Beacon Knowledge Kinds

**Date:** 2026-06-29  
**Status:** design note  
**Scope:** declared, observed, and derived knowledge in Beacon responses

## 0. Purpose

Beacon should not treat all project knowledge as the same kind of fact.

A project has:

- what maintainers say should be true
- what the repository currently shows
- what can be inferred by comparing the two

This document defines three knowledge kinds:

1. Declared knowledge
2. Observed knowledge
3. Derived knowledge

## 1. Declared knowledge

Declared knowledge is maintainer/project intent.

Sources include:

- `beacon.yaml`
- README
- architecture docs
- ADRs
- contribution guides
- guardrail declarations
- roadmap docs
- maintainer-authored notes

Examples:

```text
The project uses a provider abstraction.
```

```text
Generated files should not be edited.
```

```text
The canonical architecture doc is docs/architecture.md.
```

Declared knowledge answers:

- What does the project claim?
- What does the maintainer intend?
- What rules should agents follow?

## 2. Observed knowledge

Observed knowledge is evidence from the project itself.

Sources include:

- repository file tree
- code structure
- symbols
- imports/dependencies
- Git history
- test results
- benchmark outputs
- generated indexes
- CI results

Examples:

```text
The repository currently has five top-level packages.
```

```text
The file referenced by the onboarding guide does not exist.
```

```text
The build command failed on the current checkout.
```

Observed knowledge answers:

- What is actually present?
- What does the code do?
- What changed recently?
- What evidence exists?

## 3. Derived knowledge

Derived knowledge is inferred by comparing declared and observed knowledge, often across time.

Sources include:

- declared/observed comparison
- temporal memory
- decision history
- contradiction analysis
- benchmark changes
- structure graph joins
- git history joins

Examples:

```text
The manifest references a deleted file, so the onboarding path may be stale.
```

```text
The intended architecture says layer A should not depend on layer B, but the observed import graph shows that dependency exists.
```

```text
A benchmark claim is no longer supported by the current benchmark fixture.
```

Derived knowledge answers:

- What is stale?
- What contradicts what?
- What drifted?
- What assumptions were invalidated?
- What should the agent verify before acting?

## 4. Why this matters

A normal documentation file usually only exposes declared knowledge.

A code index usually only exposes observed knowledge.

A useful Beacon should expose the relationship between them.

That relationship is often the most valuable part.

Example:

```text
Declared: tests live under tests/.
Observed: this repo currently has no tests/ directory.
Derived: test guidance is stale or tests have not been added yet.
```

## 5. Menhir's role

Menhir is especially valuable for derived knowledge because it can reason across:

- time
- memory
- code structure
- Git history
- decisions
- superseded facts
- contradictions
- benchmark evidence

A simple provider can detect basic drift.

Menhir should eventually detect temporal and semantic drift.

Example:

```text
Declared: role-routing solves stale relevance.
Observed: later benchmark docs show per-family contribution caps are the current lever.
Derived: earlier role-routing guidance is superseded.
```

## 6. Response metadata

Beacon responses should eventually identify knowledge kinds.

Example:

```json
{
  "claims": [
    {
      "kind": "declared",
      "text": "The project uses a provider abstraction.",
      "sources": []
    },
    {
      "kind": "observed",
      "text": "The repo contains src/beacon/providers/manifest.py.",
      "sources": []
    },
    {
      "kind": "derived",
      "text": "The provider abstraction appears to be implemented in code and not only documented.",
      "sources": []
    }
  ]
}
```

## 7. Trust model

Declared knowledge should not automatically be treated as truth.

Observed knowledge should not automatically be treated as intent.

Derived knowledge should expose enough evidence for verification.

Beacon should help agents avoid collapsing these categories.

## 8. Design implication

When possible, Beacon should answer with language like:

- "The project declares..."
- "The repository currently shows..."
- "Beacon infers..."
- "This may indicate drift..."
- "This appears superseded by..."

That wording is more honest and safer than pretending every answer is a single flat truth.
