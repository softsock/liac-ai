"""One serialized, recoverable observer. No provider operation belongs to Fast."""
import asyncio
from time import perf_counter

from vtuber.contracts.context import ContextBudgetExceeded
from vtuber.contracts.deep import DeepUnavailable
from vtuber.contracts.events import RuntimeOutput, UserMessage, new_id
from vtuber.contracts.protocols import ContextPolicy, DeepMind, OutputSink
from vtuber.runtime.journal import Journal


async def retry_delay(seconds: float) -> None:
    await asyncio.sleep(seconds)


class DeepWorker:
    def __init__(self, character_id: str, journal: Journal, mind: DeepMind, output: OutputSink,
                 *, timeout: float, context_policy: ContextPolicy | None, diagnostics: dict[str, object]) -> None:
        self.character_id, self.journal, self.mind, self.output = character_id, journal, mind, output
        self.timeout, self.context_policy, self.diagnostics = timeout, context_policy, diagnostics
        self.error: str | None = None
        self._wake = asyncio.Event()
        self._retry = asyncio.Event()
        self._task = None
        self._compact = False
        self._attempted = None
        self._stopping = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name='vtuber-deep')
        self.notify()

    def notify(self, *, compact: bool = False) -> None:
        self._compact |= compact
        self._wake.set()

    def retry(self) -> None:
        self._attempted = None
        self._retry.set()
        self.notify()

    async def _backoff(self, seconds: float) -> bool:
        timer = asyncio.create_task(retry_delay(seconds))
        retry = asyncio.create_task(self._retry.wait())
        try:
            await asyncio.wait((timer, retry), return_when=asyncio.FIRST_COMPLETED)
            requested = self._retry.is_set()
            self._retry.clear()
            return requested
        finally:
            timer.cancel()
            retry.cancel()
            await asyncio.gather(timer, retry, return_exceptions=True)

    def _pressure(self) -> bool:
        if self.context_policy is None:
            return False
        snapshot = self.journal.fast_snapshot(self.character_id)
        latest = next((e for e in reversed(snapshot.recent_dialogue) if e.kind == 'user.message.completed'), None)
        if latest is None:
            return False
        message = UserMessage(latest.payload['text'], self.character_id,
            event_id=latest.event_id, turn_id=latest.turn_id)
        return self.context_policy.input_tokens(snapshot, message) >= self.context_policy.input_limit*3//4

    async def _run(self):
        while not self._stopping:
            await self._wake.wait()
            self._wake.clear()
            self._retry.clear()
            failures = 0
            while not self._stopping:
                revision = self.journal.snapshot(self.character_id).revision
                try:
                    pressure = self._compact or self._pressure()
                    request = self.journal.deep_request(self.character_id, request_id=new_id('deep'), compact=pressure)
                    self._compact = False
                    if request is None:
                        break
                    key = (request.snapshot.epoch.version, request.snapshot.state.revision,
                           request.compaction.cutoff if request.compaction else None)
                    if not request.events and key == self._attempted:
                        break
                    self.diagnostics.update(degraded=False, observed_through=request.snapshot.through_sequence,
                        cursor_from=request.cursor_from, preparing_epoch=request.compaction is not None,
                        base_epoch=request.snapshot.epoch.version)
                    start = perf_counter()
                    async with asyncio.timeout(self.timeout):
                        result = await self.mind.propose(request)
                    if self._stopping:
                        return
                    self.diagnostics['analysis_ms'] = round((perf_counter()-start)*1000, 3)
                    budget_error = None
                    if result.compaction and self.context_policy:
                        try:
                            self.context_policy.validate_compaction(self.journal.fast_snapshot(self.character_id), result.compaction)
                        except ContextBudgetExceeded:
                            budget_error = 'context_budget_exceeded'
                    start = perf_counter()
                    decision = self.journal.apply_deep(request, result, compaction_error=budget_error)
                    self.diagnostics.update(commit_ms=round((perf_counter()-start)*1000, 3),
                        decision=decision.reason, acknowledged=decision.acknowledged)
                    if not decision.acknowledged:
                        raise ValueError(decision.reason)
                    current = self.journal.snapshot(self.character_id)
                    self._attempted = (self.journal.context_epoch(self.character_id).version,
                        current.revision, request.compaction.cutoff if request.compaction else None)
                    self.error = None
                    self.diagnostics.update(error=None, retry_count=0, degraded=False)
                    failures = 0
                    revision = self.journal.snapshot(self.character_id).revision
                    self.output(RuntimeOutput('deep.completed', self.character_id, revision,
                        text=f'{decision.reason}; through #{request.snapshot.through_sequence}'))
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    if self._stopping:
                        return
                    self.error = type(error).__name__
                    terminal = isinstance(error, DeepUnavailable)
                    self.diagnostics.update(error=self.error, retry_count=failures, degraded=terminal or failures >= 5)
                    self.output(RuntimeOutput('deep.failed', self.character_id, revision, text=self.error))
                    if terminal or failures >= 5:
                        # Notifications accumulated during this failed cycle do not bypass its cap.
                        self._wake.clear()
                        break
                    failures = 0 if await self._backoff(2**failures) else failures + 1

    async def close(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
