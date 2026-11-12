"""Versioned immutable Deep work and deterministic application decisions."""
from dataclasses import dataclass

from vtuber.contracts.context import CompactionProposal, CompactionResult
from vtuber.contracts.events import Event
from vtuber.contracts.state import FastSnapshot, NoteProposal, UpdateResult


class DeepUnavailable(RuntimeError):
    """Provider requires an external change; do not automatically retry this cycle."""


@dataclass(frozen=True)
class CompactionInput:
    cutoff: int
    events: tuple[Event, ...]


@dataclass(frozen=True)
class DeepRequest:
    request_id: str
    snapshot: FastSnapshot
    cursor_from: int
    events: tuple[Event, ...]
    compaction: CompactionInput | None = None


@dataclass(frozen=True)
class DeepResult:
    schema_version: int
    request_id: str
    note: NoteProposal | None = None
    compaction: CompactionProposal | None = None


@dataclass(frozen=True)
class DeepDecision:
    request_id: str
    note: UpdateResult | None
    compaction: CompactionResult | None
    acknowledged: bool
    reason: str


def evidence_ids(request: DeepRequest) -> set[str]:
    events = request.events + request.snapshot.recent_dialogue
    if request.compaction:
        events += request.compaction.events
    return {e.event_id for e in events if e.kind in ('user.message.completed', 'character.reply.completed')} | {
        source for item in request.snapshot.epoch.items for source in item.source_event_ids}
