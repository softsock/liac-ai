from typing import AsyncGenerator, Protocol

from vtuber.contracts.events import Event, RuntimeOutput, UserMessage
from vtuber.contracts.state import CharacterState, FastSnapshot, NoteProposal
from vtuber.contracts.context import CompactionProposal


class ContextPolicy(Protocol):
    def prepare_epoch(self, snapshot: FastSnapshot, message: UserMessage) -> CompactionProposal | None: ...

    def validate_compaction(self, snapshot: FastSnapshot, proposal: CompactionProposal) -> None: ...


class FastMind(Protocol):
    def stream(self, snapshot: FastSnapshot, message: UserMessage) -> AsyncGenerator[str, None]: ...


class DeepMind(Protocol):
    async def propose(self, state: CharacterState,
                      events: tuple[Event, ...]) -> NoteProposal | None: ...


class OutputSink(Protocol):
    def __call__(self, output: RuntimeOutput, /) -> None:
        """Consume a notification promptly; never change domain state here."""
        ...
