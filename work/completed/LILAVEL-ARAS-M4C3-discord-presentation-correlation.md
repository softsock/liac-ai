# LILAVEL-ARAS-M4C-3 — Discord Presentation Correlation

Status: COMPLETED
Updated: 2026-09-06
Repository / checkout: `C:\\Lilavel` isolated worktree `C:\\Lilavel-m4c-3`
Branch / worktree: `work/m4c-3-discord-presentation-correlation`
Base commit: `6bcbc74f7e41f8cda870d54a37677442ca548909` (committed M4C-1)
Last checkpoint commit: `6bcbc74f7e41f8cda870d54a37677442ca548909`

## Goal

Extend ephemeral Discord presentation diagnostics so a fresh agent can join
semantic Core `run_id` to an opaque edge-local `core_run_id`, then to the
existing flush/operation/request evidence, without changing semantic
ownership, canonical state, or product behavior.

## Scope

- Discord edge diagnostics, presenter lifecycle wiring, package documentation,
  and focused fake-edge tests.
- Existing AUTH-02-style positive field allowlists and redaction guarantees.
- Deterministic usefulness and adversarial allowlist proofs.

## Non-goals

- No Core source/API, protocol, model-sidecar, provider/session, persistence,
  replay CLI, generic telemetry/event bus, or Discord social behavior change.
- No canonical Discord channel/message identity, raw content, URL, auth,
  response body, exception message, or new Discord-ID diagnostic field.
- No modification, merge, or commit of M4C-2.

## Preflight and isolation

- Canonical repository: `C:\\Lilavel`, branch `feat/conversation-core`, clean
  at `6bcbc74f7e41f8cda870d54a37677442ca548909`.
- M4C-1 presence: committed Core lifecycle trace and completed record at that
  HEAD.
- M4C-2 discovery: separate `C:\\Lilavel-m4c-2` worktree and branch
  `work/m4c-2-physical-sidecar-evidence`, same base HEAD, with eight
  task-owned uncommitted Core/sidecar paths and its untracked completed record.
  Its state was inspected before and after and was not modified.
- M4C-3 worktree: `C:\\Lilavel-m4c-3`, branch
  `work/m4c-3-discord-presentation-correlation`, based directly on committed
  M4C-1 `6bcbc74`; no unrelated pre-existing changes were present.

## Verified current identity/correlation map

The current edge receives `ConversationRun.run_id` in `_present_run`; channel
metadata is used only to select an opaque in-memory Core session. Existing
diagnostics already provide:

```text
presenter flush_id -> operation_id -> HTTP request_id
```

M4C-3 now provides:

```text
Core run_id == edge-local core_run_id
  -> presenter_flush_start/return.flush_id
  -> operation_start/return.operation_id
  -> http_request_start/response/exception.request_id
  -> presentation_outcome
```

`core_run_id` is an edge diagnostic alias of the existing opaque Core run
identity, not a new semantic identity. It is process-ephemeral and exists only
inside the diagnostics presentation context. It does not enter Core history,
`ModelRequest`, persistence, or the protocol.

Current presentation outcomes are represented as safe enums:

- completed run: `status=completed`, no reason;
- Core cancellation/supersession: `status=interrupted`, reason
  `cancelled` or `superseded`;
- edge cancellation: `status=interrupted`, reason `edge_cancelled`;
- bridge, missing-terminal, Core failure, or presenter failure: `status=failed`
  with the corresponding structured reason.

## Mechanism and rejected alternatives

Selected a diagnostics `ContextVar` presentation scope bound in
`DiscordTextEdge._present_run`. Operation and HTTP trace state capture the
scope key, while the presenter pump is created inside the scope so its child
task inherits the same correlation. A single safe `presentation_outcome`
record is emitted after presenter cleanup and bridge join.

Rejected alternatives:

1. Explicitly thread `core_run_id` through `ReplyPresenter` and
   `DiscordMessageSink`: wider signatures and more missed-path risk for a
   context that is already task-local.
2. Add `run_id` to Core history, protocol frames, or sidecar diagnostics:
   violates the M4B ownership boundary and is unnecessary for the existing
   `ConversationRun.run_id` edge seam.
3. Add Discord channel/message IDs to diagnostics: not needed for the join and
   would expand the redaction surface.

## Diagnostics contract

The explicitly allowlisted `core_run_id` field is present only on:

- `presenter_flush_start` and `presenter_flush_return`;
- `operation_start` and `operation_return`;
- `http_request_start`, `http_response`, and `http_request_exception`;
- `presentation_outcome`.

`presentation_outcome` contains only `core_run_id`, safe `status`, safe
structured `reason`, `flush_count`, `terminal_flush_count`, `kind`, and the
existing monotonic `at_s`. `semantic_selection` remains uncorrelated because
it is not needed to join the flush/operation/request chain. Uncorrelated
transport diagnostics preserve their previous field shape. No new field
contains channel/message IDs, URLs, auth, text, bodies, raw bucket IDs, or
exception messages.

## Tests and deterministic usefulness proof

Added focused tests using the existing fake Core/runtime/Discord edge:

- `test_edge_diagnostics_join_core_run_to_flush_operation_and_http_request_chain`
  obtains `run_id` from M4C-1 Core evidence, groups edge diagnostics by the
  equal `core_run_id`, and verifies flush → operation → request joins,
  completion outcome, and absence of channel/message/content sentinels.
- `test_superseded_edge_presentation_remains_correlated_to_its_own_run`
  proves the old run remains grouped as `interrupted/superseded` while the new
  run is independently `completed`; both retain their own HTTP chains.
- `test_concurrent_edge_presentations_do_not_cross_correlate_diagnostics`
  proves two simultaneous DM presentations have distinct run groups and no
  cross-run diagnostic key.
- `test_failed_core_run_records_safe_correlated_presentation_outcome` covers
  safe Core-failure classification without exposing `provider_error`.
- Diagnostics tests cover the positive allowlist, context isolation,
  request/flush joins, JSONL emission, exception paths, and existing sensitive
  sentinels.

The evidence-only proof uses Core runtime evidence for the semantic `run_id`
and Discord diagnostics for all edge IDs/outcome; it does not inspect response
text or Discord identifiers to establish the join.

## Adversarial proof

Temporarily injected `unauthorized_field="m4c3-unauthorized-sentinel"` into
`presentation_outcome`. The existing allowlist test failed exactly with:

```text
unexpected fields for presentation_outcome: {'unauthorized_field'}
```

The field was removed with the inverse patch. The guard then passed again, and
search confirmed no sabotage field or sentinel remains.

## Files changed

- `apps/discord-edge/src/lilavel_discord_edge/diagnostics.py`
- `apps/discord-edge/src/lilavel_discord_edge/edge.py`
- `apps/discord-edge/tests/test_diagnostics.py`
- `apps/discord-edge/tests/test_edge.py`
- `apps/discord-edge/README.md`
- this completed work record

No Core, sidecar, protocol source, shared corpus, SQLite schema, or Discord
channel/message identity path was changed.

## Validation

- Deterministic PASS — Discord `uv sync --locked`.
- Deterministic PASS — Discord `uv lock --check`.
- Deterministic PASS — Discord Ruff check.
- Deterministic PASS — Discord Ruff format check.
- Deterministic PASS — Discord Pyright: 0 errors, warnings, or informations.
- Deterministic PASS — full Discord-edge suite: `68 passed`.
- Deterministic PASS — `git diff --check`.
- Deterministic PASS — adversarial allowlist FAIL, exact restore, then focused
  guard PASS.
- Core targeted regression: NOT APPLICABLE; no Core-facing source/API usage
  changed. Existing Core M4C-1 evidence was read, not modified.
- Live Discord/provider/restart/full external E2E: BLOCKED or UNVERIFIED;
  no credential or live service was used. Existing `discord.py` `audioop`
  deprecation warning remains non-causal and unchanged.

## Independent read-only review

PASS. The final diff was reviewed for Core ownership leakage, accidental
canonical persistence, allowlist duplication, sensitive-field propagation,
ContextVar task inheritance, sequential/concurrent cross-run contamination,
presentation behavior changes, M4C-2 dependency/overlap, and M4C-4
overengineering. No material in-scope issue remained. The pump-creation
ordering issue found by the first focused run was fixed and covered by the
integration tests.

## Current Git state and handoff

- M4C-3 branch remains uncommitted with only the five listed Discord package
  files modified and this completed record untracked; nothing is staged.
- Canonical `C:\\Lilavel` remains clean at M4C-1 `6bcbc74`.
- M4C-2 remains separate and unmodified at its pre-existing uncommitted state.
- Ready for a human checkpoint.
- Later integration with M4C-2 should be an explicit separate step after the
  human gate. The paths are disjoint: M4C-2 owns Core/runtime/sidecar evidence;
  M4C-3 owns Discord diagnostics/presentation. Preserve the unchanged
  protocol and keep both evidence layers ephemeral and non-canonical.
