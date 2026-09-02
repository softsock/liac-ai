# Lilavel

Lilavel is a communication-first AI system. Natural, responsive text interaction is its primary product priority.

## Project orientation

- [`AGENTS.md`](AGENTS.md) — project-specific operating contract.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — established ownership boundaries and interaction invariants.
- [`docs/STACK.md`](docs/STACK.md) — selected runtime and provider-layer technologies.

## P0.1 foundation

Lilavel Core is an importable Python 3.12 package managed with `uv` under [`apps/core`](apps/core). The model sidecar is an independent TypeScript package managed with Bun under [`apps/model-sidecar`](apps/model-sidecar). These packages contain foundation smoke coverage only; provider and product behavior remain out of scope.

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
