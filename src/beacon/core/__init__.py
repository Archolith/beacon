"""Beacon core: manifest schema, loader, validator, and document index.

Pure data + parsing. No Menhir, Neo4j, or MCP imports live here so any project
can reuse the manifest machinery on its own.
"""

from beacon.core.doc_index import DocChunk, DocIndex
from beacon.core.loader import ManifestError, load_beacon_manifest, parse_manifest
from beacon.core.schema import (
    AgentOnboarding,
    BeaconConcept,
    BeaconDoc,
    BeaconGuardrail,
    BeaconManifest,
    BeaconProjectInfo,
    BeaconSource,
    ConceptExplanation,
    GuardrailResponse,
    ProjectOverview,
    SearchHit,
    SearchResult,
    to_payload,
)
from beacon.core.validator import (
    ManifestValidationError,
    ValidationIssue,
    ValidationReport,
    require_valid_manifest,
    validate_beacon_manifest,
)

__all__ = [
    "DocChunk",
    "DocIndex",
    "ManifestError",
    "load_beacon_manifest",
    "parse_manifest",
    "AgentOnboarding",
    "BeaconConcept",
    "BeaconDoc",
    "BeaconGuardrail",
    "BeaconManifest",
    "BeaconProjectInfo",
    "BeaconSource",
    "ConceptExplanation",
    "GuardrailResponse",
    "ProjectOverview",
    "SearchHit",
    "SearchResult",
    "to_payload",
    "ManifestValidationError",
    "ValidationIssue",
    "ValidationReport",
    "require_valid_manifest",
    "validate_beacon_manifest",
]
