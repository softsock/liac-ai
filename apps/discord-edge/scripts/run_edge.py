"""Run the live DM-only Discord edge against the existing Core/runtime path."""

from __future__ import annotations

import asyncio

from lilavel_discord_edge import (
    DiscordTextEdge,
    MissingDiscordToken,
    diagnostics_from_environment,
)


async def main() -> int:
    edge = DiscordTextEdge(diagnostics=diagnostics_from_environment())
    try:
        await edge.start()
    except MissingDiscordToken:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
