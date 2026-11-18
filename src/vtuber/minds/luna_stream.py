import asyncio
import json
from collections.abc import Callable
from uuid import uuid4

from vtuber.contracts.mind import MindDecision, MindStreamError


MAX_FRAME_BYTES = 64 * 1024
ERROR_KINDS = {
    "busy", "cancelled", "input_too_large", "invalid_request", "invalid_tool_call",
    "oauth_unavailable", "provider_error", "request_mismatch",
}


class LunaStreamError(MindStreamError):
    pass


class LunaStream:
    def __init__(self, command: tuple[str, ...], *, system: str = "", reasoning: str = "low") -> None:
        self._command = command
        self._system = system
        self._reasoning = reasoning
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._launch_attempted = False
        self._closed = False
        self.last_timings: dict[str, int] = {}

    def model_status(self) -> dict[str, str]:
        if self._process is not None and self._process.returncode is None:
            bridge = "running"
        elif self._launch_attempted or self._closed:
            bridge = "unavailable"
        else:
            bridge = "not_started"
        return {"name": "gpt-6-luna", "reasoning": self._reasoning, "bridge": bridge}

    async def _start(self) -> asyncio.subprocess.Process:
        if self._process is None or self._process.returncode is not None:
            self._launch_attempted = True
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *self._command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=MAX_FRAME_BYTES,
                )
            except OSError:
                raise LunaStreamError("startup_failed") from None
        return self._process

    @staticmethod
    async def _send(process: asyncio.subprocess.Process, frame: dict[str, object]) -> None:
        data = json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        if len(data) > MAX_FRAME_BYTES:
            raise LunaStreamError("input_too_large")
        assert process.stdin is not None
        process.stdin.write(data)
        await process.stdin.drain()

    @staticmethod
    async def _read(process: asyncio.subprocess.Process, identifier: str) -> dict:
        assert process.stdout is not None
        try:
            line = await process.stdout.readline()
            frame = json.loads(line) if 0 < len(line) <= MAX_FRAME_BYTES else None
        except (ValueError, UnicodeError):
            raise LunaStreamError("invalid_frame") from None
        if not isinstance(frame, dict) or frame.get("id") != identifier:
            raise LunaStreamError("invalid_frame" if line else "bridge_closed")
        return frame

    async def generate(
        self,
        messages: tuple[dict[str, object], ...],
        *,
        on_speak_delta: Callable[[str], None] | None = None,
    ) -> MindDecision:
        async with self._lock:
            if self._closed:
                raise LunaStreamError("bridge_closed")
            system = self._system
            if messages and messages[0].get("role") == "system":
                system = messages[0]["content"]
                messages = messages[1:]
            self.last_timings = {}
            process = await self._start()
            identifier = uuid4().hex
            try:
                await self._send(process, {
                    "type": "turn", "id": identifier, "messages": messages,
                    "system": system, "reasoning": self._reasoning,
                })
                async with asyncio.timeout(45):
                    while True:
                        frame = await self._read(process, identifier)
                        kind = frame.get("type")
                        if kind == "speak_delta" and isinstance(frame.get("text"), str):
                            if on_speak_delta is not None:
                                on_speak_delta(frame["text"])
                        elif kind == "result":
                            decision = self._decision(frame)
                            self.last_timings = self._counters(frame.get("timings")) or {}
                            return decision
                        elif kind == "error":
                            error = frame.get("kind")
                            raise LunaStreamError(error if isinstance(error, str) and error in ERROR_KINDS
                                                  else "bridge_error")
                        else:
                            raise LunaStreamError("invalid_frame")
            except asyncio.CancelledError:
                # Drain the cancelled turn while holding the process lock, even if cancelled again.
                cleanup = asyncio.create_task(self._cancel(process, identifier))
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        continue
                cleanup.result()
                raise
            except (OSError, TimeoutError, UnicodeError):
                await self._stop()
                raise LunaStreamError("bridge_io_failed") from None
            except Exception:
                await self._stop()
                raise

    @staticmethod
    def _counters(value: object) -> dict[str, int] | None:
        if not isinstance(value, dict):
            return None
        return {key: count for key, count in value.items()
                if isinstance(key, str) and type(count) is int and count >= 0}

    @classmethod
    def _decision(cls, frame: dict) -> MindDecision:
        action, text, call_id = (frame.get(key) for key in ("action", "message", "tool_call_id"))
        if (action not in ("speak", "stay_silent") or not isinstance(text, str)
                or not isinstance(call_id, str) or not call_id.strip()):
            raise LunaStreamError("invalid_tool_call")
        try:
            return MindDecision(action, text, call_id, cls._counters(frame.get("usage")))
        except ValueError:
            raise LunaStreamError("invalid_tool_call") from None

    async def _cancel(self, process: asyncio.subprocess.Process, identifier: str) -> None:
        try:
            async with asyncio.timeout(1):
                await self._send(process, {"type": "cancel", "id": identifier})
                while (await self._read(process, identifier)).get("type") not in ("result", "error"):
                    pass
        except (OSError, TimeoutError, LunaStreamError):
            await self._stop()

    async def _stop(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            process = self._process
            if process is None:
                return
            try:
                async with asyncio.timeout(1):
                    if process.returncode is None:
                        await self._send(process, {"type": "shutdown"})
                    await process.wait()
            except (OSError, TimeoutError):
                pass
            finally:
                await self._stop()
