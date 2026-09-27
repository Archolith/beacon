# Deploying Beacon beyond this machine

Beacon's HTTP servers bind `127.0.0.1` only, by design. Loopback is the default
posture; exposure to other machines happens only through an explicitly configured
TLS reverse proxy. This guide describes that configuration, and the `deploy/`
directory ships the matching example configs:

```
deploy/nginx/beacon.conf        primary, complete nginx example
deploy/caddy/Caddyfile          shorter Caddy equivalent
deploy/systemd/beacon-http.service   runs `beacon serve-http` (JSON API + MCP at /mcp) under systemd
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
> - systemd: `systemd-analyze verify deploy/systemd/beacon-http.service`

## What to expose

One loopback server serves both surfaces on one port:

| Surface | Served by | Loopback address | Path |
|---------|-----------|------------------|------|
| JSON API | `beacon serve-http --manifest beacon.yaml` | `127.0.0.1:3366` | `/.well-known/archolith-beacon`, `/v1/*`, `/healthz` |
| MCP (Streamable HTTP) | the same `beacon serve-http` process | `127.0.0.1:3366` | `/mcp` |

The JSON API serves immutable GET/HEAD representations plus the dynamic query
routes (`/v1/search`, `/v1/read`, `/v1/explain`) for clients that speak plain
HTTP. The MCP endpoint serves the same knowledge as MCP tools over Streamable
HTTP, answering from the same snapshot and provider. The example configs expose
both behind one hostname and one upstream (`127.0.0.1:3366`); `/mcp` keeps its
own proxy location for streaming. To expose only the JSON API, run
`beacon serve-http --no-mcp` and drop the `/mcp` location.
(`beacon serve --snapshot S --transport http` still serves MCP alone, also on
3366 by default, if you ever need it separately.)

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

`serve-http` builds the same policy-checked snapshot in memory at startup from
`--manifest` and serves both the JSON API and `/mcp` from it; it never serves the
working tree directly. (The standalone `serve --transport http` requires a
pre-exported snapshot file instead.)

The snapshot stays immutable for the process lifetime. **After content
changes, re-export and restart the service** — a stale snapshot is the quiet
failure mode of a Beacon deployment, since the servers will happily keep
serving yesterday's knowledge. How the re-export is triggered (systemd timer,
cron, manual step) is the operator's choice.

## Run the server under a service manager

`deploy/systemd/beacon-http.service` runs `beacon serve-http` (JSON API and
`/mcp`) as an unprivileged `beacon` user, bound to loopback on the default port
(3366). It restarts on
failure, and use the standard systemd hardening set (`NoNewPrivileges`,
`ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, plus a few more common
restrictions). The manifest and snapshot paths are read-only to the service
(`ReadOnlyPaths=/var/lib/beacon`); the servers write nothing at runtime.

The units deliberately do **not** use `StateDirectory=`: systemd would make that
directory writable by the service despite `ProtectSystem=strict`, so a
compromised server could replace what it serves. Provision the content
directory yourself, owned by the deployment user rather than `beacon`:

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin beacon
sudo install -d -o deploy -g beacon -m 0750 /var/lib/beacon /var/lib/beacon/snapshots
# as the deployment user: place beacon.yaml + docs, then
beacon export --output /var/lib/beacon/snapshots/beacon.snapshot.json
```

Adjust the placeholders (executable path, manifest/snapshot path, user), then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now beacon-http
```

## The reverse proxy

The nginx config is the reference example; the Caddyfile is a shorter
equivalent. What the proxy must do, and why:

### TLS

TLS terminates at the proxy. The Beacon servers speak plain HTTP on loopback
and must never be bound to a public interface (they refuse non-loopback binds
with `http_host_not_loopback` anyway). The one exception is `serve-http`'s
container mode (below): a non-loopback bind on a private container network,
accepted only together with an exact `--allowed-host` list.

### The Host rewrite is required for both servers

Both servers are wrapped in a `LoopbackGuard` (anti-DNS-rebinding): a request
whose `Host` is not `127.0.0.1` or `localhost` (any port) is refused with
**421**, and a request carrying a non-loopback browser `Origin` with **403**.
A reverse proxy that forwards the client's `Host` header (Caddy's default) or
carries the common `proxy_set_header Host $host;` boilerplate (nginx) would
send `beacon.example.org` upstream — and **every proxied request would be
refused**. The proxy must set the upstream Host to the loopback address:

- nginx, in `location /mcp` and the JSON API locations alike:
  `proxy_set_header Host 127.0.0.1:3366;`
- Caddy, in both reverse proxies: `header_up Host {upstream_hostport}`

The example configs already do this for both upstreams.

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
error. The shipped config narrows this: `limit_req_log_level warn` plus a
Beacon `error_log ... error` keeps rate-limit refusals (the common case under
load) out of the error log entirely; they still appear, query-free, as 429s
in the access log. What remains are genuine errors (upstream down, malformed
requests), which can still carry the request line, so treat the error log as
query-bearing: restrict access and rotate it quickly. Caddy's access logs record the full URI by default; see the
comment in the Caddyfile for the redaction options rather than a guessed
snippet.

## Container: serve a pinned demo bundle

For a public demo of one project at one commit, build a **bundle** locally and
serve it with the repository's `Dockerfile` instead of a systemd unit.

1. Build the bundle (a clean clone at the pinned commit; never your working tree):

   ```bash
   python scripts/build_demo_bundle.py --source https://github.com/<org>/<repo> \
       --commit <full 40-hex sha> --name <slug> --out-dir dist/demo
   ```

   It runs `beacon build`, `beacon validate --strict-warnings` and `beacon export`
   (never with `--allow-sensitive`), then writes `beacon-demo-<slug>-<commit12>.tar.gz`
   holding `bundle.json`, `beacon.generated.yaml`, `beacon.snapshot.json` and `repo/`,
   a sparse, shallow checkout of the commit with only the manifest's documents.
   Before it returns, it extracts the tarball and smoke-tests `serve-http` from it:
   discovery, the pinned commit in freshness, a search, and the MCP tool list.
   `repo/` keeps its `.git` so discovery freshness reports that commit with
   `dirty: false`.

2. Build the image: `docker build -t beacon-demo .` (it installs Beacon from the
   checked-out source and runs as uid 10001).

3. Run it with the extracted bundle mounted read-only at `/bundle`:

   ```bash
   docker run -d --read-only --tmpfs /tmp --cap-drop ALL \
       --security-opt no-new-privileges -v /srv/beacon-demo/<slug>/current:/bundle:ro \
       --network container:<proxy> beacon-demo
   ```

   The server still binds `127.0.0.1:3366`, so the reverse proxy must share the
   container's network namespace (`--network container:<proxy>`, or compose
   `network_mode: "service:<proxy>"`). Two bundles in one namespace need distinct
   ports: append `serve-http --manifest /bundle/beacon.generated.yaml --docs-root
   /bundle/repo --port 3367` as the command.

To refresh, build a new bundle, switch the mount, and restart the container. CI's
`demo-image` job builds this image and serves a bundle of the commit under test.

### Container mode: `--allowed-host` (no shared network namespace)

Sharing the proxy's network namespace couples the containers: recreating the proxy
leaves Beacon in the old namespace. Instead, run `serve-http` in **container mode**
on a private container network, the way an app sits behind its own tunnel or proxy:

```bash
beacon serve-http --manifest /bundle/beacon.generated.yaml --docs-root /bundle/repo \
    --host 0.0.0.0 --port 3366 --allowed-host beacon.example.org
```

- A non-loopback `--host` must be an IPv4 address, and it is accepted **only**
  together with at least one `--allowed-host`. Without one, the loopback-only rule
  applies unchanged (`http_host_not_loopback`).
- Container mode binds only `0.0.0.0`, loopback, or a private RFC 1918 address
  (10/8, 172.16/12, 192.168/16). Public, multicast, broadcast, link-local and
  shared-address binds are refused (`http_host_not_private`).
- `--allowed-host` takes exact DNS names (repeatable). Wildcards, ports, IP
  addresses, names a client could read as an IPv4 address (a numeric or `0x` last
  label), and loopback names are refused (`http_allowed_host_invalid`).
- The Host guard admits loopback names plus exactly those names. Any other `Host`
  gets **421**, and a browser `Origin` that is not loopback still gets **403**, as in
  loopback mode. The proxy or tunnel must send one of the allowed names as `Host`,
  which is the public hostname unless you rewrite it.
- Discovery reports `"scope": "container"` (descriptor 1.10) instead of `"loopback"`.
- **The Host guard is not access control**: a client that can reach the port chooses its
  own `Host`. Isolation comes from the network. The bind is reachable from every container
  on that network, so attach Beacon only to a private network shared with its proxy or
  tunnel. **Never** publish its port (`-p`/`-P`, compose `ports:`), never use
  `network_mode: host`, and never run container mode directly on a host: any of those
  serves plain HTTP past the proxy's TLS, rate limits and log redaction.
- MCP at `/mcp` stays behind Beacon's own guard; fastmcp's separate host/origin
  protection is switched off explicitly, so `FASTMCP_HTTP_HOST_ORIGIN_PROTECTION`
  cannot refuse the allowed names.
- A `Host` port must be decimal 1-65535 in both modes; malformed forms get 421.
- A browser `Origin` equal to the allowed host's own `https://` origin is still 403:
  browser clients are out of scope. A future same-origin web page would need that rule
  revisited.

### Release image and bundles in CI (no workstation in the loop)

Two workflows build what a production deployment pins, so no bundle or image is ever
pushed from a workstation:

- **`.github/workflows/release-image.yml`**
  - **Validate job:** builds the `Dockerfile` with no registry credentials, smoke-tests it,
    generates an SBOM with digest-pinned Syft, and scans with digest-pinned Grype, failing
    on HIGH or CRITICAL. It uploads the sealed image, identity and evidence.
  - **Publish job:** runs only on a manual dispatch with `push: true` from `master`, behind
    the `beacon-release-image` environment. It verifies the sealed image's checksums and
    image ID before logging in, pushes that exact image to `ghcr.io/archolith/beacon`, and
    attests build provenance.
  - Pin the resulting `ghcr.io/archolith/beacon:<label>@sha256:...` in the deployment.
- **`.github/workflows/demo-bundle.yml`** (reusable, `workflow_call`, plus manual dispatch)
  - It takes a public `repository`, a full `commit` and a `name`, and runs
    `scripts/build_demo_bundle.py` (build, strict validate, export, package, serve smoke).
  - It uploads the tarball and its `.sha256`.
  - With `publish: true` it creates a prerelease named `beacon-demo-<name>-<commit12>` in
    the **calling** repository, so a project's bundle lives with that project, and refuses
    to overwrite an existing tag.
  - Pin the asset URL and SHA-256 in the deployment.

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
        -H 'Host: beacon.example.org' http://127.0.0.1:3366/mcp
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
   ss -ltn | grep -E ':3366'
   # expect: Local Address:Port 127.0.0.1:3366 — nothing else
   ```

   In container mode, check instead that the container publishes no ports
   (`docker port <container>` prints nothing) and sits only on its private network.

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
