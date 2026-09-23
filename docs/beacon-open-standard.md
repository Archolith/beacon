# Beacon as an open standard

> Status: direction, not yet a normative spec (2026-09-22)
> Scope: what Beacon standardizes, who owns what, how it is versioned and proven, and the track
> from the Menhir MVP showcase to a standard other projects adopt

## 1. The gap

Coding agents orient themselves in a repository by reading scattered files and guessing what is
current. The existing pieces each cover part of the problem:

| Existing | What it gives an agent | What it does not give |
|---|---|---|
| `AGENTS.md` | A static file of instructions: how to build, test and behave in this repo | Answers to questions, citations, what is current vs outdated |
| `llms.txt` | An index of a website's docs | Anything about a repository's code, decisions or state |
| Context7-style doc servers | Up-to-date API docs for third-party libraries | Understanding of *your* project |
| DeepWiki-style generated wikis | A vendor-generated description of a repo | Project ownership, review, or a way to say "this is wrong" |
| MCP | A transport for tools and resources | Any agreement on *what* a project should expose |

Beacon fills the gap between them: **an MCP endpoint a project publishes that answers agents'
questions about the project, live and with citations.** Its answers come from what the project
states in its own `beacon.yaml`, what git shows, and what a memory backend has indexed, bound
to the commit they describe. Later, answers may also be synthesized by an LLM, inside the same
citation contract.

`AGENTS.md` is a file an agent reads whole; a beacon is an endpoint the agent asks. The agent
pulls only what its task needs, and the answer reflects the project's current state rather than
whatever was true when someone last edited a file. Beacon complements `AGENTS.md` rather than
replacing it: a beacon can point to the project's `AGENTS.md`, and nothing in Beacon asks a project
to stop publishing one.

## 2. What the standard is

The product is the endpoint. The standard is what the endpoint answers, where its knowledge comes
from, and how that knowledge is built and proven. Each layer is a versioned document; code is an
implementation of it.

| Layer | Document | Schema |
|---|---|---|
| Endpoint | The questions an agent can ask, and the shape of every answer | the five MCP tools in the [README](../README.md#what-agents-can-ask) and the resource/index schemas in [`schemas/`](schemas/) |
| Intent | The project's own `beacon.yaml`: purpose, guardrails, commands, canonical docs | manifest model and validator (`src/beacon/core/schema.py`, `core/validator.py`); no published JSON schema yet |
| The ask | What a beacon needs, and which source may supply each field (intent, declared, git, memory, inferred, derived; forge planned) | [`beacon-requirements-1.1`](schemas/beacon-requirements-1.1.json) |
| Provider contract | What a memory or index backend may contribute, bound to a repository and commit | [`beacon-memory-evidence-1.1`](schemas/beacon-memory-evidence-1.1.schema.json) |
| Snapshot | The built knowledge the endpoint serves, and its fallback when live sources are down | [`beacon-snapshot-1.0`](schemas/beacon-snapshot-1.0.schema.json) |

Agents reach the endpoint over MCP: stdio for a local beacon, HTTP for a remote one. On the
provider side the evidence is a JSON document first; Beacon accepts it as a file
(`--memory-evidence`) or over MCP (`--memory`, `get_beacon_evidence`). A file needs no server, no
SDK and no account, so it is the lowest bar for a new provider.

### How an answer is produced

The answer shape is fixed; what produces it may vary. Every answer says which mode produced it,
so an agent can weigh it.

| Mode | Source of the answer | Status |
|---|---|---|
| Static | the snapshot built by `beacon build` | shipped |
| Live | a memory provider queried when the agent asks, with the snapshot as fallback | roadmap v0.5 |
| Synthesized | an optional LLM answer broker over the same knowledge; output must pass schema and citation validation or it is discarded and the answer is `unanswered` | later; boundary in the [functional roadmap](beacon-functional-product-roadmap.md#optional-ai-answer-broker-boundary) |

## 3. Roles

| Role | Owns | Never does |
|---|---|---|
| Project | its `beacon.yaml`: what it is for, its rules, its commands | -- |
| Beacon (the tool and endpoint) | the ask, scaffolding, building, validation, freshness checks, gap reports, every write into a project, serving answers | invent purpose, guardrails or commands; depend on one backend |
| Memory provider (Menhir is one) | answering what it indexed about a project, bound to a commit | read the caller's checkout, write into a project, decide what a beacon contains |
| Consumer (an agent) | asking questions and citing the answers | treat an answer as more current than its binding says |

## 4. Principles

1. **The project owns its words.** Purpose, guardrails and commands come only from the project.
   Other sources may fill facts; they are reported by source, never as the maintainers' words.
2. **Unknown is an answer.** A missing field is a reported gap, not an invented value. A document
   with no currentness claim is published as `unknown`, not `current`. An LLM never fills a gap
   silently.
3. **Bound to reality.** Provider evidence names the repository and commit it describes; Beacon
   uses it only against that checkout.
4. **Fail closed.** Unusable, stale or mismatched input refuses the build, and nothing is written.
5. **Ask, don't stuff.** Research on `AGENTS.md` (Gloaguen et al., 2026) found that long or
   LLM-generated context files can lower agent success and raise cost. An endpoint avoids that:
   the agent asks for what its task needs instead of loading everything. The required core of
   `beacon.yaml` stays small enough to write by hand in minutes.

## 5. Conformance (proposed)

| Level | Claim | How it is checked |
|---|---|---|
| Producer | A project publishes a valid beacon | `beacon validate` passes; required fields supplied |
| Provider | A backend's evidence is valid and truthfully bound | a provider conformance kit: schema, binding, refusal cases (unknown project, dirty index, stale commit) |
| Endpoint | A server answers the tool contract correctly | answer schemas, citations present, answer mode declared, fallback to the snapshot when live sources fail |

The provider kit is the cheapest way to prove backends are swappable. It should ship with a
second, trivial provider (for example git-only) so Menhir is never a special case.

## 6. Versioning (proposed)

- Every schema id carries `major.minor`. A minor version only adds optional fields.
- A major version gets one release of overlap: the old version is still read, with a deprecation
  warning (as `beacon-menhir-evidence-1.0` is read by `--gaps-only` today).
- Schemas are versioned separately from the Beacon package; the spec lists which package versions
  implement which schema versions.

## 7. Distribution

- **The source lives in the repository.** `beacon.yaml` sits next to the code, like `AGENTS.md` or
  `pyproject.toml`, and is reviewed like code.
- **Agents reach the beacon through its endpoint.** Locally, the `beacon` stdio server; remotely,
  an HTTP endpoint the project or a host runs. A self-hosted endpoint must always work.
- **A registry is optional and later.** The Archolith Hub (directory, identity, trust, optional
  hosting) is the PyPI-like layer that lets an agent find a project's endpoint, planned in
  [`../.agent/plans/beacon-trust-hub-and-federation-plan-2026-08-09.md`](../.agent/plans/beacon-trust-hub-and-federation-plan-2026-08-09.md).
  Nothing in the standard may require it.

## 8. Evidence before claiming a standard

A format becomes a standard through use, not through a spec. Before calling Beacon one:

1. **It helps agents.** An agent-task evaluation shows an agent with a beacon endpoint and
   `AGENTS.md` beats `AGENTS.md` alone on success and cost (see the scorecard in the
   [functional roadmap](beacon-functional-product-roadmap.md#8-evaluation-and-release-scorecard)).
2. **It works without Menhir.** Two maintained non-Archolith repositories publish beacons.
3. **Backends are swappable.** A second provider passes the conformance kit.
4. **It is cheap to adopt.** An unaided developer publishes a first beacon in 15 minutes (the
   open v0.2 gate).

## 9. Track

| Step | Outcome | Depends on |
|---|---|---|
| S0 Showcase | The Menhir local MVP demo: a repo with no beacon -> `--gaps-only` -> project fills `beacon.yaml` -> `beacon build --memory` with Menhir -> an agent asks the beacon over MCP stdio | Menhir MVP (Archolith/menhir#123), Phase 3 of the ownership plan |
| S1 Spec | This document becomes a normative spec: layers, answer shapes and modes, field rules, versioning, the provider contract, and a published JSON schema for `beacon.yaml` itself | S0 |
| S2 Swappable | Provider conformance kit plus a second provider | S1 |
| S3 Live | The endpoint queries a memory provider when the agent asks, with snapshot fallback (roadmap v0.5) | S2 |
| S4 Authoring | An LLM-assisted workflow that proposes values for gaps with citations; the maintainer approves locally | S1 |
| S5 Synthesized answers | The optional LLM answer broker, inside the citation contract | S3 |
| S6 Adoption | Two external repositories; `AGENTS.md` interop documented; the task evaluation from section 8 | S2, S4 |
| S7 Governance | Consider a neutral home (for example, proposing it to the Agentic AI Foundation) | S6 |

## 10. Settled decisions

- **Declared sources (2026-09-23).** A beacon reads `AGENTS.md`, `CONTRIBUTING.md` and
  `SECURITY.md` as `declared` sources, alongside package manifests, the license file, CI
  workflows and the README. It never reads agent-vendor files (`CLAUDE.md`, `.cursor/rules` and
  similar); those should only point to `AGENTS.md`. `beacon init` writes only the fields a
  maintainer must answer; everything a project's files state is read at build time, never
  copied into `beacon.yaml`.

## 11. Open decisions

- The published name: "Beacon" is shared by unrelated projects (for example the Ethereum Beacon
  Chain), which matters for search and discovery of a standard.
- Whether the spec lives in this repository or a separate `beacon-spec` repository.
- Whether the file transport is required of every provider or only recommended.
- How an agent discovers a project's endpoint without the Hub (for example, a pointer in
  `AGENTS.md` or a well-known path).
