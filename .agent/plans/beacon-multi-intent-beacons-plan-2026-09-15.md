# Beacon — Multiple Intent-Scoped Beacons Per Project

**Status:** DRAFT — NEEDS REVIEW
**Date:** 2026-09-15
**Owner:** Beacon
**Parent roadmap:** `docs/beacon-functional-product-roadmap.md`
**Related:** `.agent/plans/beacon-trust-hub-and-federation-plan-2026-08-09.md` (federation/trust; this plan
depends on none of it); `.agent/plans/beacon-build-pipeline-and-source-adapters-plan-2026-09-15.md`
(supplies an optional generation path for beacon *content* — see §4.1; this plan does not depend on it)

## 1. Goal

Let a single project serve **several beacons with different intents** from its own beacon root, instead
of exactly one beacon per project.

One project, several front doors. Menhir is the motivating case:

| Beacon | The agent's actual job | Wrong answer today |
| --- | --- | --- |
| `contribute` | "I am changing Menhir's code." | — (this is what the current single manifest assumes) |
| `operate` | "I am installing/running Menhir and it will not start." | gets architecture docs and guardrails about `BeaconProvider` |
| `consume` | "I am wiring Menhir's MCP tools into another project." | gets contributor onboarding for a codebase it will never edit |

This is explicitly **not** a multi-project registry. Each project hosts its own beacons; nothing here
indexes other people's projects. The Hub/directory question is owned by the federation plan and is out
of scope.

Three questions this plan answers:

1. Can the current architecture expose multiple beacons at all? — Yes, with a bounded refactor (§3).
2. What default intents ship? — Three (`contribute`, `operate`, `consume`), with `research` opt-in (§4).
3. If only one beacon is configured, is it served directly rather than behind an index? — Yes, and that
   is a hard invariant, not a convenience (§5).

## 2. Constraints (from current code)

Every constraint below is a thing the code does today, not a hypothetical.

1. **One provider per process, held in a module global.**
   `src/beacon/mcp/lifecycle.py:27` declares `_provider: ManifestBeaconProvider | None = None`;
   `get_provider()` (`:30-36`) returns it or raises. `beacon_lifespan` (`:43-77`) sets it once at
   startup. There is no key, no lookup, no second slot.

2. **Tools reach the provider through that global, with no context threading.**
   `src/beacon/mcp/contracts.py:23` imports `get_provider` at module scope; `BeaconBaseTool.get_provider`
   (`:56-57`) just calls it. A tool has no way to ask "which beacon am I serving?" — see
   `src/beacon/mcp/tools/project_overview.py:22`. This is the single most load-bearing constraint: the
   tool layer is not merely single-manifest by configuration, it is single-manifest by construction.

3. **Settings carry exactly one manifest path, and hard-fail without it.**
   `src/beacon/config/settings.py:28` (`manifest_path: str = ""`) and `__post_init__` (`:41-45`) raise
   `ValueError` when it is empty. `BEACON_MANIFEST_PATH` is a single path, not a list or a directory.

4. **The server object and its tool set are built at import time.**
   `src/beacon/mcp/server.py:20-35` calls `create_gateway_server(...)` at module scope with a fixed
   `always_visible` list of the five tool names, then `register_all_tools(mcp)` at `:37`. Nothing can
   vary per manifest, because no manifest has been read yet when this runs.

5. **stdio only.** `src/beacon/main.py:45-67` ends in `run_server(mcp)`, which is
   `mcp.run(transport="stdio")` in `archolith_mcp_framework`. `BeaconSettings.host`/`port`
   (`settings.py:37-39`) are read from env and consumed by nothing.

6. **The manifest schema has no concept of a beacon identity or an intent.**
   `BeaconManifest` (`src/beacon/core/schema.py:139-150`) has `project`, `purpose`, `audiences`,
   `core_concepts`, `canonical_docs`, `agent_guidance`, `build_and_test`, `guardrails`. A manifest
   describes *a project*, and the implicit assumption throughout is one manifest = one project.

7. **`audience` already exists and is a different axis — do not collide with it.**
   `project_overview.py:19` takes `audience: str = "coding_agent"`
   (`new_contributor|coding_agent|researcher|maintainer`) and `schema.py:145` has a free-text
   `audiences` tuple. **Audience is who is asking; intent is what they are trying to do.** A maintainer
   installing the thing and a maintainer refactoring it are the same audience with different intents.
   Intent must be a new axis that selects *which beacon*, while audience stays a *parameter within* a
   beacon.

8. **Composition primitives already exist in the dependency.** `FastMCP.mount(server, namespace=...)`
   (`fastmcp/server/server.py:2124`) composes servers with namespaced tool names, and `http_app()`
   (`fastmcp/server/mixins/transport.py:370`) returns a Starlette app that can be path-mounted. Nothing
   in §3 requires inventing transport or composition machinery.

## 3. Proposed steps

Ordered. Steps 1–4 are the feature; step 5 is optional and separable.

### Step 1 — Give a manifest an identity and an intent

**Files:** `src/beacon/core/schema.py`, `src/beacon/core/loader.py`, `src/beacon/core/validator.py`

Add to `BeaconManifest` (all optional, defaulted — constraint from
`beacon-v0.2-implementation-readiness-addendum`'s `no_manifest_schema_change` guardrail: existing
`beacon.yaml` files in the wild must still load unchanged):

```yaml
beacon:
  id: operate              # slug, unique within the project
  intent: operate          # contribute | operate | consume | research | <custom>
  title: Install and run Menhir
  primary: false           # exactly one beacon may be primary; see §5
```

A manifest with no `beacon:` block loads exactly as today and is treated as
`id=default, intent=contribute, primary=true`. That default is what keeps every existing deployment
working.

Validator additions: unique `id` across the resolved set, at most one `primary: true`, `id` is a safe
slug (it becomes a tool-name prefix and a URL path segment).

The base-beacon definitions from §4 — purpose, source selection, completeness rules, guardrail scope —
ship as **built-in intent definitions in the package**, not as something each project restates. A
project declares `intent: operate` and inherits the contract; `beacon validate` then checks that
project's `operate` beacon against it. A project may define a custom intent by supplying the same four
fields, which keeps the escape hatch open without making the common case verbose.

### Step 2 — Resolve a *set* of manifests instead of one path

**Files:** `src/beacon/config/settings.py`, new `src/beacon/core/registry.py`

`BeaconSettings` gains `manifest_paths: tuple[str, ...]` and a `BEACON_MANIFEST_DIR` env var, while
`manifest_path`/`BEACON_MANIFEST_PATH` stay supported and become "the set of one". Relax
`__post_init__` (`settings.py:41-45`) to require *at least one* of the two rather than the single path.

New `BeaconRegistry` resolves, in precedence order: explicit `BEACON_MANIFEST_PATHS` list →
`BEACON_MANIFEST_DIR` glob of `beacon.*.yaml` → single `BEACON_MANIFEST_PATH` → `./beacon.yaml`. It
returns an ordered mapping `{beacon_id: ManifestBeaconProvider}` and knows which one is primary.

Sharing: a per-intent manifest should not restate project identity, repository, and license. Add
`extends: beacon.base.yaml` support in the loader — a shallow per-field merge where the child wins.
Without this, four beacons means four copies of the `project:` block and guaranteed drift.

### Step 3 — Replace the provider singleton with a registry lookup

**Files:** `src/beacon/mcp/lifecycle.py`, `src/beacon/mcp/contracts.py`, all five files in
`src/beacon/mcp/tools/`

This is the real work, and it is the constraint from §2.1–§2.2.

- `beacon_lifespan` builds the whole registry and stores it in the module slot instead of one provider.
- `get_provider()` keeps working and returns the primary provider — so nothing that calls it breaks —
  and a new `get_provider_for(beacon_id)` serves the multi case.
- `BeaconBaseTool` gains a `beacon_id: str | None` attribute set at registration time;
  `get_provider()` (`contracts.py:56-57`) resolves through it. Tool *classes* stay as they are; what
  changes is that `register_all_tools` instantiates them **bound to a beacon** rather than free-floating.

`src/beacon/mcp/tools/__init__.py:25-28` changes from `tool_cls().register(mcp)` to
`tool_cls(beacon_id=...).register(mcp)`.

### Step 4 — Build the server from the registry, not at import time

**Files:** `src/beacon/mcp/server.py`, `src/beacon/main.py`

`server.py:20-37` currently runs at import. Convert to `build_server(registry) -> FastMCP`, called after
the registry resolves. Composition:

- **One beacon:** register the five tools directly on the root server. Tool names are byte-identical to
  today. No selector tool. (§5)
- **Two or more:** the primary beacon's tools are registered un-namespaced (still `beacon_search`), and
  each additional beacon is mounted with `FastMCP.mount(child, namespace=<beacon_id>)`
  (`fastmcp/server/server.py:2124`), producing `operate_beacon_search`, `consume_beacon_search`. Add one
  root-level tool, `beacon_list_beacons`, returning each beacon's `id`, `intent`, `title`, and the tool
  prefix to use — that is the index, and it costs one tool rather than a separate discovery surface.

Why the primary stays un-namespaced: see Risk R2. It makes "project adds a second beacon" a non-breaking
change for every client already connected.

### Step 5 — HTTP serving (optional, separable)

**Files:** `src/beacon/main.py`, `archolith_mcp_framework` (runner)

Wire the already-present `settings.host`/`port` (`settings.py:37-39`) to a `--transport http` option and
mount each beacon's `http_app()` (`fastmcp/server/mixins/transport.py:370`) at `/b/{beacon_id}/mcp`, with
`/` serving a small JSON index of the same data `beacon_list_beacons` returns. This is the shape a
project-owned public endpoint would take, and it is the natural join point with the federation plan's
per-beacon descriptor URLs — but nothing in steps 1–4 needs it, and it should not gate them.

## 4. Base beacons

A base beacon is a **declared contract**, not a document that happens to exist. Ship **three**. The
pressure is toward more; resist it, because every added beacon multiplies the maintenance surface and
the thing that kills this feature is manifests that rot.

Each base beacon is defined by four things, and `beacon validate` enforces them:

| Field | What it fixes |
| --- | --- |
| **purpose** | The question this beacon answers. One sentence, and the tiebreaker when deciding whether content belongs here. |
| **source selection** | Which doc roles/paths feed it — and, as importantly, which do not. |
| **completeness rules** | What a usable instance must contain. An `operate` beacon with no install command is incomplete and should fail validation, not ship thin. |
| **guardrail scope** | Which class of rules applies — operational, architectural, or integration. |

This definition is what makes a beacon testable rather than merely present, and it is a prerequisite
for §4.1: a generator cannot draft an `operate` view unless `operate` is a defined shape.

1. **`contribute` — default and primary.** "I am changing this codebase."
   - *Sources:* architecture and design docs, concept definitions, contributor guides, test config.
   - *Complete when:* it names read-first docs, test/build commands, and at least one guardrail.
   - *Guardrails:* architectural — what not to change without review.
   - This is exactly today's manifest content. Every project that has a beacon already has this one,
     whether or not it is labeled.

2. **`operate` — the one with the strongest evidence.** "I am installing, configuring, running, or
   troubleshooting this."
   - *Sources:* README quick start, install/setup docs, operations runbook, env/config reference, CLI
     help, troubleshooting. Explicitly **not** architecture ADRs or contributor guides.
   - *Complete when:* it names an install command, a start command, a readiness/verification check, and
     where logs live. Missing any of these fails validation — a thin `operate` beacon is the failure
     mode this beacon exists to prevent.
   - *Guardrails:* operational — "never hand-edit deployed files", "run setup before up".
   - Menhir's own CHANGELOG is the argument: multiple same-day entries on 2026-09-15 and 2026-09-14 are
     fixes for **cold-start evaluator agents misreading install docs** — `menhir up --help` describing a
     checkout requirement that no longer held, a `MENHIR_OPERATOR_KEY` line that did not exist,
     `--compose-neo4j` Docker-daemon ambiguity. Those are install-intent failures by agents handed
     contribute-intent material.

3. **`consume` — the integration front door.** "I am calling this project's API/MCP surface from
   somewhere else and will never edit it."
   - *Sources:* endpoint/tool reference, auth and tier docs, client configuration examples, versioning
     and compatibility notes.
   - *Complete when:* it names the surface (tools/endpoints), how to authenticate, and one working
     client configuration.
   - *Guardrails:* integration — rate limits, tier requirements, what is not a stable contract.
   - For Menhir this is the most externally-visible surface and the one least served by a contributor
     manifest.

**`research` — defined, not default.** Benchmarks, prior art, negative results. Menhir and
archolith-bench have a real corpus for this; most projects have none, and an empty beacon is worse than
an absent one. It gets the same four-field definition so it is ready when populated, and stays off
until it passes its own completeness rules.

**Rule for adding a fourth:** a new intent earns its place only when it would answer a question the
existing three answer *wrongly* — not merely a question they answer thinly. Thin coverage is a manifest
problem; wrong routing is an intent problem.

### 4.1 Two ways to fill a base beacon

The definitions above say what a beacon **is**. They say nothing about where its content comes from,
and both routes are first-class:

- **Hand-authored (the floor, always supported).** A maintainer writes the YAML. This must remain
  sufficient on its own, because the build pipeline's tier 0 is manifest + docs with no Menhir and no
  model. If a base beacon could only exist by generation, intents would become a tier-3 feature and
  would break that floor.
- **Generated (optional).** `beacon build` drafts the body from the sources the definition selects, a
  maintainer reviews and commits it. Shared facts — project identity, repository, license — come from
  one place via `extends:` (Step 2) or from the build, so the set does not drift apart field by field.

The definition is what makes generation possible at all: the four fields are the generator's spec and
the validator's contract at the same time. A generated `operate` beacon that omits the start command
fails the same rule a hand-written one does.

## 5. Single beacon is served directly — invariant, not convenience

**If exactly one beacon resolves, the server is indistinguishable from today's.** Five tools, original
names, no `beacon_list_beacons`, no namespace prefix, no index layer of any kind.

Two reasons this is an invariant with a test rather than a nicety:

- **Backward compatibility.** Every existing `BEACON_MANIFEST_PATH` deployment and every client config in
  `README.md`'s "Connecting an agent" section must keep working with zero edits. A namespace prefix would
  silently break all of them.
- **An index over one item is a lie.** It advertises a choice that does not exist and spends a tool slot
  and a round trip to tell the agent there was nothing to choose. The v0 surface is deliberately small
  (`docs/beacon-mcp-roadmap.md` §0); this keeps it small for the common case.

The index appears exactly when it has something to index. Combined with the primary-stays-un-namespaced
rule from Step 4, the transition is smooth in both directions: one beacon → two beacons never renames
an existing tool, and deleting the second beacon returns the server to the single-beacon shape.

## 6. Risks

**R1 — Provider-singleton refactor reaches every tool. (Mitigable)**
Steps 3 touches `lifecycle.py`, `contracts.py`, and all five tool modules. Mitigation: `get_provider()`
keeps its current signature and returns the primary, so the blast radius is the *binding* at
registration, not the call sites inside `endpoint()` bodies. Existing tests that drive one manifest
should pass unchanged — and if they do not, that is the signal the refactor went wider than intended.

**R2 — Adding a second beacon silently renames the first one's tools. (Mitigable — and mitigated by
design)** The obvious implementation namespaces *every* mounted beacon, so a project that adds `operate`
would rename `beacon_search` → `contribute_beacon_search` for every already-connected client, as a
side effect of a config edit. The primary-un-namespaced rule (Step 4) removes this. Worth stating
explicitly because the default behavior of `FastMCP.mount` is the broken version.

**R3 — Tool count grows 5× per beacon. (Acceptable, with a ceiling)**
Three beacons is 11 tools (5 primary + 5 namespaced + selector); four is 16. Tolerable, but it argues
directly for §4's three-default discipline and against a per-topic beacon habit. Revisit if a real
project needs more than four.

**R4 — N beacons rot N times faster. (Mitigable — reduced, not removed)**
The federation plan already names staleness as the thing that breaks agent trust, and an `operate`
beacon describing last release's install flow is worse than no beacon. Mitigations, in order of
strength:

- `canonical_docs` pointing at live files rather than restating their content in manifest prose — the
  discipline that already makes the existing manifest largely self-maintaining;
- `extends:` (Step 2) so shared facts live once;
- completeness rules (§4) turning a hollowed-out beacon into a validation failure rather than a quiet
  degradation;
- `beacon validate` checking every resolved beacon, not just one;
- and, where the build pipeline is in use, digest-based refresh so a generated beacon updates when its
  sources change.

Honest limit: this **reduces** the risk, it does not dissolve it. A hand-authored beacon still rots at
the rate its maintainer tends it, and hand-authoring stays supported by design (§4.1). Three beacons
tended badly are worse than one tended well, which is the real argument for §4's three-beacon ceiling.

**R5 — Intent and audience blur into each other. (Mitigable)**
Per §2.7 they are different axes, and a reviewer will reasonably ask why `operate` is not just
`audience=maintainer`. Mitigation: document the split once, in the schema docstring and the intent
table, and keep `audience` as a within-beacon parameter. If the distinction cannot be held in practice,
that is a real signal to collapse the feature back into richer `task_hint` filtering rather than to ship
a confused two-axis model.

**R5b — Generation could quietly become the only path. (Mitigable)**
If the build pipeline lands first and the docs lead with `beacon build`, hand-authoring decays into an
undocumented fallback, and a project without a model or a git checkout can no longer produce the
beacons this plan defines. Mitigation: §4.1 makes hand-authoring the floor, the validator treats both
identically, and the fixture pair in §8 keeps a hand-authored beacon in CI permanently.

**R6 — This overlaps `beacon_agent_onboarding(task_hint=...)`. (Acceptable — worth a reviewer's eye)**
That tool already does soft intent-filtering inside one manifest. The claim here is that some intents
need different *sources and guardrails*, not a different slice of the same ones — an `operate` beacon
cites the runbook and README, which a contribute manifest has no reason to list at all. If a reviewer
disagrees, the cheap experiment is to author Menhir's `operate` manifest first (Step 0 below) and
compare its answers against `task_hint="install menhir"` on the existing one.

## 7. Open questions

1. **Does Menhir get the first multi-beacon deployment?** It has no `beacon.yaml` at all today (checked:
   no manifest in the repo), so this plan's motivating case starts from zero manifests, not one. Authoring
   Menhir's `contribute` + `operate` pair is the natural pilot, but it is a separate piece of work in a
   separate repo and needs its own go-ahead.
2. **`extends:` merge semantics** — shallow per-field child-wins is proposed; list fields (`canonical_docs`,
   `guardrails`) could reasonably replace *or* append. Needs a fixture before implementation.
3. **Is `primary` the right selector**, or should the primary be positional (first resolved)? Explicit is
   proposed; a reviewer may prefer convention over configuration.
4. **Do namespaced tool names read well to a model?** `operate_beacon_search` is clear but ugly.
   `beacon_search__operate` or a `beacon` argument on a single tool set are alternatives with different
   discovery behavior. This is a tool-naming decision with real model-behavior consequences and deserves
   a quick empirical check rather than a taste call.
5. **Does step 5 (HTTP) belong in this plan's release at all**, or does it wait for the federation plan's
   descriptor/trust work so a public endpoint is never exposed without identity verification?

## 8. Validation

Per step, with the invariant tests called out because they are the ones that encode §5.

- **Step 1:** an existing `beacon.yaml` with no `beacon:` block loads unchanged and reports
  `id=default, intent=contribute, primary=true`. `beacon validate` rejects duplicate ids, two primaries,
  and a non-slug id.
- **Step 1 — completeness contract (§4):** an `operate` beacon missing its start command fails
  validation with a message naming the missing field; the same beacon with the field present passes.
  A hand-authored and a generated beacon are held to the identical rule — prove it with one fixture of
  each, since "generated content is judged more leniently" is exactly the failure this contract exists
  to prevent.
- **Step 2:** registry resolution precedence fixture covering all four sources; `extends:` fixture proving
  child-wins and that the base's `project:` block reaches the child.
- **Step 3:** the existing test suite passes untouched — this is the regression gate for the singleton
  refactor. Add one test that two registered beacons return *different* providers for the same tool class.
- **Step 4 — the two invariants:**
  - one resolved beacon → `tools/list` is exactly the five current names, no selector tool, no prefix
    (this is the §5 invariant, and it should fail loudly if someone later namespaces unconditionally);
  - two resolved beacons → primary's five names unchanged, second beacon's five present with prefix,
    `beacon_list_beacons` present and listing both.
- **Step 5:** `GET /` returns the same set `beacon_list_beacons` returns; each `/b/{id}/mcp` serves that
  beacon's five tools un-namespaced.
- **End to end:** `beacon inspect` against a two-beacon set prints both, and the same `task_hint` routed
  at the `operate` vs `contribute` beacon returns materially different docs — if it does not, R6 is real
  and the feature needs rethinking before release.

## 9. Coverage summary

**Inspected:** `src/beacon/main.py`, `src/beacon/mcp/server.py`, `src/beacon/mcp/lifecycle.py`,
`src/beacon/mcp/contracts.py` (provider access only), `src/beacon/mcp/tools/__init__.py`,
`src/beacon/mcp/tools/project_overview.py`, `src/beacon/core/schema.py` (field listing),
`src/beacon/config/settings.py`, `beacon.yaml`, `README.md`, `pyproject.toml`,
`.agent/plans/beacon-trust-hub-and-federation-plan-2026-08-09.md`,
`.agent/plans/beacon-v0.2-*` (headers/status), `docs/beacon-functional-product-roadmap.md` (§6 v0.8, §7,
§9), `docs/beacon-mcp-roadmap.md` (header, §0); `fastmcp/server/server.py:2124` (`mount`),
`fastmcp/server/mixins/transport.py:370` (`http_app`);
`archolith-mcp-framework/src/archolith_mcp_framework/server.py` (`create_gateway_server` is a pure
factory returning `FastMCP(**kwargs)` — confirms Step 4 may call it after import) and
`.../runner.py` (`run_server` is `mcp.run(transport="stdio")`, confirming constraint §2.5);
Menhir's `CHANGELOG.md` (cold-start entries) and absence of a `beacon.yaml`.

**Not inspected:** `src/beacon/core/loader.py`, `validator.py`, `doc_index.py`,
`provider/manifest_provider.py`, `provider/base.py` bodies (Steps 1–2 touch loader/validator; their
internals need reading before implementation, not before planning); the four non-overview tool modules
(assumed to follow `project_overview.py`'s `self.get_provider()` pattern — verified by the shared base
class in `contracts.py:56-57`, not by reading each file); `tests/` (not read — Step 3's gate is "existing
tests pass", which needs them read at implementation time); `docs/schemas/*.json`
(v0.2 snapshot/CLI contracts, which Step 1's schema change may touch).

**Assumptions without code evidence:**
- That `FastMCP.mount` composes cleanly with `WorkspaceSearchTransform`, which
  `create_gateway_server` installs — mount + transform interaction is unverified and is the most likely
  place Step 4 hits a surprise.
- That no consumer outside this repo imports `beacon.mcp.server.mcp` as a module-level object (Step 4
  would break that); unverified beyond this workspace.
