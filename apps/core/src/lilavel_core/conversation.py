"""Core-owned conversation semantics above the provider-neutral model runtime."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from queue import Queue
from threading import Event, Lock, RLock, Thread
from typing import Literal, Protocol
from uuid import uuid4

from .persistence import (
    CanonicalMessage,
    ConversationStore,
    EvidenceRecord,
    PersistenceError,
    SQLiteConversationStore,
    validate_scope_id,
)
from .sidecar_protocol import (
    ContextMessage,
    GenerationCancelled,
    GenerationCompleted,
    GenerationEvent,
    ModelRequest,
    ProtocolError,
    TextDelta,
)
from .sidecar_protocol import GenerationFailed as GenerationFailedEvent


class ConversationError(RuntimeError):
    """Base class for semantic conversation failures."""


class ConversationBusy(ConversationError):
    """A new turn was requested without allowing the active turn to supersede."""


class RuntimeGeneration(Protocol):
    """The small generation surface consumed by ``ConversationRun``."""

    generation_id: str

    def events(self) -> Iterator[GenerationEvent]:
        """Yield the runtime's correlated generation events."""
        ...


class ConversationRuntime(Protocol):
    """The lifecycle surface needed from ``ModelRuntime``."""

    def generate(self, request: ModelRequest) -> RuntimeGeneration:
        """Start one generation for a complete caller-owned request."""
        ...

    def cancel(self, generation_id: str) -> bool:
        """Request cancellation for one runtime generation."""
        ...


class ConversationContextComposer(Protocol):
    """Compose canonical history into the next provider-neutral model input."""

    def compose(self, history: tuple[ContextMessage, ...]) -> Sequence[ContextMessage]:
        """Return the ordered role/text context for one model request."""
        ...


class FullHistoryContextComposer:
    """The initial composition policy: send the complete canonical history."""

    def compose(self, history: tuple[ContextMessage, ...]) -> tuple[ContextMessage, ...]:
        return history


type ConversationCancellationReason = Literal["cancelled", "superseded"]
type ConversationStatus = Literal["completed", "cancelled", "superseded", "failed"]


@dataclass(frozen=True, slots=True)
class ConversationTextDelta:
    """One transient assistant delta that was surfaced incrementally."""

    run_id: str
    delta: str


@dataclass(frozen=True, slots=True)
class ConversationCompleted:
    """A successfully completed assistant response."""

    run_id: str
    text: str


@dataclass(frozen=True, slots=True)
class ConversationCancelled:
    """A cancelled or superseded run whose candidate was not committed."""

    run_id: str
    text: str
    reason: ConversationCancellationReason


@dataclass(frozen=True, slots=True)
class ConversationFailed:
    """A run that could not produce a canonical assistant response."""

    run_id: str
    text: str
    error: PersistenceError | None = None


type ConversationEvent = (
    ConversationTextDelta | ConversationCompleted | ConversationCancelled | ConversationFailed
)


@dataclass(frozen=True, slots=True)
class ConversationOutcome:
    """The terminal semantic result of one conversation run."""

    run_id: str
    status: ConversationStatus
    text: str
    error: PersistenceError | None = None


class ConversationRun:
    """One user turn and its transient assistant generation.

    The run owns a semantic event stream, while ``ConversationCore`` owns the
    canonical history.  The underlying runtime generation is deliberately
    private so protocol and provider fields do not become conversation API.
    """

    def __init__(
        self,
        core: ConversationCore,
        run_id: str,
        predecessor: ConversationRun | None,
        user_message_id: str,
        assistant_message_id: str,
    ) -> None:
        self.run_id = run_id
        self.user_message_id = user_message_id
        self.assistant_message_id = assistant_message_id
        self._core = core
        self._predecessor = predecessor
        self._events: Queue[ConversationEvent] = Queue()
        self._settled_event = Event()
        self._lock = Lock()
        self._outcome: ConversationOutcome | None = None
        self._candidate_parts: list[str] = []
        self._cancel_requested = False
        self._cancel_reason: ConversationCancellationReason = "cancelled"
        self._runtime_generation: RuntimeGeneration | None = None
        self._cancel_sent = False
        self._assistant_committed = False
        self._assistant_commit_reserved = False
        self._consumer_active = False
        self._worker = Thread(
            target=self._execute,
            name=f"lilavel-conversation-{run_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._worker.start()

    def events(self) -> Iterator[ConversationEvent]:
        """Yield semantic deltas followed by exactly one terminal event."""

        with self._lock:
            if self._consumer_active:
                raise ConversationError("conversation run events already have a consumer")
            self._consumer_active = True
        try:
            while True:
                event = self._events.get()
                yield event
                if isinstance(
                    event,
                    (ConversationCompleted, ConversationCancelled, ConversationFailed),
                ):
                    return
        finally:
            with self._lock:
                self._consumer_active = False

    def __iter__(self) -> Iterator[ConversationEvent]:
        return self.events()

    def wait(self, timeout: float | None = None) -> ConversationOutcome:
        """Wait for the terminal semantic outcome without draining events."""

        if not self._settled_event.wait(timeout):
            raise TimeoutError("conversation run did not complete before the deadline")
        with self._lock:
            if self._outcome is None:
                raise ConversationError("conversation run ended without an outcome")
            return self._outcome

    def cancel(self) -> bool:
        """Cancel this run without committing its candidate assistant text."""

        return self.request_cancel("cancelled")

    @property
    def text(self) -> str:
        """Return the candidate text surfaced so far, whether or not it commits."""

        with self._lock:
            return "".join(self._candidate_parts)

    @property
    def settled(self) -> bool:
        with self._lock:
            return self._outcome is not None

    @property
    def outcome(self) -> ConversationOutcome | None:
        with self._lock:
            return self._outcome

    def wait_for_settlement(self) -> None:
        self._settled_event.wait()

    def request_cancel(self, reason: ConversationCancellationReason) -> bool:
        generation: RuntimeGeneration | None = None
        with self._lock:
            if self._outcome is not None:
                return False
            if not self._cancel_requested:
                self._cancel_requested = True
                self._cancel_reason = reason
            if self._runtime_generation is not None and not self._cancel_sent:
                self._cancel_sent = True
                generation = self._runtime_generation
        if generation is not None:
            self._send_runtime_cancel(generation)
        return True

    def _send_runtime_cancel(self, generation: RuntimeGeneration) -> None:
        try:
            self._core.runtime_cancel(generation.generation_id)
        except Exception:
            # A failed physical cancellation is a failed semantic run.  The
            # runtime remains responsible for settling/poisoning its handle.
            self._settle_failed()

    def _cancel_requested_now(self) -> bool:
        with self._lock:
            return self._cancel_requested

    def _cancel_reason_now(self) -> ConversationCancellationReason:
        with self._lock:
            return self._cancel_reason

    def _set_runtime_generation(self, generation: RuntimeGeneration) -> None:
        send_cancel = False
        with self._lock:
            self._runtime_generation = generation
            if self._cancel_requested and not self._cancel_sent:
                self._cancel_sent = True
                send_cancel = True
        if send_cancel:
            self._send_runtime_cancel(generation)

    def _execute(self) -> None:
        try:
            if self._predecessor is not None:
                self._predecessor.wait_for_settlement()

            if self._cancel_requested_now():
                self._settle_cancelled(self._cancel_reason_now())
                return

            try:
                request = self._core.build_model_request()
            except Exception:
                # This includes the existing structured-context validation
                # boundary.  The accepted user remains canonical.
                self._settle_failed()
                return

            if self._cancel_requested_now():
                self._settle_cancelled(self._cancel_reason_now())
                return

            try:
                generation = self._core.runtime_generate(request)
            except Exception:
                self._settle_failed()
                return

            self._set_runtime_generation(generation)
            self._consume_generation(generation)
        except Exception:
            self._settle_failed()

    def _consume_generation(self, generation: RuntimeGeneration) -> None:
        for event in generation.events():
            if isinstance(event, TextDelta):
                self._core.publish_delta(self, event.delta)
            elif isinstance(event, GenerationCompleted):
                try:
                    commit = self._core.commit_assistant(self)
                except PersistenceError as error:
                    self._settle_failed(error)
                    return
                if commit == "committed":
                    self._settle_completed()
                elif commit == "superseded":
                    self._settle_cancelled("superseded")
                elif commit == "cancelled":
                    self._settle_cancelled("cancelled")
                else:
                    self._settle_failed()
                return
            elif isinstance(event, GenerationCancelled):
                self._settle_cancelled(self._cancel_reason_now())
                return
            elif isinstance(event, GenerationFailedEvent):
                self._settle_failed()
                return
            # ``accepted`` is a runtime admission event, not conversation
            # semantics.  Other non-generation events are ignored likewise.

        # A conforming runtime always supplies a terminal generation event.
        # Do not leave a semantic run hanging if a test/runtime substitute does
        # not honor that contract.
        if not self.settled:
            self._settle_failed()

    def append_delta_if_live(self, delta: str) -> None:
        with self._lock:
            if self._outcome is not None or self._cancel_requested:
                return
            self._candidate_parts.append(delta)
            self._events.put(ConversationTextDelta(self.run_id, delta))

    def _candidate_text(self) -> str:
        with self._lock:
            return "".join(self._candidate_parts)

    def _settle_completed(self) -> None:
        text = self._candidate_text()
        self._settle(
            ConversationOutcome(self.run_id, "completed", text),
            ConversationCompleted(self.run_id, text),
        )

    def _settle_cancelled(self, reason: ConversationCancellationReason) -> None:
        text = self._candidate_text()
        status: ConversationStatus = "superseded" if reason == "superseded" else "cancelled"
        self._settle(
            ConversationOutcome(self.run_id, status, text),
            ConversationCancelled(self.run_id, text, reason),
        )

    def _settle_failed(self, error: PersistenceError | None = None) -> None:
        text = self._candidate_text()
        self._settle(
            ConversationOutcome(self.run_id, "failed", text, error),
            ConversationFailed(self.run_id, text, error),
        )

    def _settle(self, outcome: ConversationOutcome, event: ConversationEvent) -> None:
        with self._lock:
            if self._outcome is not None:
                return
            self._outcome = outcome
            self._events.put(event)
            self._settled_event.set()
        self._core.run_settled(self)

    def reserve_assistant_commit(
        self,
    ) -> tuple[Literal["new", "already", "cancelled", "invalid"], ContextMessage | None]:
        """Reserve one validated assistant message for Core's history append."""

        with self._lock:
            if self._outcome is not None or self._cancel_requested:
                return "cancelled", None
            if self._assistant_committed or self._assistant_commit_reserved:
                return "already", None
            try:
                message = ContextMessage("assistant", "".join(self._candidate_parts))
            except ProtocolError:
                return "invalid", None
            self._assistant_commit_reserved = True
            return "new", message

    def mark_assistant_committed(self) -> None:
        with self._lock:
            self._assistant_commit_reserved = False
            self._assistant_committed = True

    def release_assistant_commit(self) -> None:
        with self._lock:
            self._assistant_commit_reserved = False


type _CommitResult = Literal["committed", "superseded", "cancelled", "invalid"]


class ConversationCore:
    """Own canonical role/text history and coordinate one active run."""

    def __init__(
        self,
        runtime: ConversationRuntime,
        *,
        composer: ConversationContextComposer | None = None,
        trusted_guidance: Sequence[str] = (),
        scope_id: str | None = None,
        store: ConversationStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._composer = composer or FullHistoryContextComposer()
        self._trusted_guidance = tuple(trusted_guidance)
        self._lock = RLock()
        self._store = store or SQLiteConversationStore(":memory:")
        self._scope_id = validate_scope_id(scope_id if scope_id is not None else str(uuid4()))
        self._canonical_messages: list[CanonicalMessage] = list(
            self._store.load_canonical_messages(self._scope_id)
        )
        self._active: ConversationRun | None = None

    @property
    def scope_id(self) -> str:
        """Return the provider-neutral durable scope identity."""

        return self._scope_id

    @property
    def history(self) -> tuple[ContextMessage, ...]:
        """Return canonical user and successfully completed assistant messages."""

        with self._lock:
            return tuple(
                ContextMessage(message.role, message.text) for message in self._canonical_messages
            )

    @property
    def canonical_history(self) -> tuple[CanonicalMessage, ...]:
        """Return canonical messages with their durable Core-owned identities."""

        with self._lock:
            return tuple(self._canonical_messages)

    @property
    def evidence_records(self) -> tuple[EvidenceRecord, ...]:
        """Load raw provenance records for audit/testing."""

        with self._lock:
            return self._store.load_evidence(self._scope_id)

    @property
    def active_run(self) -> ConversationRun | None:
        with self._lock:
            if self._active is None or self._active.settled:
                return None
            return self._active

    def start_turn(self, text: str, *, supersede: bool = True) -> ConversationRun:
        """Accept one user message and start its assistant run.

        The user message is appended before any model call.  If another run is
        active, the new run becomes the logical active run immediately and the
        previous physical generation is cancelled before the new run asks the
        single-generation runtime to start work.
        """

        user_message = ContextMessage("user", text)
        user_message_id = str(uuid4())
        with self._lock:
            previous = self._active
            if previous is not None and previous.settled:
                previous = None
                self._active = None
            if previous is not None and not supersede:
                raise ConversationBusy("a conversation run is already active")

            canonical_user = self._store.append_user_message(
                scope_id=self._scope_id,
                message_id=user_message_id,
                text=user_message.text,
            )
            self._canonical_messages.append(canonical_user)
            run = ConversationRun(
                self,
                str(uuid4()),
                previous,
                canonical_user.message_id,
                str(uuid4()),
            )
            self._active = run

        if previous is not None:
            previous.request_cancel("superseded")
        run.start()
        return run

    def build_model_request(self) -> ModelRequest:
        with self._lock:
            history = tuple(
                ContextMessage(message.role, message.text) for message in self._canonical_messages
            )
        composed = tuple(self._composer.compose(history))
        return ModelRequest(messages=composed, system_prompt=self._trusted_guidance)

    def publish_delta(self, run: ConversationRun, delta: str) -> None:
        with self._lock:
            if self._active is not run:
                return
            run.append_delta_if_live(delta)

    def commit_assistant(self, run: ConversationRun) -> _CommitResult:
        with self._lock:
            if self._active is not run:
                return "superseded"
            reservation, assistant_message = run.reserve_assistant_commit()
            if reservation == "already":
                return "committed"
            if reservation == "cancelled":
                return "cancelled"
            if reservation == "invalid" or assistant_message is None:
                return "invalid"
            try:
                canonical_assistant = self._store.append_assistant_message(
                    scope_id=self._scope_id,
                    message_id=run.assistant_message_id,
                    text=assistant_message.text,
                )
            except Exception:
                run.release_assistant_commit()
                raise
            self._canonical_messages.append(canonical_assistant)
            run.mark_assistant_committed()
            return "committed"

    def run_settled(self, run: ConversationRun) -> None:
        with self._lock:
            if self._active is run:
                self._active = None

    def runtime_generate(self, request: ModelRequest) -> RuntimeGeneration:
        """Bridge one semantic request to the configured runtime."""

        return self._runtime.generate(request)

    def runtime_cancel(self, generation_id: str) -> bool:
        """Bridge one semantic cancellation to the configured runtime."""

        return self._runtime.cancel(generation_id)
