"""Immutable project-status companion resource for HTTP Beacon consumers.

The status resource deliberately separates maintainer-declared work state from
startup-observed repository and source evidence.  Observation happens once,
before the HTTP process begins serving, and the resulting value is immutable
for that process.  It is evidence about one startup instant, not a live file
watcher and not a cryptographic attestation.
"""

from __future__ import annotations

import hashlib
import shutil

# Fixed local Git inspection is the only subprocess use; it has no shell or network behavior.
import subprocess  # nosec B404
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from beacon.core.limits import (
    LIMIT_DOCUMENT_BYTES,
    LIMIT_MANIFEST_BYTES,
    LimitError,
    ResourceLimits,
    read_bytes_bounded,
)
from beacon.core.paths import UnsafeCanonicalPath, resolve_canonical_path
from beacon.core.snapshot import Snapshot

STATUS_VERSION = "1.1"


@dataclass(frozen=True)
class RepositoryEvidence:
    """Bounded Git evidence collected without network access."""

    state: str
    commit: str = ""
    branch: str = ""
    dirty: bool | None = None


@dataclass(frozen=True)
class SourceEvidence:
    """One startup comparison between a snapshot digest and a local source."""

    kind: str
    path: str
    expected_sha256: str
    state: str
    observed_sha256: str = ""


@dataclass(frozen=True)
class StatusObservation:
    """All objective evidence captured for one immutable HTTP process."""

    mode: str
    observed_at: str | None
    repository: RepositoryEvidence
    sources: tuple[SourceEvidence, ...]

    @classmethod
    def unavailable(cls) -> StatusObservation:
        """Return a deterministic fallback for direct library construction."""
        return cls(
            mode="not_collected",
            observed_at=None,
            repository=RepositoryEvidence(state="unavailable"),
            sources=(),
        )


def observe_project_status(
    snapshot: Snapshot,
    *,
    manifest_path: str | Path,
    docs_root: str | Path,
    observed_at: str | None = None,
    limits: ResourceLimits | None = None,
) -> StatusObservation:
    """Capture local source and Git evidence once without outbound I/O."""
    active_limits = limits or ResourceLimits()
    root = Path(docs_root).resolve()
    manifest = Path(manifest_path).resolve()
    timestamp = observed_at or _utc_now()
    sources = [
        _observe_source(
            "manifest",
            _safe_manifest_name(manifest, root),
            manifest,
            snapshot.manifest.source_sha256,
            ceiling=active_limits.manifest_bytes,
            limit_code=LIMIT_MANIFEST_BYTES,
            limit_field="manifest_bytes",
        )
    ]
    for document in snapshot.documents:
        try:
            source_path = resolve_canonical_path(root, document.path)
        except UnsafeCanonicalPath:
            sources.append(
                SourceEvidence(
                    "document",
                    document.path,
                    document.source_sha256,
                    "unavailable",
                )
            )
            continue
        sources.append(
            _observe_source(
                "document",
                document.path,
                source_path,
                document.source_sha256,
                ceiling=active_limits.document_bytes,
                limit_code=LIMIT_DOCUMENT_BYTES,
                limit_field="document_bytes",
            )
        )
    return StatusObservation(
        mode="startup",
        observed_at=timestamp,
        repository=_observe_repository(root),
        sources=tuple(sources),
    )


def build_status_payload(
    snapshot: Snapshot,
    *,
    snapshot_sha256: str,
    observation: StatusObservation | None = None,
) -> dict[str, Any]:
    """Return the versioned status companion payload."""
    observed = observation or StatusObservation.unavailable()
    return {
        "beacon_status_version": STATUS_VERSION,
        "snapshot": {
            "sha256": snapshot_sha256,
            "schema_version": snapshot.beacon_snapshot_version,
        },
        "declared": _declared_state(snapshot),
        "observed": {
            "mode": observed.mode,
            "observed_at": observed.observed_at,
            "repository": _repository_payload(observed.repository),
            "freshness": _freshness_payload(observed.sources),
        },
        "trust": {
            "assertion": "self_reported",
            "signed": False,
            "verification_scope": "origin_startup",
            "note": (
                "Source hashes and repository state were observed by this Beacon origin; "
                "remote consumers need an independent repository comparison or a future signature."
            ),
        },
    }


def _declared_state(snapshot: Snapshot) -> dict[str, Any]:
    raw = snapshot.manifest.data.get("project_state", {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "active_work": _state_item_payload(raw.get("active_work")),
        "recently_completed": _state_item_list(raw.get("recently_completed")),
        "blockers": _state_item_list(raw.get("blockers")),
        "pending_decisions": _state_item_list(raw.get("pending_decisions")),
    }


def _state_item_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for raw in value if (item := _state_item_payload(raw)) is not None]


def _state_item_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("title"), str):
        return None
    summary = value.get("summary", "")
    next_step = value.get("next_step", "")
    sources = value.get("sources", [])
    return {
        "title": value["title"],
        "summary": summary if isinstance(summary, str) else "",
        "next_step": next_step if isinstance(next_step, str) else "",
        "sources": _source_citations(sources),
    }


def _source_citations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    citations: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        citation: dict[str, Any] = {}
        for key in ("type", "title", "path", "url", "status"):
            candidate = item.get(key)
            if isinstance(candidate, str):
                citation[key] = candidate
        for key in ("line_start", "line_end"):
            candidate = item.get(key)
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                citation[key] = candidate
        citations.append(citation)
    return citations


def _observe_source(
    kind: str,
    public_path: str,
    source_path: Path,
    expected_sha256: str,
    *,
    ceiling: int,
    limit_code: str,
    limit_field: str,
) -> SourceEvidence:
    try:
        first = read_bytes_bounded(
            source_path,
            ceiling=ceiling,
            code=limit_code,
            field=limit_field,
        )
        second = read_bytes_bounded(
            source_path,
            ceiling=ceiling,
            code=limit_code,
            field=limit_field,
        )
    except FileNotFoundError:
        return SourceEvidence(kind, public_path, expected_sha256, "missing")
    except (LimitError, OSError):
        return SourceEvidence(kind, public_path, expected_sha256, "unavailable")
    if first != second:
        return SourceEvidence(kind, public_path, expected_sha256, "unavailable")
    observed_sha256 = hashlib.sha256(first).hexdigest()
    state = "fresh" if observed_sha256 == expected_sha256 else "stale"
    return SourceEvidence(kind, public_path, expected_sha256, state, observed_sha256)


def _observe_repository(root: Path) -> RepositoryEvidence:
    git = shutil.which("git")
    if git is None:
        return RepositoryEvidence(state="unavailable")
    try:
        status = _git(
            git,
            root,
            "status",
            "--porcelain=v2",
            "--branch",
            "--untracked-files=normal",
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return RepositoryEvidence(state="unavailable")
    lines = status.splitlines()
    commit = _status_header(lines, "# branch.oid ")
    branch = _status_header(lines, "# branch.head ")
    dirty = any(not line.startswith("# ") for line in lines)
    if len(commit) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in commit
    ):
        return RepositoryEvidence(state="unavailable")
    if not branch or len(branch) > 1024:
        return RepositoryEvidence(state="unavailable")
    return RepositoryEvidence(state="observed", commit=commit, branch=branch, dirty=dirty)


def _status_header(lines: list[str], prefix: str) -> str:
    return next((line.removeprefix(prefix) for line in lines if line.startswith(prefix)), "")


def _git(executable: str, root: Path, *arguments: str) -> str:
    # Only fixed Git subcommands reach this helper; arguments are never request or manifest data.
    completed = subprocess.run(  # nosec B603
        [executable, "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=2,
        shell=False,
    )
    return completed.stdout.strip()


def _safe_manifest_name(manifest: Path, root: Path) -> str:
    try:
        return manifest.relative_to(root).as_posix()
    except ValueError:
        return manifest.name


def _repository_payload(evidence: RepositoryEvidence) -> dict[str, Any]:
    # The branch name is not published: it is free text read from the live checkout, outside
    # the export filter and secret scan, and can name tickets, customers or hosts (status 1.1).
    payload: dict[str, Any] = {"state": evidence.state}
    if evidence.state == "observed":
        payload.update({"commit": evidence.commit, "dirty": evidence.dirty})
    return payload


def _freshness_payload(sources: tuple[SourceEvidence, ...]) -> dict[str, Any]:
    counts = {state: 0 for state in ("fresh", "stale", "missing", "unavailable")}
    items: list[dict[str, Any]] = []
    for source in sources:
        counts[source.state] += 1
        item: dict[str, Any] = {
            "kind": source.kind,
            "path": source.path,
            "expected_sha256": source.expected_sha256,
            "state": source.state,
        }
        if source.observed_sha256:
            item["observed_sha256"] = source.observed_sha256
        items.append(item)
    aggregate = "unavailable"
    if sources:
        if counts["stale"]:
            aggregate = "stale"
        elif counts["missing"]:
            aggregate = "missing"
        elif counts["unavailable"]:
            aggregate = "unavailable"
        else:
            aggregate = "fresh"
    return {
        "state": aggregate,
        "checked": len(sources),
        **counts,
        "sources": items,
    }


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "STATUS_VERSION",
    "RepositoryEvidence",
    "SourceEvidence",
    "StatusObservation",
    "build_status_payload",
    "observe_project_status",
]
