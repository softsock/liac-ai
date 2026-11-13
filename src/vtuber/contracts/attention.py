"""Attention observations are evidence-backed possibilities, never speech commands."""
from dataclasses import dataclass
from typing import Literal

AttentionKind = Literal['topic_change', 'mood_change', 'callback', 'open_loop',
                        'correction', 'boundary', 'opportunity', 'other']
AttentionSignificance = Literal['low', 'normal', 'high']
AttentionOutcome = Literal['notice', 'defer', 'ignore']
AttentionStatus = Literal['noticed', 'deferred', 'ignored', 'superseded', 'expired']
KINDS = ('topic_change', 'mood_change', 'callback', 'open_loop', 'correction', 'boundary', 'opportunity', 'other')
SIGNIFICANCE = ('low', 'normal', 'high')
OUTCOMES = ('notice', 'defer', 'ignore')
STATUSES = ('noticed', 'deferred', 'ignored', 'superseded', 'expired')


@dataclass(frozen=True)
class AttentionProposal:
    kind: AttentionKind
    significance: AttentionSignificance
    outcome: AttentionOutcome
    reason: str
    source_event_ids: tuple[str, ...]
    ttl_seconds: int | None = None
    target_signal_id: str | None = None
    target_version: int | None = None
    supersedes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AttentionSignal:
    signal_id: str
    character_id: str
    version: int
    kind: AttentionKind
    significance: AttentionSignificance
    outcome: AttentionOutcome
    reason: str
    source_event_ids: tuple[str, ...]
    status: AttentionStatus
    observed_through_sequence: int
    created_at: str
    updated_at: str
    expires_at: str | None


@dataclass(frozen=True)
class AttentionView:
    through_sequence: int
    signals: tuple[AttentionSignal, ...]


def validate_attention(proposal: AttentionProposal, evidence: set[str],
                       context: tuple[AttentionSignal, ...]) -> None:
    """Shared shape/captured-evidence check; Journal additionally checks live rows."""
    p = proposal
    if (not isinstance(p, AttentionProposal) or p.kind not in KINDS
            or p.significance not in SIGNIFICANCE or p.outcome not in OUTCOMES
            or not isinstance(p.reason, str) or not 1 <= len(p.reason.strip()) <= 1000
            or len(p.reason) > 1000):
        raise ValueError('Invalid attention fields')
    if (not isinstance(p.source_event_ids, tuple) or not 1 <= len(p.source_event_ids) <= 32
            or any(not isinstance(s, str) or s not in evidence for s in p.source_event_ids)
            or len(set(p.source_event_ids)) != len(p.source_event_ids)):
        raise ValueError('Invalid attention sources')
    if p.ttl_seconds is not None and (type(p.ttl_seconds) is not int or not 1 <= p.ttl_seconds <= 86400):
        raise ValueError('Invalid attention TTL')
    available = {s.signal_id: s for s in context if s.status in ('noticed', 'deferred')}
    if p.target_signal_id is None:
        if p.target_version is not None:
            raise ValueError('Unexpected attention version')
    elif (not isinstance(p.target_signal_id, str) or p.target_signal_id not in available
          or type(p.target_version) is not int or p.target_version != available[p.target_signal_id].version
          or p.kind != available[p.target_signal_id].kind):
        raise ValueError('Invalid attention target')
    if (not isinstance(p.supersedes, tuple) or len(p.supersedes) > 32
            or any(not isinstance(s, str) or s not in available or s == p.target_signal_id for s in p.supersedes)
            or len(set(p.supersedes)) != len(p.supersedes)):
        raise ValueError('Invalid attention supersession')
