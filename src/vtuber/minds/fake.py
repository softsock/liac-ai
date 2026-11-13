import asyncio
import re
from dataclasses import dataclass
from typing import AsyncGenerator

from vtuber.contracts.events import UserMessage, FastInput
from vtuber.contracts.state import FastSnapshot, NoteProposal
from vtuber.contracts.deep import DeepRequest, DeepResult


@dataclass(frozen=True)
class FakeFast:
    delay: float = 0.03

    async def stream(self, snapshot: FastSnapshot, message: FastInput) -> AsyncGenerator[str, None]:
        origin = f'You said: {message.text}' if isinstance(message, UserMessage) else f'Character initiative: {message.intent}'
        text = (f"[r{snapshot.state.revision}] {origin} | "
                f"note: {snapshot.state.context_note or '(none)'}")
        for chunk in re.findall(r"\S+\s*", text):
            await asyncio.sleep(self.delay)
            yield chunk


@dataclass(frozen=True)
class FakeDeep:
    delay: float = 2.0

    async def propose(self, request: DeepRequest) -> DeepResult:
        await asyncio.sleep(self.delay)
        state, events = request.snapshot.state, request.events
        messages = [event for event in events if event.kind == "user.message.completed"]
        if not messages:
            return DeepResult(1, request.request_id)
        latest = messages[-1]
        return DeepResult(1, request.request_id, NoteProposal(
            request.request_id + ':note',
            state.character_id, state.revision, events[-1].sequence,
            (latest.event_id,), f"Last user message: {latest.payload['text'][:160]}"))
