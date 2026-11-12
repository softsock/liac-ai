# M0 implementation decisions

The task and `PROJECT_BLUEPRINT.md` §§3–7, 9, 13–14, 18, 20–21 define this slice.

## Plan and boundaries

1. Add frozen event/state/proposal contracts and asynchronous Fast/Deep ports.
2. Implement a SQLite WAL journal, per-character sequence, revision reducer and
   durable Deep cursor. Prove duplicate detection, revision rejection and rollback
   with a few real-database tests.
3. Wire one cancelable Fast task and one bounded-batch Deep worker. New direct
   input supersedes Fast. Deep reads the journal, never gates Fast, and commits
   proposal audit, state and cursor together.
4. Add deterministic streaming fakes and an interactive CLI; exercise scenarios
   A–E against the same runtime and document the observed results.

## Decisions [DECIDED for M0]

- Python 3.12+, standard-library runtime; setuptools only for packaging.
- One runtime owns a database at a time. SQLite transactions serialize writers;
  asynchronous tasks share its connection on the event-loop thread. Short local
  SQLite operations are synchronous; inference never holds a transaction.
- State contains only character ID, revision and one context note. Deep cursor
  is storage bookkeeping, separate from the revisioned snapshot.
- Event payloads are canonical JSON strings inside frozen envelopes; reading
  `payload` returns an independent object. Token deltas remain ephemeral.
- Deep consumes at most 100 journal events per batch. No in-memory input backlog:
  a wake flag signals durable work. A state proposal includes its base revision,
  source event IDs and observed watermark. Stale proposals are audited/rejected
  and their processed batch acknowledged, rather than silently rebased.
- A proposal ID identifies its durable audit event. Repeating identical content
  returns the original decision; conflicting reuse fails. State, audit and cursor
  commit in one transaction. Unacknowledged work replays on startup.
- An interrupted visible stream receives a durable cancellation; abrupt-process
  leftovers are cancelled on next startup. Partial text is never completed text.
- Ports must cooperate with asyncio cancellation. Deep has a time limit; a
  failure leaves its cursor untouched and retries on a pending/new input/output
  notification or `/retry`.
  Output callbacks are synchronous, short and observational.
- Schema v1 is tracked by SQLite `user_version`; unknown database versions fail
  before use. Two tables suffice: `events` and `character_state` (including the
  Deep cursor). `turn_id` is the M0 envelope's turn correlation identifier.
- The note persists until another validated proposal replaces it. The current
  input and up to 20 recent exact dialogue events are available in FastSnapshot;
  provider-specific prompt compilation and note expiry belong to later slices.
- Accepted inputs are retained after a crash; speech is not automatically
  regenerated. Started-but-unfinished streams are cancelled during recovery.

## Verification — 2026-11-12

All checks used the actual runtime, real SQLite files and fake minds. No live
provider behavior is inferred from these results.

| Scenario | Observed result |
|---|---|
| A — independence | CLI processes streamed the first text in 55–75 ms locally; two replies completed before the first 1.2-second Deep batch. New input was accepted while Deep was busy. These are smoke observations, not an inference latency SLO. |
| B — propagation | Deep committed revision 2 with the note from `beta`; the next Fast turn used revision 2 and that exact note. A separate runtime check committed Deep mid-stream: all current deltas remained revision 0, while the next turn used revision 1. |
| C — persistence | A new CLI process restored the exact state, revision and three committed replies from the same database. Unacknowledged Deep input replayed on restart. |
| D — IDs/revisions | Real-database tests proved event deduplication, conflicting-ID failure, per-character sequences, stale-update rejection, proposal deduplication and acknowledgement of an already-recorded decision. A SQLite trigger forced audit insertion to fail: state, audit and cursor all rolled back. |
| E — shutdown | `/quit` during Deep work returned in 24–29 ms locally. Mid-stream shutdown recorded cancellation without completing partial text. Forced process termination left a started stream; the next process recorded `process_restarted` cancellation. |

Additional checks:

- Eight focused `unittest` checks pass on Windows with Python **3.12.14** and
  **3.14.7**, including immediate supersession, provider failure after a partial
  chunk and an adapter returning normally after cancellation.
- Deep timeout left cursor 0 while Fast completed; restarting with a responsive
  fake consumed the pending range and applied its note. An injected cursor-only
  write failure was visible and retried successfully after removing the fault.
- Actual Windows console input preserved Ukrainian text. Ctrl+C during a visible
  stream printed cancellation and resource closure; no second Enter was needed.
- CLI subprocess checks ran with `-X dev` and asyncio debug enabled: no resource
  or pending-task warnings; SQLite `integrity_check` returned `ok`.
- Editable installation, both entry points, `pip check`, frozen snapshot/event
  payload checks and an AST inspection of module dependency directions passed.

Repeat the persistent checks after installation:

```powershell
.\.venv\Scripts\python -X dev -m unittest discover -s tests -v
```

To repeat CLI acceptance, start with `--deep-delay 5`, complete two turns before
Deep finishes, inspect `/state`, then send another turn. Quit during background
work and restart with the same `--db`; inspect `/events 100` and `/state`.
Temporary process drivers and their databases were used only for verification.

## M1 handoff and limits

The foundation is ready for an LM Studio Fast adapter: `FastMind.stream` receives
the frozen state, journal watermark, recent exact dialogue and current input,
and yields closeable asynchronous text chunks. Runtime already handles lifecycle,
supersession, completion, cancellation and durable output independently of Deep.
M1 still needs the real adapter, deterministic budgeted ContextCompiler, persona,
no-reasoning capability probe and real latency/character-quality measurements.

Only one process/runtime may own a database. SQLite calls and observer callbacks
run on the event-loop thread and should remain short; multi-process coordination,
large-history performance, hard cancellation of noncooperative providers and
production backup/retention are not established by M0. The CLI uses a bounded
stdin bridge with a daemon raw reader so an idle console read cannot delay exit;
all domain asyncio tasks are cancelled and awaited before storage is closed.
LM Studio/OMP, POSIX execution and physical power-loss durability were not tested.
