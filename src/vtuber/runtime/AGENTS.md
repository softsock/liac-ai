# Runtime

Own event ordering, revision validation, durable Deep acknowledgement and task
lifecycle. Import contracts and sibling runtime modules, never concrete minds or
CLI. `journal.py` commits state + proposal audit + cursor in one transaction;
`state.py` is the pure reducer. No transaction spans an inference await.
One Runtime owns one database; new input supersedes its previous visible stream.
Deep failures preserve the cursor. Do not turn audit events into new Deep work.
Fast diagnostics are observational and bounded to the latest turn; never persist
token chunks or provider configuration in domain events.
