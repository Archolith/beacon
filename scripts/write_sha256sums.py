#!/usr/bin/env python3
"""Deterministic ``SHA256SUMS`` writer (cross-platform).

Writes one ``<sha256>  <filename>`` line per regular file in *directory* (not
recursive), sorted by filename for determinism, terminated by a single newline.
The sums file is written to an explicit *output path* that may live outside the
hashed directory, so the checksum is never mistaken for a distribution. Pure
Python so it behaves identically on Windows, macOS, and Linux.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def write_sha256sums(directory: Path, out_path: Path) -> Path:
    """Write a deterministic ``SHA256SUMS`` for *directory* to *out_path*."""
    files = sorted(path for path in directory.iterdir() if path.is_file())
    lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in files]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="write_sha256sums",
        description="Write a deterministic SHA256SUMS for a directory.",
    )
    parser.add_argument("directory", help="directory to hash")
    parser.add_argument(
        "--out",
        default="SHA256SUMS",
        help="output path (may be outside the directory; default: ./SHA256SUMS)",
    )
    args = parser.parse_args(argv)
    write_sha256sums(Path(args.directory).resolve(), Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
