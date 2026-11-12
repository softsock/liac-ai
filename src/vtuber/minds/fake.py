import asyncio
import re
from dataclasses import dataclass
from typing import AsyncGenerator

from vtuber.contracts.events import Event, UserMessage
from vtuber.contracts.state import CharacterState, FastSnapshot, NoteProposal


@dataclass(frozen=True)
class FakeFast:
    delay: float = 0.03

    async def stream(self, snapshot: FastSnapshot, message: UserMessage) -> AsyncGenerator[str, None]:
        text = (f"[r{snapshot.state.revision}] You said: {message.text} | "
                f"note: {snapshot.state.context_note or '(none)'}")
        for chunk in re.findall(r"\S+\s*", text):
            await asyncio.sleep(self.delay)
            yield chunk


@dataclass(frozen=True)
class FakeDeep:
    delay: float = 2.0

    async def propose(self, state: CharacterState, events: tuple[Event, ...]) -> NoteProposal | None:
        await asyncio.sleep(self.delay)
        messages = [event for event in events if event.kind == "user.message.completed"]
        if not messages:
            return None
        latest = messages[-1]
        return NoteProposal(
            f"deep_{state.character_id}_{events[0].sequence}_{events[-1].sequence}",
            state.character_id, state.revision, events[-1].sequence,
            (latest.event_id,), f"Last user message: {latest.payload['text'][:160]}")
