"""Immutable, provider-independent context epochs and asynchronous proposals."""

from dataclasses import dataclass
from typing import Literal

from vtuber.contracts.events import CharacterId, EventId


class ContextBudgetExceeded(ValueError):
    """Required content or an uncompactable live turn cannot fit."""


@dataclass(frozen=True)
class ContextItem:
    text: str
    source_event_ids: tuple[EventId, ...]
    kind: Literal["extract", "summary"] = "extract"
    truncated: bool = False


@dataclass(frozen=True)
class ContextEpoch:
    version: int = 0
    compacted_through_sequence: int = 0
    items: tuple[ContextItem, ...] = ()


@dataclass(frozen=True)
class CompactionProposal:
    proposal_id: str
    character_id: CharacterId
    based_on_epoch: int
    based_on_revision: int
    observed_through_sequence: int
    compacted_through_sequence: int
    items: tuple[ContextItem, ...]


@dataclass(frozen=True)
class CompactionResult:
    accepted: bool
    epoch_version: int
    reason: str
