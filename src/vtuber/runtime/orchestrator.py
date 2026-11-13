"""One visible stream, one background consumer, and no model-owned mutable state."""

import asyncio
import logging
from contextlib import aclosing, suppress
from time import perf_counter
from pathlib import Path
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Literal

from vtuber.contracts.events import Event, OutputKind, RuntimeOutput, UserMessage, FastInput, CharacterInitiative, utc_now
from vtuber.contracts.deep import DeepRequest, DeepResult, DeepDecision, validate_initiative_timing
from vtuber.contracts.protocols import ContextPolicy, DeepMind, FastMind, OutputSink
from vtuber.contracts.context import CompactionProposal, CompactionResult, ContextBudgetExceeded
from vtuber.contracts.state import FastSnapshot
from vtuber.runtime.deep import DeepWorker
from vtuber.runtime.journal import Journal
from vtuber.contracts.trace import TraceSink, emit_trace, trace_enabled

logger = logging.getLogger(__name__)
TERMINAL_OUTPUTS: dict[str, OutputKind] = {
    "completed": "reply.completed", "cancelled": "reply.cancelled", "failed": "reply.failed",
}


async def initiative_delay(seconds: float) -> None:
    await asyncio.sleep(seconds)


class Runtime:
    def __init__(self, character_id: str, journal: Journal, fast: FastMind, deep: DeepMind,
                 output: OutputSink, *, deep_timeout: float = 30.0,
                 fast_diagnostics: dict[str, object] | None = None,
                 deep_diagnostics: dict[str, object] | None = None,
                 context_policy: ContextPolicy | None = None, trace: TraceSink | None = None,
                 context_path: Path | None = None, initiative_enabled: bool = False,
                 initiative_delay_seconds: float = 5.0, initiative_ttl_seconds: float = 120.0,
                 initiative_cooldown_seconds: float = 60.0) -> None:
        validate_initiative_timing(initiative_delay_seconds, initiative_ttl_seconds, initiative_cooldown_seconds)
        self.initiative_enabled = initiative_enabled
        self.initiative_cooldown_seconds = initiative_cooldown_seconds
        self._initiative_task: asyncio.Task[None] | None = None
        self._initiative_id: str | None = None
        self.character_id = character_id
        self.journal = journal
        self.fast = fast
        self.deep = deep
        self.output = output
        self.trace = trace
        self.deep_timeout = deep_timeout
        self.context_policy = context_policy
        self.fast_diagnostics = fast_diagnostics if fast_diagnostics is not None else {}
        self.last_cancellation_ms: float | None = None
        self.deep_diagnostics = deep_diagnostics if deep_diagnostics is not None else {}
        self._deep_worker = DeepWorker(character_id, journal, deep, self._emit,
            timeout=deep_timeout, context_policy=context_policy, diagnostics=self.deep_diagnostics, trace=trace,
            context_path=context_path, on_decision=self._on_deep_decision,
            initiative_enabled=initiative_enabled, initiative_delay_seconds=initiative_delay_seconds,
            initiative_ttl_seconds=initiative_ttl_seconds)
        self._input_lock = asyncio.Lock()
        self._fast_task: asyncio.Task[None] | None = None
        self._current: tuple[FastInput, FastSnapshot] | None = None
        self._stopping = False
        self._started = False

    async def start(self) -> None:
        if self._started or self._stopping:
            raise RuntimeError("Runtime cannot be started twice")
        self._withdraw_initiative('process_restarted')
        for message in self.journal.unfinished_inputs(self.character_id):
            started = self.journal.get(f'reply_started_{message.event_id}')
            revision = (started.payload['snapshot_revision'] if started else
                        self.journal.snapshot(self.character_id).revision)
            self.journal.append(Event.create(self.character_id, "character.reply.cancelled",
                {"reason": "process_restarted", "snapshot_revision": revision},
                event_id=f"reply_terminal_{message.event_id}",
                turn_id=message.turn_id, causation_id=message.event_id))
        self._started = True
        self._deep_worker.start()

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
            self._deep_worker.notify()
            await self._cancel_fast("superseded")
            self._withdraw_initiative("new_user_input")
            return self._start_fast(message)

    def _start_fast(self, message: FastInput, *, initiative_clock: tuple[datetime, float] | None = None) -> asyncio.Task[None] | None:
        snapshot = self.journal.fast_snapshot(self.character_id)
        error = None
        start = perf_counter()
        try:
            if self.context_policy is not None:
                proposal = self.context_policy.prepare_epoch(snapshot, message)
                if proposal is not None:
                    before = asdict(snapshot.epoch) if trace_enabled(self.trace) else None
                    result = self.apply_compaction(proposal)
                    if trace_enabled(self.trace):
                        emit_trace(self.trace, 'runtime.epoch', message.turn_id,
                                   before=before, proposal=asdict(proposal), result=asdict(result),
                                   after=asdict(self.journal.context_epoch(self.character_id)))
                    if not result.accepted:
                        raise ValueError(f"Local compaction rejected: {result.reason}")
                    snapshot = self.journal.fast_snapshot(self.character_id)
                if isinstance(message, UserMessage):
                    self._deep_worker.notify(compact=self.context_policy.input_tokens(snapshot, message)
                        >= self.context_policy.input_limit * 3 // 4)
        except ContextBudgetExceeded as caught:
            error = caught
        self.fast_diagnostics["preparation_ms"] = round((perf_counter() - start) * 1000, 3)
        if isinstance(message, CharacterInitiative):
            if error is not None:
                self.journal.close_initiative(message.proposal_id, 'preparation_failed')
                return None
            claimed = self.journal.claim_initiative(message.proposal_id, snapshot,
                cooldown_seconds=self.initiative_cooldown_seconds,
                checked_at=(initiative_clock[0]+timedelta(seconds=perf_counter()-initiative_clock[1])).isoformat()
                    if initiative_clock is not None else None)
            if claimed is None:
                return None
            message = claimed
        else:
            self.journal.append(Event.create(self.character_id, "character.reply.started",
                {"snapshot_revision": snapshot.state.revision,
                 "through_sequence": snapshot.through_sequence, "epoch_version": snapshot.epoch.version,
                 "compacted_through_sequence": snapshot.epoch.compacted_through_sequence},
                event_id=f"reply_started_{message.event_id}", turn_id=message.turn_id,
                causation_id=message.event_id))
        self._current = message, snapshot
        if trace_enabled(self.trace):
            emit_trace(self.trace, 'fast.started', message.turn_id,
                       message=asdict(message), snapshot=asdict(snapshot))
        if error is not None:
            self.fast_diagnostics.pop("context", None)
            self.fast_diagnostics["generation"] = {"turn_id": message.turn_id, "status": "failed",
                "error": type(error).__name__}
            self._emit(RuntimeOutput("reply.started", self.character_id, snapshot.state.revision, message.turn_id))
            self._finish(message, snapshot, "failed", reason=type(error).__name__)
            return None
        self._fast_task = asyncio.create_task(self._run_fast(message, snapshot), name=f"vtuber-fast-{message.turn_id}")
        self._fast_task.add_done_callback(self._observe_task)
        return self._fast_task

    def apply_compaction(self, proposal: CompactionProposal) -> CompactionResult:
        if not self._started or self._stopping:
            raise RuntimeError("Runtime is not running")
        if proposal.character_id != self.character_id:
            raise ValueError("Compaction belongs to another character")
        snapshot = self.journal.fast_snapshot(self.character_id)
        replay = self.journal.get(f"compaction_{proposal.proposal_id}") is not None
        if (not replay and self.context_policy is not None
                and proposal.based_on_epoch == snapshot.epoch.version
                and proposal.based_on_revision == snapshot.state.revision):
            self.context_policy.validate_compaction(snapshot, proposal)
        result = self.journal.apply_compaction(proposal)
        if result.accepted and not replay:
            covered = tuple(dict.fromkeys([
                *(s for item in snapshot.epoch.items for s in item.source_event_ids),
                *(e.event_id for e in snapshot.recent_dialogue
                  if e.sequence <= proposal.compacted_through_sequence)]))
            retained = {s for item in proposal.items for s in item.source_event_ids}
            omitted = tuple(s for s in covered if s not in retained)
            self.fast_diagnostics["last_compaction"] = {"epoch_version": result.epoch_version,
                "covered_source_count": len(covered), "retained_source_count": len(retained),
                "omitted_source_count": len(omitted), "omitted_source_ids": omitted[:32]}
        return result

    def _finish(self, message: FastInput, snapshot: FastSnapshot,
                status: Literal["completed", "cancelled", "failed"],
                text: str = "", reason: str = "", partial: str = "") -> None:
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
        self._deep_worker.notify()
        emit_trace(self.trace, 'fast.finished', message.turn_id, status=status, text=text,
                   partial=partial, reason=reason, metrics=self.fast_diagnostics)
        self._emit(RuntimeOutput(TERMINAL_OUTPUTS[status], self.character_id, snapshot.state.revision,
                                 message.turn_id, text if status == "completed" else reason))

    async def _run_fast(self, message: FastInput, snapshot: FastSnapshot) -> None:
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
        except asyncio.CancelledError as cancelled:
            reason = str(cancelled) or ('shutdown' if self._stopping else 'superseded')
            self._finish(message, snapshot, "cancelled", reason=reason, partial=''.join(chunks))
            raise
        except Exception as error:
            self._finish(message, snapshot, "failed", reason=type(error).__name__, partial=''.join(chunks))

    async def cancel_fast(self) -> None:
        """Cancel visible speech without stopping the independent Deep observer."""
        async with self._input_lock:
            waiting = self._withdraw_initiative('user_cancelled')
            if waiting:
                await asyncio.gather(waiting, return_exceptions=True)
            await self._cancel_fast('user_cancelled')

    def _withdraw_initiative(self, reason: str) -> asyncio.Task[None] | None:
        pending = self.journal.pending_initiative(self.character_id)
        if pending:
            self.journal.close_initiative(pending.event_id, reason)
        task, self._initiative_task = self._initiative_task, None
        self._initiative_id = None
        if task:
            task.cancel()
        return task

    def _on_deep_decision(self, request: DeepRequest, result: DeepResult, decision: DeepDecision) -> None:
        pending = self.journal.pending_initiative(self.character_id)
        proposal_id = pending.event_id if pending else None
        if proposal_id == self._initiative_id:
            return
        if self._initiative_task:
            self._initiative_task.cancel()
        self._initiative_task = None
        self._initiative_id = proposal_id
        if pending and self.initiative_enabled and not self._stopping:
            self._initiative_task = asyncio.create_task(self._wait_initiative(proposal_id), name='vtuber-initiative')
            self._initiative_task.add_done_callback(self._observe_task)

    async def _wait_initiative(self, proposal_id: str) -> None:
        proposal = self.journal.get(proposal_id)
        p = proposal.payload
        now = datetime.fromisoformat(utc_now())
        armed = perf_counter()
        remaining = (datetime.fromisoformat(p['expires_at']) - now).total_seconds()
        delay = max(0, (datetime.fromisoformat(p['ready_at']) - now).total_seconds())
        last = self.journal.last_initiative_attempt(self.character_id)
        if last:
            delay = max(delay, self.initiative_cooldown_seconds -
                        (now - datetime.fromisoformat(last.occurred_at)).total_seconds())
        if remaining <= delay:
            self.journal.close_initiative(proposal_id, 'expired_before_ready')
            return
        await initiative_delay(delay)
        active = self._fast_task
        if active is not None and not active.done():
            await asyncio.wait((active,), timeout=max(0, remaining-delay))
        # Let already queued real inputs acquire the lock first.
        await asyncio.sleep(0)
        async with self._input_lock:
            if self._stopping or not self.initiative_enabled:
                return
            if self._fast_task is not None and not self._fast_task.done():
                self.journal.close_initiative(proposal_id, 'expired_while_speaking')
                return
            self._start_fast(CharacterInitiative(p['intent'], p['reason'], self.character_id,
                'initiative_input_'+proposal_id, 'initiative_turn_'+proposal_id, utc_now(), proposal_id),
                initiative_clock=(now, armed))

    async def _cancel_fast(self, reason: str) -> None:
        if self._fast_task is not None:
            task, self._fast_task = self._fast_task, None
            was_active = not task.done()
            start = perf_counter()
            task.cancel(reason)
            with suppress(asyncio.CancelledError):
                await task
            # A task cancelled before its first instruction cannot run its own cleanup.
            if self._current is not None:
                self._finish(*self._current, "cancelled", reason=reason)
            if was_active:
                self.last_cancellation_ms = round((perf_counter() - start) * 1000, 2)

    @property
    def deep_error(self) -> str | None:
        return self._deep_worker.error

    def retry_deep(self) -> None:
        if self._stopping or not self._started:
            raise RuntimeError("Runtime is not running")
        self._deep_worker.retry()

    async def close(self) -> None:
        async with self._input_lock:
            if self._stopping:
                return
            self._stopping = True
            try:
                waiting = self._withdraw_initiative('shutdown')
                if waiting:
                    await asyncio.gather(waiting, return_exceptions=True)
                await self._cancel_fast("shutdown")
            finally:
                await self._deep_worker.close()

    async def __aenter__(self) -> "Runtime":
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
