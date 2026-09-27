# Beacon production deployment

This is Beacon's own deployment, mirroring Menhir's: its own compose projects, its own
Cloudflare Tunnel, and an image and bundles built in CI and pinned by digest. The host
builds nothing and receives nothing from a workstation. It downloads pinned artifacts,
verifies them, and switches.

```
/srv/beacon/production/
  deploy/     these files, plus pins.json and the .env that deploy.sh writes (root-owned)
  ingress/    cloudflared-config.yml (from cloudflared-config.yml.example)
  secrets/    cloudflare/credentials.json (root-owned, 0640, group 65532)
  bundles/    <name>/<beacon-demo-name-commit12>/ and <name>/current  (owned by beacon-demo)
```

| File | Role |
|---|---|
| `docker-compose.production.yml` | `beacon-prod-app`: `serve-http` in container mode on `beacon-proxy`, hardened, with the bundle mounted read-only |
| `docker-compose.cloudflared.yml` | `beacon-prod-cloudflared`: the tunnel, the same pinned image as Menhir's |
| `cloudflared-config.yml.example` | tunnel ingress: the public host to `http://10.203.66.3:3366`, anything else 404 |
| `pins.example.json` | the pins shape; the real `pins.json` is committed per release |
| `pins.py` | strict pins validator, used by `deploy.sh` |
| `deploy.sh` | the mechanical app deploy, with rollback |

## Where the pins come from

- **Image:** a dispatch of `.github/workflows/release-image.yml` with `push: true` (environment
  approval) prints `ghcr.io/archolith/beacon:<label>@sha256:...`.
- **Bundle:** a dispatch of `.github/workflows/demo-bundle.yml` with `publish: true` prints the
  release asset URL and its SHA-256.
- Changing either one is a PR that edits `pins.json`.

## One-time host setup

```bash
# Content owner: no login, no sudo, no docker. uid/gid 3366 already exists on the VPS
# (created for the yawn-hosted demo); reuse it.
getent passwd beacon-demo || {
  sudo groupadd --system --gid 3366 beacon-demo
  sudo useradd --system --uid 3366 --gid 3366 --no-create-home \
      --shell /usr/sbin/nologin beacon-demo
}
sudo install -d -m 0755 /srv/beacon/production /srv/beacon/production/deploy \
    /srv/beacon/production/ingress
sudo install -d -m 0750 -g 65532 /srv/beacon/production/secrets \
    /srv/beacon/production/secrets/cloudflare
sudo install -d -o beacon-demo -g beacon-demo -m 0755 /srv/beacon/production/bundles

# Internal, IPv4-only network shared by the app and its tunnel. 10.203.66.0/24 is outside
# Docker's default address pools; check that it is free first.
docker network create --internal --ipv6=false --subnet 10.203.66.0/24 beacon-proxy

# Tunnel. Credentials go straight to secrets/ and are never printed or committed.
cloudflared tunnel create beacon-prod        # or via the Cloudflare API
# install the credentials as secrets/cloudflare/credentials.json (0640 root:65532),
# write ingress/cloudflared-config.yml from the example, then:
docker compose -f /srv/beacon/production/deploy/docker-compose.cloudflared.yml up -d
```

## Deploy (the app lane)

```bash
sudo BEACON_PUBLIC_PROBE=0 bash /srv/beacon/production/deploy/deploy.sh   # before the DNS cutover
sudo bash /srv/beacon/production/deploy/deploy.sh                         # after it
```

`deploy.sh`:
1. validates `pins.json`;
2. downloads the bundle, checks its SHA-256, and refuses any archive member that isn't a plain
   file or directory under `<stem>/`;
3. extracts it as `beacon-demo` and checks `bundle.json` against the pin;
4. pulls the image by digest;
5. switches `current`, writes `.env`, and recreates `beacon-prod-app`;
6. waits for it to be healthy, then requires discovery to report the pinned commit (clean,
   `scope: container`), from inside the container and, unless skipped, over the public URL.

Any failure after the switch restores the prior `current`, `.env` and image. On a first
deploy it stops the app instead.

## Cutover and checks

- Before switching DNS, request the public hostname through the tunnel and confirm Beacon
  sees it as `Host`. cloudflared forwards the public name by default, and the config sets no
  `httpHostHeader`.
- DNS: replace the proxied A record with the tunnel's CNAME. The zone's Cloudflare
  rate-limit rule applies to the tunnel path too.
- `docker port beacon-prod-app` must print nothing. The app sits only on `beacon-proxy`,
  which has no egress.
