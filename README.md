# Lilavel

Lilavel is a communication-first AI system. Natural, responsive text interaction is its primary product priority.

## Project orientation

- [`AGENTS.md`](AGENTS.md) — project-specific operating contract.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — established ownership boundaries and interaction invariants.
- [`docs/STACK.md`](docs/STACK.md) — selected runtime and provider-layer technologies.

## P0.1 foundation

Lilavel Core is an importable Python 3.12 package managed with `uv` under [`apps/core`](apps/core). The model sidecar is an independent TypeScript package managed with Bun under [`apps/model-sidecar`](apps/model-sidecar). Core owns product semantics; the sidecar provides only the direct model transport and the local runtime boundary described below.

The commands below assume Python 3.12 or newer, [`uv`](https://docs.astral.sh/uv/getting-started/installation/), and [Node.js](https://nodejs.org/en/download) with `npm`/`npx` are installed on the host. Use the [Python](https://www.python.org/downloads/) installer if Python is missing. Check the prerequisites first:

```powershell
python --version
uv --version
node --version
npm --version
```

From the repository root, run the authoritative Core checks in PowerShell:

```powershell
Set-Location apps/core
uv sync --locked
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest
```

The sidecar pins its Bun runtime and dependencies in `package.json` and `bun.lock`. If Bun is not already installed, the pinned runtime can execute the same commands through npm:

```powershell
Set-Location apps/model-sidecar
npx --yes bun@1.4.0 install --frozen-lockfile
npx --yes bun@1.4.0 run check
npx --yes bun@1.4.0 test
```

## P0.2 direct model sidecar

The sidecar now provides the first direct model-transport boundary. It pins
`@oh-my-pi/pi-ai@18.1.2` and `@oh-my-pi/pi-catalog@18.1.2`, discovers supported
OMP authentication internally, selects `openai-codex/gpt-5.6-luna`, and emits
incremental text events through `streamSimple`. It does not start an OMP
`AgentSession`, expose MCP/tools, or retain semantic conversation history. A
supported OMP authentication setup must already be available; P0.2 does not
add a login flow.

Run the sidecar checks and temporary diagnostic probes from its package:

```powershell
Set-Location apps/model-sidecar
npx --yes bun@1.4.0 install --frozen-lockfile
npx --yes bun@1.4.0 run check
npx --yes bun@1.4.0 test
npx --yes bun@1.4.0 run smoke -- "Reply exactly STREAM_OK."
npx --yes bun@1.4.0 run probe -- cancel-recovery
npx --yes bun@1.4.0 run probe -- isolation
```

## P0.3 Core ↔ sidecar runtime

`apps/core` exposes `ModelRuntime`, which starts the persistent sidecar, waits
for its `ready` event, submits one small `ModelRequest` at a time, streams
`TextDelta` events, cancels by generation ID, reports health, and shuts the
process down. Core creates a unique generation ID and epoch for each request;
the sidecar does not retain semantic conversation state.

The runtime uses UTF-8 newline-delimited JSON on the sidecar's stdin/stdout.
Every frame has `protocol_version: 1`. Commands are `generate`, `cancel`,
`health`, and `shutdown`; sidecar events are `ready`, `accepted`, `text_delta`,
`completed`, `cancelled`, `failed`, `health`, and `shutdown`. Generation-scoped
frames carry both `generation_id` and `epoch`. Stdout is reserved for these
protocol frames; diagnostics belong on stderr.

To run the persistent protocol host directly:

```powershell
Set-Location apps/model-sidecar
npx --yes bun@1.4.0 run protocol
```

The host authenticates and loads the configured direct model before emitting `ready`.
It permits one active generation, aborts and cleans up provider work for
`cancel`, and remains reusable for the next generation. Core ignores
well-formed late events from older or cancelled generations and treats
malformed output or unexpected process death as a failure.
