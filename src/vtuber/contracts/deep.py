"""Versioned immutable Deep work and deterministic application decisions."""
from dataclasses import dataclass
import math

from vtuber.contracts.context import CompactionProposal, CompactionResult
from vtuber.contracts.events import Event
from vtuber.contracts.state import FastSnapshot, NoteProposal, UpdateResult


class DeepUnavailable(RuntimeError):
    """Provider requires an external change; do not automatically retry this cycle."""


@dataclass(frozen=True)
class CompactionInput:
    cutoff: int
    events: tuple[Event, ...]


def validate_initiative_timing(delay: float, ttl: float, cooldown: float = 0) -> None:
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (delay, ttl, cooldown))
            or not 0 <= delay < ttl or cooldown < 0):
        raise ValueError('Require finite 0 <= initiative delay < TTL and nonnegative cooldown')


@dataclass(frozen=True)
class InitiativeProposal:
    intent: str
    reason: str
    source_event_ids: tuple[str, ...]
    delay_seconds: float | None = None
    ttl_seconds: float | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(v, str) or not v.strip() or len(v) > 1000
               for v in (self.intent, self.reason)):
            raise ValueError('Invalid initiative text')
        sources = self.source_event_ids
        if (not isinstance(sources, tuple) or not 1 <= len(sources) <= 32
                or any(not isinstance(s, str) or not s.strip() for s in sources)
                or len(set(sources)) != len(sources)):
            raise ValueError('Invalid initiative sources')
        delay, ttl = self.delay_seconds, self.ttl_seconds
        if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v)) for v in (delay, ttl)):
            raise ValueError('Invalid initiative timing')
        if delay is not None:
            validate_initiative_timing(delay, ttl if ttl is not None else max(120, delay + 1))
        if ttl is not None:
            validate_initiative_timing(delay if delay is not None else 0, ttl)


@dataclass(frozen=True)
class InitiativeCancel:
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip() or len(self.reason) > 1000:
            raise ValueError('Invalid initiative cancellation')


@dataclass(frozen=True)
class DeepRequest:
    request_id: str
    snapshot: FastSnapshot
    cursor_from: int
    events: tuple[Event, ...]
    compaction: CompactionInput | None = None
    working_context_tokens: int = 2048
    initiative_allowed: bool = False
    captured_at: str = ''
    initiative_delay_seconds: float = 5.0
    initiative_ttl_seconds: float = 120.0


@dataclass(frozen=True)
class DeepResult:
    schema_version: int
    request_id: str
    note: NoteProposal | None = None
    compaction: CompactionProposal | None = None
    initiative: InitiativeProposal | InitiativeCancel | None = None


@dataclass(frozen=True)
class DeepDecision:
    request_id: str
    note: UpdateResult | None
    compaction: CompactionResult | None
    acknowledged: bool
    reason: str
    initiative_reason: str | None = None


def evidence_ids(request: DeepRequest) -> set[str]:
    events = request.events + request.snapshot.recent_dialogue
    if request.compaction:
        events += request.compaction.events
    return {e.event_id for e in events if e.kind in ('user.message.completed', 'character.reply.completed')} | {
        source for item in request.snapshot.epoch.items for source in item.source_event_ids}
