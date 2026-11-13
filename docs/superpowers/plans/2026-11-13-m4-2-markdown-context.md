# M4.2 Luna-managed Markdown Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Luna asynchronously replace one durable Markdown working context that naturally influences subsequent Nemotron replies without disrupting Fast or Context Epochs.

**Architecture:** Reuse M2's immutable requests, whole-document `NoteProposal`, serialized Deep worker and atomic SQLite batch application. Keep the existing internal names and schema v2; replace the 1000-character policy with a small locally counted Markdown budget, remove technical state metadata from the Fast prompt, and export a recoverable `context.md` projection. Reject actual revision/epoch conflicts using the existing CAS checks, allow results delayed by ordinary dialogue, and preserve newer exact user input with explicit precedence over older suggestions.

**Tech Stack:** Python 3.12+, stdlib asyncio/SQLite/unittest, existing HTTPX, pinned optional Nemotron tokenizer and vendored OMP RPC SDK. No new dependency.

**Spec:** [User-supplied M4.2 requirements](../specs/2026-11-13-m4-2-markdown-context-requirements.md).

## Global Constraints

- “Не створюй Performance Beat Scheduler, новий Attention Engine чи окремих агентів.” No new application agents; do not restore reverted M4.1.
- “Не роби файлову систему другим незалежним джерелом правди” — SQLite owns state; never import manual file edits.
- “редагування Markdown-контексту не повинно змінювати стабільний префікс Fast prompt.”
- “Асинхронна підготовка на 75% бюджету”; “Детермінований fallback після 90%.”
- “Не створюй PR і не пуш без окремого прохання.”
- “створи один змістовний коміт з автором softsock і потрібним `Co-authored-by`.” This overrides per-task commits: stage nothing until final verification.
- Python 3.12+; English application interface text and code comments; no GPT-6 Astra subagents. No secrets/private dialogue in Git; no Loonyball edits, deployment or large services.
- Keep single BOS, exact local real-provider counting, 16384 context / 512 output / 32 margin defaults, stateless `/v1/completions`, streaming and cancellation.
- Empty replacement, identical replacement and null/no-op are valid. Suggested Threads are optional, with no required headings or section schema.

## Review Focus

1. New user input arrives while Luna is running: ordinary dialogue must not starve updates; current corrections must still override an older suggestion (Task 2, live check in Task 4).
2. Empty/identical Markdown: clearing persists, null preserves content, identical content does not churn revision or trigger another inference (Task 1).
3. Unicode, whitespace and literal template control strings: preserve document bytes, count the rendered escaped form and reject oversized updates without truncating history (Tasks 1–2).
4. File write fails after DB commit: SQLite/cursor stay committed, the old file stays whole, and startup restores the file from SQLite (Task 3).
5. Large Markdown and near-16K history during epoch preparation: preserve reservations, frozen snapshots and exact newer turns; measure actual evaluated tokens separately from TTFT (Tasks 2 and 4).

---

## Inspected baseline and execution boundary

Planning inspected fetched `origin/main` at `ec46c3e3524c92bf6c18da0d69f53276c0c76298`, including M1.5/M2 reports, contracts, ContextCompiler, Journal, DeepWorker, OMP confinement and desktop consumers. M4.1 is absent there. The current working checkout is older `codex/m1-context-cache` (`656a12b`); **do not implement against it**. These two new planning documents are the only changes made during planning.

The linked ChatGPT conversation resolves to Capri/Hermes approval-port discussion, not M4.2; it supplies no requirements for this plan. The copied attachment plus the user revisions below are the authoritative requirements. Re-read the relevant blueprint sections 6–9, 11, 13 and milestone statuses on the execution base.

### User revisions incorporated

- Remove rejection triggered by any newer user message. Keep actual state/epoch conflicts and source validation; newer exact dialogue remains authoritative.
- Make the working-context budget configurable, initially evaluate 1024–2048 tokens rather than treating 1024 as final.
- Keep atomic file persistence, integrity/restart checks, real dialogue and KV measurements, but use the existing worker and verification tools without a separate export subsystem or large new harness.

At execution, use `superpowers:using-git-worktrees` to create `codex/m4-2-markdown-context` from freshly fetched `origin/main`; carry both planning documents into that worktree. Recheck instructions and diff the inspected modules if main moved. Keep the existing worktree and its changes intact.

## File map and decisions

| Files | Responsibility/change |
|---|---|
| `contracts/state.py`, `contracts/deep.py` | Document existing `context_note`/`note` as whole Markdown, keeping dataclass shapes and schema v1 envelope. |
| `runtime/journal.py`, `runtime/state.py` | Empty/unchanged replacements, structural limit, existing conflict checks, durable rejection/replay; preserve schema v2 and audit encoding. |
| `minds/luna.py`, `minds/deep.md`, `minds/fake.py` | Single Markdown text field, strict transport validation, optional concrete suggestions and true no-op. |
| `context.py`, `contracts/protocols.py`, `runtime/deep.py`, `contracts/deep.py`, `app.py`, `cli.py` | Mutable-tail block, configured local document budget and its propagation to Luna, precommit budget rejection; existing compaction remains. |
| `runtime/context_file.py` (new), `runtime/deep.py`, `runtime/orchestrator.py`, `app.py` | Small atomic file writer called by the existing Deep worker, plus startup refresh. |
| `minds/character.md` | Explicit latest-user precedence and optional suggestions; authored once at startup. |
| Existing focused tests plus `tests/test_context_file.py` | Critical invariants; reuse real temporary SQLite fixtures. |
| `scripts/verify_m2_luna.py`, `scripts/verify_m1_5_context.py` | Small opt-in Markdown dialogue and cache cases in existing verification tools; no new harness. |
| README, relevant AGENTS, blueprint, `docs/M4_2_IMPLEMENTATION.md` | Current contract, commands, scope and actual evidence. |

Keep `CharacterState.context_note`, `NoteProposal.note`, `DeepResult.note`, `DeepDecision.note`, existing audit kinds and SQL column names. There is only one logical document, not a parallel Markdown state. This avoids unnecessary schema migration and preserves historical desktop traces and `/state`. Explain legacy naming in documentation. No desktop redesign or executable rebuild is needed: existing plain-text snapshot/diff consumers continue to read these fields.

Transport remains `{"schema_version":1,"note":{"text":"<whole Markdown>","source_event_ids":["..."]},"compaction":null}`. `note:null` means leave unchanged; `text:""` clears it. Sources remain required for replacements, including clear; provenance is not semantic proof. Keep the 64-KiB response/512-KiB request transport gates and compaction validation unchanged.

Document limits are execution decisions: keep **32768 UTF-8 bytes** as a structural parser/Journal safety ceiling. Add `Config.working_context_tokens: int = 2048` at the end of the existing dataclass and CLI `--working-context-tokens`; accept a positive integer below `input_limit`. Pass it by keyword to `ContextCompiler.working_context_tokens: int = 2048`. This is an initial adjustable budget, not an allocation permanently taken from history. Compare 1024 and 2048 in real conversations before recommending a default for continued use. Count actual rendered document cost; preserve the full input/output reserves. Reject oversize proposals durably rather than slicing them. Existing stored text remains unchanged when opening old databases or reducing the configured budget; report its size, apply the new cap to subsequent proposals, and retain normal whole-prompt overflow handling.

## Task 1: Whole-document replacement on the existing durable contract

**Files:** Modify `src/vtuber/{contracts/state.py,contracts/deep.py,minds/luna.py,minds/deep.md,minds/fake.py,runtime/journal.py,runtime/state.py}`. Tests: `tests/test_luna.py`, `tests/test_journal.py`, `tests/test_deep.py`.

**Interfaces:** Consume existing `parse_result(text: str, request: DeepRequest) -> DeepResult`, `Journal.apply_deep(...) -> DeepDecision`, `Journal.apply_note(...) -> UpdateResult` and `reduce_note(state: CharacterState, proposal: NoteProposal) -> CharacterState`. Preserve their existing data shapes. Produce replacement semantics: empty accepted; identical returns `UpdateResult(True, current_revision, "no_change")`; changed content increments exactly once. Null returns no note operation and acknowledges valid work normally.

Parser test using the existing `LunaParserTests.setUp` request:

```python
def test_markdown_clear_is_not_noop(self):
    clear = parse_result(json.dumps({"schema_version": 1, "note": {
        "text": "", "source_event_ids": ["source"]}, "compaction": None}), self.request)
    noop = parse_result('{"schema_version":1,"note":null,"compaction":null}', self.request)
    self.assertEqual(clear.note.note, "")
    self.assertIsNone(noop.note)
```

- [x] **Step 1: Add failing parser and persistence tests.** Extend `LunaParserTests` to assert parsing Markdown longer than 1000 characters, preserving leading/trailing whitespace and custom headings, and parsing `text:""` versus `note:null`. Retain duplicate/unknown keys, invented sources, boolean version and invalid compaction cases; replace the obsolete 1001-character rejection with UTF-8 byte boundary tests (`"🙂" * 8192` accepted structurally, one more rejected; serialize with `ensure_ascii=False` to stay within the separate transport ceiling). Add `DeepJournalTests.test_markdown_replace_clear_and_no_change` using existing user/finish/result helpers: changed document survives reopen, repeated content keeps revision, empty increments once and survives reopen, null preserves revision/content while advancing the cursor. Assert unknown/cross-character sources still reject.
- [x] **Step 2: Run RED.** Run `python -m unittest discover -s tests -p test_luna.py -v` and the equivalent `test_deep.py`/`test_journal.py` commands. Expect failures on the old 1000-character/empty/identical behavior, not import/environment failures.
- [x] **Step 3: Implement replacement semantics in the named existing interfaces.** Validate string type and UTF-8 bytes without trimming the stored value; strict source validation still applies. In `_apply_note`, record unchanged accepted operations without SQL revision increment; preserve operation replay checks, old proposal serialization and batch rollback. Update Deep role instructions for free-form Markdown, optional almost-ready lines, latest corrections, canonical evidence over session recollection, clear/no-op, and the separate epoch summary purpose. Keep FakeDeep deterministic and its current API; adjust its output description only where required.
- [x] **Step 4: Run GREEN.** Repeat the three focused suites. Extend the existing rollback/replay test with a >1000-character document and empty clear, asserting a failed batch audit restores document, revision, epoch and cursor. Reopen existing v1/v2 fixtures and assert original note, raw events, cursors and epochs are unchanged; schema stays v2.

## Task 2: Configurable mutable prompt tail and conflict handling

**Files:** Modify `src/vtuber/{context.py,contracts/protocols.py,contracts/deep.py,runtime/deep.py,runtime/journal.py,app.py,cli.py,minds/character.md,minds/deep.md}`. Tests: `tests/test_context.py`, `tests/test_deep.py`, `tests/test_cli.py`, existing tokenizer/runtime suites.

**Interfaces:** Add `ContextPolicy.working_context_tokens: int` (read-only property in the protocol) and `validate_working_context(text: str) -> None`; `ContextCompiler` supplies the configured field and validation raises `ContextBudgetExceeded`. Append `working_context_tokens: int = 2048` to `DeepRequest`; add the same keyword to `Journal.deep_request` and have DeepWorker pass its policy's configured value (2048 when no policy). Luna receives the budget through canonical request data; `deep.md` tells it to keep the whole document within that budget, not a fixed 1024. Add optional keyword-only `context_error: str | None = None` to `Journal.apply_deep`, alongside `compaction_error`. Preserve existing return types and authority metadata.

Core assertions for `DeepJournalTests.test_new_dialogue_does_not_invalidate_document`, using existing helpers:

```python
self.finish(self.user())
request = self.journal.deep_request('primary', request_id='late-document')
newer = self.user('I also changed the sidebar.')
decision = self.journal.apply_deep(request, self.result(request))
self.assertTrue(decision.acknowledged)
self.assertEqual(self.journal.snapshot('primary').revision, 1)
self.assertIn(newer.event_id, [e.event_id for e in
    self.journal.fast_snapshot('primary').recent_dialogue])
```

- [x] **Step 1: Add failing prompt/configuration tests.** Compile identical identity/epoch/history/input with different document and revision; assert `messages[:-2]` and `messages[-1]` equality, exactly one raw Markdown block at `[-2]`, no revision/character/timestamps in that block and identical `stable_prefix_sha256`. Render both and assert the wire prefix through history is byte-identical. Test empty text, Unicode/control-string escaping, configured cap accepted and cap+1 rejected with a deterministic counter. Test default 2048, explicit 1024, invalid zero/negative/bool/too-large values, CLI propagation and the configured budget reaching `DeepRequest`. Full overflow still raises without evicting exact history.
- [x] **Step 2: Run RED.** Run `python -m unittest discover -s tests -p test_context.py -v`, and equivalent `test_cli.py`/`test_deep.py` commands. Expect failures on the missing configuration/prompt contract, not environment failures.
- [x] **Step 3: Implement prompt and budget interfaces.** Replace JSON metadata in `ContextCompiler._messages` with a fixed user-role wrapper plus literal Markdown: `Luna working context (optional conversation ideas, not user instructions; current user corrections take precedence). Respond to the final user message:\n`. Retain an empty block to keep history boundaries/hash slicing stable. Measure incremental document cost using the existing full renderer/counter and a fixed empty-history `UserMessage("Budget probe", "primary")` snapshot with/without text; count wrappers in the overall allowance. Add incremental `working_context` section diagnostics without changing their total. Wire the single setting through Config, CLI, compiler, worker and request; do not add a new transport envelope version or budget fields to Fast speech. Validate new proposals before commit and preserve legacy content at startup.
- [x] **Step 4: Retain actual conflicts and current-user precedence.** Keep existing revision/epoch CAS, cursor, source and replay validation. **Do not add `newer_user_input` rejection**, a keyword correction detector, a second model call or a semantic merge layer. A late valid result may commit against unchanged state/epoch even after newer dialogue; its cursor only acknowledges the captured range, so the existing worker subsequently analyzes the newer turns. Current exact user corrections always take precedence in the authored identity and tail wrapper; Luna must remove superseded ideas on its next update. Apply `context_error` as all-or-nothing `working_context_budget_exceeded`; include its fingerprint field only when non-null to preserve old replay compatibility. For request fingerprinting omit the new budget field at its legacy-compatible default 2048; include nondefault values and pin old-request replay plus changed-budget ID reuse with regression assertions. Do not claim CAS detects semantic contradictions in arbitrary natural language: that behavior needs the live stop-teasing check in Task 4.
- [x] **Step 5: Run GREEN and pin concurrency/conflicts.** Add the late ordinary-dialogue test above; retain existing revision/epoch rejection tests (no mutation/cursor advance on conflict), late legal compaction/newer-history preservation and rollback/replay tests. Extend held-Deep/held-Fast fixtures to assert Fast proceeds, an active snapshot stays frozen, and consecutive ordinary inputs do not force repeated rejection of every document. A correction fixture must assert the exact correction is present after a late commit and the prompt explicitly gives it precedence; it does not claim model obedience. Assert token-budget rejection rolls back bundled compaction and cursor. Run affected suites plus existing Nemotron/runtime suites, retaining one-BOS/parity/cancellation and 75%/>90% pressure checks with a nonempty near-configured-cap document.

## Task 3: Small atomic context.md writer and startup recovery

**Files:** Create `src/vtuber/runtime/context_file.py`, `tests/test_context_file.py`; modify `src/vtuber/{runtime/deep.py,runtime/orchestrator.py,app.py}`.

**Interfaces:** Two functions only: `context_file_path(db: Path, character_id: str) -> Path` and `write_context(path: Path, text: str) -> None`. Derive `db.parent / (db.name + ".contexts") / sha256(character_id.encode("utf-8")).hexdigest() / "context.md"` to isolate DBs/characters safely. Optional `context_path: Path | None = None` on Runtime/DeepWorker is supplied by `open_runtime`. No export service, queue, watcher, revision manifest or periodic retry loop.

Atomic-writer test core inside a temporary directory:

```python
path = Path(folder) / 'context.md'
write_context(path, '# Context\r\n🙂\r\n')
expected = path.read_bytes()
with patch('vtuber.runtime.context_file.os.replace', side_effect=OSError):
    with self.assertRaises(OSError):
        write_context(path, 'replacement')
self.assertEqual(path.read_bytes(), expected)
```

- [x] **Step 1: Write the focused failing checks.** One writer test covers exact UTF-8/empty text and replacement failure preserving the old complete file. One integration test commits a document, deletes/stales the file, restarts and verifies file bytes equal SQLite without revision/cursor changes; inject a write failure and verify the committed DB/cursor stay valid. Include a simple distinct/contained path assertion for different DBs and an unsafe character ID. Keep the existing held-Fast test for independence; no large recovery matrix.
- [x] **Step 2: Run RED.** Run `python -m unittest discover -s tests -p test_context_file.py -v`; expect the missing writer/recovery contract to fail.
- [x] **Step 3: Implement the two helpers and existing-worker calls.** Write a same-directory temporary file as UTF-8 bytes, close it, replace with `os.replace`, clean up on failure. DeepWorker refreshes at startup and after a changed acknowledged document, capturing committed text on the SQLite-owning loop then invoking the writer via `asyncio.to_thread`; no transaction or submit lock spans that await. Keep writes serial inside that worker. On `OSError`, record only the exception class in `context_export_error`, leave the already committed DB/cursor alone, and retry on the next changed document or restart. Join the single in-flight write on close before a replacement Runtime can start. This small lifecycle rule prevents stale overwrites without a separate exporter subsystem. Never read the file as input or add technical headers to it.
- [x] **Step 4: Run GREEN.** Repeat focused checks and existing shutdown/CLI checks; reopen the test DB and assert `PRAGMA integrity_check` is `ok`. Path/error can use existing Deep diagnostics and `/status`; no new CLI command or desktop change.

## Task 4: Focused live acceptance using existing verification tools

**Files:** Modify `scripts/verify_m2_luna.py` and `scripts/verify_m1_5_context.py` only as needed for a small Markdown case. Keep private raw conversations/logs/databases under ignored `.data/m4-2-*`. No new script, general scenario runner, results framework or comprehensive fault matrix.

**Interfaces:** In M2 verifier add opt-in `--phase markdown` and `async def markdown_context(evidence) -> None` following its existing phase conventions. Use the existing runtime/config/evidence helpers. In M1.5 verifier add opt-in `--phase markdown-cache` and `async def markdown_cache(evidence, trials: int) -> None`, reusing `counters`, `raw_call` and owned log subscription. Existing phases/default behavior remain compatible. Reuse M2’s `--self-check`, M1.5’s inline parser assertions and the existing `--trials`; add no other verifier options. The Markdown dialogue phase constructs Config with 1024 and 2048 in turn.

- [x] **Step 1: Keep a tiny self-check for any new branch.** Extend the existing self-check for phase selection and single-task cache attribution; reuse its existing parser checks rather than duplicating them. Expected assertions include `counters(sample)['prompt_evaluated_tokens'] == 84` for the existing sample and `counters(sample + sample)['prompt_evaluated_tokens'] is None` for ambiguity. Run `python scripts/verify_m2_luna.py --self-check`; retain M1.5’s inline parser checks, which run before any live model call. New phase-selection assertions fail before implementing the new phase, then pass. Do not invent a `--self-check` option for M1.5.
- [x] **Step 2: Run one focused real dialogue at each starting budget.** Using actual Luna/Nemotron, compare configured 1024 and 2048 on the same short conversation outline: an earned concrete suggestion influences a later reply; user changes direction and Luna removes/replaces the idea; user asks to stop teasing and older suggestions do not revive it, including a Luna result delivered after that input; an uninformative message permits unchanged/null output. Let normal newer messages arrive during Luna work and record whether documents still commit. Record actual document/reply pairs privately and summarize successes/failures without a scripted-phrase assertion. Verify Fast responds during Deep work, restart restores the document/file, and DB integrity is `ok`. An injected held result is labeled separately from provider latency. Use the existing M2 long/offline/CLI checks to confirm near-16K semantic epochs, >90% fallback, newer exact turns and restart; do not reimplement them.
- [x] **Step 3: Measure the two cache cases with existing logs.** Add only matched Markdown-tail-change versus epoch-switch prompts to M1.5's existing cache controls (three serial trials via its existing setting). Prime the same baseline separately for each case; keep identity/history/input fixed. Record full prompt count, attributed backend evaluated tokens (cached tokens if exposed) and TTFT. Do not infer reuse from TTFT alone; ambiguous/missing backend counters are unverified. Reuse the existing subscriber and cleanup; do not reload the model or change shared server settings.
- [x] **Step 4: Record commands and outcomes.** After read-only provider availability checks, run `python scripts/verify_m2_luna.py --phase markdown --endpoint http://127.0.0.1:1230 --model liac-nemotron --tokenizer .data/tokenizers/nemotron.json --omp-executable C:/Users/shtvl/AppData/Local/omp/omp.exe --output .data/m4-2-dialogue.jsonl` and `python scripts/verify_m1_5_context.py --phase markdown-cache --endpoint http://127.0.0.1:1230 --model liac-nemotron --tokenizer .data/tokenizers/nemotron.json --output .data/m4-2-cache.jsonl`. Verify current endpoint/model rather than trusting historical defaults. Keep failed samples, chosen budget rationale and provider/log blockers in the report; no milestone-complete claim while required live behavior/cache evidence is missing. No downloads/services are authorized; close only owned resources.

## Task 5: Evidence, scope documentation and one final commit

**Files:** Modify `AGENTS.md`, `src/vtuber/{contracts,runtime,minds}/AGENTS.md`, `tests/AGENTS.md`, `README.md`, `docs/PROJECT_BLUEPRINT.md`; create `docs/M4_2_IMPLEMENTATION.md`. Update `src/vtuber/desktop/AGENTS.md` only if describing its unchanged legacy-key compatibility helps readers; no application UI changes.

**Interfaces:** User-facing documentation names the logical Markdown document, its exact budget/path, SQLite authority and legacy internal field names. Blueprint marks the chosen Markdown path DECIDED for M4.2 and scheduler/structured attention proposals FUTURE; keep prior milestone reports historical.

- [x] **Step 1: Write current behavior and evidence.** Explain whole replacement/no-op/clear, revision/epoch conflicts, late-result acceptance and current-user precedence, atomic commit/file recovery, stable prefix, unchanged epochs and v1/v2 compatibility. Report actual conversation excerpts that are safe to commit, including one effective concrete idea and removal, failed trials, backend evaluated-token comparisons and TTFT with trial counts. Explain simplification versus reverted M4.1 without restoring its code. Separate measurements from assumptions and deterministic checks; never copy secrets or raw private traces. Link the carried spec and plan.
- [x] **Step 2: Verify final implementation.** Run `python -m unittest discover -s tests -v`, M2 verifier self-check and M1.5 parser assertions, fake CLI startup/quit and `git diff --check`; run existing optional desktop tests when dependencies are available and report skips. Confirm `git status --short` contains only scoped source/tests/docs/script changes, no DBs, context exports or traces. Inspect every remaining `1000`, `context_note`, `.note`, `schema_version` and `apply_deep` caller for obsolete policy while preserving public/history compatibility. No vendored SDK or dependency changes. Runtime and provider acceptance must both be reported before claiming completion.
- [x] **Step 3: Commit once after reviewing the full diff.** Stage the explicit implementation/test/doc files (including the two planning documents), not `git add .`. Run `git diff --cached --check`, then `git commit --author="softsock <109231668+softsock@users.noreply.github.com>" -m "feat: add Luna-managed Markdown working context" -m "Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>"`. Check `git show -s --format=full` and final status. Do not push or create a PR.

## Self-review and handoff

Coverage: spec sections 1–3 map to Tasks 1/3; sections 4–6 to Task 2 plus Deep/identity instructions in Task 1; section 7 to Task 4 and focused invariants; section 8/report to Task 5. All five Review Focus conditions have named checks. Contracts/transport remain compatible; the configured budget propagates through Config/CLI/compiler/DeepRequest, and only the policy validation method, optional budget error and optional file path additionally extend existing interfaces. No task depends on an undefined proposal type or new subsystem.

The configurable initial 2048-token budget (compared with 1024), 32768-byte structural ceiling and derived file path are concrete implementation choices. Ordinary newer dialogue is not a conflict; existing revision/epoch CAS rejects conflicting state changes. Semantic correction precedence is enforced by prompt policy and evaluated live, not guaranteed by CAS. Remaining uncertainty is provider behavior, useful document size and cache-log availability; Task 4 records that evidence without adding infrastructure.

Recommend **Native** execution: the five tasks share the existing batch/epoch boundaries and form one small architectural change; implementation can stay in one context with a fresh whole-branch review. The user must review the plan and select execution before code changes, as required by the invoked writing-plans skill. Use no Astra reviewers. The requested single final commit overrides task-by-task commits.

Executed on `codex/m4-2-markdown-context`; see [actual outcomes and limitations](../../M4_2_IMPLEMENTATION.md).
