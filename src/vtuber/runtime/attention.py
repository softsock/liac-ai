"""Deterministic lifecycle rules; semantic interpretation belongs to Luna."""
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Callable

from vtuber.contracts.attention import AttentionSignal, validate_attention
from vtuber.contracts.deep import DeepRequest, DeepResult, evidence_ids
from vtuber.contracts.events import Event, canonical_json


def attention_key(character_id: str, kind: str, source_event_ids: tuple[str, ...]) -> str:
    return sha256(canonical_json([character_id, kind, sorted(source_event_ids)]).encode()).hexdigest()


def rank_signal(signal: AttentionSignal) -> tuple[int, int, int, str]:
    return (0 if signal.kind in ('boundary', 'correction') else 1,
            ('high', 'normal', 'low').index(signal.significance),
            -signal.observed_through_sequence, signal.signal_id)


def decode_signal(data: dict) -> AttentionSignal:
    return AttentionSignal(**{**data, 'source_event_ids': tuple(data['source_event_ids'])})


def prepare_attention(request: DeepRequest, result: DeepResult, current: tuple[AttentionSignal, ...],
                      get: Callable[[str], Event | None], now: datetime,
                      provenance: dict[str, str]) -> tuple[AttentionSignal, ...]:
    if not isinstance(result.attention, tuple) or len(result.attention) > 16:
        raise ValueError('Invalid attention list')
    character = request.snapshot.state.character_id
    by_id = {s.signal_id: s for s in current}
    captured = {s.signal_id: s for s in request.attention_context}
    by_key = {key: by_id[signal_id] for key, signal_id in provenance.items()}
    changes, touched = [], set()
    stamp = now.isoformat()
    for index, p in enumerate(result.attention):
        validate_attention(p, evidence_ids(request), request.attention_context)
        target = by_id.get(p.target_signal_id)
        affected = p.supersedes + ((p.target_signal_id,) if p.target_signal_id else ())
        for signal_id in affected:
            live = by_id.get(signal_id)
            if (signal_id in touched or live is None or live != captured.get(signal_id)
                    or live.status not in ('noticed', 'deferred')):
                raise ValueError('Attention version conflict')
            if live.expires_at is not None and datetime.fromisoformat(live.expires_at) <= now:
                raise ValueError('Attention expired during analysis')
            touched.add(signal_id)
        sources = tuple(sorted(set(p.source_event_ids) | (set(target.source_event_ids) if target else set())))
        if len(sources) > 32:
            raise ValueError('Attention source limit exceeded')
        events = [get(s) for s in sources]
        if any(e is None or e.character_id != character or e.sequence > request.snapshot.through_sequence
               or e.kind not in ('user.message.completed', 'character.reply.completed') for e in events):
            raise ValueError('Invalid canonical attention source')
        expires = None
        if p.ttl_seconds is not None:
            newest = max(datetime.fromisoformat(e.recorded_at.replace('Z', '+00:00')) for e in events)
            expires = (newest + timedelta(seconds=p.ttl_seconds)).isoformat()
        if target and target.expires_at is not None:
            old_high = max(e.sequence for e in events if e.event_id in target.source_event_ids)
            if max(e.sequence for e in events) <= old_high:
                if expires is None or datetime.fromisoformat(expires) > datetime.fromisoformat(target.expires_at):
                    expires = target.expires_at
        key = attention_key(character, p.kind, sources)
        duplicate = by_key.get(key)
        if duplicate is not None and (target is None or duplicate.signal_id != target.signal_id):
            # Wording is not identity. A later interpretation must target the existing row.
            if target is not None:
                raise ValueError('Attention provenance conflict')
            if p.supersedes:
                raise ValueError('Duplicate attention cannot supersede signals')
            continue
        status = {'notice': 'noticed', 'defer': 'deferred', 'ignore': 'ignored'}[p.outcome]
        if expires is not None and datetime.fromisoformat(expires) <= now:
            status = 'expired'
        signal = AttentionSignal(target.signal_id if target else f'{request.request_id}:attention:{index}',
            character, target.version + 1 if target else 1, p.kind, p.significance, p.outcome, p.reason,
            sources, status, request.snapshot.through_sequence, target.created_at if target else stamp, stamp, expires)
        by_key[key] = signal
        by_id[signal.signal_id] = signal
        changes.append(signal)
        for signal_id in p.supersedes:
            old = by_id[signal_id]
            changes.append(replace(old, status='superseded', version=old.version + 1, updated_at=stamp))
    return tuple(changes)
