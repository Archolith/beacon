# Beacon as an open standard

> Status: direction, not yet a normative spec (2026-09-22)
> Scope: what Beacon standardizes, who owns what, how it is versioned and proven, and the track
> from the Menhir MVP showcase to a standard other projects adopt

## 1. The gap

Coding agents orient themselves in a repository by reading scattered files and guessing what is
current. The existing pieces each cover part of the problem:

| Existing | What it gives an agent | What it does not give |
|---|---|---|
| `AGENTS.md` | Instructions: how to build, test and behave in this repo | Structured facts, citations, what is current vs outdated |
| `llms.txt` | An index of a website's docs | Anything about a repository's code, decisions or state |
| Context7-style doc servers | Up-to-date API docs for third-party libraries | Understanding of *your* project |
| DeepWiki-style generated wikis | A vendor-generated description of a repo | Project ownership, review, or a way to say "this is wrong" |
| MCP | A transport for tools and resources | Any agreement on *what* a project should expose |

Beacon fills the gap between them: **a project-owned, structured, source-cited description of a
repository, bound to the commit it describes, that any agent can read and any backend can help
fill.** `AGENTS.md` says how to work here; a beacon says what is true here and how we know.

Beacon complements `AGENTS.md` rather than replacing it. A beacon can point to the project's
`AGENTS.md`, and nothing in Beacon asks a project to stop publishing one.

## 2. What the standard is

The standard is a set of versioned documents. Code and transports are implementations of it.

| Layer | Document | Schema |
|---|---|---|
| Intent | The project's own `beacon.yaml`: purpose, guardrails, commands, canonical docs | manifest model and validator (`src/beacon/core/schema.py`, `core/validator.py`); no published JSON schema yet |
| The ask | What a beacon needs, and which source may supply each field | [`beacon-requirements-1.0`](schemas/beacon-requirements-1.0.json) |
| Provider contract | What a memory or index backend may contribute, bound to a repository and commit | [`beacon-memory-evidence-1.1`](schemas/beacon-memory-evidence-1.1.schema.json) |
| Published beacon | The built result an agent reads | [`beacon-snapshot-1.0`](schemas/beacon-snapshot-1.0.schema.json) and the resource/index schemas in [`schemas/`](schemas/) |
| Consumer surface | The questions an agent can ask | the five MCP tools in the [README](../README.md#what-agents-can-ask) |

**The schemas are the standard; transports are bindings.** A provider's evidence is a JSON
document first. Beacon accepts it as a file (`--memory-evidence`) or over MCP (`--memory`,
`get_beacon_evidence`). A file needs no server, no SDK and no account, so it is the lowest bar
for a new provider.

## 3. Roles

| Role | Owns | Never does |
|---|---|---|
| Project | its `beacon.yaml`: what it is for, its rules, its commands | -- |
| Beacon (the tool) | the ask, scaffolding, building, validation, freshness checks, gap reports, every write into a project | invent purpose, guardrails or commands; depend on one backend |
| Memory provider (Menhir is one) | answering what it indexed about a project, bound to a commit | read the caller's checkout, write into a project, decide what a beacon contains |
| Consumer (an agent) | asking questions and citing the answers | treat a beacon as more current than its binding says |

## 4. Principles

1. **The project owns its words.** Purpose, guardrails and commands come only from the project.
   Other sources may fill facts; they are reported by source, never as the maintainers' words.
2. **Unknown is an answer.** A missing field is a reported gap, not an invented value. A document
   with no currentness claim is published as `unknown`, not `current`.
3. **Bound to reality.** Provider evidence names the repository and commit it describes; Beacon
   publishes it only against that checkout.
4. **Fail closed.** Unusable, stale or mismatched input refuses the build, and nothing is written.
5. **Small core.** A useful beacon must be writable by hand in minutes. Research on `AGENTS.md`
   (Gloaguen et al., 2026) found that long or LLM-generated context files can lower agent success
   and raise cost; Beacon must keep the required core small and let agents ask for detail on demand.

## 5. Conformance (proposed)

| Level | Claim | How it is checked |
|---|---|---|
| Producer | A repository publishes a valid beacon | `beacon validate` passes; required fields supplied |
| Provider | A backend's evidence is valid and truthfully bound | a provider conformance kit: schema, binding, refusal cases (unknown project, dirty index, stale commit) |
| Consumer | A server or agent reads beacons correctly | the resource and tool schemas; citations preserved |

The provider kit is the cheapest way to prove backends are swappable. It should ship with a
second, trivial provider (for example git-only) so Menhir is never a special case.

## 6. Versioning (proposed)

- Every schema id carries `major.minor`. A minor version only adds optional fields.
- A major version gets one release of overlap: the old version is still read, with a deprecation
  warning (as `beacon-menhir-evidence-1.0` is read by `--gaps-only` today).
- Schemas are versioned separately from the Beacon package; the spec lists which package versions
  implement which schema versions.

## 7. Distribution

- **Direct mode is the baseline and must always work.** A beacon lives in the repository, like
  `AGENTS.md` or `pyproject.toml`; an agent that can read the repository can read the beacon.
- **A registry is optional and later.** The Archolith Hub (directory, identity, trust, optional
  hosting) is the PyPI-like layer, planned in
  [`../.agent/plans/beacon-trust-hub-and-federation-plan-2026-08-09.md`](../.agent/plans/beacon-trust-hub-and-federation-plan-2026-08-09.md).
  Nothing in the standard may require it.

## 8. Evidence before claiming a standard

A format becomes a standard through use, not through a spec. Before calling Beacon one:

1. **It helps agents.** An agent-task evaluation shows beacon + `AGENTS.md` beats `AGENTS.md`
   alone on success and cost (see the scorecard in the
   [functional roadmap](beacon-functional-product-roadmap.md#8-evaluation-and-release-scorecard)).
2. **It works without Menhir.** Two maintained non-Archolith repositories publish beacons.
3. **Backends are swappable.** A second provider passes the conformance kit.
4. **It is cheap to adopt.** An unaided developer publishes a first beacon in 15 minutes (the
   open v0.2 gate).

## 9. Track

| Step | Outcome | Depends on |
|---|---|---|
| S0 Showcase | The Menhir local MVP demo: a repo with no beacon -> `--gaps-only` -> project fills `beacon.yaml` -> `beacon build --memory` with Menhir -> an agent reads it | Menhir MVP (Archolith/menhir#123), Phase 3 of the ownership plan |
| S1 Spec | This document becomes a normative spec: layers, field rules, versioning, the provider contract, and a published JSON schema for `beacon.yaml` itself | S0 |
| S2 Swappable | Provider conformance kit plus a second provider | S1 |
| S3 Authoring | An LLM-assisted workflow that proposes values for gaps with citations; the maintainer approves locally | S1 |
| S4 Adoption | Two external repositories; `AGENTS.md` interop documented; the task evaluation from section 8 | S2, S3 |
| S5 Governance | Consider a neutral home (for example, proposing it to the Agentic AI Foundation) | S4 |

## 10. Open decisions

- The published name: "Beacon" is shared by unrelated projects (for example the Ethereum Beacon
  Chain), which matters for search and discovery of a standard.
- Whether the spec lives in this repository or a separate `beacon-spec` repository.
- Whether a beacon should read an existing `AGENTS.md` as an intent source.
- Whether the file transport is required of every provider or only recommended.
