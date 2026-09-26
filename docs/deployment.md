# Deploying Beacon beyond this machine

Beacon's HTTP servers bind `127.0.0.1` only, by design. Loopback is the default
posture; exposure to other machines happens only through an explicitly configured
TLS reverse proxy. This guide describes that configuration, and the `deploy/`
directory ships the matching example configs:

```
deploy/nginx/beacon.conf        primary, complete nginx example
deploy/caddy/Caddyfile          shorter Caddy equivalent
deploy/systemd/beacon-http.service   runs the JSON API under systemd
deploy/systemd/beacon-mcp.service    runs the MCP server under systemd
```

This is documentation and config only. Beacon ships no hosting, no DNS, and no
certificates; the operator provides the machine, the hostname, and the TLS
certificate.

> **Validation status.** These configs were written against nginx, Caddy, and
> systemd behavior, but they were **not validated in the Beacon development
> environment** (neither `nginx`, `caddy`, nor `systemd-analyze` is installed
> there) and were not tested against a live deployment. Validate before use:
>
> - nginx: `nginx -t` (after installing the file, e.g. in `/etc/nginx/conf.d/`)
> - Caddy: `caddy validate --config deploy/caddy/Caddyfile`
> - systemd: `systemd-analyze verify deploy/systemd/beacon-http.service deploy/systemd/beacon-mcp.service`

## What to expose

Two independent loopback servers can be exposed, singly or side by side:

| Server | Command | Loopback address | Path |
|--------|---------|------------------|------|
| JSON API | `beacon serve-http --manifest beacon.yaml` | `127.0.0.1:8765` | `/.well-known/archolith-beacon`, `/v1/*`, `/healthz` |
| MCP (Streamable HTTP) | `beacon serve --snapshot beacon.snapshot.json --transport http` | `127.0.0.1:8766` | `/mcp` |

The JSON API serves immutable GET/HEAD representations plus the dynamic query
routes (`/v1/search`, `/v1/read`, `/v1/explain`) for clients that speak plain
HTTP. The MCP endpoint serves the same knowledge as MCP tools over Streamable
HTTP. The example configs expose both behind one hostname: `/mcp` goes to 8766,
everything else to 8765. Expose only what your clients need.

**Trust level: direct, unverified.** Both servers are unsigned and
self-reported; the discovery document labels this `"trust": "direct_unverified"`.
There is **no authentication**: anyone who can reach the proxy can read
everything the snapshot serves. Do not expose anything that is not already
publishable. If that is unacceptable today, add access control at the proxy
(Basic auth, IP allowlists, mTLS) — Beacon itself provides none.

Plan rules this guide preserves:

- Loopback stays the default; exposure happens only through an explicitly
  configured TLS reverse proxy.
- The proxy does TLS, per-client rate limits, request size limits, and access
  logs. Beacon does none of these in-process.
- **No CORS.** Browser clients are out of scope; no route sends or needs CORS
  headers. Do not add `Access-Control-Allow-Origin` headers at the proxy either.

## Build (and rebuild) the snapshot

Only serve a snapshot built by `beacon export`. Export applies the serving
policy — excluded documents, secret scanning, and `visibility: local` rules —
so excluded, sensitive, and local-only documents are not in the snapshot and
cannot leak through a deployment.

```bash
beacon export                     # writes beacon.snapshot.json, applying the serving policy
```

The two servers consume snapshots differently:

- `serve-http` builds the same policy-checked snapshot in memory at startup
  from `--manifest`; it never serves the working tree directly.
- `serve --transport http` requires a pre-exported snapshot file.

Both hold the snapshot immutable for the process lifetime. **After content
changes, re-export and restart the service** — a stale snapshot is the quiet
failure mode of a Beacon deployment, since the servers will happily keep
serving yesterday's knowledge. How the re-export is triggered (systemd timer,
cron, manual step) is the operator's choice.

## Run each server under a service manager

`deploy/systemd/` contains one unit per server. Both run as an unprivileged
`beacon` user, bind loopback on the default ports (8765 and 8766), restart on
failure, and use the standard systemd hardening set (`NoNewPrivileges`,
`ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, plus a few more common
restrictions). The manifest and snapshot paths are read-only to the service;
the servers write nothing at runtime.

Adjust the placeholders (executable path, manifest/snapshot path, user), then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now beacon-http beacon-mcp
```

## The reverse proxy

The nginx config is the reference example; the Caddyfile is a shorter
equivalent. What the proxy must do, and why:

### TLS

TLS terminates at the proxy. The Beacon servers speak plain HTTP on loopback
and must never be bound to a public interface (they refuse non-loopback binds
with `http_host_not_loopback` anyway).

### The Host rewrite is required for MCP

The MCP server is wrapped in a `LoopbackGuard` (anti-DNS-rebinding): a request
whose `Host` is not `127.0.0.1` or `localhost` (any port) is refused with
**421**, and a request carrying a non-loopback browser `Origin` with **403**.
A reverse proxy that forwards the client's `Host` header (Caddy's default) or
carries the common `proxy_set_header Host $host;` boilerplate (nginx) would
send `beacon.example.org` upstream — and **every proxied MCP request would be
refused**. The proxy must set the upstream Host to the loopback address:

- nginx, in `location /mcp`: `proxy_set_header Host 127.0.0.1:8766;`
- Caddy, in the `/mcp` reverse proxy: `header_up Host {upstream_hostport}`

The JSON API has no Host check today; the example configs still pin
`Host 127.0.0.1:8765` upstream so the pattern is uniform and future-proof.

### No buffering, long timeouts, session header for MCP

Streamable HTTP uses POST and GET on `/mcp`, can hold the connection open with
Server-Sent Events, and pages sessions through the `Mcp-Session-Id`
request/response header. The proxy must:

- not buffer responses — nginx `proxy_buffering off;`, Caddy
  `flush_interval -1` — or SSE delivery stalls until the buffer fills;
- allow long read timeouts — nginx `proxy_read_timeout 3600s;` — since idle
  event streams look like a stalled upstream;
- pass the `Mcp-Session-Id` header through unchanged. It is an ordinary
  header; proxies forward it unless configured to strip it, so the only
  requirement is to not strip it.

### Request size limit

All JSON API routes are GET/HEAD (no bodies), and MCP messages are small
JSON-RPC envelopes. 64 KB (`client_max_body_size 64k;` /
`request_body max_size 64KB`) is generous. Requests are refused outright
above the limit; there is no legitimate large upload.

### Methods

The JSON API serves GET and HEAD only. `/mcp` serves GET (SSE stream), POST
(JSON-RPC), and DELETE (session end). The example configs refuse every other
method at the proxy.

### Per-client rate limits

Rate limiting lives at the proxy. The nginx config defines one zone per
client IP for the JSON API and stricter, separate zones for `/v1/search`
(each query runs a scan) and `/mcp` (tool traffic). **Caddy has no built-in
rate limiting**: use a rate-limit plugin build or an upstream limiter; the
shipped Caddyfile deliberately contains no rate-limit directives.

### Access logs must not contain query strings

`/v1/search?q=...` carries user queries, and Beacon never logs them
server-side — the proxy must not become the leak. The nginx config defines a
`log_format` that logs `$uri` (the path only) instead of `$request` or
`$request_uri`, which embed the query string. Never switch the format to
`$request`, `$request_uri`, `$args`, or `$query_string`, and keep query
strings out of any other logging or analytics in front of Beacon. One caveat
this format cannot fix: nginx can embed the raw request line — query string
included — in its **error log** when a request is malformed or triggers an
error, so the error log needs the same care (ship it to storage operators
treat as potentially query-bearing, or keep it at a level where such lines
are rare). Caddy's access logs record the full URI by default; see the
comment in the Caddyfile for the redaction options rather than a guessed
snippet.

## Verify a deployment (curl checklist)

With `beacon.example.org` standing in for your hostname, from any client
machine:

1. **Discovery answers through the proxy** and labels the trust level:

   ```bash
   curl -fsS https://beacon.example.org/.well-known/archolith-beacon
   # expect: 200, JSON with "trust": "direct_unverified"
   ```

2. **A forged Host straight at the loopback MCP port is refused** — this
   proves the guard is active, which is what makes the proxy's Host rewrite
   load-bearing rather than decorative:

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' -X POST \
        -H 'Host: beacon.example.org' http://127.0.0.1:8766/mcp
   # expect: 421

   curl -s -o /dev/null -w '%{http_code}\n' -X POST \
        https://beacon.example.org/mcp -H 'Accept: application/json'
   # expect: an MCP-level answer (not 421/403) — the rewrite did its job
   ```

3. **The query string never reaches the access log:**

   ```bash
   curl -s "https://beacon.example.org/v1/search?q=SECRET-PROBE-QUERY" -o /dev/null
   sudo grep -c SECRET-PROBE-QUERY /var/log/nginx/beacon.access.log
   # expect: 0 — a count of 1 means your log format leaked the query
   ```

4. **Plain HTTP redirects to HTTPS:**

   ```bash
   curl -sI http://beacon.example.org/v1/status | head -n 1
   # expect: 301 or 308 with Location: https://beacon.example.org/v1/status
   ```

5. **Both servers still bind loopback only**, on the server itself:

   ```bash
   ss -ltn | grep -E ':(8765|8766)'
   # expect: Local Address:Port 127.0.0.1:8765 and 127.0.0.1:8766 — nothing else
   ```

## Not provided yet

Honest limits of this deployment story:

- **No authentication.** Beacon serves no auth surface; whoever reaches the
  proxy reads the snapshot.
- **No signing and no trust broker.** Responses and the discovery document
  are unsigned and self-reported (`"trust": "direct_unverified"`). Remote
  trust, signed attestation, and the trust broker are later protocol layers
  in the trust plan:
  `.agent/plans/beacon-trust-hub-and-federation-plan-2026-08-09.md`.
- **No CORS.** Browser clients are out of scope by design.
- **No in-app rate limiting or request-size limits** — by plan, both live at
  the proxy.
- **No Caddy rate limiting in the example** — Caddy needs a plugin or an
  upstream limiter; see the comment in the Caddyfile.
