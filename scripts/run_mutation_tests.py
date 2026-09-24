#!/usr/bin/env python3
"""Run deterministic negative-control mutations against Beacon's test suite.

Each mutant changes one release-critical invariant in a temporary copy of the
``beacon`` package. The selected pytest test must then exit with code 1
(``TESTS_FAILED``). A passing test means the mutant survived and this runner
fails. Pytest collection or infrastructure errors also fail the runner rather
than being mistaken for a killed mutant.

The real checkout is never edited.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PACKAGE = REPO_ROOT / "src" / "beacon"
PYTEST_TESTS_FAILED = 1


@dataclass(frozen=True)
class Mutant:
    """One exact source mutation and the focused test expected to kill it."""

    name: str
    relative_path: str
    needle: str
    replacement: str
    test: str
    invariant: str


MUTANTS = (
    Mutant(
        name="known-token-detection-disabled",
        relative_path="core/security.py",
        needle="if _TOKEN_ALT_RE.search(line):",
        replacement="if False and _TOKEN_ALT_RE.search(line):",
        test="tests/test_security.py::test_detects_github_token",
        invariant="known provider tokens are blocked",
    ),
    Mutant(
        name="strict-warning-gate-disabled",
        relative_path="main.py",
        needle="ok = servable and not (strict_warnings and not publishable)",
        replacement="ok = servable",
        test="tests/test_cli.py::TestValidate::test_strict_warning_exits_one",
        invariant="strict validation rejects unresolved publication warnings",
    ),
    Mutant(
        name="manifest-export-collision-disabled",
        relative_path="main.py",
        needle="if out_resolved == context.manifest_path.resolve():",
        replacement="if False and out_resolved == context.manifest_path.resolve():",
        test="tests/test_cli.py::TestExport::test_manifest_output_collision_refused",
        invariant="export cannot overwrite the source manifest",
    ),
    Mutant(
        name="mcp-tools-not-registered",
        relative_path="mcp/server.py",
        needle="register_all_tools(mcp)",
        replacement="# mutation: omit Beacon tool registration",
        test="tests/test_mcp_contracts.py::test_public_tool_surface_is_exactly_the_seven_beacon_tools",
        invariant="the public MCP catalog contains exactly seven Beacon tools",
    ),
)


class MutationError(RuntimeError):
    """Raised when a mutant cannot be applied or verified correctly."""


def select_mutants(names: list[str]) -> tuple[Mutant, ...]:
    """Resolve requested mutant names, preserving the canonical order."""
    if not names:
        return MUTANTS
    requested = set(names)
    known = {mutant.name for mutant in MUTANTS}
    unknown = sorted(requested - known)
    if unknown:
        raise MutationError(f"unknown mutant(s): {', '.join(unknown)}")
    return tuple(mutant for mutant in MUTANTS if mutant.name in requested)


def apply_mutant(package_root: Path, mutant: Mutant) -> Path:
    """Apply *mutant* exactly once inside a temporary package copy."""
    target = package_root / Path(mutant.relative_path)
    source = target.read_text(encoding="utf-8")
    occurrences = source.count(mutant.needle)
    if occurrences != 1:
        raise MutationError(
            f"{mutant.name}: expected one mutation target in {mutant.relative_path}, "
            f"found {occurrences}"
        )
    target.write_text(source.replace(mutant.needle, mutant.replacement, 1), encoding="utf-8")
    return target


def run_mutant(mutant: Mutant) -> tuple[bool, str]:
    """Return whether the focused test killed *mutant* and concise evidence."""
    with tempfile.TemporaryDirectory(prefix=f"beacon-mutant-{mutant.name}-") as temp_name:
        temp_root = Path(temp_name)
        package_root = temp_root / "src" / "beacon"
        shutil.copytree(SOURCE_PACKAGE, package_root)
        apply_mutant(package_root, mutant)

        env = os.environ.copy()
        existing_path = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(temp_root / "src") + (
            os.pathsep + existing_path if existing_path else ""
        )
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-q",
                mutant.test,
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

    combined = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part)
    evidence = "\n".join(combined.splitlines()[-8:])
    return completed.returncode == PYTEST_TESTS_FAILED, evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Require focused Beacon tests to fail under deliberate mutations."
    )
    parser.add_argument("--only", action="append", default=[], help="run one named mutant")
    parser.add_argument("--list", action="store_true", help="list mutants without running them")
    args = parser.parse_args(argv)

    try:
        selected = select_mutants(args.only)
    except MutationError as exc:
        print(f"MUTATION ERROR: {exc}", file=sys.stderr)
        return 2

    if args.list:
        for mutant in selected:
            print(f"{mutant.name}: {mutant.invariant}")
        return 0

    survivors: list[str] = []
    infrastructure_failures: list[str] = []
    for mutant in selected:
        print(f"[mutate] {mutant.name}: {mutant.invariant}")
        try:
            killed, evidence = run_mutant(mutant)
        except (MutationError, OSError) as exc:
            infrastructure_failures.append(mutant.name)
            print(f"  ERROR: {exc}")
            continue
        if killed:
            print("  KILLED: focused test failed as required")
        else:
            survivors.append(mutant.name)
            print("  SURVIVED/INVALID: focused pytest did not exit with TESTS_FAILED")
            if evidence:
                print(evidence)

    if infrastructure_failures:
        print(
            f"MUTATION GATE FAILED: infrastructure errors for {', '.join(infrastructure_failures)}",
            file=sys.stderr,
        )
        return 2
    if survivors:
        print(f"MUTATION GATE FAILED: surviving mutants: {', '.join(survivors)}", file=sys.stderr)
        return 1
    print(f"MUTATION GATE PASSED: {len(selected)} of {len(selected)} mutants killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
