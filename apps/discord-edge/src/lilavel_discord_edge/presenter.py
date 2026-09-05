"""Rate-aware, mention-safe rendering of transient Core output to Discord."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, Final, Protocol

from .diagnostics import DiscordDiagnostics
from .transport import MAX_DISCORD_MESSAGE_CHARS, split_discord_content, validate_edit_interval

INTERRUPTED_MARKER: Final = "\n\n[response interrupted]"
FAILED_MARKER: Final = "\n\n[response unavailable]"
NO_RESPONSE_MARKER: Final = "[no response]"
DEFAULT_EDIT_INTERVAL_S: Final = 1.0


class MessageSink(Protocol):
    async def create(self, content: str) -> Any: ...

    async def edit(self, message: Any, content: str) -> Any: ...


class ReplyPresenter:
    """Materialize one growing response as bounded Discord messages.

    The first meaningful delta is published immediately. Later snapshots are
    published by one owned pump after a configurable minimum interval. Deltas
    arriving while Discord is busy only update the latest snapshot; the pump
    never starts a second reconciliation concurrently. Terminal methods force
    one final reconciliation and are idempotent.
    """

    def __init__(
        self,
        sink: MessageSink,
        *,
        edit_interval_s: float = DEFAULT_EDIT_INTERVAL_S,
        clock: Callable[[], float] = time.perf_counter,
        diagnostics: DiscordDiagnostics | None = None,
    ) -> None:
        validate_edit_interval(edit_interval_s)
        self._sink = sink
        self._edit_interval_s = edit_interval_s
        self._clock = clock
        self._diagnostics = diagnostics
        self._text = ""
        self._published_chunks: tuple[str, ...] = ()
        self._messages: list[Any] = []
        self._last_publish_started_at: float | None = None
        self._publish_lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._pump_failed = asyncio.Event()
        self._pump_task: asyncio.Task[None] | None = None
        self._pump_error: BaseException | None = None
        self._terminal_requested = False
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

    def start(self) -> None:
        """Start the single-flight publisher owned by this presenter."""

        if self._pump_task is None:
            self._pump_task = asyncio.create_task(
                self._run_pump(),
                name="lilavel-discord-reply-presenter-pump",
            )

    def append_delta(self, delta: str) -> None:
        if self._finalized or self._terminal_requested:
            return
        if delta:
            self._text += delta
            self._wake.set()

    def replace_text(self, text: str) -> None:
        if self._finalized or self._terminal_requested:
            return
        if self._text != text:
            self._text = text
            self._wake.set()

    def ready_to_flush(self) -> bool:
        if self._finalized or self._terminal_requested or not self._has_pending_snapshot():
            return False
        if self._last_publish_started_at is None:
            return True
        return self._clock() - self._last_publish_started_at >= self._edit_interval_s

    async def flush(self, *, force: bool = False) -> bool:
        """Reconcile once for callers that do not use the owned pump."""

        if self._finalized or self._terminal_requested:
            return False
        if not force and not self.ready_to_flush():
            return False
        return await self._flush_once(force=force)

    async def complete(self, text: str) -> None:
        await self._finalize(text, "", empty_fallback=NO_RESPONSE_MARKER)

    async def interrupted(self, text: str) -> None:
        await self._finalize(text, INTERRUPTED_MARKER)

    async def failed(self, text: str) -> None:
        await self._finalize(text, FAILED_MARKER)

    async def shutdown(self) -> None:
        """Settle the owned pump when the surrounding response task is cancelled."""

        task = self._pump_task
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def wait_for_error(self) -> BaseException:
        """Wait for an unexpected sink error from the owned pump."""

        await self._pump_failed.wait()
        if self._pump_error is None:
            raise RuntimeError("reply presenter pump failed without an error")
        return self._pump_error

    async def _finalize(
        self,
        text: str,
        marker: str,
        *,
        empty_fallback: str | None = None,
    ) -> None:
        if self._finalized:
            return
        if self._terminal_requested:
            await self._await_pump()
            return
        self._text = text + marker if text else (empty_fallback or marker.lstrip())
        self._terminal_requested = True
        self.terminal_flush_count += 1
        self.start()
        self._wake.set()
        await self._await_pump()

    async def _await_pump(self) -> None:
        task = self._pump_task
        if task is None:
            raise RuntimeError("reply presenter pump was not started")
        await task

    async def _run_pump(self) -> None:
        try:
            while not self._finalized:
                if self._terminal_requested:
                    await self._flush_once(force=True)
                    self._finalized = True
                    return

                if self.ready_to_flush():
                    await self._flush_once(force=False)
                    continue

                self._wake.clear()
                if self._terminal_requested or self.ready_to_flush():
                    continue

                timeout = self._time_until_eligible()
                try:
                    if timeout is None:
                        await self._wake.wait()
                    else:
                        await asyncio.wait_for(self._wake.wait(), timeout)
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            self._pump_error = error
            self._pump_failed.set()
            raise

    def _time_until_eligible(self) -> float | None:
        if not self._has_pending_snapshot():
            return None
        if self._last_publish_started_at is None:
            return 0.0
        elapsed = self._clock() - self._last_publish_started_at
        return max(0.0, self._edit_interval_s - elapsed)

    def _has_pending_snapshot(self) -> bool:
        chunks = split_discord_content(self._text, max_chars=MAX_DISCORD_MESSAGE_CHARS)
        return bool(chunks) and chunks != self._published_chunks

    async def _flush_once(self, *, force: bool) -> bool:
        async with self._publish_lock:
            if self._finalized:
                return False
            if not force and self._terminal_requested:
                return False
            if not force and not self.ready_to_flush():
                return False

            chunks = split_discord_content(self._text, max_chars=MAX_DISCORD_MESSAGE_CHARS)
            if not chunks:
                return False
            if not force and chunks == self._published_chunks:
                return False

            # A slow request consumes part of the floor; do not add another full wait.
            self._last_publish_started_at = self._clock()
            if self._diagnostics is None:
                await self._reconcile(chunks)
            else:
                with self._diagnostics.presenter_flush(
                    chunk_count=len(chunks),
                    force=force,
                ):
                    await self._reconcile(chunks)
            self._published_chunks = chunks
            self.flush_count += 1
            return True

    async def _reconcile(self, chunks: tuple[str, ...]) -> None:
        for index, chunk in enumerate(chunks):
            if index < len(self._messages):
                if index >= len(self._published_chunks) or self._published_chunks[index] != chunk:
                    self._messages[index] = await self._sink.edit(self._messages[index], chunk)
            else:
                self._messages.append(await self._sink.create(chunk))
