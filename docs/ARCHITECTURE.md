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
the sidecar echoes both values on accepted, delta, and terminal frames. The
sidecar owns provider cancellation and awaits provider iterator cleanup before
becoming reusable. Core rejects or ignores stale generation events and maps
malformed output or unexpected process death to Core-side failure.

The protocol host reserves stdout for machine-readable JSONL frames. Human
diagnostics use stderr. The protocol contains no conversation, memory,
character, social, voice, or tool state.

## Interaction invariants

Streaming and cancellation are first-class interaction concerns. Changes to the runtime or model transport must preserve both.
