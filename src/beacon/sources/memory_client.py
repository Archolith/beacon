"""Fetch memory evidence from a provider over MCP (streamable HTTP).

The provider contract is one read-only tool, :data:`EVIDENCE_TOOL`, called
with ``{"project_id": ...}``. It returns one text content item holding a
``beacon-memory-evidence-1.1`` document. Beacon never writes to a provider and
never sends it a local path.

Every failure maps to one stable code and nothing is written:

* ``memory_unavailable`` -- the provider could not be reached or timed out;
* ``memory_unauthorized`` -- the credential was missing or rejected (401/403);
* ``memory_invalid`` -- the provider answered, but not with usable evidence.

There is no retry, no cache and no fallback: a configured provider that fails
refuses the build (plan: provider states).
"""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlsplit

import httpx

EVIDENCE_TOOL = "get_beacon_evidence"
#: Environment variable holding the provider credential (sent as a bearer
#: header, never in the URL, never logged). Bandit B105 misreads the name.
TOKEN_ENV = "BEACON_MEMORY_TOKEN"  # nosec B105
DEFAULT_TIMEOUT_S = 30.0

MEMORY_UNAVAILABLE = "memory_unavailable"
MEMORY_UNAUTHORIZED = "memory_unauthorized"
MEMORY_INVALID = "memory_invalid"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class MemoryProviderError(RuntimeError):
    """A configured provider could not supply evidence. ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def check_provider_url(url: str) -> None:
    """Refuse URLs that would send a credential in clear or carry one in the URL."""
    parts = urlsplit(url)
    if parts.username or parts.password or parts.query:
        raise MemoryProviderError(
            MEMORY_INVALID, "the provider URL must not carry credentials or a query string"
        )
    if parts.scheme == "https":
        return
    if parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK_HOSTS:
        return
    raise MemoryProviderError(
        MEMORY_INVALID, "the provider URL must be https (plain http only for loopback)"
    )


def fetch_evidence(
    url: str,
    project_id: str,
    *,
    token: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> bytes:
    """Return the evidence document bytes for *project_id*, or raise."""
    check_provider_url(url)
    credential = token if token is not None else os.environ.get(TOKEN_ENV) or None
    if not credential and urlsplit(url).scheme == "https":
        # A loopback development provider may run without auth; a remote one may not.
        raise MemoryProviderError(
            MEMORY_UNAUTHORIZED, f"no credential: set {TOKEN_ENV} for a remote memory provider"
        )
    try:
        return asyncio.run(
            asyncio.wait_for(_fetch(url, project_id, credential, timeout_s), timeout_s)
        )
    except MemoryProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified below, never re-raised raw
        raise _classify(exc) from exc


async def _fetch(url: str, project_id: str, token: str | None, timeout_s: float) -> bytes:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import TextContent

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with (
        httpx.AsyncClient(headers=headers, timeout=timeout_s) as http,
        streamable_http_client(url, http_client=http) as streams,
    ):
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(EVIDENCE_TOOL, {"project_id": project_id})
    if result.isError:
        raise MemoryProviderError(MEMORY_INVALID, "the provider refused the evidence request")
    texts = [item.text for item in result.content if isinstance(item, TextContent)]
    if len(texts) != 1:
        raise MemoryProviderError(
            MEMORY_INVALID, "the provider must return exactly one text evidence document"
        )
    return texts[0].encode("utf-8")


def _classify(exc: BaseException) -> MemoryProviderError:
    """Map a transport failure to a stable code without echoing its text."""
    for inner in _leaves(exc):
        if isinstance(inner, MemoryProviderError):
            return inner
        if isinstance(inner, httpx.HTTPStatusError):
            if inner.response.status_code in (401, 403):
                return MemoryProviderError(
                    MEMORY_UNAUTHORIZED, "the provider rejected the credential"
                )
            return MemoryProviderError(
                MEMORY_UNAVAILABLE, f"the provider answered HTTP {inner.response.status_code}"
            )
        if isinstance(inner, (httpx.TransportError, TimeoutError, OSError)):
            return MemoryProviderError(MEMORY_UNAVAILABLE, "the provider could not be reached")
    return MemoryProviderError(MEMORY_INVALID, "the provider did not return usable evidence")


def _leaves(exc: BaseException) -> list[BaseException]:
    """Flatten exception groups (anyio task groups raise them) and causes."""
    found: list[BaseException] = []
    stack = [exc]
    while stack:
        current = stack.pop()
        if isinstance(current, BaseExceptionGroup):
            stack.extend(current.exceptions)
            continue
        found.append(current)
        if current.__cause__ is not None:
            stack.append(current.__cause__)
    return found


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "EVIDENCE_TOOL",
    "MEMORY_INVALID",
    "MEMORY_UNAUTHORIZED",
    "MEMORY_UNAVAILABLE",
    "MemoryProviderError",
    "TOKEN_ENV",
    "check_provider_url",
    "fetch_evidence",
]
