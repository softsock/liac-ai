# P1 — Fail-closed protocol reader shutdown

Status: COMPLETED
Updated: 2026-09-07
Repository / checkout: C:\Lilavel-m4c-integration
Branch / worktree: feat/conversation-core
Base commit: 6c931ec84082b9e9f0e5ecc100831add22d8d4b6
Last checkpoint commit: none; implementation and this capsule committed together

## Goal and scope
Normalize malformed Python protocol input and independently prevent a reader
exception from certifying clean shutdown. Scope: Python parser/runtime, focused
regressions, two shared negative cases. All other audit findings are excluded.

## Result
- FACT: untyped set membership leaked TypeError for array code/role; UTF-8
  encoding leaked UnicodeEncodeError; json.loads auto-detected non-UTF-8 bytes.
- FACT: the reader caught only selected exceptions; its finally path accepted
  expected shutdown with unknown/zero process exit, while ACK woke shutdown.
- RESULT: enum checks, explicit UTF-8 decoding and normalized Unicode/JSON
  failures now preserve ProtocolError. Duplicate/version protections remain.
- RESULT: the reader catches unexpected BaseException at its thread boundary;
  clean shutdown requires ACK, valid EOF, settled generation, zero process exit
  and containment. Shutdown waits for reader completion within its deadline.
- RESULT: original ACK + array-code frame regression fails closed 3/3, explicitly
  confirming process exit 0 before parsing the bad frame. Synthetic TypeError,
  RuntimeError and SystemExit also fail closed independently of normalization.
- DECISION: shared corpus adds array code/role only. TypeScript source is unchanged;
  Python Unicode/API rejection is tested locally, without claiming Unicode parity.

## Validation
Windows, deterministic/platform-specific: PASS — Core uv sync --locked,
uv lock --check, Ruff check, Ruff format --check, Pyright, pytest (160 passed).
An initial Pyright diagnostic on a redundant type guard was corrected before
final checks. Existing streaming/cancellation/recovery/containment tests pass.
Sidecar: PASS — Bun 1.4.0 frozen install, check, test (67 passed).
Repository: PASS — final diff reviewed and git diff --check.
Live provider: UNVERIFIED; not required or invoked for this fix.

## Closure
No unresolved in-scope ambiguity. No unrelated findings fixed or canonical
architecture changes promoted. Task-owned paths only are included in the commit;
initial worktree was clean. No further implementation is required for this item.
