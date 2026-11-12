"""A single asyncio owner thread; Qt widgets never touch its live Journal."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal

from vtuber.app import Config, open_runtime
from vtuber.contracts.events import UserMessage
from vtuber.tracing import TraceRecorder


class RuntimeWorker(QThread):
    output = Signal(object)
    record = Signal(object)
    journal_events = Signal(object)
    history = Signal(object)
    status = Signal(object)
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, config: Config, trace_root: Path) -> None:
        super().__init__()
        self.config = config
        self.trace_root = trace_root
        self._loop = None
        self._runtime = None
        self._stop = None
        self._stop_requested = Event()
        self._commands = set()

    def command(self, action: str, text: str = '') -> None:
        if action == 'stop':
            self._stop_requested.set()
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._schedule, action, text)
            except RuntimeError:
                pass  # The owner finished between the state check and scheduling.

    def _schedule(self, action, text):
        task = asyncio.create_task(self._execute(action, text))
        self._commands.add(task)
        task.add_done_callback(self._commands.discard)

    async def _execute(self, action, text):
        try:
            if action == 'stop':
                self._stop.set()
            elif self._runtime is not None and not self._stop_requested.is_set():
                if action == 'submit':
                    await self._runtime.submit(UserMessage(text, self.config.character_id))
                elif action == 'cancel':
                    await self._runtime.cancel_fast()
                elif action == 'retry':
                    self._runtime.retry_deep()
        except Exception as error:
            self.failed.emit(f'{type(error).__name__}: {error}')

    def run(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception as error:
            self.failed.emit(f'{type(error).__name__}: {error}')
        finally:
            self._loop = None
            self._runtime = None

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        trace = TraceRecorder(self.trace_root)
        trace.on_record = lambda row: self.record.emit({'row': row, 'path': str(trace.path)})
        async with open_runtime(self.config, self.output.emit, trace=trace) as runtime:
            self._runtime = runtime
            self.history.emit([asdict(e) for e in runtime.journal.recent_dialogue(self.config.character_id, limit=1000)])
            self.ready.emit(str(trace.path))
            cursor = 0
            try:
                while not self._stop_requested.is_set():
                    events = runtime.journal.read(self.config.character_id, after=cursor, limit=100)
                    if events:
                        cursor = events[-1].sequence
                        self.journal_events.emit([asdict(e) for e in events])
                    self.status.emit(deepcopy({
                        'state': asdict(runtime.journal.snapshot(self.config.character_id)),
                        'epoch': asdict(runtime.journal.context_epoch(self.config.character_id)),
                        'deep_cursor': runtime.journal.cursor(self.config.character_id),
                        'journal_sequence': runtime.journal.high_watermark(self.config.character_id),
                        'fast': runtime.fast_diagnostics, 'deep': runtime.deep_diagnostics,
                        'trace_path': str(trace.path), 'trace_error': trace.error,
                    }))
                    try:
                        await asyncio.wait_for(self._stop.wait(), .2)
                    except TimeoutError:
                        pass
            finally:
                self._stop_requested.set()
                if self._commands:
                    await asyncio.gather(*tuple(self._commands), return_exceptions=True)
                self._runtime = None
