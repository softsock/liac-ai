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

## Interaction invariants

Streaming and cancellation are first-class interaction concerns. Changes to the runtime or model transport must preserve both.
