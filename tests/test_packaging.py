"""Packaging-contract tests for Beacon's distribution metadata.

These inspect ``pyproject.toml`` and the executable package with the standard
library only (``tomllib``/``pathlib``), so they run without installing the
package or the framework. They assert semantics — that a given metadata field
is present and has the expected shape/value — rather than snapshotting the
whole file as prose.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest

from beacon import __version__
from beacon.core.loader import load_beacon_manifest
from beacon.core.schema import BeaconSource

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
PACKAGE_ROOT = REPO_ROOT / "src" / "beacon"

RUNTIME_ENV_VARS = {
    "BEACON_MANIFEST_PATH",
    "BEACON_DOCS_ROOT",
    "BEACON_VALIDATE_ON_LOAD",
    "BEACON_LOG_LEVEL",
    "BEACON_HOST",
    "BEACON_PORT",
    "BEACON_MAX_MANIFEST_BYTES",
    "BEACON_MAX_DOCUMENTS",
    "BEACON_MAX_DOCUMENT_BYTES",
    "BEACON_MAX_TOTAL_DOCUMENT_BYTES",
    "BEACON_MAX_CHUNKS",
    "BEACON_MAX_SNAPSHOT_BYTES",
}


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _package_python_sources() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


# ---------------------------------------------------------------------------
# Distribution identity
# ---------------------------------------------------------------------------


def test_distribution_name(pyproject: dict) -> None:
    assert pyproject["project"]["name"] == "archolith-beacon"


def test_console_script(pyproject: dict) -> None:
    assert pyproject["project"]["scripts"]["beacon"] == "beacon.main:main"


def test_python_requires_range(pyproject: dict) -> None:
    assert pyproject["project"]["requires-python"] == ">=3.12,<3.15"


# ---------------------------------------------------------------------------
# Single-source version
# ---------------------------------------------------------------------------


def test_version_is_dynamic(pyproject: dict) -> None:
    assert "version" in pyproject["project"]["dynamic"]


def test_dynamic_version_reads_beacon_version(pyproject: dict) -> None:
    dynamic = pyproject["tool"]["setuptools"]["dynamic"]["version"]
    assert dynamic == {"attr": "beacon.__version__"}


def test_no_static_version_field(pyproject: dict) -> None:
    assert "version" not in pyproject["project"]


def test_imported_version_matches_rc() -> None:
    assert __version__ == "0.2.0rc2"


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def test_framework_dependency_declared(pyproject: dict) -> None:
    assert "archolith-mcp-framework>=0.2,<0.3" in pyproject["project"]["dependencies"]


def test_fastmcp_dependency_declared(pyproject: dict) -> None:
    assert "fastmcp>=3.2.4,<4" in pyproject["project"]["dependencies"]


def test_http_dependencies_declared(pyproject: dict) -> None:
    dependencies = pyproject["project"]["dependencies"]
    assert "starlette>=1.0.1,<2" in dependencies
    assert "uvicorn>=0.35,<1" in dependencies


def test_legacy_framework_dependency_absent(pyproject: dict) -> None:
    assert "cth-mcp-framework" not in " ".join(pyproject["project"]["dependencies"])


def test_no_direct_url_dependencies(pyproject: dict) -> None:
    for dep in pyproject["project"]["dependencies"]:
        assert "@" not in dep


def test_runtime_dependencies_complete(pyproject: dict) -> None:
    names = {
        dep.split(">=")[0].split("<")[0].lower() for dep in pyproject["project"]["dependencies"]
    }
    assert {
        "archolith-mcp-framework",
        "fastmcp",
        "pyyaml",
        "python-dotenv",
        "starlette",
        "typer",
        "uvicorn",
    } <= names


# ---------------------------------------------------------------------------
# Metadata: URLs / readme / license
# ---------------------------------------------------------------------------


def test_readme_declared(pyproject: dict) -> None:
    assert pyproject["project"]["readme"] == "README.md"
    assert (REPO_ROOT / pyproject["project"]["readme"]).is_file()


def test_license_metadata(pyproject: dict) -> None:
    assert pyproject["project"]["license"] == "MIT"
    assert (REPO_ROOT / "LICENSE").is_file()


def test_pep639_license_does_not_duplicate_legacy_classifier(pyproject: dict) -> None:
    classifiers = pyproject["project"]["classifiers"]
    assert not any(value.startswith("License ::") for value in classifiers)


def test_repository_url(pyproject: dict) -> None:
    assert pyproject["project"]["urls"]["Repository"] == "https://github.com/Archolith/beacon"


def test_issues_url(pyproject: dict) -> None:
    assert pyproject["project"]["urls"]["Issues"] == "https://github.com/Archolith/beacon/issues"


def test_homepage_url(pyproject: dict) -> None:
    assert pyproject["project"]["urls"]["Homepage"] == "https://github.com/Archolith/beacon"


def test_urls_complete(pyproject: dict) -> None:
    urls = pyproject["project"]["urls"]
    assert {"Homepage", "Repository", "Issues"} <= set(urls)


def test_release_docs_match_current_rc() -> None:
    for relative in (
        ".agent/architecture.md",
        ".agent/for-review/BEACON-v0.2-UNAIDED-TRIAL-SCORECARD.md",
    ):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert __version__ in text, relative
        assert "0.2.0rc1" not in text, relative


def test_environment_variable_tables_match_runtime_contract() -> None:
    sections = {
        "README.md": "## Configuration",
        ".agent/architecture.md": "## Config / Environment Variables",
    }
    for relative, heading in sections.items():
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        section = text.split(heading, 1)[1].split("\n## ", 1)[0]
        documented = set(re.findall(r"^\| `(BEACON_[A-Z_]+)`", section, flags=re.MULTILINE))
        assert documented == RUNTIME_ENV_VARS, relative


def _assert_sources_resolve(sources: Sequence[BeaconSource], record_id: str) -> None:
    assert sources, f"{record_id} has no sources"
    for source in sources:
        relative = Path(source.path)
        target = REPO_ROOT / relative
        assert target.is_file(), f"{record_id}: missing source {relative}"
        line_count = len(target.read_text(encoding="utf-8").splitlines())
        assert source.line_start is not None, f"{record_id}: {relative} has no start line"
        assert source.line_end is not None, f"{record_id}: {relative} has no end line"
        assert 1 <= source.line_start <= source.line_end <= line_count, (
            f"{record_id}: invalid source range {relative}:"
            f"{source.line_start}-{source.line_end} (file has {line_count} lines)"
        )


def test_dogfood_concepts_and_guardrails_are_traceable() -> None:
    manifest = load_beacon_manifest(REPO_ROOT / "beacon.yaml")

    assert manifest.core_concepts
    for concept in manifest.core_concepts:
        _assert_sources_resolve(concept.sources, concept.id)
        assert concept.implementation_locations, f"{concept.id} has no implementation locations"
        for relative in concept.implementation_locations:
            assert (REPO_ROOT / relative).is_file(), (
                f"{concept.id}: missing implementation location {relative}"
            )

    assert manifest.guardrails
    for guardrail in manifest.guardrails:
        _assert_sources_resolve(guardrail.sources, guardrail.id)


# ---------------------------------------------------------------------------
# Source hygiene
# ---------------------------------------------------------------------------


def test_no_legacy_framework_import_in_source() -> None:
    offenders: list[str] = []
    for path in _package_python_sources():
        text = path.read_text(encoding="utf-8")
        if "cth_mcp_framework" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"legacy cth_mcp_framework import found in {offenders}"


def test_framework_import_present_in_executable_source() -> None:
    sources = {path.read_text(encoding="utf-8") for path in _package_python_sources()}
    assert any("archolith_mcp_framework" in text for text in sources)


# ---------------------------------------------------------------------------
# Dev extras (pip install -e .[dev])
# ---------------------------------------------------------------------------


def test_dev_extra_installs_tooling(pyproject: dict) -> None:
    dev = " ".join(pyproject["project"]["optional-dependencies"]["dev"])
    for pkg in ("pytest", "pytest-asyncio", "build", "twine", "jsonschema"):
        assert re.search(rf"(^|\s){re.escape(pkg)}", dev), f"{pkg} missing from dev extra"
