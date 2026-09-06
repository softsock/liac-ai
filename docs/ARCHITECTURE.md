# Architecture

This document records established current boundaries only. Lilavel is intended to become a real-time autonomous AI character / AI streamer, but streamer-specific capabilities are outside the implemented architecture unless separately documented. The current architecture is the conversational foundation for that later work.

## Semantic ownership

Lilavel Core owns the implemented semantic conversation state and boundaries: canonical conversation history, context composition, generation lifecycle, and local canonical/evidence persistence. Memory, retrieval, reflection, memory injection, and final character/personality behavior are not implemented in the current slice. See [ADR-001](decisions/ADR-001-core-owns-canonical-conversation-state.md) and [ADR-005](decisions/ADR-005-canonical-history-provenance.md).

Provider and sidecar code may own authentication, network, and transport state. That state must not silently become Lilavel's semantic conversation memory, and semantic behavior is not delegated to the provider transport.

`ConversationCore` is the narrow semantic layer above `ModelRuntime`. It
accepts each user message into canonical history immediately. A
`ConversationRun` exposes streamed assistant deltas as transient candidate
output; only one successful completion is committed as the canonical assistant
message. Cancellation, supersession, failure, and stale generations do not
commit partial assistant output. Core permits one logical active run per
conversation and delegates physical cancellation and generation settlement to
`ModelRuntime`.

Canonical history is composed into model input through a small
`ConversationContextComposer` seam. The initial composer sends the complete
provider-neutral structured role/text history. This keeps future context
selection and compaction separate from canonical storage without adding
provider continuation state. Core's local persistence layer stores canonical
messages and raw provenance evidence; it does not yet implement memory claims,
retrieval, reflection, or memory injection.

`ConversationCore` accepts a user message only after an atomic append to its
Core-owned `ConversationStore`, and it commits an assistant message only after
a live generation completes successfully. The store writes the canonical
message and its raw evidence record in one SQLite transaction. Cancelled,
superseded, failed, stale, and partial assistant output has no persistence
path. A durable caller supplies an explicit provider-neutral scope ID and
reopens the same SQLite database; the Discord edge does not supply or own this
mapping in this slice. By default, `ConversationCore` uses SQLite `:memory:`;
restart-safe history is therefore not the default. The transaction is the
assistant commit point: a crash before it leaves only the accepted user, while
a crash after it can leave a durable assistant whose delivery acknowledgement
was not observed.

## Model transport

A small TypeScript/Bun sidecar is intended for model transport where it is needed. It is a transport boundary, not a second conversational runtime. See [ADR-002](decisions/ADR-002-provider-sidecar-transport-boundary.md).

The P0.2 provider layer selects `openai-codex/gpt-5.6-luna` from the pinned
`@oh-my-pi/pi-catalog` and invokes it directly through `@oh-my-pi/pi-ai`'s
`streamSimple`. Supported OMP authentication is resolved through its auth
broker/storage boundary. Each diagnostic request supplies its own caller-owned
context; the sidecar omits provider session state and uses SSE transport, so
semantic history remains outside the provider layer. OMP `AgentSession` is not
Lilavel's conversational runtime, and MCP/tools are not part of this boundary.

`ModelRuntime` in Python Core owns the local generation lifecycle. It starts a
persistent sidecar process, waits for a version-two `ready` frame, sends one
small prompt request at a time, and receives UTF-8 newline-delimited JSON
events. Core creates and tracks each generation's `generation_id` and `epoch`;
the sidecar echoes both values on accepted, delta, and terminal frames. See
[ADR-003](decisions/ADR-003-core-generation-lifecycle.md).

Core admission and teardown are serialized. Shutdown closes admission under
the same lock used by generation admission, then moves through
`shutting_down`; a new generation receives `RuntimeShuttingDown`. A clean
close requires the shutdown acknowledgement, zero process exit, no unsettled
generation, and confirmed process-containment teardown. Protocol, pipe,
abnormal-exit, queue, cancellation-deadline, or containment failures leave the
runtime `failed` and do not trigger an automatic restart. Every returned
generation handle receives exactly one terminal settlement on completion,
cancellation, failure, or shutdown exit. A caller that never cancels a hung
provider has no separate generation deadline.

The sidecar owns provider cancellation and must finish iterator cleanup before
becoming reusable. Its cleanup deadline also covers the optional provider
stream result acknowledgement. A rejected or timed-out cleanup emits a
generation-scoped failure, poisons the sidecar, and prevents `ready` or
same-process reuse. Core accepts one in-flight `accepted` frame after caller
cancellation, drops later deltas for that generation, and permits the valid
terminal event that wins a completion/cancellation race. Older settled events
are ignored; future, mismatched, malformed, or otherwise invalid events fail
closed.

The protocol host reserves stdout for machine-readable JSONL frames. Human
diagnostics use stderr. The protocol contains no conversation, memory,
character, social, voice, or tool state.

## Caller-owned structured text context

The version-two `generate` command supports a structured request alongside the
legacy single `prompt` shape. Core may send a non-empty ordered array whose
only fields are:

```json
{"role":"user","text":"Remember the word quartz."}
{"role":"assistant","text":"ACK_1"}
```

`role` is limited to `user` or `assistant`; the aggregate UTF-8 text is
bounded to 64 KiB. Core owns the complete context supplied for each request
and retains only this provider-neutral role/text representation. It does not
store provider, API, model, usage, response IDs, or provider payloads.

The sidecar adapts each request to pi-ai `Context.messages`. User messages use
their text as the pi-ai content string. Completed assistant history becomes a
pi-ai assistant message with one text content block; the sidecar supplies the
required local adapter fields (`api`, `provider`, `model`, zeroed placeholder
usage, `stopReason: "stop"`, and a timestamp). It never forwards
`providerPayload` or `responseId` for this contract. Optional Core-owned trusted
guidance is mapped to pi-ai `Context.systemPrompt`; absent guidance leaves that
field unset. Trusted guidance is application-owned compiler output, never a
copy or transformation of caller/user text. The context has no tool definitions. The provider adapter may
still serialize empty provider-required scaffolding, but it adds no caller tool
semantics or MCP behavior.

The full structured context is sent on every request. The sidecar does not
use `AgentSession`, MCP/tools, provider `sessionId`, `providerSessionState`,
or `statefulResponses` continuation for this boundary, and it keeps
`preferWebsockets: false`. The existing prompt form remains accepted in version
two so current single-turn callers retain the same prompt/messages field shape.
The strict schema change that adds optional trusted guidance is a protocol
version bump; version-one peers are not mixed-version compatible.

## Interaction invariants

Streaming and cancellation are first-class interaction concerns. Changes to the runtime or model transport must preserve both.

`GenerationHandle.events()` is the sole streaming consumer. It uses a bounded
per-generation queue (128 events by default) for accepted and text-delta
events; a full queue raises `EventQueueOverflow` and fails closed. The terminal
failure is retained separately so a full queue cannot hide settlement.
`wait(timeout)` waits for settlement only: it does not drain events or cancel
the request, and a timeout leaves the request active. Core text is bounded to
256 KiB and contains only deltas accepted into that queue, so cancelled output
is explicitly partial.

`ready` and `health` describe local model, sidecar, and process state. They do
not prove provider endpoint availability, quota, or entitlement. The default
Windows launcher is placed in a verified Job Object with kill-on-close before
the suspended process is resumed; forced containment therefore covers the
`npx`/Bun descendant tree. If containment setup cannot be established, Core
fails closed. The POSIX fallback targets the owned process and does not claim
the same descendant guarantee.

## Discord text edge

The initial Discord integration lives in `apps/discord-edge` and depends on
`lilavel-core`; Core has no Discord or `discord.py` dependency. This edge is a
transport/presentation adapter only. See
[ADR-004](decisions/ADR-004-discord-transport-presentation-edge.md):

```text
Discord MESSAGE_CREATE (one-to-one DM)
        │
        ▼
apps/discord-edge
  channel metadata → opaque in-memory session identity → ConversationCore
        │                                              │
        │                                              ▼
        │                                       role/text ModelRequest
        ▼
Discord typing, send, coalesced edit, continuation
```

The Discord channel ID never enters canonical Core history or a model request.
Each mapped DM session owns one `ConversationCore` and the existing
`ModelRuntime`; this preserves the current runtime's one-physical-generation
boundary while keeping histories separate. The edge does not add provider
continuation or session state.

Only one-to-one DM `MESSAGE_CREATE` is admitted. The edge requests only the
standard `DIRECT_MESSAGES` gateway intent, does not enable guild or privileged
message-content behavior, and has no message-update/delete handlers. It does
not import Discord channel history. Self/bot messages are ignored. A bounded
4096-entry in-memory LRU keyed by the Discord `message_id` is claimed before
the Core call, making Gateway replay idempotent for the life of the process;
eviction and process restart are intentionally outside this slice.

The edge consumes only `ConversationRun` semantic events. It owns a blocking
iterator bridge and explicit response tasks, starts Discord typing while Core
waits for the first delta, materializes the first meaningful delta immediately,
and admits later edits only at a configurable cadence. Terminal completion,
cancellation/supersession, and failure each perform one terminal flush. The
presenter marks interrupted output visibly and marks failures without exposing
provider errors. Core remains the only owner of canonical assistant commit;
partial, cancelled, superseded, or failed assistant text is not added to
history. All model-generated creates and edits use `AllowedMentions.none()`,
and every content chunk is at most Discord's 2000-character limit.

The transport edge deliberately excludes guild ambient listening, social
attention, slash commands, voice/DAVE, persistence, memory, character
behavior, tools, MCP, and `AgentSession`. Discord voice remains a separate
future transport concern.
