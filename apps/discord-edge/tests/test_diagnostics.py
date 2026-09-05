"""Deterministic coverage for opt-in Discord HTTP diagnostics."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import discord
import pytest
from aiohttp.tracing import TraceRequestEndParams, TraceRequestStartParams
from multidict import CIMultiDict
from yarl import URL

from lilavel_discord_edge import (
    DiscordDiagnostics,
    DiscordMessageSink,
    DiscordTextEdge,
    RateLimitObservation,
    ReplyPresenter,
    TransportMetrics,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.edits: list[str] = []

    async def edit(self, **kwargs: Any) -> FakeMessage:
        self.content = cast(str, kwargs["content"])
        self.edits.append(self.content)
        return self


class FakeChannel:
    def __init__(self) -> None:
        self.messages: list[FakeMessage] = []

    async def send(self, **kwargs: Any) -> FakeMessage:
        message = FakeMessage(cast(str, kwargs["content"]))
        self.messages.append(message)
        return message


async def emit_http_response(
    diagnostics: DiscordDiagnostics,
    clock: FakeClock,
    *,
    method: str,
    url: str,
    response_at: float,
    status: int,
    response_headers: dict[str, str],
    request_headers: dict[str, str] | None = None,
) -> None:
    trace = diagnostics.trace_config
    context = trace.trace_config_ctx()
    await trace.on_request_start.send(
        cast(Any, None),
        context,
        TraceRequestStartParams(
            method,
            URL(url),
            CIMultiDict(request_headers or {}),
        ),
    )
    clock.value = response_at
    response = SimpleNamespace(status=status, headers=CIMultiDict(response_headers))
    await trace.on_request_end.send(
        cast(Any, None),
        context,
        TraceRequestEndParams(method, URL(url), CIMultiDict(), cast(Any, response)),
    )


def test_disabled_instrumentation_preserves_existing_sink_behavior() -> None:
    async def scenario() -> None:
        channel = FakeChannel()
        metrics = TransportMetrics()
        sink = DiscordMessageSink(cast(Any, channel), metrics=metrics)

        message = await sink.create("first")
        await sink.edit(message, "second")

        assert channel.messages[0].content == "second"
        assert metrics.send_latencies_s and metrics.edit_latencies_s

    asyncio.run(scenario())


def test_enabled_diagnostics_use_discord_pys_supported_http_trace_constructor_hook() -> None:
    diagnostics = DiscordDiagnostics()
    edge = DiscordTextEdge(diagnostics=diagnostics)
    assert edge.client.http.http_trace is diagnostics.trace_config


def test_enabled_trace_records_safe_post_patch_headers_and_post_response_gap() -> None:
    async def scenario() -> list[dict[str, object]]:
        clock = FakeClock()
        emitted: list[dict[str, object]] = []
        diagnostics = DiscordDiagnostics(
            clock=clock,
            emit=lambda event: emitted.append(dict(event)),
        )
        diagnostics.trace_config.freeze()

        with diagnostics.operation("POST message"):
            clock.value = 0.10
            await emit_http_response(
                diagnostics,
                clock,
                method="POST",
                url="https://discord.com/api/v10/channels/channel-123/messages",
                response_at=0.35,
                status=200,
                response_headers={
                    "X-RateLimit-Limit": "5",
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset-After": "1.25",
                    "X-RateLimit-Bucket": "bucket-secret-value",
                    "Retry-After": "0.75",
                },
                request_headers={
                    "Authorization": "Bot token-secret-value",
                    "X-Request-Body": "message-content-secret-value",
                },
            )
            clock.value = 0.90

        with diagnostics.operation("PATCH message"):
            clock.value = 1.00
            await emit_http_response(
                diagnostics,
                clock,
                method="PATCH",
                url="https://discord.com/api/v10/channels/channel-123/messages/message-456",
                response_at=1.20,
                status=429,
                response_headers={"Retry-After": "2.5"},
            )
            clock.value = 1.25

        assert emitted == diagnostics.events
        return diagnostics.events

    events = asyncio.run(scenario())
    responses = [event for event in events if event["kind"] == "http_response"]
    assert [event["operation"] for event in responses] == ["POST message", "PATCH message"]
    assert responses[0]["response_status"] == 200
    assert responses[0]["rate_limit_limit"] == 5
    assert responses[0]["rate_limit_remaining"] == 0
    assert responses[0]["rate_limit_reset_after_s"] == 1.25
    assert responses[0]["retry_after_s"] == 0.75
    assert isinstance(responses[0]["rate_limit_bucket_hash"], str)
    assert responses[1]["response_status"] == 429
    assert responses[1]["rate_limited"] is True
    assert responses[1]["retry_after_s"] == 2.5

    operation_returns = [event for event in events if event["kind"] == "operation_return"]
    assert operation_returns[0]["await_duration_s"] == pytest.approx(0.9)
    assert operation_returns[0]["post_response_gap_s"] == pytest.approx(0.55)
    assert operation_returns[1]["post_response_gap_s"] == pytest.approx(0.05)

    serialized = json.dumps(events, sort_keys=True)
    assert "token-secret-value" not in serialized
    assert "message-content-secret-value" not in serialized
    assert "https://discord.com" not in serialized
    assert "bucket-secret-value" not in serialized


def test_absent_and_invalid_rate_limit_headers_are_safe() -> None:
    async def scenario() -> list[dict[str, object]]:
        clock = FakeClock()
        diagnostics = DiscordDiagnostics(clock=clock)
        diagnostics.trace_config.freeze()
        await emit_http_response(
            diagnostics,
            clock,
            method="PATCH",
            url="https://discord.com/api/v10/channels/c/messages/m",
            response_at=0.1,
            status=204,
            response_headers={
                "X-RateLimit-Limit": "not-an-int",
                "X-RateLimit-Remaining": "",
                "X-RateLimit-Reset-After": "nan",
                "Retry-After": "not-a-number",
            },
        )
        return diagnostics.events

    response = next(event for event in asyncio.run(scenario()) if event["kind"] == "http_response")
    assert response["rate_limit_limit"] is None
    assert response["rate_limit_remaining"] is None
    assert response["rate_limit_reset_after_s"] is None
    assert response["rate_limit_bucket_hash"] is None
    assert response["retry_after_s"] is None


def test_presenter_flushes_correlate_without_duplicate_edits_or_concurrency_changes() -> None:
    async def scenario() -> tuple[list[dict[str, object]], FakeChannel]:
        clock = FakeClock()
        diagnostics = DiscordDiagnostics(clock=clock)
        channel = FakeChannel()
        presenter = ReplyPresenter(
            DiscordMessageSink(
                cast(Any, channel),
                diagnostics=diagnostics,
                clock=clock,
            ),
            edit_interval_s=0.2,
            clock=clock,
            diagnostics=diagnostics,
        )

        presenter.append_delta("a")
        assert await presenter.flush(force=True)
        presenter.append_delta("b")
        assert await presenter.flush(force=True)
        presenter.append_delta("c")
        await presenter.complete(presenter.text)
        await presenter.shutdown()
        return diagnostics.events, channel

    events, channel = asyncio.run(scenario())
    assert len(channel.messages) == 1
    assert channel.messages[0].edits == ["ab", "abc"]

    flush_starts = [event for event in events if event["kind"] == "presenter_flush_start"]
    flush_returns = [event for event in events if event["kind"] == "presenter_flush_return"]
    operation_starts = [event for event in events if event["kind"] == "operation_start"]
    operation_returns = [event for event in events if event["kind"] == "operation_return"]
    assert len(flush_starts) == len(flush_returns) == 3
    assert [event["operation"] for event in operation_starts] == [
        "POST message",
        "PATCH message",
        "PATCH message",
    ]
    assert [event["presenter_flush_id"] for event in operation_starts] == [
        flush_starts[0]["flush_id"],
        flush_starts[1]["flush_id"],
        flush_starts[2]["flush_id"],
    ]
    assert all(event["outcome"] == "returned" for event in operation_returns)
    assert all(event["http_response_count"] == 0 for event in operation_returns)


def test_429_is_observed_without_swallowing_existing_sink_exception() -> None:
    async def scenario() -> tuple[list[dict[str, object]], list[RateLimitObservation]]:
        clock = FakeClock()
        diagnostics = DiscordDiagnostics(clock=clock)
        metrics = TransportMetrics()
        response = SimpleNamespace(
            status=429,
            reason="Too Many Requests",
            headers={"Retry-After": "1.5"},
        )
        error = discord.HTTPException(cast(Any, response), {"retry_after": 1.5})

        class FailingMessage:
            async def edit(self, **kwargs: Any) -> Any:
                del kwargs
                raise error

        sink = DiscordMessageSink(
            cast(Any, SimpleNamespace()),
            metrics=metrics,
            diagnostics=diagnostics,
            clock=clock,
        )
        try:
            await sink.edit(FailingMessage(), "not recorded")
        except discord.HTTPException as raised:
            assert raised is error
        else:
            raise AssertionError("expected discord.HTTPException")
        return diagnostics.events, list(metrics.rate_limits)

    events, rate_limits = asyncio.run(scenario())
    assert [event["kind"] for event in events] == ["operation_start", "operation_return"]
    assert events[-1]["outcome"] == "raised"
    assert len(rate_limits) == 1
    assert rate_limits[0].operation == "edit"
    assert rate_limits[0].retry_after_s == 1.5
