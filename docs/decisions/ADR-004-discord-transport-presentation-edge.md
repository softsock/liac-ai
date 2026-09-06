# ADR-004 — Discord remains a replaceable transport/presentation edge

## Status

Accepted for the current architecture.

## Origin

Current reaffirmation.

## Scope

Discord message admission, edge metadata, presentation, and the dependency
direction between Discord and Core.

## Decision

**Architectural invariant:** Discord is a replaceable transport and presentation
surface. It may translate Discord events into Core requests and Core run events
back into Discord output, but Discord is not the owner of semantic history,
provider state, or character behavior.

**Current implementation:** `apps/discord-edge` admits one-to-one DM
`MESSAGE_CREATE` events, maps channel metadata to an opaque in-memory session
identity, consumes `ConversationRun` events, and owns typing, sends, edits,
continuations, and terminal presentation. Discord IDs do not enter Core
history or model requests.

## Historical rationale status

Contemporaneous rationale was not recovered. This ADR does not treat current
interpretation as historical fact.

## Current rationale

Discord is the current interaction surface for testing the future character,
while keeping semantic ownership independent of one vendor or transport makes
that surface replaceable.

## Consequences

- Core has no Discord dependency; the edge depends on Core.
- Guild listening, social behavior, voice, persistence, memory, character
  behavior, tools, MCP, and provider continuation are outside this edge.
- Delivery pacing and presentation reconciliation cannot change canonical Core
  history.

## Evidence

- [Architecture: Discord text edge](../ARCHITECTURE.md#discord-text-edge)
- [Discord edge README](../../apps/discord-edge/README.md)
- [Discord edge implementation](../../apps/discord-edge/src/lilavel_discord_edge/edge.py)

## Revisit conditions

Revisit if an approved interaction surface becomes semantic owner, Discord
requirements expand beyond the current DM edge, or a separately approved
transport needs different ownership or identity semantics.
