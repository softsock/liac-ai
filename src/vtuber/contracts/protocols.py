from typing import AsyncGenerator, Protocol

from vtuber.contracts.events import RuntimeOutput, FastInput
from vtuber.contracts.state import FastSnapshot
from vtuber.contracts.context import CompactionProposal
from vtuber.contracts.deep import DeepRequest, DeepResult


class ContextPolicy(Protocol):
    @property
    def input_limit(self) -> int: ...

    @property
    def working_context_tokens(self) -> int: ...

    def validate_working_context(self, text: str) -> None: ...

    def input_tokens(self, snapshot: FastSnapshot, message: FastInput) -> int: ...

    def prepare_epoch(self, snapshot: FastSnapshot, message: FastInput) -> CompactionProposal | None: ...

    def validate_compaction(self, snapshot: FastSnapshot, proposal: CompactionProposal) -> None: ...


class FastMind(Protocol):
    def stream(self, snapshot: FastSnapshot, message: FastInput) -> AsyncGenerator[str, None]: ...


class DeepMind(Protocol):
    async def propose(self, request: DeepRequest) -> DeepResult: ...


class OutputSink(Protocol):
    def __call__(self, output: RuntimeOutput, /) -> None:
        """Consume a notification promptly; never change domain state here."""
        ...
