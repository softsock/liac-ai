"""Core-owned lifecycle for the local model sidecar."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, Queue
from typing import BinaryIO, Final, Literal

from .sidecar_protocol import (
    MAX_FRAME_BYTES,
    MAX_RESPONSE_BYTES,
    CancelCommand,
    GenerateCommand,
    GenerationAccepted,
    GenerationCancelled,
    GenerationCompleted,
    GenerationEvent,
    HealthEvent,
    ModelRequest,
    ProtocolError,
    ReadyEvent,
    RuntimeState,
    ShutdownCommand,
    ShutdownEvent,
    TextDelta,
    encode_command,
    parse_event,
)
from .sidecar_protocol import GenerationFailed as GenerationFailedEvent

DEFAULT_EVENT_QUEUE_SIZE: Final = 128
DEFAULT_STARTUP_TIMEOUT: Final = 30.0
DEFAULT_SHUTDOWN_TIMEOUT: Final = 5.0
DEFAULT_WRITE_TIMEOUT: Final = 5.0
_READ_CHUNK_SIZE: Final = 4096


class ModelRuntimeError(RuntimeError):
    """Base class for Core-side runtime failures."""


class RuntimeNotReady(ModelRuntimeError):
    """The sidecar has not completed its ready handshake."""


class RuntimeBusy(ModelRuntimeError):
    """A generation is already active."""


class RuntimeStartTimeout(ModelRuntimeError):
    """The sidecar did not become ready before the bounded startup deadline."""


class ShutdownTimeout(ModelRuntimeError):
    """The sidecar did not exit before the bounded shutdown deadline."""


class SidecarCrashed(ModelRuntimeError):
    """The sidecar exited or its pipe became unusable before completion."""


class ProtocolViolation(ModelRuntimeError):
    """The sidecar emitted malformed or invalidly correlated protocol data."""


class GenerationFailed(ModelRuntimeError):
    """The sidecar reported a terminal generation failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    state: RuntimeState
    pid: int | None
    error: str | None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    generation_id: str
    status: Literal["completed", "cancelled"]
    text: str


class GenerationHandle:
    """A streamed generation owned by one ModelRuntime instance."""

    def __init__(self, generation_id: str, epoch: int, queue_size: int) -> None:
        self.generation_id = generation_id
        self.epoch = epoch
        self._events: Queue[GenerationEvent] = Queue(maxsize=queue_size)
        self._terminal = threading.Event()
        self._lock = threading.Lock()
        self._text_parts: list[str] = []
        self._text_bytes = 0
        self._result: GenerationResult | None = None
        self._failure: ModelRuntimeError | None = None
        self._terminal_event: (
            GenerationCompleted | GenerationCancelled | GenerationFailedEvent | None
        ) = None
        self._terminal_delivered = False

    def events(self) -> Iterator[GenerationEvent]:
        """Yield accepted, delta, and terminal events in wire order."""
        while True:
            try:
                event = self._events.get(timeout=0.1)
            except Empty:
                if self._terminal.is_set():
                    with self._lock:
                        if self._terminal_delivered or self._terminal_event is None:
                            return
                        self._terminal_delivered = True
                        terminal_event = self._terminal_event
                    yield terminal_event
                    return
                continue
            yield event

    def __iter__(self) -> Iterator[GenerationEvent]:
        return self.events()

    def wait(self, timeout: float | None = None) -> GenerationResult:
        """Wait for the terminal event; failures are raised as Core errors."""
        if not self._terminal.wait(timeout):
            raise TimeoutError("generation did not complete before the deadline")
        with self._lock:
            if self._failure is not None:
                raise self._failure
            if self._result is None:
                raise ModelRuntimeError("generation ended without a result")
            return self._result

    @property
    def text(self) -> str:
        with self._lock:
            return "".join(self._text_parts)

    def offer(self, event: GenerationEvent) -> Literal["accepted", "queue_full", "output_limit"]:
        if isinstance(event, TextDelta):
            delta_bytes = len(event.delta.encode("utf-8"))
            with self._lock:
                if self._text_bytes + delta_bytes > MAX_RESPONSE_BYTES:
                    return "output_limit"
                self._text_parts.append(event.delta)
                self._text_bytes += delta_bytes
        try:
            self._events.put_nowait(event)
        except Full:
            return "queue_full"
        return "accepted"

    def complete(self, event: GenerationCompleted | GenerationCancelled) -> None:
        with self._lock:
            self._result = GenerationResult(
                generation_id=self.generation_id,
                status="completed" if isinstance(event, GenerationCompleted) else "cancelled",
                text="".join(self._text_parts),
            )
            self._terminal_event = event
            self._terminal.set()

    def fail(self, event: GenerationFailedEvent, error: ModelRuntimeError) -> None:
        with self._lock:
            self._failure = error
            self._terminal_event = event
            self._terminal.set()


@dataclass(slots=True)
class _PendingGeneration:
    handle: GenerationHandle
    generation_id: str
    epoch: int
    phase: Literal["created", "accepted", "streaming", "cancelling", "terminal"] = "created"


class ModelRuntime:
    """Start and supervise one persistent local model sidecar process."""

    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        sidecar_dir: Path | None = None,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
        shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
        write_timeout: float = DEFAULT_WRITE_TIMEOUT,
        event_queue_size: int = DEFAULT_EVENT_QUEUE_SIZE,
    ) -> None:
        if startup_timeout <= 0 or shutdown_timeout <= 0 or write_timeout <= 0:
            raise ValueError("runtime timeouts must be positive")
        if event_queue_size <= 0:
            raise ValueError("event_queue_size must be positive")
        self._command = tuple(command) if command is not None else _default_command()
        self._sidecar_dir = sidecar_dir or _default_sidecar_dir()
        self._startup_timeout = startup_timeout
        self._shutdown_timeout = shutdown_timeout
        self._write_timeout = write_timeout
        self._event_queue_size = event_queue_size
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._write_broken = False
        self._state: RuntimeState = "new"
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._shutdown_complete = threading.Event()
        self._active: _PendingGeneration | None = None
        self._next_epoch = 0
        self._failure: ModelRuntimeError | None = None
        self._shutdown_requested = False

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._state == "ready"

    def health(self) -> RuntimeHealth:
        with self._lock:
            return RuntimeHealth(
                state=self._state,
                pid=self._process.pid if self._process is not None else None,
                error=str(self._failure) if self._failure is not None else None,
            )

    def start(self) -> None:
        with self._lock:
            if self._state in {"ready", "busy"}:
                return
            if self._state == "closed":
                raise ModelRuntimeError("runtime is closed")
            if self._state == "failed":
                raise self._failure or ModelRuntimeError("runtime has failed")
            if self._state == "starting":
                pass
            else:
                self._state = "starting"
                self._failure = None
                self._shutdown_requested = False
                self._write_broken = False
                self._ready.clear()
                self._shutdown_complete.clear()
                try:
                    process = subprocess.Popen(
                        self._command,
                        cwd=str(self._sidecar_dir),
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        bufsize=0,
                    )
                except OSError as error:
                    failure = SidecarCrashed(f"could not start sidecar: {error.__class__.__name__}")
                    self._state = "failed"
                    self._failure = failure
                    self._ready.set()
                    raise failure from error
                if process.stdout is None or process.stdin is None:
                    process.kill()
                    failure = SidecarCrashed("sidecar pipes were not created")
                    self._state = "failed"
                    self._failure = failure
                    self._ready.set()
                    raise failure
                self._process = process
                self._reader_thread = threading.Thread(
                    target=self._read_stdout,
                    args=(process.stdout,),
                    name="lilavel-sidecar-reader",
                    daemon=True,
                )
                self._reader_thread.start()
                if process.stderr is not None:
                    self._stderr_thread = threading.Thread(
                        target=self._drain_stderr,
                        args=(process.stderr,),
                        name="lilavel-sidecar-stderr",
                        daemon=True,
                    )
                    self._stderr_thread.start()
        self._ready.wait(self._startup_timeout)
        if not self.ready:
            with self._lock:
                failure = self._failure
            if failure is not None:
                raise failure
            timeout = RuntimeStartTimeout("sidecar did not become ready")
            self._fail_runtime(timeout)
            raise timeout

    def generate(self, request: ModelRequest) -> GenerationHandle:
        with self._lock:
            self._ensure_ready()
            if self._active is not None:
                raise RuntimeBusy("a generation is already active")
            self._next_epoch += 1
            generation_id = str(uuid.uuid4())
            handle = GenerationHandle(generation_id, self._next_epoch, self._event_queue_size)
            self._active = _PendingGeneration(handle, generation_id, self._next_epoch)
            self._state = "busy"
            command = GenerateCommand(generation_id, self._next_epoch, request.prompt)
            try:
                self._write_command(command)
            except OSError as error:
                failure = SidecarCrashed("sidecar input pipe failed")
                self._fail_pending_locked(failure)
                self._fail_runtime_locked(failure)
                raise failure from error
            return handle

    def cancel(self, generation_id: str) -> bool:
        with self._lock:
            pending = self._active
            if (
                pending is None
                or pending.generation_id != generation_id
                or pending.phase == "terminal"
            ):
                return False
            if pending.phase == "cancelling":
                return True
            pending.phase = "cancelling"
            command = CancelCommand(pending.generation_id, pending.epoch)
            try:
                self._write_command(command)
            except OSError as error:
                failure = SidecarCrashed("sidecar input pipe failed during cancellation")
                self._fail_pending_locked(failure)
                self._fail_runtime_locked(failure)
                raise failure from error
            return True

    def shutdown(self) -> None:
        with self._lock:
            if self._state == "closed":
                return
            if self._state == "new":
                self._state = "closed"
                return
            process = self._process
            self._shutdown_requested = True
            pending = self._active
            cancel_command: CancelCommand | None = None
            if pending is not None and pending.phase != "terminal":
                pending.phase = "cancelling"
                cancel_command = CancelCommand(pending.generation_id, pending.epoch)
        try:
            if cancel_command is not None:
                self._write_command(cancel_command)
            self._write_command(ShutdownCommand())
        except OSError:
            self._fail_runtime(SidecarCrashed("sidecar input pipe failed during shutdown"))

        deadline = time.monotonic() + self._shutdown_timeout
        completed = self._shutdown_complete.wait(max(0.0, deadline - time.monotonic()))
        timed_out = not completed
        if process is not None:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate_process(process)
            _close_pipes(process)
        with self._lock:
            self._state = "closed"
            self._process = None
            self._active = None
        if timed_out:
            raise ShutdownTimeout("sidecar did not shut down before the deadline")

    def _ensure_ready(self) -> None:
        if self._state != "ready":
            if self._state == "busy":
                raise RuntimeBusy("a generation is already active")
            raise RuntimeNotReady(f"runtime is {self._state}")

    def _write_command(self, command: GenerateCommand | CancelCommand | ShutdownCommand) -> None:
        payload = encode_command(command)
        with self._lock:
            process = self._process
            if process is None or process.stdin is None:
                raise OSError("sidecar stdin is unavailable")
            stream = process.stdin

        with self._write_lock:
            if self._write_broken:
                raise OSError("sidecar input pipe is unavailable")
            completed = threading.Event()
            failure: list[BaseException] = []

            def write() -> None:
                try:
                    stream.write(payload)
                    stream.flush()
                except (OSError, ValueError) as error:
                    failure.append(error)
                finally:
                    completed.set()

            threading.Thread(target=write, name="lilavel-sidecar-writer", daemon=True).start()
            if not completed.wait(self._write_timeout):
                self._write_broken = True
                raise OSError("sidecar input pipe write timed out")
            if failure:
                self._write_broken = True
                raise OSError("sidecar input pipe failed") from failure[0]

    def _read_stdout(self, stream: BinaryIO) -> None:
        try:
            for frame in _iter_frames(stream):
                self._dispatch(parse_event(frame))
        except ProtocolError as error:
            self._fail_runtime(ProtocolViolation(f"invalid sidecar protocol: {error.reason}"))
        except (OSError, ValueError) as error:
            self._fail_runtime(SidecarCrashed(f"sidecar output failed: {error.__class__.__name__}"))
        finally:
            with self._lock:
                expected_shutdown = self._shutdown_requested
            if expected_shutdown:
                self._shutdown_complete.set()
            else:
                self._fail_runtime(SidecarCrashed("sidecar exited before shutdown"))

    def _drain_stderr(self, stream: BinaryIO) -> None:
        while stream.read(_READ_CHUNK_SIZE):
            pass

    def _dispatch(self, event: GenerationEvent) -> None:
        if isinstance(event, ReadyEvent):
            with self._lock:
                if self._state != "starting":
                    self._fail_runtime_locked(ProtocolViolation("unexpected ready event"))
                    return
                self._state = "ready"
                self._ready.set()
            return
        if isinstance(event, HealthEvent):
            return
        if isinstance(event, ShutdownEvent):
            self._shutdown_complete.set()
            return
        if isinstance(event, GenerationFailedEvent) and event.generation_id is None:
            with self._lock:
                failure: ModelRuntimeError = GenerationFailed(event.code)
                self._fail_runtime_locked(failure)
                self._ready.set()
            return
        cancel_after_limit = False
        cancel_identity: tuple[str, int] | None = None
        if isinstance(event, GenerationFailedEvent):
            if event.generation_id is None or event.epoch is None:
                self._fail_runtime(ProtocolViolation("failed event has no generation identity"))
                return
            generation_id = event.generation_id
            epoch = event.epoch
        else:
            generation_id = event.generation_id
            epoch = event.epoch
        with self._lock:
            pending = self._active
            if pending is None:
                if epoch <= self._next_epoch:
                    return
                self._fail_runtime_locked(ProtocolViolation("future generation event"))
                return
            if generation_id != pending.generation_id:
                if epoch < pending.epoch:
                    return
                self._fail_runtime_locked(ProtocolViolation("generation identity mismatch"))
                return
            if epoch != pending.epoch:
                if epoch < pending.epoch:
                    return
                self._fail_runtime_locked(ProtocolViolation("generation epoch mismatch"))
                return

            if isinstance(event, GenerationAccepted):
                if pending.phase != "created" or pending.handle.offer(event) != "accepted":
                    self._fail_runtime_locked(ProtocolViolation("invalid accepted transition"))
                else:
                    pending.phase = "accepted"
            elif isinstance(event, TextDelta):
                if pending.phase in {"cancelling", "terminal"}:
                    return
                if pending.phase not in {"accepted", "streaming"}:
                    self._fail_runtime_locked(ProtocolViolation("delta before accepted"))
                else:
                    offer_result = pending.handle.offer(event)
                    if offer_result == "queue_full":
                        self._fail_runtime_locked(
                            ProtocolViolation("generation event buffer is full")
                        )
                    elif offer_result == "output_limit":
                        pending.phase = "terminal"
                        pending.handle.fail(
                            GenerationFailedEvent(
                                pending.generation_id, pending.epoch, "output_limit"
                            ),
                            GenerationFailed("output_limit"),
                        )
                        self._active = None
                        self._state = "ready"
                        cancel_after_limit = True
                        cancel_identity = (pending.generation_id, pending.epoch)
                    else:
                        pending.phase = "streaming"
            elif isinstance(event, GenerationCompleted):
                if pending.phase not in {"accepted", "streaming", "cancelling"}:
                    self._fail_runtime_locked(ProtocolViolation("invalid completion transition"))
                else:
                    pending.phase = "terminal"
                    pending.handle.complete(event)
                    self._finish_pending_locked(pending)
            elif isinstance(event, GenerationCancelled):
                if pending.phase not in {"accepted", "streaming", "cancelling"}:
                    self._fail_runtime_locked(ProtocolViolation("invalid cancellation transition"))
                else:
                    pending.phase = "terminal"
                    pending.handle.complete(event)
                    self._finish_pending_locked(pending)
            else:
                pending.phase = "terminal"
                pending.handle.fail(event, GenerationFailed(event.code))
                self._finish_pending_locked(pending)
        if cancel_after_limit:
            try:
                if cancel_identity is None:
                    raise OSError("missing generation identity")
                self._write_command(CancelCommand(*cancel_identity))
            except OSError:
                self._fail_runtime(SidecarCrashed("sidecar input pipe failed after output limit"))

    def _finish_pending_locked(self, pending: _PendingGeneration) -> None:
        if self._active is pending:
            self._active = None
            if self._state == "busy":
                self._state = "ready"

    def _fail_pending_locked(self, failure: ModelRuntimeError) -> None:
        pending = self._active
        if pending is None:
            return
        pending.phase = "terminal"
        event = GenerationFailedEvent(pending.generation_id, pending.epoch, "protocol_error")
        pending.handle.fail(event, failure)
        self._finish_pending_locked(pending)

    def _fail_runtime(self, failure: ModelRuntimeError) -> None:
        process: subprocess.Popen[bytes] | None
        with self._lock:
            process = self._fail_runtime_locked(failure)
        if process is not None:
            _terminate_process(process)

    def _fail_runtime_locked(self, failure: ModelRuntimeError) -> subprocess.Popen[bytes] | None:
        if self._state in {"closed", "failed"}:
            return None
        self._state = "failed"
        self._failure = failure
        self._ready.set()
        self._shutdown_complete.set()
        pending = self._active
        if pending is not None:
            self._fail_pending_locked(failure)
        process = self._process
        if process is not None and process.poll() is None:
            threading.Thread(target=_terminate_process, args=(process,), daemon=True).start()
        return None


def _default_sidecar_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "model-sidecar"


def _default_command() -> tuple[str, ...]:
    executable = shutil.which("npx") or shutil.which("npx.cmd")
    if executable is None:
        executable = "npx.cmd" if os.name == "nt" else "npx"
    return (executable, "--yes", "bun@1.4.0", "run", "protocol")


def _iter_frames(stream: BinaryIO) -> Iterator[bytes]:
    buffered = bytearray()
    while True:
        chunk = stream.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        line_start = 0
        for index, value in enumerate(chunk):
            if value != 0x0A:
                continue
            line = bytes(buffered) + chunk[line_start:index]
            buffered.clear()
            line_start = index + 1
            if line.endswith(b"\r"):
                line = line[:-1]
            if len(line) > MAX_FRAME_BYTES or not line:
                raise ProtocolError(
                    "frame_too_large" if len(line) > MAX_FRAME_BYTES else "malformed"
                )
            yield line
        remainder = chunk[line_start:]
        if remainder:
            if len(buffered) + len(remainder) > MAX_FRAME_BYTES:
                raise ProtocolError("frame_too_large")
            buffered.extend(remainder)
    if buffered:
        raise ProtocolError("malformed")


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        with suppress(OSError):
            process.kill()


def _close_pipes(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            with suppress(OSError, ValueError):
                stream.close()
