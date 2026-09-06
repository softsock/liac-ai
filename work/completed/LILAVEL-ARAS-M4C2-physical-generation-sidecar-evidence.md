# LILAVEL-ARAS-M4C-2 — Physical Generation / Sidecar Evidence Projection

Status: COMPLETED
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel`, isolated M4C-2 worktree
Branch / worktree: `work/m4c-2-physical-sidecar-evidence` / `C:\Lilavel-m4c-2`
Base commit: `6bcbc74f7e41f8cda870d54a37677442ca548909`
Last checkpoint commit: none

## Goal

Extend the ephemeral runtime-evidence chain so a fresh agent can correlate:

```text
ConversationCore run_id
  -> Core generation_bound generation_id + epoch
  -> ModelRuntime physical protocol evidence
  -> sidecar requestId alias and terminal outcome
```

The projection must remain diagnostic-only, bounded, provider-neutral, and
separate from canonical conversation state.

## Scope and non-goals

- Added a bounded Core `ModelRuntime.physical_evidence()` snapshot over the
  existing version-two generation protocol events.
- Verified and documented the existing sidecar `requestId` alias contract.
- Added deterministic Core↔sidecar correlation, cancellation, failure,
  boundedness, redaction, and snapshot-isolation tests.
- Added sidecar observer/protocol tests without changing the protocol schema.
- Updated the scoped Core/sidecar package documentation.

Excluded Discord/M4C-3 files, replay runner/M4D, generic logging or telemetry,
event bus, durable trace storage, provider/session state, credentials, URLs,
raw messages/deltas, exception bodies, protocol redesign, and canonical
persistence changes. No commit was created.

## Verified current identity map

- `ConversationCore.start_turn()` creates semantic `run_id` and Core-owned
  canonical message identities.
- `ModelRuntime._generate_impl()` creates the physical UUID `generation_id`
  and monotonic `epoch`, then sends both in the existing `GenerateCommand`.
- Version-two generation-scoped commands/events carry only
  `generation_id`+`epoch`; `run_id` does not cross the protocol boundary.
- `ProtocolServer` passes the command pair as `GenerationIdentity` to
  `ModelSidecar.generate()`.
- On that protocol-host path, `ModelSidecar.generate()` sets
  `requestId = identity.generationId`; sidecar `requestId` is therefore exactly
  the Core `generation_id`, not a second semantic identity.
- Sidecar direct observer events already expose request/epoch correlation and
  safe event metadata; protocol stdout projects only the existing v2 event
  shape. Core previously retained no physical event history.
- Core stderr remains a drained diagnostic stream, not the evidence surface.

## Mechanism selected

`ModelRuntime` now owns a `deque(maxlen=256)` of frozen
`PhysicalGenerationEvidenceRecord` values, exposed through a copied
`physical_evidence()` tuple. The optional capacity is validated as a positive
integer. Records contain only:

- monotonic local sequence;
- `generation_id` and `epoch`;
- `generation_created`, `protocol_event`, or `generation_terminal` kind;
- safe protocol event/result enums;
- safe failure codes;
- aggregate event count and UTF-8 byte length for `text_delta`.

Text-delta content is never retained. Repeated text-delta protocol events for
one generation are aggregated. Physical terminal evidence is idempotent per
generation/epoch. Snapshot records are copied frozen dataclasses, and bounded
eviction cleans the auxiliary aggregation indexes.

The Core semantic trace remains the join authority from `run_id` to
`generation_id`/`epoch`. The physical trace does not add `run_id`, `scope_id`,
message IDs, provider IDs, session IDs, or a duplicate `sidecar_request_id`.

### Minimal alternatives considered

1. Add `run_id` or a new request field to the Core↔sidecar protocol — rejected:
   it would widen the transport contract and leak semantic identity into the
   provider boundary.
2. Add a separate sidecar request-ID field to Core evidence — rejected:
   current protocol execution already makes `requestId` an exact alias of
   `generation_id`, so a second field would duplicate correlation and create
   drift risk.
3. Keep only the existing direct sidecar observer — insufficient for a
   post-run Core-side join because the observer is not retained by Core and
   stdout must remain protocol-only.

The selected option reuses the existing protocol/runtime identity and records
only a bounded safe projection at the Core runtime boundary. No protocol
source or shared compatibility corpus changed.

## Evidence contract and usefulness proof

For the successful structured sidecar fixture, the evidence-only join proves
for each of two semantic runs:

```text
Core runtime_evidence(): run_id -> generation_bound(generation_id, epoch)
ModelRuntime physical_evidence():
  generation_created
  protocol_event(accepted)
  protocol_event(text_delta, count=1, byte length only)
  protocol_event(completed)
  generation_terminal(result=completed)
```

The proof does not inspect response text to establish the correlation, and
the physical snapshot representation contains none of the fixture output.

The deterministic cancellation proof shows the same generation pair through
`accepted -> text_delta -> cancelled -> generation_terminal(cancelled)`. The
failure proof shows `accepted -> failed(cleanup_timeout) ->
generation_terminal(failed, cleanup_timeout)`. A process-crash proof shows
`accepted -> generation_terminal(failed, sidecar_crashed)` when no sidecar
terminal frame exists.

## Files changed

- `apps/core/src/lilavel_core/runtime.py`
- `apps/core/src/lilavel_core/__init__.py`
- `apps/core/tests/test_runtime.py`
- `apps/core/tests/test_conversation.py`
- `apps/core/README.md`
- `apps/model-sidecar/tests/model-sidecar.test.ts`
- `apps/model-sidecar/tests/server.test.ts`
- `apps/model-sidecar/README.md`
- this completed work record

No `apps/discord-edge` file was changed. No protocol source, shared corpus,
SQLite schema, persistence implementation, or canonical conversation contract
was changed.

## Validation

- Deterministic PASS — Core `uv sync --locked`.
- Deterministic PASS — Core `uv lock --check`.
- Deterministic PASS — Core Ruff check and format check.
- Deterministic PASS — Core Pyright: 0 errors, warnings, or informations.
- Deterministic PASS — focused Core evidence/protocol/conversation tests:
  `69 passed` before final added bounded/failure assertions; final runtime
  evidence tests: `11 passed`.
- Deterministic PASS — full Core suite: `127 passed`.
- Deterministic PASS — frozen sidecar install:
  `npx --yes bun@1.4.0 install --frozen-lockfile`.
- Deterministic PASS — sidecar TypeScript check: `tsc --noEmit`.
- Deterministic PASS — full sidecar suite: `65 pass`, `0 fail`, `217 expect()`.
- Deterministic PASS — sidecar protocol parity tests remain green; no shared
  protocol corpus changed.
- Deterministic PASS — `git diff --check`.

## Independent review

PASS. The final read-only review found no material in-scope issue:

- semantic `run_id` and physical/provider identities remain distinct;
- `requestId` is treated as a tested alias, not promoted as semantic truth;
- protocol stdout shape and parity remain unchanged;
- physical evidence is bounded, typed, copied, frozen, and non-durable;
- no raw message/delta, auth material, provider payload, URL, or exception
  body is retained;
- canonical history, assistant commit rules, and SQLite persistence are
  untouched;
- no Discord/M4C-3 overlap or telemetry/event-bus overreach was introduced.

## Limitations and unverified claims

- Live provider execution and supported-auth behavior were not run; live model
  causality, entitlement, quota, and provider timing remain UNVERIFIED.
- The sidecar `requestId` alias is verified for the current Core-launched
  protocol path. Direct sidecar callers that omit `GenerationIdentity` may
  receive a sidecar-generated request ID; that path is not semantic Core
  correlation.
- No durable runtime trace, restart reconstruction, replay runner, Discord
  presentation correlation, or cross-process exported evidence artifact was
  added. Those remain later-slice work.
- Deterministic Windows fixture tests do not establish live provider or full
  external end-to-end behavior.

## Handoff

- Isolation: canonical `C:\Lilavel` remains at clean base
  `6bcbc74f7e41f8cda870d54a37677442ca548909` on `feat/conversation-core`;
  implementation exists only in `C:\Lilavel-m4c-2` on
  `work/m4c-2-physical-sidecar-evidence`.
- Git state: no commit, nothing staged, eight task-owned files modified, and
  this completed record untracked; no unrelated changes are present.
- Recommendation: ready for human checkpoint review and later integration with
  the separate M4C-3 Discord correlation work, preserving disjoint ownership.
