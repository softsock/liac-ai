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

M4.1 SQLite v3 persists attention alongside Deep decisions and cursor atomically.
`attention.py` owns pure provenance/ranking/preparation, Journal owns transactions.
Exclude attention audit from model work. Deferred signals wait for a new complete
turn; expiry never invokes Luna. UTC expiry survives restart; monotonic deadlines
prevent in-process clock rollback from reviving existing opportunities. Attention
candidate views expose the cursor: future consumers must check freshness before use.
