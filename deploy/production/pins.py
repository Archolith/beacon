"""Validate Beacon production pins and emit them as shell assignments.

``pins.json`` is the only input a deploy trusts: the GHCR image by digest, the public host
name, and one demo bundle by release URL, commit and SHA-256. Every field is checked against
a strict pattern before ``deploy.sh`` uses it, and values are emitted shell-quoted.

    python3 pins.py pins.json      # prints KEY='value' lines, or exits 2 with a reason
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

PINS_VERSION = 1
IMAGE_RE = re.compile(
    r"ghcr\.io/archolith/beacon(?::[A-Za-z0-9][A-Za-z0-9._-]{0,127})?@sha256:[0-9a-f]{64}"
)
HOST_RE = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
URL_RE = re.compile(
    r"https://github\.com/Archolith/[A-Za-z0-9._-]+/releases/download/"
    r"(?P<tag>beacon-demo-[a-z0-9-]+-[0-9a-f]{12})/(?P<file>beacon-demo-[a-z0-9-]+-[0-9a-f]{12})\.tar\.gz"
)


class PinsError(ValueError):
    """The pins file is missing, malformed or inconsistent."""


def _field(data: dict[str, Any], key: str, pattern: re.Pattern[str]) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise PinsError(f"{key} is missing or invalid")
    return value


def validate(data: Any) -> dict[str, str]:
    """Return the validated pins as flat shell variables; raise ``PinsError`` otherwise."""
    if not isinstance(data, dict) or data.get("pins_version") != PINS_VERSION:
        raise PinsError(f"pins_version must be {PINS_VERSION}")
    unknown = set(data) - {"pins_version", "image", "public_host", "bundle"}
    if unknown:
        raise PinsError(f"unknown keys: {sorted(unknown)}")
    bundle = data.get("bundle")
    if not isinstance(bundle, dict) or set(bundle) != {"name", "commit", "url", "sha256"}:
        raise PinsError("bundle must have exactly name, commit, url, sha256")
    name = _field(bundle, "name", NAME_RE)
    commit = _field(bundle, "commit", COMMIT_RE)
    url = _field(bundle, "url", URL_RE)
    stem = f"beacon-demo-{name}-{commit[:12]}"
    match = URL_RE.fullmatch(url)
    assert match is not None
    if match["tag"] != stem or match["file"] != stem:
        raise PinsError(f"bundle url must name {stem} as both release tag and file")
    return {
        "PIN_IMAGE": _field(data, "image", IMAGE_RE),
        "PIN_PUBLIC_HOST": _field(data, "public_host", HOST_RE),
        "PIN_NAME": name,
        "PIN_COMMIT": commit,
        "PIN_URL": url,
        "PIN_SHA256": _field(bundle, "sha256", SHA256_RE),
        "PIN_STEM": stem,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: pins.py <pins.json>", file=sys.stderr)
        return 2
    try:
        pins = validate(json.loads(Path(argv[1]).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:  # PinsError and JSON errors are ValueErrors
        print(f"pins.py: {exc}", file=sys.stderr)
        return 2
    for key, value in pins.items():
        print(f"{key}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
