"""Nemotron text-only, no-thinking Fast via LM Studio's raw stateless SSE API."""

import asyncio
import json
import math
from dataclasses import asdict, dataclass
from hashlib import sha256
from time import perf_counter
from typing import AsyncGenerator
from urllib.parse import urlsplit

import httpx

from vtuber.context import ChatMessage, ContextCompiler
from vtuber.minds.nemotron import CONTROL_MARKERS, render_nemotron
from vtuber.contracts.events import UserMessage
from vtuber.contracts.state import FastSnapshot
from vtuber.contracts.trace import TraceSink, emit_trace, trace_enabled


class StreamProtocolError(RuntimeError):
    """Malformed, incomplete, reasoning or non-speech output; never commit it."""


class ModelUnavailable(RuntimeError):
    """An explicitly loaded Nemotron instance with sufficient context is required."""


@dataclass(frozen=True)
class LMStudioSettings:
    endpoint: str = "http://127.0.0.1:1234"
    model: str = ""
    max_output_tokens: int = 512
    temperature: float = 1.0
    top_p: float = 0.95
    connect_timeout: float = 2.0
    read_timeout: float = 15.0
    generation_timeout: float = 45.0

    def __post_init__(self) -> None:
        url = urlsplit(self.endpoint)
        _ = url.port
        if (url.scheme not in ("http", "https") or not url.hostname or url.username
                or url.password or url.query or url.fragment or url.path not in ("", "/")):
            raise ValueError("LM Studio endpoint must be a server origin without credentials or path")
        if not 0 < self.max_output_tokens or not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2:
            raise ValueError("Require positive output limit and temperature in [0, 2]")
        if not math.isfinite(self.top_p) or not 0 < self.top_p <= 1:
            raise ValueError("top_p must be in (0, 1]")
        if not all(math.isfinite(v) and v > 0 for v in
                   (self.connect_timeout, self.read_timeout, self.generation_timeout)):
            raise ValueError("HTTP timeouts must be finite and positive")


async def sse_data(response: httpx.Response) -> AsyncGenerator[str, None]:
    data: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data:
                yield "\n".join(data)
                data.clear()
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    if data:
        raise StreamProtocolError("Incomplete SSE frame")


def speech_prefix(buffer: str) -> tuple[str, str]:
    """Hold only possible marker prefixes so split control tokens cannot leak."""
    if any(marker in buffer for marker in CONTROL_MARKERS):
        raise StreamProtocolError("Unexpected model control/reasoning output")
    cut = len(buffer)
    for marker in CONTROL_MARKERS:
        for size in range(1, len(marker)):
            if buffer.endswith(marker[:size]):
                cut = min(cut, len(buffer) - size)
    return buffer[:cut], buffer[cut:]


class LMStudioFast:
    def __init__(self, client: httpx.AsyncClient, compiler: ContextCompiler,
                 settings: LMStudioSettings, diagnostics: dict[str, object], *, trace: TraceSink | None = None) -> None:
        self.client, self.compiler, self.settings = client, compiler, settings
        self.diagnostics = diagnostics
        self.count_verified = False
        self.trace = trace
        diagnostics.update({"backend": "lmstudio", "configuration": asdict(settings),
            "context_tokens": compiler.context_tokens, "enable_thinking": False,
            "conversational_mode": True, "template": "NVIDIA Gemma4 text-only (2026-08-20)",
            "endpoint_path": "/v1/completions"})

    async def verify_token_count(self) -> None:
        self.count_verified = False
        counter = self.compiler.token_counter
        if counter is None:
            raise StreamProtocolError("Real Fast requires a local tokenizer")
        messages = (ChatMessage("system", "Token count compatibility probe."),
                    ChatMessage("user", "Say only READY."))
        async with asyncio.timeout(self.settings.generation_timeout):
            await self.check_model()
            response = await self.client.post("/v1/completions", json={
                "model": self.settings.model, "prompt": render_nemotron(messages),
                "stream": False, "max_tokens": 4, "temperature": 0,
                "stop": ["<turn|>", "<|endoftext|>"]})
            response.raise_for_status()
            actual = (response.json().get("usage") or {}).get("prompt_tokens")
            if type(actual) is not int or actual != counter(messages):
                raise StreamProtocolError("Local tokenizer/provider usage mismatch; revalidate configuration")
        self.count_verified = True
        self.diagnostics["token_count_verified"] = True

    async def check_model(self) -> None:
        response = await self.client.get("/api/v1/models")
        response.raise_for_status()
        for model in response.json()["models"]:
            for instance in model.get("loaded_instances", []):
                if instance["id"] != self.settings.model:
                    continue
                if "nemotron-3.5-bolt-e4b" not in model["key"].lower():
                    raise ModelUnavailable("This renderer requires NVIDIA Nemotron 3.5 Bolt E4B")
                if instance["config"]["context_length"] < self.compiler.context_tokens:
                    raise ModelUnavailable("Loaded context is smaller than the configured budget")
                self.diagnostics["model"] = {"key": model["key"], "instance": instance["id"],
                    "loaded_context": instance["config"]["context_length"], "load_state": "preloaded",
                    "quantization": model.get("quantization")}
                return
        raise ModelUnavailable("Load the selected model first; use --list-models to inspect identifiers")

    async def stream(self, snapshot: FastSnapshot, message: UserMessage) -> AsyncGenerator[str, None]:
        start = perf_counter()
        metrics: dict[str, object] = {"turn_id": message.turn_id, "status": "streaming",
            "ttft_ms": None, "output_tokens": None, "prompt_tokens": None,
            "tokens_per_second": None, "reasoning_detected": False}
        self.diagnostics["generation"] = metrics
        self.diagnostics.pop("context", None)
        pending = ""
        visible = False
        finished = False
        done = False
        try:
            if not self.count_verified:
                raise StreamProtocolError("Token counter is unverified; restart or revalidate before generation")
            compiled = self.compiler.compile(snapshot, message)
            prompt = render_nemotron(compiled.messages)
            self.diagnostics["context"] = {**compiled.metadata(),
                "rendered_prompt_sha256": sha256(prompt.encode()).hexdigest()}
            if trace_enabled(self.trace):
                emit_trace(self.trace, 'fast.context', message.turn_id,
                           messages=[asdict(m) for m in compiled.messages], prompt=prompt,
                           metadata=self.diagnostics['context'], configuration=asdict(self.settings))
            async with asyncio.timeout(self.settings.generation_timeout):
                await self.check_model()
                async with self.client.stream("POST", "/v1/completions", json={
                    "model": self.settings.model, "prompt": prompt, "stream": True,
                    "stream_options": {"include_usage": True}, "echo": False,
                    "max_tokens": self.settings.max_output_tokens,
                    "temperature": self.settings.temperature, "top_p": self.settings.top_p,
                    "stop": ["<turn|>", "<|endoftext|>"]}) as response:
                    response.raise_for_status()
                    if not response.headers.get("content-type", "").startswith("text/event-stream"):
                        raise StreamProtocolError("Expected SSE response")
                    async for data in sse_data(response):
                        if data == "[DONE]":
                            done = True
                            break
                        packet = json.loads(data)
                        if "error" in packet:
                            raise StreamProtocolError("Provider error during streaming")
                        usage = packet.get("usage") or {}
                        if usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0):
                            metrics["reasoning_detected"] = True
                            raise StreamProtocolError("Backend reported reasoning tokens")
                        for source, target in (("prompt_tokens", "prompt_tokens"), ("completion_tokens", "output_tokens")):
                            if source in usage:
                                count = usage[source]
                                if type(count) is not int or count < 0:
                                    raise StreamProtocolError("Invalid token usage")
                                metrics[target] = count
                        choices = packet.get("choices", [])
                        if not isinstance(choices, list) or len(choices) > 1:
                            raise StreamProtocolError("Expected one completion choice")
                        for choice in choices:
                            if choice.get("reasoning_content") or choice.get("reasoning"):
                                metrics["reasoning_detected"] = True
                                raise StreamProtocolError("Unexpected reasoning channel")
                            text = choice.get("text", "")
                            if not isinstance(text, str) or (finished and text):
                                raise StreamProtocolError("Invalid text chunk")
                            pending += text
                            try:
                                safe, pending = speech_prefix(pending)
                            except StreamProtocolError:
                                metrics["reasoning_detected"] = True
                                raise
                            if safe:
                                if not visible and safe.strip():
                                    metrics["ttft_ms"] = round((perf_counter() - start) * 1000, 2)
                                    visible = True
                                yield safe
                            reason = choice.get("finish_reason")
                            if reason is not None:
                                if reason not in ("stop", "length"):
                                    raise StreamProtocolError("Unexpected finish reason")
                                metrics["finish_reason"] = reason
                                finished = True
                    if not done or not finished:
                        raise StreamProtocolError("Stream ended without a terminal frame and DONE")
                    actual = metrics["prompt_tokens"]
                    metrics["local_prompt_tokens"] = compiled.estimated_input_tokens
                    metrics["token_count_difference"] = (actual - compiled.estimated_input_tokens
                        if type(actual) is int else None)
                    if type(actual) is not int or actual != compiled.estimated_input_tokens:
                        self.count_verified = False
                        self.diagnostics["token_count_verified"] = False
                        raise StreamProtocolError("Local tokenizer/provider usage mismatch; revalidation required")
                    if pending:
                        if not visible:
                            metrics["ttft_ms"] = round((perf_counter() - start) * 1000, 2)
                        visible = True
                        yield pending
                    if not visible:
                        raise StreamProtocolError("Model returned no speech")
            metrics["status"] = "completed"
        except asyncio.CancelledError:
            metrics["status"] = "cancelled"
            raise
        except Exception as error:
            metrics["status"] = "failed"
            metrics["error"] = type(error).__name__
            if isinstance(error, (ModelUnavailable, ValueError)):
                metrics["hint"] = str(error)
            raise
        finally:
            elapsed = perf_counter() - start
            metrics["total_ms"] = round(elapsed * 1000, 2)
            if isinstance(metrics["output_tokens"], int):
                metrics["tokens_per_second"] = round(metrics["output_tokens"] / max(elapsed, 0.001), 2)
                if isinstance(metrics["ttft_ms"], (int, float)) and metrics["output_tokens"] > 1:
                    metrics["approx_decode_tokens_per_second"] = round((metrics["output_tokens"] - 1) /
                        max(elapsed - metrics["ttft_ms"] / 1000, 0.001), 2)
