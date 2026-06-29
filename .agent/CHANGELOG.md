# Changelog — beacon

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
