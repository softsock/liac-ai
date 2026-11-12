# Verification

Use `python -m unittest discover -s tests -v`. Keep persistent tests focused on
critical invariants with real temporary SQLite files. Explicitly close SQLite
connections: their context manager commits/rolls back but does not close them.
Use CLI/process smoke checks for milestone acceptance and record actual outcomes
in `docs/M0_IMPLEMENTATION.md`; distinguish fakes from live provider evidence.
