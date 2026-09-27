"""Invariants of the image-release and demo-bundle workflows.

Both workflows can publish (GHCR image, GitHub Release asset), so their shape is pinned here:
publication only behind an explicit gate, least-privilege permissions per job, verification of
the sealed artifact before any credential or publish step, and SHA/digest-pinned tooling.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
_SHA_PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
_DIGEST_PINNED = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")


def _load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on` as boolean True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def _index(steps: list[dict[str, Any]], predicate: Any) -> int:
    for position, step in enumerate(steps):
        if predicate(step):
            return position
    raise AssertionError("expected workflow step not found")


def _run(step: dict[str, Any]) -> str:
    return str(step.get("run", ""))


def _uses(step: dict[str, Any]) -> str:
    return str(step.get("uses", ""))


# -- release-image.yml -----------------------------------------------------------------


def test_release_image_actions_and_scanners_are_pinned() -> None:
    workflow = _load("release-image.yml")
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert _SHA_PINNED.match(step["uses"]), step["uses"]
    assert _DIGEST_PINNED.match(workflow["env"]["SYFT_IMAGE"])
    assert _DIGEST_PINNED.match(workflow["env"]["GRYPE_IMAGE"])


def test_release_image_validation_holds_no_publish_rights() -> None:
    workflow = _load("release-image.yml")
    assert workflow["permissions"] == {"contents": "read"}
    validate = workflow["jobs"]["validate"]
    assert "permissions" not in validate  # inherits contents: read only
    steps = validate["steps"]
    assert not any("login" in _uses(step) for step in steps)
    assert not any("docker push" in _run(step) for step in steps)
    scan = _index(steps, lambda s: "GRYPE_IMAGE" in _run(s))
    assert "--fail-on critical" in _run(steps[scan])
    seal = _index(steps, lambda s: "docker save" in _run(s))
    upload = _index(steps, lambda s: "upload-artifact" in _uses(s))
    assert seal < scan < upload


def test_release_image_publishes_only_on_explicit_master_dispatch() -> None:
    workflow = _load("release-image.yml")
    publish = workflow["jobs"]["publish"]
    gate = publish["if"]
    for required in ("workflow_dispatch", "inputs.push", "refs/heads/master"):
        assert required in gate, required
    assert workflow["on"]["workflow_dispatch"]["inputs"]["push"]["default"] is False
    assert publish["environment"]["name"] == "beacon-release-image"
    assert publish["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "attestations": "write",
    }
    assert publish["needs"] == "validate"


def test_release_image_verifies_the_sealed_candidate_before_login_and_push() -> None:
    steps = _load("release-image.yml")["jobs"]["publish"]["steps"]
    download = _index(steps, lambda s: "download-artifact" in _uses(s))
    verify = _index(
        steps,
        lambda s: "sha256sum --strict -c SHA256SUMS" in _run(s) and "IMAGE_ID" in _run(s),
    )
    login = _index(steps, lambda s: "docker/login-action" in _uses(s))
    push = _index(steps, lambda s: "docker push" in _run(s))
    attest = _index(steps, lambda s: "attest-build-provenance" in _uses(s))
    assert download < verify < login < push < attest


# -- demo-bundle.yml -------------------------------------------------------------------


def test_demo_bundle_actions_are_pinned_and_build_is_read_only() -> None:
    workflow = _load("demo-bundle.yml")
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert _SHA_PINNED.match(step["uses"]), step["uses"]
    build = workflow["jobs"]["build"]
    assert "permissions" not in build
    assert not any("gh release" in _run(step) for step in build["steps"])


def test_demo_bundle_validates_inputs_before_using_them() -> None:
    steps = _load("demo-bundle.yml")["jobs"]["build"]["steps"]
    validate = _index(steps, lambda s: s.get("name") == "Validate inputs")
    bundle = _index(steps, lambda s: "build_demo_bundle.py" in _run(s))
    assert validate == 0 and validate < bundle
    text = _run(steps[validate])
    assert "^[0-9a-f]{40}$" in text and "^[a-z0-9][a-z0-9-]{0,62}$" in text
    # Inputs reach shell only through env, never interpolated into the script body.
    for step in steps:
        assert "${{ inputs." not in _run(step), step.get("name")


def test_demo_bundle_publishes_only_when_asked_and_only_to_the_caller() -> None:
    workflow = _load("demo-bundle.yml")
    for trigger in ("workflow_call", "workflow_dispatch"):
        assert workflow["on"][trigger]["inputs"]["publish"]["default"] is False
    publish = workflow["jobs"]["publish"]
    assert publish["if"] == "${{ inputs.publish }}"
    assert publish["permissions"] == {"contents": "write"}
    steps = publish["steps"]
    verify = _index(steps, lambda s: "sha256sum --strict -c" in _run(s))
    release = _index(steps, lambda s: "gh release create" in _run(s))
    assert verify < release
    assert '--repo "$GITHUB_REPOSITORY"' in _run(steps[release])
    for step in steps:
        assert "${{ inputs." not in _run(step), step.get("name")
