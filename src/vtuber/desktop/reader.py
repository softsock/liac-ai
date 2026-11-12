"""Disk reads off the GUI thread, with generation IDs to discard stale selections."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from vtuber.tracing import read_trace


class TraceReader(QObject):
    loaded = Signal(int, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.token = 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='liac-trace-read')
        self.futures = []

    def load(self, function):
        self.token += 1
        for future in self.futures:
            future.cancel()
        self.futures = [future for future in self.futures if not future.done()]
        self.futures.append(self.executor.submit(self._read, self.token, function))
        return self.token

    def _read(self, token, function):
        try:
            result, error = function(), ''
        except Exception as exc:
            result, error = None, f'{type(exc).__name__}: {exc}'
        self.loaded.emit(token, result, error)

    @property
    def busy(self):
        return any(not future.done() for future in self.futures)

    def stop(self):
        self.token += 1
        self.executor.shutdown(wait=False, cancel_futures=True)

    def join(self):
        # All reads finished before this call; only retire the idle Python thread.
        self.executor.shutdown(wait=True)


def details(records):
    return [json.loads((Path(record['path']) / record['row']['file']).read_text(encoding='utf-8'))
            for record in records]


def history(path):
    return [{'row': row, 'path': str(path)} for row in read_trace(Path(path))]
