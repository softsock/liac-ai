# LILAVEL-ARAS-M4A — Runtime legibility baseline

Status: COMPLETED
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel` - canonical Lilavel repository checkout
Branch / worktree: `feat/conversation-core`
Base commit: `a7d0b8cca2a38961513838d220e6bc01cadfd82d`
Last checkpoint commit: `a7d0b8cca2a38961513838d220e6bc01cadfd82d`

## Goal

Establish a read-only baseline for how well a fresh Codex agent can observe,
reproduce, correlate, and reason about Lilavel runtime behavior using only
repository-local surfaces.

## Scope

- Core, model-sidecar, and Discord-edge entrypoints, tests, fixtures, probes,
  diagnostics, persistence surfaces, artifacts, and canonical docs.
- Three bounded fresh-agent debugging simulations using existing tests,
  fixtures, source, and documentation only.
- Explicit deterministic, platform-specific, live, BLOCKED, and UNVERIFIED
  evidence classification.

## Non-goals

- No runtime/source/test/docs/config/hook/CI changes or observability,
  replay, provider, Discord, voice, or identity redesign.
- No live provider or Discord calls and no commit.

## Preflight

- Canonical checkout: `C:\Lilavel`.
- Branch: `feat/conversation-core`.
- HEAD and origin: `a7d0b8cca2a38961513838d220e6bc01cadfd82d`.
- Initial index/worktree: no staged or tracked diff; one pre-existing
  untracked `work/completed/ARAS-M3D-integrated-adversarial-enforcement-eval.md`.
- Current `work/completed/` contains M3A, M3B, M3C-1, M3C-2, M3C-3, and the
  untracked M3D record. No standalone M1/M2 record is present in the current
  `work/` tree; M2 continuity is referenced by the M3A record.

## Results

- Core deterministic suite: `118 passed` on Windows.
- Model-sidecar deterministic suite: `64 passed`; TypeScript check passed.
- Discord-edge deterministic suite: `62 passed`; the existing `discord.py`
  `audioop` deprecation warning remained.
- Core and Discord lock, Ruff, format, and Pyright checks passed.
- Credential-free Discord transport probe returned
  `{"status":"BLOCKED","reason":"missing LILAVEL_DISCORD_BOT_TOKEN"}`.
- No live provider, live Discord, or external restart evidence was attempted.
- Tracked Discord JSONL artifacts are historical and poorly discoverable; a
  PowerShell-captured sample set contains `uv :`-prefixed non-JSON lines and
  is not parseable as a complete JSONL stream.

## Baseline findings

- Strong: canonical ownership and assistant-commit semantics are documented;
  deterministic fake sidecars cover cancellation, supersession, malformed
  frames, poisoning, process failure, and persistence restart; protocol V2 has
  a shared corpus; Discord diagnostics have tested event allowlists and safe
  redaction paths.
- Fragmented: there is no documented offline Core conversation runner, no
  local fake-sidecar CLI, no local fake Discord end-to-end command, no runtime
  event log, and no persisted cross-boundary evidence bundle.
- Core exposes `run_id`, message IDs, scope IDs, canonical/evidence records,
  and `ModelRuntime` exposes generation ID/epoch, but the protocol carries only
  generation ID/epoch. The Discord edge and diagnostics do not propagate Core
  run/scope/message identity, and provider IDs/session selection are not
  semantic conversation identity.
- End-to-end local traceability is `PARTIAL`: Core generation-to-sidecar
  correlation is possible; Core semantic run → sidecar diagnostics → provider
  response → Discord message correlation breaks at the Core protocol boundary,
  provider boundary, and Discord presentation boundary.

## Scorecard

| Area | Score | Basis |
| --- | ---: | --- |
| Runtime surface discoverability | 2 | Package docs name commands, but offline/debug surfaces are fragmented. |
| Local reproducibility | 2 | Deterministic fixtures are broad but mostly test-only. |
| Identity correlation | 1 | Local identities exist, but cross-boundary propagation is incomplete. |
| Diagnostics readability | 2 | Sidecar/Discord diagnostics are structured; Core drains stderr and no unified stream exists. |
| Replay/debug usability | 1 | Tests prove behavior but do not emit a reusable runtime trace/replay artifact. |
| Persistence inspectability | 2 | SQLite APIs and restart tests are clear; no inspection CLI/artifact exists. |
| Validation/evidence clarity | 3 | `docs/VALIDATION.md` clearly separates deterministic, live, platform, BLOCKED, and UNVERIFIED. |
| Live/runtime uncertainty handling | 3 | Missing credentials are explicitly BLOCKED and local readiness is not overstated. |
| Fresh-agent debugging efficiency | 1 | Three simulations recovered answers only after multi-file archaeology and source inference. |

## Debugging simulations

1. Superseded generation: `test_conversation.py` with the Core conversation
   source, architecture docs, and the Discord supersession test recovered the
   logical/physical cancellation order and stale-delta discard. The answer was
   deterministic but required source inference; no runtime trace exposed the
   event sequence directly.
2. Canonical partial output: the persistence restart and assistant-commit
   tests plus `persistence.py`, the Core README, and ADR-005 recovered that
   user input is durable immediately, partial assistant text is transient, and
   only successful completion is canonical. The answer was recoverable from
   deterministic evidence, but only through assertions/API inspection.
3. Sidecar failure classification: runtime malformed-frame, process-death,
   and global-poison tests plus `runtime.py`, `sidecar_protocol.py`, and the
   fake fixtures distinguished `ProtocolViolation`, `SidecarCrashed`, and
   runtime-poisoned non-reuse. The answer was deterministic; provider-level
   causality remained unavailable.

## Gaps

- `DISCOVERABILITY GAP`: offline Core/sidecar/Discord debugging paths are
  test-oriented rather than directly runnable and observable.
- `CORRELATION GAP`: `run_id`, `scope_id`, canonical message/evidence IDs,
  generation ID/epoch, sidecar request IDs, and Discord operation/message IDs
  are not one traceable evidence chain.
- `DIAGNOSTICS GAP`: Core has no retained/queryable lifecycle diagnostics and
  drains sidecar stderr; Discord diagnostics correlate only presenter/HTTP
  operations locally.
- `REPLAY GAP`: no repository-supported replay or capture bundle exists for a
  full local conversation/presentation lifecycle.
- `VALIDATION GAP`: tests assert behavior but do not by themselves establish
  runtime observability, provider behavior, or live Discord delivery.
- `LIVE-EVIDENCE GAP`: provider and Discord credentials are external
  constraints, not evidence of a repository design defect.
- `INTENTIONAL BOUNDARY`: provider auth/session state, provider response IDs,
  Discord IDs in Core semantics, and partial assistant text outside canonical
  history are intentionally excluded by current architecture.

## Recommendation

Lilavel is not yet sufficiently runtime-legible for autonomous Codex debugging.
M4 does not need a broad observability platform build, but it does need a small
targeted improvement phase. The next step should be `M4B — Runtime Evidence
Model` before implementation: define the minimum agent-readable evidence and
cross-boundary correlation contract, preserving current semantic ownership and
redaction boundaries. Do not skip directly to an implementation plan.

## Handoff

- Git/checkout state: branch `feat/conversation-core`, HEAD/checkpoint
  `a7d0b8c`; no commit created by M4A.
- Uncommitted changes: the pre-existing untracked M3D completed record and
  this untracked completed M4A record; no source/test/config/docs/CI changes.
- Blockers/unknowns: live provider, live Discord, provider response/session
  semantics, and restart evidence beyond deterministic SQLite tests remain
  `BLOCKED` or `UNVERIFIED` as classified above.
- Completion: M4A exit criteria satisfied; no runtime-legibility
  infrastructure was added.
