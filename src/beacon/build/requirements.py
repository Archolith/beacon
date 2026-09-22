"""What a Beacon asks for: the declared requirements catalogue.

Every manifest field the build can populate is listed here with the source
tiers allowed to supply it (build-pipeline plan §4):

* ``intent`` -- the project's own hand-authored ``beacon.yaml``;
* ``git`` -- the repository (reality);
* ``memory`` -- a memory/index provider's evidence (history). The Menhir
  adapter is today's only memory provider.

A field absent from a successful build becomes a *gap*: a stable code the
project (or a later authoring assistant) can act on. Codes shared with
``beacon init`` reuse init's review codes. Required fields never appear as
gaps -- their absence refuses the build (``build_*`` codes in
:mod:`beacon.build.policy`).

The catalogue is published as ``docs/schemas/beacon-requirements-1.0.json``;
a test keeps that file identical to :func:`catalogue_payload`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from beacon.build.policy import MergedProjectFacts
from beacon.core.schema import BeaconManifest

CATALOGUE_NAME = "beacon.requirements"
CATALOGUE_VERSION = "1.0"

TIER_INTENT = "intent"
TIER_GIT = "git"
TIER_MEMORY = "memory"


@dataclass(frozen=True)
class Requirement:
    field: str
    sources: tuple[str, ...]
    required: bool
    gap_code: str
    ask: str


def _present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


#: Field -> how to read it from the merged facts.
_READERS: dict[str, Callable[[MergedProjectFacts], Any]] = {
    "project.name": lambda f: f.name,
    "project.description": lambda f: f.description,
    # Stated purpose: memory evidence may supply it; from intent it counts only when the
    # maintainers wrote purpose.one_sentence (a bare project.description, such as the
    # `beacon init` starter text, is not a stated purpose). Resolved in evaluate_gaps.
    "purpose.one_sentence": lambda f: f.description_authority != TIER_INTENT,
    "project.tagline": lambda f: f.tagline,
    "project.repository": lambda f: f.repository,
    "project.primary_language": lambda f: f.primary_language,
    "project.status": lambda f: f.status,
    "project.license": lambda f: f.license,
    "purpose.problem": lambda f: f.purpose_problem,
    "purpose.non_goals": lambda f: f.non_goals,
    "audiences": lambda f: f.audiences,
    "current_focus": lambda f: f.current_focus,
    "canonical_docs": lambda f: f.canonical_docs,
    "core_concepts": lambda f: f.intent_concepts or f.decisions,
    "agent_guidance.safe_first_tasks": lambda f: f.agent_guidance.get("safe_first_tasks"),
    "agent_guidance.avoid_without_review": lambda f: f.agent_guidance.get("avoid_without_review"),
    "build_and_test.setup": lambda f: f.build_and_test.get("setup"),
    "build_and_test.test": lambda f: f.build_and_test.get("test"),
    "build_and_test.benchmark": lambda f: f.build_and_test.get("benchmark"),
    "guardrails": lambda f: f.guardrails,
}

_I, _G, _M = TIER_INTENT, TIER_GIT, TIER_MEMORY

CATALOGUE: tuple[Requirement, ...] = (
    Requirement("project.name", (_I, _M), True, "build_identity_unresolved", "The project's name."),
    Requirement(
        "project.description",
        (_I, _M),
        True,
        "build_description_unresolved",
        "A grounded description of the project.",
    ),
    Requirement(
        "purpose.one_sentence",
        (_I, _M),
        False,
        "purpose_missing",
        "One sentence, in the maintainers' words, saying what the project is for.",
    ),
    Requirement("project.tagline", (_I,), False, "tagline_missing", "A short tagline."),
    Requirement(
        "project.repository", (_I, _G), False, "repository_unknown", "The canonical repository URL."
    ),
    Requirement(
        "project.primary_language",
        (_I, _M),
        False,
        "primary_language_unknown",
        "The main implementation language.",
    ),
    Requirement(
        "project.status",
        (_I, _M),
        False,
        "project_status_unknown",
        "Maturity (experimental, active, stable, ...) as the maintainers state it.",
    ),
    Requirement("project.license", (_I,), False, "license_omitted", "The license identifier."),
    Requirement(
        "purpose.problem", (_I,), False, "problem_missing", "The problem the project solves."
    ),
    Requirement(
        "purpose.non_goals",
        (_I,),
        False,
        "non_goals_missing",
        "What the project deliberately does not do.",
    ),
    Requirement("audiences", (_I,), False, "audiences_missing", "Who the project is for."),
    Requirement(
        "current_focus",
        (_I,),
        False,
        "current_focus_missing",
        "What the maintainers are working on now.",
    ),
    Requirement(
        "canonical_docs",
        (_I, _M),
        True,
        "canonical_docs_missing",
        "The documents an agent should treat as authoritative.",
    ),
    Requirement(
        "core_concepts",
        (_I, _M),
        False,
        "concepts_omitted",
        "The domain concepts an agent must understand.",
    ),
    Requirement(
        "agent_guidance.safe_first_tasks",
        (_I,),
        False,
        "safe_first_tasks_missing",
        "Tasks a new agent can safely start with.",
    ),
    Requirement(
        "agent_guidance.avoid_without_review",
        (_I,),
        False,
        "avoid_without_review_missing",
        "Areas an agent must not change without review.",
    ),
    Requirement(
        "build_and_test.setup", (_I,), False, "build_commands_unknown", "The setup/build command."
    ),
    Requirement("build_and_test.test", (_I,), False, "test_command_missing", "The test command."),
    Requirement(
        "build_and_test.benchmark",
        (_I,),
        False,
        "benchmark_omitted",
        "The benchmark command, if any.",
    ),
    Requirement(
        "guardrails",
        (_I,),
        False,
        "guardrails_missing",
        "Rules an agent must follow, each citing its source.",
    ),
)


def evaluate_gaps(
    facts: MergedProjectFacts, intent: BeaconManifest | None = None
) -> list[dict[str, Any]]:
    """Return one gap per catalogue field the build left empty (deterministic order)."""
    gaps: list[dict[str, Any]] = []
    for item in CATALOGUE:
        present = _present(_READERS[item.field](facts))
        if item.field == "purpose.one_sentence" and intent is not None:
            present = present or _present(intent.purpose.one_sentence)
        if present:
            continue
        gaps.append(
            {
                "code": item.gap_code,
                "field": item.field,
                "required": item.required,
                "sources": list(item.sources),
            }
        )
    return gaps


def catalogue_payload() -> dict[str, Any]:
    """The catalogue as published JSON data."""
    return {
        "catalogue": CATALOGUE_NAME,
        "version": CATALOGUE_VERSION,
        "tiers": {
            TIER_INTENT: "the project's own beacon.yaml",
            TIER_GIT: "the repository (reality)",
            TIER_MEMORY: "a memory/index provider's evidence (history)",
        },
        "requirements": [
            {
                "field": item.field,
                "sources": list(item.sources),
                "required": item.required,
                "gap_code": item.gap_code,
                "ask": item.ask,
            }
            for item in CATALOGUE
        ],
    }


__all__ = [
    "CATALOGUE",
    "CATALOGUE_NAME",
    "CATALOGUE_VERSION",
    "Requirement",
    "catalogue_payload",
    "evaluate_gaps",
]
