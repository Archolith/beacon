"""Beacon provider layer.

v0 ships :class:`ManifestBeaconProvider`, which derives all answers
deterministically from a parsed ``beacon.yaml`` + in-memory doc index.
"""

from beacon.provider.base import BeaconProvider
from beacon.provider.manifest_provider import ManifestBeaconProvider

__all__ = ["BeaconProvider", "ManifestBeaconProvider"]
