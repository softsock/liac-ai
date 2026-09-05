"""Live-free-by-default Discord transport probe."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import discord

from .edge import make_dm_intents, read_discord_token
from .presenter import ReplyPresenter
from .transport import DiscordMessageSink, TransportMetrics

_PROBE_TIMEOUT_S = 180.0
_INITIAL_TEXT = "Lilavel Discord transport probe: @everyone and <@123456789> must stay inert."
_COALESCED_PARTS = (
    " coalesced-1",
    " coalesced-2",
    " coalesced-3",
    " coalesced-4",
)
_LONG_PART = " continuation-block-0123456789" * 100


class _LiveTransportProbe:
    def __init__(self) -> None:
        self.client = discord.Client(intents=make_dm_intents())
        self.started_at = time.perf_counter()
        self.ready_at: float | None = None
        self.received_at: float | None = None
        self.typing_entered_at: float | None = None
        self.result: dict[str, Any] | None = None
        self.resumed_count = 0
        self.disconnect_count = 0
        self._register_handlers()

    async def run(self, token: str) -> dict[str, Any]:
        try:
            await self.client.start(token, reconnect=True)
        except BaseException as error:
            if self.result is None:
                self.result = {
                    "status": "FAIL",
                    "error_type": type(error).__name__,
                }
        finally:
            if not self.client.is_closed():
                await self.client.close()
        return self.result or {"status": "FAIL", "error_type": "probe_ended_without_result"}

    def _register_handlers(self) -> None:
        self.client.event(self.on_ready)
        self.client.event(self.on_resumed)
        self.client.event(self.on_disconnect)
        self.client.event(self.on_message)

    async def on_ready(self) -> None:
        self.ready_at = time.perf_counter()

    async def on_resumed(self) -> None:
        self.resumed_count += 1

    async def on_disconnect(self) -> None:
        self.disconnect_count += 1

    async def on_message(self, message: discord.Message) -> None:
        if self.result is not None or not isinstance(message.channel, discord.DMChannel):
            return
        if message.author.bot:
            return
        if self.client.user is not None and message.author.id == self.client.user.id:
            return
        await self._exercise(message)

    async def _exercise(self, message: discord.Message) -> None:
        received_at = time.perf_counter()
        self.received_at = received_at
        metrics = TransportMetrics()
        presenter = ReplyPresenter(
            DiscordMessageSink(message.channel, metrics=metrics),
            edit_interval_s=60.0,
        )
        async with message.channel.typing():
            typing_entered_at = time.perf_counter()
            self.typing_entered_at = typing_entered_at
            presenter.append_delta(_INITIAL_TEXT)
            first_flush_started = time.perf_counter()
            await presenter.flush(force=True)
            first_visible_at = time.perf_counter()
            for part in _COALESCED_PARTS:
                presenter.append_delta(part)
            await presenter.flush(force=True)
            presenter.append_delta(_LONG_PART)
            await presenter.flush(force=True)
            await presenter.complete(presenter.text)

        now = time.perf_counter()
        self.result = {
            "status": "PASS",
            "dependency": discord.__version__,
            "intents_value": self.client.intents.value,
            "ready_observed": self.ready_at is not None,
            "ready_after_start_s": (
                None if self.ready_at is None else self.ready_at - self.started_at
            ),
            "received_dm": True,
            "typing_context_entered": True,
            "typing_context_latency_s": (typing_entered_at - received_at),
            "first_visible_content_s": first_visible_at - received_at,
            "first_send_operation_s": first_visible_at - first_flush_started,
            "synthetic_delta_count": len(_COALESCED_PARTS) + 2,
            "presenter_flush_count": presenter.flush_count,
            "terminal_flush_count": presenter.terminal_flush_count,
            "message_count": presenter.message_count,
            "max_published_chars": max(
                (len(chunk) for chunk in presenter.published_chunks), default=0
            ),
            "published_total_chars": len(presenter.text),
            "over_2000_continuation_exercised": len(presenter.text) > 2000
            and presenter.message_count > 1,
            "allowed_mentions_disabled": True,
            "send_latency_s": metrics.send_latencies_s,
            "edit_latency_s": metrics.edit_latencies_s,
            "surfaced_429": [
                {"operation": item.operation, "retry_after_s": item.retry_after_s}
                for item in metrics.rate_limits
            ],
            "reconnect_observed": self.resumed_count > 0,
            "disconnect_events_observed": self.disconnect_count,
            "shutdown_clean": False,
            "elapsed_s": now - self.started_at,
        }
        await self.client.close()
        self.result["shutdown_clean"] = self.client.is_closed()


async def run_transport_probe(
    *,
    token: str | None = None,
    timeout_s: float = _PROBE_TIMEOUT_S,
) -> dict[str, Any]:
    """Run Stage A, or return deterministic BLOCKED when the token is absent."""

    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    resolved = token or read_discord_token()
    if not resolved:
        return {
            "status": "BLOCKED",
            "reason": "missing LILAVEL_DISCORD_BOT_TOKEN",
            "live_probe": False,
        }
    probe = _LiveTransportProbe()
    try:
        return await asyncio.wait_for(probe.run(resolved), timeout_s)
    except TimeoutError:
        if not probe.client.is_closed():
            await probe.client.close()
        return {"status": "FAIL", "error_type": "probe_timeout"}
