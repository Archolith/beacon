"""The declared source: facts the project already wrote, in files other than ``beacon.yaml``.

Package manifests (``pyproject.toml``, ``package.json``, ``Cargo.toml``), the license
file, CI workflows and the README are the project's own statements. ``beacon build``
reads them on every run instead of copying them into ``beacon.yaml``, so they cannot go
stale there. Each value records the file and line it came from.

Two tiers come out of this module:

* ``declared`` -- the value is stated in a project file (a manifest field, a license
  text that matches a known license, a command a CI workflow runs, the README's lead
  paragraph);
* ``inferred`` -- a heuristic guess (the conventional command for a build marker, a
  license named only by its filename). Inferred values are reported as low confidence.

Reads follow the same bounded, in-root, no-symlink rules as ``beacon init`` discovery,
never run git or the network, and never execute anything.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from beacon.core import discovery as _discovery
from beacon.core.limits import ResourceLimits
from beacon.core.security import classify_path
from beacon.sources.adrs import AdrFacts, collect_adrs
from beacon.sources.conventions import ConventionFacts, collect_conventions

TIER_DECLARED = "declared"
TIER_INFERRED = "inferred"

#: Entry documents in reading order (declared canonical docs).
DECLARED_DOC_PATHS: tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    ".agent/README.md",
    "docs/README.md",
    "docs/index.md",
    "docs/architecture.md",
)
#: Entry documents an agent reads first.
_ENTRYPOINTS = frozenset({"README.md", "AGENTS.md"})

#: CI workflow directories and the most workflow files read from them.
_WORKFLOW_DIRS: tuple[str, ...] = (".github/workflows",)
_MAX_WORKFLOWS = 20
_MAX_DESCRIPTION_CHARS = 1000

#: A CI step line that runs the test suite.
_TEST_RE = re.compile(
    r"^(?:python3? -m pytest|pytest|uv run pytest|poetry run pytest|tox|nox|"
    r"npm (?:run )?test|pnpm (?:run )?test|yarn (?:run )?test|bun test|deno test|"
    r"cargo test|go test|make test|mvn(?:w)? test|\./gradlew test|gradle test|"
    r"bundle exec rspec|rspec)\b"
)
#: A CI step line that installs the project itself (not tooling). pip installs count
#: only with a project target (``.``, ``.[extras]``, ``--group``, a requirements file).
_SETUP_RE = re.compile(
    r"^(?:uv sync|poetry install|pdm install|npm ci|npm install|pnpm install|"
    r"yarn install|bun install|cargo build|go mod download|bundle install)\b"
)
_PIP_INSTALL_RE = re.compile(r"^(?:python3? -m pip|pip3?|uv pip) install\b")
_PIP_PROJECT_TARGET_RE = re.compile(
    r"(?:^|\s)(?:-e\s+|--editable\s+)?\.(?:\[[^\]]*\])?(?=\s|$)|--group\b|(?:^|\s)-r\s"
)
#: Workflows read first (tests/CI) and last (publishing), by filename.
_PREFERRED_WORKFLOW_RE = re.compile(r"test|ci|check|build", re.IGNORECASE)
_LATE_WORKFLOW_RE = re.compile(r"publish|release|deploy|pages", re.IGNORECASE)
#: Lines that are not safe or not meaningful to publish as a command.
_UNPUBLISHABLE_RE = re.compile(r"\$\{\{|secrets\.|token|password", re.IGNORECASE)

#: (SPDX id, phrases that must all appear), checked in order; more specific first.
_LICENSE_TEXTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AGPL-3.0", ("gnu affero general public license", "version 3")),
    ("LGPL-3.0", ("gnu lesser general public license", "version 3")),
    ("LGPL-2.1", ("gnu lesser general public license", "version 2.1")),
    ("GPL-3.0", ("gnu general public license", "version 3")),
    ("GPL-2.0", ("gnu general public license", "version 2")),
    ("Apache-2.0", ("apache license", "version 2.0")),
    ("MPL-2.0", ("mozilla public license", "2.0")),
    ("MIT", ("permission is hereby granted, free of charge",)),
    ("ISC", ("permission to use, copy, modify, and/or distribute this software",)),
    (
        "BSD-3-Clause",
        ("redistribution and use in source and binary forms", "neither the name"),
    ),
    ("BSD-2-Clause", ("redistribution and use in source and binary forms",)),
    ("Unlicense", ("this is free and unencumbered software released into the public domain",)),
)

_MARKDOWN_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_EMPHASIS_RE = re.compile(r"(\*\*|__|`)")


@dataclass(frozen=True)
class DeclaredValue:
    """One value, the tier that stated it, and where."""

    value: str
    tier: str
    path: str
    line: int | None = None


@dataclass(frozen=True)
class DeclaredFacts:
    """Everything the declared source found; ``None`` means nothing stated it."""

    name: DeclaredValue | None = None
    description: DeclaredValue | None = None
    license: DeclaredValue | None = None
    primary_language: DeclaredValue | None = None
    setup: DeclaredValue | None = None
    test: DeclaredValue | None = None
    canonical_docs: tuple[str, ...] = ()
    #: Markers and conventions (guardrails, non-goals, concepts, review areas, ...).
    conventions: ConventionFacts = field(default_factory=ConventionFacts)

    def doc_role(self, path: str) -> str:
        return "entrypoint" if path in _ENTRYPOINTS else "reference"


def collect_declared(root: str | Path, *, limits: ResourceLimits | None = None) -> DeclaredFacts:
    """Read the project's own declarations from *root* (bounded, offline, no execution)."""
    active = limits if limits is not None else ResourceLimits()
    root_path = Path(root).resolve()
    manifest = _read_package_manifest(root_path, active)
    name = _manifest_value(manifest, "name")
    description = _manifest_value(manifest, "description") or _readme_lead(root_path, active)
    license_value = _manifest_license(manifest) or _license_from_file(root_path, active)
    language = _language(manifest, root_path, active)
    setup, test = _ci_commands(root_path, active)
    guess_setup, guess_test = _marker_commands(root_path, active)
    conventions = collect_conventions(
        root_path, lambda base, rel: _read_text(base, rel, active), limits=active
    )
    # A command marked in the project's docs is the most exact statement of all.
    marked = {
        key: DeclaredValue(item["value"], TIER_DECLARED, item["path"], item["line"])
        for key, item in conventions.commands.items()
    }
    docs = _docs(root_path, active)
    nav = tuple(
        rel
        for rel in conventions.nav_docs
        if rel not in docs and _discovery._safe_regular(root_path, root_path / rel, active)
    )
    return DeclaredFacts(
        name=name,
        description=description,
        license=license_value,
        primary_language=language,
        setup=marked.get("setup") or setup or guess_setup,
        test=marked.get("test") or test or guess_test,
        canonical_docs=(docs + nav)[: active.documents],
        conventions=conventions,
    )


def collect_declared_adrs(
    root: str | Path, *, adr_dirs: tuple[str, ...] = (), limits: ResourceLimits | None = None
) -> AdrFacts:
    """The project's ADRs (see :mod:`beacon.sources.adrs`), read with the same bounded,
    in-root, no-symlink rules as every other declared file."""
    active = limits if limits is not None else ResourceLimits()
    root_path = Path(root).resolve()
    return collect_adrs(
        root_path,
        lambda base, rel: _read_text(base, rel, active),
        adr_dirs=adr_dirs,
        limits=active,
    )


# ---------------------------------------------------------------------------
# File access (same rules as init discovery)
# ---------------------------------------------------------------------------


def _read_text(root: Path, rel: str, limits: ResourceLimits) -> str | None:
    candidate = root / rel
    if classify_path(rel) is not None:
        return None
    if not _discovery._safe_regular(root, candidate, limits):
        return None
    return _discovery._read_bounded(candidate, limits).decode("utf-8", errors="replace")


def _line_of(text: str, needle: str) -> int | None:
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    return None


def _key_line(text: str, key: str, value: str) -> int | None:
    """The line that assigns *key*, preferring one that also holds *value* (TOML or JSON)."""
    key_re = re.compile(rf'^\s*"?{re.escape(key)}"?\s*[=:]')
    fallback: int | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if key_re.match(line):
            if value[:40] in line:
                return number
            fallback = fallback or number
    return fallback


# ---------------------------------------------------------------------------
# Package manifests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Manifest:
    path: str
    text: str
    data: dict[str, Any]
    table: dict[str, Any]
    language: str


def _read_package_manifest(root: Path, limits: ResourceLimits) -> _Manifest | None:
    for rel, language in (
        ("pyproject.toml", "Python"),
        ("package.json", "JavaScript"),
        ("Cargo.toml", "Rust"),
    ):
        text = _read_text(root, rel, limits)
        if text is None:
            continue
        try:
            data = json.loads(text) if rel.endswith(".json") else tomllib.loads(text)
        except (ValueError, tomllib.TOMLDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        section = {"pyproject.toml": "project", "Cargo.toml": "package"}.get(rel)
        table = data.get(section) if section else data
        if not isinstance(table, dict):
            table = {}
        if rel == "package.json" and "typescript" in json.dumps(data.get("devDependencies") or {}):
            language = "TypeScript"
        return _Manifest(path=rel, text=text, data=data, table=table, language=language)
    return None


def _manifest_value(manifest: _Manifest | None, key: str) -> DeclaredValue | None:
    if manifest is None:
        return None
    value = manifest.table.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    text = " ".join(value.split())[:_MAX_DESCRIPTION_CHARS]
    line = _key_line(manifest.text, key, value.strip())
    return DeclaredValue(text, TIER_DECLARED, manifest.path, line)


def _manifest_license(manifest: _Manifest | None) -> DeclaredValue | None:
    if manifest is None:
        return None
    raw = manifest.table.get("license")
    if isinstance(raw, dict):
        raw = raw.get("text") if isinstance(raw.get("text"), str) else None
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 100 or "\n" in raw.strip():
        return None
    return DeclaredValue(
        raw.strip(), TIER_DECLARED, manifest.path, _key_line(manifest.text, "license", raw.strip())
    )


def _language(
    manifest: _Manifest | None, root: Path, limits: ResourceLimits
) -> DeclaredValue | None:
    if manifest is not None:
        return DeclaredValue(manifest.language, TIER_DECLARED, manifest.path)
    if _read_text(root, "go.mod", limits) is not None:
        return DeclaredValue("Go", TIER_DECLARED, "go.mod")
    return None


# ---------------------------------------------------------------------------
# License text
# ---------------------------------------------------------------------------


def _license_from_file(root: Path, limits: ResourceLimits) -> DeclaredValue | None:
    for filename in _discovery.LICENSE_FILENAMES:
        text = _read_text(root, filename, limits)
        if text is None:
            continue
        normalized = " ".join(text.lower().split())
        for spdx, phrases in _LICENSE_TEXTS:
            if all(phrase in normalized for phrase in phrases):
                return DeclaredValue(spdx, TIER_DECLARED, filename, 1)
        guessed = _discovery._LICENSE_FILENAME_MAP.get(filename.lower(), "unknown")
        if guessed != "unknown":
            return DeclaredValue(guessed, TIER_INFERRED, filename)
        return None
    return None


# ---------------------------------------------------------------------------
# README lead paragraph
# ---------------------------------------------------------------------------


def _readme_lead(root: Path, limits: ResourceLimits) -> DeclaredValue | None:
    text = _read_text(root, "README.md", limits)
    if text is None:
        return None
    lines = text.replace("\r\n", "\n").split("\n")
    index = 0
    if lines and lines[0].strip() == "---":  # front matter
        for end in range(1, len(lines)):
            if lines[end].strip() == "---":
                index = end + 1
                break
    # The lead paragraph follows the first H1 when there is one.
    for position in range(index, len(lines)):
        if lines[position].startswith("# "):
            index = position + 1
            break
    paragraph: list[str] = []
    start: int | None = None
    for position in range(index, len(lines)):
        stripped = lines[position].strip()
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith("#"):
            if paragraph:
                break
            continue
        if not paragraph and (
            stripped.startswith(("![", "[![", "<", "|", "```", "---"))
            or _MARKDOWN_LINK_RE.sub("", stripped).strip(" |") == ""
        ):
            continue  # badges, HTML, tables and link rows are not prose
        if start is None:
            start = position + 1
        paragraph.append(stripped.lstrip(">").strip())
    if not paragraph or start is None:
        return None
    prose = _MARKDOWN_LINK_RE.sub(r"\1", " ".join(paragraph))
    prose = " ".join(_EMPHASIS_RE.sub("", prose).split())[:_MAX_DESCRIPTION_CHARS]
    if len(prose) < 20:
        return None
    return DeclaredValue(prose, TIER_DECLARED, "README.md", start)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _ci_commands(
    root: Path, limits: ResourceLimits
) -> tuple[DeclaredValue | None, DeclaredValue | None]:
    setup: DeclaredValue | None = None
    test: DeclaredValue | None = None
    for directory in _WORKFLOW_DIRS:
        folder = root / directory
        if folder.is_symlink() or not folder.is_dir():
            continue
        files = sorted(
            (
                p.name
                for p in folder.iterdir()
                if p.suffix in (".yml", ".yaml") and not p.is_symlink()
            ),
            key=_workflow_order,
        )[:_MAX_WORKFLOWS]
        for filename in files:
            rel = f"{directory}/{filename}"
            text = _read_text(root, rel, limits)
            if text is None:
                continue
            for command in _workflow_run_lines(text):
                if setup is None and _is_project_setup(command):
                    setup = DeclaredValue(command, TIER_DECLARED, rel, _line_of(text, command))
                if test is None and _TEST_RE.match(command):
                    test = DeclaredValue(command, TIER_DECLARED, rel, _line_of(text, command))
            if setup is not None and test is not None:
                return setup, test
    return setup, test


def _workflow_order(name: str) -> tuple[int, str]:
    if _LATE_WORKFLOW_RE.search(name):
        return (2, name)
    return (0 if _PREFERRED_WORKFLOW_RE.search(name) else 1, name)


def _is_project_setup(command: str) -> bool:
    if _PIP_INSTALL_RE.match(command):
        unquoted = command.replace('"', "").replace("'", "")
        return bool(_PIP_PROJECT_TARGET_RE.search(unquoted))
    return bool(_SETUP_RE.match(command))


def _workflow_run_lines(text: str) -> list[str]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, dict):
        return []
    commands: list[str] = []
    for job in jobs.values():
        steps = job.get("steps") if isinstance(job, dict) else None
        if not isinstance(steps, list):
            continue
        for step in steps:
            run = step.get("run") if isinstance(step, dict) else None
            if not isinstance(run, str):
                continue
            for line in run.splitlines():
                command = " ".join(line.strip().rstrip("\\").split())
                if (
                    command
                    and not command.startswith("#")
                    and not _UNPUBLISHABLE_RE.search(command)
                ):
                    commands.append(command)
    return commands


def _marker_commands(
    root: Path, limits: ResourceLimits
) -> tuple[DeclaredValue | None, DeclaredValue | None]:
    """The conventional command for a build marker: a guess, labelled ``inferred``."""
    language, evidence, setup, test, _unknown = _discovery._discover_build(root, limits)
    if evidence is None:
        return None, None
    return (
        DeclaredValue(setup, TIER_INFERRED, evidence.path) if setup else None,
        DeclaredValue(test, TIER_INFERRED, evidence.path) if test else None,
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def _docs(root: Path, limits: ResourceLimits) -> tuple[str, ...]:
    found: list[str] = []
    for rel in DECLARED_DOC_PATHS:
        if classify_path(rel) is not None:
            continue
        if _discovery._safe_regular(root, root / rel, limits):
            found.append(rel)
    return tuple(found[: limits.documents])


__all__ = [
    "DECLARED_DOC_PATHS",
    "TIER_DECLARED",
    "TIER_INFERRED",
    "DeclaredFacts",
    "DeclaredValue",
    "collect_declared",
]
