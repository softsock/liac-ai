# LILAVEL-ARAS-M4C-1 — Core Semantic Lifecycle Trace

Status: COMPLETED
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel` - canonical Lilavel repository checkout
Branch / worktree: `feat/conversation-core`
Base commit: `cbdf64bd327499ac0c553c97fff072f860e81cfa`
Last checkpoint commit: `cbdf64bd327499ac0c553c97fff072f860e81cfa`

## Goal

Add a bounded, typed, Core-owned in-memory lifecycle evidence trace for
semantic conversation runs without changing canonical history or runtime
semantics.

## Scope

- Existing Core lifecycle and IDs were grounded in `conversation.py`, the
  runtime protocol types, and deterministic fake-runtime tests.
- `_RuntimeEvidenceTrace` stores frozen `RuntimeEvidenceRecord` values in a
  `deque(maxlen=256)`; `delta_discarded` is aggregated by run/generation/
  epoch/reason with count and UTF-8 byte total.
- `ConversationCore.runtime_evidence()` returns copied immutable snapshots.
- Focused semantic, redaction, boundedness, snapshot-safety, and persistence
  failure tests provide the usefulness proof.

## Non-goals

- No durable trace, logging backend, event bus, replay runner, sidecar
  projection, Discord correlation, provider/auth data, raw message content,
  hooks, CI, or commit.

## Exit criteria

- Required Core lifecycle facts are accurately represented and correlated.
- Trace is diagnostic-only, bounded, deterministic, and non-mutable to callers.
- Supersession/cancellation usefulness proof and required Core validation pass.
- Independent read-only review finds no material in-scope issue.

## Event contract

Implemented vocabulary: `turn_accepted`, `generation_bound`,
`cancel_requested`, `delta_discarded`, `generation_terminal`,
`assistant_commit`, and `run_terminal`.

Records contain sequence, `scope_id`, `run_id`, `user_message_id`, applicable
`generation_id`/`epoch`, post-persistence `assistant_message_id`, safe result /
reason / failure-code categories, and aggregate discard counts. No timestamp,
raw message content, provider/session/auth data, or Discord IDs were added.
`assistant_commit` is appended only after `append_assistant_message` succeeds.

## Inspection and retention

The only stable inspection surface is `ConversationCore.runtime_evidence()`;
it returns a tuple of copied frozen records and is distinct from
`canonical_history` and durable `evidence_records`. Sequence numbers provide
deterministic ordering. Capacity is `RUNTIME_EVIDENCE_CAPACITY = 256`, with
predictable oldest-first eviction; discarded-delta aggregates prevent token
volume from consuming one trace slot per delta.

## Usefulness proof

`tests/test_conversation.py::test_runtime_evidence_proves_supersession_and_aggregates_late_deltas`
reproduces supersession with the fake runtime. The old run's trace alone shows
`turn_accepted → generation_bound → cancel_requested(reason=superseded) →
delta_discarded(reason=not_current,count=3) → generation_terminal(cancelled) →
run_terminal(superseded)`, with no `assistant_commit`; late text is absent from
the trace representation and canonical history. The same test also proves the
three late deltas are aggregated rather than emitted per token.

`tests/test_conversation.py::test_runtime_evidence_is_bounded_and_evicted_oldest_first`
proves oldest-first eviction and preserves the most recent run's correlation.

## Independent review

A separate read-only red-team pass checked canonical authority, lifecycle
ordering, all failed/cancelled paths, binding/cancel races, bounded auxiliary
state, delta aggregation, payload redaction, snapshot isolation, brittle
internals, and overlap with M4C-2/3/4. No material in-scope issue remained.

## Validation

- Deterministic: PASS — `uv sync --locked` and `uv lock --check`.
- Deterministic: PASS — full Core Ruff check and format check.
- Deterministic: PASS — full Core Pyright check.
- Deterministic: PASS — targeted conversation/persistence tests: `24 passed`.
- Deterministic: PASS — full Core suite: `123 passed`.
- Deterministic: PASS — `git diff --check`.
- Deterministic persistence failure: PASS — no assistant commit is reported
  after injected assistant store failure; accepted user remains canonical.
- Provider/live/Discord/external restart/full-E2E: UNVERIFIED or BLOCKED —
  excluded from this Core-only slice. Deterministic local persistence tests
  were included in the full Core suite.

The first full-suite attempt observed one existing runtime-adversarial
shutdown-timeout race; the named test passed in isolation and the repeated
full suite passed with `123 passed`.

## Exit result

All M4C-1 exit criteria are satisfied. The trace is diagnostic-only and
process-ephemeral; it does not alter canonical history, assistant commit rules,
generation lifecycle, or external protocol boundaries.

## Files changed

- `apps/core/src/lilavel_core/conversation.py`
- `apps/core/src/lilavel_core/__init__.py`
- `apps/core/tests/test_conversation.py`
- `apps/core/tests/test_persistence.py`
- this completed work record

## Handoff

- Git/checkout state: `feat/conversation-core` at `cbdf64b`; no commit created.
- Uncommitted changes: the four task-owned source/test files are modified and
  this completed record is untracked; nothing is staged; no unrelated changes
  are present.
- Blockers/unknowns: live provider, live Discord, external restart, and full
  cross-boundary evidence remain outside this slice.
- Next safe action: human checkpoint review of M4C-1, then plan M4C-2 and
  M4C-3 in disjoint worktrees/owned paths; do not expand this trace into a
  generic exporter or event bus.
