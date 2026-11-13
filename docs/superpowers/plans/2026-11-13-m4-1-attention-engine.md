# M4.1 Attention Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the approved Native execution. Track steps below.

**Goal:** Persistent, source-backed semantic attention without blocking Fast.
**Architecture:** Extend the existing serialized Deep batch, typed proposals and
atomic Journal acknowledgement. Runtime owns validation/lifecycle; Luna owns semantics.
**Tech Stack:** Python 3.12+, SQLite, asyncio, unittest, existing OMP SDK; no new dependencies.
**Spec:** User's M4.1 request and approved design from the preceding chat turn.

## Global Constraints

- User override: branch `codex/m4-1-attention` from `codex/desktop-inspector` at `c6c8b24`.
- One Runtime/Luna, independent Fast; no beats, autonomous speech or memory store.
- English UI/comments, no Astra; softsock author and required coauthor trailer.
- Commit after verification; no push/PR requested. Preserve desktop and traces.

## Review Focus

Late corrections; duplicate/paraphrased proposals; rollback before acknowledgement;
untrusted IDs/foreign sources; deferred/expired signals across restart.

## Tasks and Interfaces

- [x] Task 1: Frozen `AttentionProposal`, `AttentionSignal`, `AttentionView` in
  `contracts/attention.py`; extend Deep envelopes with defaulted attention fields.
  Schema-v2 Luna parser, prompt and fakes; source/enum/bounds validation. RED→GREEN
  in `tests/test_attention.py` and existing Luna tests. Empty attention is normal.
- [x] Task 2: Schema-v3 additive signal table, pure ranking/provenance helpers in
  `runtime/attention.py`, Journal-owned atomic lifecycle/acknowledgement. Test
  migration/replay/rollback/foreign sources/expiry/target CAS. Creation identity is
  character + kind + sorted source IDs, independent of wording. Updates preserve
  provenance. Runtime assigns IDs/time/status, Luna may target/version/supersede
  supplied nonterminal signals. TTL 1..86400 seconds from newest source timestamp;
  no TTL for persistent observations. Outcomes notice/defer/ignore map to
  noticed/deferred/ignored; terminal superseded/expired do not revive.
- [x] Task 3: Normal Deep batches carry active attention and original source events;
  deferred signals await next completed-turn batch. No timer-only inference or
  second session. Boundary/correction before opportunities, then significance and
  recency. FIFO source batches remain; semantic priority is unknown before Luna.
  Test held-call backlog, correction, restart, failure and Fast independence.
- [x] Task 4: CLI `/attention [status] [count]`, `/attention-source EVENT_ID`; bounded
  same-character inspection and read-only M4.2 candidate view with cursor watermark.
  Verifier `scripts/verify_m4_1_attention.py` with self-check and real-provider runs.
  Prelabel topic/callback/open-loop/correction/boundary/mundane scenarios. Record
  false positives, misses, duplicates, TTFT, Deep latency and OMP usage; distinguish
  live provider behavior from injected delay/failure. Preserve ignored evidence.
- [x] Task 5: README/AGENTS/blueprint/report, full tests on available 3.12/3.14,
  one fresh branch review, important fixes RED→GREEN, final softsock commit.

## File Map

New: `contracts/attention.py`, `runtime/attention.py`, `tests/test_attention.py`,
`scripts/verify_m4_1_attention.py`, `docs/M4_1_IMPLEMENTATION.md`.
Modify: Deep contracts/worker/Journal, Luna parser/prompt/fake, CLI, existing tests,
relevant AGENTS/README/blueprint. Desktop consumes additive traced fields; its
existing executable is not rebuilt in this milestone.

## Acceptance

All six requested live scenarios, source correctness and no Fast blocking.
Atomic signal/note/epoch/audit/cursor; no inference from audit tails. Revisit
deferred with new evidence, recover unacknowledged input after restart. Existing
64 KiB response/512 KiB prompt limits remain explicit without silent truncation.
Open-signal growth and semantic deduplication remain measured limitations.

## Execution Notes

The approved planning files were absent when execution began on `main`; this
document reconstructs their decisions and records the user's base override.
Untracked local EXE was preserved under ignored `.data/pre-m4-1-LIAC-Inspector.exe`
before switching, since Git refused to overwrite it. Desktop baseline: 83 tests
pass on Python 3.14.7. No private artifacts were removed.
