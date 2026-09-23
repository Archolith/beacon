"""The forge source: project state from the code host (GitHub), opt-in with ``--forge``.

What a project's maintainers track on their code host is its state: open milestones are
the current focus, issues labelled as blockers or decisions are exactly that, issues
labelled for newcomers are safe first tasks, and releases are recently completed work.
``beacon build --forge`` reads them through the host's API instead of asking maintainers
to copy them into ``beacon.yaml``, where they would go stale.

Rules:

* opt-in and bounded: a fixed, small number of requests (milestones, one issue query per
  label group, releases), one page each, a short timeout, and at most ``MAX_ITEMS`` items
  per field;
* read-only; the token (``BEACON_FORGE_TOKEN``, else ``GITHUB_TOKEN``) is only ever sent
  as a header and never appears in output, errors or files. Without one, public
  repositories still work within the host's anonymous rate limit;
* a rate limit, missing access or an unreachable host stops the forge source at once
  (no retries) and the build continues without it, reporting why;
* every item cites its issue, milestone or release URL; titles the secret detector flags
  are dropped.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import quote

import httpx

from beacon.core.security import detect_sensitive_text

TOKEN_ENV = ("BEACON_FORGE_TOKEN", "GITHUB_TOKEN")
API_URL = "https://api.github.com"
DEFAULT_TIMEOUT_S = 10.0
MAX_ITEMS = 5
_TITLE_CHARS = 200
_SUMMARY_CHARS = 300

#: Label groups: project-state field -> issue labels that mean it.
DEFAULT_LABELS: Mapping[str, tuple[str, ...]] = {
    "blockers": ("blocker", "blocked"),
    "pending_decisions": ("decision", "needs-decision", "rfc"),
    "safe_first_tasks": ("good first issue",),
}

FORGE_UNSUPPORTED = "forge_unsupported"
FORGE_RATE_LIMITED = "forge_rate_limited"
FORGE_UNAUTHORIZED = "forge_unauthorized"
FORGE_NOT_FOUND = "forge_not_found"
FORGE_UNAVAILABLE = "forge_unavailable"
FORGE_INVALID = "forge_invalid"

_GITHUB = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")


class ForgeError(Exception):
    """The forge source stopped; ``code`` is stable and carries no secret."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ForgeFacts:
    """Project state read from the code host. Items are project-state item mappings."""

    repository: str
    current_focus: tuple[str, ...] = ()
    active_work: dict[str, Any] | None = None
    blockers: tuple[dict[str, Any], ...] = ()
    pending_decisions: tuple[dict[str, Any], ...] = ()
    recently_completed: tuple[dict[str, Any], ...] = ()
    safe_first_tasks: tuple[str, ...] = ()
    fields: frozenset[str] = field(default_factory=frozenset)


def github_slug(origin: str | None) -> str | None:
    """``owner/repo`` for a sanitized GitHub origin URL, else None."""
    match = _GITHUB.match((origin or "").strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def forge_token(env: Mapping[str, str] | None = None) -> str | None:
    source = os.environ if env is None else env
    for name in TOKEN_ENV:
        value = (source.get(name) or "").strip()
        if value:
            return value
    return None


def collect_forge(
    origin: str | None,
    *,
    token: str | None = None,
    labels: Mapping[str, tuple[str, ...]] = DEFAULT_LABELS,
    transport: httpx.BaseTransport | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    api_url: str = API_URL,
) -> ForgeFacts:
    """Read project state for *origin* from GitHub. Raises :class:`ForgeError`."""
    slug = github_slug(origin)
    if slug is None:
        raise ForgeError(FORGE_UNSUPPORTED, "the forge source reads GitHub repositories only")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    base = f"{api_url.rstrip('/')}/repos/{slug}"
    with httpx.Client(headers=headers, timeout=timeout_s, transport=transport) as client:

        def get(path: str, params: dict[str, str]) -> list[dict[str, Any]]:
            try:
                response = client.get(f"{base}{path}", params=params)
            except httpx.HTTPError as exc:
                raise ForgeError(FORGE_UNAVAILABLE, "the code host could not be reached") from exc
            _raise_for_status(response)
            try:
                data = response.json()
            except ValueError as exc:
                raise ForgeError(FORGE_INVALID, "the code host returned invalid JSON") from exc
            if not isinstance(data, list):
                raise ForgeError(FORGE_INVALID, "the code host returned an unexpected shape")
            return [item for item in data if isinstance(item, dict)]

        milestones = get(
            "/milestones",
            {"state": "open", "sort": "due_on", "direction": "asc", "per_page": "10"},
        )
        grouped = {group: _issues(get, names) for group, names in labels.items() if names}
        releases = get("/releases", {"per_page": str(MAX_ITEMS)})

    focus = tuple(title for title in (_title(m.get("title")) for m in milestones) if title)[
        :MAX_ITEMS
    ]
    active = _milestone_item(milestones[0]) if milestones else None
    completed = tuple(
        item for item in (_release_item(r) for r in releases if not r.get("draft")) if item
    )[:MAX_ITEMS]
    safe = tuple(item["title"] for item in grouped.get("safe_first_tasks", ()))
    facts = ForgeFacts(
        repository=slug,
        current_focus=focus,
        active_work=active,
        blockers=tuple(grouped.get("blockers", ())),
        pending_decisions=tuple(grouped.get("pending_decisions", ())),
        recently_completed=completed,
        safe_first_tasks=safe,
    )
    supplied = {
        name
        for name, value in (
            ("current_focus", facts.current_focus),
            ("agent_guidance.safe_first_tasks", facts.safe_first_tasks),
            (
                "project_state",
                facts.active_work
                or facts.blockers
                or facts.pending_decisions
                or facts.recently_completed,
            ),
        )
        if value
    }
    return replace(facts, fields=frozenset(supplied))


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    remaining = response.headers.get("x-ratelimit-remaining")
    if status == 429 or (status == 403 and remaining == "0"):
        reset = response.headers.get("x-ratelimit-reset", "")
        raise ForgeError(
            FORGE_RATE_LIMITED,
            "the code host's rate limit is exhausted"
            + (f" (resets at epoch {reset})" if reset.isdigit() else "")
            + "; not retrying",
        )
    if status in (401, 403):
        raise ForgeError(FORGE_UNAUTHORIZED, "the code host refused access (check the token)")
    if status == 404:
        raise ForgeError(FORGE_NOT_FOUND, "the repository was not found on the code host")
    raise ForgeError(FORGE_UNAVAILABLE, f"the code host answered HTTP {status}")


def _issues(get: Any, names: tuple[str, ...]) -> list[dict[str, Any]]:
    """Open issues (never pull requests) carrying any of *names*, newest first, capped."""
    seen: dict[int, dict[str, Any]] = {}
    for name in names:
        for issue in get(
            "/issues",
            {"state": "open", "labels": name, "per_page": "10", "sort": "updated"},
        ):
            if "pull_request" in issue or not isinstance(issue.get("number"), int):
                continue
            item = _issue_item(issue)
            if item is not None:
                seen.setdefault(issue["number"], item)
        if len(seen) >= MAX_ITEMS:
            break
    return list(seen.values())[:MAX_ITEMS]


def _clean(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if not text or detect_sensitive_text(text):
        return ""
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _title(value: Any) -> str:
    return _clean(value, _TITLE_CHARS)


def _cite(kind: str, label: str, url: Any) -> list[dict[str, str]]:
    link = str(url or "")
    if not link.startswith("https://"):
        return []
    return [
        {"type": kind, "title": label, "url": quote(link, safe=":/?#=&%.-_~"), "status": "current"}
    ]


def _issue_item(issue: dict[str, Any]) -> dict[str, Any] | None:
    title = _title(issue.get("title"))
    if not title:
        return None
    return {
        "title": title,
        "sources": _cite("issue", f"#{issue['number']}", issue.get("html_url")),
    }


def _milestone_item(milestone: dict[str, Any]) -> dict[str, Any] | None:
    title = _title(milestone.get("title"))
    if not title:
        return None
    item: dict[str, Any] = {
        "title": title,
        "sources": _cite("issue", f"milestone {title}", milestone.get("html_url")),
    }
    summary = _clean(milestone.get("description"), _SUMMARY_CHARS)
    if summary:
        item["summary"] = summary
    open_issues = milestone.get("open_issues")
    if isinstance(open_issues, int):
        due = str(milestone.get("due_on") or "")[:10]
        item["next_step"] = f"{open_issues} open issue(s)" + (f"; due {due}" if due else "")
    return item


def _release_item(release: dict[str, Any]) -> dict[str, Any] | None:
    name = _title(release.get("name") or release.get("tag_name"))
    if not name:
        return None
    item: dict[str, Any] = {
        "title": f"Release {name}",
        "sources": _cite("commit", str(release.get("tag_name") or name), release.get("html_url")),
    }
    published = str(release.get("published_at") or "")[:10]
    if published:
        item["summary"] = f"Published {published}."
    return item


__all__ = [
    "DEFAULT_LABELS",
    "FORGE_INVALID",
    "FORGE_NOT_FOUND",
    "FORGE_RATE_LIMITED",
    "FORGE_UNAUTHORIZED",
    "FORGE_UNAVAILABLE",
    "FORGE_UNSUPPORTED",
    "ForgeError",
    "ForgeFacts",
    "collect_forge",
    "forge_token",
    "github_slug",
]
