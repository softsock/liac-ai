"""Own one text turn at a time on the caller's asyncio loop."""

import asyncio
import logging
from copy import deepcopy
from time import monotonic
from typing import Literal

from vtuber.contracts.events import Event, RuntimeOutput, UserMessage
from vtuber.contracts.mind import MindDecision, MindStreamError, SingleMindPort
from vtuber.contracts.perception import Perception, PerceptionBatch
from vtuber.contracts.protocols import OutputSink
from vtuber.minds.m6_context import build_m6_messages, sensor_entry
from vtuber.runtime.attention import LiveState, should_wake
from vtuber.runtime.journal import Journal


logger = logging.getLogger(__name__)
HISTORY_TURNS = 20


class SingleMindRuntime:
    def __init__(self, character_id: str, journal: Journal, mind: SingleMindPort,
                 output: OutputSink, *, identity: str) -> None:
        self.character_id = character_id
        self.journal = journal
        self.mind = mind
        self.output = output
        self.identity = identity
        self._input_lock = asyncio.Lock()
        self._live_state = LiveState()
        self._active: tuple[UserMessage, int, asyncio.Task[None]] | None = None
        self._failed = False
        self._perception: dict[str, str] = {}
        self._wake: dict[str, object] = {'decision': None, 'reason': None}
        self._context: dict[str, object] = dict.fromkeys(
            ('turn_id', 'frame_bytes', 'history_turns', 'sensor_included', 'older_history_omitted'))
        self._generation: dict[str, object] = dict.fromkeys(
            ('turn_id', 'first_tool_delta_ms', 'duration_ms', 'bridge_duration_ms', 'usage', 'last_action'))
        self._turn_started = 0.0
        self._error: dict[str, str] = {}
        self._started = False
        self._closed = False

    def snapshot(self) -> dict[str, object]:
        """Read local diagnostics on the runtime's owning event loop."""
        turn_id = self._active[0].turn_id if self._active is not None else None
        model_status = getattr(self.mind, 'model_status', None)
        return {
            'runtime': {'state': 'generating' if turn_id else 'failed' if self._failed else 'idle',
                        'turn_id': turn_id},
            'model': model_status() if model_status is not None else {
                'name': type(self.mind).__name__, 'reasoning': None, 'bridge': 'not_applicable'},
            'perception': self._perception.copy() or None,
            'wake': self._wake.copy(),
            'live_state': [{**sensor_entry(item), 'expires_in_seconds': remaining}
                           for item, remaining in self._live_state.active('local')],
            'context': self._context.copy(),
            'generation': deepcopy(self._generation),
            'errors': self._error.copy() or None,
        }

    async def start(self) -> None:
        if self._started or self._closed:
            raise RuntimeError('Single Mind cannot be started twice')
        for message in self.journal.unfinished_inputs(self.character_id):
            if message.kind != 'user.message.completed':
                continue
            started = self.journal.get(f'reply_started_{message.event_id}')
            revision = (started.payload['snapshot_revision'] if started else
                        self.journal.snapshot(self.character_id).revision)
            self._finish(message, revision, 'reply.cancelled', {'reason': 'process_restarted'}, notify=False)
        self._started = True

    async def submit_perceptions(self, batch: PerceptionBatch) -> asyncio.Task[None] | None:
        async with self._input_lock:
            if not self._started or self._closed:
                raise RuntimeError('Single Mind is not accepting perceptions')
            message, fresh = self.journal.ingest_local_perceptions(self.character_id, batch)
            wake = should_wake(batch) and message is not None
            if batch.conversation_key == 'local':
                self._live_state.observe(fresh)
                if fresh:
                    item = fresh[-1]
                    self._perception = {'id': item.perception_id, 'kind': item.kind,
                                        'source': item.source, 'occurred_at': item.occurred_at}
                if wake:
                    reason = 'new_direct'
                elif fresh:
                    reason = 'ambient_only'
                elif any(item.delivery != 'noise' for item in batch.items):
                    reason = 'duplicate'
                else:
                    reason = 'noise_only'
                self._wake = {'decision': wake, 'reason': reason}
            if not wake or message is None:
                return None
            revision = self.journal.snapshot(self.character_id).revision
            try:
                await self._cancel_active('superseded')
            except asyncio.CancelledError:
                self._finish(message, revision, 'reply.cancelled', {'reason': 'submission_cancelled'})
                raise
            latest = self.journal.get(message.event_id)
            assert latest is not None
            history = self.journal.completed_dialogue(latest, limit=HISTORY_TURNS + 1)
            observations = self._live_state.snapshot(batch.conversation_key)
            self.journal.append(Event.create(self.character_id, 'character.reply.started',
                {'snapshot_revision': revision}, event_id=f'reply_started_{message.event_id}',
                turn_id=message.turn_id, causation_id=message.event_id))
            self._generation.update(turn_id=message.turn_id, first_tool_delta_ms=None,
                                    duration_ms=None, bridge_duration_ms=None, usage=None)
            self._turn_started = monotonic()
            self._failed = False
            task = asyncio.create_task(self._run(message, revision, latest, history, observations),
                                       name='single-mind-turn')
            self._active = message, revision, task
            task.add_done_callback(self._finish_cancelled_task)
            return task

    def _finish_cancelled_task(self, task: asyncio.Task[None]) -> None:
        if self._active is not None and self._active[2] is task and task.cancelled():
            message, revision, _ = self._active
            self._finish(message, revision, 'reply.cancelled', {'reason': 'cancelled'})

    def _emit(self, output: RuntimeOutput) -> None:
        try:
            self.output(output)
        except Exception as error:
            logger.warning('Output sink failed: %s', type(error).__name__)

    def _finish(self, message: UserMessage | Event, revision: int,
                kind: Literal['reply.completed', 'reply.cancelled', 'reply.failed'],
                payload: dict[str, str], *, notify: bool = True, decision: MindDecision | None = None) -> None:
        event_id = f'reply_terminal_{message.event_id}'
        if self.journal.get(event_id) is not None:
            return
        self.journal.append(Event.create(self.character_id, f'character.{kind}',
            {**payload, 'snapshot_revision': revision}, event_id=event_id,
            turn_id=message.turn_id, causation_id=message.event_id))
        if notify and self._generation['turn_id'] == message.turn_id:
            self._active = None
            self._failed = kind == 'reply.failed'
            self._generation['duration_ms'] = round((monotonic() - self._turn_started) * 1000)
            if self._failed:
                self._error = {'code': payload['reason'], 'turn_id': message.turn_id}
            if decision is not None:
                timings = getattr(self.mind, 'last_timings', {})
                self._generation.update(last_action=decision.action,
                    first_tool_delta_ms=timings.get('first_tool_delta_ms'),
                    bridge_duration_ms=timings.get('completed_ms'),
                    usage=None if decision.usage is None else decision.usage.copy())
        if notify:
            self._emit(RuntimeOutput(kind, self.character_id, revision, message.turn_id,
                                     payload['text'] if kind == 'reply.completed' else payload['reason']))

    async def _run(self, message: UserMessage, revision: int,
                   latest: Event, history: tuple[tuple[Event, Event], ...],
                   observations: tuple[Perception, ...]) -> None:
        task = asyncio.current_task()
        assert task is not None
        index = 0
        streaming = True

        def is_current() -> bool:
            return self._active is not None and self._active[2] is task

        def preview(text: str) -> None:
            nonlocal index
            if streaming and is_current() and not task.cancelling() and text:
                index += 1
                self._emit(RuntimeOutput('reply.delta', self.character_id, revision, message.turn_id, text, index))

        self._emit(RuntimeOutput('reply.started', self.character_id, revision, message.turn_id))
        try:
            context = build_m6_messages(self.identity, latest, history[-HISTORY_TURNS:], observations)
            self._context.update(turn_id=message.turn_id, frame_bytes=context.frame_bytes,
                history_turns=context.history_turns, sensor_included=context.sensor_included,
                older_history_omitted=context.history_turns < len(history))
            decision = await self.mind.generate(context.messages, on_speak_delta=preview)
            if not is_current() or task.cancelling():
                raise asyncio.CancelledError
            if not isinstance(decision, MindDecision) or not decision.tool_call_id.strip():
                raise ValueError('Expected one completed tool decision with an ID')
        except asyncio.CancelledError:
            if is_current():
                self._finish(message, revision, 'reply.cancelled', {'reason': 'cancelled'})
            raise
        except Exception as error:
            if is_current():
                code = error.code if isinstance(error, MindStreamError) else type(error).__name__
                self._finish(message, revision, 'reply.failed', {'reason': code})
        else:
            self._finish(message, revision, 'reply.completed', {'text': decision.message,
                'action': decision.action, 'tool_call_id': decision.tool_call_id}, decision=decision)
        finally:
            streaming = False

    async def _cancel_active(self, reason: str) -> None:
        if self._active is None:
            return
        (message, revision, task), self._active = self._active, None
        task.cancel()
        try:
            self._finish(message, revision, 'reply.cancelled', {'reason': reason})
        finally:
            await asyncio.gather(task, return_exceptions=True)

    async def close(self) -> None:
        async with self._input_lock:
            self._closed = True
            await self._cancel_active('shutdown')
