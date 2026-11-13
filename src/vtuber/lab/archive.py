"""Bounded run observations and provider-free historical inspection."""
import asyncio
import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path
from time import monotonic

from vtuber.app import Config
from vtuber.contracts.events import canonical_json, utc_now
from vtuber.tracing import QueuedTraceRecorder, read_trace


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    temporary.replace(path)


def owned(path: Path, relative: str) -> Path:
    target = (path / relative).resolve()
    if not target.is_relative_to(path.resolve()):
        raise ValueError('Archive path points outside this run')
    return target


class RunArchive:
    @classmethod
    def create(cls, root: Path, config: Config, *, scenario: dict | None = None,
               seed: int | None = None) -> 'RunArchive':
        trace = QueuedTraceRecorder(root)
        try:
            version = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True,
                                     text=True, timeout=3).stdout.strip()
            dirty = bool(subprocess.run(['git', 'status', '--porcelain'], capture_output=True,
                                        text=True, timeout=3).stdout)
            manifest = dict(schema_version=1, started_at=utc_now(), status='running',
                            code_sha=version, dirty=dirty, config=asdict(config), scenario=scenario,
                            seed=seed, segments=['.'], elapsed_seconds=0, turns=0,
                            provenance='Recorded history; remote inference is not deterministic')
            return cls(trace.path, trace, manifest)
        except BaseException:
            trace._closed = True
            trace.thread.join()
            raise

    @classmethod
    def resume(cls, path: Path) -> 'RunArchive':
        manifest = json.loads((path/'run.json').read_text(encoding='utf-8'))
        if manifest.get('schema_version') != 1 or manifest.get('status') == 'completed':
            raise ValueError('Only stopped or interrupted simulation runs can resume')
        if not manifest.get('scenario') or not (path/'runtime.sqlite3').is_file():
            raise ValueError('This is not a resumable simulation')
        # Acquire ownership before creating another capture segment.
        archive = cls(path, None, manifest)
        try:
            used = sum(file.stat().st_size for segment in manifest.get('segments',['.'])
                       for file in owned(path,segment).glob('*.json*') if file.is_file())
            archive.trace = QueuedTraceRecorder(path/'segments',max_bytes=max(0,128*1024*1024-used))
            manifest['segments'].append(str(archive.trace.path.relative_to(path)))
            manifest['status'] = 'running'
            write_json(path/'run.json', manifest)
            return archive
        except BaseException:
            archive._lease.close()
            raise

    def __init__(self, path, trace, manifest):
        self.path, self.trace, self.manifest = path, trace, manifest
        self.db = path/'runtime.sqlite3'
        self._lease = (path/'.owner').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self._lease.seek(0)
                if self._lease.read(1) == b'':
                    self._lease.write(b'1')
                    self._lease.flush()
                self._lease.seek(0)
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self._lease.close()
            raise ValueError('Run already has an owner')
        self._cursor = 0
        self._started = monotonic()
        self._previous_elapsed = manifest.get('elapsed_seconds', 0)
        self.origins = {}
        self._closed = False
        write_json(path/'run.json', manifest)

    def observe_output(self, output):
        self.trace('runtime.output', output.turn_id or 'runtime', asdict(output))

    def input(self, message, origin='manual', session=1):
        self.origins[message.turn_id] = origin
        self.trace('conversation.input', message.turn_id,
                   dict(text=message.text, origin=origin, session=session, event_id=message.event_id))

    async def capture(self, runtime):
        while True:
            events = runtime.journal.read(runtime.character_id, after=self._cursor, limit=200)
            for event in events:
                self.trace(event.kind if event.kind.startswith('initiative.') else 'runtime.journal',
                           event.turn_id or event.event_id, {'event':asdict(event)})
            if not events:
                break
            self._cursor = events[-1].sequence
        status = dict(state=asdict(runtime.journal.snapshot(runtime.character_id)),
                      epoch=asdict(runtime.journal.context_epoch(runtime.character_id)),
                      deep_cursor=runtime.journal.cursor(runtime.character_id),
                      journal_sequence=runtime.journal.high_watermark(runtime.character_id),
                      fast=runtime.fast_diagnostics, deep=runtime.deep_diagnostics,
                      pending=asdict(p) if (p := runtime.journal.pending_initiative(runtime.character_id)) else None)
        # Record status transitions, not an identical large snapshot every poll.
        fingerprint = canonical_json(status)
        if fingerprint != getattr(self, '_last_status', None):
            self._last_status = fingerprint
            self.trace('runtime.status', runtime.character_id, status)
        return status

    async def close(self, status: str, reason: str | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.trace:
                await self.trace.aclose()
            self.manifest.update(status=status, reason=reason, ended_at=utc_now(),
                elapsed_seconds=self._previous_elapsed+monotonic()-self._started,
                capture_error=self.trace.error if self.trace else None,
                omitted_records=self.trace.dropped if self.trace else 0)
            await asyncio.to_thread(write_json, self.path/'run.json', self.manifest)
        finally:
            self._lease.close()


class RunReader:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        manifest = owned(self.path,'run.json')
        if manifest.exists() and manifest.stat().st_size > 512*1024:
            raise ValueError('Run manifest exceeds 512 KiB')
        self.manifest = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
        if self.manifest and self.manifest.get('schema_version') != 1:
            raise ValueError('Unsupported run manifest')
        self.rows, self.conversation, self.contexts = [], [], []
        self._requests, self._turn_requests = {}, {}
        self._inputs, self._origins = {}, {}
        self._seen_events = set()
        self._context_order = 0
        self._session = 1
        for segment in self.manifest.get('segments', ['.']):
            folder = owned(self.path, segment)
            for row in read_trace(folder):
                record = dict(row, path=str(folder), ordinal=len(self.rows))
                self.rows.append(record)
                self._requests.setdefault(row['request_id'], []).append(record)
                data = self.load(record)['data']
                self._index(record, data)
        self.conversation.sort(key=lambda r: r['order'])

    @staticmethod
    def load(row):
        target = owned(Path(row['path']), row['file'])
        if target.stat().st_size > 3*1024*1024:
            return dict(row, data={'omitted':True, 'reason':'Preview file exceeds 3 MiB'})
        return json.loads(target.read_text(encoding='utf-8'))

    def _context(self, record, snapshot):
        if isinstance(snapshot, dict) and 'state' in snapshot and 'epoch' in snapshot:
            self.contexts.append(dict(sequence=snapshot.get('through_sequence', 0),
                ordinal=record['ordinal'], snapshot=snapshot, time=record['time']))

    def _index(self, row, data):
        kind, rid = row['kind'], row['request_id']
        if kind == 'conversation.input':
            self._origins[rid] = data
            self._session = data.get('session',self._session)
        if kind == 'fast.started':
            message = data.get('message', {})
            self._inputs[rid] = message
            if proposal := message.get('proposal_id'):
                self._turn_requests.setdefault(rid,set()).add(proposal.removeprefix('initiative_'))
            self._context(row, data.get('snapshot'))
            if 'text' in message:
                meta = self._origins.get(rid, {})
                self.conversation.append(dict(turn_id=rid, text=message['text'], role='user',
                    origin=meta.get('origin','manual'), session=meta.get('session',1), status='completed',
                    order=row['ordinal'], time=row['time']))
        elif kind == 'fast.finished':
            self.conversation.append(dict(turn_id=rid, text=data.get('text') or data.get('partial',''),
                role='assistant', origin='initiative' if 'proposal_id' in self._inputs.get(rid,{}) else 'reply',
                status=data.get('status','unknown'), reason=data.get('reason',''),
                order=row['ordinal'], time=row['time'],
                session=self._origins.get(rid,{}).get('session',self._session)))
        elif kind == 'deep.started':
            request = data.get('request', {})
            for event in request.get('events', []):
                if turn := event.get('turn_id'):
                    self._turn_requests.setdefault(turn, set()).add(rid)
            self._context(row, request.get('snapshot'))
        elif kind == 'deep.decision':
            self._context(row, data.get('after'))
        elif kind in ('runtime.lifecycle', 'runtime.context'):
            self._context(row, data.get('snapshot'))
        elif kind == 'runtime.epoch' and isinstance(data.get('after'), dict):
            # Old traces supply epoch-only transitions; never invent the accompanying Markdown.
            pass
        elif kind == 'runtime.journal' or kind.startswith('initiative.'):
            event = data.get('event', {})
            if event.get('kind','').startswith('initiative.'):
                if event['kind']=='initiative.proposed':
                    self._turn_requests.setdefault(rid,set()).add(event['event_id'].removeprefix('initiative_'))
                for candidate in (event.get('causation_id'), event.get('event_id')):
                    if candidate:
                        self._turn_requests.setdefault(candidate, set()).add(rid)
        elif kind == 'simulator.boundary':
            self.conversation.append(dict(turn_id=rid, role='boundary', origin='simulator',
                text=data.get('reason','Session boundary'), status='boundary',
                session=data.get('session'), order=row['ordinal'], time=row['time']))
            self._session = data.get('session',self._session)+1

    def page(self, kind: str, *, offset: int = 0, limit: int = 200) -> list[dict]:
        if offset < 0 or not 0 < limit <= 1000:
            raise ValueError('Invalid page bounds')
        source = {'conversation':self.conversation, 'timeline':self.rows, 'context':self.contexts}[kind]
        return source[offset:offset+limit]

    def related(self, turn_id: str) -> list[dict]:
        requests = {turn_id} | self._turn_requests.get(turn_id,set())
        records = [r for rid in requests for r in self._requests.get(rid,[])]
        return [dict(self.load(r), path=r['path']) for r in sorted(records,key=lambda r:r['ordinal'])]

    def context_at(self, sequence: int) -> dict:
        candidates = [r for r in self.contexts if r['sequence'] <= sequence]
        if not candidates:
            return {'status':'unavailable', 'reason':'No historical context captured'}
        best = max(candidates, key=lambda r:(r['sequence'],r['ordinal']))
        snapshot = best['snapshot']
        return dict(status='partial' if self.manifest.get('capture_error') else 'captured',
                    markdown=snapshot['state']['context_note'], epoch=snapshot['epoch'],
                    revision=snapshot['state']['revision'], sequence=best['sequence'])

    def summary(self) -> dict:
        from vtuber.lab.report import summarize_run
        return summarize_run(self)
