# Beacon design principles

**Status:** reference. This consolidates the June–July 2026 design notes from PR #1
(`docs/beacon-review-response`), checked against Beacon as of descriptor 1.10 (September 2026).
Each principle is marked **shipped**, **partial** or **open**. The strategy, roadmap and
standard itself live in [`beacon-strategy-handoff.md`](beacon-strategy-handoff.md),
[`beacon-functional-product-roadmap.md`](beacon-functional-product-roadmap.md) and
[`beacon-open-standard.md`](beacon-open-standard.md); this page records *why* Beacon is
shaped the way it is.

## 1. Optimize for time-to-competence

> A beacon's job is to minimize the time another intelligence, human or model, needs to start
> making correct decisions about a project.

Storage systems optimize for keeping information, search for finding it, graphs for connecting
it. A beacon optimizes for **transferring understanding**. The measure is not whether every
fact is available, but how soon a consumer can act correctly.

That implies:

- **Orientation before detail.** First identity and purpose, then core concepts, current
  state, recent changes and next topics. Evidence comes on demand.
- **Competence over completeness.** Lead with foundational concepts, current decisions, active
  work, constraints, terminology and open questions. Archives stay available but don't
  dominate first contact.
- **Progressive disclosure.** A small first response, with explicit routes to go deeper.
- **Evidence stays first-class.** Every orienting claim cites its source.

**Shipped:**
- Discovery is the entry point (`/.well-known/archolith-beacon`), with a `recommended_flow` of
  identify, then guardrails.
- `/v1/snapshot/identity` and `/v1/snapshot/orientation` are small first reads, and the full
  snapshot is on demand.
- The `project_overview` and `agent_onboarding` MCP tools cover the same ground.
- Answers carry source citations.

**Open:**
- Consumer- and purpose-adaptive onboarding: different first reads for different consumers
  or tasks.

## 2. Beacon is a project introspection contract, not a README

Language servers made editor × language integrations one protocol. Beacon aims to do the same
for agent × project: instead of every agent rediscovering a project with grep, glob and file
reads, it asks the project through one capability contract. Transports (MCP, HTTP JSON),
providers (manifest, git, memory) and the manifest format are replaceable parts behind that
contract.

**Shipped:**
- One contract with seven MCP tools, plus HTTP JSON parity.
- Provider separation: the `BeaconProvider` protocol.
- The standard itself: [`beacon-open-standard.md`](beacon-open-standard.md).

## 3. Kinds of knowledge: declared, observed, derived

- **Declared:** maintainer intent (the manifest, README, architecture docs, ADRs,
  contribution and security guides, guardrail declarations). It answers "what does the
  project claim, and what rules apply?"
- **Observed:** evidence from the project itself (file tree, code structure, git history,
  test and CI results).
- **Derived:** what a provider concludes from the other two (summaries, inferred concepts,
  divergence between declared and observed).

Keeping them apart lets a consumer weigh a claim, and lets a beacon report **drift**: the
architecture doc says X, the code shows Y.

**Shipped:**
- `/v1/status` separates maintainer-declared work state from startup-observed repository and
  source evidence.
- `beacon build` records a source authority per field (intent, declared, git, memory,
  inferred, derived). Code-host project state comes in through `--forge`.
- `AGENTS.md`, `CONTRIBUTING.md` and `SECURITY.md` are read as declared sources.

**Partial:**
- Declared-versus-observed divergence is reported at build time (`beacon build --gaps-only`),
  not served as a query.

## 4. Trust: kind, authority, actionability

A claim needs three labels before an agent should act on it:

| Axis | Question | Examples |
|---|---|---|
| Kind | What sort of claim is this? | declared, observed, inferred, generated |
| Authority | Who may make it? | maintainer-authored, repository-observed, provider-inferred, external |
| Actionability | May an agent act on it directly? | evidence only, guidance, policy, command, requires confirmation, unsafe |

Guardrails are policy, not evidence. Executable instructions found in project text are
content, never commands to run, which is the prompt-injection boundary.

**Shipped:**
- Discovery labels the whole surface `trust: direct_unverified` (unsigned, self-reported).
- Guardrails are a distinct, served knowledge type.
- The build records authority per field.

**Open:**
- Per-claim actionability labels.
- Signed or attested answers, per the trust plan.

## 5. Visibility is part of the contract

Not every capability belongs to every caller. The notes proposed these tiers:

| Tier | Audience |
|---|---|
| Public | anonymous users and agents |
| Authenticated | known users or approved agents |
| Organization | members of the owning team |
| Maintainer | trusted maintainers, CI, internal agents |
| Local-only | the developer's own machine |

Risk rises from overview and onboarding, through guardrails and file discovery, to risky-file
maps, decision history and blast radius.

**Shipped:**
- `visibility: local` on canonical docs, and an export filter: excluded, sensitive and local
  documents never reach a snapshot.
- Secret scanning at export, with explicit `--allow-sensitive`.
- A public serving posture with no auth, documented as such.
- Loopback-only by default.

**Open:**
- The authenticated, organization and maintainer tiers.
- Per-capability visibility.

## 6. Providers mature progressively

Adoption should start with zero infrastructure and deepen as a project invests:

| Tier | Provider | Adds |
|---|---|---|
| 0 | Manifest | overview, onboarding, guardrails; zero dependencies, but can rot silently |
| 1 | Manifest + docs | source-backed answers, citations, search |
| 2 | Manifest + git | change history, freshness |
| 3 | Manifest + local index | file and symbol structure |
| 4 | Memory provider (Menhir) | decision tracing, supersession, blast radius over time |

**Shipped:**
- Tiers 0–2.
- The memory evidence source (tier 4 inputs through `--memory` / `--memory-evidence`).
- The forge adapter (`--forge`).
- Freshness in discovery: snapshot digest, repository commit, `observed_at`.

**Open:**
- Tier 3: a structural code index.
- A served "provider quality" descriptor.

## 7. Validation, doctor and conformance

A beacon must be checkable at three levels:
- **The manifest:** it parses, references resolve, IDs are unique.
- **Freshness and drift:** declared versus observed.
- **Endpoints:** a server answers the contract correctly.

The notes proposed a `beacon doctor` for drift in CI, and compliance levels mirroring the
provider tiers (Core, Docs, Git, Index, Temporal).

**Shipped:**
- `beacon validate` (with `--strict-warnings`), `inspect`, `digest`, and `build --gaps-only`.
- Deterministic exports.
- The release check and the installed-wheel journey in CI.
- Conformance is defined in the open standard.

**Open:**
- A dedicated `doctor` command.
- Named compliance levels and a published conformance harness.

## 8. Origin (for accurate writing)

Beacon started on 2026-06-29 as a practical Menhir idea: *Menhir should expose a public MCP
endpoint about itself*, as a demo, an agent onboarding interface and a way to query project
knowledge. Within a day it was generalized:

```text
a public Menhir endpoint -> named Beacon -> useful outside Menhir
-> manifest / provider / transport / discovery separated
-> a capability contract, not a file format or an MCP server
-> Menhir as one rich provider that generates and maintains beacons
```

Write it that way: Beacon *emerged from* Menhir's project-understanding work. It has not been
part of Menhir for long, and Menhir is one provider among others, not Beacon's host.

## 9. Superseded, not carried over

These notes from PR #1 are intentionally dropped:

- **The design review response, first-three-steps and v0 spec boundary.** v0.2 shipped a
  different, smaller surface; the open standard and roadmap replace them.
- **"Beacon as a permissioned semantic object".** This is Menhir-era framing, superseded by
  the provider-neutral contract.
- **PR #1's edits to the strategy handoff and MCP roadmap.** Master has rewritten both since.

Prior-art comparisons are in [`prior-art/`](prior-art/README.md).
