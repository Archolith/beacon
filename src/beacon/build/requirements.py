"""What a Beacon asks for: the declared requirements catalogue and the report.

Every manifest field is listed here with the source tiers allowed to supply it
(build-pipeline plan §4):

* ``intent`` -- the project's own hand-authored ``beacon.yaml``;
* ``git`` -- the repository (reality);
* ``memory`` -- a memory/index provider's evidence (history). The Menhir
  adapter is today's only memory provider (authority label ``menhir``);
* ``derived`` -- Beacon computes the value from other fields.

``beacon_version`` is fixed by Beacon and is the only field not catalogued.

:func:`requirements_report` returns one row per field: whether it was
supplied, missing, or only filled by Beacon's schema default, which tier
actually supplied it, and the gap code. A test checks that every supplied row
names only allowed tiers, so the catalogue and :mod:`beacon.build.policy`
cannot drift apart silently.

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
TIER_DERIVED = "derived"

STATUS_SUPPLIED = "supplied"
STATUS_MISSING = "missing"
STATUS_DEFAULT = "default"

#: Manifest fields Beacon itself fixes; never asked for, never a gap.
BEACON_OWNED_FIELDS = frozenset({"beacon_version"})

#: Policy authority labels -> catalogue tiers.
_AUTHORITY_TIER = {
    "intent": TIER_INTENT,
    "git": TIER_GIT,
    "menhir": TIER_MEMORY,
}


@dataclass(frozen=True)
class Requirement:
    field: str
    sources: tuple[str, ...]
    required: bool
    gap_code: str
    ask: str


_I, _G, _M, _D = TIER_INTENT, TIER_GIT, TIER_MEMORY, TIER_DERIVED

CATALOGUE: tuple[Requirement, ...] = (
    Requirement("project.name", (_I, _M), True, "build_identity_unresolved", "The project's name."),
    Requirement(
        "project.description",
        (_I, _M),
        True,
        "build_description_unresolved",
        "A grounded description of the project.",
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
        "purpose.one_sentence",
        (_I, _M),
        False,
        "purpose_missing",
        "One sentence, in the maintainers' words, saying what the project is for.",
    ),
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
        "build_no_canonical_docs",
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
        "agent_guidance.read_first",
        (_I, _D),
        False,
        "read_first_missing",
        "The documents a new agent reads first (derived from canonical_docs when unstated).",
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
        "agent_guidance.expected_behavior",
        (_I,),
        False,
        "expected_behavior_missing",
        "How agents are expected to behave in this project.",
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
    Requirement(
        "project_state",
        (_I,),
        False,
        "project_state_missing",
        "Active work, recent completions, blockers and pending decisions.",
    ),
)


def _filled(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _tiers(authority: str) -> list[str]:
    """Map a policy authority label (``intent+menhir`` allowed) to tiers."""
    return [_AUTHORITY_TIER.get(part, part) for part in authority.split("+") if part]


def _intent_only(value: Any) -> tuple[str, list[str]]:
    return (STATUS_SUPPLIED, [TIER_INTENT]) if _filled(value) else (STATUS_MISSING, [])


def _authority(value: Any, authority: str) -> tuple[str, list[str]]:
    if not _filled(value) or not authority:
        return STATUS_MISSING, []
    return STATUS_SUPPLIED, _tiers(authority)


def _status(f: MergedProjectFacts, _intent: BeaconManifest | None) -> tuple[str, list[str]]:
    if f.status_authority == "default":
        return STATUS_DEFAULT, []
    # `beacon init` writes "unknown" as an explicit placeholder: still a gap.
    if f.status.strip().lower() == "unknown":
        return STATUS_MISSING, []
    return _authority(f.status, f.status_authority)


def _one_sentence(f: MergedProjectFacts, intent: BeaconManifest | None) -> tuple[str, list[str]]:
    # A stated purpose: memory may supply it (projected into purpose.one_sentence);
    # from intent it counts only when the maintainers wrote purpose.one_sentence --
    # a bare project.description such as `beacon init`'s starter text is not one.
    if intent is not None and intent.purpose.one_sentence.strip():
        return STATUS_SUPPLIED, [TIER_INTENT]
    if f.description_authority == "menhir":
        return STATUS_SUPPLIED, [TIER_MEMORY]
    return STATUS_MISSING, []


def _concepts(f: MergedProjectFacts, _intent: BeaconManifest | None) -> tuple[str, list[str]]:
    tiers = []
    if f.intent_concepts:
        tiers.append(TIER_INTENT)
    if f.decisions or f.structure_summary:
        tiers.append(TIER_MEMORY)
    return (STATUS_SUPPLIED, tiers) if tiers else (STATUS_MISSING, [])


def _read_first(f: MergedProjectFacts, intent: BeaconManifest | None) -> tuple[str, list[str]]:
    if intent is not None and intent.agent_guidance.read_first:
        return STATUS_SUPPLIED, [TIER_INTENT]
    return (STATUS_SUPPLIED, [TIER_DERIVED]) if f.read_first else (STATUS_MISSING, [])


def _project_state(f: MergedProjectFacts, _intent: BeaconManifest | None) -> tuple[str, list[str]]:
    state = f.project_state or {}
    return _intent_only(any(_filled(value) for value in state.values()))


_Reader = Callable[[MergedProjectFacts, BeaconManifest | None], tuple[str, list[str]]]

_READERS: dict[str, _Reader] = {
    "project.name": lambda f, _i: _authority(f.name, f.name_authority),
    "project.description": lambda f, _i: _authority(f.description, f.description_authority),
    "project.tagline": lambda f, _i: _intent_only(f.tagline),
    "project.repository": lambda f, _i: _authority(f.repository, f.repository_authority),
    "project.primary_language": lambda f, _i: _authority(
        f.primary_language, f.primary_language_authority
    ),
    "project.status": _status,
    "project.license": lambda f, _i: _intent_only(f.license),
    "purpose.one_sentence": _one_sentence,
    "purpose.problem": lambda f, _i: _intent_only(f.purpose_problem),
    "purpose.non_goals": lambda f, _i: _intent_only(f.non_goals),
    "audiences": lambda f, _i: _intent_only(f.audiences),
    "current_focus": lambda f, _i: _intent_only(f.current_focus),
    "canonical_docs": lambda f, _i: _authority(f.canonical_docs, f.canonical_docs_authority),
    "core_concepts": _concepts,
    "agent_guidance.read_first": _read_first,
    "agent_guidance.safe_first_tasks": lambda f, _i: _intent_only(
        f.agent_guidance.get("safe_first_tasks")
    ),
    "agent_guidance.avoid_without_review": lambda f, _i: _intent_only(
        f.agent_guidance.get("avoid_without_review")
    ),
    "agent_guidance.expected_behavior": lambda f, _i: _intent_only(
        f.agent_guidance.get("expected_behavior")
    ),
    "build_and_test.setup": lambda f, _i: _intent_only(f.build_and_test.get("setup")),
    "build_and_test.test": lambda f, _i: _intent_only(f.build_and_test.get("test")),
    "build_and_test.benchmark": lambda f, _i: _intent_only(f.build_and_test.get("benchmark")),
    "guardrails": lambda f, _i: _intent_only(f.guardrails),
    "project_state": _project_state,
}


def requirements_report(
    facts: MergedProjectFacts, intent: BeaconManifest | None = None
) -> list[dict[str, Any]]:
    """One row per catalogued field, in catalogue order."""
    rows: list[dict[str, Any]] = []
    for item in CATALOGUE:
        status, supplied_by = _READERS[item.field](facts, intent)
        rows.append(
            {
                "field": item.field,
                "status": status,
                "supplied_by": supplied_by,
                "allowed_sources": list(item.sources),
                "required": item.required,
                "gap_code": item.gap_code,
            }
        )
    return rows


def gaps_from_report(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows still asking for data (missing, or filled only by a schema default)."""
    return [
        {
            "code": row["gap_code"],
            "field": row["field"],
            "required": row["required"],
            "sources": row["allowed_sources"],
        }
        for row in report
        if row["status"] != STATUS_SUPPLIED
    ]


def catalogue_payload() -> dict[str, Any]:
    """The catalogue as published JSON data."""
    return {
        "catalogue": CATALOGUE_NAME,
        "version": CATALOGUE_VERSION,
        "tiers": {
            TIER_INTENT: "the project's own beacon.yaml",
            TIER_GIT: "the repository (reality)",
            TIER_MEMORY: "a memory/index provider's evidence (history)",
            TIER_DERIVED: "computed by Beacon from other fields",
        },
        "beacon_owned": sorted(BEACON_OWNED_FIELDS),
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
    "BEACON_OWNED_FIELDS",
    "CATALOGUE",
    "CATALOGUE_NAME",
    "CATALOGUE_VERSION",
    "Requirement",
    "catalogue_payload",
    "gaps_from_report",
    "requirements_report",
]
