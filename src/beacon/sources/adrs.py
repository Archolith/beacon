"""Architecture decision records: the project's own reviewed "why", read verbatim.

An ADR is a decision the maintainers already approved by committing it. This module
reads ADR files from the conventional directories (``docs/adr``, ``doc/adr``,
``docs/decisions``, ``adr``, ``.agent/adr``) and any ``adr_dir`` the project names,
and turns each into one decision record:

* **Deterministic and verbatim.** Title, number, status, date and the Decision section
  are copied from the file; nothing is summarized or inferred. The Decision text is
  capped (``truncated`` says so) and every section is cited by line span, so the rest is
  one ``beacon_read`` away.
* **Status keeps its words.** The status line's first word maps onto Beacon's knowledge
  statuses (accepted -> current, proposed -> planned, superseded -> superseded, ...);
  the full text is kept as ``status_text`` because qualifiers such as "target
  architecture" or "activation open" matter. Those qualifiers set ``implemented: false``.
* **Supersession comes from metadata only** -- the status line, the metadata bullets or
  frontmatter -- never from prose that happens to mention another ADR.
* **Gaps, not guesses.** A file without a Decision section is not published; an
  unrecognised status is published as ``unknown``. Both are reported.

Formats understood: Nygard (``## Status`` section or ``- **Status:**`` bullets) and
MADR (YAML frontmatter, ``## Decision Outcome``, ``## Considered Options`` as a list).
Index files (``README.md``, ``index.md``) and templates are skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from beacon.core.citation_digest import digest_text
from beacon.core.limits import ResourceLimits
from beacon.core.security import classify_path, detect_sensitive_text

#: Directories read by default, in this order.
ADR_DIRS: tuple[str, ...] = ("docs/adr", "doc/adr", "docs/decisions", "adr", ".agent/adr")
#: File names in an ADR directory that are indexes or templates, never decisions.
_SKIP_NAMES = frozenset({"readme.md", "index.md", "template.md", "adr-template.md"})
_SKIP_PREFIXES = ("0000-", "template")

MAX_DECISIONS = 64
MAX_DIRS = 8
DECISION_CHARS = 4000
STATUS_TEXT_CHARS = 300
MAX_ALTERNATIVES = 8
ALTERNATIVE_CHARS = 120
REASON_CHARS = 600

#: First word of an ADR status -> Beacon knowledge status.
STATUS_WORDS = {
    "accepted": "current",
    "approved": "current",
    "corrected": "current",
    "amended": "current",
    "proposed": "planned",
    "draft": "planned",
    "superseded": "superseded",
    "deprecated": "superseded",
    "rejected": "superseded",
    "withdrawn": "superseded",
}
#: Qualifiers that mean an accepted decision is not in effect yet.
_NOT_IN_EFFECT = re.compile(
    r"\b(target architecture|implementation deferred|deferred|default-off|not yet "
    r"(?:implemented|active|enabled)|activation (?:open|pending)|adoption (?:open|pending)|"
    r"rollout (?:open|pending)|remains? open)\b",
    re.IGNORECASE,
)

_SECTION_ROLES: dict[str, tuple[str, ...]] = {
    "decision": ("decision", "decision outcome"),
    "context": ("context", "context and problem statement"),
    "consequences": ("consequences",),
    "alternatives": (
        "considered alternatives",
        "considered options",
        "alternatives",
        "alternatives considered",
        "options considered",
    ),
}
# Separator after the number: em dash, en dash, colon, period or hyphen (re escapes keep
# this file ASCII).
_TITLE_PREFIX = re.compile(r"^(?:ADR[-\s]?)?(\d+)\s*[\u2014\u2013:.\-]\s*", re.IGNORECASE)
_FILE_NUMBER = re.compile(r"^(\d+)[-_]")
_META = re.compile(r"^[-*] \*\*([A-Za-z][A-Za-z -]*):\*\*\s*(.*)$")
_PLAIN_META = re.compile(
    r"^(Status|Date|Deciders|Supersedes|Superseded by):\s*(.+)$", re.IGNORECASE
)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_REF = r"\[?(?:ADR[-\s]?)?0*(\d+)"
_SUPERSEDED_BY = re.compile(r"superseded\s+by\s+" + _REF, re.IGNORECASE)
_SUPERSEDES = re.compile(r"\bsupersedes\s+" + _REF, re.IGNORECASE)


@dataclass(frozen=True)
class AdrGap:
    """An ADR that could not be read fully; reported by the build, never served."""

    code: str
    path: str
    detail: str


@dataclass(frozen=True)
class AdrFacts:
    """Every decision read, the ADR files they came from, and the gaps."""

    decisions: tuple[dict[str, Any], ...] = ()
    gaps: tuple[AdrGap, ...] = ()

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(str(d["path"]) for d in self.decisions)


def adr_id(number: str) -> str:
    return f"adr-{int(number):04d}"


def collect_adrs(
    root: Path,
    read_text: Any,
    *,
    adr_dirs: tuple[str, ...] = (),
    limits: ResourceLimits | None = None,
) -> AdrFacts:
    """Read the ADRs under *root*. *read_text(root, rel)* is the bounded, in-root reader."""
    del limits  # bounds are enforced by read_text
    folders: list[str] = []
    for folder in (*adr_dirs, *ADR_DIRS):
        clean = folder.strip().strip("/")
        if clean and clean not in folders:
            folders.append(clean)
    decisions: list[dict[str, Any]] = []
    gaps: list[AdrGap] = []
    used_ids: set[str] = set()
    for folder in folders[:MAX_DIRS]:
        base = root / folder
        if base.is_symlink() or not base.is_dir():
            continue
        for path in sorted(base.glob("*.md")):
            name = path.name.lower()
            if name in _SKIP_NAMES or name.startswith(_SKIP_PREFIXES):
                continue
            rel = f"{folder}/{path.name}"
            if classify_path(rel) is not None:
                continue
            if len(decisions) >= MAX_DECISIONS:
                gaps.append(AdrGap("adr_limit", rel, f"more than {MAX_DECISIONS} ADRs; not read"))
                continue
            text = read_text(root, rel)
            if text is None:
                gaps.append(AdrGap("adr_unreadable", rel, "not a readable regular file"))
                continue
            if detect_sensitive_text(text, path=rel):
                gaps.append(AdrGap("adr_sensitive_content", rel, "sensitive content; not read"))
                continue
            decision, file_gaps = parse_adr(rel, text)
            gaps.extend(file_gaps)
            if decision is None:
                continue
            base_id = decision["id"]
            unique, n = base_id, 2
            while unique in used_ids:
                unique, n = f"{base_id}-{n}", n + 1
            used_ids.add(unique)
            decisions.append({**decision, "id": unique})
    return AdrFacts(decisions=tuple(decisions), gaps=tuple(gaps))


def parse_adr(rel: str, text: str) -> tuple[dict[str, Any] | None, list[AdrGap]]:
    """One ADR file -> (decision record or None, gaps)."""
    lines = text.replace("\r\n", "\n").split("\n")
    gaps: list[AdrGap] = []
    front, body_start = _frontmatter(lines)
    h1_index = next((i for i in range(body_start, len(lines)) if lines[i].startswith("# ")), None)
    h1 = lines[h1_index][2:].strip() if h1_index is not None else ""
    title_match = _TITLE_PREFIX.match(h1)
    file_match = _FILE_NUMBER.match(Path(rel).name)
    number = title_match.group(1) if title_match else file_match.group(1) if file_match else ""
    title = _TITLE_PREFIX.sub("", h1).strip() or str(front.get("title") or "") or Path(rel).stem
    meta = _metadata(lines, body_start)
    sections = _sections(lines)
    roles: dict[str, tuple[str, int, int]] = {}
    for name, start, end in sections:
        low = name.lower().rstrip(":")
        for role, names in _SECTION_ROLES.items():
            if role not in roles and low in names:
                roles[role] = (name, start, end)

    status_text = meta.get("status") or _section_text(lines, sections, "status")
    if not status_text and isinstance(front.get("status"), str):
        status_text = front["status"]
    status_text = " ".join(status_text.split())
    word = re.sub(r"[^a-z]", "", (status_text.split() or [""])[0].lower())
    status = STATUS_WORDS.get(word)
    if status is None:
        gaps.append(AdrGap("adr_status_unrecognised", rel, "status not recognised; unknown"))
        status = "unknown"
    if "decision" not in roles:
        gaps.append(AdrGap("adr_no_decision", rel, "no Decision section; not published"))
        return None, gaps

    _, d_start, d_end = roles["decision"]
    decision_text = "\n".join(lines[d_start:d_end]).strip()
    truncated = len(decision_text) > DECISION_CHARS
    first_line = d_start + 1
    last_line = max(first_line, d_end)
    record: dict[str, Any] = {
        "id": adr_id(number) if number else _slug(Path(rel).stem),
        "title": title,
        "status": status,
        "status_text": status_text[:STATUS_TEXT_CHARS],
        "date": str(meta.get("date") or front.get("date") or "").strip()[:40],
        "path": rel,
        "decision": decision_text[:DECISION_CHARS],
        "truncated": truncated,
        "alternatives": _alternatives(lines, roles.get("alternatives")),
        "sections": {
            role: {"line_start": start + 1, "line_end": max(start + 1, end)}
            for role, (_, start, end) in sorted(roles.items())
        },
        "supersedes": _refs(_SUPERSEDES, status_text, meta, front, "supersedes"),
        "superseded_by": _refs(_SUPERSEDED_BY, status_text, meta, front, "superseded_by"),
        "sources": [
            {
                "type": "doc",
                "title": f"{h1 or title} > Decision",
                "path": rel,
                "line_start": first_line,
                "line_end": last_line,
                "status": status,
                "digest": digest_text(text, first_line, last_line),
            }
        ],
    }
    if status == "current" and _NOT_IN_EFFECT.search(status_text):
        record["implemented"] = False
    for role in ("context", "consequences"):
        if role not in roles:
            gaps.append(AdrGap(f"adr_no_{role}", rel, f"no {role.title()} section"))
    return record, gaps


def _frontmatter(lines: list[str]) -> tuple[dict[str, Any], int]:
    if not lines or lines[0].strip() != "---":
        return {}, 0
    for end in range(1, min(len(lines), 60)):
        if lines[end].strip() == "---":
            try:
                data = yaml.safe_load("\n".join(lines[1:end]))
            except yaml.YAMLError:
                return {}, end + 1
            return (data if isinstance(data, dict) else {}), end + 1
    return {}, 0


def _metadata(lines: list[str], start: int) -> dict[str, str]:
    """``- **Key:** value`` bullets (with indented continuations) or ``Key: value`` lines
    before the first section."""
    meta: dict[str, str] = {}
    key: str | None = None
    for line in lines[start:]:
        if line.startswith("## "):
            break
        bullet = _META.match(line)
        plain = _PLAIN_META.match(line)
        if bullet or plain:
            match = bullet or plain
            assert match is not None
            key = match.group(1).strip().lower()
            meta.setdefault(key, match.group(2).strip())
        elif key and line.startswith("  ") and line.strip():
            meta[key] += " " + line.strip()
        else:
            key = None
    return meta


def _sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """``(heading, first body index, end index)`` for each H2."""
    heads = [(i, line[3:].strip()) for i, line in enumerate(lines) if line.startswith("## ")]
    return [
        (name, i + 1, heads[n + 1][0] if n + 1 < len(heads) else len(lines))
        for n, (i, name) in enumerate(heads)
    ]


def _section_text(lines: list[str], sections: list[tuple[str, int, int]], name: str) -> str:
    for heading, start, end in sections:
        if heading.lower().rstrip(":") == name:
            return " ".join(line.strip() for line in lines[start:end] if line.strip())
    return ""


def _alternatives(lines: list[str], section: tuple[str, int, int] | None) -> list[dict[str, str]]:
    """One entry per ``###`` alternative (with its reason), else per list item (Nygard/MADR)."""
    if section is None:
        return []
    _, start, end = section
    heads = [i for i in range(start, end) if lines[i].startswith("### ")]
    out: list[dict[str, str]] = []
    if heads:
        for n, i in enumerate(heads[:MAX_ALTERNATIVES]):
            stop = heads[n + 1] if n + 1 < len(heads) else end
            reason = " ".join(line.strip() for line in lines[i + 1 : stop] if line.strip())
            out.append(
                {
                    "alternative": lines[i][4:].strip()[:ALTERNATIVE_CHARS],
                    "reason": reason[:REASON_CHARS],
                }
            )
        return out
    for line in lines[start:end]:
        if _BULLET.match(line) and len(out) < MAX_ALTERNATIVES:
            out.append(
                {"alternative": _BULLET.sub("", line).strip()[:ALTERNATIVE_CHARS], "reason": ""}
            )
    return out


def _refs(
    pattern: re.Pattern[str],
    status_text: str,
    meta: dict[str, str],
    front: dict[str, Any],
    key: str,
) -> list[str]:
    """ADR ids named by the status line (``Superseded by ADR-0005``), a metadata bullet
    (``- **Supersedes:** ADR 0003``) or a frontmatter key; never by body prose."""
    numbers = list(pattern.findall(status_text))
    numbers += re.findall(_REF, meta.get(key.replace("_", " "), ""))
    value = front.get(key)
    for item in value if isinstance(value, list) else [value]:
        if isinstance(item, (str, int)) and not isinstance(item, bool):
            numbers += re.findall(_REF, str(item))
    found: list[str] = []
    for number in numbers:
        ref = adr_id(number)
        if ref not in found:
            found.append(ref)
    return found


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "adr"


__all__ = [
    "ADR_DIRS",
    "AdrFacts",
    "AdrGap",
    "MAX_DECISIONS",
    "STATUS_WORDS",
    "collect_adrs",
    "parse_adr",
]
