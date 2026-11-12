"""Composition root: configuration and concrete adapters meet only here."""

import asyncio
import math
import os
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import AsyncIterator

import httpx

from vtuber.context import ContextCompiler
from vtuber.contracts.protocols import FastMind, OutputSink
from vtuber.minds.fake import FakeDeep, FakeFast
from vtuber.minds.lmstudio import LMStudioFast, LMStudioSettings
from vtuber.minds.nemotron import NemotronTokenCounter
from vtuber.minds.omp import OMPSettings, OMPTransport
from vtuber.minds.luna import LunaDeep
from vtuber.runtime.journal import Journal
from vtuber.runtime.orchestrator import Runtime


@dataclass(frozen=True)
class Config:
    db: Path = Path(".data/character.sqlite3")
    character_id: str = "primary"
    fast_delay: float = 0.03
    deep_delay: float = 2.0
    deep_timeout: float = 30.0
    fast_backend: str = "fake"
    lmstudio: LMStudioSettings = field(default_factory=LMStudioSettings)
    context_tokens: int = 16384
    identity: Path | None = None
    tokenizer: Path = Path(".data/tokenizers/nemotron.json")
    deep_backend: str = 'fake'
    omp: OMPSettings = field(default_factory=OMPSettings)

    def __post_init__(self) -> None:
        if not self.character_id.strip():
            raise ValueError("Character ID must be nonempty")
        if not all(math.isfinite(value) and value >= 0 for value in (self.fast_delay, self.deep_delay)):
            raise ValueError("Fake delays must be finite and nonnegative")
        if not math.isfinite(self.deep_timeout) or self.deep_timeout <= 0:
            raise ValueError("Deep timeout must be finite and positive")
        if self.fast_backend not in ("fake", "lmstudio"):
            raise ValueError("Unknown Fast backend")
        if self.deep_backend not in ('fake', 'luna'):
            raise ValueError('Unknown Deep backend')
        if not 0 < self.lmstudio.max_output_tokens < self.context_tokens:
            raise ValueError("Context budget must exceed the output reserve")
        if self.fast_backend == "lmstudio" and not self.lmstudio.model.strip():
            raise ValueError("--model must identify a loaded LM Studio instance")


def http_client(settings: LMStudioSettings) -> httpx.AsyncClient:
    token = os.environ.get("LMSTUDIO_API_TOKEN")
    return httpx.AsyncClient(base_url=settings.endpoint.rstrip("/"), trust_env=False,
        headers={"Authorization": f"Bearer {token}"} if token else {},
        timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout),
        limits=httpx.Limits(max_connections=2, max_keepalive_connections=1))


async def list_models(settings: LMStudioSettings) -> object:
    async with http_client(settings) as client:
        async with asyncio.timeout(settings.generation_timeout):
            response = await client.get("/api/v1/models")
            response.raise_for_status()
            return response.json()


@asynccontextmanager
async def open_runtime(config: Config, output: OutputSink) -> AsyncIterator[Runtime]:
    # The client outlives Runtime so cancellation closes streams before the pool.
    async with AsyncExitStack() as stack:
        diagnostics: dict[str, object] = {"backend": config.fast_backend}
        fast: FastMind = FakeFast(config.fast_delay)
        identity = (config.identity.read_text(encoding="utf-8") if config.identity else
                    files("vtuber.minds").joinpath("character.md").read_text(encoding="utf-8"))
        compiler = ContextCompiler(identity, config.context_tokens, config.lmstudio.max_output_tokens)
        if config.fast_backend == "lmstudio":
            compiler = ContextCompiler(identity, config.context_tokens, config.lmstudio.max_output_tokens,
                                       NemotronTokenCounter(config.tokenizer))
            client = await stack.enter_async_context(http_client(config.lmstudio))
            fast = LMStudioFast(client, compiler, config.lmstudio, diagnostics)
            await fast.verify_token_count()
        journal = Journal(config.db)
        stack.callback(journal.close)
        deep = FakeDeep(config.deep_delay)
        deep_diagnostics: dict[str, object] = {'backend': config.deep_backend}
        if config.deep_backend == 'luna':
            role = files('vtuber.minds').joinpath('deep.md').read_text(encoding='utf-8')
            transport = OMPTransport(config.omp, role+'\n\nCharacter Identity:\n'+identity, deep_diagnostics)
            stack.push_async_callback(transport.close)
            deep = LunaDeep(transport, identity)
        runtime = await stack.enter_async_context(Runtime(config.character_id, journal, fast,
            deep, output, deep_timeout=config.deep_timeout, deep_diagnostics=deep_diagnostics,
            fast_diagnostics=diagnostics, context_policy=compiler))
        yield runtime
