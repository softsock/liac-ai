# Architecture

This document records established boundaries only.

## Semantic ownership

Lilavel Core owns semantic conversation state, conversation history, memory, and character/personality behavior. These are product semantics and remain inside Lilavel.

Provider and sidecar code may own authentication, network, and transport state. That state must not silently become Lilavel's semantic conversation memory, and character behavior must not be delegated to the provider transport.

## Model transport

A small TypeScript/Bun sidecar is intended for model transport where it is needed. It is a transport boundary, not a second conversational runtime.

The intended provider layer for `openai-codex/gpt-5.6-luna` is direct `@oh-my-pi/pi-ai` use. OMP `AgentSession` is not Lilavel's conversational runtime.

## Interaction invariants

Streaming and cancellation are first-class interaction concerns. Changes to the runtime or model transport must preserve both.
