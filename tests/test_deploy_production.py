"""Static safety checks for Beacon's own production deployment (``deploy/production/``).

These pin the properties the deployment relies on: container mode on an internal network
with no ports, no egress, a read-only bundle and digest-pinned images; strict pins; and a
deploy script that verifies before it switches and rolls back after.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

PROD = Path(__file__).resolve().parents[1] / "deploy" / "production"
APP_COMPOSE = PROD / "docker-compose.production.yml"
INGRESS_COMPOSE = PROD / "docker-compose.cloudflared.yml"
DEPLOY_SH = PROD / "deploy.sh"
DIGEST_IMAGE = "cloudflare/cloudflared@sha256:"

_COMMIT = "0123456789abcdef0123456789abcdef01234567"
_STEM = f"beacon-demo-beacon-{_COMMIT[:12]}"
_GOOD_PINS: dict[str, Any] = {
    "pins_version": 1,
    "image": "ghcr.io/archolith/beacon:0.2.0rc2-1@sha256:" + "a" * 64,
    "public_host": "beacon.archolith.dev",
    "bundle": {
        "name": "beacon",
        "commit": _COMMIT,
        "url": f"https://github.com/Archolith/beacon/releases/download/{_STEM}/{_STEM}.tar.gz",
        "sha256": "b" * 64,
    },
}


@pytest.fixture(scope="module")
def pins() -> Any:
    spec = importlib.util.spec_from_file_location("beacon_prod_pins", PROD / "pins.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _service(path: Path, name: str) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8"))["services"][name])


def _hardened(service: dict[str, Any]) -> None:
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert "ports" not in service and "expose" not in service
    assert "network_mode" not in service
    assert "environment" not in service and "env_file" not in service
    limits = service["deploy"]["resources"]["limits"]
    assert {"cpus", "memory", "pids"} <= set(limits)


# -- compose ---------------------------------------------------------------------------


def test_app_runs_container_mode_on_the_internal_network_only() -> None:
    app = _service(APP_COMPOSE, "beacon")
    _hardened(app)
    assert app["user"] == "10001:10001"
    assert app["image"].startswith("${BEACON_IMAGE:?")
    command = app["command"]
    assert command[:1] == ["serve-http"]
    assert command[command.index("--host") + 1] == "0.0.0.0"
    assert command[command.index("--port") + 1] == "3366"
    assert command[command.index("--allowed-host") + 1].startswith("${BEACON_PUBLIC_HOST:?")
    assert list(app["networks"]) == ["beacon-proxy"]
    address = ipaddress.IPv4Address(app["networks"]["beacon-proxy"]["ipv4_address"])
    assert address in ipaddress.IPv4Network("10.203.66.0/24")
    (mount,) = app["volumes"]
    assert mount["target"] == "/bundle" and mount["read_only"] is True
    assert mount["bind"]["create_host_path"] is False
    assert "healthz" in " ".join(app["healthcheck"]["test"])


def test_tunnel_is_pinned_hardened_and_the_only_egress() -> None:
    tunnel = _service(INGRESS_COMPOSE, "cloudflared")
    _hardened(tunnel)
    assert (
        tunnel["image"].startswith(DIGEST_IMAGE) and len(tunnel["image"]) == len(DIGEST_IMAGE) + 64
    )
    assert tunnel["user"] == "65532:65532"
    assert set(tunnel["networks"]) == {"beacon-proxy", "egress"}
    assert tunnel["networks"]["beacon-proxy"]["ipv4_address"] == "10.203.66.2"
    assert all(v["read_only"] is True for v in tunnel["volumes"])
    assert "--no-autoupdate" in tunnel["command"]
    networks = yaml.safe_load(INGRESS_COMPOSE.read_text(encoding="utf-8"))["networks"]
    assert networks["beacon-proxy"] == {"external": True}


def test_tunnel_ingress_targets_the_app_ip_and_keeps_the_public_host() -> None:
    config = yaml.safe_load((PROD / "cloudflared-config.yml.example").read_text(encoding="utf-8"))
    first, last = config["ingress"][0], config["ingress"][-1]
    assert first["service"] == "http://10.203.66.3:3366"
    assert "httpHostHeader" not in first.get("originRequest", {})
    assert last == {"service": "http_status:404"}


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")
def test_compose_files_render(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "BEACON_IMAGE": _GOOD_PINS["image"],
        "BEACON_PUBLIC_HOST": "beacon.archolith.dev",
        "BEACON_BUNDLE_DIR": str(tmp_path),
    }
    for path in (APP_COMPOSE, INGRESS_COMPOSE):
        probe = subprocess.run(["docker", "compose", "version"], capture_output=True, env=env)
        if probe.returncode != 0:
            pytest.skip("docker compose unavailable")
        done = subprocess.run(
            ["docker", "compose", "-f", str(path), "config", "-q"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert done.returncode == 0, done.stderr


# -- pins ------------------------------------------------------------------------------


def test_valid_pins_become_shell_assignments(pins: Any) -> None:
    flat = pins.validate(json.loads(json.dumps(_GOOD_PINS)))
    assert flat["PIN_STEM"] == _STEM and flat["PIN_COMMIT"] == _COMMIT
    assert flat["PIN_PUBLIC_HOST"] == "beacon.archolith.dev"


def _mutated(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    data = json.loads(json.dumps(_GOOD_PINS))
    target = data
    for key in path[:-1]:
        target = target[key]
    if value is _DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data


_DELETE = object()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("pins_version",), 2),
        (("image",), "ghcr.io/archolith/beacon:latest"),
        (("image",), "ghcr.io/evil/beacon@sha256:" + "a" * 64),
        (("image",), "docker.io/archolith/beacon@sha256:" + "a" * 64),
        (("public_host",), "localhost"),
        (("public_host",), "beacon.archolith.dev; rm -rf /"),
        (("bundle", "name"), "Beacon"),
        (("bundle", "commit"), "abc"),
        (("bundle", "sha256"), "B" * 64),
        (
            ("bundle", "url"),
            f"http://github.com/Archolith/beacon/releases/download/{_STEM}/{_STEM}.tar.gz",
        ),
        (
            ("bundle", "url"),
            f"https://github.com/evil/beacon/releases/download/{_STEM}/{_STEM}.tar.gz",
        ),
        (
            ("bundle", "url"),
            "https://github.com/Archolith/beacon/releases/download/"
            "beacon-demo-beacon-ffffffffffff/beacon-demo-beacon-ffffffffffff.tar.gz",
        ),
        (("bundle", "extra"), "x"),
        (("bundle", "sha256"), _DELETE),
        (("unexpected",), "x"),
    ],
)
def test_bad_pins_are_refused(pins: Any, path: tuple[str, ...], value: Any) -> None:
    with pytest.raises(pins.PinsError):
        pins.validate(_mutated(path, value))


def test_example_pins_are_placeholders_and_refused(pins: Any) -> None:
    example = json.loads((PROD / "pins.example.json").read_text(encoding="utf-8"))
    with pytest.raises(pins.PinsError):
        pins.validate(example)


def test_committed_pins_are_valid(pins: Any) -> None:
    path = PROD / "pins.json"
    if not path.exists():
        pytest.skip("no production pins committed yet")
    flat = pins.validate(json.loads(path.read_text(encoding="utf-8")))
    assert flat["PIN_PUBLIC_HOST"] == "beacon.archolith.dev"


def test_pins_cli_quotes_values(
    pins: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "pins.json"
    path.write_text(json.dumps(_GOOD_PINS), encoding="utf-8")
    assert pins.main(["pins.py", str(path)]) == 0
    out = capsys.readouterr().out
    assert f"PIN_STEM={_STEM}\n" in out and "PIN_IMAGE=" in out
    path.write_text("{}", encoding="utf-8")
    assert pins.main(["pins.py", str(path)]) == 2


# -- deploy.sh -------------------------------------------------------------------------


def _line(text: str, needle: str) -> int:
    for number, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return number
    raise AssertionError(f"not found in deploy.sh: {needle!r}")


def test_deploy_script_verifies_before_switching_and_rolls_back_after() -> None:
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    pins = _line(text, 'python3 "$HERE/pins.py"')
    download = _line(text, "curl -fsSL --proto '=https'")
    sha = _line(text, "sha256sum --strict -c -")
    members = _line(text, "unsafe member path")
    extract = _line(text, "tar -xzf")
    pull = _line(text, 'docker pull --quiet "$PIN_IMAGE"')
    switch = _line(text, 'switch_current "$PIN_STEM"')
    recreate = _line(text, "up -d --force-recreate --no-build beacon || rollback")
    assert pins < download < sha < members < extract < pull < switch < recreate
    # Every check after the switch rolls back on failure.
    for message in (
        "not healthy within",
        "discovery does not report the pinned commit",
        "public discovery unreachable",
        "public discovery does not report the pinned commit",
    ):
        assert f'rollback "{message}' in text, message
    assert "--max-filesize" in text and 'sudo -n -u "$CONTENT_USER"' in text


@pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt",
    reason="needs a POSIX bash (Windows may resolve bash to the WSL launcher)",
)
def test_deploy_script_parses() -> None:
    done = subprocess.run(["bash", "-n", "deploy.sh"], cwd=PROD, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
