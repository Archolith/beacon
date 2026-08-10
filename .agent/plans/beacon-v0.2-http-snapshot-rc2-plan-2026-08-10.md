# Beacon v0.2 RC2 loopback HTTP snapshot plan

**Date:** 2026-08-10  
**Status:** IMPLEMENTING  
**Target:** `archolith-beacon==0.2.0rc2`

## Goal

Give clients that do not speak MCP a small, read-only HTTP compatibility surface without weakening
Beacon's deterministic snapshot, publication-policy, privacy, or future trust boundaries.

## Frozen RC2 contract

- Command: `beacon serve-http --manifest beacon.yaml --host 127.0.0.1 --port 8765`.
- Only `127.0.0.1` is accepted; `--port 0` selects an available port.
- The embedded canonical snapshot is built once at startup through the existing export policy,
  path, resource, and secret gates. Requests never reread source files.
- Routes:
  - `GET|HEAD /.well-known/archolith-beacon`
  - `GET|HEAD /v1/snapshot`
  - `GET|HEAD /beacon.json` as a byte/header-identical convenience alias
  - `GET|HEAD /healthz`
- Snapshot responses provide exact length, quoted SHA-256 ETag,
  `X-Beacon-Snapshot-SHA256`, `Cache-Control: no-cache`, and `nosniff`; matching
  `If-None-Match` returns bodyless `304`.
- Discovery advertises loopback/no-auth scope plus explicit `snapshot=true`, `query=false`,
  `question_submission=false`, and `mcp_http=false` capabilities.
- Health contains only readiness, Beacon version, immutable-startup mode, and snapshot
  schema/digest. It is `no-store` and contains no project content, paths, environment, or time.
- Unknown routes and unsupported methods return deterministic versioned Beacon error JSON. No CORS,
  access logs, server/date headers, hot reload, source writes, outbound network, or remote binding.

## Future boundary, not RC2 scope

- Authenticated remote exposure, signed identity/trust handshakes, query and question endpoints,
  browser-origin allowlists, hot refresh, and Archolith hosting remain later work.
- A future AI answer broker may synthesize only into validated Beacon-shaped responses with source
  snapshot identity and citations; raw model output never crosses the boundary.

## Acceptance matrix

| Boundary | Required proof |
| --- | --- |
| Canonical bytes | `/v1/snapshot`, `/beacon.json`, and `beacon export` are byte-identical |
| Immutability | source changes after startup do not change responses |
| HTTP contract | exact routes, GET/HEAD, ETag/304, 404/405 envelopes, no CORS |
| Privacy | discovery/health/errors/startup omit content, paths, env, timestamps, and exception text |
| Safety | invalid/unpublishable/secret-bearing snapshots refuse before binding |
| Exposure | non-loopback hosts and invalid/occupied ports fail closed |
| Runtime | real installed-wheel process answers every route over loopback under outbound denial |
| Packaging | direct Starlette/Uvicorn dependencies, wheel inspection, clean install, `pip check` |
| Matrix | Python 3.12/3.13/3.14 locally; hosted Linux/macOS/Windows matrix after push |

## Release sequence

1. Implement and centrally audit RC2 without moving the immutable RC1 tag.
2. Build and install framework-first wheels in clean environments.
3. Push the reviewed branch and require branch/PR 3-by-3 CI.
4. Register no new publisher; the existing trusted publisher remains scoped to `release.yml` and
   environment `pypi`.
5. With explicit release authorization, tag and publish `v0.2.0rc2`, then public-index smoke it.
6. Conduct the deferred unaided owner trial against RC2 before final `0.2.0`.
