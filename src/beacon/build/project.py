"""Deterministic projection: resolved facts -> raw Beacon manifest.

This is the MVP-critical piece: merged, resolved evidence becomes a valid
``beacon.yaml`` mapping **without an LLM**. Two rules govern every field:

1. **Only evidence-backed fields are populated.** Project identity, canonical
   documents, source-grounded concepts, and implementation locations come
   straight from the resolved facts. Unknown intent stays unknown/empty --
   nothing is synthesized to satisfy the schema (a missing test command or
   guardrail set is a recorded, acknowledged absence, never invented text).
2. **Every claim carries a resolvable citation.** Concept sources point at
   canonical documents (``doc``), real files (``file``), the Menhir evidence
   (``memory``, identified by scan fingerprint), or the git HEAD commit
   (``commit``). The ``type=manifest``-with-empty-path citation shape of the
   retired Menhir bridge is deliberately never produced.

Output is a plain mapping consumed by :func:`beacon.core.loader.parse_manifest`
-- this module never parses or validates manifests itself, and rendering is a
separate, byte-deterministic step (:func:`render_manifest_yaml`).
"""

from __future__ import annotations

import hashlib
from typing import Any

import yaml

from beacon.build.policy import MergedProjectFacts

#: Manifest schema version the projection targets (unchanged since v0.1).
MANIFEST_SCHEMA_VERSION = "0.1"

#: Concept id of the evidence-backed structure concept.
STRUCTURE_CONCEPT_ID = "project-structure"

#: Fixed reasons for the publication warnings a generated manifest carries.
ACK_GUARDRAILS_MISSING = (
    "guardrails_missing",
    "generated from source evidence: no authoritative guardrail source exists yet",
)
ACK_TEST_COMMAND_MISSING = (
    "test_command_missing",
    "generated from source evidence: no authoritative test command source exists yet",
)

_SLUG_ALPHABET_OK = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def _slug(text: str) -> str:
    lowered = text.strip().lower()
    slug = "".join(char if char in _SLUG_ALPHABET_OK else "-" for char in lowered)
    return slug.strip("-") or "decision"


def _source(payload: dict[str, Any]) -> dict[str, Any]:
    source: dict[str, Any] = {
        "type": payload["type"],
        "title": payload.get("title", ""),
        "path": payload.get("path", ""),
        "url": payload.get("url", ""),
        "status": "current",
    }
    # Line fields are absent, never null: the loader requires a positive
    # integer when the key is present.
    if payload.get("line_start") is not None:
        source["line_start"] = payload["line_start"]
    if payload.get("line_end") is not None:
        source["line_end"] = payload["line_end"]
    return source


def build_raw_manifest(facts: MergedProjectFacts) -> dict[str, Any]:
    """Project resolved facts into the raw manifest mapping (deterministic)."""
    concepts: list[dict[str, Any]] = []

    if facts.structure_summary is not None:
        sources = [_source({"type": "memory", "title": "Menhir structure scan"})]
        if facts.structure_fingerprint:
            sources[0]["title"] = f"Menhir structure scan ({facts.structure_fingerprint})"
        if facts.git_head:
            short = facts.git_head[:12]
            sources.append(
                _source({"type": "commit", "title": f"git HEAD {short}", "url": ""})
            )
        concepts.append(
            {
                "id": STRUCTURE_CONCEPT_ID,
                "name": "Project structure",
                "definition": facts.structure_summary,
                "why_it_exists": "",
                "status": "current",
                "related_concepts": [],
                "implementation_locations": [],
                "sources": sources,
            }
        )

    for decision in facts.decisions:
        concepts.append(
            {
                "id": _slug(decision.title),
                "name": decision.title,
                "definition": decision.summary,
                "why_it_exists": "",
                "status": decision.status,
                "related_concepts": [],
                "implementation_locations": list(decision.locations),
                "sources": [
                    _source({"type": "file", "title": location, "path": location})
                    for location in decision.locations
                ],
            }
        )

    raw: dict[str, Any] = {
        "beacon_version": MANIFEST_SCHEMA_VERSION,
        "project": {
            "name": facts.name,
            "tagline": "",
            "description": facts.description,
            "status": facts.status,
            "repository": facts.repository,
            "primary_language": facts.primary_language,
            "license": "",
        },
        "purpose": {
            "one_sentence": facts.description,
            "problem": facts.purpose_problem,
            "non_goals": list(facts.non_goals),
        },
        "audiences": list(facts.audiences),
        "current_focus": list(facts.current_focus),
        "core_concepts": concepts,
        "canonical_docs": [
            {"path": doc["path"], "role": doc["role"], "status": "current", "title": doc["title"]}
            for doc in facts.canonical_docs
        ],
        "agent_guidance": {
            "read_first": list(facts.read_first),
            "safe_first_tasks": [],
            "avoid_without_review": [],
            "expected_behavior": [],
        },
        "build_and_test": dict(facts.build_and_test),
        "guardrails": list(facts.guardrails),
    }
    return raw


def render_manifest_yaml(raw: dict[str, Any], *, note: str | None = None) -> bytes:
    """Render the raw mapping as deterministic manifest YAML bytes.

    Sorted keys, plain style, ASCII, exactly one trailing newline -- the same
    manifest always renders to identical bytes. An optional fixed ``note`` is
    prepended as a YAML comment line (used by embedding generators to mark
    provenance).
    """
    body = yaml.safe_dump(raw, sort_keys=True, allow_unicode=False, default_flow_style=False)
    encoded = body.encode("utf-8")
    if note:
        sanitized = " ".join(note.splitlines()).strip()
        if sanitized:
            encoded = f"# {sanitized}\n".encode("utf-8") + encoded
    if not encoded.endswith(b"\n"):
        encoded += b"\n"
    return encoded


def manifest_bytes_sha256(data: bytes) -> str:
    """Return the hex sha256 of the exact manifest bytes (report metadata)."""
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "ACK_GUARDRAILS_MISSING",
    "ACK_TEST_COMMAND_MISSING",
    "MANIFEST_SCHEMA_VERSION",
    "STRUCTURE_CONCEPT_ID",
    "build_raw_manifest",
    "manifest_bytes_sha256",
    "render_manifest_yaml",
]
