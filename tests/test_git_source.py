"""Tests for the v0.3 GitSourceAdapter (reality/history evidence layer).

The fixture repositories are real local git repositories built with fixed
commands; every test enforces one of the adapter's documented guarantees:
bounded determinism, provenance, no-network/no-mutation behavior, secret
exclusion, and honest degradation.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest

from beacon.core.scaffold import init, to_payload
from beacon.sources.git import (
    GitCaps,
    GitSourceAdapter,
    GitSourceError,
    GitSourceUnavailable,
    records_to_git_evidence,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

_COMMIT_ENV = ("-c", "user.email=fixture@example.com", "-c", "user.name=Fixture")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *_COMMIT_ENV, *args],
        check=True,
        capture_output=True,
        timeout=60,
    )


def _commit_all(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--allow-empty", "-m", message)
    out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return out.stdout.decode("ascii").strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A small repository exercising every evidence kind."""
    root = tmp_path / "fixture-repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "README.md").write_text("# Fixture\n", encoding="utf-8")
    src = root / "src"
    src.mkdir()
    (src / "x.py").write_text("x = 1\n", encoding="utf-8")
    (src / "y.py").write_text("y = 2\n", encoding="utf-8")
    _commit_all(root, "add sources")
    (src / "x.py").write_text("x = 2\n", encoding="utf-8")
    (src / "y.py").write_text("y = 3\n", encoding="utf-8")
    _commit_all(root, "touch x and y together")
    _git(root, "mv", "src/x.py", "src/renamed.py")
    (src / "y.py").write_text("y = 4\n", encoding="utf-8")
    _commit_all(root, "rename x, touch y again")
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    _commit_all(root, "add sensitive config")
    _git(root, "tag", "-a", "v0.1.0", "-m", "first tag")
    return root


# ---------------------------------------------------------------------------
# Availability and failure modes
# ---------------------------------------------------------------------------


def test_unavailable_without_git_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    adapter = GitSourceAdapter(plain)
    assert adapter.is_available() is False
    with pytest.raises(GitSourceUnavailable):
        adapter.collect()


def test_empty_repo_raises_git_source_error(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    _git(root, "init", "-q")
    with pytest.raises(GitSourceError):
        GitSourceAdapter(root).collect()


# ---------------------------------------------------------------------------
# Determinism, provenance, and content
# ---------------------------------------------------------------------------


def test_collect_is_deterministic(repo: Path) -> None:
    adapter = GitSourceAdapter(repo)
    first = [dict(r.payload) for r in adapter.collect()]
    second = [dict(r.payload) for r in GitSourceAdapter(repo).collect()]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_head_record_matches_repository_state(repo: Path) -> None:
    records = GitSourceAdapter(repo).collect()
    head = next(r for r in records if r.kind == "git_head")
    expected = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout.decode("ascii")
    assert head.payload["commit"] == expected.strip()
    assert head.payload["branch"] in ("main", "master", "HEAD")
    assert head.payload["dirty"] is False
    assert head.payload["window_commits"] == 4
    assert any(c.kind == "commit" and c.value == head.payload["commit"] for c in head.citations)


def test_dirty_state_detected(repo: Path) -> None:
    (repo / "README.md").write_text("# changed\n", encoding="utf-8")
    records = GitSourceAdapter(repo).collect()
    head = next(r for r in records if r.kind == "git_head")
    assert head.payload["dirty"] is True
    assert head.payload["dirty_paths"] == 1


def test_rename_history_folded(repo: Path) -> None:
    records = GitSourceAdapter(repo).collect()
    renamed = next(r for r in records if r.payload.get("path") == "src/renamed.py")
    assert renamed.payload["renamed_from"] == ["src/x.py"]
    assert renamed.payload["changes"] == 1  # the rename commit itself
    assert renamed.payload["introduced_in"] is None  # rename, not an addition
    assert renamed.payload["last_commit"]
    original = next(r for r in records if r.payload.get("path") == "src/x.py")
    assert original.payload["changes"] == 3  # added, modified, renamed (old name)


def test_introduction_and_removal_recorded(repo: Path) -> None:
    records = GitSourceAdapter(repo).collect()
    y = next(r for r in records if r.payload.get("path") == "src/y.py")
    assert y.payload["introduced_in"]
    readme = next(r for r in records if r.payload.get("path") == "README.md")
    assert readme.payload["removed_in"] is None  # still tracked at HEAD


def test_recent_commits_and_tags_carry_provenance(repo: Path) -> None:
    records = GitSourceAdapter(repo).collect()
    commits = [r for r in records if r.kind == "git_commit"]
    assert commits
    for record in commits:
        assert record.citations[0].value == record.payload["commit"]
    tags = [r for r in records if r.kind == "git_tag"]
    assert [t.payload["name"] for t in tags] == ["v0.1.0"]
    assert tags[0].payload["commit"]


def test_co_change_pairs_require_two_co_occurrences(repo: Path) -> None:
    records = GitSourceAdapter(repo).collect()
    pairs = [r for r in records if r.kind == "git_co_change"]
    # src/x.py and src/y.py co-occurred in all three of their shared commits:
    # introduced together, modified together, and the rename commit touched
    # both lineages.
    assert any(
        set(r.payload["paths"]) == {"src/x.py", "src/y.py"} and r.payload["commits"] == 3
        for r in pairs
    )


def test_activity_buckets_by_top_level_directory(repo: Path) -> None:
    records = GitSourceAdapter(repo).collect()
    activity = {r.payload["path"]: r.payload["commits"] for r in records if r.kind == "git_activity"}
    assert activity.get("src") == 3
    # Only the README commit buckets here: the .env commit is excluded from
    # path-bearing evidence by design, even though "." leaks nothing.
    assert activity.get(".") == 1


# ---------------------------------------------------------------------------
# Secret exclusion
# ---------------------------------------------------------------------------


def test_sensitive_paths_never_appear_in_path_bearing_records(repo: Path) -> None:
    records = GitSourceAdapter(repo).collect()
    for record in records:
        serialized = json.dumps(record.payload, sort_keys=True)
        assert ".env" not in serialized
    inventory = next(r for r in records if r.kind == "git_inventory")
    # The sensitive file is counted in the total but never named anywhere.
    assert inventory.payload["tracked_file_count"] == 4


# ---------------------------------------------------------------------------
# Bounds and truncation honesty
# ---------------------------------------------------------------------------


def test_small_walk_cap_reports_truncation(repo: Path) -> None:
    adapter = GitSourceAdapter(repo, caps=GitCaps(log_commits=2))
    records = adapter.collect()
    head = next(r for r in records if r.kind == "git_head")
    assert head.payload["window_commits"] == 2
    assert head.payload["truncated"] is True


def test_invalid_caps_rejected() -> None:
    with pytest.raises(ValueError):
        GitCaps(recent_commits=0)


# ---------------------------------------------------------------------------
# Repository URL (replaces the .git/config read)
# ---------------------------------------------------------------------------


def test_repository_url_sanitized_and_raw_never_stored(repo: Path) -> None:
    _git(repo, "remote", "add", "origin", "https://user:sekrit@github.com/acme/acme.git")
    adapter = GitSourceAdapter(repo)
    url, findings = adapter.repository_url()
    assert url == "https://github.com/acme/acme.git"
    assert any(f.code == "sensitive_credential_url" and not f.blocked for f in findings)
    records = adapter.collect()
    assert "sekrit" not in json.dumps([r.payload for r in records])


def test_repository_url_absent_without_remote(repo: Path) -> None:
    url, findings = GitSourceAdapter(repo).repository_url()
    assert url is None
    assert findings == ()


# ---------------------------------------------------------------------------
# No mutation and no network
# ---------------------------------------------------------------------------


def test_collect_does_not_mutate_the_repository(repo: Path) -> None:
    def snapshot() -> dict[str, bytes | None]:
        files = {}
        git_dir = repo / ".git"
        for name in ("index", "HEAD", "refs", "config"):
            candidate = git_dir / name
            if candidate.is_file():
                files[name] = candidate.read_bytes()
            elif candidate.is_dir():
                for child in sorted(candidate.rglob("*")):
                    if child.is_file():
                        files[str(child.relative_to(git_dir))] = child.read_bytes()
        return files

    before = snapshot()
    GitSourceAdapter(repo).collect()
    assert snapshot() == before


# ---------------------------------------------------------------------------
# Init integration
# ---------------------------------------------------------------------------


def _v11_schema() -> dict:
    path = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "beacon-init-report-1.1.schema.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_init_includes_git_evidence_section(tmp_path: Path, repo: Path) -> None:
    report = init(repo)
    assert report.git_evidence is not None
    assert report.git_evidence["adapter"] == "git"
    assert report.git_evidence["head"] is not None
    assert report.git_evidence["window_commits"] == 4
    payload = to_payload(report)
    jsonschema.validate(payload, _v11_schema())


def test_init_without_git_omits_the_section(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "README.md").write_text("# Plain\n", encoding="utf-8")
    report = init(plain)
    assert report.git_evidence is None
    payload = to_payload(report)
    assert "git_evidence" not in payload
    jsonschema.validate(payload, _v11_schema())


def test_init_prefers_adapter_url_over_config_read(tmp_path: Path, repo: Path) -> None:
    _git(repo, "remote", "add", "origin", "https://github.com/acme/from-adapter.git")
    # A conflicting legacy config value must lose to the resolved remote.
    (repo / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/acme/from-config.git\n',
        encoding="utf-8",
    )
    report = init(repo)
    assert report.git_evidence is not None
    repository = next(
        f for f in report.discovered if f.manifest_path == "project.repository"
    )
    assert any(e.kind == "git_remote" for e in repository.evidence)


def test_records_to_git_evidence_is_a_pure_projection(repo: Path) -> None:
    records = GitSourceAdapter(repo).collect()
    first = records_to_git_evidence(records)
    second = records_to_git_evidence(records)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
