"""Build a Beacon demo bundle for one project at one pinned commit.

The bundle is what a public demo container serves (see ``Dockerfile`` and
``docs/deployment.md``)::

    beacon-demo-<name>-<commit12>/
        bundle.json              what was built, from which commit
        beacon.generated.yaml    the manifest ``beacon build`` produced
        beacon.snapshot.json     ``beacon export`` of that manifest (reference copy)
        repo/                    sparse, shallow checkout of the pinned commit holding
                                 only the manifest's documents, plus its ``.git``

``repo/`` keeps its ``.git`` so ``serve-http``'s startup observation reports the
pinned commit and ``dirty: false`` in discovery freshness, with no Beacon-side
special case. Sparse checkout keeps every other file out of the bundle without
making the checkout look dirty.

Steps: fetch the commit, ``beacon build``, ``beacon validate --strict-warnings``,
``beacon export`` (never with ``--allow-sensitive``), assemble, tar, then extract the
tarball into a fresh directory and smoke-test ``beacon serve-http`` from it: discovery,
freshness commit, a search, and the MCP tool list on ``/mcp``.

Usage::

    python scripts/build_demo_bundle.py --source https://github.com/Archolith/beacon \\
        --commit <40-hex sha> --name beacon --out-dir dist/demo
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import queue
import re
import shutil
import subprocess  # nosec B404 - fixed git and beacon commands, no shell
import sys
import tarfile
import tempfile
import threading
from pathlib import Path
from typing import Any

BUNDLE_VERSION = 1
MANIFEST_NAME = "beacon.generated.yaml"
SNAPSHOT_NAME = "beacon.snapshot.json"
EXPECTED_MCP_TOOLS = 7

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# Sparse-checkout (no-cone) patterns are gitignore syntax; refuse paths that would be
# read as pattern syntax rather than escaping them.
_UNSAFE_PATTERN_CHARS = set("*?[]!#\\")
_READY_RE = re.compile(r"Beacon HTTP ready url=(http://127\.0\.0\.1:\d+)")
# Byte-exact checkouts on every host: CRLF conversion on Windows would make the
# bundle's files differ from the committed blobs and read as dirty in the container.
_GIT_CONFIG = ("-c", "core.autocrlf=false", "-c", "core.eol=lf")


class BundleError(RuntimeError):
    """A gate failed; the message says which."""


def validate_commit(commit: str) -> str:
    """Return *commit* if it is a full 40-hex SHA-1, else raise."""
    if not _COMMIT_RE.match(commit):
        raise BundleError("--commit must be a full 40-character lowercase hex SHA")
    return commit


def validate_name(name: str) -> str:
    """Return *name* if it is a short lowercase slug, else raise."""
    if not _NAME_RE.match(name):
        raise BundleError("--name must be a lowercase slug: [a-z0-9-], at most 63 characters")
    return name


def bundle_name(name: str, commit: str) -> str:
    """Top-level directory and tarball stem for one bundle."""
    return f"beacon-demo-{name}-{commit[:12]}"


def sparse_patterns(paths: list[str]) -> list[str]:
    """Anchored no-cone sparse-checkout patterns for exactly *paths*."""
    patterns = []
    for path in sorted(set(paths)):
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise BundleError(f"document path is not a safe relative path: {path!r}")
        if _UNSAFE_PATTERN_CHARS & set(path) or path != path.strip():
            raise BundleError(f"document path cannot be expressed as a sparse pattern: {path!r}")
        patterns.append("/" + path)
    return patterns


def _run(args: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(  # nosec B603
        args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout).strip().splitlines()[-5:]
        raise BundleError(
            f"command failed ({completed.returncode}): {args[:4]}...\n" + "\n".join(tail)
        )
    return completed.stdout


def _git(*args: str, cwd: Path | None = None) -> str:
    return _run(["git", *_GIT_CONFIG, *args], cwd=cwd)


def _source_url(source: str) -> str:
    """A fetchable URL for *source*: remote URLs pass through, local paths become file://."""
    if re.match(r"^[a-z][a-z0-9+.-]*://", source):
        return source
    return Path(source).resolve().as_uri()


def fetch_commit(source: str, commit: str, dest: Path) -> None:
    """Shallow-fetch exactly *commit* from *source* into a new checkout at *dest*."""
    dest.mkdir(parents=True)
    _git("init", "-q", cwd=dest)
    _git("config", "core.autocrlf", "false", cwd=dest)
    _git("fetch", "-q", "--depth", "1", _source_url(source), commit, cwd=dest)
    _git("checkout", "-q", "--detach", "FETCH_HEAD", cwd=dest)
    head = _git("rev-parse", "HEAD", cwd=dest).strip()
    if head != commit:
        raise BundleError(f"fetched HEAD {head} does not match --commit {commit}")


def sparse_clone(full: Path, commit: str, patterns: list[str], dest: Path) -> None:
    """Shallow, sparse clone of *full* at *commit* holding only *patterns*; no remote."""
    # --filter=blob:none: only the checked-out documents' blobs land in the bundle's .git.
    _git(
        "clone",
        "-q",
        "--no-checkout",
        "--depth",
        "1",
        "--filter=blob:none",
        "--upload-pack=git -c uploadpack.allowFilter=true upload-pack",
        full.resolve().as_uri(),
        str(dest),
    )
    _git("config", "core.autocrlf", "false", cwd=dest)
    completed = subprocess.run(  # nosec B603
        ["git", *_GIT_CONFIG, "sparse-checkout", "set", "--no-cone", "--stdin"],
        cwd=dest,
        input="\n".join(patterns) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        raise BundleError("sparse-checkout failed: " + completed.stderr.strip())
    _git("checkout", "-q", "--detach", commit, cwd=dest)
    _git("remote", "remove", "origin", cwd=dest)
    status = _git("status", "--porcelain", "--untracked-files=normal", cwd=dest)
    if status.strip():
        raise BundleError("bundle checkout is not clean:\n" + status)


def _beacon(*args: str, cwd: Path) -> str:
    return _run([sys.executable, "-m", "beacon", *args], cwd=cwd)


def build_manifest(full: Path) -> tuple[Path, Path, list[str]]:
    """Run build, strict validate and export in *full*; return manifest, snapshot, doc paths."""
    _beacon("build", "--repo", ".", "--out", MANIFEST_NAME, cwd=full)
    _beacon("validate", MANIFEST_NAME, "--strict-warnings", cwd=full)
    snapshot = full.parent / SNAPSHOT_NAME
    _beacon("export", MANIFEST_NAME, "--output", str(snapshot), cwd=full)
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    paths = [str(document["path"]) for document in data.get("documents", [])]
    if not paths:
        raise BundleError("exported snapshot has no documents")
    return full / MANIFEST_NAME, snapshot, paths


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    if info.issym() or info.islnk():
        raise BundleError(f"refusing to bundle a link: {info.name}")
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o755 if info.isdir() else 0o644
    return info


def write_tarball(stage: Path, out_dir: Path) -> Path:
    """Tar *stage* (one top-level directory) into ``<out_dir>/<stage.name>.tar.gz``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tarball = out_dir / f"{stage.name}.tar.gz"
    if tarball.exists():
        raise BundleError(f"output already exists: {tarball}")
    with tarfile.open(tarball, "w:gz") as archive:
        archive.add(stage, arcname=stage.name, filter=_tar_filter)
    return tarball


# ---------------------------------------------------------------------------
# Smoke test: serve the extracted bundle the way the container does
# ---------------------------------------------------------------------------


def _read_ready_url(process: subprocess.Popen[str], timeout: float) -> str:
    lines: queue.Queue[str] = queue.Queue()

    def pump() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            lines.put(line)

    threading.Thread(target=pump, daemon=True).start()
    seen: list[str] = []
    while True:
        try:
            line = lines.get(timeout=timeout)
        except queue.Empty:
            raise BundleError("serve-http did not report ready:\n" + "".join(seen[-10:])) from None
        seen.append(line)
        match = _READY_RE.search(line)
        if match:
            return match.group(1)


async def _mcp_tool_names(url: str) -> list[str]:
    from fastmcp import Client

    async with Client(url) as client:
        return sorted(tool.name for tool in await client.list_tools())


def smoke_test(bundle_dir: Path, commit: str, timeout: float = 60.0) -> dict[str, Any]:
    """Serve *bundle_dir* with ``serve-http`` on a free loopback port and check it."""
    import httpx

    command = [
        sys.executable,
        "-m",
        "beacon",
        "serve-http",
        "--manifest",
        str(bundle_dir / MANIFEST_NAME),
        "--docs-root",
        str(bundle_dir / "repo"),
        "--port",
        "0",
    ]
    process = subprocess.Popen(  # nosec B603
        command,
        cwd=bundle_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        base = _read_ready_url(process, timeout)
        with httpx.Client(base_url=base, timeout=30.0) as http:
            discovery = http.get("/.well-known/archolith-beacon")
            if discovery.status_code != 200:
                raise BundleError(f"discovery returned {discovery.status_code}")
            payload = discovery.json()
            repository = payload.get("freshness", {}).get("repository", {})
            if repository != {"state": "observed", "commit": commit, "dirty": False}:
                raise BundleError(
                    f"discovery freshness is not the pinned clean commit: {repository}"
                )
            if payload.get("mcp", {}).get("url") != "/mcp":
                raise BundleError("discovery does not advertise /mcp")
            search = http.get("/v1/search", params={"q": "architecture"})
            if search.status_code != 200:
                raise BundleError(f"search returned {search.status_code}")
        tools = asyncio.run(_mcp_tool_names(base + "/mcp"))
        if len(tools) != EXPECTED_MCP_TOOLS:
            raise BundleError(f"expected {EXPECTED_MCP_TOOLS} MCP tools, got {tools}")
        return {
            "snapshot_sha256": payload.get("freshness", {}).get("snapshot_sha256"),
            "mcp_tools": tools,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_bundle(
    source: str, commit: str, name: str, out_dir: Path, *, smoke: bool = True
) -> dict[str, Any]:
    """Build, check and write one bundle; return the summary that ``bundle.json`` holds."""
    validate_commit(commit)
    validate_name(name)
    stem = bundle_name(name, commit)
    with tempfile.TemporaryDirectory(prefix="beacon-demo-") as tmp:
        work = Path(tmp)
        full = work / "full"
        fetch_commit(source, commit, full)
        manifest, snapshot, paths = build_manifest(full)

        stage = work / "stage" / stem
        stage.mkdir(parents=True)
        sparse_clone(full, commit, sparse_patterns(paths), stage / "repo")
        shutil.copyfile(manifest, stage / MANIFEST_NAME)
        shutil.copyfile(snapshot, stage / SNAPSHOT_NAME)

        from beacon import __version__

        summary: dict[str, Any] = {
            "bundle_version": BUNDLE_VERSION,
            "name": name,
            "commit": commit,
            "source": source if re.match(r"^https://", source) else None,
            "beacon_version": __version__,
            "documents": len(paths),
            "manifest_sha256": _sha256(stage / MANIFEST_NAME),
            "snapshot_file_sha256": _sha256(stage / SNAPSHOT_NAME),
        }
        (stage / "bundle.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        tarball = write_tarball(stage, out_dir)
        summary["tarball"] = str(tarball)
        summary["tarball_sha256"] = _sha256(tarball)

        if smoke:
            extracted = work / "extracted"
            extracted.mkdir()
            with tarfile.open(tarball, "r:gz") as archive:
                archive.extractall(extracted, filter="data")
            summary["smoke"] = smoke_test(extracted / stem, commit)
            if summary["smoke"]["snapshot_sha256"] != summary["snapshot_file_sha256"]:
                raise BundleError("served snapshot differs from the exported snapshot")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", required=True, help="Git URL or local repository path.")
    parser.add_argument("--commit", required=True, help="Full 40-hex commit SHA to pin.")
    parser.add_argument("--name", required=True, help="Project slug, e.g. menhir.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Where the tarball goes.")
    parser.add_argument(
        "--no-smoke", action="store_true", help="Skip the serve-http smoke test (not for uploads)."
    )
    args = parser.parse_args(argv)
    try:
        summary = build_bundle(
            args.source, args.commit, args.name, args.out_dir, smoke=not args.no_smoke
        )
    except BundleError as exc:
        print(f"build-demo-bundle: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
