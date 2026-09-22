"""Beacon runtime settings loaded from environment variables.

Mirrors the frozen-dataclass + ``from_env()`` pattern from
``menhir.config.settings``. All fields have usable defaults so the server
starts from just ``BEACON_MANIFEST_PATH``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from beacon.core.limits import ResourceLimits, resource_limits_from_env


def _getenv(*names: str, default: str = "") -> str:
    """Return the first non-empty env var from *names*, or *default*."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


@dataclass(frozen=True)
class BeaconSettings:
    """Immutable runtime configuration for the Beacon MCP server."""

    # Path to the beacon.yaml manifest file.
    manifest_path: str = ""

    # Root directory for resolving canonical doc paths in the manifest.
    # Defaults to the directory containing beacon.yaml when empty.
    docs_root: str = ""

    # Whether to hard-fail at startup if the manifest has validation errors.
    validate_on_load: bool = True

    # MCP server listening host/port (for remote transport; stdio ignores these).
    host: str = "127.0.0.1"
    port: int = 8788

    # Immutable resource-limit profile (defaults; overridable via BEACON_MAX_*).
    limits: ResourceLimits = field(default_factory=ResourceLimits)

    def __post_init__(self) -> None:
        if not self.manifest_path:
            raise ValueError("BEACON_MANIFEST_PATH must be set to the beacon.yaml path")

    def resolved_docs_root(self) -> str:
        """Derive docs_root from manifest_path when not explicitly set."""
        if self.docs_root:
            return self.docs_root
        import pathlib

        return str(pathlib.Path(self.manifest_path).parent)

    @classmethod
    def from_env(cls) -> BeaconSettings:
        """Load settings from environment variables."""
        validate_raw = _getenv("BEACON_VALIDATE_ON_LOAD", default="true").lower()
        return cls(
            manifest_path=_getenv("BEACON_MANIFEST_PATH"),
            docs_root=_getenv("BEACON_DOCS_ROOT"),
            validate_on_load=validate_raw not in ("false", "0", "no"),
            host=_getenv("BEACON_HOST", default="127.0.0.1"),
            port=int(_getenv("BEACON_PORT", default="8788")),
            limits=resource_limits_from_env(),
        )
