"""P2 of near-zero authoring: project state from the code host. HTTP is always mocked."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from beacon.build import policy as policy_mod
from beacon.core.loader import parse_manifest
from beacon.main import app
from beacon.sources import forge as forge_mod
from beacon.sources.forge import ForgeError, ForgeFacts, collect_forge, github_slug

runner = CliRunner()
ORIGIN = "https://github.com/acme/widgets.git"
REPO_URL = "https://github.com/acme/widgets"


def _issue(number: int, title: str, *, pr: bool = False) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "number": number,
        "title": title,
        "html_url": f"{REPO_URL}/issues/{number}",
    }
    if pr:
        issue["pull_request"] = {"url": "x"}
    return issue


def _routes() -> dict[tuple[str, str], Any]:
    return {
        ("/milestones", ""): [
            {
                "title": "v1.0",
                "description": "First stable release.",
                "open_issues": 4,
                "due_on": "2026-10-01T00:00:00Z",
                "html_url": f"{REPO_URL}/milestone/1",
            },
            {"title": "v1.1", "html_url": f"{REPO_URL}/milestone/2"},
        ],
        ("/issues", "blocker"): [_issue(7, "Auth refresh breaks CI"), _issue(8, "A PR", pr=True)],
        ("/issues", "blocked"): [_issue(7, "Auth refresh breaks CI")],
        ("/issues", "decision"): [_issue(9, "Pick a license for the SDK")],
        ("/issues", "needs-decision"): [],
        ("/issues", "rfc"): [],
        ("/issues", "good first issue"): [
            _issue(11, "Fix a typo in the README"),
            _issue(12, "token ghp_abcdefghijklmnopqrstuvwxyz0123456789 leaked"),
        ],
        ("/releases", ""): [
            {
                "name": "v0.9",
                "tag_name": "v0.9",
                "published_at": "2026-09-01T00:00:00Z",
                "html_url": f"{REPO_URL}/releases/tag/v0.9",
            },
            {"name": "draft", "tag_name": "v1.0-rc", "draft": True},
        ],
    }


class _Recorder:
    def __init__(
        self,
        routes: dict[tuple[str, str], Any],
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.routes = routes
        self.status = status
        self.headers = headers or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, headers=self.headers, json={"message": "no"})
        path = request.url.path.removeprefix("/repos/acme/widgets")
        label = request.url.params.get("labels", "")
        return httpx.Response(200, json=self.routes.get((path, label), []))


def _collect(recorder: _Recorder, token: str | None = None) -> ForgeFacts:
    return collect_forge(ORIGIN, token=token, transport=httpx.MockTransport(recorder))


def test_github_slug_accepts_only_github_origins() -> None:
    assert github_slug("https://github.com/acme/widgets.git") == "acme/widgets"
    assert github_slug("https://github.com/acme/widgets") == "acme/widgets"
    assert github_slug("https://gitlab.com/acme/widgets") is None
    assert github_slug(None) is None


def test_collects_focus_state_tasks_and_releases_with_citations() -> None:
    recorder = _Recorder(_routes())
    facts = _collect(recorder, token="secret-token")

    assert facts.repository == "acme/widgets"
    assert facts.current_focus == ("v1.0", "v1.1")
    assert facts.active_work is not None
    assert facts.active_work["title"] == "v1.0"
    assert facts.active_work["next_step"] == "4 open issue(s); due 2026-10-01"
    # Deduplicated across labels, pull requests excluded.
    assert [b["title"] for b in facts.blockers] == ["Auth refresh breaks CI"]
    assert facts.blockers[0]["sources"][0]["url"] == f"{REPO_URL}/issues/7"
    assert [d["title"] for d in facts.pending_decisions] == ["Pick a license for the SDK"]
    # A title the secret detector flags is dropped.
    assert facts.safe_first_tasks == ("Fix a typo in the README",)
    # Drafts are not completed work.
    assert [r["title"] for r in facts.recently_completed] == ["Release v0.9"]
    assert facts.fields == {"current_focus", "agent_guidance.safe_first_tasks", "project_state"}
    # The token is only a header.
    assert all(r.headers["Authorization"] == "Bearer secret-token" for r in recorder.requests)
    assert len(recorder.requests) == 8  # milestones + 6 labels + releases, one page each


@pytest.mark.parametrize(
    ("status", "headers", "code"),
    [
        (
            403,
            {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000000"},
            forge_mod.FORGE_RATE_LIMITED,
        ),
        (429, {}, forge_mod.FORGE_RATE_LIMITED),
        (401, {}, forge_mod.FORGE_UNAUTHORIZED),
        (404, {}, forge_mod.FORGE_NOT_FOUND),
        (500, {}, forge_mod.FORGE_UNAVAILABLE),
    ],
)
def test_failures_stop_at_once_without_retrying(
    status: int, headers: dict[str, str], code: str
) -> None:
    recorder = _Recorder({}, status=status, headers=headers)
    with pytest.raises(ForgeError) as caught:
        _collect(recorder, token="secret-token")
    assert caught.value.code == code
    assert len(recorder.requests) == 1
    assert "secret-token" not in str(caught.value)


def test_unreachable_host_and_non_github_origin() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ForgeError) as down:
        collect_forge(ORIGIN, transport=httpx.MockTransport(refuse))
    assert down.value.code == forge_mod.FORGE_UNAVAILABLE
    with pytest.raises(ForgeError) as other:
        collect_forge("https://gitlab.com/acme/widgets", transport=httpx.MockTransport(refuse))
    assert other.value.code == forge_mod.FORGE_UNSUPPORTED


def test_token_env_order() -> None:
    assert forge_mod.forge_token({"GITHUB_TOKEN": "b", "BEACON_FORGE_TOKEN": "a"}) == "a"
    assert forge_mod.forge_token({"GITHUB_TOKEN": "b"}) == "b"
    assert forge_mod.forge_token({}) is None


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


def _facts(tmp_path: Path, intent: dict[str, Any] | None, forge: ForgeFacts):
    (tmp_path / "README.md").write_text("# W\n\nWidgets for every team.\n", encoding="utf-8")
    return policy_mod.resolve_project_facts(
        intent=parse_manifest(intent) if intent else None,
        git_records=(),
        docs_root=tmp_path,
        repo_root=tmp_path,
        strict=False,
        forge=forge,
    )


def test_forge_fills_what_intent_leaves_empty(tmp_path: Path) -> None:
    forge = _collect(_Recorder(_routes()))
    facts = _facts(
        tmp_path,
        {
            "beacon_version": "0.1",
            "project": {"name": "w"},
            "current_focus": ["the maintainers' own focus"],
            "project_state": {"blockers": [{"title": "Stated in beacon.yaml"}]},
        },
        forge,
    )
    assert facts.current_focus == ("the maintainers' own focus",)
    assert facts.field_authority["current_focus"] == "intent"
    assert facts.project_state is not None
    assert [b["title"] for b in facts.project_state["blockers"]] == ["Stated in beacon.yaml"]
    assert facts.project_state["active_work"]["title"] == "v1.0"
    assert facts.field_authority["project_state"] == "intent+forge"
    assert facts.agent_guidance["safe_first_tasks"] == ("Fix a typo in the README",)
    assert facts.field_authority["agent_guidance.safe_first_tasks"] == "forge"


def test_without_intent_the_forge_supplies_focus(tmp_path: Path) -> None:
    facts = _facts(tmp_path, None, _collect(_Recorder(_routes())))
    assert facts.current_focus == ("v1.0", "v1.1")
    assert facts.field_authority["current_focus"] == "forge"


# ---------------------------------------------------------------------------
# CLI: opt-in, never fatal
# ---------------------------------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    from tests.test_build_pipeline import _fixture_repo

    return _fixture_repo(tmp_path)


def test_build_forge_reports_what_it_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    facts = _collect(_Recorder(_routes()))
    monkeypatch.setattr(forge_mod, "collect_forge", lambda origin, token=None: facts)
    result = runner.invoke(
        app, ["build", "--repo", str(root), "--forge", "--format", "json", "--gaps-only"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    assert payload["forge"]["status"] == "ok"
    assert "project_state" in payload["forge"]["fields"]


def test_build_continues_when_the_forge_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)

    def fail(origin: Any, token: Any = None) -> ForgeFacts:
        raise ForgeError(forge_mod.FORGE_RATE_LIMITED, "the code host's rate limit is exhausted")

    monkeypatch.setattr(forge_mod, "collect_forge", fail)
    result = runner.invoke(app, ["build", "--repo", str(root), "--forge", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    assert payload["forge"] == {
        "status": "error",
        "code": "forge_rate_limited",
        "message": "the code host's rate limit is exhausted",
    }
    assert (root / "beacon.generated.yaml").is_file()


def test_build_without_forge_makes_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)

    def boom(*args: Any, **kwargs: Any) -> ForgeFacts:
        raise AssertionError("the forge must be opt-in")

    monkeypatch.setattr(forge_mod, "collect_forge", boom)
    result = runner.invoke(app, ["build", "--repo", str(root), "--format", "json", "--gaps-only"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["result"]["forge"] is None
