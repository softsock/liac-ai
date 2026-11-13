# Runtime

Own event ordering, revision validation, durable Deep acknowledgement and task
lifecycle. Import contracts and sibling runtime modules, never concrete minds or
CLI. `journal.py` commits state + proposal audit + cursor in one transaction;
`state.py` is the pure reducer. No transaction spans an inference await.
One Runtime owns one database; new input supersedes its previous visible stream.
Deep failures preserve the cursor. Do not turn audit events into new Deep work.
Fast diagnostics are observational and bounded to the latest turn; never persist
token chunks or provider configuration in domain events.
An optional TraceSink captures immutable request/decision boundaries separately;
failed capture cannot alter domain state. `cancel_fast()` serializes explicit user
cancellation with submit/close. Keep before/after snapshots outside inference awaits.
Schema v2 adds immutable context epochs; additive migration preserves all events,
notes and cursors. Compaction CASes epoch + note revision and commits decision +
epoch atomically, without acknowledging Deep. Validate source/range/turn boundaries;
no cutoff may split an exchange or cover an unfinished turn. Reject stale proposals
without rebasing. Read state/epoch/watermark/exact history in one short transaction.

M2 `deep.py` owns one serialized observer, complete-turn batches and bounded retry. `apply_deep` commits all operation decisions plus cursor together; stale dependencies retain input for reconsideration. Audit-only tails never become model work. No-op compaction is coalesced by epoch/revision/cutoff.

Notes and compaction both depend on the captured epoch. Startup cancels every accepted input without a terminal, including inputs persisted before reply.started. Worker stop prevents post-close application even when an adapter swallows cancellation.

M4.2 validates the document token budget before the atomic Deep batch commit.
Ordinary newer dialogue is not a conflict; revision/epoch CAS still applies.
The serialized Deep worker writes context.md off-loop after changed commits and
at startup; SQLite is authoritative. File failure preserves DB/cursor, exposes
only the error class, and retries on the next change or restart. Close joins writes.
