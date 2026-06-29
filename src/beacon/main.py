"""Beacon MCP stdio entry point.

Invoked via ``python -m beacon`` or the ``beacon`` console script.
"""

from __future__ import annotations

import logging
import os
import sys


def _configure_logging(*, include_console: bool = False) -> None:
    level = os.environ.get("BEACON_LOG_LEVEL", "WARNING").upper()
    handlers: list[logging.Handler] = []
    if include_console:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        handlers=handlers or None,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(os.getenv("ENV_FILE") or None)

    _configure_logging(include_console=False)

    from cth_mcp_framework import run_server
    from beacon.mcp.server import mcp

    print(
        f"[beacon] MCP stdio starting (pid={os.getpid()})",
        file=sys.stderr,
        flush=True,
    )
    run_server(mcp)


if __name__ == "__main__":
    main()
