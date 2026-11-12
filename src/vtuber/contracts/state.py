from dataclasses import dataclass

from vtuber.contracts.events import CharacterId, Event, EventId


@dataclass(frozen=True)
class CharacterState:
    character_id: CharacterId
    revision: int = 0
    context_note: str = ""


@dataclass(frozen=True)
class FastSnapshot:
    state: CharacterState
    through_sequence: int
    recent_dialogue: tuple[Event, ...]


@dataclass(frozen=True)
class NoteProposal:
    proposal_id: str
    character_id: CharacterId
    based_on_revision: int
    observed_through_sequence: int
    source_event_ids: tuple[EventId, ...]
    note: str


@dataclass(frozen=True)
class UpdateResult:
    accepted: bool
    revision: int
    reason: str
