# M6.0 Luna Single Mind Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that one GPT-6 Luna model with `low` reasoning can drive Liac's first text-only `speak` / `stay_silent` turn through the existing M5.0 Perception Bus and Journal, with real tool-stream latency measured and without the old Bolt/Deep split.

**Architecture:** First run a standalone, *real provider* transport probe. If successful, use one tiny Node/`pi-ai` bridge to stream tool-call data to Python, one small SingleMind coordinator, existing atomic local perception ingestion and SQLite Journal; keep the old Runtime executable. The initial context is deliberately small. M4.8 compaction adaptation, Wake/Attention, VLM and TTS are separate subsequent milestones.

**Tech Stack:** Python 3.12+, `asyncio`, `dataclasses`, `unittest`, existing SQLite Journal/PerceptionBus, Node.js (existing user installation) and a **pinned** `@oh-my-pi/pi-ai` version **only in the opt-in Luna bridge**. No additional Python framework.

**Spec:** [Current M6 Blueprint](../../PROJECT_BLUEPRINT.md), particularly ``2–8, 12–14`. Historical behavior: [M5.0 Perception Bus](../../M5_0_PERCEPTION_BUS.md). The Blueprint is the reviewed design/spec for this milestone; do not create a redundant new architecture document.

## Global Constraints

- **Correct repository:** `SheetHappiness/liac-ai`, branch `codex/m6-0-single-mind`, based on `main` at commit `fa7c5d70ccf40a383958da9b51c6be06ef76eea3`. `softsock/liac-ai` is the old system/backup and must not change.
- **Status:** M6 is an EXPERIMENT. Existing M5.0 tests were 164/165 at last recorded run, with the pre-existing `MainWindow.context` desktop failure. Re-measure locally, do not call this a pass if a new failure appears.
- **Minimal scope:** local single-author `source='local'`, `conversation_key='local'` chat only; one cognitive model, one tool choice per turn; no Deep worker in M6; no VLM, external action, STT, TTS, Attention/Live State or history compaction migration.
- **Model:** `openai-codex/gpt-6-luna` requested with `low`; test `off` only if the *live model/provider* advertises it. Do not silently substitute a different model or reasoning setting.
- **Transport decision gate:** `@oh-my-pi/pi-ai` (not the coding-agent harness) is a candidate, not a proven provider. **Stop** after Task 1 if real OAuth/model access, tool streaming or prompt control cannot be established; document results rather than build an unverified bridge. OMP RPC is an alternative to investigate separately, not a silent fallback.
- **Prompt:** `src/vtuber/minds/character.md` is the original tiny character identity; add one concise M6 operating prompt. Do **not** reuse `deep.md`, which tells Luna to manage Bolt's memory.
- **Data:** preserve M5.0 `perception.received`, `user.message.completed`, deterministic IDs and Journal transaction semantics. No SQL/schema migration; use a new ignored `.data/m6-0.sqlite3` database for first live trials.
- **Implementation:** Python remains the orchestration owner; optional Node bridge handles provider/OAuth/stream only. Never copy credentials into the repo, traces, stdout or test fixtures.
- **Boundaries:** trust only completed/parsed tool calls for terminal actions; do not execute partial JSON. One owner loop, explicit cancellation, bounded message payload. Streaming text preview is *ephemeral*, not proof that audio was heard.
- **Style:** keep the code small and follow the existing repo layout/`AGENTS.md`. Prefer stdlib and direct methods to new frameworks or duplicate validation. New comments/application messages in English.
- **Commits:** each implementation commit contains `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`. No GPT-6 Astra subagents, no automatic PR/merge/deployment and no Loonyball changes.
- **No invented success:** test code offline as needed; real Luna/`off` support, usage limits, cache hits and timings must be separately observed in the user's authenticated environment.

## Review Focus

1. **OAuth/model mismatch:** a generic `pi-ai` package install does not prove this account can call `gpt-6-luna`; the real probe must establish exact model, reasoning and tool streaming in Task 1.
2. **Private data on wire:** requests/credential refresh or debug payloads must never write access tokens and full raw private prompts to ordinary logs; Task 1/2 tests and manual inspection.
3. **Split/cancelled speech delta:** partial `speak` JSON, UTF-8 escapes, tool-call interleaving and cancellation cannot appear as committed speech; Task 2 and 4 tests.
4. **Atomic input/replay:** extracting ingestion must not duplicate raw events or cause the old M5.0 Runtime to stop generating; Task 3 and 4 tests.
5. **Crash after visible output:** terminal event may be absent after a crash, but startup must close the input as cancelled and never automatically regenerate or assert the partial text was fully delivered; Task 4 and 5 tests.

---

## Source map and decisions

| File | Responsibility |
| --- | --- |
| `tools/luna-bridge/package.json`, `package-lock.json` | Isolated pinned `@oh-my-pi/pi-ai` dependency; no Node requirement for fake mode |
| `tools/luna-bridge/probe.mjs` | One-off real Codex auth/model/reasoning/tool-stream capability probe; redacted metrics only |
| `tools/luna-bridge/bridge.mjs` | One persistent JSONL subprocess: one in-flight Luna request, streamed tool deltas and final completed call |
| `tools/luna-bridge/speak_stream.mjs` | Small incremental extractor for the `message` string in `speak` tool-call argument fragments |
| `tools/luna-bridge/speak_stream.test.mjs` | Node tests of incomplete/escaped/split JSON and deliberate silence |
| `src/vtuber/contracts/mind.py` | `MindDecision` and minimal `SingleMindPort`/callback types; stdlib only |
| `src/vtuber/minds/luna_stream.py` | Python-owned subprocess lifecycle and JSONL decoder; no runtime or SQLite imports |
| `tests/test_luna_stream.py` | Fake bridge, startup, streamed deltas, complete tool calls, cancellation and errors |
| `src/vtuber/runtime/journal.py` | Extract existing M5.0 atomic local batch ingestion into reusable narrow method |
| `src/vtuber/runtime/orchestrator.py` | Existing Fast/Deep Runtime delegates to extracted ingestion, with no behavioral change |
| `src/vtuber/context.py` | **Do not change old `ContextCompiler` yet**; separate M6 projection below |
| `src/vtuber/minds/m6_context.py` | Small deterministic M6 prompt/history projection, including completed tool-call replay |
| `tests/test_m6_context.py` | Legacy messages, complete `speak`/silence wire replay, no duplicate current input |
| `src/vtuber/runtime/single_mind.py` | New opt-in M6 coordinator, one active character turn, Journal terminal events |
| `tests/test_single_mind.py` | One batch/one turn, ambient silence, retry/restart, cancellation, no Deep worker |
| `src/vtuber/m6.py`, `tests/test_m6_cli.py` | Minimal opt-in text-only console harness; does not modify existing `vtuber.cli` |
| `docs/M6_0_SINGLE_MIND.md` | Actual offline/live test evidence, transport decision, known limitations |

**Existing exact APIs to reuse:**
- `PerceptionBus.publish(Perception)`, `drain() -> PerceptionBatch | None`, `close()`.
- `Journal.append_many(tuple[Event, ...])`, `get(event_id)`, `recent_dialogue(character_id, limit=20)`, `unfinished_inputs(character_id)`.
- `Runtime.submit_perceptions(batch)` currently builds its canonical input **and** starts old Fast under `_input_lock`; do **not** call this from new SingleMind or it will start Bolt.
- `RuntimeOutput` and `OutputSink` already report start, delta, complete/cancel/failure. `character.reply.completed` is already a canonical terminal event.
- Bea reference: [Consciousness](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core/consciousness.py), [incremental tool arguments](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core/agent/streaming.py), [tool-call replay](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core/mind/single_context.py). **Adapt behavior; do not port its entire framework.** Preserve MIT notices on any substantial copied source.

### Task 1: Real Luna transport capability gate

**Files:** Create `tools/luna-bridge/package.json`, `package-lock.json`, `probe.mjs`; later document probe results in `docs/M6_0_SINGLE_MIND.md`.

**Interfaces:** CLI `node tools/luna-bridge/probe.mjs --list`, `--login`, `--reasoning low` and optionally `--reasoning off`. Structured local report: selected provider/model, supported reasoning levels if discoverable, first event/first tool-delta/final elapsed ms, final tool name, usage if exposed; **never** tokens or raw private prompt.

- [x] **Step 1: Create the isolated dependency and probe scaffold.** Pin a released `@oh-my-pi/pi-ai` version exactly in `package.json` plus lockfile. Document the version actually installed. Probe should use the library's supported `openai-codex` model/OAuth APIs, not OMP internal credential parsing or an unofficial HTTP endpoint. Interactive login stores secrets only under ignored `.data/m6-auth/`.
- [x] **Step 2: Verify locally without credentials.** Run `node --check tools/luna-bridge/probe.mjs` and `node tools/luna-bridge/probe.mjs --list`. Missing `gpt-6-luna` or credentials must produce a clear diagnostic, never an invented model substitution.
- [x] **Step 3: Run the **real, authenticated** probe on the target machine.** With a deliberately non-sensitive example and two tool schemas (`speak(message: string)`, `stay_silent()`), verify model ID, `low` acceptance, `toolcall_delta` delivery, final complete tool-call arguments and request/prompt shaping. The library's `onPayload` hook may be inspected privately/redacted to check extra prompt overhead; do not log credentials.
- [x] **Step 4: Check `off` only if advertised** by the real provider/model. Compare at least five short matched `low` trials and, if supported, five `off` trials. Record median first-tool-delta, completed duration, whether a usable `speak` fragment appeared and failures. Record `off unavailable` rather than faking support.
- [x] **Step 5: Decision gate.** **GO** only if the exact Luna route with acceptable prompt control and streamed tool argument deltas works. **NO-GO** → document failure and stop before Task 2; a separate review may choose OMP RPC, but the execution must not silently switch transports. Commit probe/lock/evidence as `test: verify direct Luna transport capabilities` with the required trailer.

### Task 2: Narrow streaming bridge, not a coding agent

**Files:** Create `tools/luna-bridge/bridge.mjs`, `speak_stream.mjs`, `speak_stream.test.mjs`, `src/vtuber/contracts/mind.py`, `src/vtuber/minds/luna_stream.py`, `tests/test_luna_stream.py`.

**Interfaces:**
- `@dataclass(frozen=True) class MindDecision` in `contracts/mind.py`: fields `action: Literal['speak','stay_silent']`, `message: str = ''`, `tool_call_id: str = ''`, `usage: dict[str, int] | None = None`. Speech requires a nonempty message; silence must not carry a spoken message.
- `SingleMindPort.generate(messages: tuple[dict[str, object], ...], *, on_speak_delta: Callable[[str], None] | None = None) -> Awaitable[MindDecision]`. Only one complete model choice per turn in M6.0.
- JSONL host → bridge: `{"type":"turn","id":"...","system":"...","messages":[...],"reasoning":"low"}`; `{"type":"cancel","id":"..."}`; `{"type":"shutdown"}`. Bridge owns the fixed two-tool schema, provider and auth. M6 controls only system and message data, not raw auth.
- JSONL bridge → host: `{"type":"speak_delta","id":"...","text":"..."}` for **provisional** text; `{"type":"result","id":"...","action":"speak","message":"...","tool_call_id":"...","usage":{...}}` or `stay_silent`; `{"type":"error","id":"...","kind":"..."}`. One terminal frame per ID. No credentials, reasoning text or raw provider payload in frames.

- [x] **Step 1: Write RED Python tests** `test_fake_bridge_speak_and_silence`, `test_bridge_error_is_visible`, `test_cancel_stops_deltas`, `test_close_joins_owned_process`. Use a tiny Python JSONL fixture instead of importing Node or requiring credentials in `unittest`. Run `python -m unittest test_luna_stream -v` and observe expected missing-interface failures.
- [x] **Step 2: Write RED Node parser tests** for `speak_stream.mjs`: split `"message"` across JSON chunks; escaped quotes/backslashes; Unicode surrogate pairs; more than one tool-call index; no text emitted for `stay_silent`; malformed partial argument never treated as a completed action.
- [x] **Step 3: Implement small, scoped components.** Bridge: one `AbortController` per active turn and one output line per event; no filesystem tools, coding-agent session, auto-tools or agent loop. `speak_stream` only extracts decoded `message` from the matching `speak` argument stream, inspired by Bea's tested parser. Host: one `asyncio.create_subprocess_exec` owner, read/write JSONL, cancellation → `cancel`/abort, bounded teardown; validate a **complete** final call before returning `MindDecision`. No generic multiprocess supervisor or retry ladder.
- [x] **Step 4: Run GREEN:** `python -m unittest test_luna_stream -v`; `node --test tools/luna-bridge/speak_stream.test.mjs`; `node --check tools/luna-bridge/bridge.mjs`. Record the difference between provisional streamed words and completed authoritative tool calls.
- [x] **Step 5: Commit** as `feat: stream minimal Luna tool decisions` with trailer.

### Task 3: Reuse durable ingestion and build tool-aware context

**Files:** Modify `src/vtuber/runtime/journal.py` and `src/vtuber/runtime/orchestrator.py` minimally; create `src/vtuber/minds/m6_context.py` and `tests/test_m6_context.py`; extend `tests/test_perception_runtime.py` only for an actual M5.0 regression.

**Interfaces:**
- `Journal.accept_local_perceptions(character_id: str, batch: PerceptionBatch) -> UserMessage | None`: move the existing atomic raw-input/canonical-group logic out of `Runtime.submit_perceptions` into a single short Journal transaction. Return the **new** canonical message, or `None` if ambient-only or already persisted. Invalid direct route/author combinations fail **before writes**. Existing Runtime consumes the result and starts Fast exactly as before. No new SQL schema.
- `build_m6_messages(identity: str, dialogue: tuple[Event, ...]) -> tuple[dict[str, object], ...]`. Deterministic context construction using already-committed `Journal.recent_dialogue(..., limit=40)`; include the current newly accepted user message **once**.
- For M6 terminal `character.reply.completed` add payload fields `action='speak'|'stay_silent'`, `tool_call_id` and `text` (empty for silence); project M6 speech as an assistant tool call + successful tool-result message. **Legacy completed replies without `action` remain legacy assistant text**, not falsely invented tool calls. Cancelled/failed events do not become completed speech.

- [x] **Step 1: Add RED tests** `test_existing_m5_ingestion_unchanged`, `test_m6_tool_replay_uses_stable_call_id`, `test_stay_silent_replay`, `test_legacy_reply_remains_plain_text`, `test_current_user_message_only_once`. Run `python -m unittest test_m6_context test_perception_runtime -v`.
- [x] **Step 2: Extract only the shared atomic ingestion** from the old Runtime into Journal; do not redesign Journal transactions. Rewire old `Runtime.submit_perceptions` to reuse it under its existing input lock. Preserve the order/raw event IDs and partial replay semantics.
- [x] **Step 3: Add M6 context projection** without editing the legacy `ContextCompiler` or M4.8 schema. Keep persona+operating instructions short and model-owned. Do not use `deep.md`; do not insert hidden reasoning. The output must match the chosen `pi-ai` tool-call history format from Task 1.
- [x] **Step 4: Run GREEN:** `python -m unittest test_m6_context test_perception_runtime test_context test_deep -v`. Verify that M5.0 still produces a Fast turn for new local input.
- [x] **Step 5: Commit** as `refactor: share perception ingestion and replay Luna actions` with trailer.

### Task 4: One SingleMindRuntime on the existing event loop

**Files:** Create `src/vtuber/runtime/single_mind.py` and `tests/test_single_mind.py`; use the `MindDecision` and `SingleMindPort` from Task 2 and `Journal.accept_local_perceptions` from Task 3.

**Interfaces:**
- `SingleMindRuntime(character_id: str, journal: Journal, mind: SingleMindPort, output: OutputSink, *, identity: str)`.
- `async start() -> None`, `async submit_perceptions(batch: PerceptionBatch) -> asyncio.Task[None] | None`, `async close() -> None`. Only one active visible generation; own the task and input lock; no Deep worker or legacy Initiative.
- Durable IDs reuse M5.0 conventions: `reply_started_{canonical_input.event_id}` and `reply_terminal_{canonical_input.event_id}`. Terminal reply payload contains `text`, `action` and `tool_call_id` on success, or existing cancelled/failed event kinds with reason. New database for M6 live smoke.

- [x] **Step 1: Add RED `IsolatedAsyncioTestCase` tests** `test_direct_burst_starts_one_luna_turn`, `test_ambient_only_no_inference`, `test_replay_no_second_speech`, `test_silence_is_completed_without_text`, `test_superseded_turn_cannot_emit_late_text`, `test_restart_closes_unfinished_without_regeneration`, `test_only_complete_tool_call_commits`. Use a scripted fake `SingleMindPort` and real temporary SQLite.
- [x] **Step 2: Implement the coordinator.** Ingress happens inside the owner lock; persist before starting inference; create a frozen read of canonical dialogue; no model call for ambient-only input. Emit `RuntimeOutput(kind='reply.started', ...)`, provisional `reply.delta` for already decoded `speak` fragments, and one terminal notification. Ignore/cancel deltas after supersession. Complete authoritative `speak` or `stay_silent` results only after bridge final validation.
- [x] **Step 3: Reuse existing restart semantics.** At startup mark persisted-but-unterminated user inputs `character.reply.cancelled` with `process_restarted`. **Never auto-regenerate** a turn that may have already produced visible output. Do not report partial text as fully delivered. Prevent duplicate terminal IDs.
- [x] **Step 4: Run GREEN:** `python -m unittest test_single_mind test_m6_context test_perception_runtime test_runtime_lifecycle -v`. Inspect transaction ordering and cancellation in a real SQLite temp file.
- [x] **Step 5: Commit** as `feat: run one Luna cognitive turn per local batch` with trailer.

### Task 5: Opt-in CLI proof, evidence and final review

**Files:** Create `src/vtuber/m6.py`, `tests/test_m6_cli.py` and `docs/M6_0_SINGLE_MIND.md`; optionally a one-line reference in `README.md`. **Do not** alter legacy `vtuber.cli` flags or default runtime.

**Interfaces:**
- `python -m vtuber.m6 --backend fake --db .data/m6-0.sqlite3` and `--backend luna` use the same SingleMindRuntime and existing `PerceptionBus`. `--reasoning low` is the explicit real default; `off` is available only when the Task 1 probe confirmed support.
- Local text messages are published as `Perception(kind='chat', source='local', conversation_key='local', delivery='direct', ...)`. A background drain task consumes settled batches while the stdin reader continues, allowing a later user turn to supersede an active generation. Shut down by closing the Bus and joining owned tasks.
- CLI renders `reply.delta` as **provisional text**, `reply.completed` as final, and explicit silence as no spoken line; no audio claim.

- [x] **Step 1: Add RED CLI tests** `test_fake_console_burst_one_reply`, `test_quit_drains_then_closes`, `test_ambient_does_not_start_luna` (the latter may directly call Runtime), plus `test_legacy_cli_unchanged` when relevant. Use monkey-patched input lines and fake adapter, no Node credentials in CI.
- [x] **Step 2: Implement only the new optional M6 CLI** by reusing `vtuber.cli.input_lines`; do not redesign stdin or add a generic service framework. Let fake mode work with no npm install, OAuth or LM Studio.
- [x] **Step 3: Run offline verification** on the user's worktree:
  - `$env:PYTHONPATH='src;tests;vendor/omp-rpc/src'` (PowerShell).
  - `python -m unittest test_luna_stream test_m6_context test_single_mind test_m6_cli test_perception_runtime -v`.
  - `python -m unittest discover -s tests -v`.
  - `python -m vtuber.m6 --backend fake --db .data/m6-fake.sqlite3`, type two quick lines and `/quit`.
  - `git diff --check`, `git status --short`.
- [x] **Step 4: Run real Luna acceptance**, **only in the user's authenticated environment**. Send 5 short direct prompts and 2 deliberate silence scenarios; measure p50/p95 where sample counts permit, first `toolcall_delta`/first decoded `speak` fragment/full response, accepted model and reasoning, failures/usage. Try `off` only if advertised; run the same prompts and compare behavior. Do not claim TTS/first-audio latency. Use no personal transcript in committed files.
- [x] **Step 5: Write `docs/M6_0_SINGLE_MIND.md`** with the tested versions/commands, actual observations, old baseline failure, private-data safeguards and explicit **not yet implemented** list: Attention/Wake, Live State, VLM, M4.8 adaptation, TTS, actions. Note the limitations of the small last-40-event context and separate M6 scratch database.
- [x] **Step 6: Commit** as `docs: verify M6 single-mind text prototype` with trailer. Request one independent review of the branch for real regressions and clear stop/go recommendation. **No PR, merge, deployment or changes to `softsock/liac-ai`** without a new request.

## Acceptance checklist

- [x] Real `openai-codex/gpt-6-luna` with `low` returns a real `speak` tool call; provider-facing prompt and streaming capability measured, not assumed.
- [x] Optional `off` is either tested on the *exact route* or explicitly marked unavailable.
- [x] Fake and real (if access works) use the **same** SingleMind protocol and Journal ingestion.
- [x] A direct burst produces one canonical user input and at most one spoken decision; ambient/noise stays silent.
- [x] Tool-call history preserves original action identity; replay never invents executed speech.
- [x] Cancellation/restart cannot produce a second committed reply or a stale visible delta.
- [x] M5.0 perception and Runtime regression tests pass. The full suite retains the measured `MainWindow.context` baseline error.
- [x] Real timing and usage are recorded separately from offline fake tests; **no TTS or VLM claim**.

## Deliberate exclusions and next step

M6.0 is **not** the full Bea-like system. Proceed to **M6.1 – Wake, Attention, one-context Hot/Cold and Live State** only after a clean text-only Luna turn exists. M6.2 is VLM; M6.3 is streaming TTS and first-audio latency; M6.4 is an evidence-based keep/revert decision followed by external actions.

**Execution handoff:** Read this plan and the Blueprint first. The earliest meaningful decision is the real provider probe. If that fails, stop and report rather than writing speculative production code. For implementation, **Native** is a reasonable default because the bridge, Journal projection and runtime share closely coupled interfaces; a fresh whole-branch reviewer should assess it afterward.
