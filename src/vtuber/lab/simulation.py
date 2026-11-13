"""A human-client loop with explicit pauses and stale-action cancellation."""
import asyncio
import json
import math
import random
from dataclasses import dataclass
from time import monotonic
from typing import Awaitable, Callable

from vtuber.contracts.events import UserMessage, new_id
from vtuber.contracts.trace import emit_trace


@dataclass(frozen=True)
class VisibleMessage:
    turn_id: str
    role: str
    text: str
    origin: str
    session: int


@dataclass(frozen=True)
class SimulationAction:
    kind: str
    text: str = ''
    wait_seconds: float = 0
    reason: str = ''


def parse_action(text: str) -> SimulationAction:
    if len(text.encode('utf-8')) > 65536:
        raise ValueError('Simulator response exceeds 64 KiB')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('Duplicate simulator field')
            value[key] = item
        return value
    data = json.loads(text, object_pairs_hook=pairs)
    if not isinstance(data, dict) or set(data)-{'schema_version','kind','text','wait_seconds','reason'}:
        raise ValueError('Invalid simulator action fields')
    if type(data.get('schema_version',1)) is not int or data.get('schema_version',1) != 1:
        raise ValueError('Unsupported simulator action version')
    action = SimulationAction(**{k:v for k,v in data.items() if k != 'schema_version'})
    if action.kind not in ('message','silence','end_session','finish'):
        raise ValueError('Invalid simulator action kind')
    if not isinstance(action.text,str) or not isinstance(action.reason,str):
        raise ValueError('Simulator text/reason must be strings')
    if (type(action.wait_seconds) not in (int,float) or not math.isfinite(action.wait_seconds)
            or not 0 <= action.wait_seconds <= 3600):
        raise ValueError('Simulator wait must be finite, between 0 and 3600 seconds')
    if action.kind == 'message' and not action.text.strip():
        raise ValueError('Empty simulated message')
    if action.kind == 'silence' and not action.wait_seconds:
        raise ValueError('Silence requires a positive wait')
    return action


class SimulationController:
    def __init__(self, simulator, submit: Callable[[UserMessage], Awaitable[object]], *,
                 character_id: str, trace=None, pause_scale: float = 1, seed: int | None = None,
                 session: int = 1, initial_turns: int = 0, initial_elapsed: float = 0,
                 on_input=None, on_status=None, wait=asyncio.sleep):
        if type(pause_scale) not in (int,float) or not math.isfinite(pause_scale) or pause_scale <= 0:
            raise ValueError('Pause scale must be positive and finite')
        self.simulator, self.submit, self.character_id = simulator, submit, character_id
        self.trace, self.pause_scale = trace, pause_scale
        self.on_input, self.on_status, self.wait = on_input, on_status, wait
        self.history = []
        self.session, self.turns, self.initial_elapsed = session, initial_turns, initial_elapsed
        self._generation = 0
        self._paused = False
        self._stopped = False
        self._wake = asyncio.Event()
        self._pending = None
        self.phase = 'ready'
        self.random = random.Random(seed)
        self._started = None

    def observe(self, message: VisibleMessage):
        self.history.append(message)

    def status(self):
        return dict(phase=self.phase, session=self.session, turns=self.turns, paused=self._paused,
                    elapsed_seconds=self.initial_elapsed+(monotonic()-self._started if self._started else 0))

    def _phase(self, phase, **extra):
        self.phase = phase
        state = {**self.status(), **extra}
        emit_trace(self.trace, 'simulator.phase', 'simulation', **state)
        if self.on_status:
            self.on_status(state)

    def pause(self):
        self._paused = True
        self._generation += 1
        self._wake.set()
        self._phase('paused')

    def manual_input(self):
        self.pause()

    def resume(self):
        self._paused = False
        self._generation += 1
        self._wake.set()
        self._phase('resuming')

    async def stop(self):
        self._stopped = True
        self._generation += 1
        self._wake.set()
        if self._pending:
            self._pending.cancel()
            await asyncio.gather(self._pending, return_exceptions=True)

    async def _delay(self, seconds):
        self._wake.clear()
        timer = asyncio.create_task(self.wait(seconds*self.pause_scale))
        interrupt = asyncio.create_task(self._wake.wait())
        try:
            await asyncio.wait((timer,interrupt), return_when=asyncio.FIRST_COMPLETED)
        finally:
            timer.cancel()
            interrupt.cancel()
            await asyncio.gather(timer,interrupt, return_exceptions=True)

    async def run(self, *, turns: int | None, duration_seconds: float | None):
        if turns is not None and (type(turns) is not int or turns <= 0):
            raise ValueError('Turns must be a positive integer')
        if duration_seconds is not None and (type(duration_seconds) not in (int,float)
                or not math.isfinite(duration_seconds) or duration_seconds <= 0):
            raise ValueError('Duration must be positive and finite')
        if turns is None and duration_seconds is None:
            raise ValueError('A turn or duration budget is required')
        self._started = monotonic()
        try:
            remaining_seconds = (max(.001,duration_seconds-self.initial_elapsed)
                                 if duration_seconds is not None else None)
            async with asyncio.timeout(remaining_seconds):
                while not self._stopped and (turns is None or self.turns < turns):
                    if self._paused:
                        self._wake.clear()
                        await self._wake.wait()
                        continue
                    generation = self._generation
                    request_id = new_id('simulator')
                    self._phase('generating', action_id=request_id)
                    self._pending = asyncio.create_task(self.simulator.next_action(tuple(self.history),
                        session=self.session, remaining_turns=max(0,turns-self.turns) if turns else 100000))
                    try:
                        action = await self._pending
                    except asyncio.CancelledError:
                        if self._stopped:
                            break
                        raise
                    finally:
                        self._pending = None
                    if self._stopped or generation != self._generation:
                        continue
                    emit_trace(self.trace, 'simulator.action', request_id,
                               action=action.__dict__, session=self.session)
                    if action.kind == 'finish':
                        self._phase('finished_early', reason=action.reason)
                        break
                    if action.kind == 'message':
                        message = UserMessage(action.text,self.character_id)
                        if self.on_input:
                            self.on_input(message, 'simulated', self.session)
                        self.observe(VisibleMessage(message.turn_id,'user',message.text,'simulated',self.session))
                        self._phase('waiting_fast')
                        active = await self.submit(message)
                        self.turns += 1
                        if isinstance(active,asyncio.Task):
                            await asyncio.gather(active, return_exceptions=True)
                    elif action.kind == 'end_session':
                        emit_trace(self.trace, 'simulator.boundary', request_id,
                                   session=self.session, reason=action.reason)
                        self.session += 1
                    if generation != self._generation:
                        continue
                    pause = action.wait_seconds or self.random.choice((8,20,45))
                    self._phase('silence', wait_seconds=pause, actual_wait_seconds=pause*self.pause_scale)
                    await self._delay(pause)
                else:
                    self._phase('stopped' if self._stopped else 'completed')
        except TimeoutError:
            self._phase('duration_reached')
        finally:
            await self.simulator.close()
        return self.status()
