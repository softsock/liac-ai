# Lilavel Discord text edge

This package is a replaceable, DM-only text edge. It depends on
`lilavel-core`; Core does not depend on Discord or `discord.py`.

## Stage A: isolated transport probe

The probe does not create a `ConversationCore` or call Luna. It requests only
the Discord `DIRECT_MESSAGES` intent, waits for one human-authored one-to-one
DM, starts a typing context, sends a synthetic response, edits the same
response with coalesced chunks, and exercises safe continuation messages over
2000 characters. It reports operation timings, surfaced HTTP 429 observations,
and reconnect events without printing credentials or message contents.

The only supported credential variable is `LILAVEL_DISCORD_BOT_TOKEN`. If it
is absent, the probe exits successfully with a deterministic `BLOCKED` report;
that is not live evidence.

The event callback only completes the transport exercise and signals its
completion. The application-owned probe runner owns the `Client.start()` task,
closes the client after that signal, awaits both the Discord start/connect task
and the callback settlement, and then computes `shutdown_clean`. A clean value
requires the awaited client close to complete, `client.is_closed()` to be true,
the start/connect task to finish normally, the event callback to have settled,
and the observable websocket to be closed. It does not treat an empty global
`asyncio` task set as a shutdown contract.

```powershell
Set-Location apps/discord-edge
uv sync --locked
uv lock --check
uv run --locked python scripts/transport_probe.py
```

With the variable configured, start the probe and send one DM to the bot. The
probe closes the client after the transport exercise. discord.py owns gateway
reconnect/resume behavior; this one-shot probe reports whether a reconnect or
resume event actually occurred, but does not manufacture a disconnect.

## Stage B: Core-backed DM edge

```powershell
uv run --locked python scripts/run_edge.py
```

Each direct-message channel is kept as edge metadata and maps to a private,
opaque session identity and its own `ConversationCore`. The Discord channel
ID is never placed in Core history or a `ModelRequest`. The default session
runtime is the existing `ModelRuntime`, using the persistent Bun/Luna sidecar
path already owned by Core. No provider continuation or new provider state is
added.

Only `MESSAGE_CREATE` is handled. Bot/self-authored messages, guild messages,
group DMs, edits, deletes, and imported Discord history are ignored. A bounded
4096-entry in-memory message-ID LRU admits a message before the Core call, so
Gateway replay within one process cannot create a second semantic turn. The
bound and process lifetime are explicit limitations; there is no durable
Discord idempotency store in this slice.

Core remains responsible for canonical history, successful assistant commit,
one active run per conversation, supersession, and physical cancellation.
The edge consumes only semantic run events. It starts typing before Core/model
work and gives each response an owned presenter pump. The first meaningful
delta materializes a message as soon as practical; later deltas update one
latest-text snapshot. At most one Discord reconciliation is in flight, and a
configurable minimum cadence floor (currently `0.2` seconds by default) limits
new publish attempts without imposing a fixed 0.5-second wait after every
edit. When an edit completes, a newer snapshot is published on the next
eligible wake-up; a timer wake-up prevents queued deltas from waiting for an
unrelated future delta. A terminal event forces exactly one final
reconciliation. Every create and edit passes `AllowedMentions.none()`.
Text is split on Unicode code-point boundaries into messages of at most 2000
characters. Cancelled or superseded output is marked `[response interrupted]`;
failed output is marked `[response unavailable]` and failed assistant text is
never committed by Core.

The current `ModelRuntime` admits one physical generation at a time. Keeping
one runtime with each mapped Core session preserves that existing boundary and
isolates histories; a future shared-runtime scheduler would be a separate
design decision.

## Package checks

```powershell
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest
```

The package deliberately contains no guild ambient listening, slash commands,
voice, DAVE, persistence, memory, character behavior, tools, MCP, or
`AgentSession` integration.
