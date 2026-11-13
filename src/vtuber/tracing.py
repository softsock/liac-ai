"""Private append-only request snapshots; never a source of domain truth."""
import json
import re
import asyncio
from queue import Queue, Empty, Full
from threading import Lock, Thread
from pathlib import Path
from uuid import uuid4

from vtuber.contracts.events import canonical_json, utc_now


class TraceRecorder:
    def __init__(self, root: Path, max_bytes: int = 128 * 1024 * 1024, on_record=None) -> None:
        self.path = root / ('run-' + uuid4().hex)
        self.max_bytes = max_bytes
        self.on_record = on_record
        self.error: str | None = None
        self._bytes = 0
        self._sequence = 0
        try:
            self.path.mkdir(parents=True)
        except OSError as error:
            self.error = f'Trace capture stopped ({type(error).__name__}). Chat continues.'

    def __call__(self, kind: str, request_id: str, data: dict[str, object]) -> None:
        if self.error:
            return
        try:
            sequence = self._sequence + 1
            row = dict(sequence=sequence, time=utc_now(), kind=kind, request_id=request_id,
                       file=f'{sequence:08d}.json')
            payload = canonical_json({**row, 'data': data}).encode('utf-8')
            index = (canonical_json(row) + '\n').encode('utf-8')
            if self._bytes + len(payload) + len(index) > self.max_bytes:
                self.error = 'Trace storage limit reached; capture stopped. Chat continues.'
                return
            target = self.path / row['file']
            temporary = target.with_suffix('.tmp')
            temporary.write_bytes(payload)
            temporary.replace(target)
            with (self.path / 'index.jsonl').open('ab') as stream:
                stream.write(index)
            self._sequence = sequence
            self._bytes += len(payload) + len(index)
            if self.on_record:
                self.on_record(row)
        except (OSError, ValueError, TypeError) as error:
            self.error = f'Trace capture stopped ({type(error).__name__}). Chat continues.'


class QueuedTraceRecorder:
    """Freeze observations promptly; one owned thread performs all file writes."""

    def __init__(self, root: Path, max_bytes: int = 128 * 1024 * 1024, on_record=None) -> None:
        self.recorder = TraceRecorder(root, max_bytes, on_record)
        self.path = self.recorder.path
        self.queue = Queue(maxsize=256)
        self._lock = Lock()
        self._pending_bytes = 0
        self._error = None
        self._closed = False
        self.dropped = 0
        self.thread = Thread(target=self._write, name='liac-trace-write', daemon=True)
        self.thread.start()

    @property
    def error(self):
        return self._error or self.recorder.error

    @property
    def on_record(self):
        return self.recorder.on_record

    @on_record.setter
    def on_record(self, callback):
        self.recorder.on_record = callback

    def __call__(self, kind: str, request_id: str, data: dict[str, object]) -> None:
        if self.error or self._closed:
            self.dropped += 1
            return
        payload = canonical_json({**data, 'captured_at': utc_now()}).encode('utf-8')
        if len(payload) > 2 * 1024 * 1024:
            self.dropped += 1
            payload = canonical_json({'omitted': True, 'reason': 'record exceeds 2 MiB',
                                      'captured_at': utc_now()}).encode('utf-8')
        with self._lock:
            if self._pending_bytes + len(payload) > 8 * 1024 * 1024:
                self._error = 'Trace queue limit reached; capture stopped. Chat continues.'
                self.dropped += 1
                return
            try:
                self.queue.put_nowait((kind, request_id, payload))
                self._pending_bytes += len(payload)
            except Full:
                self._error = 'Trace queue limit reached; capture stopped. Chat continues.'
                self.dropped += 1

    def _write(self):
        while True:
            try:
                kind, request_id, payload = self.queue.get(timeout=.05)
            except Empty:
                if self._closed:
                    return
                continue
            try:
                self.recorder(kind, request_id, json.loads(payload))
            except Exception as error:
                self._error = f'Trace capture stopped ({type(error).__name__}). Chat continues.'
            finally:
                with self._lock:
                    self._pending_bytes -= len(payload)
                self.queue.task_done()

    async def aclose(self) -> None:
        self._closed = True
        await asyncio.to_thread(self.thread.join)


def read_trace(path: Path) -> list[dict]:
    index = path / 'index.jsonl'
    if index.resolve().parent != path.resolve():
        raise ValueError('Trace index points outside this run')
    if not index.exists():
        return []
    rows = []
    with index.open(encoding='utf-8') as stream:
        for line in stream:
            if not line.endswith('\n'):
                break  # A writer/crash may leave an unfinished final record.
            row = json.loads(line)
            if (not isinstance(row, dict) or not isinstance(row.get('file'), str)
                    or not re.fullmatch(r'[0-9]{8,}\.json', row['file'])
                    or any(not isinstance(row.get(key), str) for key in ('kind', 'request_id', 'time'))
                    or type(row.get('sequence')) is not int):
                raise ValueError('Invalid trace index record')
            if (path / row['file']).resolve().parent != path.resolve():
                raise ValueError('Trace file points outside this run')
            if (path / row['file']).is_file():
                rows.append(row)
    return rows
