"""Tests for the v0.3 GitSourceAdapter (reality/history evidence layer).

The fixture repositories are real local git repositories built with fixed
commands; every test enforces one of the adapter's documented guarantees:
bounded determinism, provenance, no-network/no-mutation behavior, secret
exclusion, and honest degradation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import jsonschema
import pytest

import beacon.sources.git as gitmod
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
        assert record.payload["subject_redacted"] is False
    tags = [r for r in records if r.kind == "git_tag"]
    assert [t.payload["name"] for t in tags] == ["v0.1.0"]
    # The fixture tags with `-a`, so git's %(objectname) is the tag object's
    # own digest; the record must cite the peeled target commit instead.
    tag_object = (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "v0.1.0"],
            check=True,
            capture_output=True,
            timeout=60,
        )
        .stdout.decode("ascii")
        .strip()
    )
    peeled = (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "v0.1.0^{commit}"],
            check=True,
            capture_output=True,
            timeout=60,
        )
        .stdout.decode("ascii")
        .strip()
    )
    assert tags[0].payload["commit"] == peeled
    assert tag_object != peeled  # the fixture must actually exercise peeling
    assert tags[0].citations[0].value == peeled


def test_commit_subject_carrying_a_secret_is_redacted(repo: Path) -> None:
    secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    assert len(secret) == 40  # ghp_ prefix plus the 36-character body
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"leak attempt {secret}")
    records = GitSourceAdapter(repo).collect()
    serialized = json.dumps([r.payload for r in records])
    assert secret not in serialized
    flagged = next(r for r in records if r.kind == "git_commit" if r.payload["subject_redacted"])
    assert flagged.payload["subject"] == "[redacted]"
    # Clean subjects pass through untouched and are flagged as such.
    clean = next(
        r
        for r in records
        if r.kind == "git_commit" and r.payload["commit"] == flagged.payload["commit"]
    )
    assert "leak attempt" not in clean.payload["subject"]
    earlier = next(
        r for r in records if r.kind == "git_commit" and "sensitive" in r.payload["subject"]
    )
    assert earlier.payload["subject_redacted"] is False


def test_sha256_repository_accepted(tmp_path: Path) -> None:
    root = tmp_path / "sha256-repo"
    root.mkdir()
    probe = subprocess.run(
        ["git", "-C", str(root), "init", "-q", "--object-format=sha256"],
        capture_output=True,
        timeout=60,
    )
    if probe.returncode != 0:
        pytest.skip("this git does not support --object-format=sha256")
    (root / "README.md").write_text("# Sha256\n", encoding="utf-8")
    _commit_all(root, "first commit")
    records = GitSourceAdapter(root).collect()
    head = next(r for r in records if r.kind == "git_head")
    assert len(head.payload["commit"]) == 64
    assert all(c.value == head.payload["commit"] for c in head.citations if c.kind == "commit")
    section = records_to_git_evidence(records)
    jsonschema.validate(
        {
            "beacon_init_report_version": "1.1",
            "git_evidence": section,
            "operation": "create",
            "repository_root": ".",
            "manifest_path": "beacon.yaml",
            "would_write": False,
            "written": False,
            "replaced": False,
            "discovered": [],
            "omitted": [],
            "review_required": [],
            "security_findings": [],
        },
        _v11_schema(),
    )


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
    activity = {
        r.payload["path"]: r.payload["commits"] for r in records if r.kind == "git_activity"
    }
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


def test_late_cap_hits_are_reflected_in_the_head_record(repo: Path) -> None:
    """A cap hit by a projection built after the head record still reports."""
    adapter = GitSourceAdapter(repo, caps=GitCaps(file_history_entries=1))
    records = adapter.collect()
    head = next(r for r in records if r.kind == "git_head")
    file_histories = [r for r in records if r.kind == "git_file_history"]
    # The cap genuinely clipped this projection (the fixture has 4 eligible
    # files, and .env is excluded before the cap applies).
    assert len(file_histories) == 1
    assert head.payload["truncated"] is True
    assert records_to_git_evidence(records)["truncated"] is True


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
    path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "schemas"
        / "beacon-init-report-1.1.schema.json"
    )
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
    repository = next(f for f in report.discovered if f.manifest_path == "project.repository")
    assert any(e.kind == "git_remote" for e in repository.evidence)


def test_records_to_git_evidence_is_a_pure_projection(repo: Path) -> None:
    records = GitSourceAdapter(repo).collect()
    first = records_to_git_evidence(records)
    second = records_to_git_evidence(records)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# Hard deadline and process-tree kill
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _fake_git(tmp_path: Path, body: str) -> Path:
    """An executable stand-in for git that answers ``--version`` and runs *body*.

    On Windows it is a ``.cmd`` wrapper around a Python child, which mirrors
    Git for Windows' ``cmd\\git.exe`` wrapper: killing only the wrapper would
    leave the child running.
    """
    script = tmp_path / "fake_git.py"
    script.write_text(
        "import os, sys, time\n"
        "if '--version' in sys.argv:\n"
        "    print('git version 2.99.0')\n"
        "    sys.exit(0)\n" + body,
        encoding="utf-8",
    )
    if sys.platform == "win32":
        wrapper = tmp_path / "fake_git.cmd"
        wrapper.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        return wrapper
    wrapper = tmp_path / "fake_git"
    wrapper.write_text(f"#!{sys.executable}\n" + script.read_text(encoding="utf-8"))
    wrapper.chmod(0o755)
    return wrapper


def test_silent_hung_git_is_killed_at_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "hung"
    (root / ".git").mkdir(parents=True)
    pidfile = tmp_path / "child.pid"
    fake = _fake_git(
        tmp_path,
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(20)\n",
    )
    monkeypatch.setattr(gitmod, "_GIT_TIMEOUT_SECONDS", 1)
    started = time.monotonic()
    with pytest.raises(GitSourceError):
        GitSourceAdapter(root, git_executable=str(fake)).collect()
    elapsed = time.monotonic() - started
    # The deadline covers the whole command, not just the wait after EOF.
    assert elapsed < 10, f"collect() blocked for {elapsed:.1f}s past a 1s deadline"
    # The kill reaches the process tree, not only a wrapper process.
    pid = int(pidfile.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _pid_alive(pid)


# ---------------------------------------------------------------------------
# Child environment and repository-config hardening
# ---------------------------------------------------------------------------


def _rev_parse_head(root: Path) -> str:
    return (
        subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            timeout=60,
        )
        .stdout.decode("ascii")
        .strip()
    )


def test_inherited_git_env_cannot_redirect_the_adapter(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other-repo"
    other.mkdir()
    _git(other, "init", "-q")
    (other / "other.txt").write_text("other\n", encoding="utf-8")
    _commit_all(other, "a different repository")
    assert _rev_parse_head(other) != _rev_parse_head(repo)
    # A git hook (or any wrapper) exports these for its children.
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.bare'='true'")
    records = GitSourceAdapter(repo).collect()
    head = next(r for r in records if r.kind == "git_head")
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    monkeypatch.delenv("GIT_INDEX_FILE")
    monkeypatch.delenv("GIT_CONFIG_PARAMETERS")
    assert head.payload["commit"] == _rev_parse_head(repo)


def _object_store(git_dir: Path) -> dict[str, int]:
    objects = git_dir / "objects"
    return {
        str(path.relative_to(objects)): path.stat().st_size
        for path in objects.rglob("*")
        if path.is_file()
    }


def test_partial_clone_is_never_lazily_fetched(tmp_path: Path, repo: Path) -> None:
    # An inexact rename (moved and edited) makes `log -M` compare blob
    # contents, which a blobless clone does not have locally.
    body = "".join(f"line {n}\n" for n in range(40))
    (repo / "src" / "big.py").write_text(body, encoding="utf-8")
    _commit_all(repo, "add big")
    _git(repo, "mv", "src/big.py", "src/moved.py")
    (repo / "src" / "moved.py").write_text(body + "edited\n", encoding="utf-8")
    _commit_all(repo, "move and edit big")
    _git(repo, "config", "uploadpack.allowFilter", "true")
    clone = tmp_path / "blobless"
    subprocess.run(
        ["git", "clone", "-q", "--filter=blob:none", repo.as_uri(), str(clone)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    before = _object_store(clone / ".git")
    records = GitSourceAdapter(clone).collect()
    # No promisor contact: the object store is byte-for-byte unchanged.
    assert _object_store(clone / ".git") == before
    head = next(r for r in records if r.kind == "git_head")
    assert head.payload["commit"] == _rev_parse_head(repo)
    assert head.payload["window_commits"] == 6
    # Rename detection was skipped, so the evidence is reported as partial.
    assert head.payload["truncated"] is True
