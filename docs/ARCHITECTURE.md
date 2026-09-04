# Architecture

This document records established boundaries only.

## Semantic ownership

Lilavel Core owns semantic conversation state, conversation history, memory, and character/personality behavior. These are product semantics and remain inside Lilavel.

Provider and sidecar code may own authentication, network, and transport state. That state must not silently become Lilavel's semantic conversation memory, and character behavior must not be delegated to the provider transport.

## Model transport

A small TypeScript/Bun sidecar is intended for model transport where it is needed. It is a transport boundary, not a second conversational runtime.

The P0.2 provider layer selects `openai-codex/gpt-5.6-luna` from the pinned
`@oh-my-pi/pi-catalog` and invokes it directly through `@oh-my-pi/pi-ai`'s
`streamSimple`. Supported OMP authentication is resolved through its auth
broker/storage boundary. Each diagnostic request supplies its own caller-owned
context; the sidecar omits provider session state and uses SSE transport, so
semantic history remains outside the provider layer. OMP `AgentSession` is not
Lilavel's conversational runtime, and MCP/tools are not part of this boundary.

`ModelRuntime` in Python Core owns the local generation lifecycle. It starts a
persistent sidecar process, waits for a version-one `ready` frame, sends one
small prompt request at a time, and receives UTF-8 newline-delimited JSON
events. Core creates and tracks each generation's `generation_id` and `epoch`;
the sidecar echoes both values on accepted, delta, and terminal frames.

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
