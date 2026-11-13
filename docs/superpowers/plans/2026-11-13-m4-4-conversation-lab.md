# M4.4 Conversation Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the PySide6 inspector into a live conversation and simulation lab with correlated, historical, offline inspection of real Liac behavior.

**Architecture:** Keep one Runtime/Journal owner and the existing RuntimeWorker. A bounded asynchronous capture writer saves observations for a shared read-only replay model; an independent simulator receives only public conversation and submits ordinary UserMessage objects. The same simulation controller runs headlessly and inside the worker, without Qt in core or simulation code.

**Tech Stack:** Python 3.12+, stdlib asyncio/threading/queue/json/sqlite3/unittest, existing HTTPX, pinned OMP SDK, optional PySide6 Widgets and Nemotron tokenizer. No new dependency or service.

**Spec:** [Original M4.4 requirements](../specs/2026-11-13-m4-4-conversation-lab-requirements.md).

**Execution update:** Native execution authorized. During implementation the user
deferred full testing; the live smoke was stopped after five simulated messages.
Task 6's remaining live/full/long provider checks are postponed, not success claims.
Local invariant verification, documentation and final review remain in scope.

## Global Constraints

- Start execution on a separate `codex/m4-4-conversation-lab` branch from local M4.3 `8f42dfa43f72fdef91740335ee7900ca9d0b9fc0`, or its verified successor containing M4.2/M4.3; do not reset to old main. Planning does not switch branches.
- One meaningful final implementation commit, author softsock, trailer `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`. No push or PR. This overrides per-task commit examples in the skill; task checkpoints remain uncommitted until final verification.
- No GPT-6 Astra subagents. English only for application interface text and code comments.
- Headless Runtime remains independent of PySide6. Simulator and manual chat use the same Runtime; no second Journal or alternative Liac context.
- Simulator cannot access Liac's hidden state. All Qt updates cross the safe worker/UI boundary. Trace capture must not block Fast on disk I/O or queue capacity.
- Preserve Context Epoch, Markdown, cancellation, initiative and KV-cache semantics. Do not change Nemotron/Luna character instructions to improve evaluation scores.
- `Enable initiative` is off by default. Existing configurable 5/120/60-second timing defaults remain experiments.
- Each simulation uses a new SQLite database in a unique Git-ignored run directory. Never overwrite ordinary conversations. Replay is recorded-history viewing, not inference reproduction.
- Do not capture credentials or hidden provider reasoning. Retain capture size limits, expose omitted data, and label unexposed provider-wire prompts/metrics unavailable.
- Use real Nemotron through existing LM Studio and Luna through OMP. Check endpoints/model/tokenizer first; no new model downloads or global LM Studio setting changes.
- Prioritize real end-to-end evidence and a few critical concurrency/lifecycle tests. A long run that stops early is incomplete evidence, not a successful 100–150-turn run.

## Review Focus

1. A slow disk, exhausted capture budget or full writer queue must leave inference responsive and make missing evidence visible — Task 1 failure test.
2. Manual input arriving during simulator inference, pause or shutdown must prevent a stale synthetic submission and preserve ordinary cancellation — Task 3 race test.
3. Selecting an old turn after later corrections/compaction must show its captured Markdown/epoch, with unavailable gaps rather than today's state — Task 2 history test.
4. A crash, truncated archive or older inspector trace must open read-only without inference, duplicate speech or unsafe file access — Task 2 interrupted/legacy test and Task 4 replay test.
5. Long sessions and large prompts must remain navigable without silently losing older conversation, freezing Qt or applying stale detail reads — Task 4 paging/selection test.

---

## Current source findings and scope

Inspected baseline: clean `8f42dfa`, branch `codex/m4-2-markdown-context`.

- `tracing.py` already writes immutable JSON payloads and a validated JSONL index with a 128 MiB limit, but its writes happen synchronously on the inference loop. Preserve its format and direct API for existing callers; add an owned queued wrapper for Lab/headless capture.
- Runtime emits `fast.started/finished` and local `runtime.epoch`; Deep emits started/response/decision/failure with captured snapshots. LMStudioFast records the exact rendered prompt. OMP records submitted prompt, configured role, visible session context and usage; it does not expose provider HTTP requests or reasoning. Preserve its 100 ms optional history-observation deadline.
- RuntimeWorker already polls Journal and status every 200 ms, owns all core objects, and emits copies. Extend this path instead of adding a second Runtime or Qt thread hierarchy.
- `window.py` has useful detail tabs, but a plain chat with a 5000-block cap, a growing QListWidget and current-only state. Offline trace load restores request rows, not the full transcript/context timeline.
- M4.3 initiative state is event-backed; the UI currently leaves it disabled. Journal proposals/closures plus actual character-origin turns provide the inspection source; do not create a parallel initiative state machine.
- Existing verifier scripts contain live provider/cache probes. Reuse them for targeted evidence, but do not import their CLI argument state into production modules or infer cache hits from TTFT.

One plan is appropriate: capture/replay, simulator and GUI are separately reviewable tasks but share the run format and are needed together for this milestone's usable deliverable. No general evaluation framework, memory subsystem, GUI rewrite, speculative scheduler or executable rebuild is required.

## File responsibilities

| Files | Responsibility |
|---|---|
| Modify `src/vtuber/tracing.py` | Existing immutable format plus bounded queued writer lifecycle |
| Modify `runtime/orchestrator.py`, `runtime/deep.py`, `minds/omp.py`, `minds/lmstudio.py` | Missing observational phases/metrics/context transitions; no decision-policy changes |
| Create `src/vtuber/lab/archive.py` | Run metadata, capture pump, read-only indexed replay and historical context lookup |
| Create `src/vtuber/lab/simulation.py` | Scenario/action validation, visible conversation boundary, simulation controller |
| Create `src/vtuber/lab/simulator.py`, `simulator.md` | Independent OMP user adapter and exact role instructions |
| Create `src/vtuber/lab/__init__.py`, `__main__.py` | Headless composition/CLI, without eager Qt/SDK imports |
| Create `src/vtuber/lab/scenarios/skin-creator.json` | Initial five-session life situation, private facts, corrections, pauses and criteria |
| Create `src/vtuber/lab/report.py` | Technical summary, evidence references and optional post-run subjective assessment |
| Modify `desktop/bridge.py`, `window.py`, `reader.py`; create `desktop/models.py` | Reuse worker/reader, paged conversation/timeline and historical details |
| Modify `desktop/__main__.py`, `pyproject.toml` | Lab naming, replay entry option, packaged role/scenario assets |
| Extend `tests/test_tracing.py`, `test_runtime_lifecycle.py`, `test_desktop.py`; create `tests/test_lab.py` | Focused persistence/privacy/concurrency/replay checks |
| Update README, scoped/root AGENTS, blueprint observability section; create `docs/M4_4_CONVERSATION_LAB.md` | Usage, boundaries, actual evidence and limitations |

## Task 1: Nonblocking, complete observational capture

**Files:** `src/vtuber/tracing.py`, `src/vtuber/runtime/{orchestrator,deep}.py`, `src/vtuber/minds/{omp,lmstudio}.py`, `tests/test_tracing.py`, `tests/test_runtime_lifecycle.py`.

**Interfaces:**
- Consume unchanged `TraceSink(kind: str, request_id: str, data: dict[str, object]) -> None`, `RuntimeOutput`, existing snapshots and diagnostics.
- Produce `QueuedTraceRecorder(root: Path, max_bytes: int = 128*1024*1024, on_record=None)` with compatible `path`, `error`, callable sink and `async aclose() -> None`.
- Sink freezes JSON-compatible values before returning, queues with `put_nowait`, and uses one owned writer thread. Queue limits: 256 records and 8 MiB pending payloads, maximum one record 2 MiB. Oversized records become omission markers rather than stopping unrelated capture. Queue overflow stops capture with an explicit error/gap count; disk failure and total cap stop it visibly. These are implementation bounds, not model-context limits.
- Existing TraceRecorder remains the disk serializer. Queued wrapper reserves bytes before enqueue, preserves order and drains accepted records on async close; an unresponsive filesystem never blocks the GUI event loop while cleanup waits. Completion signals fire only for persisted records and carry copies.
- Add `runtime.lifecycle`, `runtime.context`, `deep.phase`, `fast.progress` observation kinds. Each uses its real request/turn ID, or character ID for run-level state, and includes relevant event IDs/sequence/revision/epoch. Journal retains canonical initiative lifecycle events.

- [ ] **Step 1: Add the failing critical capture check.** In `test_tracing.py`, `test_queued_capture_is_immutable_bounded_and_off_loop` holds the writer with a threading Event, mutates an original nested payload after enqueue, fills the queue, and completes a fake Runtime Fast turn before releasing the writer. Assert immutable stored content, explicit overflow notice, bounded queue, one terminal, and a joined writer after release/close. Extend the disk-limit test for queued size/oversized omission and nonfatal write failure; retain path and interrupted-index tests.
- [ ] **Step 2: Run RED.** `python -m unittest discover -s tests -p test_tracing.py -v`; fail on the missing queued writer behavior.
- [ ] **Step 3: Implement the queued writer and observational additions.** Record startup snapshot before recovery and after it; local and public `apply_compaction` transitions; explicit cancellation/recovery/shutdown; Deep queued/analyzing/retry/terminal phases including retry number and reason. Existing `deep.decision` supplies every parsed operation and accepted/rejected/no-op reason. Emit runtime context snapshots at actual revision/epoch mutations, not only 200 ms polling. Never await or perform disk writes inside model loops/transactions.
- [ ] **Step 4: Capture streaming and metrics without per-token domain events.** Batch `fast.progress` observations at most once per 100 ms, including accumulated visible text length/partial text and turn ID; always retain final/cancelled partial output. Capture whitelisted provider usage counters when supplied, otherwise explicit null/unavailable. Preserve exact Fast prompt and OMP provenance/reasoning exclusion. Add lifecycle coverage to the existing trace correlation check, including an initiative cancellation and a public compaction transition. Check fake/core imports still work without Qt/SDK/tokenizers.
- [ ] **Step 5: Verify and checkpoint.** Run trace, Runtime lifecycle and OMP tests with stdlib discovery; `git diff --check`. Expected PASS; record changed contracts and results, no task commit.

## Task 2: Portable run archive and historical replay

**Files:** create `src/vtuber/lab/{__init__,archive}.py`, `tests/test_lab.py`; extend `src/vtuber/desktop/reader.py` only for archive reading helpers.

**Interfaces:**
- Produce `RunArchive.create(root: Path, config: Config, *, scenario: dict | None = None, seed: int | None = None) -> RunArchive`, allocating a unique directory and `runtime.sqlite3` path; never copies an existing user DB into a simulation.
- Produce `RunArchive.resume(path: Path) -> RunArchive` only for an explicitly requested stopped/interrupted simulation with a valid manifest and owned DB. Add a fresh `segments/run-*` capture directory and numbered session boundary, retain prior immutable segments and pending-work recovery evidence, and resume from the last completed public conversation. Reject a completed run, mismatched character/model configuration or an already-owned DB. Resume is explicit continuation, distinct from offline replay; a stale simulator action is never restored. RunReader merges segment indexes using manifest order and segment-local sequences.
- Archive has `path: Path`, `db: Path`, `trace: QueuedTraceRecorder`, `observe_output(output: RuntimeOutput) -> None`, `async capture(runtime: Runtime) -> None`, and `async close(status: str, reason: str | None = None) -> None`. Capture runs on the existing owner loop, polls Journal pages/status every 200 ms and flushes the final tail after Runtime close, before Journal disposal.
- Produce read-only `RunReader(path: Path)` with `page(kind: str, *, offset: int = 0, limit: int = 200) -> list[dict]`, `related(turn_id: str) -> list[dict]`, `context_at(sequence: int) -> dict`, and `summary() -> dict`. Categories are conversation/timeline/context; details retain source record paths. Build metadata/offset indexes once off the UI thread, not by rereading all payloads per selection.
- `run.json` schema_version 1 stores UTC start/end, status/reason, code SHA/dirty flag, allowlisted model/scenario settings, seed, real elapsed/declared virtual session gaps, capture bounds/gaps. Reuse trace `index.jsonl`/immutable payloads for transcript, simulator and observations. SQLite is authoritative for Liac; archived Journal envelopes are inspection records, never an alternative write path. No additional database.

- [ ] **Step 1: Write RED history/replay tests.** `test_context_at_turn_survives_correction_and_compaction` archives two different documents/epochs, including multiple changes between polls, then asserts old-turn lookup returns its exact captured values and later lookup returns the correction. `test_interrupted_and_legacy_run_are_read_only` opens a truncated run and an old index-only trace: assert unfinished labels, explicit missing transcript/context, traversal rejection and zero Runtime/provider calls. Test closure includes shutdown initiative cancellation and last terminal events. Run `python -m unittest discover -s tests -p test_lab.py -v`; expect missing archive API failure.

  Pin historical values directly, rather than testing the implementation's indexing algorithm:

  ```python
  self.assertEqual(reader.context_at(old_sequence)['markdown'], '# Project\nVersion 1')
  self.assertEqual(reader.context_at(new_sequence)['markdown'], '# Project\nVersion 2')
  self.assertEqual(reader.context_at(old_sequence)['epoch']['version'], old_epoch)
  self.assertEqual(reader.related(old_turn)[0]['turn_id'], old_turn)
  ```
- [ ] **Step 2: Implement archive capture and correlations.** Index immutable snapshots by domain sequence and trace sequence separately. A Fast turn's snapshot is exact; general context-at-time uses actual mutation observations, never current DB state. `related` maps input/turn → Fast → canonical evidence → zero or more Deep calls → proposals/initiative/context transitions, allowing many-to-many links and delayed Deep. Preserve session boundaries, simulated/manual origins and noncanonical cancelled partial output. When capture has gaps, mark uncertainty instead of carrying the last snapshot across an unknown interval as fact.
- [ ] **Step 3: Finish safe reading and persistence.** Keep readers independent of Qt, Runtime and providers. Reuse filename/path validation; reject symlink escapes and malformed manifests; bound preview reads before allocation. Journal snapshot/status polling remains owner-thread only. Drain archived output and final Journal tail before marking a run complete; interrupted archives remain viewable. Expose missing/capped observations in metadata and replay. Credentials and arbitrary environment/config dumps are excluded by allowlist.
- [ ] **Step 4: Verify and checkpoint.** Lab/trace tests PASS. Reopen a temporary fake run after all runtime objects are disposed and inspect transcript, related Deep decision and old context. `git diff --check`; no commit yet.

## Task 3: Independent human simulator and headless runner

**Files:** create `src/vtuber/lab/{simulation,simulator,__main__}.py`, `simulator.md`, `scenarios/skin-creator.json`; modify `pyproject.toml`; extend `tests/test_lab.py`.

**Interfaces:**
- Frozen `VisibleMessage(turn_id: str, role: str, text: str, origin: str, session: int)` contains only user text and completed public Liac speech; cancelled visible fragments carry an explicit interrupted marker and never become a completed assistant answer.
- Frozen `SimulationAction(kind: str, text: str = '', wait_seconds: float = 0, reason: str = '')`; allowed kinds `message`, `silence`, `end_session`, `finish`. Strict JSON v1 parser `parse_action(text: str) -> SimulationAction`: exact fields, nonempty message text, no unknown actions, finite 0–3600-second wait, no boolean numbers; max output 64 KiB. Silence requires a positive wait; no busy loops.
- `OMPUserSimulator(settings: OMPSettings, scenario: dict, *, trace: TraceSink | None = None)` owns a separate OMPTransport/data directory/session/role; `async next_action(history: tuple[VisibleMessage, ...], *, session: int, remaining_turns: int) -> SimulationAction`; `async close() -> None`. It never receives Runtime, Journal, RunArchive, DeepRequest, Markdown or a diagnostic callback. Use distinct simulator request IDs and trace kinds to distinguish OMP calls from Luna.
- `SimulationController(simulator: OMPUserSimulator, submit: Callable[[UserMessage], Awaitable[object]], *, character_id: str, trace: TraceSink | None = None)` exposes `async run(*, turns: int | None, duration_seconds: float | None) -> dict`, `observe(message: VisibleMessage) -> None`, `pause() -> None`, `resume() -> None`, `async stop() -> None`, `manual_input() -> None`, `status() -> dict`. At least one positive stop budget; if both, first reached wins. Turns count submitted simulated user messages; autonomous replies do not inflate progress. Duration uses real monotonic elapsed time, including pauses.
- CLI: `python -m vtuber.lab --scenario skin-creator --turns 12 --output-root .data/lab --simulator-model MODEL --omp-executable PATH --endpoint URL --model ID --tokenizer PATH [--duration-seconds N] [--seed N] [--enable-initiative] [--pause-scale N]`. Reuse Config/LMStudioSettings/OMPSettings and existing option names/defaults; `--pause-scale` finite positive, default 1, scales simulator waits only. Seed controls local scheduling choices, not remote deterministic inference.
- Explicit `--resume RUN_PATH` uses Task 2's resume API and recorded configuration, validating any supplied overrides before opening Runtime. The turn/duration budgets apply to the overall run, retaining prior counts/elapsed time. GUI offers Resume saved simulation separately from read-only Open run; both use this same continuation path.

- [ ] **Step 1: Add focused RED privacy/lifecycle checks.** `test_simulator_sees_only_public_conversation` puts sentinel secrets in Markdown, Deep proposals and diagnostic dictionaries and asserts none enter simulator prompt/history; private scenario facts appear only in simulator instructions until spoken. `test_manual_pause_stop_invalidate_inflight_action` holds a simulator call, sends manual input/pause/stop, releases a stale message result, and asserts no stale submit, no double submit on resume, and owned transport cleanup. Run Lab tests and observe RED.

  ```python
  self.assertNotIn('HIDDEN_LIAC_SENTINEL', captured_simulator_prompt)
  self.assertEqual(submitted_after_stale_result, [])
  self.assertTrue(simulator_closed)
  ```
- [ ] **Step 2: Implement scenario and adapter.** Five initial sessions: introduction, Skin Creator work, return, correction/pressure, ordinary conversation. Store persona/style, private facts, evolving project plans, possible life events, turn-range guidance and fact/correction criteria; no prewritten dialogue. Default long target 120 turns across five sessions, smoke target 12. Role asks for human behavior, occasional brief replies, changed topics and genuine silence, not perpetual questions. No tools or Liac internals. Give each session its own simulator OMP session, carry the visible transcript, keep one Liac DB across sessions. Cap submitted visible transcript to a documented 96 KiB recent window and label older omissions; scenario facts are simulator-private, not an alternate Liac memory.
- [ ] **Step 3: Implement controller on existing Runtime API.** Host owns `open_runtime`, output fan-out and archive; controller receives only submit callable and visible messages. Runtime.submit returns a Task or None: await the call, then await that returned Fast task when present, while processing public autonomous speech during pauses. Never await Luna to send normal input. Use an action-generation counter checked after every await to invalidate stale simulator work. Manual send pauses simulation before Runtime submission; Resume regenerates from current visible history. Pause suspends new simulator activity but keeps Liac initiative alive; Stop cancels only simulator work, while Runtime Stop closes everything. End-session records a boundary and waits without falsifying Journal timestamps. Drain active work and record unfinished Deep explicitly at the configured end/drain timeout (90 seconds), rather than hanging forever.
- [ ] **Step 4: Implement headless composition and packaging.** Allocate archive/DB and independent simulator/Luna data paths; enable the same capture flow as desktop. Ctrl+C stops controller and joins owned provider/writer work, preserving partial results. Package role/scenario assets. Record requested model vs actual model and clean errors without credentials. Validate all CLI budgets before inference. Use real sleep in production; deterministic tests inject an async wait callable into the controller only. Accelerated gaps are visibly labelled and never change Runtime clocks.
- [ ] **Step 5: Verify and checkpoint.** Lab tests PASS including malformed action/budget validation and no Qt imports. Run a 12-turn fake-host smoke using a deterministic simulator stub to establish mechanics only; real acceptance is Task 6. No task commit.

## Task 4: Evolve PySide6 into a usable live/replay Lab

**Files:** `src/vtuber/desktop/{window,bridge,reader,__main__}.py`, create `desktop/models.py`, extend `tests/test_desktop.py`.

**Interfaces:**
- Preserve existing worker command names; widen `RuntimeWorker.command(action: str, payload: object = '') -> None` with `simulation.start`, `simulation.pause`, `simulation.resume`, `simulation.stop`. Add copied `simulation_status` signal. Start payload contains validated scenario/budgets/model/pause-scale, never Qt objects. Worker creates the Task 3 controller on its existing loop.
- `ConversationModel` and `TimelineModel` subclass QAbstractListModel; consume immutable row dictionaries from Task 2, keyed by turn ID or trace sequence. Initial page 200; fetch older pages through TraceReader; live view retains a bounded 1000-row window while all persisted rows remain navigable. No live Journal or SQLite connection on the GUI thread.
- `Enable initiative` feeds Config at Runtime startup; settings are disabled while that Runtime runs. Simulation Start starts a fresh isolated Runtime/run; if manual Runtime is active, stop it asynchronously first, preserving its DB. Existing ordinary database path is never reused for a simulation.

- [ ] **Step 1: Write RED GUI integration checks.** Extend existing lifecycle test for simulation Start/Pause/Resume/Stop plus manual intervention. Add `test_paged_replay_and_stale_selection`: use a generated 10,000-row archive with a historical correction, select an early turn, switch selection while a reader is held, and assert the old completion cannot overwrite the new selection; fetching older pages recovers early speech/context. Open a saved interrupted run with providers unavailable: assert no Runtime start, correct origins/partials and unavailable detail labels. Run offscreen desktop tests, expect RED.
- [ ] **Step 2: Reuse window structure and worker.** Conversation center, Process Timeline left, Inspector right, compact collapsible Simulation controls. Use existing widgets and native styling; no web frontend or custom design system. Conversation distinguishes Real user / Simulated user / Liac reply / Liac initiative, with streaming, cancellation, session boundaries and pauses. Clicking a row selects linked processes, not just the nearest timestamp. Preserve user scroll position; streaming updates by turn ID rather than one unkeyed pending string. Render all untrusted content as plain text.
- [ ] **Step 3: Add live filters and historical detail.** Timeline filters Fast/Luna/Runtime/Context/Initiative/Simulator. Group detail tabs into Input / Prompt, Output / Proposals, Context / Diff, Metrics, Journal / Raw JSON. Context Timeline selects captured Markdown and epoch, displays Markdown unified diff separately from epoch changes, and links proposal sources and Runtime decisions. Show queued/analyzing/retry phases while work is running, and ready/deadline/claimed/closed initiative reasons. Keep exact Fast vs OMP session-view provenance explicit. Unknown metrics display unavailable; cost distinguishes local Fast, Luna and simulator and uses supplied provider cost only.
- [ ] **Step 4: Add controls/replay without blocking UI.** Simulation panel shows scenario, turns/duration, simulator model, Start/Pause/Resume/Stop, phase, progress, usage/cost and manual-intervention state. Open run supports new archives and old trace directories; optional desktop `--replay PATH` opens offline without inference. Load indexes/details in existing reader thread, batch worker notifications at 100–200 ms, cap previews at existing 200,000 characters. Surface capture limits/gaps persistently. Stop/close joins controller, Runtime, OMP and writer asynchronously; no QThread termination or synchronous model wait from widgets.
- [ ] **Step 5: Verify and checkpoint.** Desktop tests PASS with process exit 0, including existing teardown checks; core tests still run without Qt. Native Windows check follows in Task 6. No task commit.

## Task 5: Compact evidence-based run summaries

**Files:** create `src/vtuber/lab/report.py`, extend `lab/__main__.py`, `tests/test_lab.py`; use Task 4 existing detail panel for summary display.

**Interfaces:** `summarize_run(reader: RunReader) -> dict`; `async assess_run(reader: RunReader, settings: OMPSettings) -> dict`. Headless CLI `python -m vtuber.lab report RUN_PATH [--judge-model MODEL --omp-executable PATH]`; summary always works offline, judge runs only when requested. Save `summary.json` and optional `assessment.json` atomically in the ignored run directory.

- [ ] **Step 1: Add one summary fixture test.** `test_summary_counts_attempts_and_missing_metrics_honestly` provides repeated lifecycle observations, cancelled partial output, one no-op proposal, two Fast TTFTs and missing cost/KV counters. Assert distinct call/turn counts, nearest-rank p50/p95 with sample count, usage counted once per call, cancelled initiative separate from spoken, no-op separate from rejection, unavailable rather than zero unknown metrics. Fact criteria distinguish not elicited / observed correct / contradicted / unresolved using cited visible messages; a semantic verdict cannot be presented as a deterministic assertion. Run RED.
- [ ] **Step 2: Implement technical summary.** Count total real/simulated user turns and completed autonomous turns separately, Deep calls/retries, TTFT p50/p95, token/cost totals by actor with coverage, available KV counters with attribution, compactions, Deep lag max/final (sequence lag, not seconds), errors/rejections/no-ops/cancellations and initiative proposed/spoken/cancelled/expired. Derive from IDs and canonical terminal events; claimed is not spoken. Missing or capped evidence marks totals partial. No provider-cache claim from latency.
- [ ] **Step 3: Implement optional independent assessment.** Fresh tools-disabled OMP session sees only visible transcript plus criteria/scenario fact targets, never Luna's internal state. Report fact retention/corrections, repeated lines/jokes, excess questions, assistant-like behavior, initiative appropriateness and character continuity, each with cited turn IDs, examples and subjective label. Expose literal scenario checks separately from semantic judge ratings. Bound judge input to 384 KiB, label omitted turns and incomplete coverage; retain raw public-text response even if structured assessment is invalid. No judging during conversation and no model instructions tuned to satisfy the judge.
- [ ] **Step 4: Verify and checkpoint.** Lab summary fixture PASS; offline report of the fake smoke contains no fabricated provider usage. Manual inspection distinguishes technical counts, objective checks and subjective opinions. No commit yet.

## Task 6: Real provider/native acceptance, documentation and final commit

**Files:** create `docs/M4_4_CONVERSATION_LAB.md`; update `README.md`, `docs/DESKTOP_INSPECTOR.md`, relevant observability/milestone sections of `docs/PROJECT_BLUEPRINT.md`, root/scoped AGENTS and add concise `src/vtuber/lab/AGENTS.md`.

**Interfaces:** Use Tasks 1–5 as shipped. Keep all private transcripts, traces, databases, reports and screenshots under ignored `.data/lab/`; commit only sanitized documentation and synthetic test fixtures.

- [ ] **Step 1: Verify prerequisites and baseline.** Check current branch/base, interpreter/dependencies, existing localhost endpoints, loaded Nemotron ID, tokenizer parity and authenticated OMP via existing integration. Never download models or change shared LM Studio settings. Verify packaged role/scenario files through the project's existing build path. Record actual versions and unavailable providers; failures do not become fake success.
- [ ] **Step 2: Native manual conversation.** Launch updated source PySide6 Lab, initiative opt-in, real Nemotron/Luna. Send a fact, correction and conversational pause. During inference inspect the Fast exact prompt, Luna role/request/session view, live phases and one complete evidence→proposal→Runtime decision→context-diff chain. Inspect an autonomous opportunity if one occurs; silence remains a valid behavioral outcome. Save run and native UI evidence with actual IDs; do not copy private content into Git.
- [ ] **Step 3: Real 12-turn smoke.** Separate run DB, independent simulator OMP session/model, five-session scenario compressed in turn count but real Journal clock. Exercise Pause/Resume, manual intervention, real silence and Stop. Confirm no hidden-state leakage, trace links, Fast while Luna analyzes, distinct cost accounting, replay without providers and cleanup. If smoke fails, fix the owning cause before the long run.
- [ ] **Step 4: Real 120-turn run.** With successful smoke and available providers, use default real pauses (`--pause-scale 1`), five sessions and initiative enabled. Record actual elapsed wall time; a 120-turn run shorter than hours is not a multi-hour soak. Schedule genuine long session gaps in the scenario (initial experiments: 30–90-second ordinary waits and 10–15-minute inter-session gaps, editable before run and recorded); do not force 120 provider responses if the simulated human ends early. Save early termination, quota/provider errors and unnatural dialogue. Perform one controlled checkpoint restart between sessions using the same run's DB and a new capture segment, with an explicit resume manifest/segment boundary; never resume an interrupted simulator inference automatically. Verify no duplicated initiative, preserve cancelled work and distinguish restart recovery from offline replay.
- [ ] **Step 5: Inspect outcomes and required cases.** Reopen run offline in native PySide6; navigate early/middle/late turns, historical context, compaction and linked Fast/Luna/Simulator work. Record initiative/silence/correction/restart/concurrency observations. If real compaction did not occur, use a separately labelled pressure run with smaller valid context budget and ordinary generated conversation; do not fabricate a natural compaction event. Reuse existing serial cache verifier for available counters; overlapping/unattributable LM Studio log windows are unavailable. No global log collector service. Optional independent assessment follows only after completion and retains negative examples.
- [ ] **Step 6: Document actual scope and results.** Architecture, launch/headless/replay commands, controls and origins, exact vs unavailable prompt data, archive schema/privacy/caps, one sanitized full trace chain, run IDs/progress/duration/cost/metrics, behavior problems and limitations. State whether the multi-hour/120-turn target actually completed. Update blueprint with DECIDED tooling and EXPERIMENT timing/scenario choices, leaving cognitive semantics unchanged. Document source launcher usage; existing bundled executable is not rebuilt and must not be described as containing M4.4.
- [ ] **Step 7: Final checks and one review.** Run `python -m unittest discover -s tests -v`, existing `python scripts/verify_m2_luna.py --self-check`, `git diff --check`, `git status --short`; use the configured venv and `PYTHONPATH=src` on Windows. Inspect archive privacy/ignored paths and packaged assets. Perform one whole-branch review per chosen execution workflow, especially the five Review Focus items; reproduce/fix material findings, rerun affected checks. No automatic swarm or repeated review loop.
- [ ] **Step 8: Final commit.** Stage explicit implementation/docs/test paths only. Commit `feat: add conversation lab and long-running simulation` with author `softsock <109231668+softsock@users.noreply.github.com>` and required coauthor trailer. Verify commit identity, parent/base and clean tree. No push/PR. Report actual checks, saved evidence, incomplete runs and risks.

## Self-review and handoff

Coverage: spec §§1–2 → Tasks 1–2; §3 → Task 4; §§4–5 → Task 3 and live Task 6; §6 → Tasks 1/3/4; §7 → Tasks 1–2/4; §8 → Task 5; §9 → all interfaces/global constraints; §§10–11/DoD → Task 6. All five Review Focus cases have named checks. Interfaces use the same IDs, archive reader and controller across headless/Qt; only hosts access Runtime state. No cognitive feature, second domain store or general evaluation framework is added.

Execution method is not yet selected for M4.4. Recommend **Native**: tasks share the archive/controller interfaces closely, existing code already supplies most primitives, and one final independent review concentrates cost on cross-boundary failures. Plan review and method selection precede implementation as required by writing-plans. The original requirement for a separate branch and one final commit is preserved.
