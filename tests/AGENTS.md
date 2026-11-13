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

M2 checks closed/interleaved turn boundaries, batch rollback/replay, stale retry, off-loop SDK waits and confirmed cancellation. Separate actual Luna/Nemotron acceptance from injected delay/transport checks.

M4.2 checks whole Markdown/clear/no-op, configured token rejection, stable tails,
legacy replay, late ordinary inputs, atomic file failure and startup repair.
Use existing verifier Markdown phases for live behavior and backend cache counters;
model no-op choice and suggestion adoption remain variable.

M4.3 new regression work concentrates on atomic claim/replay, duplicate execution,
expiry, race/user priority, cancellation and restart. Reuse parser/context/transport
checks; live initiative/silence and Nemotron delivery are primary acceptance.
Use existing verifier initiative phases; keep injected holds distinct from natural trials.
