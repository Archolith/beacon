# Beacon Compliance Harness

**Date:** 2026-06-29  
**Status:** roadmap/design note  
**Scope:** how to test whether different providers satisfy the same Beacon capability contract

## 0. Purpose

Beacon should be testable.

The core protocol question is:

> Can two very different providers answer the same Beacon questions consistently enough for an agent client to rely on the interface?

A compliance harness is how Beacon avoids becoming only a slogan or a documentation convention.

## 1. Core idea

A compliance harness should run the same capability requests against multiple providers.

Example providers:

- static manifest provider
- manifest + docs provider
- Git-aware provider
- local index provider
- Menhir provider

The harness should verify:

- handshake exists and returns provider/capability metadata
- required capabilities exist
- required response envelope fields are present
- context signals have severity, scope, evidence, and suggested action
- source attribution is valid
- unsupported capabilities fail explicitly
- freshness/confidence/warnings are represented
- declared/observed/inferred/generated source types are distinguishable
- provider capabilities are accurately advertised

## 2. Why this matters

If Beacon only works with Menhir, it is not a protocol.

If Beacon only works with a static manifest, it is too weak.

Beacon becomes real when materially different implementations can answer the same client requests through the same contract.

## 3. Proposed commands

```bash
beacon compliance --provider manifest --fixture fixtures/basic_project
beacon compliance --provider docs --fixture fixtures/docs_project
beacon compliance --provider menhir --fixture fixtures/temporal_project
```

Small demo-facing commands:

```bash
beacon validate .
beacon handshake .
beacon ask . describe_project
beacon signals .
```

Possible aliases:

```bash
beacon test-provider
beacon conformance
```

## 4. Fixture design

The harness should include small fixture projects.

### 4.1 Basic project fixture

Contains:

- `beacon.yaml`
- README
- one source file
- one guardrail

Tests:

- handshake
- get capabilities
- context signals
- describe project
- onboarding path
- guardrails
- unsupported advanced capabilities fail explicitly

### 4.2 Docs project fixture

Contains:

- multiple docs
- concept definitions
- stale doc reference
- canonical docs list

Tests:

- search with citations
- explain concept
- missing file warning
- freshness metadata
- context signal for stale or missing docs

### 4.3 Git history fixture

Contains:

- multiple commits
- changed docs
- renamed file
- superseded decision note

Tests:

- change summary
- stale references
- declared vs observed drift
- signal for superseded or stale project context

### 4.4 Local index fixture

Contains:

- multiple modules
- exported symbols
- dependency relationships

Tests:

- find relevant files
- explain symbol
- dependency graph hints
- observed structure metadata

### 4.5 Menhir temporal fixture

Contains:

- decision history
- superseded docs
- contradictory assumptions
- temporal blast-radius scenario

Tests:

- decision tracing
- temporal blast radius
- contradiction reporting
- current vs superseded knowledge
- proactive temporal drift signal

## 5. Required v0 assertions

Every compliant v0 provider must satisfy these assertions for required capabilities.

### 5.1 Handshake assertions

Handshake includes:

- project identity
- provider identity
- provider tier
- supported capabilities
- unsupported capabilities
- visibility scope
- freshness/indexing metadata where available
- initial context signals or explicit empty signal list

### 5.2 Envelope assertions

Response includes:

- `capability`
- `answer` or explicit `error`
- `sources`
- `source_type`
- `confidence`
- `authority`
- `freshness`
- `scope`
- `provider`
- `warnings`
- `next_actions`

### 5.3 Signal assertions

Context signals include:

- `signal_id`
- `severity`
- `summary`
- `scope`
- `evidence`
- `source_type`
- `authority`
- `confidence`
- `suggested_action`

Signals should not be treated as commands. They are prioritized evidence/warnings.

### 5.4 Source assertions

Sources must include enough information to verify provenance.

Minimum source fields:

- source ID or path
- source kind
- title or label
- location if available
- visibility/scope if available

For text files, line ranges should be included when possible.

### 5.5 Unsupported capability assertions

Unsupported capabilities should return structured errors.

They should not return hallucinated or generic answers.

### 5.6 Trust assertions

Responses should distinguish:

- declared
- observed
- inferred
- generated
- mixed

The harness should reject providers that collapse every answer into undifferentiated text.

## 6. Golden-output tests

Beacon should avoid overfitting to exact prose.

Golden tests should verify structure and key claims rather than requiring identical wording.

Examples:

- answer is non-empty
- confidence is valid enum
- at least one source exists for sourced claims
- guardrail severity is preserved
- unsupported advanced capability returns correct error code
- declared/observed drift is represented as drift, not as a flat truth
- context signals include severity/scope/evidence
- handshake accurately advertises provider capability support

## 7. Provider comparison tests

Some tests should compare two providers over the same fixture.

Example:

```text
Manifest provider: reports declared project description.
Docs provider: reports same description plus README citation.
```

Both are valid.

The richer provider should improve provenance or detail without changing the capability contract.

## 8. Compliance levels

Possible compliance levels:

| Level | Meaning |
| --- | --- |
| Beacon Core | handshake, context signals, required v0 capabilities, envelope |
| Beacon Docs | core + docs search/concepts |
| Beacon Git | docs + change summaries/freshness |
| Beacon Index | git + file/symbol structure |
| Beacon Temporal | index + decision history/blast radius/supersession |

These map naturally to the provider maturity model.

## 9. Reporting

Example output:

```text
Beacon compliance report

Provider: ManifestBeaconProvider
Tier: 0

✓ beacon.handshake
✓ beacon.get_capabilities
✓ beacon.get_context_signals
✓ beacon.describe_project
✓ beacon.get_onboarding_path
✓ beacon.get_guardrails
⚠ beacon.search_project_context returned limited answer
✓ unsupported beacon.get_temporal_blast_radius returned structured error

Result: Beacon Core compliant
```

## 10. CI usage

Projects and providers should be able to run compliance in CI.

Examples:

```bash
beacon compliance --provider manifest --strict
beacon compliance --provider menhir --level temporal
```

This makes provider compatibility visible and prevents regressions.

## 11. Design principle

Do not accept a capability into Beacon Core unless the compliance harness can test it.

Do not accept a provider as compliant unless it fails honestly when it cannot answer.

The goal is not identical answers.

The goal is a reliable contract that agents can use across projects and providers.
