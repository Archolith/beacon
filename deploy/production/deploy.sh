#!/usr/bin/env bash
# deploy.sh - mechanical Beacon production deploy (the app lane), mirroring Menhir's:
# it verifies and refuses, it never judges. Every input comes from pins.json, validated
# by pins.py. After the switch, any failure restores the prior bundle, image and .env.
#
#   sudo bash deploy.sh [pins.json]
#
# Environment: BEACON_BASE (default /srv/beacon/production), BEACON_CONTENT_USER
# (default beacon-demo), BEACON_PUBLIC_PROBE=0 to skip the public discovery probe (first
# bring-up before the DNS cutover).
set -euo pipefail
umask 022

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="${BEACON_BASE:-/srv/beacon/production}"
PINS="${1:-$HERE/pins.json}"
CONTENT_USER="${BEACON_CONTENT_USER:-beacon-demo}"
PUBLIC_PROBE="${BEACON_PUBLIC_PROBE:-1}"
APP=beacon-prod-app
MAX_BUNDLE_BYTES=$((64 * 1024 * 1024))
HEALTH_TIMEOUT_S=120

die() { echo "deploy.sh: $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root (sudo): extraction runs as $CONTENT_USER, compose as root"
command -v python3 >/dev/null || die "python3 is required"
id "$CONTENT_USER" >/dev/null 2>&1 || die "content user $CONTENT_USER does not exist"

# 1. Pins: strict validation, shell-quoted assignments only.
assignments="$(python3 "$HERE/pins.py" "$PINS")" || die "invalid pins: $PINS"
eval "$assignments"

BUNDLE_ROOT="$BASE/bundles/$PIN_NAME"
TARGET="$BUNDLE_ROOT/$PIN_STEM"
CURRENT="$BUNDLE_ROOT/current"
ENV_FILE="$HERE/.env"
COMPOSE=(docker compose --project-name beacon-prod --env-file "$ENV_FILE"
         -f "$HERE/docker-compose.production.yml")

tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT

# 2. Fetch and verify the bundle before anything on the host changes.
echo "==> Fetching $PIN_STEM"
curl -fsSL --proto '=https' --tlsv1.2 --retry 3 --max-filesize "$MAX_BUNDLE_BYTES" \
    -o "$tmp/bundle.tar.gz" "$PIN_URL" || die "download failed"
echo "$PIN_SHA256  $tmp/bundle.tar.gz" | sha256sum --strict -c - >/dev/null \
    || die "bundle SHA-256 does not match the pin"

# 3. Refuse anything but plain files and directories under exactly <stem>/.
python3 - "$tmp/bundle.tar.gz" "$PIN_STEM" <<'PY' || die "bundle archive failed the member check"
import sys, tarfile
path, stem = sys.argv[1], sys.argv[2]
with tarfile.open(path, "r:gz") as archive:
    for member in archive.getmembers():
        name = member.name
        parts = name.split("/")
        if name.startswith("/") or ".." in parts or parts[0] != stem:
            raise SystemExit(f"unsafe member path: {name!r}")
        if not (member.isfile() or member.isdir()):
            raise SystemExit(f"non-regular member: {name!r}")
PY

# 4. Extract as the content user (idempotent: an already-extracted stem is reused).
install -d -o "$CONTENT_USER" -g "$CONTENT_USER" -m 0755 "$BASE/bundles" "$BUNDLE_ROOT"
if [ ! -d "$TARGET" ]; then
    echo "==> Extracting as $CONTENT_USER"
    stage="$BUNDLE_ROOT/.staging-$$"
    install -d -o "$CONTENT_USER" -g "$CONTENT_USER" -m 0755 "$stage"
    chmod 0644 "$tmp/bundle.tar.gz"
    chmod 0755 "$tmp"
    sudo -n -u "$CONTENT_USER" sh -c 'umask 022 && tar -xzf "$1" -C "$2" --no-same-owner' \
        _ "$tmp/bundle.tar.gz" "$stage" || { rm -rf -- "$stage"; die "extraction failed"; }
    mv -T "$stage/$PIN_STEM" "$TARGET"
    rmdir "$stage"
fi
python3 - "$TARGET/bundle.json" "$PIN_COMMIT" "$PIN_NAME" <<'PY' || die "bundle.json does not match the pin"
import json, sys
bundle = json.load(open(sys.argv[1], encoding="utf-8"))
if bundle.get("commit") != sys.argv[2] or bundle.get("name") != sys.argv[3]:
    raise SystemExit("bundle.json commit/name differ from pins.json")
PY

# 5. Pull the image by digest (before the switch: a pull failure changes nothing).
echo "==> Pulling $PIN_IMAGE"
docker pull --quiet "$PIN_IMAGE" >/dev/null || die "image pull failed"

# 6. Record the prior state, then switch.
prior_current="$(readlink "$CURRENT" 2>/dev/null || true)"
[ -f "$ENV_FILE" ] && cp -p -- "$ENV_FILE" "$tmp/env.prior"

write_env() { # <image> <public host>
    local next="$ENV_FILE.next"
    printf 'BEACON_IMAGE=%s\nBEACON_PUBLIC_HOST=%s\nBEACON_BUNDLE_DIR=%s\n' \
        "$1" "$2" "$CURRENT" > "$next"
    chmod 0640 "$next"
    mv -f -- "$next" "$ENV_FILE"
}
switch_current() { # <stem>
    sudo -n -u "$CONTENT_USER" ln -sfn -- "$1" "$CURRENT.next"
    mv -T -- "$CURRENT.next" "$CURRENT"
}
rollback() {
    echo "==> FAILED: $*; rolling back" >&2
    if [ -n "$prior_current" ] && [ -f "$tmp/env.prior" ]; then
        switch_current "$prior_current"
        cp -p -- "$tmp/env.prior" "$ENV_FILE"
        "${COMPOSE[@]}" up -d --force-recreate --no-build beacon >&2 \
            || echo "deploy.sh: ROLLBACK FAILED; the app needs manual recovery" >&2
        echo "==> Restored $prior_current" >&2
    else
        "${COMPOSE[@]}" stop beacon >&2 || true
        echo "==> First deploy: nothing to restore; the app is stopped" >&2
    fi
    exit 1
}

switch_current "$PIN_STEM"
write_env "$PIN_IMAGE" "$PIN_PUBLIC_HOST"

# 7. Recreate the app on the new bundle and image.
echo "==> Recreating $APP"
"${COMPOSE[@]}" up -d --force-recreate --no-build beacon || rollback "compose up failed"

# 8. Health, then the pinned commit from inside the container (independent of DNS).
deadline=$((SECONDS + HEALTH_TIMEOUT_S))
until [ "$(docker inspect -f '{{.State.Health.Status}}' "$APP" 2>/dev/null)" = healthy ]; do
    [ "$SECONDS" -lt "$deadline" ] || rollback "not healthy within ${HEALTH_TIMEOUT_S}s"
    sleep 3
done
docker exec "$APP" python -c '
import json, sys, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:3366/.well-known/archolith-beacon", timeout=10))
repo = d["freshness"]["repository"]
ok = repo.get("commit") == sys.argv[1] and repo.get("dirty") is False and d["scope"] == "container"
sys.exit(0 if ok else 1)
' "$PIN_COMMIT" || rollback "discovery does not report the pinned commit"

# 9. The public path through the tunnel (skip before the DNS cutover).
if [ "$PUBLIC_PROBE" = 1 ]; then
    curl -fsS --max-time 20 "https://$PIN_PUBLIC_HOST/.well-known/archolith-beacon" -o "$tmp/public.json" \
        || rollback "public discovery unreachable"
    python3 - "$tmp/public.json" "$PIN_COMMIT" <<'PY' || rollback "public discovery does not report the pinned commit"
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if d["freshness"]["repository"].get("commit") == sys.argv[2] else 1)
PY
fi

echo "==> Deployed $PIN_STEM on $PIN_IMAGE (public host $PIN_PUBLIC_HOST)"
