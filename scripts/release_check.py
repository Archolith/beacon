#!/usr/bin/env python3
"""Cross-platform installed-wheel release-check journey for Beacon v0.2 (WP5).

This script proves the product works from an *installed* distribution rather
than an editable checkout. It uses the standard library plus lazy ``yaml`` for
the review edit and ``jsonschema`` for published HTTP contract validation, so
it runs identically on Windows, macOS, and Linux with no bash-only logic.

Two input modes:

* **Wheel mode (CI):** pass ``--framework-wheel`` and ``--beacon-wheel``. The
  script creates a fresh virtual environment, installs the local framework
  wheel first, then the Beacon wheel, and runs every step against the installed
  ``beacon``. Installation may hit the package index for dependencies; the
  runtime steps afterwards are fully offline.
* **Executable mode:** pass ``--beacon-exe`` (or let it default to the current
  interpreter's ``python -m beacon``) to run the journey against an already
  installed Beacon.

``--dry-run`` prints the exact ordered plan (commands, working directories,
environment, and expected assertions) and performs no subprocess, build, install,
or network action -- it only creates a temporary scratch directory. This makes
the infrastructure reviewable without building.

The journey exercises: version/help; ``init`` of a fresh minimal repository;
the init JSON report; a deterministic explicit review edit into a clean
manifest; strict JSON validation; task-aware JSON inspect covering all seven
tools; two embedded exports with identical bytes/SHA256; a metadata-only export
without chunk text; a real loopback HTTP process proving discovery/health/snapshot/alias/ETag and
error behavior; an explicit ``serve``/stdio MCP connection enumerating and calling exactly seven
tools; and a socket-deny guard proving no runtime step attempts outbound network. It uses temporary
directories and leaves the checkout clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The exact seven MCP tools Beacon registers.
BEACON_TOOLS = (
    "beacon_project_overview",
    "beacon_agent_onboarding",
    "beacon_search",
    "beacon_explain_concept",
    "beacon_guardrails",
    "beacon_catalog",
    "beacon_read",
)

#: Default task hint used for task-aware inspect.
DEFAULT_TASK_HINT = "review the release-check journey implementation"

#: Purpose sentence written by the deterministic review edit.
REVIEW_PURPOSE = "A maintainer-authored purpose for the release-check fixture."
#: Concept entry written by the deterministic review edit.
REVIEW_CONCEPTS = [
    {
        "id": "release_contract",
        "name": "Release Contract",
        "definition": "The installed product journey Beacon must preserve.",
        "why_it_exists": "Keep release evidence reproducible and source-cited.",
        "status": "current",
        "related_concepts": [],
        "implementation_locations": ["README.md"],
        "sources": [
            {
                "type": "doc",
                "title": "Fixture README",
                "path": "README.md",
                "line_start": 1,
                "line_end": 1,
                "status": "current",
            }
        ],
    }
]
#: Guardrail entry written by the deterministic review edit.
REVIEW_GUARDRAILS = [
    {
        "id": "no_documented_assumptions",
        "severity": "high",
        "rule": "Do not introduce undocumented assumptions in this fixture.",
        "scope": "release_process",
        "applies_to": ["README.md"],
        "sources": [
            {
                "type": "doc",
                "title": "Fixture README",
                "path": "README.md",
                "line_start": 1,
                "line_end": 1,
                "status": "current",
            }
        ],
    }
]

_SOCKET_GUARD_SITECUSTOMIZE = """\
import os
import socket
import ipaddress
from pathlib import Path

_original_create_connection = socket.create_connection
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex

def _deny(*args, **kwargs):
    Path(os.environ["BEACON_SOCKET_GUARD_MARKER"]).write_text("blocked", encoding="utf-8")
    raise RuntimeError("outbound network disabled by Beacon release check")

def _is_loopback(address):
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

def _guard_create_connection(address, *args, **kwargs):
    if _is_loopback(address):
        return _original_create_connection(address, *args, **kwargs)
    return _deny(address, *args, **kwargs)

def _guard_connect(sock, address):
    if _is_loopback(address):
        return _original_connect(sock, address)
    return _deny(sock, address)

def _guard_connect_ex(sock, address):
    if _is_loopback(address):
        return _original_connect_ex(sock, address)
    return _deny(sock, address)

socket.create_connection = _guard_create_connection
socket.socket.connect = _guard_connect
socket.socket.connect_ex = _guard_connect_ex
"""


class JourneyError(Exception):
    """Raised when a journey step fails with actionable, non-secret detail."""


@dataclass(frozen=True)
class Step:
    """One journey step: a subprocess or an in-process action plus a checker."""

    name: str
    description: str
    argv: tuple[str, ...] | None = None
    func: Callable[[], None] | None = None
    cwd: Path | None = None
    env: dict[str, str] | None = None
    expect_exit: int = 0
    checker: Callable[[Any], None] | None = None

    def __post_init__(self) -> None:
        if (self.argv is None) == (self.func is None):
            raise ValueError(f"step {self.name!r} must define exactly one of argv/func")


@dataclass
class Plan:
    """The ordered journey plan, with temp roots created by the runner."""

    steps: list[Step] = field(default_factory=list)

    def extend(self, steps: list[Step]) -> None:
        self.steps.extend(steps)


# ---------------------------------------------------------------------------
# Pure planning (no subprocess / no I/O beyond path construction)
# ---------------------------------------------------------------------------


def build_plan(
    *,
    beacon_cmd: tuple[str, ...],
    manifest: Path,
    repo: Path,
    out_dir: Path,
    socket_guard_dir: Path,
    guard_marker: Path,
    inspect_task_hint: str = DEFAULT_TASK_HINT,
    serve_cmd: tuple[str, ...] | None = None,
    run_stdio_mcp: bool = True,
    intent: Path | None = None,
) -> Plan:
    """Build the ordered :class:`Plan` of steps for the release journey.

    Pure and deterministic for a given set of inputs, so it is unit-testable
    without building or executing the CLI.
    """
    plan = Plan()
    guard_env = socket_guard_env(socket_guard_dir, guard_marker)
    # init writes the beacon.yaml overlay (judgment only); build derives the rest
    # into *manifest* (beacon.generated.yaml), which every later step uses.
    intent_path = intent if intent is not None else repo / "beacon.yaml"

    plan.extend(
        [
            Step(
                name="version",
                description="print the installed Beacon version",
                argv=beacon_cmd + ("--version",),
                env=guard_env,
            ),
            Step(
                name="help",
                description="print Beacon help and exit successfully",
                argv=beacon_cmd + ("--help",),
                env=guard_env,
            ),
            Step(
                name="init",
                description="initialize a fresh minimal repository with a JSON report",
                argv=beacon_cmd
                + (
                    "init",
                    "--format",
                    "json",
                    "--report",
                    str(out_dir / "init-report.json"),
                    str(repo),
                ),
                cwd=repo,
                env=guard_env,
                checker=_check_init,
            ),
            Step(
                name="review_edit",
                description="fill the judgment fields init leaves empty in beacon.yaml",
                func=lambda: apply_review_edits(intent_path),
            ),
            Step(
                name="build",
                description="build beacon.generated.yaml from beacon.yaml and the project's files",
                argv=beacon_cmd + ("build", "--repo", str(repo), "--format", "json", "--force"),
                cwd=repo,
                env=guard_env,
                checker=_check_build,
            ),
            Step(
                name="validate_strict",
                description="strict JSON validation succeeds with zero errors",
                argv=beacon_cmd
                + ("validate", "--strict-warnings", "--format", "json", str(manifest)),
                cwd=repo,
                env=guard_env,
                checker=_check_validate,
            ),
            Step(
                name="inspect",
                description="task-aware JSON inspect covering all seven tools",
                argv=beacon_cmd
                + ("inspect", "--task-hint", inspect_task_hint, "--format", "json", str(manifest)),
                cwd=repo,
                env=guard_env,
                checker=_check_inspect,
            ),
            Step(
                name="export_1",
                description="first embedded export",
                argv=beacon_cmd
                + ("export", str(manifest), "--output", str(out_dir / "export-1.json")),
                cwd=repo,
                env=guard_env,
            ),
            Step(
                name="export_2",
                description="second embedded export",
                argv=beacon_cmd
                + ("export", str(manifest), "--output", str(out_dir / "export-2.json")),
                cwd=repo,
                env=guard_env,
            ),
            Step(
                name="export_compare",
                description="embedded exports are byte-identical with equal SHA256",
                func=lambda: compare_exports(out_dir / "export-1.json", out_dir / "export-2.json"),
            ),
            Step(
                name="export_metadata_only",
                description="metadata-only export omits chunk text",
                argv=beacon_cmd
                + (
                    "export",
                    "--metadata-only",
                    str(manifest),
                    "--output",
                    str(out_dir / "export-meta.json"),
                ),
                cwd=repo,
                env=guard_env,
                checker=_check_metadata_only,
            ),
            Step(
                name="http_snapshot",
                description=(
                    "real loopback HTTP discovery, identity/orientation/full snapshots, selective "
                    "status/concept/guardrail/chunk resources, health, alias, HEAD, ETag, and errors"
                ),
                func=lambda: probe_http_snapshot(
                    beacon_cmd,
                    manifest=manifest,
                    expected_snapshot=out_dir / "export-1.json",
                    expected_orientation=out_dir / "export-meta.json",
                    env=guard_env,
                ),
            ),
            Step(
                name="serve_or_stdio",
                description="explicit serve / real stdio MCP enumerating and calling exactly seven tools",
                func=lambda: serve_or_stdio(
                    serve_cmd or beacon_cmd,
                    manifest=manifest,
                    env=guard_env,
                    run_stdio_mcp=run_stdio_mcp,
                ),
            ),
            Step(
                name="socket_guard",
                description="no runtime step (including MCP/serve startup and tool calls) made an outbound network attempt",
                func=lambda: _check_socket_guard(guard_marker),
            ),
        ]
    )
    return plan


def socket_guard_env(
    guard_dir: Path, marker: Path, base_env: dict[str, str] | None = None
) -> dict[str, str]:
    """Return an environment with the socket-deny guard injected on PYTHONPATH."""
    env = dict(os.environ if base_env is None else base_env)
    env["BEACON_SOCKET_GUARD_MARKER"] = str(marker)
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(guard_dir) + (os.pathsep + current if current else "")
    return env


def apply_review_edits(manifest: Path) -> None:
    """Deterministically edit *manifest* into a strict-clean state (no guessing).

    The edits mirror exactly the review items ``init`` reports (unknown status,
    missing purpose, missing guardrails) and are written back with PyYAML so a
    subsequent strict validation passes. This is an explicit, documented review
    edit -- not a heuristic guess.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - yaml is a runtime dependency
        raise JourneyError("PyYAML is required to apply the review edit") from exc
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        raise JourneyError("review edit requires a project mapping in the manifest")
    project["status"] = "experimental"
    data["purpose"] = {"one_sentence": REVIEW_PURPOSE, "problem": "", "non_goals": []}
    data["core_concepts"] = REVIEW_CONCEPTS
    data["guardrails"] = REVIEW_GUARDRAILS
    text = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1_000_000,
    )
    manifest.write_text(text.rstrip("\n") + "\n", encoding="utf-8")


def compare_exports(first: Path, second: Path) -> None:
    """Assert two embedded exports are byte-identical with equal SHA256."""
    if not first.is_file() or not second.is_file():
        raise JourneyError("one or both export files are missing")
    a = first.read_bytes()
    b = second.read_bytes()
    if a != b:
        raise JourneyError("two embedded exports of the same manifest are not byte-identical")
    if hashlib.sha256(a).hexdigest() != hashlib.sha256(b).hexdigest():
        raise JourneyError("embedded export SHA256 digests differ")


def probe_http_snapshot(
    cmd: tuple[str, ...],
    *,
    manifest: Path,
    expected_snapshot: Path,
    expected_orientation: Path,
    env: dict[str, str],
) -> None:
    """Start the installed HTTP server and verify its real loopback contract."""
    proc = subprocess.Popen(
        list(cmd)
        + ["serve-http", "--manifest", str(manifest), "--host", "127.0.0.1", "--port", "0"],
        cwd=str(manifest.parent),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        startup = _readline_with_timeout(proc, timeout=15)
        match = re.search(
            r"url=(http://127\.0\.0\.1:\d+) .*snapshot_sha256=([0-9a-f]{64})", startup
        )
        if match is None:
            raise JourneyError("serve-http did not emit the bounded startup contract")
        base_url, reported_sha = match.groups()
        expected = expected_snapshot.read_bytes()
        expected_sha = hashlib.sha256(expected).hexdigest()
        orientation_expected = expected_orientation.read_bytes()
        orientation_sha = hashlib.sha256(orientation_expected).hexdigest()
        identity_payload = json.loads(orientation_expected)
        manifest_data = identity_payload["manifest"]["data"]
        identity_payload["manifest"]["data"] = {
            key: manifest_data[key]
            for key in ("project", "purpose", "audiences", "current_focus")
            if key in manifest_data
        }
        identity_payload["documents"] = []
        identity_expected = (
            json.dumps(identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        identity_sha = hashlib.sha256(identity_expected).hexdigest()
        if reported_sha != expected_sha:
            raise JourneyError("serve-http startup digest differs from the canonical export")

        descriptor_body, descriptor_headers = _http_request(
            base_url + "/.well-known/archolith-beacon"
        )
        descriptor = json.loads(descriptor_body)
        if descriptor.get("scope") != "loopback" or descriptor.get("authentication") != "none":
            raise JourneyError("HTTP discovery has the wrong scope or authentication mode")
        capabilities = descriptor.get("capabilities")
        # #26: a servable snapshot adds the decision resources and the query routes.
        if capabilities != {
            "chunks": True,
            "concepts": True,
            "decisions": True,
            "guardrails": True,
            "status": True,
            "mcp_http": False,
            "query": True,
            "question_submission": False,
            "snapshot": True,
        }:
            raise JourneyError("HTTP discovery capabilities differ from the descriptor 1.7 contract")
        if descriptor.get("snapshot", {}).get("sha256") != expected_sha:
            raise JourneyError("HTTP discovery snapshot digest differs from the canonical export")
        if descriptor.get("descriptor_version") != "1.7":
            raise JourneyError("HTTP discovery descriptor version is not 1.7")
        if descriptor.get("trust") != "direct_unverified":
            raise JourneyError("HTTP discovery does not label itself direct and unverified")
        representations = descriptor.get("representations", {})
        if representations.get("identity") != {
            "url": "/v1/snapshot/identity",
            "mode": "metadata_only",
            "sha256": identity_sha,
            "bytes": len(identity_expected),
            "schema_version": "1.0",
        }:
            raise JourneyError("HTTP discovery identity representation is wrong")
        if representations.get("orientation") != {
            "url": "/v1/snapshot/orientation",
            "mode": "metadata_only",
            "sha256": orientation_sha,
            "bytes": len(orientation_expected),
            "schema_version": "1.0",
        }:
            raise JourneyError("HTTP discovery orientation representation is wrong")
        if representations.get("full") != {
            "url": "/v1/snapshot",
            "mode": "embedded",
            "sha256": expected_sha,
            "bytes": len(expected),
            "schema_version": "1.0",
        }:
            raise JourneyError("HTTP discovery full representation is wrong")

        status_body, status_headers = _http_request(base_url + "/v1/status")
        status_sha = hashlib.sha256(status_body).hexdigest()
        status = json.loads(status_body)
        _validate_http_schema(status, schema_name="beacon-status-1.0.schema.json")
        if _guided(descriptor.get("resources", {}).get("status")) != {
            "url": "/v1/status",
            "version": "1.0",
            "sha256": status_sha,
            "bytes": len(status_body),
        }:
            raise JourneyError("HTTP discovery status resource is wrong")
        if status.get("snapshot", {}).get("sha256") != expected_sha:
            raise JourneyError("HTTP status does not identify the full snapshot")
        if (
            status.get("trust", {}).get("assertion") != "self_reported"
            or status.get("trust", {}).get("signed") is not False
        ):
            raise JourneyError("HTTP status overstates unsigned trust")
        observed = status.get("observed", {})
        if observed.get("mode") != "startup" or not observed.get("observed_at"):
            raise JourneyError("HTTP status omits its startup observation time")
        freshness = observed.get("freshness", {})
        if freshness.get("state") != "fresh" or freshness.get("stale") != 0:
            raise JourneyError("HTTP status source freshness is not clean at startup")
        if status_headers.get("x-beacon-status-sha256") != status_sha:
            raise JourneyError("HTTP status digest header is wrong")
        if status_headers.get("x-beacon-snapshot-sha256") != expected_sha:
            raise JourneyError("HTTP status lineage header is wrong")
        _assert_no_server_identity(status_headers)

        chunk_index_body, chunk_index_headers = _http_request(base_url + "/v1/chunks")
        chunk_index_sha = hashlib.sha256(chunk_index_body).hexdigest()
        chunk_index = json.loads(chunk_index_body)
        if _guided(descriptor.get("resources", {}).get("chunks")) != {
            "index_url": "/v1/chunks",
            "item_url_template": "/v1/chunks/{id}",
            "version": "1.0",
            "count": chunk_index.get("count"),
            "sha256": chunk_index_sha,
            "bytes": len(chunk_index_body),
        }:
            raise JourneyError("HTTP discovery chunk-index resource is wrong")
        if chunk_index.get("snapshot", {}).get("sha256") != expected_sha:
            raise JourneyError("HTTP chunk index does not identify the full snapshot")
        entries = [
            chunk
            for document in chunk_index.get("documents", [])
            for chunk in document.get("chunks", [])
        ]
        if not entries or chunk_index.get("count") != len(entries):
            raise JourneyError("HTTP chunk index is empty or has the wrong count")
        if chunk_index_headers.get("x-beacon-chunk-index-sha256") != chunk_index_sha:
            raise JourneyError("HTTP chunk-index digest header is wrong")
        _assert_no_server_identity(chunk_index_headers)

        chunk_entry = entries[0]
        chunk_url = chunk_index["item_url_template"].replace("{id}", chunk_entry["id"])
        chunk_body, chunk_headers = _http_request(base_url + chunk_url)
        if len(chunk_body) != chunk_entry.get("bytes"):
            raise JourneyError("HTTP chunk response byte budget is wrong")
        chunk_sha = hashlib.sha256(chunk_body).hexdigest()
        chunk = json.loads(chunk_body)
        if len(chunk.get("text", "").encode("utf-8")) != chunk_entry.get("text_bytes"):
            raise JourneyError("HTTP chunk text byte budget is wrong")
        if not chunk_entry.get("parent_role") or not chunk_entry.get("parent_status"):
            raise JourneyError("HTTP chunk index omits parent role or status")
        if chunk_headers.get("x-beacon-chunk-sha256") != chunk_sha:
            raise JourneyError("HTTP chunk digest header is wrong")
        _assert_no_server_identity(chunk_headers)

        knowledge_responses: list[tuple[str, dict[str, str], str, dict[str, str]]] = []
        for kind, entries_key, resource_key, index_digest_header, resource_digest_header in (
            (
                "concepts",
                "concepts",
                "concept",
                "x-beacon-concept-index-sha256",
                "x-beacon-concept-sha256",
            ),
            (
                "guardrails",
                "guardrails",
                "guardrail",
                "x-beacon-guardrail-index-sha256",
                "x-beacon-guardrail-sha256",
            ),
        ):
            index_body, index_headers = _http_request(base_url + f"/v1/{kind}")
            index_sha = hashlib.sha256(index_body).hexdigest()
            index = json.loads(index_body)
            _validate_http_schema(
                index,
                schema_name=f"beacon-{resource_key}-index-1.0.schema.json",
            )
            entries_for_kind = index.get(entries_key, [])
            if len(entries_for_kind) != 1 or index.get("count") != 1:
                raise JourneyError(f"HTTP {kind} index is empty or has the wrong count")
            if index.get("snapshot", {}).get("sha256") != expected_sha:
                raise JourneyError(f"HTTP {kind} index does not identify the full snapshot")
            if index_headers.get(index_digest_header) != index_sha:
                raise JourneyError(f"HTTP {kind} index digest header is wrong")
            advertised = _guided(descriptor.get("resources", {}).get(kind))
            if advertised != {
                "index_url": f"/v1/{kind}",
                "item_url_template": f"/v1/{kind}/{{id}}",
                "version": "1.0",
                "count": 1,
                "sha256": index_sha,
                "bytes": len(index_body),
            }:
                raise JourneyError(f"HTTP discovery {kind} resource is wrong")
            entry = entries_for_kind[0]
            resource_url = index["item_url_template"].replace("{id}", entry["resource_id"])
            resource_body, resource_headers = _http_request(base_url + resource_url)
            resource_sha = hashlib.sha256(resource_body).hexdigest()
            resource = json.loads(resource_body)
            _validate_http_schema(
                resource,
                schema_name=f"beacon-{resource_key}-resource-1.0.schema.json",
            )
            if len(resource_body) != entry.get("bytes") or resource_sha != entry.get("sha256"):
                raise JourneyError(f"HTTP {kind} resource byte budget or digest is wrong")
            if resource_headers.get(resource_digest_header) != resource_sha:
                raise JourneyError(f"HTTP {kind} resource digest header is wrong")
            if resource.get("snapshot_sha256") != expected_sha:
                raise JourneyError(f"HTTP {kind} resource lineage is wrong")
            if resource.get(resource_key, {}).get("id") != entry.get("id"):
                raise JourneyError(f"HTTP {kind} resource logical identity is wrong")
            _assert_no_server_identity(index_headers)
            _assert_no_server_identity(resource_headers)
            knowledge_responses.append((resource_url, resource_headers, kind, index_headers))
        _assert_no_server_identity(descriptor_headers)

        identity_body, identity_headers = _http_request(base_url + "/v1/snapshot/identity")
        if identity_body != identity_expected:
            raise JourneyError("HTTP identity bytes differ from the derived identity snapshot")
        if len(identity_body) >= len(orientation_expected):
            raise JourneyError("HTTP identity is not smaller than orientation")
        if identity_headers.get("x-beacon-snapshot-sha256") != identity_sha:
            raise JourneyError("HTTP identity digest header is wrong")
        if identity_headers.get("etag") != f'"{identity_sha}"':
            raise JourneyError("HTTP identity ETag is wrong")
        if identity_headers.get("link") != (
            '</v1/status>; rel="status"; title="project status", '
            '</v1/snapshot/orientation>; rel="alternate"; title="orientation snapshot"'
        ):
            raise JourneyError("HTTP identity does not link to status and orientation")
        _assert_no_server_identity(identity_headers)

        orientation_body, orientation_headers = _http_request(base_url + "/v1/snapshot/orientation")
        if orientation_body != orientation_expected:
            raise JourneyError("HTTP orientation bytes differ from the metadata-only export")
        if len(orientation_body) >= len(expected):
            raise JourneyError("HTTP orientation is not smaller than the full snapshot")
        if orientation_headers.get("x-beacon-snapshot-sha256") != orientation_sha:
            raise JourneyError("HTTP orientation digest header is wrong")
        if orientation_headers.get("etag") != f'"{orientation_sha}"':
            raise JourneyError("HTTP orientation ETag is wrong")
        if orientation_headers.get("cache-control") != "no-cache":
            raise JourneyError("HTTP orientation cache policy is wrong")
        if orientation_headers.get("link") != (
            '</v1/snapshot>; rel="alternate"; title="full snapshot"'
        ):
            raise JourneyError("HTTP orientation does not link to the full snapshot")
        _assert_no_server_identity(orientation_headers)

        snapshot_body, snapshot_headers = _http_request(base_url + "/v1/snapshot")
        alias_body, alias_headers = _http_request(base_url + "/beacon.json")
        if snapshot_body != expected or alias_body != expected:
            raise JourneyError("HTTP snapshot bytes differ from the canonical export")
        for headers in (snapshot_headers, alias_headers):
            if headers.get("x-beacon-snapshot-sha256") != expected_sha:
                raise JourneyError("HTTP snapshot digest header is wrong")
            if headers.get("etag") != f'"{expected_sha}"':
                raise JourneyError("HTTP snapshot ETag is wrong")
            if headers.get("cache-control") != "no-cache":
                raise JourneyError("HTTP snapshot cache policy is wrong")
            _assert_no_server_identity(headers)

        head_body, head_headers = _http_request(base_url + "/v1/snapshot", method="HEAD")
        if head_body or head_headers.get("etag") != snapshot_headers.get("etag"):
            raise JourneyError("HTTP HEAD response differs from the snapshot representation")
        _http_expect_status(
            base_url + "/v1/snapshot",
            304,
            headers={"If-None-Match": f'"{expected_sha}"'},
        )
        orientation_head_body, orientation_head_headers = _http_request(
            base_url + "/v1/snapshot/orientation", method="HEAD"
        )
        if orientation_head_body or orientation_head_headers.get("etag") != (
            orientation_headers.get("etag")
        ):
            raise JourneyError("HTTP orientation HEAD response differs from GET")
        _http_expect_status(
            base_url + "/v1/snapshot/orientation",
            304,
            headers={"If-None-Match": f'"{orientation_sha}"'},
        )
        identity_head_body, identity_head_headers = _http_request(
            base_url + "/v1/snapshot/identity", method="HEAD"
        )
        if identity_head_body or identity_head_headers.get("etag") != identity_headers.get("etag"):
            raise JourneyError("HTTP identity HEAD response differs from GET")
        _http_expect_status(
            base_url + "/v1/snapshot/identity",
            304,
            headers={"If-None-Match": f'"{identity_sha}"'},
        )
        status_head_body, status_head_headers = _http_request(
            base_url + "/v1/status", method="HEAD"
        )
        if status_head_body or status_head_headers.get("etag") != status_headers.get("etag"):
            raise JourneyError("HTTP status HEAD response differs from GET")
        _http_expect_status(
            base_url + "/v1/status",
            304,
            headers={"If-None-Match": status_headers["etag"]},
        )
        chunk_index_head_body, chunk_index_head_headers = _http_request(
            base_url + "/v1/chunks", method="HEAD"
        )
        if chunk_index_head_body or chunk_index_head_headers.get("etag") != (
            chunk_index_headers.get("etag")
        ):
            raise JourneyError("HTTP chunk-index HEAD response differs from GET")
        _http_expect_status(
            base_url + "/v1/chunks",
            304,
            headers={"If-None-Match": chunk_index_headers["etag"]},
        )
        chunk_head_body, chunk_head_headers = _http_request(base_url + chunk_url, method="HEAD")
        if chunk_head_body or chunk_head_headers.get("etag") != chunk_headers.get("etag"):
            raise JourneyError("HTTP chunk HEAD response differs from GET")
        _http_expect_status(
            base_url + chunk_url,
            304,
            headers={"If-None-Match": chunk_headers["etag"]},
        )
        for resource_url, resource_headers, kind, index_headers in knowledge_responses:
            index_head_body, index_head_headers = _http_request(
                base_url + f"/v1/{kind}", method="HEAD"
            )
            if index_head_body or index_head_headers.get("etag") != index_headers.get("etag"):
                raise JourneyError(f"HTTP {kind} index HEAD response differs from GET")
            _http_expect_status(
                base_url + f"/v1/{kind}",
                304,
                headers={"If-None-Match": index_headers["etag"]},
            )
            resource_head_body, resource_head_headers = _http_request(
                base_url + resource_url, method="HEAD"
            )
            if resource_head_body or resource_head_headers.get("etag") != resource_headers.get(
                "etag"
            ):
                raise JourneyError(f"HTTP {kind} resource HEAD response differs from GET")
            _http_expect_status(
                base_url + resource_url,
                304,
                headers={"If-None-Match": resource_headers["etag"]},
            )

        health_body, health_headers = _http_request(base_url + "/healthz")
        health = json.loads(health_body)
        if health.get("status") != "ready" or health.get("startup_mode") != "immutable_snapshot":
            raise JourneyError("HTTP health response is not ready in immutable snapshot mode")
        if health_headers.get("cache-control") != "no-store":
            raise JourneyError("HTTP health cache policy is wrong")
        _assert_no_server_identity(health_headers)
        _http_expect_status(base_url + "/missing?private=query", 404)
        _http_expect_status(base_url + "/v1/snapshot", 405, method="POST")
        _http_expect_status(base_url + "/v1/snapshot/orientation", 405, method="POST")
        _http_expect_status(base_url + "/v1/snapshot/identity", 405, method="POST")
        _http_expect_status(base_url + "/v1/status", 405, method="POST")
        _http_expect_status(base_url + "/v1/chunks", 405, method="POST")
        _http_expect_status(base_url + "/v1/chunks/not-a-real-id?private=query", 404)
        for kind in ("concepts", "guardrails"):
            _http_expect_status(base_url + f"/v1/{kind}", 405, method="POST")
            _http_expect_status(base_url + f"/v1/{kind}/not-a-real-id?private=query", 404)
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        raise JourneyError(f"loopback HTTP journey failed ({type(exc).__name__})") from exc
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if proc.stdout is not None:
            stdout = proc.stdout.read()
            if stdout:
                raise JourneyError("serve-http unexpectedly wrote to stdout")


def _readline_with_timeout(proc: subprocess.Popen[str], *, timeout: float) -> str:
    if proc.stderr is None:
        raise JourneyError("serve-http stderr pipe is unavailable")
    result: queue.Queue[str] = queue.Queue(maxsize=1)

    def read() -> None:
        result.put(proc.stderr.readline())

    threading.Thread(target=read, daemon=True).start()
    try:
        line = result.get(timeout=timeout)
    except queue.Empty as exc:
        raise JourneyError("serve-http did not become ready before the timeout") from exc
    if not line:
        raise JourneyError("serve-http exited before reporting readiness")
    return line.strip()


def _http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, method=method, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - fixed loopback URL
        return response.read(), {key.lower(): value for key, value in response.headers.items()}


def _http_expect_status(
    url: str,
    status: int,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> None:
    try:
        _http_request(url, method=method, headers=headers)
    except urllib.error.HTTPError as exc:
        if exc.code != status:
            raise JourneyError(f"HTTP status {exc.code} != expected {status}") from exc
        if status == 304 and exc.read():
            raise JourneyError("HTTP 304 unexpectedly contained a response body") from exc
        return
    raise JourneyError(f"HTTP request unexpectedly succeeded; expected status {status}")


def _assert_no_server_identity(headers: dict[str, str]) -> None:
    if "server" in headers or "date" in headers:
        raise JourneyError("HTTP response exposes a server-identifying header")


def _validate_http_schema(instance: dict[str, Any], *, schema_name: str) -> None:
    """Validate one installed HTTP response against its published source schema."""
    try:
        import jsonschema
    except ImportError as exc:
        raise JourneyError("jsonschema is required for HTTP contract validation") from exc
    schema_path = Path(__file__).resolve().parents[1] / "docs" / "schemas" / schema_name
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(instance, schema)
    except (OSError, ValueError, jsonschema.SchemaError, jsonschema.ValidationError) as exc:
        raise JourneyError(f"HTTP response failed published schema: {schema_name}") from exc


def serve_or_stdio(
    cmd: tuple[str, ...],
    *,
    manifest: Path,
    env: dict[str, str],
    run_stdio_mcp: bool,
) -> None:
    """Start the explicit serve / stdio server and verify exactly seven tools.

    The default installed-wheel journey *requires* the real FastMCP client:
    ``archolith-mcp-framework`` supplies it, so an unavailable MCP stack is a
    packaging failure, never a reason to fall back to a lighter check. Only an
    explicit ``--no-stdio-mcp`` (``run_stdio_mcp=False``) selects the lighter
    serve-start check. *env* carries the socket-deny guard so any outbound
    attempt fails.
    """
    env = dict(env)
    env["BEACON_MANIFEST_PATH"] = str(manifest)
    env["BEACON_DOCS_ROOT"] = str(manifest.parent)
    env.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")
    env.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")

    if run_stdio_mcp:
        _stdio_mcp_check(cmd, env)
    else:
        _serve_start_check(cmd, env)


def _serve_start_check(cmd: tuple[str, ...], env: dict[str, str]) -> None:
    """Spawn ``serve`` and require it to stay up and log a startup line."""
    proc = subprocess.Popen(
        list(cmd) + ["serve"],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        try:
            _, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            return  # stayed up until the timeout -- good
        if b"start" not in stderr.lower() and b"mcp" not in stderr.lower():
            raise JourneyError("beacon serve did not emit an expected startup log")
    finally:
        if proc.poll() is None:
            proc.kill()


def _python_module_shape(cmd: tuple[str, ...]) -> tuple[str, list[str]] | None:
    """Return ``(interpreter, args)`` when *cmd* is a ``python -m beacon`` shape.

    Any interpreter path is accepted (including a fresh venv Python), but only
    when the command is exactly ``(<python>, "-m", "beacon", ...)``.
    """
    if len(cmd) >= 3 and cmd[1] == "-m" and cmd[2] == "beacon":
        return cmd[0], list(cmd[1:])
    return None


def _stdio_mcp_check(cmd: tuple[str, ...], env: dict[str, str]) -> None:
    """Connect over real stdio and enumerate/call exactly the seven tools.

    This is the required installed-artifact check: it runs the *installed*
    interpreter named by *cmd* (a fresh venv Python in wheel mode), never the
    release-check process interpreter. An unavailable MCP client stack or a
    non-``python -m beacon`` command is a packaging failure and raises
    :class:`JourneyError` -- there is no lighter fallback here. Client/protocol
    runtime failures are normalized to a concise, non-secret
    :class:`JourneyError` so a real stdio failure surfaces as an actionable
    result instead of a full traceback.
    """
    try:
        import fastmcp  # noqa: F401
    except ImportError as exc:
        raise JourneyError(
            "the archolith-mcp-framework MCP client is not importable; the "
            "installed-wheel journey requires the real FastMCP stack"
        ) from exc

    shape = _python_module_shape(cmd)
    if shape is None:
        raise JourneyError("serve command must be '<python> -m beacon' to drive stdio MCP")
    interpreter, args = shape
    _run_stdio_client_normalized(interpreter, args, env)


def _run_stdio_client_normalized(interpreter: str, args: list[str], env: dict[str, str]) -> None:
    """Run the stdio MCP client, normalizing broad runtime failures."""
    try:
        _run_stdio_client(interpreter, args, env)
    except JourneyError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize client/protocol failures
        raise JourneyError(
            f"stdio MCP connection or tool call failed ({type(exc).__name__})"
        ) from exc


def _run_stdio_client(interpreter: str, args: list[str], env: dict[str, str]) -> None:
    """Connect and enumerate/call the seven tools over real stdio."""
    import asyncio

    import fastmcp
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(command=interpreter, args=args, env=env)

    async def _run() -> None:
        async with fastmcp.Client(transport, timeout=20) as client:
            names = sorted(tool.name for tool in await client.list_tools())
            if tuple(names) != tuple(sorted(BEACON_TOOLS)):
                raise JourneyError(f"expected exactly the seven tools, got: {', '.join(names)}")
            calls = {
                "beacon_project_overview": {},
                "beacon_agent_onboarding": {"task_hint": DEFAULT_TASK_HINT},
                "beacon_search": {"query": "manifest"},
                "beacon_explain_concept": {"concept": "beacon_manifest"},
                "beacon_guardrails": {"task_hint": DEFAULT_TASK_HINT},
                "beacon_catalog": {},
                "beacon_read": {"path": "README.md"},
            }
            for name, arguments in calls.items():
                result = await client.call_tool(name, arguments)
                if result.is_error:
                    raise JourneyError(f"tool call failed: {name}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Result checkers
# ---------------------------------------------------------------------------


def _check_init(completed: Any) -> None:
    _assert_exit(completed, 0, "init")
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JourneyError("init did not emit a JSON result") from exc
    envelope = _require_envelope(payload, "init")
    if envelope["command"] != "init":
        raise JourneyError(f"init envelope command={envelope['command']!r} != 'init'")
    if envelope["ok"] is not True:
        raise JourneyError("init envelope ok is not true")
    report = envelope["result"]
    if not isinstance(report, dict):
        raise JourneyError("init result is not an object")
    if report.get("written") is not True:
        raise JourneyError(f"init did not write the manifest: written={report.get('written')!r}")
    if not report.get("manifest_path"):
        raise JourneyError("init report is missing manifest_path")


def _check_build(completed: Any) -> None:
    _assert_exit(completed, 0, "build")
    payload = json.loads(completed.stdout.decode("utf-8"))
    _require_envelope(payload, "build")
    if payload.get("ok") is not True:
        raise JourneyError("build envelope ok is not true")


def _check_validate(completed: Any) -> None:
    _assert_exit(completed, 0, "validate --strict-warnings")
    payload = json.loads(completed.stdout.decode("utf-8"))
    _require_envelope(payload, "validate")
    if payload.get("ok") is not True:
        raise JourneyError("strict validation envelope ok is not true")


def _check_inspect(completed: Any) -> None:
    _assert_exit(completed, 0, "inspect")
    payload = json.loads(completed.stdout.decode("utf-8"))
    envelope = _require_envelope(payload, "inspect")
    result = envelope["result"]
    if not isinstance(result, dict):
        raise JourneyError("inspect result is not an object")
    missing = [name for name in BEACON_TOOLS if name not in result]
    if missing:
        raise JourneyError(f"inspect result is missing tool payloads: {', '.join(missing)}")


def _check_metadata_only(completed: Any) -> None:
    _assert_exit(completed, 0, "export --metadata-only")
    output = _output_path_from_args(completed)
    if not output.is_file():
        raise JourneyError("metadata-only export did not produce an output file")
    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("content_mode") != "metadata_only":
        raise JourneyError(
            f"export content_mode={payload.get('content_mode')!r} != 'metadata_only'"
        )
    for doc in payload.get("documents", []):
        for chunk in doc.get("chunks", []):
            if "text" in chunk:
                raise JourneyError("metadata-only export unexpectedly contains chunk text")


def _output_path_from_args(completed: Any) -> Path:
    argv = getattr(completed, "args", None) or ()
    for index, item in enumerate(argv):
        if item == "--output" and index + 1 < len(argv):
            return Path(argv[index + 1])
    raise JourneyError("could not determine the --output path from the export invocation")


def _check_socket_guard(marker: Path) -> None:
    if marker.exists():
        raise JourneyError("a runtime step attempted outbound network access")


def _require_envelope(payload: Any, command: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise JourneyError(f"{command} JSON output is not an object")
    if payload.get("schema") != "beacon.cli-result":
        raise JourneyError(f"{command} JSON output is not a beacon.cli-result envelope")
    return payload


def _assert_exit(completed: Any, expected: int, what: str) -> None:
    code = getattr(completed, "returncode", None)
    if code != expected:
        stderr = getattr(completed, "stderr", b"") or b""
        tail = stderr.decode("utf-8", errors="replace").strip().splitlines()[-1:] or []
        detail = tail[0] if tail else "no stderr"
        raise JourneyError(f"{what} exited {code!r}, expected {expected}: {detail}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_step(step: Step, *, dry_run: bool, printer: Callable[[str], None]) -> None:
    """Execute (or print, in dry-run) one :class:`Step`."""
    printer(f"[{step.name}] {step.description}")
    if dry_run:
        if step.argv:
            printer(f"    run: {' '.join(step.argv)}")
        if step.cwd:
            printer(f"    cwd: {step.cwd}")
        if step.env and step.env.get("BEACON_SOCKET_GUARD_MARKER"):
            printer(f"    env: socket-guard active -> {step.env['BEACON_SOCKET_GUARD_MARKER']}")
        if step.checker is not None:
            printer("    assert: output/artifact check")
        return
    if step.func is not None:
        step.func()
        return
    completed = subprocess.run(
        list(step.argv or ()),
        cwd=str(step.cwd) if step.cwd else None,
        env=step.env,
        capture_output=True,
    )
    if step.checker is not None:
        step.checker(completed)
    else:
        _assert_exit(completed, step.expect_exit, step.name)


def run_plan(plan: Plan, *, dry_run: bool = False) -> None:
    """Run (or print) every step, failing fast with actionable detail."""
    for step in plan.steps:
        try:
            run_step(step, dry_run=dry_run, printer=print)
        except JourneyError as exc:
            raise JourneyError(f"journey step {step.name!r} failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="release_check",
        description="Cross-platform installed-wheel release-check journey for Beacon.",
    )
    parser.add_argument("--beacon-exe", help="installed beacon console script path")
    parser.add_argument("--framework-wheel", help="local archolith-mcp-framework wheel")
    parser.add_argument("--beacon-wheel", help="local archolith-beacon wheel")
    parser.add_argument("--workdir", help="temporary work root (default: system temp)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary work root")
    parser.add_argument("--no-stdio-mcp", action="store_true", help="only light serve-start check")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the ordered plan with no subprocess/build/install/network "
        "(a temporary scratch directory is still created)",
    )
    return parser.parse_args(argv)


def _resolve_beacon_cmd(
    args: argparse.Namespace,
) -> tuple[tuple[str, ...], tuple[Path, Path] | None]:
    """Return (beacon_cmd, wheels) honouring wheel vs executable mode."""
    wheels = None
    if args.framework_wheel and args.beacon_wheel:
        wheels = (Path(args.framework_wheel), Path(args.beacon_wheel))
        return (sys.executable, "-m", "beacon"), wheels
    if args.framework_wheel or args.beacon_wheel:
        raise JourneyError("--framework-wheel and --beacon-wheel must be provided together")
    if args.beacon_exe:
        return (args.beacon_exe,), wheels
    return (sys.executable, "-m", "beacon"), wheels


def _install_steps(
    venv_dir: Path, framework_wheel: Path, beacon_wheel: Path
) -> tuple[tuple[str, ...], list[Step]]:
    """Create a venv and install framework then Beacon wheels."""
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    steps: list[Step] = [
        Step(
            name="create_venv",
            description="create a fresh virtual environment",
            argv=(sys.executable, "-m", "venv", str(venv_dir)),
        ),
        Step(
            name="install_framework_wheel",
            description="install the local framework wheel (first)",
            argv=(str(venv_python), "-m", "pip", "install", str(framework_wheel)),
        ),
        Step(
            name="install_beacon_wheel",
            description="install the local Beacon wheel",
            argv=(str(venv_python), "-m", "pip", "install", str(beacon_wheel)),
        ),
    ]
    return (str(venv_python), "-m", "beacon"), steps


def _setup_guard(work: Path, *, write_sitecustomize: bool) -> tuple[Path, Path, dict[str, str]]:
    guard_dir = work / "socket-guard"
    guard_dir.mkdir(parents=True, exist_ok=True)
    if write_sitecustomize:
        (guard_dir / "sitecustomize.py").write_text(_SOCKET_GUARD_SITECUSTOMIZE, encoding="utf-8")
    marker = work / "network-attempted"
    return guard_dir, marker, socket_guard_env(guard_dir, marker)


def _guided(resource: Any) -> Any:
    """A discovery resource without its ``use_when`` line, which must be a non-empty string.

    Descriptor 1.7 (#26) gives every resource family a one-line usage hint; the rest of
    the entry is still compared exactly.
    """
    if not isinstance(resource, dict):
        return resource
    hint = resource.get("use_when")
    if not isinstance(hint, str) or not hint.strip():
        raise JourneyError("HTTP discovery resource has no use_when guidance")
    return {key: value for key, value in resource.items() if key != "use_when"}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    beacon_cmd, wheels = _resolve_beacon_cmd(args)
    dry_run = args.dry_run

    if args.workdir:
        work = Path(args.workdir)
        work.mkdir(parents=True, exist_ok=True)
        closer = None
    elif args.keep:
        work = Path(tempfile.mkdtemp(prefix="beacon-release-check-"))
        print(f"[release-check] keeping work dir: {work}", file=sys.stderr)
        closer = None
    else:
        temp = tempfile.TemporaryDirectory(prefix="beacon-release-check-")
        work = Path(temp.name)
        closer = temp

    try:
        repo = work / "journey-project"
        repo.mkdir(parents=True, exist_ok=True)
        if not dry_run:
            (repo / "README.md").write_text(
                "# journey-project\n\nFresh minimal repository.\n", encoding="utf-8"
            )
            (repo / "pyproject.toml").write_text(
                '[project]\nname = "journey-project"\n\n[tool.pytest.ini_options]\n',
                encoding="utf-8",
            )
        manifest = repo / "beacon.generated.yaml"
        out_dir = work / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        guard_dir, guard_marker, _ = _setup_guard(work, write_sitecustomize=not dry_run)

        steps: list[Step] = []
        if wheels is not None:
            venv_dir = work / "venv"
            beacon_cmd, wheel_steps = _install_steps(venv_dir, wheels[0], wheels[1])
            steps.extend(wheel_steps)

        plan = build_plan(
            beacon_cmd=beacon_cmd,
            manifest=manifest,
            repo=repo,
            out_dir=out_dir,
            socket_guard_dir=guard_dir,
            guard_marker=guard_marker,
            inspect_task_hint=DEFAULT_TASK_HINT,
            serve_cmd=beacon_cmd,
            run_stdio_mcp=not args.no_stdio_mcp,
        )
        plan.steps = steps + plan.steps
        run_plan(plan, dry_run=dry_run)
        return 0
    except JourneyError as exc:
        print(f"RELEASE CHECK FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if closer is not None:
            closer.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
