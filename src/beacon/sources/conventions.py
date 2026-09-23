"""Convention readers: judgment the project already wrote down, found by markup or by habit.

Two ways a project's own documents answer the fields only maintainers can fill:

* **Markers** -- an explicit, invisible span in a declared document::

      <!-- beacon:guardrail id=no-writes severity=high -->
      Never write files into indexed projects.
      <!-- /beacon -->

  Kinds: ``purpose``, ``non-goals``, ``guardrail`` (``id``, ``severity``, ``scope``),
  ``concept`` (``id``, ``name``), ``command`` (``for=setup|test``), ``avoid``. A
  marked span is exact: it is cited by line range and pinned with a digest.
* **Conventions** -- the fallback when nothing is marked: guardrail-like sections of
  ``AGENTS.md``/``CONTRIBUTING.md``/``SECURITY.md`` (one cited entry per section, never
  split into rules), other ``AGENTS.md`` sections as pointers, a ``Non-goals`` section,
  a glossary, ``CODEOWNERS``, document frontmatter and the ``mkdocs.yml`` nav.

Everything served is small by design: excerpts are capped and sections are cited, not
copied, so an agent pulls the full text only when it needs it. Agent-vendor files
(``CLAUDE.md``, ``.cursor/rules``) are never read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from beacon.core.citation_digest import digest_text
from beacon.core.limits import ResourceLimits
from beacon.core.security import classify_path

#: Documents whose markers and sections are read (never agent-vendor files).
MARKER_DOCS: tuple[str, ...] = ("README.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md")
_RULE_DOCS: tuple[str, ...] = ("AGENTS.md", "CONTRIBUTING.md", "SECURITY.md")
_GLOSSARY_DOCS: tuple[str, ...] = ("GLOSSARY.md", "docs/glossary.md", "docs/GLOSSARY.md")
_CODEOWNERS: tuple[str, ...] = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")

#: Token budget: every served excerpt and list is capped.
EXCERPT_CHARS = 300
_MAX_GUARDRAILS = 12
_MAX_POINTERS = 8
_MAX_CONCEPTS = 24
_MAX_AVOID = 20
_MAX_NAV_DOCS = 30

_MARKER_OPEN = re.compile(
    r"^\s*<!--\s*beacon:([a-z-]+)((?:\s+[a-z_]+=(?:\"[^\"]*\"|\S+?))*)\s*-->\s*$"
)
_MARKER_CLOSE = re.compile(r"^\s*<!--\s*/beacon\s*-->\s*$")
_ATTR = re.compile(r"([a-z_]+)=(\"[^\"]*\"|\S+)")
_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*#*\s*$")
_GUARD_HEADING = re.compile(
    r"\b(rules?|guardrails?|constraints?|must|never|do not|don't|safety|security|secrets?|"
    r"verification|testing|tests|git|commits?)\b",
    re.IGNORECASE,
)
_SECURITY_HEADING = re.compile(r"^(report|disclos)", re.IGNORECASE)
_NON_GOALS_HEADING = re.compile(r"\b(non-?goals|out of scope|not in scope)\b", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_MARKER_KINDS = frozenset({"purpose", "non-goals", "guardrail", "concept", "command", "avoid"})

#: Frontmatter lifecycle words (including Menhir's artifact metadata) -> knowledge status.
_STATUS_WORDS = {
    "current": "current",
    "approved": "current",
    "implemented": "current",
    "active": "current",
    "experimental": "experimental",
    "proposed": "planned",
    "draft": "planned",
    "planned": "planned",
    "deferred": "planned",
    "superseded": "superseded",
    "archived": "superseded",
    "rejected": "superseded",
    "deprecated": "superseded",
}


@dataclass(frozen=True)
class ConventionFacts:
    """What markers and conventions supplied, with the fields each route answered."""

    purpose: str = ""
    purpose_source: dict[str, Any] | None = None
    non_goals: tuple[str, ...] = ()
    guardrails: tuple[dict[str, Any], ...] = ()
    concepts: tuple[dict[str, Any], ...] = ()
    expected_behavior: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    commands: dict[str, dict[str, Any]] = field(default_factory=dict)
    nav_docs: tuple[str, ...] = ()
    #: Catalogue fields answered by explicit markers (exact) ...
    by_marker: frozenset[str] = frozenset()
    #: ... and by conventions (headings, CODEOWNERS, glossary, nav): usable, less exact.
    by_convention: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _excerpt(lines: list[str]) -> str:
    text = " ".join(_BULLET.sub("", line).strip().lstrip(">").strip() for line in lines)
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 3].rstrip() + "..."


def _bullets(lines: list[str]) -> list[str]:
    items = [" ".join(_BULLET.sub("", line).split()) for line in lines if _BULLET.match(line)]
    return [item for item in items if item]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


def _source(path: str, title: str, text: str, start: int, end: int) -> dict[str, Any]:
    """A citation pinned to *text* lines ``start..end`` (1-based) of *path*."""
    return {
        "type": "doc",
        "title": title,
        "path": path,
        "line_start": start,
        "line_end": end,
        "status": "current",
        "digest": digest_text(text, start, end),
    }


def _sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """(heading, first body line, last line) for every H2/H3, 1-based, ignoring code fences."""
    found: list[tuple[str, int, int]] = []  # (heading, level, line)
    fenced = False
    for index, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        match = None if fenced else _HEADING.match(line)
        if match:
            found.append((match.group(2), len(match.group(1)), index))
    sections: list[tuple[str, int, int]] = []
    for position, (heading, level, start) in enumerate(found):
        end = len(lines)
        for _later, later_level, later_start in found[position + 1 :]:
            if later_level <= level:
                end = later_start - 1
                break
        # Trim trailing blank lines so the cited range is exactly the section's text.
        while end > start and not lines[end - 1].strip():
            end -= 1
        first = start + 1
        while first < end and not lines[first - 1].strip():
            first += 1
        sections.append((heading, first, end))
    return sections


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect_conventions(
    root: Path, read_text: Any, *, limits: ResourceLimits | None = None
) -> ConventionFacts:
    """Read markers and conventions under *root*. *read_text(root, rel)* is the bounded reader."""
    del limits  # bounds are applied by read_text
    by_marker: set[str] = set()
    by_convention: set[str] = set()
    purpose = ""
    purpose_source: dict[str, Any] | None = None
    non_goals: list[str] = []
    guardrails: list[dict[str, Any]] = []
    concepts: list[dict[str, Any]] = []
    avoid: list[str] = []
    commands: dict[str, dict[str, Any]] = {}
    texts: dict[str, str] = {}
    marked_rule_docs: set[str] = set()

    for rel in MARKER_DOCS:
        text = read_text(root, rel)
        if text is None:
            continue
        texts[rel] = text
        for kind, attrs, start, end, body in _markers(text):
            where = _source(rel, attrs.get("title", kind), text, start, end)
            if kind == "purpose" and not purpose:
                purpose, purpose_source = _excerpt(body), where
                by_marker.add("purpose.one_sentence")
            elif kind == "non-goals":
                non_goals.extend(_bullets(body) or [_excerpt(body)])
                by_marker.add("purpose.non_goals")
            elif kind == "guardrail":
                ident = attrs.get("id") or _slug(_excerpt(body)[:40])
                guardrails.append(
                    {
                        "id": ident,
                        "rule": _excerpt(body),
                        "scope": attrs.get("scope", ""),
                        "severity": attrs.get("severity", "medium"),
                        "applies_to": [],
                        "sources": [where],
                    }
                )
                by_marker.add("guardrails")
                marked_rule_docs.add(rel)
            elif kind == "concept":
                ident = attrs.get("id") or _slug(attrs.get("name", _excerpt(body)[:40]))
                concepts.append(_concept(ident, attrs.get("name", ident), _excerpt(body), where))
                by_marker.add("core_concepts")
            elif kind == "command" and attrs.get("for") in ("setup", "test"):
                command = next(
                    (
                        line.strip().strip("`")
                        for line in body
                        if line.strip() and not line.strip().startswith("```")
                    ),
                    "",
                )
                if command:
                    commands[attrs["for"]] = {"value": command, "path": rel, "line": start}
                    by_marker.add(f"build_and_test.{attrs['for']}")
            elif kind == "avoid":
                avoid.extend(_bullets(body) or [_excerpt(body)])
                by_marker.add("agent_guidance.avoid_without_review")

    expected: list[str] = []
    # Markers replace the heading fallback per document: a document with guardrail
    # markers contributes only those, while unmarked documents still use their headings.
    for rel in _RULE_DOCS:
        text = texts.get(rel)
        if text is None:
            continue
        lines = text.replace("\r\n", "\n").split("\n")
        for heading, start, end in _sections(lines):
            body = [line for line in lines[start - 1 : end] if line.strip()]
            if not body:
                continue
            is_rule = _GUARD_HEADING.search(heading) or (
                rel == "SECURITY.md" and _SECURITY_HEADING.search(heading)
            )
            if is_rule:
                if rel in marked_rule_docs or len(guardrails) >= _MAX_GUARDRAILS:
                    continue  # this document's markers are its rules
                guardrails.append(
                    {
                        "id": _slug(f"{Path(rel).stem}-{heading}"),
                        "rule": _excerpt(body),
                        "scope": Path(rel).stem.lower(),
                        "severity": "medium",
                        "applies_to": [],
                        "sources": [_source(rel, f"{rel} > {heading}", text, start, end)],
                    }
                )
                by_convention.add("guardrails")
            elif rel == "AGENTS.md" and len(expected) < _MAX_POINTERS:
                expected.append(f"{rel} > {heading} (lines {start}-{end})")
                by_convention.add("agent_guidance.expected_behavior")

    if "purpose.non_goals" not in by_marker:
        for rel in ("README.md", "CONTRIBUTING.md"):
            text = texts.get(rel)
            if text is None:
                continue
            lines = text.replace("\r\n", "\n").split("\n")
            for heading, start, end in _sections(lines):
                if _NON_GOALS_HEADING.search(heading):
                    non_goals.extend(_bullets(lines[start - 1 : end]))
                    by_convention.add("purpose.non_goals")

    if "core_concepts" not in by_marker:
        glossary = _glossary(root, read_text)
        if glossary:
            concepts.extend(glossary)
            by_convention.add("core_concepts")

    if "agent_guidance.avoid_without_review" not in by_marker:
        owners = _codeowners(root, read_text)
        if owners:
            avoid.extend(owners)
            by_convention.add("agent_guidance.avoid_without_review")

    nav = _mkdocs_nav(root, read_text)
    if nav:
        by_convention.add("canonical_docs")

    return ConventionFacts(
        purpose=purpose,
        purpose_source=purpose_source,
        non_goals=tuple(dict.fromkeys(non_goals)),
        guardrails=tuple(_dedupe_ids(guardrails)[:_MAX_GUARDRAILS]),
        concepts=tuple(_dedupe_ids(concepts)[:_MAX_CONCEPTS]),
        expected_behavior=tuple(expected),
        avoid=tuple(dict.fromkeys(avoid))[:_MAX_AVOID],
        commands=commands,
        nav_docs=nav,
        by_marker=frozenset(by_marker),
        by_convention=frozenset(by_convention - by_marker),
    )


def _markers(text: str) -> list[tuple[str, dict[str, str], int, int, list[str]]]:
    """(kind, attrs, first body line, last body line, body lines) for each closed marker."""
    lines = text.replace("\r\n", "\n").split("\n")
    found: list[tuple[str, dict[str, str], int, int, list[str]]] = []
    index = 0
    while index < len(lines):
        match = _MARKER_OPEN.match(lines[index])
        if not match or match.group(1) not in _MARKER_KINDS:
            index += 1
            continue
        attrs = {key: value.strip('"') for key, value in _ATTR.findall(match.group(2) or "")}
        for close in range(index + 1, len(lines)):
            if _MARKER_CLOSE.match(lines[close]):
                body = lines[index + 1 : close]
                if any(line.strip() for line in body):
                    found.append((match.group(1), attrs, index + 2, close, body))
                index = close
                break
        index += 1
    return found


def _concept(ident: str, name: str, definition: str, source: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ident,
        "name": name,
        "definition": definition,
        "why_it_exists": "",
        # Written down is not the same as current: frontmatter or intent may say more.
        "status": "unknown",
        "related_concepts": [],
        "implementation_locations": [],
        "sources": [source],
    }


def _dedupe_ids(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            kept.append(item)
    return kept


def _glossary(root: Path, read_text: Any) -> list[dict[str, Any]]:
    for rel in _GLOSSARY_DOCS:
        text = read_text(root, rel)
        if text is None:
            continue
        lines = text.replace("\r\n", "\n").split("\n")
        concepts = []
        for heading, start, end in _sections(lines):
            body: list[str] = []
            for line in lines[start - 1 : end]:
                if not line.strip():
                    if body:
                        break
                    continue
                body.append(line)
            if body:
                term = heading.strip("`* ")
                concepts.append(
                    _concept(
                        _slug(term),
                        term,
                        _excerpt(body),
                        _source(rel, f"{rel} > {term}", text, start, end),
                    )
                )
        return concepts
    return []


def _codeowners(root: Path, read_text: Any) -> list[str]:
    for rel in _CODEOWNERS:
        text = read_text(root, rel)
        if text is None:
            continue
        entries = []
        for line in text.splitlines():
            parts = line.split("#", 1)[0].split()
            if len(parts) >= 2:
                entries.append(f"{parts[0]} (review by {', '.join(parts[1:4])}; {rel})")
        return entries
    return []


def _mkdocs_nav(root: Path, read_text: Any) -> tuple[str, ...]:
    text = read_text(root, "mkdocs.yml")
    if text is None:
        return ()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return ()
    if not isinstance(data, dict):
        return ()
    docs_dir = str(data.get("docs_dir") or "docs").strip("/")
    paths: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str) and node.endswith(".md") and "://" not in node:
            paths.append(f"{docs_dir}/{node.lstrip('/')}")
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(data.get("nav"))
    safe = [
        p for p in dict.fromkeys(paths) if ".." not in p.split("/") and classify_path(p) is None
    ]
    return tuple(safe[:_MAX_NAV_DOCS])


def read_frontmatter(text: str) -> dict[str, str]:
    """``status`` and ``role`` from a document's leading YAML frontmatter, normalized."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    for end in range(1, min(len(lines), 60)):
        if lines[end].strip() == "---":
            try:
                data = yaml.safe_load("\n".join(lines[1:end]))
            except yaml.YAMLError:
                return {}
            if not isinstance(data, dict):
                return {}
            result: dict[str, str] = {}
            raw_status = data.get("status", data.get("artifact_status"))
            if isinstance(raw_status, str) and raw_status.strip().lower() in _STATUS_WORDS:
                result["status"] = _STATUS_WORDS[raw_status.strip().lower()]
            if isinstance(data.get("role"), str) and data["role"].strip():
                result["role"] = data["role"].strip()
            return result
    return {}


__all__ = [
    "EXCERPT_CHARS",
    "MARKER_DOCS",
    "ConventionFacts",
    "collect_conventions",
    "read_frontmatter",
]
