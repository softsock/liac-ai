"""One visible stream, one background consumer, and no model-owned mutable state."""

import asyncio
import logging
from contextlib import aclosing, suppress
from typing import Literal

from vtuber.contracts.events import Event, OutputKind, RuntimeOutput, UserMessage
from vtuber.contracts.protocols import DeepMind, FastMind, OutputSink
from vtuber.contracts.state import FastSnapshot, NoteProposal
from vtuber.runtime.journal import Journal

logger = logging.getLogger(__name__)
DIALOGUE_KINDS = {"user.message.completed", "character.reply.completed"}
TERMINAL_OUTPUTS: dict[str, OutputKind] = {
    "completed": "reply.completed", "cancelled": "reply.cancelled", "failed": "reply.failed",
}


class Runtime:
    def __init__(self, character_id: str, journal: Journal, fast: FastMind, deep: DeepMind,
                 output: OutputSink, *, deep_timeout: float = 30.0) -> None:
        self.character_id = character_id
        self.journal = journal
        self.fast = fast
        self.deep = deep
        self.output = output
        self.deep_timeout = deep_timeout
        self.deep_error: str | None = None
        self._wake = asyncio.Event()
        self._input_lock = asyncio.Lock()
        self._fast_task: asyncio.Task[None] | None = None
        self._deep_task: asyncio.Task[None] | None = None
        self._current: tuple[UserMessage, FastSnapshot] | None = None
        self._stopping = False
        self._started = False

    async def start(self) -> None:
        if self._started or self._stopping:
            raise RuntimeError("Runtime cannot be started twice")
        for started in self.journal.unfinished_replies(self.character_id):
            self.journal.append(Event.create(self.character_id, "character.reply.cancelled",
                {"reason": "process_restarted", "snapshot_revision": started.payload["snapshot_revision"]},
                event_id=f"reply_terminal_{started.causation_id}",
                turn_id=started.turn_id, causation_id=started.causation_id))
        self._started = True
        self._deep_task = asyncio.create_task(self._run_deep(), name="vtuber-deep")
        self._deep_task.add_done_callback(self._observe_task)
        self._wake.set()

    def _emit(self, output: RuntimeOutput) -> None:
        try:
            self.output(output)
        except Exception as error:
            logger.warning("Output sink failed: %s", type(error).__name__)

    @staticmethod
    def _observe_task(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Owned task %s failed: %s", task.get_name(), type(error).__name__)

    async def submit(self, message: UserMessage) -> asyncio.Task[None] | None:
        async with self._input_lock:
            if not self._started or self._stopping:
                raise RuntimeError("Runtime is not accepting messages")
            if message.character_id != self.character_id:
                raise ValueError("Message belongs to another character")
            duplicate = self.journal.get(message.event_id) is not None
            self.journal.append(message.as_event())
            if duplicate:
                return self._fast_task if self._current and self._current[0].event_id == message.event_id else None
            self._wake.set()
            await self._cancel_fast("superseded")
            snapshot = FastSnapshot(self.journal.snapshot(self.character_id),
                self.journal.high_watermark(self.character_id),
                self.journal.recent_dialogue(self.character_id))
            self.journal.append(Event.create(self.character_id, "character.reply.started",
                {"snapshot_revision": snapshot.state.revision,
                 "through_sequence": snapshot.through_sequence},
                event_id=f"reply_started_{message.event_id}", turn_id=message.turn_id,
                causation_id=message.event_id))
            self._current = message, snapshot
            self._fast_task = asyncio.create_task(self._run_fast(message, snapshot), name=f"vtuber-fast-{message.turn_id}")
            self._fast_task.add_done_callback(self._observe_task)
            return self._fast_task

    def _finish(self, message: UserMessage, snapshot: FastSnapshot,
                status: Literal["completed", "cancelled", "failed"],
                text: str = "", reason: str = "") -> None:
        event_id = f"reply_terminal_{message.event_id}"
        if self.journal.get(event_id) is not None:
            return
        payload: dict[str, str | int] = {"snapshot_revision": snapshot.state.revision}
        if status == "completed":
            payload["text"] = text
        else:
            payload["reason"] = reason
        self.journal.append(Event.create(self.character_id, f"character.reply.{status}", payload,
            event_id=event_id, turn_id=message.turn_id, causation_id=message.event_id))
        self._wake.set()
        self._emit(RuntimeOutput(TERMINAL_OUTPUTS[status], self.character_id, snapshot.state.revision,
                                 message.turn_id, text if status == "completed" else reason))

    async def _run_fast(self, message: UserMessage, snapshot: FastSnapshot) -> None:
        self._emit(RuntimeOutput("reply.started", self.character_id, snapshot.state.revision, message.turn_id))
        chunks: list[str] = []
        try:
            async with aclosing(self.fast.stream(snapshot, message)) as stream:
                async for chunk in stream:
                    if self._stopping or asyncio.current_task() is not self._fast_task:
                        raise asyncio.CancelledError
                    if not isinstance(chunk, str):
                        raise TypeError("Fast chunks must be strings")
                    chunks.append(chunk)
                    self._emit(RuntimeOutput("reply.delta", self.character_id, snapshot.state.revision,
                                             message.turn_id, chunk, len(chunks)))
            if self._stopping or asyncio.current_task() is not self._fast_task:
                raise asyncio.CancelledError
            self._finish(message, snapshot, "completed", "".join(chunks))
        except asyncio.CancelledError:
            self._finish(message, snapshot, "cancelled", reason="shutdown" if self._stopping else "superseded")
            raise
        except Exception as error:
            self._finish(message, snapshot, "failed", reason=type(error).__name__)

    async def _cancel_fast(self, reason: str) -> None:
        if self._fast_task is not None:
            task, self._fast_task = self._fast_task, None
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            # A task cancelled before its first instruction cannot run its own cleanup.
            if self._current is not None:
                self._finish(*self._current, "cancelled", reason=reason)

    def retry_deep(self) -> None:
        if self._stopping or not self._started:
            raise RuntimeError("Runtime is not running")
        self._wake.set()

    async def _run_deep(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while not self._stopping:
                revision = 0
                try:
                    state = self.journal.snapshot(self.character_id)
                    revision = state.revision
                    cursor = self.journal.cursor(self.character_id)
                    events = self.journal.read(self.character_id, after=cursor, limit=100)
                    if not events:
                        break
                    through = events[-1].sequence
                    if not any(event.kind in DIALOGUE_KINDS for event in events):
                        self.journal.acknowledge(self.character_id, cursor, through)
                        self.deep_error = None
                        continue
                    async with asyncio.timeout(self.deep_timeout):
                        proposal = await self.deep.propose(state, events)
                    if self._stopping:
                        return
                    if proposal is None:
                        self.journal.acknowledge(self.character_id, cursor, through)
                        text, revision = f"observed through #{through}", state.revision
                    else:
                        if (not isinstance(proposal, NoteProposal)
                                or proposal.character_id != self.character_id
                                or proposal.observed_through_sequence != through):
                            raise ValueError("Deep returned an invalid batch proposal")
                        result = self.journal.apply_note(proposal, cursor_from=cursor)
                        text, revision = f"{result.reason}; through #{through}", result.revision
                    self.deep_error = None
                    self._emit(RuntimeOutput("deep.completed", self.character_id, revision, text=text))
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self.deep_error = type(error).__name__
                    self._emit(RuntimeOutput("deep.failed", self.character_id, revision, text=self.deep_error))
                    break

    async def close(self) -> None:
        async with self._input_lock:
            if self._stopping:
                return
            self._stopping = True
            if self._deep_task is not None:
                self._deep_task.cancel()
            try:
                await self._cancel_fast("shutdown")
            finally:
                if self._deep_task is not None:
                    await asyncio.gather(self._deep_task, return_exceptions=True)

    async def __aenter__(self) -> "Runtime":
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
