# Production cognition wiring

Status: COMPLETED
Updated: 2026-09-07
Repository / checkout: C:\Lilavel-m4c-integration
Branch / worktree: feat/conversation-core
Base commit: 46c105a7f77ae1b835cb1a26b16662069538898e
Last checkpoint commit: none

## Goal and scope
Wire experimental cognition into normal DM turns. Core composition, callback, shared harness canon, edge default, tests and package docs only.

## Non-goals
Final character, memory, relationships, P2 investigations, ARAS, provider changes.

## Exit criteria
Core and Discord authoritative checks pass, diff reviewed, task-owned commit.

## Current implementation state
Canon preserved verbatim; fresh neutral state/disposition per request. No user text or metadata enters guidance.

## Closure
Implementation and validation complete; included in the task commit. Package docs record the production composition contract.

## Limitations
Live Discord smoke and model-backed A/B/C were not run. Neutral controls do not classify harness scenarios or implement final Character v0. Existing experimental canon is intentionally unchanged.

## Validation
PASS on Windows: Core 161 tests; Discord 79 tests (existing audioop deprecation warning). Both packages: uv sync --locked, uv lock --check, Ruff check, Ruff format --check, Pyright. Cognition harness deterministic regressions pass. Sidecar untouched; its suite not required. Final diff reviewed and git diff --check passes. Live/provider behavior UNVERIFIED.
