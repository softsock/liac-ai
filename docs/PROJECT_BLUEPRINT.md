# PROJECT BLUEPRINT – Liac Single Mind

> **Status:** M6 Single Mind is an **EXPERIMENT**. It is a target design, **not** an implemented feature. M0–M5.0 remains the verified legacy baseline.
> **Updated:** 2026-11-18. **Version:** 0.2.
> **Active development repository (new Single Mind):** [`SheetHappiness/liac-ai`](https://github.com/SheetHappiness/liac-ai). **Legacy system / backup:** [`softsock/liac-ai`](https://github.com/softsock/liac-ai).
> **Shared M5.0 starting point:** [`7510227`](https://github.com/SheetHappiness/liac-ai/commit/7510227dcb21212c607532150b864ff7757476ce), including M5.0. **Reference:** [ProjectBEA `f2186fc`](https://github.com/emqnuele/projectBEA/tree/f2186fc647db3f9ae65e6463b9f82c882bdca68b).

This is the **target architecture** for `SheetHappiness/liac-ai`, not an assertion that its current code has already changed. Legacy Fast/Deep decisions are superseded *for M6 design*, but remain documented in the [old Blueprint](https://github.com/softsock/liac-ai/blob/7510227dcb21212c607532150b864ff7757476ce/docs/PROJECT_BLUEPRINT.md) and individual implementation reports. Do not treat old decisions about Bolt, OMP Deep or initiative as requirements for M6.

**Status vocabulary:** `IMPLEMENTED` – verified in repository; `DECIDED` – architectural direction; `EXPERIMENT` – needs evidence; `FUTURE` – do not implement yet. Agents should read root and scoped `AGENTS.md`, then only relevant Blueprint sections.

## 1. Purpose and character

**DECIDED:** Liac is a persistent, entertaining, character-first virtual person. The objective is believable continuity, contextual reactions, appropriate silence and eventual control of a limited set of permitted tools – not a general-purpose assistant.

- **One speaking mind.** GPT-6 Luna is Liac, owns character, speech, reactions, preferences and decisions. Bolt is not retained as a speech renderer or downstream personality model.
- **One shared cognitive context.** No hidden Luna director sending behavioral commands to another LLM.
- **Specialized VLM/STT/TTS are allowed.** They are senses and expression, not competing character minds.
- **Memory is experience, not a screenplay.** No `compose_beat` scheduler, forced jokes, artificial emotional directions or mandatory initiative engine.
- **Backend first.** Loonyball/avatar, Twitch, Discord, screen capture, speech and game integrations should be adapters, not dependencies of the cognitive core.

Quality must be demonstrated in live multi-turn behavior and real latency measurements. Attractive architecture alone is not acceptance.

## 2. Decisions

| ID | Decision | Status |
| --- | --- | --- |
| M6-01 | Single GPT-6 Luna cognitive actor; no Bolt/Fast + Luna/Deep split | **EXPERIMENT** |
| M6-02 | Try reasoning `low` first, then `off`/`none` only if the selected model and route support it | **EXPERIMENT** |
| M6-03 | Preserve M5.0 Perception Bus and SQLite Journal as the foundation | **DECIDED** |
| M6-04 | One serialized active cognitive turn, bounded tool steps | **DECIDED** |
| M6-05 | Separate **Wake** (should Luna run?) from **Attention** (what is important?) | **DECIDED** |
| M6-06 | Explicit `speak` / `stay_silent` tools; actions only through Runtime | **EXPERIMENT** |
| M6-07 | Replay completed speech as tool calls and outcomes, not plain assistant text | **DECIDED** |
| M6-08 | Adapt M4.8 Cold/Hot safety without copying Bea's separate storage/window system | **DECIDED** |
| M6-09 | Prefer minimal streaming transport with explicit prompt control | **EXPERIMENT** |
| M6-10 | Perception → Attention → VLM first, then TTS and real first-audio benchmark | **DECIDED** |
| M6-11 | Keep the code and checks as small as practical | **DECIDED** |

### 2.1 Minimalism and essential checks [DECIDED]

**Prefer the shortest comprehensible implementation over defensive architecture.** Reuse stdlib, existing project modules and existing SQLite; introduce a new abstraction only when two actual consumers or an unavoidable boundary justify it.

Do **not** add redundant `isinstance` checks to already validated internal dataclasses, multiple validation layers for the same value, speculative format migration, generic plugin/agent frameworks, needless retries, elaborate policy engines, future-proof configuration knobs or tests solely to raise coverage.

**Keep the few checks that prevent real harm:**

- **Data integrity:** atomic Journal writes; stable IDs; no duplicate speech/action on retry or restart.
- **Cancellation and ordering:** stale turns, results and audio cannot overtake a newer active turn.
- **Untrusted effects:** verify permission, destination and necessary tool arguments before real external actions or cloud disclosure.
- **Bounded work:** prevent unbounded sensor, audio, image and event backlogs; close owned tasks correctly.
- **Context:** don't split raw Hot turns; don't let a late summary replace newer history.

When an edge case is merely hypothetical and cannot break these invariants, don't add a guard for it. Record and test **observed failures**, not every imaginable state. If a milestone needs many layers to work, reduce its scope.

**Not needed now:** Dream Engine, mood state machine, vector DB, universal SkillRegistry, multi-agent coordinator, large dashboard, distributed services, arbitrary desktop execution, custom model orchestration framework.

## 3. Target architecture

```text
Local chat / future voice-STT, window-VLM, game, Discord
                        |
                  PerceptionBus
             quiet-gap batching / dedupe
                        |
                 SQLite Journal
                 canonical events
                        |
               Wake + Attention
           small deterministic policy
                        |
                  Context Builder
        identity + history + memory + live state
                        |
                 GPT-6 Luna LOW
                   SINGLE MIND
                        |
               speak / silence / tools
                        |
             Runtime validates effects
                        |
        text / future streaming TTS / avatar
```

Runtime owns order, transport, action execution and persistence; Luna owns **what** to say and **whether** to say it. There is one active *character decision loop*, not necessarily one process: a specialized VLM or TTS may run independently.

Maintenance may happen asynchronously only if it does not stall the live turn. Do not create a background cognition service preemptively. The existing data flow should remain inspectable using a single Journal and simple tracing.

## 4. Existing foundations and migration boundary

**IMPLEMENTED M5.0:**

- `contracts/perception.py` – frozen typed `Perception` / `PerceptionBatch`, stable IDs, source, author, timestamps, conversation key and delivery.
- `runtime/perception_bus.py` – FIFO same-key batching, monotonic ingress times, quiet gap, hard maximum window, pending dedupe, explicit overload, cancellation-safe drain.
- `runtime/journal.py` – canonical SQLite events; transactional local direct input; idempotent replay/restart; provenance of raw inputs.
- M4.8 – frozen in-flight Fast snapshot, whole-turn Cold/Hot boundary, atomic Epoch update, separate emergency fallback and recovery.
- M5.0 – ambient audit and noise silence; Deep backlog fix; offline regression suite.

**Not implemented:** a one-model Consciousness loop; live M5.0 end-to-end acceptance; automatic CLI/desktop batching; ambient projection to model context; VLM; TTS. Existing `direct` routing supports only one local author with `source='local'` and `conversation_key='local'`.

[Current Perception Bus report](M5_0_PERCEPTION_BUS.md) · [M4.8 evidence](M4_8_CONTEXT_HANDOFF.md).

Keep working foundations, but do not contort the M6 single-mind design to preserve old Deep result schemas, Luna-as-curator instructions or legacy initiative. Implement M6 on an isolated branch of `SheetHappiness/liac-ai`; retain `softsock/liac-ai` unchanged as the legacy comparison.

## 5. Perception and Attention

> **M6.1 EXPERIMENT (2026-11-18)** implements direct-only Wake, bounded local Live State, whole-turn replay, and a read-only Runtime snapshot. A short GPT-6 Luna Low run verified scene use and replay after a scene change. See [M6.1 results](M6_1_ATTENTION_LIVE_STATE.md).

### 5.1 Perception [KEEP M5.0]

Current **EXPERIMENT** defaults: `live_gap=0.30s`, `text_gap=0.75s`, `max_window=2.0s`, `max_pending=256`. These are scheduling choices, not latency promises.

- Retain original source input ID, timestamp, author and route; **ingress** order, not sender timestamp, establishes order.
- Direct messages are a clear response opportunity; ambient events may inform context; noise is ignored.
- A group of closely arriving messages is one cognitive opportunity, while each raw message remains individually auditable.
- Bus acceptance is not durable: Journal commit is. A consumer retains a drained batch until Runtime accepts it.
- One identity does not imply permission to leak one private channel into another.

### 5.2 Wake [NEW M6.1]

ProjectBEA's attention layer *ranks* every meaningful batch; it does not by itself prevent cloud-model inference on each significant update. For Luna we need a tiny second decision:

`wake(batch, recent_activity, current_state) -> bool`

First rules: direct addressed input wakes; repeated image/game state and periodic heartbeats do not; exceptional high-salience events can wake with a cooldown. Do not wake Luna just because a sensor polled. Do not use a second LLM to decide when to call the first.

### 5.3 Attention [NEW M6.1]

`annotate(batch) -> priority-ordered observations` should be pure/deterministic where possible. Direct address and relevant follow-up rank first. Other meaningful perceptions rank by change, salience, recency and simple cooldown. Attention does not author jokes, emotions or opinions.

**Luna may choose to stay silent even after a wake.** The wake gate controls cost and scheduling; the model controls the response.

### 5.4 Live State [NEW M6.1]

Volatile values (current window, room, game position, visual scene) **replace** their prior value and expire. A meaningful transition is an event; a repeated snapshot is state. Do not append every sampled snapshot to the long-term model history. Put a short bounded state block in the next frame, without altering an already running frame.

## 6. Single Mind turn lifecycle [NEW M6.0]

Implement one small `SingleMind`-like coordinator; do not copy Bea's entire `Consciousness` class.

1. Receive one settled batch and commit accepted inputs through the existing Journal.
2. Apply Wake/Attention; ambient-only non-waking input may update live state without inference.
3. Freeze a frame: static identity, canonical dialogue, relevant context, live state, current perceptions and their routes.
4. Call Luna through a narrow streaming transport. Model plain text is **not audible speech**. Only `speak(message)` is speech; `stay_silent()` is explicit silence.
5. Run a short bounded model/tool loop. An actual tool result may justify a follow-up model step; an audience-reaching `speak` or silence should end the turn.
6. Record completed actions, delivery state and results; resolve the turn. Newer turns may cancel/supersede older output.

Start with `speak` and `stay_silent`. `send_message`, game actions and free-form tools are later capabilities. Avoid generalized multi-tool orchestration, elaborate rescue steps and mid-stream steering until a real scenario requires them.

**Only complete, validated arguments may execute side-effecting tools.** Future speech can speculatively stream already decoded `speak.message` fragments to TTS, but arbitrary actions cannot execute based on partial JSON.

### 6.1 Tool-aware history

Bea replays past spoken content as the actual `assistant → speak(args)` plus `tool → result` exchange. This matters: if past responses become plain assistant text, Luna may learn to output hidden prose instead of using `speak`.

Adapt Liac's context projection accordingly. Derive deterministic call IDs from committed event/turn IDs. Capture whether text was sent, audio actually played, or output interrupted; don't invent successful speech on restart. Keep one canonical Journal; this is just a read projection.

### 6.2 Multi-channel routing [FUTURE]

One character, one awareness context, but explicit destinations. A future `send_message(platform, channel, text)` needs validated output routes and privacy scopes. Input text cannot change its own platform permissions. Do not build a full routing framework before adding a real second surface.

## 7. Context, memory and handoff

**One assembled conversation**, not Luna's supervisor history and Bolt's separate 16K context. Recommended order:

1. Static identity/persona and concise tool instructions.
2. Stable replay of actual completed dialogue and tool results.
3. Compact dynamic briefing: remembered experience if available, people/route, live state.
4. This turn's ordered perceptions with provenance.

Cache-friendly prompt order is useful but not a reason to add abstractions. Compare complete valid prompts, and do **not** call a stable byte prefix a proven provider cache hit without actual counters.

**Adapt M4.8 rather than porting another memory engine:**

- Journal is always canonical. Summaries are replaceable projections.
- Cold stops before Hot whole-turn suffix. The old 1024-token target was for local Fast; choose new thresholds only after measuring Luna's real available context.
- Snapshot cutoff is frozen; events arriving during consolidation remain verbatim after it.
- Late/failed summaries never erase new history or in-progress speech. Budget fallback and later recovery are separate.
- Do not copy Bea's extra mutable context store, diary DB or vector index.
- Keep consolidation outside the speaking critical path. First try idle-time work with the available Luna transport; only introduce background model usage when contention is actually measured.

If retrieval is added later, separate **user claims**, **character fiction/claims**, **tool observations** and **uncertain inferences**. Privacy scope and source attribution matter more than elaborate scoring.

## 8. GPT-6 Luna and transport

**EXPERIMENT:** `openai-codex/gpt-6-luna` with reasoning `low` first; try `off` / `none` only if the **specific selected transport and model** report support. Do not assume a generic OpenAI API capability is present on the Codex route.

M5.0's OMP RPC `prompt_and_wait()` served asynchronous Deep tasks but is insufficient evidence of early streaming tool arguments. Evaluate the **transport**, not just the model:

- Stream `speak.message` tool-argument deltas and text with timestamps, and support cancellation.
- Control the actual model/system prompt; minimize coding-agent wrapper instructions.
- Use a supported authentication flow; do not assume a ChatGPT subscription is a direct API key.
- Record requested and observable reasoning mode, model ID, latency, token usage and errors.
- Prefer one tiny production transport adapter. A bridge based on `pi-ai` is a candidate, not an automatic dependency; OMP may stay if it passes the same tests.

**First proof:** real `low` Luna tool call → discover supported reasoning levels → compare `off` if available → inspect streamed tool deltas and cancellation → measure first usable fragment. Do not build a complete provider SDK or TTS pipeline before that proof.

## 9. Vision and real sensors [NEW M6.2]

Bea's Minecraft adapter shows the valuable pattern: **event vs. live state**. It uses structured mod data, not an out-of-the-box screen-VLM solution.

First Liac sensor:

- Explicit, user-controlled capture of a selected screen or window.
- On-demand or scene-change-triggered frames. No continuous 30-FPS cloud VLM loop.
- One measured VLM turns a frame into concise observations, preserving source, time, uncertainty and expiry.
- Send those observations to the existing Perception Bus; non-meaningful repeats update state or are dropped.
- Avoid storing raw screenshots or uploading them to cloud systems by default. Permission is explicit.
- Bound image work to prevent stale VLM observations, latency and GPU contention.

Choose the VLM **after comparing real implementations and measurements** on the target machine. A game adapter with native structured events may be more reliable than vision for some tasks.

## 10. Streaming TTS and avatar [NEW M6.3]

Build TTS **after** Perception, Wake/Attention and a minimal real VLM sensor, per the target experimental sequence. Start with **one** voice engine and one output route.

Borrow from Bea's `JsonFieldStream`, `SpeechChunker` and `LiveLine` mechanics:

- Decode usable fragments of an incomplete `speak.message` JSON string correctly, including escapes.
- Send complete pronounceable chunks to TTS before Luna finishes the entire call.
- Preserve speech order with a small bounded lookahead; don't build a general media pipeline.
- Cancellation and barge-in stop stale queued and playing sound. Never let a cancelled turn continue speaking.
- Store the **actually delivered/heard** part if that information is available, not the hypothetical complete sentence.
- Later mood/face tags may select existing avatar assets. Do not add complex affect/prosody layers during the first audio benchmark.

Measure the whole chain: settled input → first model/tool delta → first usable `speak` fragment → first audio chunk → **first audible sound**. Streaming does not remove any long reasoning pause before the first visible delta.

## 11. Actions and game adapters [FUTURE M6.4+]

Available tools should correspond to real enabled capabilities; don't tell Luna a tool exists if the runtime cannot execute it. Begin with two speech/silence tools. Add one external tool only after the main loop is stable.

All effects pass through Runtime: validate arguments used, permission and destination; execute; record success/failure; emit tool outcome as Perception. Coarse game goals may use deterministic controllers. No direct shell or unscoped desktop control. Loonyball, Discord, OBS and game control remain optional future integrations.

## 12. Concurrency, failure and lifecycle

The Perception Bus and Runtime are owned by one asyncio event loop; cross-thread producers must marshal to it. A slow sensor/tool/consolidation task cannot block the character event loop.

**Mandatory invariants:**

- Accepted canonical events are atomic, idempotent and recoverable. Retry does not repeat an already committed character response.
- Stale generation, summary or tool result cannot overwrite newer state or play audio after supersession.
- Tools cannot execute unauthorized external effects based on model text or untrusted sensor content.
- Bounded pending work protects against runaway queues and stale vision/audio.
- Context handoff preserves raw Hot turns and immutable in-flight frames.

Avoid repeating these validations in every layer. Put each at the **single boundary that owns it**. Shutdown stops new inputs, settles or explicitly cancels accepted work, flushes Journal and closes owned transports. Never invent a successful answer after restart.

## 13. Acceptance and measurement

A fake-backed test is not a provider benchmark. Report separately: unit tests, offline integration, real Luna, real VLM, audible TTS and human evaluation. Do not add broad testing scaffolding just because a hypothetical fault exists.

**Focused regression scenarios:**

- Close messages → one batch, one canonical input, one cognitive turn; retry/restart no duplicate speech.
- Noise or unchanged state → no Luna call; meaningful perception → correct frame.
- `speak` and `stay_silent` outcomes → correct tool-aware replay.
- Cancellation and late tool results → no stale output or unsafe effect.
- Hot/Cold handoff → no raw input loss or misordered history.
- One actual live request through selected transport with matching model and reasoning options.

**Real metrics:** p50/p95 first model/tool delta; first usable speech fragment; first **audible sound**; full turn duration; inference steps and tokens; ambient false-wake frequency; cancellation and duplicate rate; memory continuity and character quality. Do not claim a cache hit without provider-side evidence. A ~2–3-second median first-audio target may guide evaluation, **not** serve as an unverified guarantee.

A pre-existing desktop regression, `MainWindow.context` missing in `test_desktop.WindowTests.test_chat_context_selection_and_offline_history`, remains outside this architectural change unless separately fixed.

## 14. Milestones

| Phase | Minimal slice | Exit evidence |
| --- | --- | --- |
| **M0–M5.0** | Original Bolt/Luna architecture; M4.8; M5.0 Perception Bus | **IMPLEMENTED**, offline evidence in reports; baseline retained |
| **M6.0** | Single Luna `low`; capability probe for `off`; small tool-call mind loop; streaming proof | Real model can `speak` or remain silent, tool deltas and latency measured |
| **M6.1** | Direct Wake, Live State, bounded tool-aware replay, Runtime snapshot | Long fake history and short live Luna acceptance |
| **M6.1.5** | **EXPERIMENT** local Electron [VTuber Hub](M6_1_5_VTUBER_HUB.md) over JSONL IPC | Process control, Runtime inspection, and direct text conversation |
| **M6.2** | One window/screen adapter with chosen VLM | Real scene change enters context, no runaway VLM requests |
| **M6.3** | Streaming TTS and interruption; first-audio benchmark | Actual end-to-end latency and naturalness evaluated |
| **M6.4** | Keep/adjust Single Mind based on evidence; first permitted external action | A conscious decision supported by measurements; one action result observed |
| **Later** | Voice/STT, Discord, Loonyball/avatar, richer game tools and memory retrieval | Independent vertical slices |

If the one-model approach is too slow, first test transport, prompt, cache and reasoning settings before restoring a two-model architecture. Keep the old system available for a measured comparison.

## 15. Code layout and boundaries

| Area | Role |
| --- | --- |
| `contracts/` | Small immutable data/port interfaces |
| `runtime/perception_bus.py` | Existing bounded ephemeral event intake |
| `runtime/journal.py` | Canonical SQLite history; transactions, replay |
| `context.py` | Deterministic window and tool-aware prompt projection |
| Future single-mind coordinator under `runtime/` | One cognitive turn, wake, tool execution, cancellation |
| `minds/` or one focused adapter | Luna streaming transport, model/reasoning config |
| Future `sensors/` | Screen/VLM, game, audio input; no decisions |
| Future `expression/` | Chunking, one TTS engine, playback |
| `app.py` | Dependency wiring only |
| `tests/` | Critical integration/regression tests, not coverage theater |

Keep the Python modular monolith and minimize added dependencies. Never alter Loonyball or deploy as an implicit part of Blueprint work. A M6 PR should change only the smallest relevant modules.

## 16. Open questions and references

Open until actual live verification: whether Codex Luna accepts `off`, how much agent-prompt overhead OMP adds on the provider-facing side, whether incremental function-call arguments are exposed, first-audio latency under perception load, usable VLM latency/VRAM, and how to schedule compaction without competing with live replies.

Upstream code review pinned to [`ProjectBEA@f2186fc`](https://github.com/emqnuele/projectBEA/tree/f2186fc647db3f9ae65e6463b9f82c882bdca68b):

- [Consciousness](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core/consciousness.py) – one turn loop and tool outcomes.
- [Attention rules](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core/attention/rules.py) and [gate](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core/attention/gate.py) – salience, addressed input and ranking.
- [SingleContext](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core/mind/single_context.py) and [Handoff](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core/mind/handoff.py) – canonical replay and background recap.
- [Streaming tool parser](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core/agent/streaming.py), [LiveLine](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core/expression/live.py) – speculative speech and cancellation.
- [Minecraft surface](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core/skills/minecraft/surface.py) – structured event versus live state, **not** a generic VLM sensor.

These are behavioral references, not automatic dependencies. If upstream source is copied, preserve applicable MIT license/copyright notices. Historical records: [M5.0 baseline Blueprint](https://github.com/softsock/liac-ai/blob/7510227dcb21212c607532150b864ff7757476ce/docs/PROJECT_BLUEPRINT.md), [M5.0 report](M5_0_PERCEPTION_BUS.md), [M4.8 report](M4_8_CONTEXT_HANDOFF.md).

---

**Direction:** Give Luna one world, one coherent history and a voice. Keep mechanisms small, necessary boundaries safe and model behavior measurable. **Single Mind stays EXPERIMENT until live evidence supports replacing M5.0.**
