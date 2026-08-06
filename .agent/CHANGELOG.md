# Changelog — beacon

## 2026-08-06 — Atlaso Ambient Memory / Orientation comparison

- `docs/prior-art/atlaso-ambient-memory-comparison.md` — compare Atlaso's automatic recall and closed Ambient Memory composer with Beacon v0 and the Adaptive Semantic Object / Orientation direction
- Record direct prior art for cross-tool memory, session-start push context, returning-user continuity, compact conflict verdicts, and background enrichment
- Distinguish Atlaso's memory-first fixed-seed context from Beacon's provider-neutral, cross-source, consumer/purpose/budget-aware composition model
- Add lifecycle delivery, injection-safety, scope-parity, Time-to-Competence, push/pull/adaptive, and adversarial benchmark implications

## 2026-08-05 — Graft prior-art and context-composition comparison

- `docs/prior-art/graft-beacon-context-comparison.md` — compare Graft with Beacon v0 and the Adaptive Semantic Object / Orientation direction
- Record direct overlap in code orientation, graph-ranked retrieval, source-grounded context packs, freshness, and push/pull benchmarking
- Define Beacon differentiation around provider-neutral contracts, cross-source authority and history, consumer-aware composition, and Time-to-Competence
- Propose cold, push, pull, adaptive, and Menhir-backed benchmark arms plus a possible Graft structural-provider adapter

## 2026-06-29 — Beacon v0 initial implementation

- `src/beacon/core/schema.py` — BeaconManifest + all answer-contract frozen dataclasses
- `src/beacon/core/loader.py` — YAML loader with structural validation
- `src/beacon/core/validator.py` — semantic validator (dup ids, dangling paths, missing fields)
- `src/beacon/core/doc_index.py` — heading-chunked doc index with keyword search
- `src/beacon/provider/base.py` — BeaconProvider Protocol (5 methods)
- `src/beacon/provider/manifest_provider.py` — ManifestBeaconProvider v0 impl
- `src/beacon/mcp/` — cth_mcp_framework gateway server, 5 readonly tools
- `beacon.yaml` — demo manifest describing menhir (corrected to reality)
- `tests/` — 35 offline tests covering all layers
- `.agent/architecture.md` + `.agent/data_models.md` — filled in with real content
- Registered in `cth.agentsmith/mcp-registry.json`; `sync.py generate` run
