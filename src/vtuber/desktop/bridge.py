"""A single asyncio owner thread; Qt widgets never touch its live Journal."""
import asyncio
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal

from vtuber.app import Config, open_runtime
from vtuber.contracts.events import UserMessage
from vtuber.lab.host import LabHost


class RuntimeWorker(QThread):
    output = Signal(object)
    record = Signal(object)
    journal_events = Signal(object)
    history = Signal(object)
    status = Signal(object)
    ready = Signal(str)
    failed = Signal(str)
    simulation_status = Signal(object)
    conversation_input = Signal(object)

    def __init__(self, config: Config, trace_root: Path, *, simulation=None, resume=None) -> None:
        super().__init__()
        self.config = config
        self.trace_root = trace_root
        self._loop = None
        self._runtime = None
        self._stop = None
        self._stop_requested = Event()
        self._commands = set()
        self.simulation, self.resume = simulation, resume
        self._host = None
        self._pending_output = None
        self._flush_handle = None

    def _flush_output(self):
        if self._flush_handle:
            self._flush_handle.cancel()
            self._flush_handle = None
        if self._pending_output:
            self.output.emit(self._pending_output)
            self._pending_output = None

    def _forward_output(self,value):
        if value.kind!='reply.delta':
            self._flush_output()
            self.output.emit(value)
            return
        if self._pending_output and self._pending_output.turn_id==value.turn_id:
            self._pending_output = replace(value,text=self._pending_output.text+value.text)
        else:
            self._flush_output()
            self._pending_output = value
        if self._flush_handle is None:
            self._flush_handle = self._loop.call_later(.05,self._flush_output)

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
                    await self._host.submit(text)
                elif action == 'cancel':
                    await self._runtime.cancel_fast()
                elif action == 'retry':
                    self._runtime.retry_deep()
                elif self._host.controller:
                    if action == 'simulation.pause':
                        self._host.controller.pause()
                    elif action == 'simulation.resume':
                        self._host.controller.resume()
                    elif action == 'simulation.stop':
                        await self._host.controller.stop()
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
        async with LabHost(self.config,self.trace_root,simulation=self.simulation,resume=self.resume,
                           output=self._forward_output,status=self.simulation_status.emit,
                           input_message=self.conversation_input.emit) as host:
            self._host = host
            self.config = host.config
            runtime, trace = host.runtime, host.archive.trace
            trace.on_record = lambda row: self.record.emit({'row': row, 'path': str(trace.path)})
            self._runtime = runtime
            self.history.emit([asdict(e) for e in runtime.journal.recent_dialogue(self.config.character_id, limit=1000)])
            self.ready.emit(str(host.archive.path))
            cursor = 0
            try:
                while not self._stop_requested.is_set():
                    events = runtime.journal.read(self.config.character_id, after=cursor, limit=100)
                    if events:
                        cursor = events[-1].sequence
                        self.journal_events.emit([asdict(e) for e in events])
                    state = await host.capture()
                    self.status.emit(deepcopy({**state,'trace_path':str(trace.path),'trace_error':trace.error}))
                    if host.simulation_task and host.simulation_task.done() and not getattr(self,'_sim_reported',False):
                        self._sim_reported = True
                        try:
                            result = host.simulation_task.result()
                            host.result = 'completed' if result['phase'] in ('completed','duration_reached') else 'stopped'
                            self.simulation_status.emit(result)
                        except Exception as error:
                            host.result,host.reason = 'failed',type(error).__name__
                            self.failed.emit(f'Simulator: {type(error).__name__}: {error}')
                    try:
                        await asyncio.wait_for(self._stop.wait(), .2)
                    except TimeoutError:
                        pass
            finally:
                self._stop_requested.set()
                if self._commands:
                    await asyncio.gather(*tuple(self._commands), return_exceptions=True)
                self._runtime = None
