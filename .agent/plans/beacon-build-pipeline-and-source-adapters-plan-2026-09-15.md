# Beacon — Build Pipeline and Multi-Source Adapters

**Status:** DRAFT — NEEDS REVIEW
**Date:** 2026-09-15
**Update 2026-09-17:** v0.2 is **implemented** on `release/v0.2.0` (PR #4) — digests, canonical
JSON, the snapshot writer, and `beacon export` all exist there, verified by the restack onto
current `master` (695 tests passing against framework 0.3.0). Step 1's conditional ownership below
is resolved for good: this plan **consumes** that writer and builds only the snapshot **reader**
and the `beacon build` pipeline on top. §2 constraints 1–2 describe the pre-implementation
baseline and are historical.
**Owner:** Beacon
**Parent roadmap:** `docs/beacon-functional-product-roadmap.md` — v0.3 "Repository-aware Beacon"
**Siblings:**
`.agent/plans/beacon-v0.2-plan-2026-09-15.md` (publishes what this builds; **its WP4 owns the
canonical snapshot writer and source digests** — Step 1 below consumes that writer and adds the
reader, per that plan's §11),
`archolith-bench/.agent/plans/beacon-view-contract-and-full500-gate-2026-08-09.md` (runtime Menhir View
read boundary — see §7 Q1),
`.agent/plans/beacon-multi-intent-beacons-plan-2026-09-15.md` (owns the base-beacon contracts; this plan
supplies an optional way to fill them — see §6 R5 for the ordering constraint)

## 1. Goal

Give Beacon a **build step**. Today a manifest is read at server startup and answered from memory.
This plan adds `beacon build` / `beacon refresh`: a pipeline that reads several sources, merges them
under an explicit precedence policy, and writes an immutable, digest-addressed snapshot that the
server then serves deterministically.

Three properties define it:

- **A floor that always works.** git + docs + file inventory, no Menhir, no network, no model. This is
  the roadmap's own v0.3 goal — "make Beacon useful for a small coding task *without requiring Menhir*"
  (roadmap:255) — and it is what makes Beacon work on a repository it has never seen before.
- **Optional enrichment above the floor.** Menhir adds lifecycle/history; an LLM stage adds drafting.
  Each is a source among sources, not a dependency. Turning either off degrades the answer, never
  breaks the build.
- **Cache by content, not by clock.** Every record records the digests it derives from. Unchanged
  digests mean the record is copied forward, never recomputed.

Non-goal: this plan does not add MCP tools, does not change the five answer contracts, and does not
touch trust/signing (owned by the federation plan).

## 2. Constraints (from current code)

1. **There is no build step and no snapshot writer.** *(Historical as of 2026-09-17: the v0.2
   implementation on `release/v0.2.0` ships `init`, `export`, `serve-http`, and the writer; only
   `build`/`refresh` remain to be added by this plan.)* `src/beacon/main.py` registers exactly three
   commands — the default `serve` (`:45`), `validate` (`:72-73`), `inspect` (`:122-123`). `beacon build`,
   `refresh`, and `export` do not exist. (The v0.2 plan approved `init`/`export`; neither was written.)

2. **Nothing computes a digest.** *(Historical as of 2026-09-17: `release/v0.2.0` computes and
   publishes source digests through `beacon export`.)* A search for `sha256|hashlib|digest` across `src/beacon/` returns
   nothing, while `docs/schemas/beacon-snapshot-1.0.schema.json` *requires* `manifest.source_sha256`
   and a per-document `source_sha256` (`$defs.documentBase.required`). **The snapshot contract has
   fields that no code produces.** That gap is the cheapest, highest-value thing in this plan.

3. **The index is in-memory and startup-built.** `DocIndex.from_docs()`
   (`src/beacon/core/doc_index.py:64`) chunks Markdown at headings at lifespan startup
   (`src/beacon/mcp/lifecycle.py:51-55`). There is no persisted artifact between builds and queries.

4. **Search is bag-of-words.** `DocIndex.search()` (`doc_index.py:81`) scores token overlap with a
   heading boost. It is deterministic and offline — a property to preserve as the fallback, not a
   ceiling to accept.

5. **Only one source type exists.** The manifest's `canonical_docs` is the sole input; `BeaconManifest`
   (`src/beacon/core/schema.py:139-150`) has no field for git, file inventory, symbols, or benchmarks,
   and `BeaconSource` (`:45-58`) already types `doc | file | symbol | commit | issue | memory |
   benchmark | human_note` — **the source taxonomy is declared but only `doc` is produced.**

6. **A snapshot may not carry errors.** `validation.errors` is `{"const": 0}` in the schema. A build
   that cannot resolve its inputs fails; it does not publish a degraded artifact silently.

7. **Two release gates constrain the LLM stage.** "Rebuilding unchanged inputs is idempotent and
   produces a content-identical canonical snapshot" (roadmap:100) and "provider failures degrade to an
   explicit fallback or error state rather than fabricated answers" (roadmap:103). Also: "mandatory
   runtime LLM synthesis" is listed Outside v1 (roadmap:132) — *mandatory* and *runtime*, which permits
   an optional build-time stage and forbids a required query-time one.

## 3. Source tiers

Each tier is independently switchable. A build states which tiers ran, and the snapshot records it.

| Tier | Sources | Requires | If absent |
| --- | --- | --- | --- |
| 0 — floor | manifest, canonical docs | nothing | build fails (this is the minimum) |
| 1 — repository | git log/diff, file inventory, selected symbols, decision records, benchmark metadata | a git checkout | records omitted, confidence lowered |
| 2 — memory | Menhir: lifecycle/supersession, decision history, conflicts, structure graph | Menhir reachable *and* project ingested | records omitted; no lifecycle claims made |
| 3 — drafting | LLM over tier 0-2 records | a model endpoint | manifest prose used as-is |

Tier 2 is deliberately *not* the top tier. Menhir supplies facts, not judgments; the drafting tier sits
above it because drafting consumes everything below.

## 4. Precedence policy

The merge is the hard part. The architecture review named it as underestimated: multiple sources in a
naive provider push conflict resolution back onto the agent, which defeats the purpose. The roadmap
requires a policy layer that "merges records, resolves lifecycle state, and fails closed on ambiguity"
(roadmap:197).

The rule, taken from that same review's framing — **the manifest is intent, the code is reality**:

| Question kind | Authority | Example |
| --- | --- | --- |
| Intent — what *should* be true | manifest | guardrails, non-goals, "do not touch X" |
| Reality — what *is* true | git / files / symbols | which files exist, what changed, actual paths |
| History — what was *decided* | Menhir | current vs superseded, why, when |

Three consequences:

1. **A source may not answer outside its authority.** An LLM-drafted guardrail is a *proposal* until a
   maintainer commits it to the manifest; git cannot declare intent; the manifest cannot assert a file
   exists that the inventory says does not.
2. **Divergence is a finding, not a tie to break.** When intent and reality disagree, the build emits a
   `drift` record naming both sides and their citations. This is arguably the pipeline's most valuable
   output — "your README quick start changed, your manifest's install concept did not" — and it is the
   CI gate the architecture review asked for.
3. **Ambiguity fails closed.** An unresolvable conflict lowers confidence or omits the record. It never
   produces a high-confidence claim, per roadmap:93-94.

## 5. Proposed steps

### Step 1 — Snapshot reader and `beacon build` entry point

**Files:** new `src/beacon/build/snapshot.py` (reader), `src/beacon/main.py`

*(Revised 2026-09-17: the writer half of this step is done.)* `release/v0.2.0` already computes
`sha256` digests for the manifest and each canonical doc and emits snapshots conforming to
`beacon-snapshot-1.0.schema.json` via `beacon export` (`src/beacon/core/snapshot.py`,
`src/beacon/core/canonical_json.py`). What remains here is the reverse path — load a snapshot
instead of re-reading the repo — so the server can run snapshot-only, plus `beacon build
[--out snapshot.json]` as the pipeline entry point that calls the adapters and then reuses that
same writer. Do not build a second writer or a second digest implementation.

**Ownership (resolved 2026-09-15; final 2026-09-17).** The digest computation and canonical writer
are v0.2 work, owned by `beacon-v0.2-plan-2026-09-15.md` WP4 under the command name `beacon export`
and implemented on `release/v0.2.0` (PR #4). This plan implements the snapshot **reader** plus
`beacon build` as the pipeline entry point, reusing that writer. There is no remaining conditional:
v0.2 shipped first, so WP4 is the writer's owner and this plan is its consumer.

### Step 2 — Source adapter interface + the repository tier

**Files:** new `src/beacon/sources/base.py`, `sources/docs.py`, `sources/git.py`, `sources/files.py`,
`src/beacon/config/settings.py`

One `SourceAdapter` protocol: `collect() -> Iterable[NormalizedRecord]`. Port the existing doc chunking
behind it (behavior unchanged — the current `DocIndex` tests are the regression gate), then add git and
file-inventory adapters. Source configuration with include/exclude and secret/generated-file defaults
lands here (roadmap:261) — **this is a security boundary, not a convenience**: the adapter reads whole
repositories and writes their content into a publishable artifact.

`NormalizedRecord` carries the envelope the roadmap already specifies (roadmap:172-188): identity,
kind, payload, lifecycle state and predecessor, times, confidence *plus the reason for it*, citations
with source digests, adapter version, freshness.

### Step 3 — Merge policy and drift records

**Files:** new `src/beacon/build/policy.py`

Implements §4. Takes records from all active adapters, resolves by authority, emits merged records plus
`drift` records. Fails closed on ambiguity. This is the file a reviewer should read hardest.

### Step 4 — Incremental invalidation

**Files:** `src/beacon/build/snapshot.py`, new `src/beacon/build/cache.py`

Each record stores the digests of every source it derives from. A rebuild recomputes a record only when
one of its digests changed; everything else is copied from the previous snapshot. Deleting a source
invalidates its dependents predictably (roadmap:101).

### Step 5 — Menhir as a tier-2 adapter

**Files:** new `src/beacon/sources/menhir.py` (optional extra dependency)

Reads lifecycle/supersession, decision history, conflicts, and structure locations through the same
normalized envelope the bench plan is defining. Concept `implementation_locations` and guardrail
`applies_to` come from the structure graph rather than being guessed — which matters because guessed
paths produce citations that do not resolve, failing the 100%-resolvable-citations gate (roadmap:98).

Hard boundary: the output snapshot must load and serve with Menhir switched off. Menhir enriches the
build; the artifact stays portable. (`beacon.yaml` non-goal: "Requiring Menhir or any external service";
roadmap:125: "Menhir as the first rich temporal provider, **not as a requirement**.")

**Menhir #120 is the MVP bridge, not the destination (recorded 2026-09-17).** Menhir now carries
generation work — `23f22c8` ("generate a validated Beacon from an indexed local project") and
`49b4033` ("provision isolated Beacon interpreter for portable CI tests"). That work generates a
Beacon manifest from an indexed project by driving Beacon through a subprocess compat layer; treat
it as the transitional MVP that proves the integration while Beacon has no build step. Long-term,
this step owns the real mapping: Beacon's Menhir adapter reads Menhir's evidence surface directly
and `beacon build` owns generation. Known debts in the bridge that this step must replace, not
inherit:

- **Brittle version pin.** Menhir's `src/menhir/services/beacon_compat.py` hard-fails unless
  `beacon.__version__ == "0.1.0"` exactly. The manifest schema stays `"0.1"` while the product
  version moves (`0.2.0rc2` on `release/v0.2.0`), so the bridge refuses the actual v0.2
  implementation. Menhir should gate on manifest compatibility, not product version.
- **Unresolved provenance.** Menhir-generated citations are typed `type=manifest` with an empty
  `path`, and the scan fingerprint is not persisted, so generated output cannot prove where its
  claims came from. Beacon's claim model (Step 3's merge policy, citations with source digests)
  supersedes this; the bridge output must not become the long-term citation format.

### Step 6 — Optional LLM drafting stage

**Files:** new `src/beacon/build/draft.py`, `docs/schemas/beacon-snapshot-1.1.schema.json`

Off by default. Drafts manifest content from tier 0-2 records — the `beacon init` "reviewable generated
manifest" (roadmap:239) — refreshes concept/guardrail wording when sources change, and summarizes drift.

Four rules make it compatible with §2.7:

1. **Output is a reviewable file**, not runtime output. Draft → maintainer reviews → commits. Publisher
   authority is preserved; nothing reaches an agent that a human did not accept.
2. **Cache key = source digests + model id + prompt version + generator version.** The schema's
   `generator` block (`distribution` + `version`) cannot express model or prompt identity today; snapshot
   1.1 must add it. Without this, improving a prompt leaves stale derived text served indefinitely.
3. **Never re-derive on an unchanged key** — copy forward. Models are not reproducible, so the cache is
   what makes the idempotent-rebuild gate satisfiable at all. This is a correctness rule, not an
   optimization.
4. **Mark derived vs. quoted.** Snapshot 1.1 needs a per-record flag distinguishing "a model wrote this
   from these sources" from "this is lines 12-34 of the README, verbatim". Agents should be able to tell,
   and `confidence` means little without it.

### Step 7 (optional, separable) — better retrieval, still not generation

**Files:** `src/beacon/core/doc_index.py`

Optional embedding/rerank for *selecting* chunks. Selection cannot fabricate; generation can. Keyword
search (§2.4) stays the always-present fallback so "manifest-only/snapshot mode works with no database,
network, or runtime LLM dependency" (roadmap:83) continues to hold.

## 6. Risks

**R1 — The adapter reads the whole repo and writes it into a publishable file. (Blocked until
addressed)** Secrets, `.env` files, generated artifacts, private paths. Step 2 must ship
include/exclude and secret defaults *in the same change* as the first repository adapter, not after.
The snapshot's `security_overrides` policy records exist for acknowledged exceptions — use them.

**R2 — Derived content in a snapshot weakens the trust story. (Mitigable)** The federation plan will
eventually sign snapshots; signing model-written prose asserts publisher authority over text no human
read. Mitigation: rule 6.1 (review before commit) plus rule 6.4 (derived flag) mean a signature covers
reviewed content and readers can see what was derived.

**R3 — Menhir's knowledge is uneven across projects. (Acceptable)** Menhir knows a project only if it
ingested it; on a fresh foreign repo tier 2 is empty and the build degrades to tiers 0-1. That is the
designed behavior, but it means Menhir-enriched beacons are strongest on projects Menhir has lived
alongside — worth stating plainly rather than implying uniform enrichment.

**R4 — Scope. (Mitigable)** This is the whole v0.3 release; Steps 1-2 are shippable alone and should be
sequenced that way rather than held for the full pipeline.

**R5 — Relationship to the multi-intent plan. (Mitigable)** That plan owns the base beacons as declared
contracts — purpose, source selection, completeness rules, guardrail scope — and holds hand-authoring as
the floor, because tier 0 here is manifest + docs with no Menhir and no model. This plan supplies an
**optional second way to fill** those contracts: the drafting stage (Step 6) generates a beacon body from
the sources the definition selects, and digest-based refresh (Step 4) keeps a generated one current when
its sources change.

The two are complementary, and the ordering constraint runs this way: the base-beacon definitions are the
generator's spec. `beacon build` cannot draft an `operate` view until `operate` is a defined shape, so the
multi-intent plan's §4 should land before this plan's Step 6.

The risk is directional drift, not contradiction — if this plan ships first and the docs lead with
`beacon build`, hand-authoring decays into an undocumented fallback and a project with no model or no git
checkout can no longer produce a beacon. Mitigation lives in both plans: hand-authored and generated
content pass the identical validator, and a hand-authored fixture stays in CI permanently
(multi-intent plan §8, R5b).

## 7. Open questions

1. **~~Build-time source or runtime provider for Menhir?~~ DECIDED 2026-09-15 (ctharvey): build-time
   now; runtime is a much later thing.** Menhir integrates as a Step 5 source adapter whose output is
   baked into the snapshot. The runtime `MenhirBeaconProvider` (roadmap:286, the bench plan's read
   boundary) is deferred, not rejected — it shares the normalized envelope and can be layered on later
   without reworking this plan.

   Why build-time wins now: the snapshot is required under either option (as the no-Menhir floor and as
   the outage fallback), so it is the foundation rather than a competing choice; it needs no live
   dependency and no uptime/auth/latency work; it satisfies the determinism gates without special
   cases; and a maintainer reviews the content before any agent sees it, which is the product's core
   trust promise.

   Revisit when: the dominant agent question turns out to be recent activity ("what changed this week,
   what is in flight") rather than orientation, or rebuilds cannot be triggered reliably and snapshots
   are chronically stale in practice.
2. **Is derived content allowed in a signed snapshot at all**, or must drafts stay in the manifest layer
   and never enter the snapshot directly? Cleanest answer is the latter (LLM writes YAML a human commits;
   the snapshot only ever contains reviewed content) — but it forecloses cheap auto-refresh. Needs a call.
3. **Snapshot 1.0 → 1.1 migration** — additive fields (`generator.model`, per-record `derived`) should be
   optional with defaults, per the v0.2 addendum's schema guardrail. Needs a compatibility fixture.
4. **Which model for the drafting tier**, and does it run locally? Affects reproducibility claims, cost,
   and whether "no network" holds during a build with tier 3 on.
5. **Does drift detection belong in `beacon build` or a separate `beacon check`?** CI wants a
   non-zero exit code on drift; a build that fails on drift cannot publish, which may be too strict.

## 8. Validation

- **Step 1:** a snapshot for this repo validates against `beacon-snapshot-1.0.schema.json`; every
  `source_sha256` matches a recomputed hash; server serving from snapshot returns answers identical to
  serving from the live manifest.
- **Step 2:** existing `DocIndex` tests pass unchanged (regression gate for the port); a git adapter
  fixture produces `commit`-typed `BeaconSource` records; an include/exclude fixture proves a seeded
  `.env` and a generated file are absent from the snapshot. **That exclusion test is the R1 gate and
  should fail loudly.**
- **Step 3:** a fixture where manifest and git disagree emits a `drift` record citing both, and does not
  present either as high-confidence; an ambiguous record is omitted rather than guessed.
- **Step 4:** rebuild with no changes is byte-identical (roadmap:100) and performs zero adapter reads;
  touching one doc rebuilds only its dependents; deleting a source invalidates its dependents.
- **Step 5:** build with Menhir off and on over the same repo — both produce valid snapshots, the
  Menhir-on one carries lifecycle records, and **the Menhir-on snapshot still serves with Menhir
  stopped.**
- **Step 6:** rebuild with unchanged sources makes zero model calls; changing only the prompt version
  invalidates derived records and nothing else; every derived record is flagged and carries the sources
  it was drafted from.
- **End to end:** generate Menhir's own `beacon.yaml` from this pipeline. Menhir has no manifest today,
  so this is simultaneously the dogfood test, the gap fix, and the "connect your agent to the Menhir
  Beacon" demo the strategy handoff is built around.

## 9. Coverage summary

**Inspected:** `src/beacon/main.py`, `core/doc_index.py` (public surface + search), `core/schema.py`,
`config/settings.py`, `mcp/lifecycle.py`, `mcp/server.py`, `mcp/contracts.py`, `mcp/tools/__init__.py`,
`mcp/tools/project_overview.py`; `docs/schemas/beacon-snapshot-1.0.schema.json` (full);
`docs/beacon-functional-product-roadmap.md` §3-§8; `docs/beacon-strategy-handoff.md` §0-§3;
`docs/beacon-mcp-roadmap.md` (header, §0); `.agent/plans/` (all four, headers + federation plan full);
`archolith-bench/.agent/plans/beacon-view-contract-and-full500-gate-2026-08-09.md` (objective,
non-goals, contract gate); Menhir's archived `menhir-beacon-architecture-review.md` and
`beacon-lsp-for-agents-proposal.md`. Digest absence verified by search across `src/beacon/`.

**Not inspected:** `core/loader.py`, `core/validator.py`, `provider/manifest_provider.py`,
`provider/base.py` bodies (Steps 1-3 touch loader/validator; read before implementing);
`tests/` (Step 2's regression gate needs them read at implementation time);
`beacon-cli-result-1.0` / `beacon-init-report-1.0` schemas (Step 1 adds a CLI command and should
conform to the former); the bench plan's phases 1-N (only its scope boundary was needed here);
Menhir's tool surface beyond names (Step 5 needs the actual envelope the bench plan defines).

**Assumptions without code evidence:**
- That Menhir can expose lifecycle/supersession and structure records through a stable read boundary —
  that boundary is what the bench plan is being written to decide, so Step 5 is blocked on it.
- That `DocIndex`'s chunking can move behind a `SourceAdapter` without behavior change; asserted from
  its signature (`from_docs`, `search`), not from reading `_chunk_markdown`'s body.
- That no current consumer depends on the server reading the manifest live at startup (Step 1 adds a
  snapshot path alongside it rather than replacing it, so this should hold, but it is untested).
