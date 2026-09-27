"""Focused tests for ``scripts/build_demo_bundle.py``.

The full build + serve path (beacon build/validate/export, tarball, serve-http smoke)
runs in CI's ``demo-image`` job against this repository; these tests pin the gates
and the git checkout properties the served freshness depends on.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "build_demo_bundle.py"
_IDENTITY = (
    "-c",
    "user.name=t",
    "-c",
    "user.email=t@example.invalid",
    "-c",
    "commit.gpgsign=false",
)


@pytest.fixture(scope="module")
def bundle() -> Any:
    spec = importlib.util.spec_from_file_location("build_demo_bundle", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *_IDENTITY, *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return done.stdout.strip()


@pytest.mark.parametrize("commit", ["abc", "A" * 40, "g" * 40, "a" * 39, "a" * 64])
def test_commit_must_be_full_lowercase_sha1(bundle: Any, commit: str) -> None:
    with pytest.raises(bundle.BundleError):
        bundle.validate_commit(commit)
    assert bundle.validate_commit("a" * 40) == "a" * 40


@pytest.mark.parametrize("name", ["", "Menhir", "a/b", "-x", "a" * 64, "a b"])
def test_name_must_be_a_slug(bundle: Any, name: str) -> None:
    with pytest.raises(bundle.BundleError):
        bundle.validate_name(name)


def test_bundle_name_uses_commit_prefix(bundle: Any) -> None:
    assert (
        bundle.bundle_name("menhir", "0123456789ab" + "c" * 28) == "beacon-demo-menhir-0123456789ab"
    )


def test_sparse_patterns_are_anchored_sorted_and_deduplicated(bundle: Any) -> None:
    assert bundle.sparse_patterns(["docs/b.md", "README.md", "docs/b.md"]) == [
        "/README.md",
        "/docs/b.md",
    ]


@pytest.mark.parametrize(
    "path", ["", "/etc/passwd", "../x.md", "docs/../x.md", "docs/*.md", "!x", "#x", "a[1].md", " x"]
)
def test_sparse_patterns_refuse_unsafe_or_pattern_paths(bundle: Any, path: str) -> None:
    with pytest.raises(bundle.BundleError):
        bundle.sparse_patterns([path])


def test_tarball_refuses_symlinks(bundle: Any, tmp_path: Path) -> None:
    stage = tmp_path / "stage" / "b"
    stage.mkdir(parents=True)
    (stage / "real.md").write_text("x", encoding="utf-8")
    try:
        (stage / "link.md").symlink_to(stage / "real.md")
    except OSError:
        pytest.skip("symlinks are not available here")
    with pytest.raises(bundle.BundleError):
        bundle.write_tarball(stage, tmp_path / "out")


def test_tarball_normalizes_ownership_and_refuses_overwrite(bundle: Any, tmp_path: Path) -> None:
    stage = tmp_path / "stage" / "b"
    stage.mkdir(parents=True)
    (stage / "a.md").write_text("x", encoding="utf-8")
    tarball = bundle.write_tarball(stage, tmp_path / "out")
    with tarfile.open(tarball) as archive:
        members = archive.getmembers()
    assert {m.name for m in members} == {"b", "b/a.md"}
    assert all(m.uid == 0 and m.gid == 0 and not m.uname for m in members)
    with pytest.raises(bundle.BundleError):
        bundle.write_tarball(stage, tmp_path / "out")


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_sparse_clone_is_clean_pinned_and_holds_only_the_documents(
    bundle: Any, tmp_path: Path
) -> None:
    src = tmp_path / "src"
    (src / "docs").mkdir(parents=True)
    (src / "README.md").write_bytes(b"# readme\r\nwith crlf\r\n")
    (src / "docs" / "a.md").write_text("a\n", encoding="utf-8")
    (src / "secret-ish.txt").write_text("not a document\n", encoding="utf-8")
    _git(src, "init", "-q")
    _git(src, "config", "core.autocrlf", "false")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "one")
    first = _git(src, "rev-parse", "HEAD")
    (src / "docs" / "a.md").write_text("a2\n", encoding="utf-8")
    _git(src, "commit", "-q", "-am", "two")

    full = tmp_path / "full"
    bundle.fetch_commit(str(src), first, full)
    assert (full / "docs" / "a.md").read_text(encoding="utf-8") == "a\n"

    dest = tmp_path / "repo"
    bundle.sparse_clone(full, first, bundle.sparse_patterns(["README.md", "docs/a.md"]), dest)
    assert _git(dest, "rev-parse", "HEAD") == first
    assert not (dest / "secret-ish.txt").exists()
    # Byte-exact: no CRLF conversion, so the container sees the committed blob.
    assert (dest / "README.md").read_bytes() == b"# readme\r\nwith crlf\r\n"
    assert _git(dest, "status", "--porcelain", "--untracked-files=normal") == ""
    assert _git(dest, "remote") == ""

    # A copy with fresh stat data (as after tar extraction) still reads clean.
    copy = tmp_path / "copy"
    shutil.copytree(dest, copy)
    assert _git(copy, "status", "--porcelain", "--untracked-files=normal") == ""


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_fetch_commit_refuses_an_unknown_commit(bundle: Any, tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("x\n", encoding="utf-8")
    _git(src, "init", "-q")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "one")
    with pytest.raises(bundle.BundleError):
        bundle.fetch_commit(str(src), "0" * 40, tmp_path / "full")
