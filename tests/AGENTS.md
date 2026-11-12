# Verification

Use `python -m unittest discover -s tests -v`. Keep persistent tests focused on
critical invariants with real temporary SQLite files. Explicitly close SQLite
connections: their context manager commits/rolls back but does not close them.
Use CLI/process smoke checks for milestone acceptance and record actual outcomes
in the corresponding milestone report; distinguish fakes from live provider
evidence. Context tests pin whole-epoch fit/overflow, source-backed transitions,
required content and stable role/prefix boundaries. Journal tests pin additive v2
migration, atomic epoch/audit rollback, replay and terminal-turn cutoffs. Transport
checks cover split control tokens, incomplete SSE and cancellation/closure;
they do not replace real Nemotron conversations and fault checks.
