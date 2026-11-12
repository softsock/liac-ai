# M1.5 Context Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Use Nemotron's context efficiently across stateless turns with durable epochs, locally verified token counts and a future Luna compaction boundary.

**Architecture:** Runtime owns atomic epoch transitions; Journal retains original evidence. A pure compiler plans bounded projections through an injected local counter, while one Nemotron renderer feeds both counting and HTTP serialization. Epoch summaries stay frozen and exact history grows until an explicit transition; asynchronous proposals never mutate an active snapshot.

**Tech Stack:** Python 3.12+, asyncio/SQLite/unittest, HTTPX, optional `tokenizers==0.22.2`, pinned NVIDIA tokenizer, existing LM Studio/Nemotron GGUF.

**Spec:** [M1.5 design and research](../specs/2026-11-12-m1-5-context-lifecycle-design.md), implementing the user's M1.5 request; [blueprint](../../PROJECT_BLUEPRINT.md) and [M1 baseline](../../M1_IMPLEMENTATION.md#m1-context-cache-follow-up--2026-11-12).

## Global Constraints

- “Працюй у поточній гілці.” Keep `codex/m1-context-cache` in its existing managed worktree; base `e3bd3ae`.
- “Зроби змістовний коміт після завершення реалізації.” One final implementation commit, after verification; no intermediate commits, push, PR or merge.
- “Збережи stateless-запити через LM Studio.” Keep raw `/v1/completions`, thinking off and conversational mode on.
- “Активна генерація Fast продовжує використовувати свій незмінний snapshot.” No inference await inside transactions; never wait for Luna on Fast's path.
- “Збережи пріоритет Character Identity, активних контекстних нотаток і поточного повідомлення.” Required blocks remain whole; Journal is never replaced by a summary.
- “Реалізуй точний або перевірено близький підрахунок токенів без мережевого запиту перед кожним turn.” Tokenization is local; startup calibration is separate.
- “Дотримуйся наявних модульних меж. Використовуй невеликі цілісні компоненти та мінімум залежностей.” Contracts use stdlib; Runtime sees policy ports, never concrete minds.
- Python 3.12+; HTTPX remains the only core direct dependency. Add one optional real-Fast dependency, `tokenizers==0.22.2` (includes its declared transitive dependencies); no Transformers/Torch or another model server.
- Defaults: context 16384, output 512, margin 32, soft transition 90% of remaining input budget; exact policies and small-window behavior are in the spec.
- “Заборонено використовувати GPT-6 Astra для subagents.” Preserve Native execution, then one fresh non-Astra whole-change reviewer.
- Every commit includes `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`; retain the previously requested softsock author/committer identity for this commit.

## Review Focus

1. A legacy database or a failed epoch-audit insert: migration is additive and rollback leaves the old active epoch, note and cursor intact (Task 2).
2. Late, duplicate, cross-character or unfinished-range compaction: reject stale/invalid evidence, preserve later turns and replay safely (Task 2).
3. A large Unicode input/note or tokenizer mismatch: never truncate required content, send an overflowing prompt or silently use a heuristic for real Fast (Tasks 1, 3, 4).
4. A Deep update or epoch commit while Fast is stalled, followed by immediate cancellation: old snapshot stays frozen and exactly one durable terminal remains (Task 4).
5. More than twenty events, quoted hostile controls, missing cache counters or a warm restart: stable serialization and correct retained facts are distinct from measured cache reuse (Tasks 3, 5).

---

## File structure

| File | Responsibility |
|---|---|
| Create `src/vtuber/contracts/context.py` | Frozen epoch, attributed item, proposal and result envelopes. |
| Modify `contracts/state.py`, `contracts/protocols.py` | Snapshot epoch and pure context-policy port; existing note/Fast/Deep ports remain. |
| Create `src/vtuber/minds/nemotron.py` | Move renderer/constants; load pinned local tokenizer and count exactly the wire prompt plus backend BOS. |
| Modify `src/vtuber/context.py` | Whole-epoch compilation, injected counter, deterministic transition planning and budget diagnostics. |
| Modify `src/vtuber/runtime/journal.py` | Additive v2 migration, immutable epoch records, coherent snapshots, atomic proposal decisions. |
| Modify `src/vtuber/runtime/orchestrator.py` | Local preparation before Fast; validated asynchronous compaction entry point; terminal failure handling. |
| Modify `minds/lmstudio.py`, `app.py`, `cli.py`, `pyproject.toml` | Share renderer/counter, verify startup parity, wire policy and tokenizer path, expose diagnostics/install extra. |
| Modify `tests/test_context.py`, `test_journal.py`, `test_runtime_lifecycle.py`, `test_lmstudio.py`; create `tests/test_nemotron.py` | Only critical persistence, budget, prefix, compatibility and lifecycle checks. |
| Create `scripts/verify_m1_5_context.py` | Reproducible opt-in synthetic/live verifier, using existing HTTPX and CLI; bounded metadata-only evidence output. |
| Update `README.md`, root/scoped `AGENTS.md`, `docs/PROJECT_BLUEPRINT.md`; create `docs/M1_5_IMPLEMENTATION.md` | Setup, changed invariants, historical comparison, actual evidence and M2 boundary. |

All `src/` paths without a leading directory in this table are below `src/vtuber/`.
Tokenizer assets, private DBs and raw engine logs stay ignored under `.data/`.
No large asset or generated evidence dump enters Git.

### Task 1: Verify local token counting and single-BOS serialization

**Files:** Create `minds/nemotron.py`, `tests/test_nemotron.py`; modify `context.py`, `minds/lmstudio.py`, `app.py`, `cli.py`, `pyproject.toml`, `tests/test_lmstudio.py`. Update minds/root AGENTS when their dependency/template statements change.

**Interfaces:**
- Preserve `render_nemotron(messages: tuple[ChatMessage, ...]) -> str`, moved to `minds/nemotron.py`; update every import/caller, including tests and the M1 verifier used for comparison.
- `NemotronTokenCounter(path: Path)` loads/checks the pinned asset once; `__call__(messages: tuple[ChatMessage, ...]) -> int` counts full rendered prompt plus one backend BOS. Expose `fingerprint: str` and `method: str`.
- Append `token_counter: Callable[[tuple[ChatMessage, ...]], int] | None = None` and `safety_margin_tokens: int = 32` to `ContextCompiler`; `None` explicitly means the existing conservative fake-mode method. Keep its first three positional arguments compatible.
- `LMStudioFast.verify_token_count() -> None` is async startup verification; later usage mismatch raises `StreamProtocolError` and latches the real adapter unverified. `stream` refuses an unverified real counter. Startup probe does not enter Journal/output.
- Append `Config.tokenizer: Path = Path(".data/tokenizers/nemotron.json")`; CLI adds `--tokenizer PATH`. Preserve existing positional arguments; construct the real counter and verify startup before entering Runtime. Fake startup requires neither tokenizer asset nor extra.

- [x] **Step 1: Pin failing renderer/counter checks.** Add `test_wire_prompt_has_no_literal_bos_and_keeps_controls_escaped` asserting wire starts `<|turn>system\n`, includes exactly one initial system role, ends `<|turn>model\n`, and quoted `<bos>` becomes `\\u003cbos>`. Add `test_counter_counts_the_serialized_prompt_plus_backend_bos` with a tiny in-memory tokenizer stub recording the exact string and `add_special_tokens=False`; disable truncation/padding. Add invalid-hash/special-ID tests with tiny temporary assets. Do not commit the 32 MB tokenizer as a fixture.

  ```python
  self.assertTrue(prompt.startswith("<|turn>system\n"))
  self.assertFalse(prompt.startswith("<bos>"))
  self.assertEqual(counter(messages), 4)  # Stub encode returns three IDs.
  ```
- [x] **Step 2: Run RED.** `python -m unittest discover -s tests -p test_nemotron.py -v`; expect missing new module/counter or the current literal BOS assertion to fail. Record the actual failure.
- [x] **Step 3: Implement renderer move and injected counting.** Move existing constants/escaping/assistant continuation unchanged except remove initial BOS. Add `nemotron` optional extra with `tokenizers==0.22.2`, a lazy import and clear missing-extra/file error. Validate SHA-256 `cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f` and special IDs BOS=2, EOS=1, turn=105/106. Use `Tokenizer.from_file`; no `from_pretrained`, download or network in counting. Recount full candidate messages in compiler; do not sum per-message tokenizer results.
- [x] **Step 4: Verify real parity before designing around it.** Install `.[nemotron]` only in the project environment. Download only the pinned tokenizer from revision `49843eed8db1f1c616c47af75cfd36e07aec0667` to `.data/tokenizers/nemotron.json`, verify its hash. Use a temporary ignored probe for at least 16 full prompts covering the spec's Unicode/whitespace/control/code cases and 2K/8K/near-limit sizes. Require local count = SSE `usage.prompt_tokens` in every sample and no duplicate-BOS warning. If not equal, inspect conversion/normalization and resolve correspondence before proceeding; do not invent a factor. Record provenance/errors, startup load time and local count latency.
- [x] **Step 5: Pin and implement startup/mismatch behavior.** Add transport tests `test_startup_count_mismatch_refuses_generation` and `test_late_count_mismatch_latches_until_revalidation`: successful startup count matches, one generation with mismatched usage fails, the next makes zero HTTP requests. Include absent usage as a failure; preserve terminal SSE/control/cancellation checks. Implement `verify_token_count` with one non-streaming short raw completion and the same renderer/counter; compare actual usage, never log the probe prompt. Update successful transport fixtures to supply usage and verified counters.
- [x] **Step 6: Run GREEN.** Run the full unittest suite and `git diff --check`; keep unrelated stream-fault tests intact. Record Task 1 results locally; do not commit yet.

### Task 2: Persist immutable epochs and validate atomic compaction proposals

**Files:** Create `contracts/context.py`; modify `contracts/state.py`, `contracts/protocols.py`, `runtime/journal.py`, `tests/test_journal.py`, contracts/runtime AGENTS.

**Interfaces:**
- Frozen `ContextItem(text: str, source_event_ids: tuple[EventId, ...], kind: Literal["extract", "summary"] = "extract", truncated: bool = False)`.
- Frozen `ContextEpoch(version: int = 0, compacted_through_sequence: int = 0, items: tuple[ContextItem, ...] = ())`; append `epoch: ContextEpoch = field(default_factory=ContextEpoch)` to `FastSnapshot`.
- Frozen `CompactionProposal(proposal_id: str, character_id: CharacterId, based_on_epoch: int, based_on_revision: int, observed_through_sequence: int, compacted_through_sequence: int, items: tuple[ContextItem, ...])` and `CompactionResult(accepted: bool, epoch_version: int, reason: str)`.
- `Journal.context_epoch(character_id: CharacterId) -> ContextEpoch`, `fast_snapshot(character_id: CharacterId) -> FastSnapshot`, `apply_compaction(proposal: CompactionProposal) -> CompactionResult`.
- `ContextPolicy` protocol: `prepare_epoch(snapshot: FastSnapshot, message: UserMessage) -> CompactionProposal | None`; `validate_compaction(snapshot: FastSnapshot, proposal: CompactionProposal) -> None`. Both synchronous, local and side-effect free.

- [x] **Step 1: Add failing migration/atomicity checks.** `test_v1_migration_preserves_state_cursor_and_events` opens an explicitly created v1 temporary DB, migrates, and asserts user_version=2, unchanged state/cursor/events and epoch version=0. `test_epoch_and_audit_rollback_and_restart` injects a SQLite trigger rejecting `context.epoch.applied`, asserts old epoch/no audit on rollback, then removes trigger, applies and reopens to assert identical epoch/cutoff/items. Note revision and Deep cursor must remain unchanged.

  ```python
  self.assertEqual(journal.context_epoch("primary").version, 0)
  self.assertEqual(journal.snapshot("primary"), original_state)
  self.assertEqual(journal.cursor("primary"), original_cursor)
  ```
- [x] **Step 2: Run RED.** `python -m unittest discover -s tests -p test_journal.py -v`; expect missing epoch API/contracts before implementation.
- [x] **Step 3: Implement additive storage and coherent snapshots.** Add `context_epochs(character_id TEXT, version INTEGER, content TEXT, PRIMARY KEY(character_id, version))`; content is canonical frozen epoch JSON. Accept versions 0/1/2, migrate in one transaction, reject newer versions. Read current state, epoch, watermark and all exact dialogue after cutoff in one short local read transaction; remove the production newest-20 limit without changing `recent_dialogue` utility semantics. No inference in Journal.
- [x] **Step 4: Add rejection/replay tests.** `test_compaction_replay_conflicts_and_invalid_ranges` uses subtests for replay, changed-content proposal ID, stale epoch, stale note revision, foreign/missing/future evidence, invalid item kind/text, mismatched extract text, reversed/boolean watermarks, cutoff through an unfinished or half-completed turn, and no-op epoch. Assert deterministic reasons, no active-epoch change and one idempotent decision. `test_late_compaction_preserves_newer_exact_turns` appends later dialogue after proposal observation, applies it and asserts all later IDs remain in the next snapshot.
- [x] **Step 5: Implement validated decisions.** Reuse canonical proposal encoding and existing EventConflict pattern with audit ID `compaction_{proposal_id}`. CAS both epoch and note revision; require `old_cutoff <= cutoff <= observed <= high_watermark`, terminal-turn boundaries, nonempty same-character evidence at/below cutoff, at most 32 items, 32 source IDs/item and nonblank text of at most 8000 characters/item. Reject malformed IDs/booleans before SQLite binding. Extract text must equal source text, or be its nonempty prefix with `truncated=True`; summary evidence is provenance, not proof of truth. Same-cutoff transitions require changed items. Insert next version and applied/rejected audit atomically; do not acknowledge Deep here.
- [x] **Step 6: Run GREEN.** Run journal and full suites; inspect a migrated synthetic database with `PRAGMA integrity_check` returning `ok`. Document schema and rejection reasons in scoped guidance; no commit yet.

### Task 3: Plan bounded epochs without sliding history or truncating required input

**Files:** Modify `context.py`, `tests/test_context.py`, tests AGENTS.

**Interfaces:**
- `ContextCompiler` implements the Task 2 `ContextPolicy` methods and keeps `compile(snapshot: FastSnapshot, message: UserMessage) -> CompiledContext`.
- `compile` includes the supplied whole epoch or raises `ContextBudgetExceeded`; it never commits or drops individual active-history messages. `prepare_epoch` returns one deterministic source-backed proposal only when optional material can be reduced.
- Append epoch version/cutoff, counted input, count method, margin, limit, reserve, headroom, section deltas, stable-prefix hash and compilation duration to existing bounded metadata. Keep `estimated_input_tokens` as a compatibility alias; label fake counts conservative. Hashes exclude timings.

- [x] **Step 1: Pin prefix and required-content regressions.** Add `test_more_than_twenty_events_append_without_prefix_loss` (at least 32 dialogue events, one unchanged epoch, exact IDs all retained), `test_note_change_only_changes_mutable_tail`, and `test_summary_and_hostile_note_remain_quoted_data`. Assert fixed identity/epoch/history bytes, current input once and last, and escaping survives actual renderer. Replace the old compiler whole-message-eviction assertion with explicit overflow/transition assertions.

  ```python
  self.assertEqual(compiled.history_included, 32)
  self.assertEqual(compiled.history_dropped, 0)
  self.assertEqual(compiled.messages[-1].content, current.text)
  self.assertEqual(before.messages[:-2], after_note.messages[:-2])
  ```
- [x] **Step 2: Run RED.** `python -m unittest discover -s tests -p test_context.py -v`; expect old rolling selection or absent epoch policy to fail.
- [x] **Step 3: Implement whole-epoch compilation and transition selection.** Render/count candidate messages through Task 1's callback. Require `count + output + 32 <= context`; compute soft threshold as floor(90% of available input). Keep latest three terminal-turn units up to 2048 incremental tokens; choose cutoff before them. Build up to 2048 incremental tokens of attributed items, oldest user anchor first plus newest evidence, chronological serialization, per-extract caps 256 tokens/8000 characters. Carry previous bounded items, not recursive textual summaries. Use deterministic proposal IDs derived from canonical base/cutoff/items. Scale optional caps to available space for small contexts; full prompt count is final authority. Exclude measured duration from dataclass equality and deterministic hashes.
- [x] **Step 4: Pin pressure and retention checks.** Add `test_transition_preserves_anchor_recent_turns_note_and_sources`, including a second transition; `test_large_unicode_input_and_note_never_truncated`; `test_exact_budget_boundary_and_noop_prevention`; `test_small_window_and_single_oversized_history_turn`. Assert count at hard limit fits, +1 fails if all content required, overlap exchanges stay whole, truncated optional extracts are marked, no source beyond cutoff/current leaks into items, and no endless same-cutoff/no-op proposal. Use injected deterministic counters to hit exact boundaries, plus the Task 1 real tokenizer corpus for provider correspondence.
- [x] **Step 5: Implement final fitting.** Required identity/note/current overflow fails before planning any durable transition. Reduce oldest optional overlap, then oldest non-anchor items, then anchor only if necessary; retain Journal unchanged. If current epoch already fits and no useful reduction exists, return None even above soft threshold. Validate external proposal item cost with the same quoted wrapper and 2048 cap; preserve M1 final-input precedence.
- [x] **Step 6: Run GREEN.** Run context and full suites, then time repeated representative local compilation at 2K/8K/near-limit. Record p50/p95; optimize only a measured problem while keeping the counted string identical. No commit yet.

### Task 4: Wire Runtime preparation, asynchronous application and CLI diagnostics

**Files:** Modify `runtime/orchestrator.py`, `app.py`, `cli.py`, `minds/lmstudio.py`, lifecycle/transport tests and affected AGENTS.

**Interfaces:**
- Append `context_policy: ContextPolicy | None = None` to Runtime keyword arguments; composition always supplies it for both fake and real paths. Direct existing lifecycle fixtures may omit it.
- `Runtime.apply_compaction(proposal: CompactionProposal) -> CompactionResult` validates local budget then calls Journal atomically; this synchronous entry point can be called after any future provider await, including while Fast streams.
- Consume Task 1's `Config.tokenizer` and startup verification; no second counter, renderer or startup probe.

- [x] **Step 1: Add failing lifecycle checks.** `test_epoch_and_note_updates_do_not_mutate_active_fast_snapshot` stalls a captured Fast snapshot, applies a valid note and compaction, asserts old snapshot/hash/epoch unchanged, then asserts the next turn sees committed state and epoch. `test_epoch_pressure_restart_and_rejected_input_have_terminal_events` drives >20 events with a small deterministic budget, restarts, checks persisted epoch and exact later history, then submits required-content overflow: no Fast call, one started/failed pair, reason ContextBudgetExceeded, no speculative epoch and no unfinished replies.

  ```python
  self.assertEqual(captured_snapshot, original_snapshot)
  self.assertEqual(next_snapshot.epoch.version, original_snapshot.epoch.version + 1)
  self.assertEqual(journal.unfinished_replies("primary"), ())
  self.assertEqual(journal.get(f"reply_terminal_{oversized.event_id}").kind,
                   "character.reply.failed")
  ```
- [x] **Step 2: Run RED.** `python -m unittest discover -s tests -p test_runtime_lifecycle.py -v`; expect missing policy/entry point before wiring.
- [x] **Step 3: Wire the smallest local preparation path.** After existing append/dedup/supersession, read Journal.fast_snapshot, call policy.prepare_epoch, validate/apply any proposal, then freeze the new snapshot. No await between loading bases and local commit. On required-content overflow append started and failed terminal using the original snapshot and return None; keep duplicate submit idempotent. Include actual epoch version/cutoff in reply-start audit metadata. `apply_compaction` does not restart Fast or touch its frozen diagnostics. Extend pure policy injection in composition; keep Runtime free of concrete minds.
- [x] **Step 4: Complete inspector and mismatch wiring.** Use the same compiler/counter instance for Runtime policy and LMStudioFast. Await Task 1 startup verification before entering Runtime. `/context` exposes active turn's frozen epoch/provenance/budget/hash; `/status` separately identifies latest committed epoch; `/metrics` shows actual/local count difference and time. Do not expose raw compacted text by default or persist performance counters as domain events.
- [x] **Step 5: Verify cancellation and fake startup.** Extend immediate supersession/shutdown tests to cross a transition; assert one terminal per turn, no stale deltas and closed HTTP stream. Run source CLI without tokenizer installed using fake Fast, then MockTransport real startup with missing/mismatching usage and assert clear refusal. Run full suite on Python 3.12 and the primary interpreter with `-X dev`, plus `git diff --check`. No commit yet.

### Task 5: Measure actual epochs, document results and commit M1.5

**Files:** Create `scripts/verify_m1_5_context.py`, `docs/M1_5_IMPLEMENTATION.md`; modify README, blueprint and applicable root/scoped AGENTS. Mark this plan's completed steps as evidence becomes available.

**Interfaces:** `python scripts/verify_m1_5_context.py --endpoint http://127.0.0.1:1230 --model liac-nemotron --tokenizer .data/tokenizers/nemotron.json --output .data/m1-5-results.jsonl`; explicit opt-in live script, not part of unittest discovery. Its synthetic DB/logs live under `.data/`; output contains hashes/IDs/counts/times/statuses only. Reuse `sse_data`, speech/control validation and production Runtime; no second model client abstraction.

- [x] **Step 1: Write the verifier with self-checks.** Run serial calls, subscribe to runtime logs with hidden owned subprocesses, attribute exactly one distinct task ID per generation window or mark counters unavailable/ambiguous. Always stop owned subscribers in finally; never kill/reload LM Studio. Assert token parity, legal budget, terminal streams, nondecreasing history prefix within an epoch, source integrity and no stale cancelled deltas. Store cached_tokens=null unless explicitly exposed; evaluated tokens are a separate measured field. Startup compatibility requests are labelled calibration and excluded from timing summaries.
- [x] **Step 2: Run matched transport controls.** Reproduce M1's garden recipe and three trials at ~2K/~8K/~15.5K for prime/repeat/append/note/rolling shift, using the old M1 BOS/order as an explicit reference and the corrected renderer as a separate variant. Record exact input sizes and configuration instead of comparing unmatched counts as equivalent work. Compare against documented M1 medians; report drift and cache-state limits.
- [x] **Step 3: Run production lifecycle measurements.** Three serial trials of at least 30 real Runtime turns, extending if necessary to observe two transitions/trial. Use actual compiler output, 16384/512 budgets and meaningful synthetic facts/corrections mixed with filler. Reach at least 85% of the 15840 input allowance on a production turn; retain the early fictional anchor and demonstrate the latest correction after transition/restart. Report each turn's epoch/input/utilization/TTFT/compile/evaluated count and transition cost; summarize p50/p95. Check whether most warmed non-transition turns above 8K evaluate <25% of prompt tokens; report any miss rather than asserting cache guarantees.
- [x] **Step 4: Exercise the actual CLI and asynchronous behavior.** Run the normal CLI with separate ignored DB: fictional penguin Мандарин/blue hat, later correction to green, enough dialogue for transition, exit and reopen the same DB, query the current fact. While a real reply streams, deliver delayed FakeDeep update and a validated older-range compaction proposal through Runtime; show the old frozen snapshot and later uptake without waiting for Deep. Supersede a streamed story and record cleanup time, durable terminal statuses and zero stale deltas. Include near-budget recall of several dispersed facts; record exact successes/failures without calling this a broad quality benchmark.
- [x] **Step 5: Update user/contributor documentation.** README gives `.[nemotron]`, one-time pinned tokenizer download/hash and `--tokenizer`, epoch lifecycle/retention and inspector commands. Update relevant AGENTS with tokenizer isolation, v2 atomicity, immutable epochs and changed tests. Blueprint §§7.2–7.3/9.4/20/OQ-04 adds M1.5 and explicitly supersedes M1 rolling-window/heuristic restrictions for this milestone. Report actual environment, counts/TTFT/cache evidence, dependency cost, two-transition/restart/Deep/cancel outcomes, semantic retention limits, failures and M2 readiness. Preserve original M1 report as historical evidence.
- [x] **Step 6: Review and verify the complete diff.** Read verification-before-completion/requesting-code-review skills; Native uses one fresh non-Astra reviewer with spec, plan, full diff and safe evidence. Resolve concrete findings, then run required focused/full checks and `git diff --check`; check tracked files exclude `.data` and tokenizer weights/assets. Readiness for M2 means contracts/replay/snapshot boundaries work; do not claim Luna/OMP itself is integrated or that all old facts survive.
- [x] **Step 7: Make the authorized final commit.** Inspect `git status --short`, stage only listed code/tests/script/docs, and commit `feat: add durable context epochs and local Nemotron budgeting` using command-scoped softsock author/committer name/email plus `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`. Verify commit identity, staged content and clean intended worktree. Do not push or create PR. Final response links the report and gives actual results, limits and commit SHA.

## Plan self-review

Requirement mapping: epochs/proposal/restart = Tasks 2–4; tokenization/template =
Tasks 1/3; stateless cache/prefix and real CLI evidence = Tasks 4–5; streaming,
cancellation and nonblocking Deep = Task 4/5; docs/AGENTS/report/M2 readiness and
authorized commit = Task 5. Each Review Focus condition has a named check above.
Interfaces consistently use `ContextItem`, `ContextEpoch`, separate note revision
and epoch version, and Task 1's shared renderer/counter. No product implementation
has been performed during planning. Open acceptance gates are tokenizer/GGUF
parity and actual live retention/performance; neither is assumed successful.
