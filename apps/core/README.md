# Lilavel Core runtime

`ModelRuntime` owns the local lifecycle of the persistent model sidecar. It
owns generation IDs, epochs, admission, cancellation, event delivery, and
failure state. The sidecar remains a provider and process transport boundary;
it does not own conversation history, memory, character behavior, tools, or
other semantic session state.

## Lifecycle and admission

The runtime uses these states:

| State | Meaning |
| --- | --- |
| `new` | No sidecar process has been started. |
| `starting` | The process is running and Core is waiting for `ready`. |
| `ready` | Local sidecar/model readiness has been confirmed and one generation may be admitted. |
| `busy` | One generation is admitted. |
| `shutting_down` | Shutdown has closed admission; teardown is in progress. |
| `closed` | A started runtime shut down with acknowledgement, zero process exit, no unsettled handle, and confirmed process-containment teardown; an unstarted `new` runtime also becomes `closed` when shut down. |
| `failed` | A protocol, pipe, process, queue, cancellation, shutdown, or containment failure made the runtime unusable. |

The normal path is `new → starting → ready`, then `ready ↔ busy`. Shutdown
sets `shutting_down` while holding the same admission lock used by
`generate()`, before cancellation or teardown commands are sent. A concurrent
or later `generate()` therefore raises `RuntimeShuttingDown` synchronously.
There is no automatic restart: a `closed` or `failed` runtime is not reused.

`ready` and `health()` report local state and process information. They do not
probe the provider endpoint or establish quota, entitlement, or a successful
future model request. The default deadlines are 30 seconds for startup, 5
seconds for shutdown, 7 seconds for cancellation settlement, and 5 seconds
for each bounded command write.

## Generation settlement

Each returned `GenerationHandle` has one Core-generated `generation_id` and
monotonic `epoch`. On every completion, cancellation, failure, or shutdown
exit path, a returned handle receives exactly one terminal settlement: a
completed or cancelled `GenerationResult`, or a typed Core failure such as
`GenerationFailed`, `ProtocolViolation`, `SidecarCrashed`,
`CancellationTimeout`, `ShutdownTimeout`, or `EventQueueOverflow`. Repeated
terminal attempts do not settle the handle a second time. There is no
independent generation deadline, so an un-cancelled provider can remain active
until its caller cancels it or the runtime exits through another failure or
shutdown path.

Cancellation records caller intent and starts the bounded cancellation
deadline. `accepted` may legally arrive once after cancellation if the request
was already in flight; duplicate `accepted` frames and deltas before an
accepted frame are protocol failures while that request is active. Once a
generation has settled, duplicate or contradictory terminal frames are stale
and ignored. Deltas that arrive after Core enters `cancelling` are discarded.
A valid completion can win a completion/cancel race, so calling `cancel()` does
not guarantee a cancelled status.

If cancellation does not produce a terminal sidecar outcome before the
deadline, Core raises `CancellationTimeout`, marks the runtime failed, and
contains the owned process. The retained terminal event uses the corresponding
version-one `cancellation_timeout` code. Cleanup failures from the sidecar
(`cleanup_timeout` or `cleanup_error`) and forced protocol shutdown
(`shutdown_timeout`) also fail closed and prevent reuse. A stale generation
failure after a handle has already settled cannot create a second settlement,
but a generationless cleanup failure remains runtime-fatal.

Clean shutdown requires the version-one `shutdown` acknowledgement, a zero
child exit, no pending generation, and confirmed containment teardown. A
missing acknowledgement, abnormal child exit, forced shutdown deadline, or
unsettled handle leaves the runtime failed. A pending handle is settled before
forced containment so its failure preserves the known cause (`ShutdownTimeout`
or `SidecarCrashed`) instead of being replaced by child EOF. The stdout reader
remains strict through EOF: a non-empty unterminated line is a malformed
protocol frame, including after a shutdown request; only the sidecar's valid
acknowledgement followed by a zero exit is clean.

On Windows, Core launches the default `npx` entry point with
`CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP`, verifies Job Object
containment, and resumes it only after the containment handle is attached.
The separate console process group prevents an operator Ctrl+C from killing
the child in the middle of a JSONL frame; Core can instead send the defined
cancel-then-shutdown command sequence and require the normal acknowledgement.
Forced containment still covers the `npx`/Node/cmd/Bun descendant tree. The
POSIX fallback targets the owned process and does not claim the same
descendant guarantee.

## Streaming consumer contract

`events()` is the sole streaming consumer for a handle and permits one active
iterator. Consume it while the generation runs when streaming output is
needed. It yields `accepted`, queued `text_delta`, and one terminal event in
wire order.

`wait(timeout)` waits only for terminal settlement. It does not drain events
and does not cancel the generation when its timeout expires; a timeout raises
Python's `TimeoutError` and leaves the request active. A later `events()` call
can still drain already queued events.

The default per-generation Core event queue holds 128 non-terminal events,
including `accepted` and deltas. `event_queue_size` may set another positive
bounded capacity. If a producer reaches a full queue, Core raises
`EventQueueOverflow`, fails the runtime closed, and retains the one terminal
failure out of band. The terminal event is delivered after the queued events
drain, so a full queue cannot hide the terminal outcome. Queue storage remains
bounded: a wait-only consumer succeeds when its stream fits, while a stream
that reaches the configured capacity is an explicitly fail-fast overload.

Only deltas successfully accepted into the Core queue contribute to
`GenerationHandle.text` and `GenerationResult.text`. Cancellation returns the
partial text available at that boundary. A delta already queued before
cancellation may still be yielded afterward; later stale or cancelled deltas
cannot leak into that generation or a later one.

The version-one protocol bounds a prompt at 64 KiB, each delta at 16 KiB, the
accumulated Core response at 256 KiB, each frame at 256 KiB, and each ID at
128 UTF-8 bytes. Older generation events are ignored. Future epochs,
mismatched identities, malformed frames, and invalid lifecycle transitions
fail closed.

## Structured caller-owned context

`ModelRequest` also accepts a non-empty ordered tuple of `ContextMessage`
values. Each value contains only `role` (`"user"` or `"assistant"`) and
`text`; aggregate UTF-8 text is bounded to 64 KiB. For example:

```python
ModelRequest(
    messages=(
        ContextMessage("user", "Remember the word quartz."),
        ContextMessage("assistant", "ACK_1"),
        ContextMessage("user", "What was the word?"),
    )
)
```

Core sends this as the version-one `generate.messages` array. The complete
caller-owned context is sent on every request; Core does not persist pi-ai or
provider-specific fields. The sidecar performs the provider adapter mapping
and retains no semantic conversation state. The legacy `prompt` form remains
available for single-turn callers.

## Semantic conversation layer

`ConversationCore` owns canonical conversation history above `ModelRuntime`.
`start_turn()` accepts the user message into history immediately and returns a
`ConversationRun`. The run surfaces assistant deltas incrementally as a
transient candidate; only a successful completion is appended once as a
canonical assistant message. Cancellation, supersession, runtime failure, or
context validation failure never commits partial assistant text.

There is at most one logical active run per conversation. A new turn may
supersede the current run; Core requests physical cancellation through
`ModelRuntime` and waits for that runtime generation to settle before asking
the single-generation runtime to start the new request. Late output from the
older run is discarded and cannot enter the new run's event stream.

`ConversationContextComposer` is the narrow seam between canonical history and
model input. The initial `FullHistoryContextComposer` sends the complete
provider-neutral `role`/`text` history as a version-one structured request.
Provider metadata, session state, tools, and transport details remain outside
this layer.

The opt-in live Luna probe uses the existing supported authentication and
prints only semantic results and timing observations:

```powershell
uv run --locked python scripts/conversation_live.py
```

The authoritative Core checks are run from this directory:

```powershell
uv sync --locked
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest
```
