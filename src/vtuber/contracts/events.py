"""Frozen journal envelopes and ephemeral output; no provider or storage imports."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping
from uuid import uuid4

type CharacterId = str
type EventId = str
type TurnId = str


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class Event:
    event_id: EventId
    character_id: CharacterId
    kind: str
    source: str
    occurred_at: str
    payload_json: str
    turn_id: TurnId | None = None
    causation_id: EventId | None = None
    schema_version: int = 1
    sequence: int = 0
    recorded_at: str | None = None

    def __post_init__(self) -> None:
        for value in (self.event_id, self.character_id, self.kind, self.source):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Event identifiers, kind and source must be nonempty strings")
        if self.schema_version != 1:
            raise ValueError("Unsupported event schema version")
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("Event payload must be a JSON object")
        object.__setattr__(self, "payload_json", canonical_json(payload))

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    @classmethod
    def create(cls, character_id: CharacterId, kind: str, payload: Mapping[str, Any],
               *, source: str = "runtime", event_id: EventId | None = None,
               turn_id: TurnId | None = None, causation_id: EventId | None = None,
               occurred_at: str | None = None) -> "Event":
        return cls(event_id or new_id("evt"), character_id, kind, source,
                   occurred_at or utc_now(), canonical_json(payload), turn_id, causation_id)


@dataclass(frozen=True)
class UserMessage:
    text: str
    character_id: CharacterId = "primary"
    event_id: EventId = field(default_factory=lambda: new_id("evt"))
    turn_id: TurnId = field(default_factory=lambda: new_id("turn"))
    occurred_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Message text must be nonempty")
        if not isinstance(self.turn_id, str) or not self.turn_id.strip():
            raise ValueError("Turn ID must be nonempty")

    def as_event(self) -> Event:
        return Event.create(self.character_id, "user.message.completed", {"text": self.text},
                            source="user", event_id=self.event_id, turn_id=self.turn_id,
                            occurred_at=self.occurred_at)


type OutputKind = Literal["reply.started", "reply.delta", "reply.completed",
                          "reply.cancelled", "reply.failed", "deep.completed", "deep.failed"]


@dataclass(frozen=True)
class RuntimeOutput:
    kind: OutputKind
    character_id: CharacterId
    revision: int
    turn_id: TurnId | None = None
    text: str = ""
    delta_index: int = 0
