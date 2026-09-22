"""Focused tests for the cross-platform CI helper scripts (WP5).

These exercise ``scripts/check_repo_clean.py`` and
``scripts/write_sha256sums.py`` directly so the CI cleanliness and checksum
gates are reviewable and correct on every platform without a full build.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def clean() -> Any:
    return _load("check_repo_clean", "check_repo_clean.py")


@pytest.fixture(scope="module")
def sums() -> Any:
    return _load("write_sha256sums", "write_sha256sums.py")


# ---------------------------------------------------------------------------
# Repository cleanliness (cross-platform, no shell)
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git_dir = tmp_path / "repo"
    git_dir.mkdir()
    _git("init", "-q", cwd=git_dir)
    return git_dir


def test_clean_repo_returns_zero(clean, repo: Path) -> None:
    (repo / "tracked.txt").write_text("hello\n", encoding="utf-8")
    _git("add", "tracked.txt", cwd=repo)
    _git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "init", cwd=repo)
    assert clean.check_clean(repo) == 0


def test_dirty_repo_returns_one(clean, repo: Path) -> None:
    (repo / "untracked.txt").write_text("x\n", encoding="utf-8")
    assert clean.check_clean(repo) == 1


def test_git_failure_returns_two(clean, tmp_path: Path) -> None:
    assert clean.check_clean(tmp_path / "does-not-exist") == 2


# ---------------------------------------------------------------------------
# Deterministic SHA256SUMS
# ---------------------------------------------------------------------------


def test_write_sha256sums_is_deterministic(sums, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "a.whl").write_bytes(b"aaa")
    (dist / "b.whl").write_bytes(b"bbb")
    (dist / "c.txt").write_bytes(b"ccc")
    out = sums.write_sha256sums(dist, out_path=tmp_path / "SHA256SUMS")
    assert out.name == "SHA256SUMS"
    content = out.read_text(encoding="utf-8")
    assert content.endswith("\n")
    # sorted by filename, one digest per regular file; sums file lives outside
    assert content == (
        f"{hashlib.sha256(b'aaa').hexdigest()}  a.whl\n"
        f"{hashlib.sha256(b'bbb').hexdigest()}  b.whl\n"
        f"{hashlib.sha256(b'ccc').hexdigest()}  c.txt\n"
    )
    # the sums file is not inside the hashed directory
    assert not (dist / "SHA256SUMS").exists()


def test_write_sha256sums_is_repeatable(sums, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "a").write_bytes(b"x")
    (dist / "b").write_bytes(b"y")
    out = tmp_path / "SHA256SUMS"
    first = sums.write_sha256sums(dist, out_path=out).read_text(encoding="utf-8")
    second = sums.write_sha256sums(dist, out_path=out).read_text(encoding="utf-8")
    assert first == second


def test_write_sha256sums_external_output_path_creates_parent(sums, tmp_path: Path) -> None:
    # --out is an explicit path outside the hashed directory; its parent is
    # created. This mirrors `write_sha256sums.py dist --out .ci/SHA256SUMS`.
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "artifact.whl").write_bytes(b"bytes")
    external = tmp_path / ".ci" / "nested" / "SHA256SUMS"
    out = sums.write_sha256sums(dist, out_path=external)
    assert out == external
    assert external.is_file()
    assert not (dist / "SHA256SUMS").exists()
    assert not (dist / ".ci").exists()
    expected = f"{hashlib.sha256(b'bytes').hexdigest()}  artifact.whl\n"
    assert external.read_text(encoding="utf-8") == expected


# ---------------------------------------------------------------------------
# Release workflow: checksums are enforced, not only produced
# ---------------------------------------------------------------------------

_RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
_SHA_PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _release_jobs() -> dict[str, Any]:
    workflow = yaml.safe_load(_RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]


def _step_index(steps: list[dict[str, Any]], predicate: Any) -> int:
    for index, step in enumerate(steps):
        if predicate(step):
            return index
    raise AssertionError("expected workflow step not found")


@pytest.mark.parametrize(
    ("job", "is_release_step"),
    (
        ("publish", lambda step: "gh-action-pypi-publish" in step.get("uses", "")),
        ("github-release", lambda step: "gh release create" in step.get("run", "")),
    ),
    ids=("publish", "github-release"),
)
def test_release_verifies_sha256sums_before_publishing(job: str, is_release_step: Any) -> None:
    steps = _release_jobs()[job]["steps"]
    download = _step_index(
        steps,
        lambda step: (
            "actions/download-artifact" in step.get("uses", "")
            and step.get("with", {}).get("name") == "release-checksums"
        ),
    )
    verify = _step_index(
        steps,
        lambda step: (
            "sha256sum" in step.get("run", "")
            and "--strict" in step.get("run", "")
            and " -c " in step.get("run", "")
        ),
    )
    release = _step_index(steps, is_release_step)
    assert download < verify < release


def test_release_actions_stay_sha_pinned_and_permissions_unchanged() -> None:
    jobs = _release_jobs()
    for job in jobs.values():
        for step in job["steps"]:
            if "uses" in step:
                assert _SHA_PINNED.match(step["uses"]), step["uses"]
    assert jobs["publish"]["permissions"] == {"contents": "read", "id-token": "write"}
    assert jobs["github-release"]["permissions"] == {"contents": "write"}
    assert "permissions" not in jobs["build"]
