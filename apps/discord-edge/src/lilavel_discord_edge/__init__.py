"""Replaceable DM-first Discord text edge for Lilavel."""

from .edge import (
    DISCORD_TOKEN_ENV,
    DiscordTextEdge,
    MissingDiscordToken,
    make_dm_intents,
    read_discord_token,
)
from .presenter import (
    FAILED_MARKER,
    INTERRUPTED_MARKER,
    NO_RESPONSE_MARKER,
    ReplyPresenter,
)
from .probe import run_transport_probe
from .transport import (
    MAX_DISCORD_MESSAGE_CHARS,
    DiscordMessageSink,
    RateLimitObservation,
    TransportMetrics,
    split_discord_content,
)

__all__ = [
    "DISCORD_TOKEN_ENV",
    "DiscordMessageSink",
    "DiscordTextEdge",
    "FAILED_MARKER",
    "INTERRUPTED_MARKER",
    "MAX_DISCORD_MESSAGE_CHARS",
    "MissingDiscordToken",
    "NO_RESPONSE_MARKER",
    "RateLimitObservation",
    "ReplyPresenter",
    "TransportMetrics",
    "make_dm_intents",
    "read_discord_token",
    "run_transport_probe",
    "split_discord_content",
]
