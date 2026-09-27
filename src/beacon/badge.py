"""README badge for a served beacon: shields.io endpoint JSON and a self-rendered SVG.

Both render the same state from facts the server captured at startup: the served commit, its
committer time and the MCP tool count. Nothing comes from the request, so a badge cannot echo
attacker-controlled text. Age is the only value computed per request, and only from the clock.

States: ``live · <commit7> · <n> tools`` in green while the served commit is at most
:data:`STALE_AFTER_DAYS` old; ``stale · <n> days`` in amber after that; ``live`` in green
when no commit was observed (a working tree without git evidence).
"""

from __future__ import annotations

from dataclasses import dataclass

#: A served commit older than this reads as stale.
STALE_AFTER_DAYS = 30

#: shields.io named colors and the hex values the SVG uses for them.
GREEN = ("brightgreen", "#44cc11")
AMBER = ("yellow", "#dfb317")
LABEL_HEX = "#555"
LABEL = "beacon"
CACHE_SECONDS = 3600

# Verdana 11px advance widths (px) for printable ASCII, as shields.io measures badge text.
_WIDTHS = {
    " ": 3.87,
    "·": 4.58,
    "-": 4.78,
    ".": 3.87,
    "0": 7.0,
    "1": 7.0,
    "2": 7.0,
    "3": 7.0,
    "4": 7.0,
    "5": 7.0,
    "6": 7.0,
    "7": 7.0,
    "8": 7.0,
    "9": 7.0,
    "a": 6.61,
    "b": 6.86,
    "c": 5.72,
    "d": 6.86,
    "e": 6.61,
    "f": 3.86,
    "g": 6.86,
    "h": 6.96,
    "i": 3.02,
    "j": 3.79,
    "k": 6.51,
    "l": 3.02,
    "m": 10.7,
    "n": 6.96,
    "o": 6.68,
    "p": 6.86,
    "q": 6.86,
    "r": 4.69,
    "s": 5.74,
    "t": 4.33,
    "u": 6.96,
    "v": 6.51,
    "w": 8.95,
    "x": 6.51,
    "y": 6.51,
    "z": 5.78,
}


@dataclass(frozen=True)
class BadgeState:
    message: str
    color_name: str
    color_hex: str


def badge_state(
    *, commit: str, commit_time: int | None, tools: int | None, now: float
) -> BadgeState:
    """The badge's message and color for a served beacon at time *now* (Unix seconds)."""
    if commit and commit_time is not None:
        age_days = max(0, int((now - commit_time) // 86400))
        if age_days > STALE_AFTER_DAYS:
            return BadgeState(f"stale · {age_days} days", *AMBER)
    parts = ["live"]
    if commit:
        parts.append(commit[:7])
    if tools:
        parts.append(f"{tools} tools")
    return BadgeState(" · ".join(parts), *GREEN)


def endpoint_payload(state: BadgeState) -> dict[str, object]:
    """shields.io endpoint schema v1 (https://shields.io/badges/endpoint-badge)."""
    return {
        "schemaVersion": 1,
        "label": LABEL,
        "message": state.message,
        "color": state.color_name,
        "cacheSeconds": CACHE_SECONDS,
    }


def _text_width(text: str) -> int:
    return round(sum(_WIDTHS.get(ch, 7.0) for ch in text))


def render_svg(state: BadgeState) -> bytes:
    """A shields-style "flat" badge. Text is escaped even though it is never request input."""
    label_w = _text_width(LABEL) + 10 + 17  # text padding plus the beacon glyph
    message_w = _text_width(state.message) + 10
    width = label_w + message_w
    label_x = 17 + (label_w - 17) / 2
    message_x = label_w + message_w / 2
    message = _escape(state.message)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" '
        f'aria-label="{LABEL}: {message}"><title>{LABEL}: {message}</title>'
        '<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" '
        'stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<clipPath id="r"><rect width="{width}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)"><rect width="{label_w}" height="20" fill="{LABEL_HEX}"/>'
        f'<rect x="{label_w}" width="{message_w}" height="20" fill="{state.color_hex}"/>'
        f'<rect width="{width}" height="20" fill="url(#s)"/></g>'
        '<g fill="#fff" transform="translate(4,0)"><circle cx="7" cy="10" r="2.2"/>'
        '<path d="M7 3.2 7.8 6.2 6.2 6.2Z M13.2 10 10.4 10.8 10.4 9.2Z M0.8 10 3.6 9.2 3.6 10.8Z '
        'M11.4 5.6 9.7 7.8 8.9 7Z M2.6 5.6 5.1 7 4.3 7.8Z"/></g>'
        '<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" '
        'font-size="11">'
        f'<text x="{label_x}" y="15" fill="#010101" fill-opacity=".3">{LABEL}</text>'
        f'<text x="{label_x}" y="14">{LABEL}</text>'
        f'<text x="{message_x}" y="15" fill="#010101" fill-opacity=".3">{message}</text>'
        f'<text x="{message_x}" y="14">{message}</text></g></svg>'
    )
    return svg.encode("utf-8")


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
