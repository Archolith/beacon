# Beacon demo image: serves one demo bundle (scripts/build_demo_bundle.py) with
# `beacon serve-http` -- JSON API plus MCP at /mcp on 127.0.0.1:3366.
#
# The default command binds loopback only, so a reverse proxy must share this
# container's network namespace (for example compose `network_mode: "service:caddy"`).
# Alternatively override the command with container mode on a private network:
#   serve-http ... --host 0.0.0.0 --allowed-host <public name>   (docs/deployment.md)
# Mount the extracted bundle read-only at /bundle. See docs/deployment.md.
FROM python:3.13-slim-trixie@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b

# git: serve-http observes the bundle's pinned commit at startup for discovery freshness.
# upgrade: pick up Debian security fixes newer than the pinned base (release-image.yml scans).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/beacon-src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf /opt/beacon-src

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin beacon

# The bundle is owned by the deploy user, not uid 10001: without safe.directory git
# refuses the checkout and freshness reads "unavailable". GIT_OPTIONAL_LOCKS=0 keeps
# `git status` from trying to write the index on the read-only mount.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    GIT_OPTIONAL_LOCKS=0 \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0=safe.directory \
    GIT_CONFIG_VALUE_0=*

USER 10001:10001
WORKDIR /bundle
EXPOSE 3366
ENTRYPOINT ["beacon"]
CMD ["serve-http", "--manifest", "/bundle/beacon.generated.yaml", "--docs-root", "/bundle/repo", "--port", "3366"]
