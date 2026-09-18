"""Deterministic, bounded, local Git evidence for init and the v0.3 build.

:class:`GitSourceAdapter` turns a repository's local git object database into
normalized :class:`~beacon.sources.base.NormalizedRecord` values: HEAD state,
tracked-file inventory summary, tags, recent commits, per-file history (last
change, churn, introduction, removal, renames), bounded co-change pairs, and
recent activity by top-level directory. One adapter serves both consumers:
``beacon init`` (starter-manifest evidence) today and ``beacon build`` (the
multi-source pipeline's repository tier) later.

Safety contract:

* **Reality and history only.** Git statistics never become architecture,
  guardrails, or any other intent-bearing manifest field. Consumers decide
  meaning; the adapter decides nothing.
* **Local only.** Every command is a read-only, local git query. There is no
  fetch, no push, no remote contact of any kind. ``GIT_TERMINAL_PROMPT=0``
  guarantees git cannot prompt for network credentials, and every invocation
  uses ``--no-optional-locks`` so git never writes to the repository (not even
  an index refresh).
* **Fixed commands, no shell.** Each command is a fixed argument vector
  executed directly (``shell=False``) with a hard timeout and a hard output
  byte cap; an over-producing command is killed, and the truncation is
  reported, never hidden.
* **Deterministic.** For a frozen repository state, ``collect()`` returns
  byte-identical records: fixed command sets, fixed caps, stable sort orders,
  and no wall-clock collection stamps.
* **Provenance.** Every record cites the concrete upstream objects it was
  derived from; a git commit digest *is* a content address, so commit
  citations double as source digests. Evidence outside the walked window is
  omitted (with ``window_commits`` stated), never extrapolated.
* **Secret exclusions.** Known-sensitive paths (via
  :func:`beacon.core.security.is_known_sensitive_path`) never appear in any
  path-bearing record; they are counted in the tracked-file total only. A
  longer, separate generated-file policy belongs to the files adapter.
"""

from __future__ import annotations

import os

# Fixed local Git inspection is the only subprocess use here: fixed argv, no
# shell, no network, bounded output.
import subprocess  # nosec B404
from collections import Counter
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import cast

from beacon.core.discovery import sanitize_remote_url
from beacon.core.security import (
    SecurityFinding,
    detect_sensitive_text,
    is_known_sensitive_path,
)
from beacon.sources.base import (
    CITATION_COMMIT,
    CITATION_PATH,
    KIND_GIT_ACTIVITY,
    KIND_GIT_CO_CHANGE,
    KIND_GIT_COMMIT,
    KIND_GIT_FILE_HISTORY,
    KIND_GIT_HEAD,
    KIND_GIT_INVENTORY,
    KIND_GIT_TAG,
    Citation,
    NormalizedRecord,
)

ADAPTER_NAME = "git"
ADAPTER_VERSION = "1"

#: Field separator inside one log header record.
_US = "\x1f"
#: Record separator starting one log block.
_RS = "\x1e"

_GIT_TIMEOUT_SECONDS = 60
_HEX_RE_ALPHABET = frozenset("0123456789abcdef")

#: Redaction marker for commit subjects that carry high-confidence secret
#: material (mirroring Beacon's export-time secret policy). The commit digest
#: remains the citation, so the underlying commit stays locally identifiable
#: without the report reproducing the secret.
REDACTED_SUBJECT = "[redacted]"


def _is_git_oid(value: str) -> bool:
    """True for a SHA-1 (40) or SHA-256 (64) hex object id.

    Mirrors the v0.2 verified-status policy (`status.py`), which deliberately
    accepts both object formats so SHA-256 repositories are not rejected.
    """
    return len(value) in (40, 64) and all(character in _HEX_RE_ALPHABET for character in value)


def _strip_control(text: str) -> str:
    return "".join(ch for ch in text if ord(ch) >= 0x20 and ord(ch) != 0x7F)


def _epoch_or_zero(iso_date: str) -> float:
    try:
        return datetime.fromisoformat(iso_date).timestamp()
    except ValueError:
        return 0.0


class GitSourceError(RuntimeError):
    """The repository exists but a bounded git query failed."""


class GitSourceUnavailable(RuntimeError):
    """No git repository at the root, or no usable git executable."""


@dataclass(frozen=True)
class GitCaps:
    """Fixed evidence bounds. Raising one is a deliberate, reviewed change."""

    log_commits: int = 400
    recent_commits: int = 20
    tags: int = 30
    file_history_entries: int = 200
    co_change_pairs: int = 25
    co_change_max_files_per_commit: int = 20
    activity_entries: int = 32
    tracked_dirs: int = 64
    subject_max_chars: int = 120
    branch_max_chars: int = 200
    path_max_bytes: int = 1024
    head_output_bytes: int = 4 * 1024
    status_output_bytes: int = 1 * 1024 * 1024
    inventory_output_bytes: int = 8 * 1024 * 1024
    tags_output_bytes: int = 1 * 1024 * 1024
    walk_output_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"GitCaps.{item.name} must be a positive integer")


@dataclass(frozen=True)
class _FileHistory:
    """Aggregated per-path history derived from one bounded log walk."""

    changes: int = 0
    last_commit: str | None = None
    last_date: str | None = None
    introduced_in: str | None = None
    removed_in: str | None = None
    renamed_from: tuple[str, ...] = ()


@dataclass
class _MutableFileHistory:
    """Accumulator used while folding one walk; frozen on conversion."""

    changes: int = 0
    last_commit: str | None = None
    last_date: str | None = None
    introduced_in: str | None = None
    removed_in: str | None = None
    renamed_from: list[str] = field(default_factory=list)

    def freeze(self) -> _FileHistory:
        return _FileHistory(
            changes=self.changes,
            last_commit=self.last_commit,
            last_date=self.last_date,
            introduced_in=self.introduced_in,
            removed_in=self.removed_in,
            renamed_from=tuple(self.renamed_from),
        )


@dataclass(frozen=True)
class _WalkCommit:
    """One parsed commit block from the history walk."""

    sha: str
    date: str
    subject: str
    statuses: tuple[tuple[str, str, str | None], ...]


class GitSourceAdapter:
    """Bounded, deterministic git evidence for one repository root."""

    def __init__(
        self,
        root: str | Path,
        *,
        caps: GitCaps | None = None,
        git_executable: str = "git",
    ) -> None:
        self._root = Path(root)
        self._caps = caps if caps is not None else GitCaps()
        self._git = git_executable
        self._truncated = False
        self._available: bool | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """True when a git repository (or worktree) sits at the root and git runs."""
        if self._available is None:
            dot_git = self._root / ".git"
            usable = dot_git.is_dir() or dot_git.is_file()
            if usable:
                try:
                    self._run(["--version"], self._caps.head_output_bytes)
                except (GitSourceError, OSError):
                    usable = False
            self._available = usable
        return self._available

    def repository_url(self) -> tuple[str | None, tuple[SecurityFinding, ...]]:
        """Return the sanitized origin URL (or ``None``) plus URL findings.

        This replaces init's direct ``.git/config`` read: git resolves the
        same value correctly for worktrees and URL rewrites. The raw value is
        never stored; sanitization reuses discovery's URL policy.
        """
        try:
            out, truncated, code = self._run(
                ["remote", "get-url", "origin"], self._caps.head_output_bytes
            )
        except GitSourceError:
            return None, ()
        if code != 0 or truncated:
            return None, ()
        raw = out.decode("utf-8", errors="replace").strip()
        if not raw:
            return None, ()
        sanitized, findings = sanitize_remote_url(raw)
        return sanitized, findings

    def collect(self) -> tuple[NormalizedRecord, ...]:
        """Return the adapter's deterministic evidence records.

        Raises :class:`GitSourceUnavailable` when there is no git repository
        or no usable git executable, and :class:`GitSourceError` when the
        repository exists but a bounded query fails (including an empty
        repository with no HEAD).
        """
        self._truncated = False
        self._available = None
        if not self.is_available():
            raise GitSourceUnavailable("no git repository at the given root")
        head_sha = self._head_sha()
        branch = self._branch()
        dirty, dirty_paths = self._dirty_state()
        tracked_total, tracked_dirs = self._inventory()
        tags = self._tags()
        walk = self._walk()
        head_date = walk[0].date if walk else ""

        records: list[NormalizedRecord] = [
            self._head_record(head_sha, head_date, branch, dirty, dirty_paths, tracked_total, walk),
            self._inventory_record(tracked_total, tracked_dirs),
        ]
        records.extend(self._tag_records(tags))
        records.extend(self._commit_records(walk))
        records.extend(self._file_history_records(walk))
        records.extend(self._activity_records(walk, head_sha))
        records.extend(self._co_change_records(walk, head_sha))
        return tuple(records)

    # ------------------------------------------------------------------
    # Command execution (fixed argv, no shell, hard caps)
    # ------------------------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        return env

    def _run(self, args: list[str], max_bytes: int) -> tuple[bytes, bool, int]:
        """Run one fixed git command; return ``(stdout, truncated, returncode)``.

        Output is read incrementally and the child is killed once *max_bytes*
        is reached (``truncated=True``), so no command can exhaust memory.
        """
        argv = [self._git, "--no-optional-locks", *args]
        try:
            proc = subprocess.Popen(  # nosec B603
                argv,
                cwd=self._root,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self._env(),
            )
        except OSError as exc:
            raise GitSourceError(f"git executable unusable: {self._git}") from exc
        chunks: list[bytes] = []
        total = 0
        killed = False
        try:
            stream = proc.stdout
            if stream is None:  # pragma: no cover - guaranteed by stdout=PIPE
                raise GitSourceError("git produced no readable output stream")
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total >= max_bytes:
                    keep = max_bytes - (total - len(chunk))
                    chunks.append(chunk[:keep])
                    self._truncated = True
                    proc.kill()
                    killed = True
                    break
                chunks.append(chunk)
            code = proc.wait(timeout=_GIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            proc.wait()
            raise GitSourceError("git command timed out") from exc
        finally:
            stream = proc.stdout
            if stream is not None:
                stream.close()
        if killed:
            return b"".join(chunks), True, 0
        return b"".join(chunks), False, code

    def _require_run(self, args: list[str], max_bytes: int, what: str) -> tuple[bytes, bool]:
        out, truncated, code = self._run(args, max_bytes)
        if code != 0:
            raise GitSourceError(f"git query failed: {what}")
        return out, truncated

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def _head_sha(self) -> str:
        out, _ = self._require_run(
            ["rev-parse", "--verify", "HEAD"], self._caps.head_output_bytes, "rev-parse HEAD"
        )
        sha = out.decode("ascii", errors="replace").strip()
        if not _is_git_oid(sha):
            raise GitSourceError("git head commit is not a 40- or 64-hex digest")
        return sha

    def _branch(self) -> str:
        out, truncated = self._require_run(
            ["rev-parse", "--abbrev-ref", "HEAD"],
            self._caps.head_output_bytes,
            "rev-parse --abbrev-ref",
        )
        name = out.decode("utf-8", errors="replace").strip()
        if truncated or not name:
            return "HEAD"
        if len(name) > self._caps.branch_max_chars:
            name = name[: self._caps.branch_max_chars]
            self._truncated = True
        return _strip_control(name)

    def _dirty_state(self) -> tuple[bool, int]:
        out, _truncated = self._require_run(
            ["status", "--porcelain=v1", "-z"], self._caps.status_output_bytes, "status"
        )
        count = sum(1 for token in out.split(b"\x00") if token)
        return count > 0, count

    def _inventory(self) -> tuple[int, list[tuple[str, int]]]:
        out, _ = self._require_run(
            ["ls-files", "-z"], self._caps.inventory_output_bytes, "ls-files"
        )
        total = 0
        dirs: Counter[str] = Counter()
        for token in out.split(b"\x00"):
            if not token:
                continue
            total += 1
            rel = token.decode("utf-8", errors="replace")
            if is_known_sensitive_path(rel):
                continue
            top = rel.split("/", 1)[0] if "/" in rel else "."
            dirs[top] += 1
        ordered = sorted(dirs.items(), key=lambda item: (-item[1], item[0]))
        if len(ordered) > self._caps.tracked_dirs:
            self._truncated = True
            ordered = ordered[: self._caps.tracked_dirs]
        return total, ordered

    def _walk(self) -> list[_WalkCommit]:
        """Run the single bounded history walk in git's reverse-chronological order."""
        out, _ = self._require_run(
            [
                "log",
                f"-n{self._caps.log_commits}",
                "--name-status",
                "-z",
                "-M",
                # %xHH hex escapes: raw control bytes cannot survive Windows
                # argv quoting, so git decodes them from literal format text.
                "--format=%x1e%H%x1f%aI%x1f%s%x1f",
            ],
            self._caps.walk_output_bytes,
            "log walk",
        )
        blocks: list[_WalkCommit] = []
        for raw_block in out.split(b"\x1e"):
            if not raw_block:
                continue
            tokens = raw_block.split(b"\x00")
            header = tokens[0].lstrip(b"\n").decode("utf-8", errors="replace")
            parts = header.split(_US)
            if len(parts) < 3 or not parts[0]:
                raise GitSourceError("unparseable log header")
            sha, date, subject = parts[0], parts[1], _strip_control(parts[2])
            if not _is_git_oid(sha):
                raise GitSourceError("git commit is not a 40- or 64-hex digest")
            if len(subject) > self._caps.subject_max_chars:
                subject = subject[: self._caps.subject_max_chars]
                self._truncated = True
            statuses: list[tuple[str, str, str | None]] = []
            i = 1
            while i < len(tokens):
                # The first status token carries the newline that separates
                # git's format output from the NUL-framed status records.
                status = tokens[i].lstrip(b"\n").decode("utf-8", errors="replace")
                if not status:
                    i += 1
                    continue
                path = (
                    tokens[i + 1].decode("utf-8", errors="replace") if i + 1 < len(tokens) else ""
                )
                orig: str | None = None
                if status[:1] in ("R", "C") and i + 2 < len(tokens):
                    orig = tokens[i + 2].decode("utf-8", errors="replace")
                    i += 1
                statuses.append((status[:1], path, orig))
                i += 2
            blocks.append(
                _WalkCommit(sha=sha, date=date, subject=subject, statuses=tuple(statuses))
            )
        if len(blocks) >= self._caps.log_commits:
            # The walk filled its cap, so older history may exist outside the
            # window; report that honestly instead of implying completeness.
            self._truncated = True
        return blocks

    def _tags(self) -> list[tuple[str, str, str]]:
        """Return bounded ``(name, peeled_commit, date)`` triples.

        ``%(objectname)`` is the tag object's own digest for an annotated tag,
        not the commit it names, so every tag is peeled to its target commit:
        a lightweight tag's ``%(*objectname)`` is empty and ``%(objectname)``
        already is the commit; an annotated tag pointing at a commit peels via
        ``%(*objectname)``; a nested tag (tag -> tag) is peeled with one
        ``rev-parse <ref>^{commit}`` call (bounded by the tag cap).
        """
        out, _ = self._require_run(
            [
                "tag",
                "--sort=-creatordate",
                "--format=%(refname:short)%09%(objectname)%09%(*objectname)"
                "%09%(*objecttype)%09%(creatordate:iso-strict)",
            ],
            self._caps.tags_output_bytes,
            "tag list",
        )
        parsed: list[tuple[str, str, str, float]] = []
        for line in out.decode("utf-8", errors="replace").splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 5:
                raise GitSourceError("unparseable tag line")
            name, object_name, peeled, peeled_type, date = parts
            if peeled and peeled_type == "commit":
                commit = peeled
            elif peeled and peeled_type == "tag":
                commit = self._peel_tag(name) or peeled
            elif not peeled:
                commit = object_name
            else:
                # A tag pointing at a non-commit object; record the direct
                # target honestly rather than guessing a commit.
                commit = peeled
            parsed.append((name, commit, date, _epoch_or_zero(date)))
        parsed.sort(key=lambda item: (-item[3], item[0]))
        if len(parsed) > self._caps.tags:
            self._truncated = True
            parsed = parsed[: self._caps.tags]
        return [(name, commit, date) for name, commit, date, _ in parsed]

    def _peel_tag(self, name: str) -> str | None:
        """Fully peel one tag reference to its commit (or None on failure)."""
        try:
            out, truncated, code = self._run(
                ["rev-parse", "--verify", "--quiet", f"refs/tags/{name}^{{commit}}"],
                self._caps.head_output_bytes,
            )
        except GitSourceError:
            return None
        if code != 0 or truncated:
            return None
        commit = out.decode("ascii", errors="replace").strip()
        return commit if _is_git_oid(commit) else None

    # ------------------------------------------------------------------
    # Record assembly
    # ------------------------------------------------------------------

    def _head_record(
        self,
        sha: str,
        head_date: str,
        branch: str,
        dirty: bool,
        dirty_paths: int,
        tracked_total: int,
        walk: list[_WalkCommit],
    ) -> NormalizedRecord:
        payload: dict[str, object] = {
            "commit": sha,
            "branch": branch,
            "dirty": dirty,
            "dirty_paths": dirty_paths,
            "tracked_file_count": tracked_total,
            "window_commits": len(walk),
            "truncated": self._truncated,
        }
        return NormalizedRecord(
            identity="git:head",
            kind=KIND_GIT_HEAD,
            payload=payload,
            citations=(Citation(CITATION_COMMIT, sha),),
            adapter=ADAPTER_NAME,
            adapter_version=ADAPTER_VERSION,
            confidence="high",
            confidence_reason="read directly from the local git object database",
            freshness=head_date or None,
        )

    def _inventory_record(
        self, tracked_total: int, dirs: list[tuple[str, int]]
    ) -> NormalizedRecord:
        payload: dict[str, object] = {
            "tracked_file_count": tracked_total,
            "tracked_dirs": [{"path": path, "files": count} for path, count in dirs],
        }
        return NormalizedRecord(
            identity="git:inventory",
            kind=KIND_GIT_INVENTORY,
            payload=payload,
            citations=(Citation(CITATION_PATH, "."),),
            adapter=ADAPTER_NAME,
            adapter_version=ADAPTER_VERSION,
            confidence="high",
            confidence_reason=(
                "derived from the git index (ls-files); sensitive filenames are counted in "
                "the total but never named"
            ),
        )

    def _tag_records(self, tags: list[tuple[str, str, str]]) -> list[NormalizedRecord]:
        return [
            NormalizedRecord(
                identity=f"git:tag:{name}",
                kind=KIND_GIT_TAG,
                payload={"name": name, "commit": sha, "date": date},
                citations=(Citation(CITATION_COMMIT, sha),),
                adapter=ADAPTER_NAME,
                adapter_version=ADAPTER_VERSION,
                confidence="high",
                confidence_reason="read from the local git ref database",
                freshness=date,
            )
            for name, sha, date in tags
        ]

    def _commit_records(self, walk: list[_WalkCommit]) -> list[NormalizedRecord]:
        records = []
        for commit in walk[: self._caps.recent_commits]:
            # Commit subjects are attacker- and accident-controlled text that
            # this adapter exists to publish, so they pass through Beacon's
            # high-confidence secret detector before entering any artifact;
            # unsafe subjects are redacted, never reproduced.
            findings = detect_sensitive_text(commit.subject, path=commit.sha)
            redacted = bool(findings)
            records.append(
                NormalizedRecord(
                    identity=f"git:commit:{commit.sha}",
                    kind=KIND_GIT_COMMIT,
                    payload={
                        "commit": commit.sha,
                        "date": commit.date,
                        "subject": REDACTED_SUBJECT if redacted else commit.subject,
                        "subject_redacted": redacted,
                    },
                    citations=(Citation(CITATION_COMMIT, commit.sha),),
                    adapter=ADAPTER_NAME,
                    adapter_version=ADAPTER_VERSION,
                    confidence="high",
                    confidence_reason="read from the local git object database",
                    freshness=commit.date,
                )
            )
        return records

    def _file_history_records(self, walk: list[_WalkCommit]) -> list[NormalizedRecord]:
        aggregated = _aggregate_files(walk, self._caps)
        ordered = sorted(aggregated.items(), key=lambda item: (-item[1].changes, item[0]))
        if len(ordered) > self._caps.file_history_entries:
            self._truncated = True
            ordered = ordered[: self._caps.file_history_entries]
        records = []
        for path, agg in ordered:
            citations = [Citation(CITATION_PATH, path)]
            if agg.last_commit:
                citations.append(Citation(CITATION_COMMIT, agg.last_commit))
            records.append(
                NormalizedRecord(
                    identity=f"git:file:{path}",
                    kind=KIND_GIT_FILE_HISTORY,
                    payload={
                        "path": path,
                        "changes": agg.changes,
                        "last_commit": agg.last_commit,
                        "last_date": agg.last_date,
                        "introduced_in": agg.introduced_in,
                        "removed_in": agg.removed_in,
                        "renamed_from": list(agg.renamed_from),
                    },
                    citations=tuple(citations),
                    adapter=ADAPTER_NAME,
                    adapter_version=ADAPTER_VERSION,
                    confidence="high",
                    confidence_reason=(
                        "derived from the bounded commit walk (window_commits in the head record)"
                    ),
                    freshness=agg.last_date,
                )
            )
        return records

    def _activity_records(self, walk: list[_WalkCommit], head_sha: str) -> list[NormalizedRecord]:
        counts: Counter[str] = Counter()
        for commit in walk:
            touched: set[str] = set()
            for _code, path, orig in commit.statuses:
                for candidate in (path, orig):
                    if candidate and not is_known_sensitive_path(candidate):
                        touched.add(candidate.split("/", 1)[0] if "/" in candidate else ".")
            for top in touched:
                counts[top] += 1
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if len(ordered) > self._caps.activity_entries:
            self._truncated = True
            ordered = ordered[: self._caps.activity_entries]
        newest = walk[0].date if walk else None
        return [
            NormalizedRecord(
                identity=f"git:activity:{top}",
                kind=KIND_GIT_ACTIVITY,
                payload={"path": top, "commits": count, "window_commits": len(walk)},
                citations=(Citation(CITATION_COMMIT, head_sha),),
                adapter=ADAPTER_NAME,
                adapter_version=ADAPTER_VERSION,
                confidence="medium",
                confidence_reason=(
                    "top-level directory bucketing is a heuristic over the bounded walk"
                ),
                freshness=newest,
            )
            for top, count in ordered
        ]

    def _co_change_records(self, walk: list[_WalkCommit], head_sha: str) -> list[NormalizedRecord]:
        pairs: Counter[tuple[str, str]] = Counter()
        for commit in walk:
            clean: list[str] = []
            for _code, path, orig in commit.statuses:
                for candidate in (path, orig):
                    if candidate and not is_known_sensitive_path(candidate):
                        if candidate not in clean:
                            clean.append(candidate)
            if len(clean) < 2 or len(clean) > self._caps.co_change_max_files_per_commit:
                continue
            for i, first in enumerate(clean):
                for second in clean[i + 1 :]:
                    key = (first, second) if first < second else (second, first)
                    pairs[key] += 1
        ordered = [(pair, count) for pair, count in sorted(pairs.items()) if count >= 2]
        ordered.sort(key=lambda item: (-item[1], item[0]))
        if len(ordered) > self._caps.co_change_pairs:
            self._truncated = True
            ordered = ordered[: self._caps.co_change_pairs]
        newest = walk[0].date if walk else None
        return [
            NormalizedRecord(
                identity=f"git:cochange:{first}~{second}",
                kind=KIND_GIT_CO_CHANGE,
                payload={"paths": [first, second], "commits": count},
                citations=(Citation(CITATION_COMMIT, head_sha),),
                adapter=ADAPTER_NAME,
                adapter_version=ADAPTER_VERSION,
                confidence="medium",
                confidence_reason=(
                    "co-occurrence within single commits is a heuristic over the bounded walk"
                ),
                freshness=newest,
            )
            for (first, second), count in ordered
        ]


# ----------------------------------------------------------------------
# Walk aggregation and serialization helpers
# ----------------------------------------------------------------------


def _aggregate_files(walk: list[_WalkCommit], caps: GitCaps) -> dict[str, _FileHistory]:
    """Aggregate the reverse-chronological walk into per-path history.

    The first walk appearance of a path is its most recent change, so
    ``last_commit``/``last_date`` are set on first sight and ``changes``
    counts every walk commit that touched the path under that name (a rename
    touches both the old and the new name). ``introduced_in`` records an
    ``A`` status, ``removed_in`` a ``D`` status, and ``renamed_from`` folds
    rename/copy source names in walk order.
    """
    files: dict[str, _MutableFileHistory] = {}

    def entry(path: str) -> _MutableFileHistory:
        return files.setdefault(path, _MutableFileHistory())

    def emit(path: str) -> bool:
        return (
            not is_known_sensitive_path(path) and len(path.encode("utf-8")) <= caps.path_max_bytes
        )

    for commit in walk:
        touched: set[str] = set()
        for code, path, orig in commit.statuses:
            # Git name-status prints the OLD name first, then the NEW name
            # for rename/copy records, so `path` is the old name here.
            if orig is not None and emit(orig):
                touched.add(orig)
            if emit(path):
                touched.add(path)
            if code in ("A", "D") and emit(path):
                item = entry(path)
                if code == "A":
                    if item.introduced_in is None:
                        item.introduced_in = commit.sha
                elif item.removed_in is None:
                    item.removed_in = commit.sha
            if code in ("R", "C") and orig is not None and emit(path) and emit(orig):
                # `path` is the old name; the folded source history lives on
                # the NEW name (orig) so follow-a-rename reads naturally.
                item = entry(orig)
                item.renamed_from.append(path)
        for path in touched:
            item = entry(path)
            item.changes += 1
            if item.last_commit is None:
                item.last_commit = commit.sha
                item.last_date = commit.date
    return {path: item.freeze() for path, item in files.items()}


def records_to_git_evidence(records: tuple[NormalizedRecord, ...]) -> dict[str, object]:
    """Serialize collected records into the init-report ``git_evidence`` section.

    The section is the adapter's owned projection (schema
    ``beacon-init-report-1.1``); ``beacon build`` will consume the records
    directly instead of this report-shaped projection.
    """
    head: dict[str, object] | None = None
    tracked_dirs: list[dict[str, object]] = []
    tags: list[dict[str, object]] = []
    recent_commits: list[dict[str, object]] = []
    activity: list[dict[str, object]] = []
    file_history: list[dict[str, object]] = []
    co_change: list[dict[str, object]] = []
    tracked_file_count = 0
    window_commits = 0
    truncated = False

    for record in records:
        kind = record.kind
        if kind == KIND_GIT_HEAD:
            head = {
                "commit": record.payload["commit"],
                "branch": record.payload["branch"],
                "dirty": record.payload["dirty"],
                "dirty_paths": record.payload["dirty_paths"],
            }
            window_commits = cast(int, record.payload["window_commits"])
            truncated = cast(bool, record.payload["truncated"])
            tracked_file_count = cast(int, record.payload["tracked_file_count"])
        elif kind == KIND_GIT_INVENTORY:
            tracked_file_count = cast(int, record.payload["tracked_file_count"])
            raw_dirs = record.payload["tracked_dirs"]
            if isinstance(raw_dirs, list):
                tracked_dirs = [dict(item) for item in raw_dirs]
        elif kind == KIND_GIT_TAG:
            tags.append(dict(record.payload))
        elif kind == KIND_GIT_COMMIT:
            recent_commits.append(
                {
                    "commit": record.payload["commit"],
                    "date": record.payload["date"],
                    "subject": record.payload["subject"],
                    "subject_redacted": record.payload["subject_redacted"],
                }
            )
        elif kind == KIND_GIT_FILE_HISTORY:
            file_history.append(dict(record.payload))
        elif kind == KIND_GIT_ACTIVITY:
            activity.append({"path": record.payload["path"], "commits": record.payload["commits"]})
        elif kind == KIND_GIT_CO_CHANGE:
            co_change.append(
                {"paths": record.payload["paths"], "commits": record.payload["commits"]}
            )
    return {
        "adapter": ADAPTER_NAME,
        "adapter_version": ADAPTER_VERSION,
        "head": head,
        "tracked_file_count": tracked_file_count,
        "tracked_dirs": tracked_dirs,
        "tags": tags,
        "recent_commits": recent_commits,
        "activity": activity,
        "file_history": file_history,
        "co_change": co_change,
        "window_commits": window_commits,
        "truncated": truncated,
    }


__all__ = [
    "ADAPTER_NAME",
    "ADAPTER_VERSION",
    "GitCaps",
    "GitSourceAdapter",
    "GitSourceError",
    "GitSourceUnavailable",
    "REDACTED_SUBJECT",
    "records_to_git_evidence",
]
