# Beacon Doctor Roadmap

**Date:** 2026-06-29  
**Status:** roadmap/design note  
**Scope:** validation, drift detection, freshness, and self-maintenance for Beacon

## 0. Purpose

Static Beacon manifests can rot.

If agents encounter stale Beacon answers marked as current or high-confidence, trust is broken. This is one of the main risks for Beacon adoption.

Beacon should therefore include first-class validation and drift-detection tools.

Working name:

```bash
beacon doctor
```

Related commands:

```bash
beacon validate
beacon inspect
beacon refresh
```

## 1. Core idea

Beacon should not rely only on humans keeping metadata fresh.

It should help maintain itself.

A Beacon provider should be able to compare declared knowledge against observable project reality and report drift.

Example output:

```text
$ beacon doctor

✓ beacon.yaml is valid
✓ README.md exists and is referenced
✓ build command succeeds
✓ test command succeeds

⚠ onboarding references deleted file docs/rungs/rung-2.md
⚠ architecture claims 4 layers, observed code index found 5 top-level packages
⚠ guardrail references src/generated/, but that path does not exist
⚠ last indexed 91 days ago

✗ canonical doc docs/architecture.md is missing
```

## 2. Commands

### `beacon validate`

Validate static schema and semantic consistency.

Checks:

- manifest parses
- required fields exist
- concept IDs are unique
- referenced docs exist
- guardrails have IDs/severity/scopes
- provider config is valid

This is the lowest-cost check and should work at Tier 0.

### `beacon inspect`

Print what Beacon believes about the project.

Useful for humans and debugging.

Examples:

```bash
beacon inspect overview
beacon inspect concepts
beacon inspect guardrails
beacon inspect provider
```

### `beacon doctor`

Run validation plus project-reality checks.

Possible checks by provider tier:

| Tier | Checks |
| --- | --- |
| Manifest | schema, references, guardrails |
| Manifest + Docs | doc existence, doc headings, citation coverage |
| Manifest + Git | stale files, recently changed canonical docs, last refresh |
| Local Index | symbol/file drift, missing paths, generated file checks |
| Menhir | supersession, contradiction, temporal drift, decision conflicts |

### `beacon refresh`

Refresh generated or derived Beacon state.

This might:

- rebuild doc index
- refresh Git metadata
- regenerate observed structure
- update last-indexed timestamp
- ask Menhir to re-ingest project memory

## 3. Declared / observed / derived checks

Beacon should distinguish:

### Declared

What the manifest/docs/maintainers say.

### Observed

What the repo, docs, Git history, and indexes show.

### Derived

What Beacon infers from comparing declared and observed knowledge.

Example:

```text
Declared: docs/generated/ is generated and should not be edited.
Observed: docs/generated/ does not exist.
Derived: guardrail scope may be stale.
```

Example:

```text
Declared: package has CLI command `beacon validate`.
Observed: no CLI command with that name is registered.
Derived: README or manifest may be ahead of implementation.
```

## 4. Freshness metadata

Every provider should eventually report freshness metadata.

Example:

```json
{
  "freshness": {
    "manifest_modified_at": "2026-06-29T18:00:00-05:00",
    "docs_indexed_at": "2026-06-29T18:05:00-05:00",
    "git_indexed_at": "2026-06-29T18:07:00-05:00",
    "provider_checked_at": "2026-06-29T18:10:00-05:00"
  }
}
```

Agents should be able to treat stale Beacon output differently from fresh Beacon output.

## 5. CI integration

Beacon should eventually support CI checks.

Example:

```bash
beacon doctor --fail-on error
beacon doctor --fail-on stale
beacon validate --strict
```

Possible policy modes:

- warn only
- fail on invalid schema
- fail on missing canonical docs
- fail on stale generated indexes
- fail on severe declared/observed divergence

## 6. Drift categories

Potential drift categories:

- missing referenced files
- stale canonical docs
- stale guardrail paths
- build/test command mismatch
- concept references with no sources
- deleted files still cited by Beacon
- architecture claims contradicted by code structure
- generated-file declarations contradicted by repo layout
- benchmark claims unsupported by benchmark files
- decision marked current but superseded elsewhere

## 7. Why this matters for product adoption

The static Beacon tier is only credible if users and agents can evaluate freshness.

Without doctor/validation support, Beacon risks becoming another static instruction file that silently rots.

With doctor/validation support, Beacon becomes self-auditing.

That gives Beacon a stronger story than `AGENTS.md` or `CLAUDE.md`:

> Beacon is not only structured. It can check whether its structure still matches the project.

## 8. Menhir-backed doctor

The Menhir provider should eventually provide the strongest doctor checks:

- current vs superseded facts
- contradiction detection
- decision history conflicts
- temporal drift
- stale assumptions
- blast-radius warnings
- documentation that was once true but is no longer true

Example:

```text
⚠ docs/architecture.md states that Oracle role-routing prevents stale relevance.
Observed decision history superseded this: per-family contribution caps are the current lever.
```

This is where Menhir can make Beacon materially better than static project instructions.

## 9. Roadmap priority

Recommended order:

1. `beacon validate` for schema and references.
2. `beacon inspect` for debugging provider state.
3. `beacon doctor` for static + docs checks.
4. Git freshness checks.
5. Local structure/index drift checks.
6. Menhir-backed temporal and contradiction checks.

Do not wait for Menhir to build the early doctor tools.

The early validation story is part of making the static tier trustworthy.
