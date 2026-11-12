"""Composition root: configuration and concrete adapters meet only here."""

import math
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from vtuber.contracts.protocols import OutputSink
from vtuber.minds.fake import FakeDeep, FakeFast
from vtuber.runtime.journal import Journal
from vtuber.runtime.orchestrator import Runtime


@dataclass(frozen=True)
class Config:
    db: Path = Path(".data/character.sqlite3")
    character_id: str = "primary"
    fast_delay: float = 0.03
    deep_delay: float = 2.0
    deep_timeout: float = 30.0

    def __post_init__(self) -> None:
        if not self.character_id.strip():
            raise ValueError("Character ID must be nonempty")
        if not all(math.isfinite(value) and value >= 0 for value in (self.fast_delay, self.deep_delay)):
            raise ValueError("Fake delays must be finite and nonnegative")
        if not math.isfinite(self.deep_timeout) or self.deep_timeout <= 0:
            raise ValueError("Deep timeout must be finite and positive")


@asynccontextmanager
async def open_runtime(config: Config, output: OutputSink) -> AsyncIterator[Runtime]:
    journal = Journal(config.db)
    try:
        async with Runtime(config.character_id, journal, FakeFast(config.fast_delay),
                           FakeDeep(config.deep_delay), output, deep_timeout=config.deep_timeout) as runtime:
            yield runtime
    finally:
        journal.close()
