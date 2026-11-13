"""Luna's bounded data protocol; model output never supplies authority metadata."""
from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vtuber.minds.omp import OMPTransport

import json

from vtuber.contracts.context import CompactionProposal, ContextItem
from vtuber.contracts.deep import DeepRequest, DeepResult, evidence_ids
from vtuber.contracts.events import canonical_json
from vtuber.contracts.state import NoteProposal
from vtuber.contracts.trace import TraceSink, emit_trace


def _object(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or value.keys() != keys:
        raise ValueError('Unexpected Deep fields')
    return value


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit or len(value) > limit:
        raise ValueError('Invalid Deep text')
    return value


def _sources(value: object, evidence: set[str]) -> tuple[str, ...]:
    if (not isinstance(value, list) or not 1 <= len(value) <= 32
            or any(not isinstance(s, str) or s not in evidence for s in value)
            or len(set(value)) != len(value)):
        raise ValueError('Invalid Deep evidence')
    return tuple(value)


def parse_result(text: str, request: DeepRequest) -> DeepResult:
    if len(text.encode('utf-8')) > 65536:
        raise ValueError('Deep response too large')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate Deep field')
            result[key] = value
        return result

    def invalid(value):
        raise ValueError('Nonfinite Deep value')

    data = _object(json.loads(text, object_pairs_hook=pairs, parse_constant=invalid),
                   {'schema_version', 'note', 'compaction'})
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise ValueError('Unsupported Deep schema')
    snapshot = request.snapshot
    evidence = evidence_ids(request)
    note = None
    if data['note'] is not None:
        value = _object(data['note'], {'text', 'source_event_ids'})
        text = value['text']
        if not isinstance(text, str) or len(text.encode('utf-8')) > 32768:
            raise ValueError('Invalid working context')
        note = NoteProposal(request.request_id + ':note', snapshot.state.character_id,
            snapshot.state.revision, snapshot.through_sequence,
            _sources(value['source_event_ids'], evidence), text)
    compaction = None
    if data['compaction'] is not None:
        if request.compaction is None:
            raise ValueError('Unrequested compaction')
        values = _object(data['compaction'], {'items'})['items']
        if not isinstance(values, list) or not 1 <= len(values) <= 32:
            raise ValueError('Invalid Deep items')
        sources = {e.event_id for e in request.compaction.events
                   if e.sequence <= request.compaction.cutoff
                   and e.kind in ('user.message.completed', 'character.reply.completed')}
        items = []
        for value in values:
            value = _object(value, {'text', 'source_event_ids', 'kind'})
            if value['kind'] != 'summary':
                raise ValueError('Unsupported Deep item kind')
            items.append(ContextItem(_text(value['text'], 8000),
                _sources(value['source_event_ids'], sources), 'summary'))
        compaction = CompactionProposal(request.request_id + ':epoch', snapshot.state.character_id,
            snapshot.epoch.version, snapshot.state.revision, snapshot.through_sequence,
            request.compaction.cutoff, tuple(items))
    return DeepResult(1, request.request_id, note, compaction)


def render_request(request: DeepRequest) -> str:
    return canonical_json(asdict(request))


class LunaDeep:
    def __init__(self, transport: OMPTransport, identity: str, *, trace: TraceSink | None = None) -> None:
        self.transport = transport
        self.identity = identity
        self.trace = trace

    async def propose(self, request: DeepRequest) -> DeepResult:
        # Identity is authored separately from all untrusted canonical evidence.
        prompt = render_request(request)
        emit_trace(self.trace, 'deep.prompt', request.request_id, prompt=prompt)
        if self.trace is None:
            text = await self.transport.request(prompt)
        else:
            text = await self.transport.request(prompt, request_id=request.request_id)
        emit_trace(self.trace, 'deep.response', request.request_id, text=text)
        return parse_result(text, request)
