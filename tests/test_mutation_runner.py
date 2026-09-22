"""Contract tests for the deterministic mutation-test runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mutation_runner() -> Any:
    path = REPO_ROOT / "scripts" / "run_mutation_tests.py"
    spec = importlib.util.spec_from_file_location("run_mutation_tests", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mutant_names_and_targets_are_unique(mutation_runner) -> None:
    names = [mutant.name for mutant in mutation_runner.MUTANTS]
    targets = [(mutant.relative_path, mutant.needle) for mutant in mutation_runner.MUTANTS]
    assert len(names) == len(set(names))
    assert len(targets) == len(set(targets))


def test_every_mutant_matches_the_current_source_exactly_once(mutation_runner) -> None:
    for mutant in mutation_runner.MUTANTS:
        source = (mutation_runner.SOURCE_PACKAGE / mutant.relative_path).read_text(encoding="utf-8")
        assert source.count(mutant.needle) == 1, mutant.name


def test_select_mutants_preserves_canonical_order(mutation_runner) -> None:
    selected = mutation_runner.select_mutants(
        ["mcp-tools-not-registered", "known-token-detection-disabled"]
    )
    assert [mutant.name for mutant in selected] == [
        "known-token-detection-disabled",
        "mcp-tools-not-registered",
    ]


def test_unknown_mutant_is_an_error(mutation_runner) -> None:
    with pytest.raises(mutation_runner.MutationError, match="unknown mutant"):
        mutation_runner.select_mutants(["not-a-real-mutant"])


def test_apply_mutant_never_edits_the_checkout(mutation_runner, tmp_path: Path) -> None:
    mutant = mutation_runner.MUTANTS[0]
    package_root = tmp_path / "beacon"
    target = package_root / mutant.relative_path
    target.parent.mkdir(parents=True)
    target.write_text(f"before\n{mutant.needle}\nafter\n", encoding="utf-8")
    checkout_before = (mutation_runner.SOURCE_PACKAGE / mutant.relative_path).read_bytes()

    mutation_runner.apply_mutant(package_root, mutant)

    assert mutant.replacement in target.read_text(encoding="utf-8")
    assert (mutation_runner.SOURCE_PACKAGE / mutant.relative_path).read_bytes() == checkout_before
