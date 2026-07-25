# Beacon as a Permissioned Semantic Object

## Status

Architecture refinement.

## Summary

Beacon is best understood not as a separate downstream artifact, but as a **permissioned Semantic Object**.

A Semantic Object is a typed composition of current Views around one stable subject identity. A Beacon is that same structured object made addressable under an explicit permission, disclosure, identity, and freshness contract.

> A Beacon is an addressable, permissioned Semantic Object whose current state can be discovered, queried, expanded, or subscribed to by authorized consumers.

The relationship is:

```text
Semantic Object
+ access policy
+ disclosure profile
+ addressability
+ revision/freshness metadata
+ optional signature
= Beacon
```

This unifies Beacon's capability-contract model with Menhir's structured semantic state without requiring two parallel object systems.

## Why this framing matters

Without a Semantic Object foundation, Beacon risks becoming a generated summary over loosely retrieved memories, documents, and project state. That can produce unstable fields, stale facts, inconsistent payloads, and weak change semantics.

With Semantic Objects, Beacon capabilities can bind to known Views:

```text
ProjectBeacon.status
  <- ProjectObject.status View

ProjectBeacon.blockers
  <- ProjectObject.blockers View

ProjectBeacon.owner
  <- ProjectObject.owner View
```

The factual payload becomes deterministic and lineage-aware. Language models may still generate presentation text, but they do not define the underlying state contract.

## One object, multiple Beacon surfaces

A Semantic Object may contain more state than any one audience should receive.

The same object can expose several permissioned surfaces:

```text
project:menhir
  |- beacon/public
  |- beacon/team
  |- beacon/partner-acme
  |- beacon/private-agent
  `- beacon/debug
```

Each surface references the same underlying semantic state but applies a different disclosure profile.

Example:

```text
ProjectObject
- objective
- status
- owner
- budget
- blockers
- internal decisions
- participants
- evidence lineage

Public Beacon
- objective
- status
- public blockers

Team Beacon
- objective
- status
- owner
- blockers
- participants

Private Agent Beacon
- all permitted Views
- expandable evidence lineage
```

No Beacon surface should duplicate or become authoritative over the underlying object.

## Permission model

Permissions should apply at the View and capability level, not only to the object as a whole.

```text
status        -> readable
budget        -> hidden
owner         -> team only
blockers      -> readable
View evidence -> expandable with elevated permission
raw memories  -> never exposed
change stream -> subscribable
```

A disclosure contract may define:

- which Views are readable;
- which fields are redacted or transformed;
- whether evidence may be expanded;
- whether historical state may be requested;
- whether changes may be subscribed to;
- whether child objects may be traversed;
- freshness requirements;
- audience and capability constraints.

## Suggested model

```json
{
  "beacon_id": "beacon:team:project:menhir",
  "object_id": "project:menhir",
  "object_type": "project",
  "schema_version": "1",
  "revision": 48,
  "issuer": "menhir://server-a",
  "audience": ["team:recall-labs"],
  "policy": {
    "profile": "team",
    "readable_views": ["objective", "status", "owner", "blockers"],
    "expandable_views": ["status", "blockers"],
    "redacted_views": ["budget", "internal_decisions"],
    "allow_history": false,
    "allow_subscribe": true
  },
  "updated_at": "2026-07-25T02:30:00-05:00",
  "signature": "optional-signature"
}
```

The Beacon definition references the object and policy. The current values remain owned by the underlying Views.

## Addressability and discovery

A Semantic Object becomes a Beacon when authorized consumers can resolve and interact with it through a stable address or capability handle.

A Beacon may support:

- discovery by type, subject, or capability;
- current-state reads;
- selective View expansion;
- evidence expansion;
- historical reconstruction where permitted;
- change subscriptions;
- traversal to related Beacon objects.

Addressability does not imply public visibility. Local, private, authenticated, organization, maintainer, and public Beacons can all share the same model.

## Revisions and change events

Because a Semantic Object is composed of independently maintained Views, Beacon revisions can expose targeted change events rather than republishing an opaque full summary.

```json
{
  "beacon_id": "beacon:team:project:menhir",
  "from_revision": 47,
  "to_revision": 48,
  "changes": [
    {
      "view": "status",
      "previous": "active",
      "current": "blocked"
    },
    {
      "view": "blockers",
      "added": ["OAuth provider approval"]
    }
  ]
}
```

Change generation should be based on View revisions or projection receipts rather than natural-language diffing.

## Evidence and lineage

A Beacon may expose compact receipts without publishing raw memory:

```json
{
  "status": {
    "value": "blocked",
    "view_id": "view:project-status:123",
    "assertion_frontier": "assertion:987",
    "evidence_count": 4,
    "updated_at": "2026-07-24T18:12:00-05:00"
  }
}
```

An authorized consumer may then request evidence expansion for that View. Expansion should preserve the distinction between:

- declared knowledge;
- observed knowledge;
- derived knowledge;
- raw supporting evidence.

Policies may permit compact receipts while denying assertion details or raw memories.

## Trust and signatures

Beacon is a natural signing boundary because it has:

- a stable issuer;
- a stable subject;
- a declared schema;
- an explicit audience;
- a revision;
- a bounded disclosed payload.

A signed Beacon can allow a receiver to verify:

- who issued it;
- which object it represents;
- which disclosure profile was applied;
- whether the payload was modified;
- which revision it supersedes;
- when it was issued and how fresh it is.

A signature proves provenance and integrity of the published Beacon. It does not independently prove that every underlying claim is true. Claim confidence and evidence lineage remain separate concerns.

## Provider independence

Beacon remains a provider-independent capability contract.

A static provider may construct a limited Semantic Object from declared project files. A Git-aware provider may add observed repository state. A local index may add derived summaries. Menhir can act as the richest provider by maintaining temporal Assertions, current Views, object identity, lineage, and historical reconstruction.

The maturity path remains:

```text
manifest
  -> documentation-aware provider
  -> Git-aware provider
  -> indexed provider
  -> temporal Semantic Object provider such as Menhir
```

The Semantic Object framing strengthens this progression without making Menhir mandatory.

## Relationship to existing Beacon concepts

This proposal preserves and clarifies the existing architecture:

- **Capability contract:** the Beacon defines what an authorized consumer may ask or observe.
- **Provider model:** different providers may construct Semantic Objects at different maturity levels.
- **Knowledge kinds:** declared, observed, and derived Views remain distinguishable.
- **Security and visibility:** disclosure is formalized as object- and View-level policy.
- **MCP transport:** MCP may expose Beacon capabilities but is not the Beacon itself.
- **Agent-to-Project communication:** Project Semantic Objects are one important Beacon subject, not the only possible object type.

## Object types

Beacon surfaces can apply to many Semantic Object types:

```text
ProjectObject       -> ProjectBeacon
PersonObject        -> PersonBeacon
IncidentObject      -> IncidentBeacon
DecisionObject      -> DecisionBeacon
OrganizationObject  -> OrganizationBeacon
TopicObject         -> TopicBeacon
```

Object schemas determine available Views. Beacon policies determine which of those Views and capabilities are exposed.

## Non-goals

This proposal does not require:

- publishing every Semantic Object;
- exposing raw memories;
- making all Beacons remotely accessible;
- storing separate copies for every audience;
- requiring Menhir as the backend;
- treating signatures as proof of factual truth;
- replacing transport-specific specifications.

## Initial implementation path

1. Define a minimal internal Semantic Object contract for Project state.
2. Define a Beacon policy object referencing allowed Views and capabilities.
3. Materialize one local private Beacon surface without duplicating state.
4. Add deterministic revision and View-level change events.
5. Add evidence receipts and permissioned expansion.
6. Add authenticated discovery and subscriptions.
7. Add optional signing and federation after the local contract stabilizes.

## Decision

Adopt the following architectural definition:

> Beacon is an addressable, permissioned Semantic Object.

Semantic Objects answer:

> What does this provider currently understand about this subject?

Beacon policies answer:

> What may this consumer discover, read, expand, traverse, or subscribe to?

Together they provide a coherent path from structured knowledge to safe Agent-to-Project and agent-to-agent exchange.
