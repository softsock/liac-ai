# Validation

This document indexes the current checks and their interpretation. It records
what a command can establish; it does not claim that a check has been run.
There is no root-level validation command in the repository.

## Result vocabulary

- `PASS` — the named check completed successfully for its stated scope.
- `FAIL` — the named check ran and found a failure.
- `BLOCKED` — a required credential, host capability, platform, or external
  service was unavailable. `BLOCKED` is neither `PASS` nor `FAIL`.
- `UNVERIFIED` — no authoritative check or committed evidence establishes the
  claim.

Reports must name the package, command, host/platform, and scope. Do not turn a
deterministic fixture result into live-provider, restart, Windows, or Discord
evidence.

## Documentation-only checks

For documentation changes, review the changed paths and Markdown links, then
run from the repository root:

```powershell
git diff --check
```

No source, test, package, or provider validation is implied by this check.

## Deterministic package checks

Run the applicable package-local commands from the package directory.

### Core

```powershell
Set-Location apps/core
uv sync --locked
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest
```

These checks cover the Python Core package, its semantic conversation and
persistence tests, and its protocol fixtures.

### Model sidecar

```powershell
Set-Location apps/model-sidecar
npx --yes bun@1.4.0 install --frozen-lockfile
npx --yes bun@1.4.0 run check
npx --yes bun@1.4.0 test
```

These checks cover the TypeScript/Bun sidecar, protocol parsing, provider
adapter fixtures, and lifecycle tests without requiring a live provider.

### Discord edge

```powershell
Set-Location apps/discord-edge
uv sync --locked
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest
```

These checks cover the replaceable DM edge and its deterministic presenter,
transport, and semantic-streaming tests.

### Shared protocol boundary

Run both the Core and model-sidecar command sets when validating the shared
JSONL boundary. The Core tests cover the Python schema/runtime side; the
sidecar tests cover the TypeScript host/provider-adapter side. This is still
deterministic evidence, not live-provider evidence.

## Windows and other platform-specific checks

The Core pytest suite includes Windows-only checks for the real `npx` → Bun
launcher, process containment, and the Windows protocol path. Run the same Core
pytest command on Windows to exercise them. On other platforms, marked tests
may be skipped; a skipped platform-specific check is not a Windows `PASS`.
The POSIX fallback does not establish the Windows descendant-containment
guarantee.

## Live, provider, and credential-dependent checks

These commands require supported authentication or an external service and
must be reported separately from deterministic checks:

- Core's opt-in Luna probe: from `apps/core`,
  `uv run --locked python scripts/conversation_live.py`.
- Sidecar smoke and probes: from `apps/model-sidecar`,
  `npx --yes bun@1.4.0 run smoke -- "Reply exactly STREAM_OK."`,
  `npx --yes bun@1.4.0 run probe -- cancel-recovery`, and
  `npx --yes bun@1.4.0 run probe -- isolation`.
- Discord Stage A transport probe: from `apps/discord-edge`,
  `uv run --locked python scripts/transport_probe.py`.
- Discord Stage B Core-backed edge: from `apps/discord-edge`,
  `uv run --locked python scripts/run_edge.py`.

The Discord probes require the supported `LILAVEL_DISCORD_BOT_TOKEN` mechanism
and an actual Discord interaction. Missing credentials produce `BLOCKED`, not
live evidence. The live Core and sidecar checks require the provider's
supported auth-discovery setup. Do not extract, replay, or persist credentials
to make a check run. A sidecar `ready` or `health` event describes local state;
it does not prove provider endpoint availability, quota, entitlement, or
successful live interaction.

No live/provider result is claimed by this documentation unless the exact
command and result are separately executed and recorded.
