"""Deterministic tests for coalescing and bounded Discord presentation."""

from __future__ import annotations

import asyncio
from typing import Any

from lilavel_discord_edge import (
    FAILED_MARKER,
    INTERRUPTED_MARKER,
    ReplyPresenter,
    split_discord_content,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def create(self, content: str) -> FakeMessage:
        self.calls.append(("create", content))
        return FakeMessage(content)

    async def edit(self, message: Any, content: str) -> FakeMessage:
        self.calls.append(("edit", content))
        message.content = content
        return message


def test_split_preserves_unicode_and_never_exceeds_limit() -> None:
    text = "é" * 2001 + "🙂"

    chunks = split_discord_content(text)

    assert "".join(chunks) == text
    assert len(chunks) == 2
    assert all(len(chunk) <= 2000 for chunk in chunks)


def test_bursty_deltas_are_coalesced_and_completion_flushes_once() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sink = FakeSink()
        presenter = ReplyPresenter(sink, edit_interval_s=1.0, clock=clock)

        presenter.append_delta("a")
        assert await presenter.flush()
        presenter.append_delta("b")
        presenter.append_delta("c")
        presenter.append_delta("d")
        assert not presenter.ready_to_flush()
        assert not await presenter.flush()

        clock.value = 1.0
        assert await presenter.flush()
        assert sink.calls == [("create", "a"), ("edit", "abcd")]

        await presenter.complete("abcd!")
        await presenter.complete("ignored")
        assert presenter.terminal_flush_count == 1
        assert presenter.finalized
        assert sink.calls == [("create", "a"), ("edit", "abcd"), ("edit", "abcd!")]

    asyncio.run(scenario())


def test_long_response_creates_safe_continuation_messages() -> None:
    async def scenario() -> None:
        sink = FakeSink()
        presenter = ReplyPresenter(sink, edit_interval_s=0.0)
        text = "x" * 4001

        presenter.append_delta(text)
        await presenter.complete(text)

        assert [kind for kind, _ in sink.calls] == ["create", "create", "create"]
        assert all(len(content) <= 2000 for _, content in sink.calls)
        assert "".join(content for _, content in sink.calls) == text
        assert presenter.published_chunks == ("x" * 2000, "x" * 2000, "x")

    asyncio.run(scenario())


def test_terminal_markers_are_visible_and_idempotent() -> None:
    async def scenario() -> None:
        sink = FakeSink()
        presenter = ReplyPresenter(sink, edit_interval_s=0.0)
        presenter.append_delta("partial")
        await presenter.flush()
        await presenter.interrupted("partial")
        await presenter.failed("different")

        assert presenter.finalized
        assert presenter.terminal_flush_count == 1
        assert presenter.text == "partial" + INTERRUPTED_MARKER
        assert sink.calls[-1] == ("edit", "partial" + INTERRUPTED_MARKER)
        assert FAILED_MARKER not in presenter.text

    asyncio.run(scenario())
