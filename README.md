# Lilavel

Lilavel is a communication-first AI system. Natural, responsive text interaction is its primary product priority.

## Project orientation

- [`AGENTS.md`](AGENTS.md) — project-specific operating contract.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — established ownership boundaries and interaction invariants.
- [`docs/STACK.md`](docs/STACK.md) — selected runtime and provider-layer technologies.

## P0.1 foundation

Lilavel Core is an importable Python 3.12 package managed with `uv` under [`apps/core`](apps/core). The model sidecar is an independent TypeScript package managed with Bun under [`apps/model-sidecar`](apps/model-sidecar). Core product semantics and cross-language integration remain out of scope for these milestones; the sidecar's direct provider boundary is defined under P0.2 below.

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
