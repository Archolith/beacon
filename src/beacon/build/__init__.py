"""Beacon v0.3 build pipeline (merged normalized records -> owned artifact).

The pipeline is deliberately small for the Menhir MVP:

* :mod:`beacon.build.policy` -- authority resolution over merged
  :class:`~beacon.sources.base.NormalizedRecord` values (intent / reality /
  history), failing closed on ambiguity;
* :mod:`beacon.build.project` -- deterministic projection of the resolved
  facts into a raw manifest mapping (no LLM, no invented fields);
* :mod:`beacon.build.snapshot` -- the snapshot reader, the reverse of the
  v0.2 export writer, so a server can run snapshot-only.
"""

from beacon.build.policy import (
    BuildError,
    DriftRecord,
    MergedProjectFacts,
    resolve_project_facts,
)
from beacon.build.project import build_raw_manifest, render_manifest_yaml

__all__ = [
    "BuildError",
    "DriftRecord",
    "MergedProjectFacts",
    "build_raw_manifest",
    "render_manifest_yaml",
    "resolve_project_facts",
]
