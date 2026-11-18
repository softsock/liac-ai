"""Local JSONL transport for the opt-in Single Mind runtime."""

import argparse
import asyncio
import json
import os
import shutil
import sys
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import ExitStack, aclosing, closing
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from typing import cast

from vtuber.contracts.events import Event, RuntimeOutput, canonical_json, new_id, utc_now
from vtuber.contracts.mind import SingleMindPort
from vtuber.contracts.perception import Perception, PerceptionBatch
from vtuber.minds.fake import FakeSingleMind
from vtuber.minds.luna_stream import LunaStream
from vtuber.runtime.journal import Journal
from vtuber.runtime.single_mind import SingleMindRuntime


CHARACTER_ID = 'primary'
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_TEXT_BYTES = 8 * 1024
MAX_DIALOGUE_TEXT_BYTES = 16 * 1024
DIALOGUE_KINDS = ('user.message.completed', 'character.reply.completed',
                  'character.reply.cancelled', 'character.reply.failed')
ACTIVITY_KINDS = (*DIALOGUE_KINDS, 'perception.received', 'character.reply.started')


class ProtocolError(ValueError):
    pass


class StartupError(ValueError):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise StartupError('invalid_arguments')


def _bounded_lines(fd: int) -> Iterator[bytes | None]:
    frame: bytearray | None = bytearray()
    while chunk := os.read(fd, 8192):
        parts = chunk.split(b'\n')
        for index, part in enumerate(parts):
            if frame is not None:
                if len(frame) + len(part) >= MAX_REQUEST_BYTES:
                    frame = None
                else:
                    frame.extend(part)
            if index + 1 < len(parts):
                yield bytes(frame) if frame is not None else None
                frame = bytearray()
    if frame is None or frame:
        yield bytes(frame) if frame is not None else None


async def _input_frames(fd: int) -> AsyncIterator[bytes | None]:
    loop = asyncio.get_running_loop()
    eof = EOFError()
    queue: asyncio.Queue[bytes | None | OSError | EOFError] = asyncio.Queue(maxsize=1)
    consumed = threading.Event()
    stopped = threading.Event()

    def send(value: bytes | None | OSError | EOFError) -> bool:
        if stopped.is_set():
            return False
        try:
            loop.call_soon_threadsafe(queue.put_nowait, value)
        except RuntimeError:
            return False
        consumed.wait()
        consumed.clear()
        return not stopped.is_set()

    def read() -> None:
        try:
            for line in _bounded_lines(fd):
                if not send(line):
                    return
        except OSError as error:
            send(error)
        else:
            send(eof)

    # shortcut: the daemon can exit with a blocked pipe read, use a cancellable transport if embedded.
    threading.Thread(target=read, name='hub-stdin', daemon=True).start()
    try:
        while True:
            item = await queue.get()
            if item is eof:
                return
            if isinstance(item, (OSError, EOFError)):
                raise item
            yield item
            consumed.set()
    finally:
        stopped.set()
        consumed.set()


def _parse_frame(frame: bytes | None) -> dict:
    if frame is None or len(frame.rstrip(b'\n')) >= MAX_REQUEST_BYTES:
        raise ProtocolError('frame_too_large')
    try:
        request = json.loads(frame.decode('utf-8'))
    except (UnicodeError, ValueError, RecursionError):
        raise ProtocolError('invalid_frame') from None
    if not isinstance(request, dict):
        raise ProtocolError('invalid_request')
    return request


def _input_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError('invalid_text')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError:
        raise ProtocolError('invalid_text') from None
    if size > MAX_TEXT_BYTES:
        raise ProtocolError('text_too_large')
    return value


def _bounded_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ''
    # Bound escaping too, so control characters cannot inflate a recent history frame.
    if len(value) <= limit and len(canonical_json(value).encode('utf-8')) <= limit + 2:
        return value
    ellipsis = '…'
    limit -= len(ellipsis.encode('utf-8'))
    low, high = 0, min(len(value), limit)
    while low < high:
        middle = (low + high + 1) // 2
        if len(canonical_json(value[:middle]).encode('utf-8')) <= limit + 2:
            low = middle
        else:
            high = middle - 1
    return value[:low] + ellipsis


def _project(event: Event, text_limit: int) -> dict[str, object]:
    payload = event.payload
    if event.kind == 'perception.received':
        text = payload.get('content')
    elif event.kind in ('character.reply.cancelled', 'character.reply.failed'):
        text = payload.get('reason')
    else:
        text = payload.get('text')
    action = payload.get('action') if event.kind == 'character.reply.completed' else None
    return {'sequence': event.sequence, 'event_id': event.event_id, 'turn_id': event.turn_id,
            'kind': event.kind, 'source': event.source, 'occurred_at': event.occurred_at,
            'text': _bounded_text(text, text_limit),
            'action': action if action in ('speak', 'stay_silent') else None}


def _inspect(runtime: SingleMindRuntime) -> dict[str, object]:
    activity = runtime.journal.recent_events(CHARACTER_ID, kinds=ACTIVITY_KINDS, limit=100)
    dialogue = runtime.journal.recent_events(CHARACTER_ID, kinds=DIALOGUE_KINDS, limit=40)
    return {'snapshot': runtime.snapshot(), 'activity': [_project(event, 512) for event in activity],
            'dialogue': [_project(event, MAX_DIALOGUE_TEXT_BYTES) for event in reversed(dialogue)]}


async def _submit(runtime: SingleMindRuntime, text: str, *, scene: bool) -> dict[str, str] | None:
    perception = Perception(new_id('perception'), 'state' if scene else 'chat',
                            'manual:scene' if scene else 'local', 'local', text, utc_now(),
                            delivery='ambient' if scene else 'direct')
    await runtime.submit_perceptions(PerceptionBatch('local', (perception,), 'immediate'))
    if scene:
        return None
    active = cast(dict[str, str], runtime.snapshot()['runtime'])
    return {'turn_id': active['turn_id']}


async def run_hub(db: Path, mind: SingleMindPort, requests: AsyncIterator[bytes | None],
                  emit: Callable[[dict[str, object]], None]) -> None:
    def output(value: RuntimeOutput) -> None:
        emit({'type': 'output', 'output': asdict(value)})

    with ExitStack() as resources:
        try:
            journal = resources.enter_context(closing(Journal(db)))
            identity = files('vtuber.minds').joinpath('character.md').read_text(encoding='utf-8')
            runtime = SingleMindRuntime(CHARACTER_ID, journal, mind, output, identity=identity)
            await runtime.start()
        except Exception:
            raise StartupError('startup_failed') from None

        try:
            emit({'type': 'ready', 'version': 1})
            async for frame in requests:
                response: dict[str, object] = {'type': 'response', 'id': None}
                stop = False
                try:
                    request = _parse_frame(frame)
                    identifier = request.get('id')
                    if type(identifier) is not int or abs(identifier) >= 2 ** 53:
                        raise ProtocolError('invalid_request')
                    response['id'] = identifier
                    op = request.get('op')
                    if op in ('inspect', 'shutdown') and request.keys() == {'id', 'op'}:
                        stop = op == 'shutdown'
                        if stop:
                            await runtime.close()
                        result = _inspect(runtime)
                    elif op in ('send_chat', 'set_scene') and request.keys() <= {'id', 'op', 'text'}:
                        result = await _submit(runtime, _input_text(request.get('text')), scene=op == 'set_scene')
                    else:
                        raise ProtocolError('invalid_request')
                    response.update(ok=True, result=result)
                except ProtocolError as error:
                    response.update(ok=False, error=str(error))
                except Exception:
                    response.update(ok=False, error='operation_failed')
                emit(response)
                if stop:
                    break
        finally:
            await runtime.close()


def _write(frame: dict[str, object]) -> None:
    data = canonical_json(frame).encode('utf-8') + b'\n'
    if len(data) >= MAX_RESPONSE_BYTES:
        if frame['type'] != 'response':
            raise ValueError('Output frame exceeds the transport limit')
        data = canonical_json({'type': 'response', 'id': frame['id'], 'ok': False,
                               'error': 'response_too_large'}).encode('utf-8') + b'\n'
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


async def _main(db: Path, backend: str, bun_name: str) -> None:
    mind: SingleMindPort = FakeSingleMind()
    if backend == 'luna':
        bun = shutil.which(bun_name)
        if bun is None:
            raise StartupError('bun_not_found')
        bridge = Path(__file__).resolve().parents[2] / 'tools/luna-bridge/bridge.mjs'
        if not bridge.is_file():
            raise StartupError('bridge_not_found')
        mind = LunaStream((bun, '--no-env-file', str(bridge)), reasoning='low')
    try:
        async with aclosing(_input_frames(sys.stdin.fileno())) as requests:
            await run_hub(db, mind, requests, _write)
    finally:
        if isinstance(mind, LunaStream):
            await mind.close()


def main() -> int:
    parser = _ArgumentParser(description='Local Liac Single Mind JSONL transport')
    parser.add_argument('--backend', choices=('fake', 'luna'), default='fake')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--bun', default='bun')
    try:
        args = parser.parse_args()
        asyncio.run(_main(args.db, args.backend, args.bun))
    except StartupError as error:
        _write({'type': 'fatal', 'error': str(error)})
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 1
    except Exception:
        _write({'type': 'fatal', 'error': 'transport_failed'})
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
