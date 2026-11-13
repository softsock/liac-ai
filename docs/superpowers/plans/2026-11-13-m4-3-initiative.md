# M4.3 Initiative & Character Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (recommended Native execution), or superpowers:subagent-driven-development if explicitly selected. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Liac can occasionally initiate one relevant Nemotron utterance from an evidence-backed Luna proposal, while remaining silent by default and giving user input priority.

**Architecture:** Extend the existing Deep result, Journal and owned Runtime tasks. Markdown remains the only working perspective; one typed proposal authorizes a possible turn, and the same compiler/stream/terminal pipeline produces its actual speech. No new agent, behavior service, memory store or scheduler.

**Tech Stack:** Python 3.12+, stdlib asyncio/SQLite/unittest, existing HTTPX/Nemotron renderer and tokenizer, pinned OMP SDK and Luna.

**Spec:** [Original M4.3 request](../specs/2026-11-13-m4-3-initiative-requirements.md). This plan proposes implementation choices; live behavior is not yet verified.

**User revisions (2026-11-13):** No new idea must not implicitly cancel a pending intent. Delay, TTL and cooldown are configurable experimental starting values. Keep new automated checks focused on races, duplicate execution, restart and cancellation; real conversations are the primary acceptance evidence.

## Global Constraints

- Base execution on M4.2 `bea6abc7bba274dd83b30546fe62d7828d88b971`. User override at execution: implement in the current `codex/m4-2-markdown-context` branch.
- One final meaningful commit, author `softsock <109231668+softsock@users.noreply.github.com>`, with `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`. No push or PR. Per-task commits are intentionally omitted.
- Never use GPT-6 Astra for subagents. Recommend inline implementation with one final independent reviewer, rather than per-task implementers.
- English application text and code comments. Existing dependencies only; no large services, model downloads, vendor modifications or Loonyball changes.
- Preserve one Runtime owner per DB, short transactions, explicit cancellation, immutable snapshots and exact-token validation.
- Preserve configurable Markdown budget (default 2048), 32768 UTF-8 byte document ceiling, current user precedence and atomic `context.md` projection.
- No numerical psychology, Attention Engine, Performance Beats, long-term memory, voice, sensors or application control.

## Review Focus

1. Crash between accepting an initiative and starting its task must cancel it on restart, never replay speech (Task 2).
2. User input queued at readiness or received during autonomous streaming must win without interleaved output (Task 4).
3. Late Luna may still update Markdown under M4.2 rules, but may not launch speech based on superseded user input (Tasks 2/4).
4. An autonomous-only journal tail must neither loop into more inference nor be silently acknowledged away before Luna can observe its result (Task 2).
5. Compaction must not split an autonomous turn, retain a cancelled partial reply or change the cached early prefix just to label initiative (Task 3).

## Current implementation and smallest scope

Read: root/scoped `AGENTS.md`, blueprint context/concurrency/initiative/persistence sections, `M2_IMPLEMENTATION.md`, `M4_2_IMPLEMENTATION.md`, contracts, compiler, Journal, DeepWorker, Runtime, CLI, composition and desktop consumers.

- `DeepWorker` already serializes Luna, validates document budgets, commits batches and exports Markdown. It can notify Runtime synchronously after a committed decision, before awaiting projection I/O.
- `Runtime.submit` currently accepts only `UserMessage`; its preparation/start block must become shared with character turns. Reuse `_run_fast`, `_finish`, cancellation and output kinds.
- `Journal.deep_request` opens exchanges only for user events and treats non-user tails as audit-only. This must distinguish autonomous turns from audits.
- `ContextCompiler` already puts changing Markdown after exact history. Keep ordinary user wire prompts byte-compatible and place the autonomous instruction at the final input position.
- Journal events support new kinds without a table migration. Use existing events for proposal/closure/turn lineage, not a second mutable intentions store.

**Approaches considered:** Parsing execution commands from Markdown conflicts with the request. A queue/scheduler and separate behavior store duplicate existing task/Journal ownership. Choose one pending typed opportunity, an owned readiness task and event-backed one-shot status.

### Proposed defaults and boundaries

These are implementation proposals, not prior user decisions:

- `Config.initiative_enabled=False`, CLI `--enable-initiative`; desktop stays disabled by default and needs no new controls.
- Configurable initial cooldown **60 seconds** from the last autonomous attempt, including failed/cancelled attempts. At most **one autonomous attempt per latest real user event**. No autonomous-to-autonomous conversation loop.
- Configurable defaults: **5-second** minimum delay and **120-second** validity from captured request time. Require finite nonnegative delay/cooldown, positive TTL and `delay < TTL`; reject booleans. These are starting values for real-dialogue experiments, not optimal settings or fixed scheduling limits. Timer expiry is permission to check an existing proposal, never a reason or a Luna trigger.
- One pending opportunity. `none`/null means no new idea: preserve the existing opportunity, its identity and original deadlines without rearming it. Only a fresh explicit `cancel` withdraws it; a fresh `speak` replacement closes the old one. New user input, shutdown, expiry, changed execution dependencies or restart still closes it permanently. A no-idea result alone is never a cancellation reason.
- Restart cancels pending opportunities rather than resuming deadlines. A new real user event can earn a new proposal. Persist wall timestamps for audits/cooldown; use monotonic deadlines within a process and patch clocks/waits in tests.
- Exact duplicate intent plus evidence is durably suppressed. One attempt per user anchor also blocks reworded proposals against that anchor. Across later user events, semantic repetition is Luna's judgment, informed by actual history; do not claim a semantic deduplication algorithm.
- Source IDs and reason prove provenance, not appropriateness. Real conversations must assess whether the proposal is earned and whether silence is natural.

## File map

| Files | Change responsibility |
|---|---|
| `src/vtuber/contracts/deep.py` | Frozen initiative proposal and optional Deep fields |
| `src/vtuber/contracts/events.py`, `protocols.py` | Distinct character input; shared Fast input union |
| `src/vtuber/minds/luna.py`, `deep.md` | Strict proposal parsing; continuity and silence guidance |
| `src/vtuber/runtime/journal.py` | Atomic proposal decisions, one-shot claim/close, restart and closed-turn ranges |
| `src/vtuber/runtime/deep.py`, `orchestrator.py` | Post-commit notification, one readiness task, shared Fast start and user priority |
| `src/vtuber/context.py`, `minds/lmstudio.py`, `minds/fake.py` | Shared typed input, explicit autonomous final instruction, compatible user prompts |
| `src/vtuber/app.py`, `cli.py` | Opt-in configuration and wiring |
| Existing `tests/test_deep.py`, `test_runtime_lifecycle.py` and existing parser/context checks only where contracts change | A few combined critical regression checks; reuse the current suite |
| Existing `scripts/verify_m2_luna.py`, `verify_m1_5_context.py` | Opt-in initiative acceptance/cache phases |
| `README.md`, `docs/PROJECT_BLUEPRINT.md`, new `docs/M4_3_IMPLEMENTATION.md`, relevant root/scoped `AGENTS.md` | Usage, actual evidence, milestone boundaries |

## Task 1: Bounded proposal and distinct Fast input

**Files:** contracts, Luna parser/role, FakeFast and LMStudioFast annotations listed above; `tests/test_luna.py`.

**Interfaces:**
- Add frozen `InitiativeProposal(intent: str, reason: str, source_event_ids: tuple[str, ...], delay_seconds: float | None = None, ttl_seconds: float | None = None)` and `InitiativeCancel(reason: str)` in `contracts/deep.py`. Omitted timings use captured configuration; Runtime assigns identity/dependency/timing metadata.
- Append `DeepResult.initiative: InitiativeProposal | InitiativeCancel | None = None`; retain old positional arguments. Append `DeepRequest.initiative_allowed: bool = False` and `captured_at: str = ''` (runtime UTC time, never model supplied). False prohibits a new speak proposal, not an explicit cancellation of a pending opportunity.
- Add frozen `CharacterInitiative` in `contracts/events.py`, carrying `intent`, `reason`, `character_id`, `event_id`, `turn_id`, `occurred_at` and `proposal_id`; `as_event()` creates `character.initiative.started`, never `user.message.completed`. `FastInput = UserMessage | CharacterInitiative` is the shared port type.
- Existing schema-v1 JSON remains valid with no new initiative and preserves pending state. Schema-v2 JSON has exactly `schema_version`, `note`, `compaction`, `initiative`: null or `{action:"none"}` preserves pending state; `{action:"cancel", reason}` explicitly withdraws it; `{action:"speak", intent, reason, source_event_ids, delay_seconds, ttl_seconds}` proposes a new opportunity. Delay/TTL may be omitted to use configuration; unknown fields reject. Both versions preserve existing note/compaction bounds. The cancellation targets the single pending opportunity, not an already running Fast stream.

- [ ] Extend the existing parser check with speak/none/cancel/legacy samples and one compact invalid-input table (invalid sources, empty/oversized text, unknown authority fields, boolean/nonfinite/invalid timings). Confirm failure before implementation; do not create a separate test per field.
- [ ] Implement the contracts and strict parsing. Reuse `_text`/`_sources`; validate frozen proposal construction too, so fake/custom minds cannot bypass structural checks.
- [ ] Extend `deep.md`: free Markdown interests/open threads/optional almost-ready lines; speak only when earned, none is normal, no reflexive questions, no repeated jokes, user corrections override. Explain that none preserves and cancel explicitly withdraws an existing intent. Always return v2 from the current role; legacy v1 remains accepted. When `initiative_allowed` is false, do not propose speak; none/cancel remain valid.
- [ ] Run parser tests and `test_lmstudio.py`; legacy Fast construction and transport checks remain green. No renderer or SDK changes.

## Task 2: Durable opportunity and closed autonomous turns

**Files:** `runtime/journal.py`; `tests/test_deep.py`, `test_journal.py`.

**Interfaces:**
- Keep `Journal.apply_deep(request, result, *, compaction_error=None, context_error=None) -> DeepDecision`. Append optional `DeepDecision.initiative_reason: str | None = None` for accepted/unchanged/cancelled/disabled/stale/duplicate opportunity decisions.
- `Journal.pending_initiative(character_id: str) -> Event | None` reads the single unresolved proposal from event records.
- `Journal.close_initiative(proposal_id: str, reason: str) -> None` appends an idempotent `initiative.closed` event.
- `Journal.claim_initiative(proposal_id: str, snapshot: FastSnapshot) -> CharacterInitiative | None` atomically consumes the opportunity and appends its character input plus `character.reply.started` with the prepared snapshot metadata; use deterministic IDs derived from the proposal ID and existing reply-terminal convention. Recheck expiry, anchor, revision/epoch, snapshot consistency and deduplication in this transaction.
- `Journal.latest_user_sequence(character_id: str) -> int` provides the persisted anchor. Add the most recent autonomous attempt timestamp query for cooldown; use event timestamps, no new table.

- [ ] Add `test_initiative_atomic_replay_and_restart`: proposal/audit/cursor rollback together on injected batch-audit failure; identical replay adds nothing; conflicting reuse raises `EventConflict`; reopen preserves history/document and cannot claim a consumed or closed proposal.
- [ ] Fold into that combined lifecycle regression: none/legacy preserve a pending ID and deadlines, explicit cancel closes it, stale cancellation cannot close a newer proposal, and a late speak is suppressed while a valid Markdown update commits. Reuse existing batch-boundary assertions for character input and confirm its completed output reaches the next ordinary Deep batch without self-triggered inference.
- [ ] Run the owning test modules and confirm RED for new behavior.
- [ ] Implement proposal events inside the existing successful Deep transaction. Record captured latest-user anchor, effective **post-batch** revision/epoch (including its own note/compaction), request capture time/deadlines, intent, reason, evidence and duplicate key. A result whose request anchor is behind the current latest user cannot replace/cancel a newer opportunity.
- [ ] Preserve historical replay fingerprints: omit new request/result/decision fields when at legacy defaults; decode old decisions with missing optional fields. Include new nondefault fields in new fingerprints. Extend the existing legacy replay fixture rather than building another compatibility test group.
- [ ] Implement claim/close and startup recovery inputs using existing event storage. Independently validate sources against actual same-character canonical events and captured evidence. No transaction spans an await.
- [ ] Include `character.initiative.started` in opened-turn tracking, unfinished-input recovery and compaction boundary validation. Keep it out of dialogue text; only completed speech becomes assistant history. Preserve autonomous-only pending observations until a real-user batch or genuine compaction request can consume them.
- [ ] Run `test_deep.py` and `test_journal.py`; old v1/v2 DB migration, note CAS, whole-batch budget rollback and cursor tests remain green.

## Task 3: One compiler and Fast stream for both origins

**Files:** `context.py`, `contracts/protocols.py`, `minds/lmstudio.py`, `minds/fake.py`, `runtime/orchestrator.py`; `tests/test_context.py`, `test_lmstudio.py`, `test_runtime_lifecycle.py`.

**Interfaces:**
- Widen compiler/policy/Fast adapter message parameters from `UserMessage` to `FastInput`.
- Extract `Runtime._start_fast(message: FastInput) -> asyncio.Task[None] | None` from submit's preparation/start logic; `_run_fast`/`_finish` retain one shared implementation. Character start consumes the atomic claim's prewritten reply-start record rather than appending a second one.
- Character final input explicitly labels its contents as a character-origin opportunity, with quoted intent/reason and the instruction to produce only the character's utterance. Using a renderer user role for the control input does not create a Journal user event or represent actual user speech.

- [ ] Extend the existing prefix/boundary checks with a character-input sample: preserve identity/epoch/history and raw Markdown, change only the tail control text; retain safe compaction boundaries and exclude cancelled partial speech. Reuse the current overflow, tokenizer and stream tests; no separate transport test matrix.
- [ ] Run the existing focused checks to establish the contract change before implementation.
- [ ] Implement input branching only at the final compiler control text and the state wrapper's final-target wording. Keep current user wrapper unchanged; character wrapper must not falsely ask to respond to a nonexistent user message. Retain the same Markdown location/counts, tokenizer, BOS, streaming and escaped control-token rules.
- [ ] Extract the shared start path; prepare the context before claiming the initiative, then atomically claim using the actual prepared snapshot before creating the Fast task. If preparation changes the epoch, invalidate the old opportunity rather than rebasing it. Never persist reply-start metadata from an earlier snapshot. Use the existing terminal IDs, output kinds and snapshot/cancellation guards for both origins. Adapt FakeFast so it labels character input without saying the user said it.
- [ ] Run focused tests; normal user supersession, frozen snapshots, stream closure and tokenizer parity remain green.

## Task 4: Opt-in readiness and user priority

**Files:** `runtime/deep.py`, `runtime/orchestrator.py`, `app.py`, `cli.py`; `tests/test_runtime_lifecycle.py`, `test_cli.py`.

**Interfaces:**
- Append `Config.initiative_enabled: bool = False`, `initiative_delay_seconds: float = 5.0`, `initiative_ttl_seconds: float = 120.0`, and `initiative_cooldown_seconds: float = 60.0`, with matching Runtime keywords. Expose CLI `--enable-initiative`, `--initiative-delay-seconds`, `--initiative-ttl-seconds`, `--initiative-cooldown-seconds`. Validate finite values and timing relationships. Resolve omitted proposal timings from configuration; freeze effective values/deadlines in the accepted event so later configuration changes do not silently renew an intent.
- Add optional synchronous DeepWorker callback `on_decision(request: DeepRequest, result: DeepResult, decision: DeepDecision) -> None`, invoked after successful commit and before awaited file refresh. Runtime owns the readiness task; the worker never generates Fast speech.
- Runtime owns at most one `_initiative_task`, with private `_wait_initiative(proposal_id: str) -> None`. Use existing `_input_lock` for the final no-await eligibility/claim/start section; never await that task's lock-dependent cleanup while holding the lock.

- [ ] Add deterministic `test_user_wins_initiative_race`: schedule input immediately before readiness and during autonomous streaming; pending opportunity closes, or active autonomous stream cancels before the user stream starts; no stale deltas escape and each started turn has exactly one terminal.
- [ ] Fold essential readiness assertions into the race/cancellation check: disabled/expired/cooldown-blocked opportunities cannot execute, none preserves the pending task/deadline, explicit cancel/replacement closes the appropriate task, and a duplicate claim never starts a second stream. Patch clocks/waits and use a nondefault configuration; no sleeps for correctness or separate test for every guard.
- [ ] Add `test_initiative_close_and_recovery`: shutdown joins the owned task and cancels pending/active initiative; crash fixtures cover before task start and after start; reopening emits durable cancellation and never resumes speech. Slow Deep and slow projection writes do not gate ordinary Fast.
- [ ] Run focused lifecycle/CLI tests and confirm RED.
- [ ] Implement configuration, callback and readiness task. Set request `initiative_allowed` only when opted in and no attempt has consumed the current latest-user anchor. Use a scheduling yield before the final lock check so already queued user submit tasks get priority. A later-arriving user still cancels an already-started autonomous turn through the normal pipeline.
- [ ] `submit` persists new input and closes pending initiative before starting its user reply. Duplicate delivery does not cancel unrelated work. `cancel_fast()` also withdraws a waiting initiative. Close/start recovery covers both origins. Enforce the one-attempt anchor and durable exact duplicate guard at claim time.
- [ ] Timer/readiness wakeups never notify or retry Deep. Completed autonomous speech waits for ordinary observation as specified in Task 2; no self-generated request chain. Permit semantic compaction only through existing pressure policy.
- [ ] Run lifecycle/CLI tests, then the full suite. Desktop stays disabled but its existing output/history reader must display a completed autonomous reply from a previously enabled CLI session as Fast, never as You; verify the existing offscreen checks without adding controls.

## Task 5: Real acceptance, cache evidence, docs and final commit

**Files:** existing `scripts/verify_m2_luna.py`, `scripts/verify_m1_5_context.py`, README, blueprint, owning `AGENTS.md`, new `docs/M4_3_IMPLEMENTATION.md`.

**Interfaces:** Add opt-in `--phase initiative` / `initiative(evidence)` to the M2 verifier and `--phase initiative-cache` to the M1.5 verifier; preserve existing defaults. Extend existing self-check/counter assertions for the new phases; no new eval framework.

- [ ] Add the smallest verifier assertions before production calls: both origins use the production Runtime, terminal lineage is checked by event ID, zero new user events accompany autonomous output, and absent/ambiguous cache counters are reported as unavailable rather than inferred from TTFT.
- [ ] Extend the existing evidence collector to record autonomous start/first-delta/completion timing, proposal/eligibility reasons, actual Markdown/utterances, real Deep invocation count and available OMP usage. Keep raw payloads/DBs under ignored `.data/`; do not print credentials or private conversations.
- [ ] Verify existing endpoint/model/OMP availability read-only first. Reuse the local Nemotron/tokenizer and existing OMP installation/auth; starting the existing local model/API is already authorized. Do not change shared model settings, download assets or claim old evidence as new.
- [ ] Run natural Skin Creator dialogue (A): earn an unfinished topic through actual conversation, stop user input, observe an unforced real Luna speak proposal and Nemotron reply. Retain silence/awkward failures too; do not inject a speak result or repeatedly order Luna to initiate and call that natural behavior.
- [ ] Make real dialogue the primary acceptance work: does Luna spontaneously form a specific interest, choose speak versus silence appropriately, and does Nemotron turn the idea into a natural line rather than a generic follow-up question? Save the conversation sequence and actual proposal as well as the final utterance. Check a no-new-idea Deep result while an existing intent remains pending, and a separate explicit withdrawal; neither requires a new framework.
- [ ] Start with configured 5/120/60-second delay/TTL/cooldown. If an earned line arrives awkwardly, expires before delivery or interrupts the rhythm, try a deliberately different configuration and record why it was better or worse. Tune for conversational naturalness, not maximum initiative count; do not call the initial values optimal or require a parameter sweep.
- [ ] Run ordinary finished-topic dialogue (B) and wait past the candidate window: no invented initiative and no timer-only Deep calls. Report actual calls/usage, including retries; claim zero **timer-triggered** calls only when counted, not zero additional tokens overall.
- [ ] Run C/E with a held **real** Luna proposal: new topic/stop-jokes before delivery and input at readiness/during output. Mark injected delivery holds as such. Verify actual Markdown may commit while stale speech is cancelled; no mixed streams. Run G by completing a new Fast response while real Deep remains busy, without waiting for Deep.
- [ ] Run D/F using the same temporary DB through reopen: executed/cancelled proposals do not repeat; history and Markdown projection recover; interrupted turn gains one cancelled terminal; `PRAGMA integrity_check` returns `ok`.
- [ ] Run three serial cache trials using the existing counter-attribution helpers: separately prime an identical compiled baseline, then vary only the final user/initiative control input with fixed identity/epoch/history/Markdown. Record full tokens, evaluated tokens, TTFT and missing counters. Also capture an actual autonomous production turn; do not equate a controlled prompt probe with a complete behavioral trial or promise zero cache cost as history grows.
- [ ] Record A–G results, real utterances/silence, costs, TTFT and cache measurements in `M4_3_IMPLEMENTATION.md`; identify model-quality failures separately from deterministic contract failures. If live providers block acceptance, preserve partial evidence and report incomplete acceptance, never mark Definition of Done achieved from fakes.
- [ ] Update README opt-in usage; relevant root/contracts/runtime/minds/tests instructions; blueprint current M4.3 decision and explicit FUTURE items. Preserve historical milestone reports.
- [ ] Run final verification:

  ```powershell
  python -m unittest discover -s tests -v
  python scripts/verify_m2_luna.py --self-check
  python scripts/verify_m2_luna.py --phase initiative --omp-executable C:/Users/shtvl/AppData/Local/omp/omp.exe --output .data/m4-3-initiative.jsonl
  python scripts/verify_m1_5_context.py --phase initiative-cache --output .data/m4-3-cache.jsonl
  git diff --check
  git status --short
  ```

  Use an existing environment with HTTPX, tokenizers and OMP SDK; set `PYTHONPATH=src` when reusing another checkout's environment. Do not install dependencies merely to plan this milestone.

- [ ] Obtain one independent whole-diff review if Native execution is chosen. Fix actionable issues and rerun affected checks; do not dispatch per-task agents or use Astra.
- [ ] Stage only milestone source/tests/docs and the plan/spec; inspect staged changes for private data. Make the one requested commit with explicit author and coauthor trailer, verify its parent/branch and clean tree. Leave local evidence ignored; no push/PR.

## Self-review and handoff

Coverage: request sections 1–3 → current-state map and Task 1; 4–6 → Tasks 1–4; naturalness/silence → Tasks 1/5; A–G and metrics → Task 5; milestone bounds/documentation/commit → global constraints and Task 5. Review Focus conditions are covered by a few combined lifecycle regressions and extensions of existing checks. Shared input/proposal names and callback signatures are consistent across tasks. New automated work concentrates on race conditions, duplicate execution, restart and cancellation; existing parser/budget/cache validations remain in place. Live conversation is the main acceptance evidence, not test count.

Consciously omitted: scheduler framework, second memory/projection, psychological scores, Markdown intent parser, semantic repetition classifier, new UI controls and generic recovery/evaluation infrastructure. Exact one-shot/cancellation is deterministic; the relevance of Luna's suggestions and naturalness of Nemotron's delivery remain live model behavior.

Execution authorized by the user in the current branch. Native inline implementation selected; actual results and deviations belong in `docs/M4_3_IMPLEMENTATION.md`.
