#!/usr/bin/env python3
"""Cross-platform repository-cleanliness check for CI.

Runs ``git status --porcelain`` from *root* (or the current directory) and
exits nonzero when anything is dirty, with safe, non-secret output. It is pure
Python so it behaves identically under PowerShell (Windows), bash, and zsh. Only
paths already ignored by ``.gitignore`` are excluded (via git itself); no
arbitrary output is silently allowed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def check_clean(root: Path) -> int:
    """Return 0 when *root* is a clean repository, 1 when dirty, 2 on error."""
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"git status --porcelain failed: {proc.stderr.strip()}", file=sys.stderr)
        return 2
    dirty = [line for line in proc.stdout.splitlines() if line.strip()]
    if dirty:
        print("Repository is not clean:", file=sys.stderr)
        for line in dirty:
            print(f"  {line}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_repo_clean",
        description="Exit nonzero if the repository has uncommitted or untracked changes.",
    )
    parser.add_argument("root", nargs="?", default=".", help="repository path (default: .)")
    args = parser.parse_args(argv)
    return check_clean(Path(args.root).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
