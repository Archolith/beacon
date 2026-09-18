"""MCP lifespan: load manifest + build provider at startup.

Beacon is self-contained — it needs only the beacon.yaml on disk, no external
service. The lifespan validates the manifest eagerly (fail loudly on bad config)
then builds the :class:`~beacon.provider.manifest_provider.ManifestBeaconProvider`
and stores it in a module-level slot so tools can retrieve it without context
threading.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

from beacon.config.settings import BeaconSettings
from beacon.provider.manifest_provider import ManifestBeaconProvider

logger = logging.getLogger(__name__)

# Module-level slot — set once during lifespan startup, never mutated after.
_provider: ManifestBeaconProvider | None = None


def get_provider() -> ManifestBeaconProvider:
    """Return the active provider; raises ``RuntimeError`` if not initialised."""
    if _provider is None:
        raise RuntimeError("Beacon provider is not initialised. Is the MCP server running?")
    return _provider


def _diag(msg: str) -> None:
    print(f"[beacon] {msg}", file=sys.stderr, flush=True)


@asynccontextmanager
async def beacon_lifespan(app: FastMCP[object]) -> AsyncIterator[dict[str, object]]:  # noqa: ANN401
    global _provider  # noqa: PLW0603

    settings = BeaconSettings.from_env()

    if getattr(settings, "snapshot_path", ""):
        _diag(f"Loading snapshot from {settings.snapshot_path} ...")
        try:
            from beacon.build.snapshot import load_snapshot

            snapshot = load_snapshot(settings.snapshot_path, limits=settings.limits)
            provider = ManifestBeaconProvider.from_snapshot(snapshot, limits=settings.limits)
        except Exception as exc:
            _diag(f"FATAL: could not load snapshot — {exc}")
            raise
    else:
        _diag(f"Loading manifest from {settings.manifest_path} ...")
        try:
            provider = ManifestBeaconProvider.from_paths(
                manifest_path=settings.manifest_path,
                docs_root=settings.resolved_docs_root(),
                validate=settings.validate_on_load,
                limits=settings.limits,
            )
        except Exception as exc:
            _diag(f"FATAL: could not load manifest — {exc}")
            raise

    _provider = provider
    limits = provider.limits
    _diag(
        "Effective limits — "
        f"manifest_bytes={limits.manifest_bytes} documents={limits.documents} "
        f"document_bytes={limits.document_bytes} "
        f"total_document_bytes={limits.total_document_bytes} chunks={limits.chunks} "
        f"snapshot_bytes={limits.snapshot_bytes} yaml_depth={limits.yaml_depth} "
        f"yaml_nodes={limits.yaml_nodes} yaml_aliases={limits.yaml_aliases} "
        f"path_bytes={limits.path_bytes} query_bytes={limits.query_bytes} "
        f"result_limit={limits.result_limit} "
        f"init_report_bytes={limits.init_report_bytes}"
    )
    chunk_count = len(provider.doc_index.chunks)
    concept_count = len(provider.manifest.core_concepts)
    _diag(
        f"Beacon ready — project={provider.manifest.project.name!r} "
        f"concepts={concept_count} doc_chunks={chunk_count}"
    )
    logger.info(
        "beacon manifest loaded project=%r concepts=%d chunks=%d",
        provider.manifest.project.name,
        concept_count,
        chunk_count,
    )

    yield {"provider": _provider}

    _provider = None
    _diag("Beacon shutdown.")
