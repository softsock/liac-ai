"""Rate-aware, mention-safe rendering of transient Core output to Discord."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Final, Protocol

from .transport import MAX_DISCORD_MESSAGE_CHARS, split_discord_content, validate_edit_interval

INTERRUPTED_MARKER: Final = "\n\n[response interrupted]"
FAILED_MARKER: Final = "\n\n[response unavailable]"
NO_RESPONSE_MARKER: Final = "[no response]"


class MessageSink(Protocol):
    async def create(self, content: str) -> Any: ...

    async def edit(self, message: Any, content: str) -> Any: ...


class ReplyPresenter:
    """Materialize one growing response as bounded Discord messages.

    The first flush is immediate. Later flushes are admitted by a configurable
    cadence, so a burst of Core deltas becomes one edit rather than one HTTP
    request per delta. Terminal methods force one final reconciliation and are
    idempotent.
    """

    def __init__(
        self,
        sink: MessageSink,
        *,
        edit_interval_s: float = 0.5,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        validate_edit_interval(edit_interval_s)
        self._sink = sink
        self._edit_interval_s = edit_interval_s
        self._clock = clock
        self._text = ""
        self._published_chunks: tuple[str, ...] = ()
        self._messages: list[Any] = []
        self._last_flush_at: float | None = None
        self._finalized = False
        self.flush_count = 0
        self.terminal_flush_count = 0

    @property
    def text(self) -> str:
        return self._text

    @property
    def finalized(self) -> bool:
        return self._finalized

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def published_chunks(self) -> tuple[str, ...]:
        return self._published_chunks

    def append_delta(self, delta: str) -> None:
        if self._finalized:
            return
        self._text += delta

    def replace_text(self, text: str) -> None:
        if self._finalized:
            return
        self._text = text

    def ready_to_flush(self) -> bool:
        if not self._text:
            return False
        if self._last_flush_at is None:
            return True
        return self._clock() - self._last_flush_at >= self._edit_interval_s

    async def flush(self, *, force: bool = False) -> bool:
        if self._finalized:
            return False
        if not force and not self.ready_to_flush():
            return False
        chunks = split_discord_content(self._text, max_chars=MAX_DISCORD_MESSAGE_CHARS)
        if not chunks:
            return False
        await self._reconcile(chunks)
        self._published_chunks = chunks
        self._last_flush_at = self._clock()
        self.flush_count += 1
        return True

    async def complete(self, text: str) -> None:
        await self._finalize(text, "", empty_fallback=NO_RESPONSE_MARKER)

    async def interrupted(self, text: str) -> None:
        await self._finalize(text, INTERRUPTED_MARKER)

    async def failed(self, text: str) -> None:
        await self._finalize(text, FAILED_MARKER)

    async def _finalize(self, text: str, marker: str, *, empty_fallback: str | None = None) -> None:
        if self._finalized:
            return
        self._text = text + marker if text else (empty_fallback or marker.lstrip())
        self.terminal_flush_count += 1
        await self.flush(force=True)
        self._finalized = True

    async def _reconcile(self, chunks: tuple[str, ...]) -> None:
        for index, chunk in enumerate(chunks):
            if index < len(self._messages):
                if index >= len(self._published_chunks) or self._published_chunks[index] != chunk:
                    self._messages[index] = await self._sink.edit(self._messages[index], chunk)
            else:
                self._messages.append(await self._sink.create(chunk))
