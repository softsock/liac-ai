"""Private append-only request snapshots; never a source of domain truth."""
import json
import re
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


def read_trace(path: Path) -> list[dict]:
    index = path / 'index.jsonl'
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
