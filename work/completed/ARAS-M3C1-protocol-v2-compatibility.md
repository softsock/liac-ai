# LILAVEL-ARAS-M3C-1 - Protocol V2 cross-language compatibility enforcement

Status: COMPLETED
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel` - canonical Lilavel repository checkout
Branch / worktree: `feat/conversation-core`
Base commit: `4bd09afb48e3f6da50d1619550e64246081d5292`
Last checkpoint commit: `32448237b542e3144c88bcd6242ea08c49188a72`

## Goal

Implement the smallest deterministic shared-corpus check that detects semantic
Protocol V2 drift between the Python Core boundary and the TypeScript/Bun
sidecar boundary without changing runtime ownership or creating a schema source
of truth.

## Scope

- One repository-shared `testdata/protocol-v2/cases.json` corpus.
- Existing Python protocol tests and TypeScript protocol tests as consumers.
- Representative valid/invalid commands and events, normalized semantics,
  version/identity/epoch checks, and stable rejection categories.
- Read-only independent review, targeted validation, and a temporary drift
  proof if it can be reverted cleanly.
- This work record and the already-authorized M3B record compaction.

## Non-goals

- No Protocol V2 redesign or Protocol V3.
- No semantic ownership, provider/session, Discord, M3C-2, or M3C-3 change.
- No generic validator, generator, schema compiler, hook, rule, sandbox, CI,
  or live-provider claim.
- No forced shared event parser: TypeScript's existing outbound event
  validator/encoder remains the event-side consumer.

## Exit criteria

- One small language-neutral V2 corpus is consumed by both package test suites.
- Selected valid and invalid cases agree, with normalized valid semantics and
  stable rejection categories only where those are shared behavior.
- The corpus is documented as examples/test evidence, not a normative schema.
- Targeted authoritative checks, fixture/path checks, and `git diff --check`
  pass; no unrelated runtime/product/config/CI changes exist.
- Adversarial proof and independent read-only review find no material issue.
- This record names remaining `UNVERIFIED` evidence and the exact Git state.

## Current implementation state

`RESULT`: the bounded mechanism is implemented. The shared corpus is
`testdata/protocol-v2/cases.json` with 30 unique examples. Core consumes it
through `parse_command`/`parse_event`; the sidecar consumes it through
`parseCommand` for commands and its existing `encodeEvent` validator for
outbound events. Both normalize accepted values to the same wire semantics.
The corpus description explicitly keeps it as test evidence, not a schema.
No production source, runtime behavior, package manifest, hook, CI, or
configuration changed.

## Established results

- `RESULT`: all selected valid and invalid cases agree across both consumers;
  shared stable rejection categories are asserted without exact error text.
- `RESULT`: the temporary TypeScript V3-acceptance mutation caused the shared
  `command-version-three` test to fail, then was reverted exactly; the case
  passed again after restoration.
- `RESULT`: existing process/framing tests remain authoritative for JSONL
  newline handling, stdout-only protocol frames, stderr diagnostics,
  backpressure, and lifecycle behavior; the shared corpus does not duplicate
  those process tests.

## Remaining work

- None for the M3C-1 implementation. Its implementation and record were
  checkpointed by commits `32448237` and `815a492`.
- `OWN-01` and `AUTH-02` are not part of this item and remain unimplemented
  proposals from M3B.

## Next safe action

Proceed to the separately recorded M3C-2 (`OWN-01`); do not mix its paths or
design into this completed work item.

## Validation

- preflight and M3B state: `PASS` - canonical `C:\Lilavel`, branch
  `feat/conversation-core`, HEAD `4bd09af`, clean start state; committed M3B
  design was compacted from `work/active/` to `work/completed/` without a
  commit.
- shared fixture/path/link checks: `PASS` - UTF-8 JSON parsed, 30 unique IDs
  and expected case fields verified; both package-relative paths loaded the
  same file; changed work-record links/paths resolved; `git diff --check`
  passed.
- Core targeted: `PASS` - from `apps/core`, `uv run --locked pytest
  tests/test_sidecar_protocol.py` (47 passed).
- Core package: `PASS` - from `apps/core`, `uv sync --locked`, `uv lock
  --check`, Ruff check/format, Pyright, and full `uv run --locked pytest`
  (115 passed on Windows).
- sidecar targeted: `PASS` - from `apps/model-sidecar`, `npx --yes
  bun@1.4.0 run check` and `npx --yes bun@1.4.0 test
  tests/protocol.test.ts` (36 passed).
- sidecar package: `PASS` - frozen install, check, and full test suite (64
  passed).
- adversarial proof: `PASS` - one-sided V3 drift failed the shared case; source
  restoration and a post-restore targeted pass succeeded.
- independent read-only review: `PASS` - no duplicate schema authority,
  semantic mismatch, brittle error-text coupling, non-portable path, runtime
  change, overengineering, or M3C-2/M3C-3 scope creep found.
- live/provider/Discord/restart evidence: `UNVERIFIED` - not claimed and not
  required for this deterministic test mechanism.

## Handoff

- Git/checkout state: `feat/conversation-core` at
  `32448237b542e3144c88bcd6242ea08c49188a72`; the M3C-1 implementation and
  its active record were checkpointed in commits `32448237` and `815a492`.
- Task-owned implementation paths are committed. This record's status
  correction and active-to-completed relocation are current execution-state
  housekeeping and remain uncommitted until the next requested checkpoint.
  Nothing is staged; no unrelated implementation paths are present.
- Exit criteria: `SATISFIED` for the deterministic M3C-1 implementation and
  review scope; live/provider/Discord/restart claims remain `UNVERIFIED`.
- Promotion: no canonical architecture or decision was promoted.
- Recommendation: M3C-1 is closed; proceed to a separately recorded M3C-2
  with its own accepted scope.
