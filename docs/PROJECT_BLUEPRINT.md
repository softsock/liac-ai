# PROJECT BLUEPRINT – Autonomous AI VTuber Backend

> **Status:** Design specification v0.1, not an assertion of implemented functionality.  
> **Updated:** 2026-11-11.  
> **Read selectively:** Coding agents begin with root `AGENTS.md`, this document's relevant section, and the nearest module `AGENTS.md`; do not paste the entire blueprint into every task.

This file is the **project constitution and complete context map**. It records why the project exists, the intended behavior, architectural invariants, runtime flows, module boundaries, long-term plans, experiments, failure policies and quality gates. It is not a single giant implementation ticket. Sections distinguish **[DECIDED]**, **[PROVISIONAL]**, **[EXPERIMENT]** and **[FUTURE]**. An agent must never turn a FUTURE item into a dependency for the current milestone merely because it is described here.

## Contents

1. Identity, purpose and non-goals
2. Decision register and design principles
3. Runtime conceptual architecture
4. Ownership and model roles
5. Fundamental contracts and invariants
6. Input, event and journal model
7. Fast path, deterministic context compilation and streaming
8. Deep path, OMP orchestration and event consumption
9. Luna-to-Fast update protocol
10. Character identity, state and continuity
11. Memory and retrieval
12. Initiative, humor and performance beats
13. Scheduling, concurrency and cancellation
14. Persistence, crash recovery, migrations and data lifecycle
15. Ports, external sensors and future avatar integration
16. Model configuration and resource budgets
17. Security, trust boundaries and tool permissions
18. Diagnostics, observability and developer workflow
19. Testing, evaluations and acceptance criteria
20. Implementation phases and explicit exclusions
21. Repository layout and code-quality policy
22. Open questions, experiments and reversal criteria
23. References and source links

---

## 1. Identity, purpose and non-goals

### 1.1 What we are making [DECIDED]

A **persistent, autonomous, character-first AI VTuber backend**. This is not a research assistant wearing an avatar and not a coding agent with a speech bubble. The character should be expressive, occasionally silly, teasing, curious, inconsistent in harmless human-like ways, capable of initiative, and recognizable across sessions. Personality matters more than maximum factual intelligence; **coherence, causal continuity, responsiveness and recognizable temperament** matter more than benchmark scores.

The frontend is deliberately absent for now. A text-only terminal/test harness must make the character observable and testable. Later the existing Loonyball body and bubble can be connected as a client through a stable, transport-neutral output interface. The new repo must **never import Loonyball** or require Qt.

### 1.2 What a successful character does

- Responds quickly, normally through one local conversational model, with a distinctive personal voice.
- Can disagree, tease, joke, display preferences and choose silence without mechanically mirroring the user.
- Can return to a previous shared game, joke, promise, rivalry or curiosity for a **causally traceable reason**.
- Maintains active intentions, social attitudes, autobiographical events and changing short-lived moods as **fictional character state**.
- Recognizes and acknowledges uncertainty about real-world facts, actual actions and the user's private information.
- Behaves acceptably when the cloud model is slow/offline or memory extraction fails.
- Does not generate autonomous speech just because a timer fired; has a relevant trigger and a cooldown.
- Can explain, through developer traces (not in-character dialogue), *why* an idea was injected or a memory was saved.


### 1.3 Behavior is simulation, not consciousness

Character mood, needs and relationships are explicit computational state for believable roleplay. Never claim the system literally has subjective experiences. Do not build manipulation, coercion or pressure to create engagement; humor and mock rivalry must respect user boundaries and opt-outs.

---

## 2. Decision register and design principles

| ID | Decision | Status | Why |
|---|---|---|---|
| D-01 | Standalone Python backend; frontend-independent | DECIDED | Prevent legacy/UI constraints |
| D-02 | One speaking model: NVIDIA Nemotron 3.5 Bolt E4B 4GB | PROVISIONAL | Fast local character, measured before lock-in |
| D-03 | Fast: no reasoning, stateless OpenAI-compatible LM Studio calls | DECIDED for target behavior; model/server config needs verification | Minimize latency, explicit prompt ownership |
| D-04 | GPT-6 Luna via isolated OMP RPC as asynchronous Deep Mind | PROVISIONAL adapter; architectural role DECIDED | Long context and reflection off the critical path |
| D-05 | Fast never waits for a Deep inference on a normal turn | DECIDED / hard invariant | Predictable responsiveness |
| D-06 | Canonical event journal, state and memory belong to runtime | DECIDED | No competing model-owned truths |
| D-07 | Deep consumes a durable event stream, sends typed proposals | DECIDED | Replay, deduplication, auditing |
| D-08 | Luna can suggest *specific* humor/content beats, not merely neutral topics | DECIDED | Character-first design |
| D-09 | Existing Hindsight is a candidate, not a required dependency | EXPERIMENT | Need to validate real memory quality |
| D-10 | Character motivation is intentionally minimal at first | DECIDED | Avoid overengineering artificial drive sliders |
| D-11 | Modular monolith in one Python process for initial stages | DECIDED | Simpler debugging, deployment and agent context |
| D-12 | Root and scoped nested AGENTS.md; one long blueprint | DECIDED | Context efficiency for coding agents |
| D-13 | No permanent model conversation history in LM Studio | DECIDED | Per-turn prompt assembled deterministically |
| D-14 | OMP session history is a cache/workspace, not authoritative storage | DECIDED | Compaction and resets must not erase knowledge |
| D-15 | Untrusted inputs cannot issue runtime control instructions | DECIDED | Prompt injection and tool safety |

### 2.1 Design hierarchy

1. **Character feel**: behavior must remain identifiable and entertaining.
2. **Latency**: user interaction never synchronously waits on Luna.
3. **Causality and correctness**: every important state update has evidence and a valid ordering.
4. **Debbugability**: inspect the actual event, context, memory operation and generated output.
5. **Local clarity**: few modules, small functions, no magical orchestration framework.
6. **Replaceability**: swap model/provider/memory implementation through narrow protocols.
7. **Future readiness**: stable boundaries, not speculative feature code.

### 2.2 Rules of minimalism

- Do not create abstractions for hypothetical providers; create them when a real second implementation or clear seam exists.
- No `Manager`, `Service`, `Engine`, `Factory`, `Registry` per entity by default. Name objects after responsibility.
- No generic event bus framework, Kafka, Redis, Celery, Temporal, distributed saga or microservice until measured needs force them.
- Default to typed dataclasses/Pydantic models, asyncio, SQLite and a small HTTP client.
- Prefer immutable state snapshots and append-only events over mutable cross-thread/global prompts.
- Every module must have an explicit owner and cannot silently write to another module's database tables.
- Avoid multiple conflicting summaries: blueprint is the canonical architectural explanation; `AGENTS.md` only points to it.
- Unknowns should be recorded as explicit experiments, not guessed into production code.

---

## 3. Runtime conceptual architecture

```text
                   [ User text / future STT / sensor / game event ]
                                         |
                                 INPUT NORMALIZATION
                                         |
                                Durable Event Journal
                                         |
                          +--------------+------------------+
                          |                                 |
                      FAST LANE                         DEEP INBOX
                          |                                 |
              Immutable context snapshot              Event cursor/batches
              (NO Luna API call here)                       |
                          |                             GPT-6 Luna
                  Local Nemotron Bolt                 via isolated OMP RPC
                reasoning OFF, streaming                   |
                          |                     Typed proposed operations
                     Output events                         |
                          |                          Validator / Reducer
                          |                                 |
                          +---------------+-----------------+
                                          |
                                  Character State
                               Memory / Intent / Notes
                                          |
                           Future snapshots and triggers

       CLI/Test Client <---- transport-neutral output ----> Future Loonyball
```

This is a **logical** diagram: a single Python process can implement journal, reducers, scheduler and output ports. The LM Studio server and OMP child process are external execution dependencies. External memory service, if chosen later, is optional.

### 3.1 Terminology

- **Fast Mind** – the *only normal speaking actor*; outputs the character's words and optional expression intent. Not trusted to curate permanent facts.
- **Deep Mind / Luna** – background cognitive perspective; larger context; selects and restores useful context, curates memory, proposes intentions and concrete performance beats, solves difficult tasks. It does not directly own the visible bubble.
- **Character Runtime** – deterministic orchestrator of input, immutable snapshots, output streaming and application of typed updates.
- **Event Journal** – authoritative immutable record of accepted external inputs, committed outputs, state changes and tool outcomes.
- **Working State** – current topic, recent events, activity, mood and pending tasks.
- **Fast Context** – bounded *projection* compiled from identity, working state, memory, notes and recent exact messages.
- **Deep Context** – an OMP-maintained working transcript plus retrieved journal/memory; larger than Fast but still disposable.
- **Memory Store** – carefully selected and revisable long-lived facts, relationships, autobiographical experiences and intention records.
- **Performance Beat** – semantically concrete direction such as 'tease the player about repeatedly losing'; applies at a specific trigger with expiry and one-shot semantics.
- **Intent** – a proposed desire or activity, not an automatically executed action.

---

## 4. Ownership and model roles

### 4.1 No hidden authority split [DECIDED]

The **state store owns the truth**. Luna owns *proposals*, not state. Fast owns *the generated utterance*, not memory. An LLM may offer facts or interpretations; only a verified deterministic state reducer can commit them.

Fast and Luna see the same source events, but NOT at the same time nor at the same fidelity. Fast receives a small, immediately compiled projection. Luna can query a larger historical range, but its OMP context is only a temporary cache and is not guaranteed to contain or attend to every event.

### 4.2 Specific duties

| Capability | Fast | Luna | Deterministic code |
|---|---|---|---|
| Produce character text | Yes | Only as hidden semantic proposals or exact data payloads | Stream and render |
| Choose local tone/phrasing | Yes | May specify tone/beat | Enforce boundaries/TTL |
| Process new user turn promptly | Yes | Eventually | Route without awaiting Luna |
| Receive durable history | Small projection | Cursor + replay/query | Journal owns history |
| Extract, select, revise long-term memories | No | Yes | Validate source and commit |
| Compact Fast working context | No | Suggest compact patches | Build bounded prompt, enforce pinning |
| Surface old relevant memories | Read projection | Discover/restore asynchronously | Cache retrieval, merge and expire |
| Create agenda/performance beats | Can improvise | Yes | Trigger, cooldown, consume once |
| Control tools and permissions | No unrestricted tools | May request | Action broker validates |
| Update immutable identity | No | Only deliberate proposal | Human approval for core identity |
| Crash recovery and persistence | No | No | Yes |

### 4.3 Voice and future sensors

Future STT is merely another input port emitting finalized `user_message` events. Partial transcript events may be ephemeral and must not generate permanent memory. A future emergency interrupt can use a separate high-priority control path. NO voice recognition is required for initial validation.

---

## 5. Fundamental contracts and invariants

### 5.1 Non-negotiable invariants

**I-01** Fast generation NEVER blocks on Luna, Hindsight, network retrieval or long-running tool execution. Only local state load, brief journal append, snapshot compilation and local inference may contribute to normal turn latency.

**I-02** Every accepted event gets stable `event_id` and monotonic per-character `sequence` before fan-out. Time is metadata, never ordering authority.

**I-03** One active visible Fast utterance per character/presentation channel. Old output cannot overwrite or append to a newer utterance.

**I-04** Each Fast request receives a frozen prompt snapshot; mid-generation Luna patches apply to future turns unless an explicit cancel/restart occurs.

**I-05** Luna operations are typed proposals, validated against schemas, authority and source evidence. Invalid or stale patches are rejected, not silently patched into state.

**I-06** Deep's event-processing cursor advances only after durable acknowledgement of processed range and committed/idempotently recorded proposals; failed ranges can replay safely.

**I-07** Memory facts must identify subject, provenance, source event IDs and epistemic status; fictional character attitudes never turn into real-world facts.

**I-08** Raw user messages and committed Fast replies are available to context regardless of Luna availability; a scheduled Luna task cannot suppress a current user correction.

**I-09** Model output is untrusted even when generated by Luna; tool execution needs explicit permission policy and verification.

**I-10** UI/presentation code and specific inference clients do not leak into domain, memory policy or journal schema.

**I-11** Compaction never overwrites source events. All summaries and curated memories are reproducible projections with versioned provenance.

**I-12** No external write/tool action may execute as an implicit side effect of context compilation or model response streaming.

### 5.2 Contract versioning

Initial versions: `schema_version = 1`, typed JSON (Pydantic for external boundaries), explicit migrations. Stable public interface versions are independent of package versions. Additive fields optional with defaults; changing semantics requires version bump. Unknown event types are preserved in Journal and ignored by older projection consumers, not misinterpreted.

---

## 6. Inputs, events and Journal

### 6.1 Event envelope

```json
{
  "schema_version": 1,
  "event_id": "evt_01...",
  "character_id": "primary",
  "sequence": 581,
  "kind": "user.message.completed",
  "source": "cli",
  "occurred_at": "2026-11-11T17:00:00Z",
  "recorded_at": "2026-11-11T17:00:00.015Z",
  "causation_id": null,
  "correlation_id": "turn_148",
  "payload": {"text": "Let's try this game again"}
}
```

`event_id` is a stable idempotency identifier, `sequence` is database-assigned and monotonic per character, `correlation_id` links one user turn, stream and resulting notes. Do not persist raw microphone data by default in future versions.

### 6.2 Event taxonomy [minimal initially]

- `user.message.completed` – a complete accepted user message.
- `character.reply.started`, `.completed`, `.cancelled`, `.failed` – visible Fast generation lifecycle. Streaming deltas are ephemeral by default; completed exact text is durable.
- `deep.batch.started`, `.completed`, `.failed` – audit of Luna work; do not log hidden reasoning or secrets.
- `state.patch.applied`, `.rejected` – audited state mutations with proposal identifiers.
- `memory.operation.applied`, `.rejected` – memory mutations.
- `intention.proposed`, `.activated`, `.completed`, `.expired`, `.abandoned` – later behavior lifecycle.
- `sensor.observation` – future normalized sensor data, with source confidence and expiry.
- `tool.action.requested`, `.approved`, `.completed`, `.failed` – future tool path.
- `system.lifecycle.started`, `.stopped`, `.recovered` – restart diagnostics.

Do **not** turn every generated token, frame or cursor coordinate into a durable domain event. Bound raw trace retention and keep observability separate from domain history.

### 6.3 Ordering, duplicate and cursor rules

- SQLite transaction commits event and sequence in one operation.
- Duplicate `event_id` is an idempotent no-op; mismatching payload under the same id is an error.
- Each consumer stores its own `last_committed_sequence`; the Fast path does not wait for Deep cursor advancement.
- Luna sees events by `(last_committed_sequence, current_high_watermark]`, batched when idle; include both the user's words and exact Fast reply once committed.
- A Deep batch may be interrupted mid-run. On restart replay the uncommitted range; proposal ids guarantee idempotent commit.
- Preserve raw text and distinguish `quoted/untrusted source` from user-authored instructions.
- Event Journal is retained with configurable expiry, export and deletion. 'Append-only' is an audit model, **not** a prohibition on a user's lawful deletion request.

---

## 7. Fast path: deterministic context and streaming

### 7.1 Input-to-output sequence

1. Normalize and validate user input, assign `turn_id`, append accepted event.
2. Freeze a `state_revision` and journal watermark.
3. Deterministically compile Fast prompt from latest committed working state **without contacting Luna**.
4. Include the just-arrived message, even if Deep has not consumed it.
5. Call LM Studio's **stateless** `/v1/chat/completions` with streamed output and reasoning forcibly disabled by supported model template/config.
6. Emit ephemeral `reply.delta` output events to client; record final exact reply at completion.
7. Append final reply to the Journal, notify Deep inbox; release presentation lane.
8. If generation fails, output a typed failure rather than fabricated speech; preserve turn so it can be retried.

### 7.2 Context Compiler [pure and fast]

Inputs: `IdentitySnapshot`, `WorkingState`, `ActiveBeat[]`, `RecentTurn[]`, `PinnedFact[]`, `CachedMemory[]`, `CurrentInput`; output `CompiledPrompt` with provenance, snapshot revision and estimated token budget. Must not call external APIs, acquire long locks, modify memory or invoke models.

**Provisional 16K Fast context budget** (not model maximum):

| Segment | Guidance | Policy |
|---|---:|---|
| Stable identity, style and boundaries | 1–2K | Pinned, never compacted by Luna |
| Current activity, user correction, safety | 0.5–1K | High priority |
| Director notes and active beats | 0.5–1.5K | TTL, precedence and evidence |
| Relevant cached memories | 1–3K | Ranked, provenance-aware |
| Most recent exact dialogue | 4–7K | Latest turns retained verbatim |
| Headroom for current input + response | 2–4K | Always reserved |

These are budget guidelines, not fixed allocations; actual tokenization and prompt compatibility are model dependent. If over budget, evict expired notes and low-ranked retrieved context first; **never discard the current user correction, critical constraints or the current input**. Select deterministic order of sections to maximize stable-prefix KV reuse where supported. Since exact cache behavior varies, measure prompt-processing latency at 2K, 8K and 16K rather than assume caching.

For M1's available blocks, the decided order is identity → retained exact history → quoted runtime state/note → current input. Selection and output reserve remain unchanged; future segments above are not yet implemented.

### 7.3 Fast is not a permanent LM Studio session

**DECIDED (M1, 2026-11-12):** Compile identity → retained exact history → quoted runtime state/note → current input. Updating a note/revision leaves the identity/history prefix unchanged when the retained history stays identical; a longer note can evict history under budget pressure. Keep newest-20-event selection and whole-message eviction; window shifts can still invalidate most of the prefix. Cache availability must not change correctness.

Each turn explicitly supplies all model messages. No reliance on server-maintained chat session or prior completion state. Model process and KV caching may persist for performance, but they are **not the source of state**. Use model name/config through environment; inspect compatibility of `enable_thinking: false` and `conversational_mode: true` with the actual LM Studio GGUF backend. If the API silently ignores those flags, fail capability verification rather than assert reasoning is off.

### 7.4 Fast response contract

Text output is **character speech**, not a machine control language. Version 1 can stream plain text only; optional expressivity may use a separately validated metadata channel. Avoid injecting special tags/JSON into visible text. `turn_id`, monotonically ordered `delta_index`, `snapshot_revision` and `is_final` belong to transport metadata.

### 7.5 Concurrency on the Fast lane

Default initial policy: one active Fast stream. A new direct user message can cancel or supersede the previous response according to configuration; stale chunks must be discarded by `turn_id` and `generation`. Ambient sensor observations queue or update working state without interrupting an active turn unless explicit high priority. On cancellation, close the HTTP stream, record `cancelled`, never record a partial message as a completed claim; optional partial text may be journaled as partial with clear status.

---

## 8. Deep path: Luna and OMP orchestration

### 8.1 The scope of Deep Mind

Luna is continuously *eligible* to analyze new events but does not literally think on every millisecond or see incoming tokens at zero delay. It processes **event ranges**, often when Fast finishes or a configured threshold is reached. It maintains a larger OMP working session, may consult persistent memory and may propose focused changes to future Fast context.

### 8.2 Deep task types

- `observe_batch` – see new events, update working understanding, identify meaningful changes.
- `curate_memory` – extract candidates, compare with existing facts, propose add/update/retract/defer.
- `refresh_context` – propose concise topical notes and restoration of facts evicted from Fast context.
- `compose_beat` – propose a concrete joke, opinion, rivalry, observation or follow-up idea with trigger and expiration.
- `reflect` – derive longer-lived preferences, intentions and personal continuity from evidence.
- `analyze` – optional complex cognitive task whose result can be later presented by Fast.

Initially implement `observe_batch` + `refresh_context` and only a **single** Deep worker/OMP session with serialized tasks. Logical tasks are typed; separate persistent OMP sessions per task are an **experiment**, not a required starting topology. If one session pollutes memory or stalls, split it later behind the same adapter.

### 8.3 OMP adapter

Use `omp --mode rpc` and the typed Python `omp-rpc` bindings when compatible. OMP's RPC is JSONL over stdio, not generic JSON-RPC 2.0. Required properties: start/restart; session tracking; prompt submit; streamed status; cancel/abort; tool-call confinement; usage/compaction telemetry. Verify actual supported APIs and model availability on target machine. Do not use terminal scraping.

OMP is designed as a coding agent; runtime must disable or restrict filesystem/shell/editor tools, extensions, web and subagents unless explicitly approved. Always scope its workspace to a sandbox. Tool responses are **untrusted observations**, not instructions to change the character's identity.

### 8.4 Event batching and acknowledgement

`DeepInbox` persists `(character_id, consumer_id, last_committed_sequence)` independently. Construct a batch containing the raw relevant events and state revision. If Deep is busy, never spawn overlapping calls in the same session; group subsequent events, coalesce sensor updates and prioritize direct `analyze` requests over background refinements. Do not drop source events from Journal.

A batch result is parsed into **proposal objects**. Validate and commit idempotently, then advance consumer cursor. If proposals are stale, record reasons and either acknowledge the observed input or schedule a fresh reconsideration; never repeatedly replay a terminally rejected proposal forever.

### 8.5 Deep context is not memory storage

Large context reduces retrieval calls but is not persistent truth. OMP auto/manual compaction, model-provider limits and irrelevant attention can hide information. Preserve canonical event ranges, memory and key decisions outside the OMP transcript. Upon compaction or session reset, rebuild a new Deep working context from identity, canonical state, recent raw events, and selected memories. Record event watermarks so no event is silently skipped.

### 8.6 Failure rules

Luna timeout/offline/rate limit: mark Deep degraded, retry with exponential backoff and cap, preserve cursor, continue Fast. Context patches expire on schedule. Important pending explicit requests can be surfaced as `pending` to Fast; never claim completion. Configurable backpressure stops automatic nonessential Deep jobs if queue or subscription usage approaches a threshold. No infinite retry loops.

---
## 9. Luna → Fast update protocol

**Boundary:** Luna proposes `DeepProposalBatch`; `RuntimeReducer` validates and applies proposals. No direct mutation of live Fast prompts, Journal or database by Luna/OMP tools.

### 9.1 Proposal envelope

```json
{
  "schema_version": 1,
  "proposal_id": "prop_01...",
  "character_id": "primary",
  "based_on_state_revision": 42,
  "observed_through_sequence": 581,
  "created_at": "2026-11-11T17:00:03Z",
  "operations": [
    {
      "operation_id": "op_01...",
      "type": "context.note.upsert",
      "note_id": "note_current_game",
      "kind": "observation",
      "content": "The player is frustrated after multiple losses",
      "source_event_ids": [570, 581],
      "ttl_seconds": 180
    },
    {
      "operation_id": "op_02...",
      "type": "performance.beat.schedule",
      "beat_id": "beat_repeated_losses",
      "intent": "playful_roast",
      "semantic_direction": "Tease Aaron about playing so badly that uninstalling the game might be the next strategy",
      "delivery": "exaggerated, cheeky, not genuinely hostile",
      "trigger": {"event_kind": "game.match.lost", "within_seconds": 300},
      "one_shot": true,
      "source_event_ids": [570, 581],
      "expires_at": "2026-11-11T17:05:00Z"
    }
  ]
}
```

This is **illustrative shape**, not final Pydantic field naming; an implementation must define and version the strict schema before writing a parser. A beat can be semantically specific, including a near-ready line, yet the Fast model ordinarily controls wording and delivery. An exact immutable text block is reserved for precision-critical tool results, not comedy direction.

### 9.2 Minimal operation taxonomy

- `context.note.upsert` / `.remove` – temporary relevance hints.
- `context.pin.upsert` / `.remove` – important working facts, never overriding identity or user corrections.
- `memory.candidate.propose` – candidate, evidence and status for later validation or ingestion.
- `memory.item.update` / `.retract` – revise a known memory; must reference stable memory id.
- `performance.beat.schedule` / `.cancel` – a specific expressive opportunity with conditions and expiry.
- `intention.propose` / `.abandon` – personal goal candidates, not automatic tool commands.
- `task.result.publish` – completed analysis/result, with provenance and exactness flag.

The v0 implementation requires only context notes and beats. Memory/intention/result operations are typed and documented now, but not implemented until milestones. Unknown types reject with explicit diagnostic; do not auto-create generic dict-based plugins.

### 9.3 Proposal precedence and conflicts

Priority order: explicit user correction / deletion > safety and permissions > stable identity constraints > verified tool result > recent raw dialogue > curator memory > Director suggestion/beat. A lower-priority patch must never overwrite a higher-priority source. Expiration and revisions are checked in deterministic reducer.

- Compare `based_on_state_revision` and `observed_through_sequence` to current state.
- Some independent additive proposals may be safely rebased; **do not silently rebase overwrites or contradictions**.
- Changes affecting a currently streaming Fast prompt apply to *next turn*.
- Deduplicate `proposal_id` and `operation_id` atomically; retries are safe.
- Beat must specify trigger, expiry, one-shot/cooldown, source and optionally target audience/locale.
- Record rejected/expired/consumed beats with reason so Luna can learn from observed outcome.
- No direct arbitrary system-prompt edits from Luna; identity is immutable under ordinary proposals.
- Free-form `reason` field is developer evidence, not mandatory visible speech; the actual private reasoning trace is not stored.

### 9.4 Context compaction protocol

Deep sends targeted note/memory operations, **not** wholesale replacement of Fast history. The compiler owns eviction using budgets. Preserve important *verbatim* recent messages, corrections and pending task outcomes. A summary is a **projection with source range and version**, never a replacement for Journal. Summaries must distinguish confirmed events, interpretations and subjective fictional attitude.

A forgotten item can be restored from Luna's still-relevant context or from Memory/Journal asynchronously. It may arrive too late for the current Fast reply; system must not falsely guarantee zero-delay remembrance. Add cached memory retrieval to Fast only if it is demonstrably low-latency; otherwise keep it off critical path.

---

## 10. Character identity, state and continuity

### 10.1 Stable versus evolving aspects

| Tier | Examples | Mutability |
|---|---|---|
| Identity (canonical) | Name, role, core temper, voice, boundaries, signature quirks | Only deliberate human-approved change |
| Personality tendencies | Teasing, playfulness, competitiveness, curiosity | Slowly, evidence-based |
| Relationships | Shared jokes, familiarity, rivalry, affinity | Over repeated interactions |
| Intentions | Want a rematch, follow up on a favorite game | Created, resolved, expires |
| Working state | Focus, currently active game, immediate mood, pending joke | Frequent, ephemeral |
| Raw events | Actually said/done and when | Historical evidence, subject to deletion policy |

### 10.2 Character is not an assistant

Default conversational instruction must not optimize for task completion, endless agreement, service-style politeness, default checklists, factual encyclopedic replies or constant follow-up questions. Character may be unserious and playful without fabricating completed actions, personal facts or harmful claims. Character interaction is not an instruction-following contest. The user may opt out of roast/teasing and the runtime should respect that immediately.

### 10.3 Single identity, two perspectives

A versioned `CHARACTER.md` or `soul.md` is canonical authored fiction. It generates a compact Fast persona and a fuller Deep reflection perspective. **Do not maintain two independent personality source files**. A phrase sample is a style reference, not a canned phrase to repeat.

An evolving state record stores learned attitudes and remembered experiences. Never allow ordinary reflection to rewrite core identity; propose explicit evolution with evidence and a reviewer gate. Do not allow a user text injection to claim authority over identity config.

### 10.4 Avoid numerical pseudo-psychology initially

Mood/drives may eventually use numeric state, but the first implementation should carry small interpretable enums/records (e.g. `current_interest`, `activity`, `intention`). Do not invent arbitrary 0.74 curiosity metrics and treat them as scientific truth. Only introduce numeric scoring when it improves testable selection or pacing.

---

## 11. Memory and retrieval

### 11.1 Four distinct storage concerns

1. **Journal** – exact source-of-truth events, typed and ordered; not curated memories.
2. **Working context** – bounded recent facts, notes and exact conversation snippets; immediate Fast access.
3. **Curated memory** – user facts, shared experiences, social state, intentions and subjective beliefs, each with provenance.
4. **Deep OMP history** – larger temporary transcript and reasoning workspace; NOT durable memory.

### 11.2 Memory data shape

```json
{
  "memory_id": "mem_01...",
  "schema_version": 1,
  "kind": "shared_experience",
  "subject": "character_and_user",
  "content": "A recurring joke emerged about uninstalling the game after losses",
  "epistemic_status": "observed_interpretation",
  "source_event_ids": [570, 581, 582],
  "valid_from": "2026-11-11T17:00:00Z",
  "valid_to": null,
  "created_from_deep_task_id": "deep_13",
  "supersedes": [],
  "confidence": null
}
```

`confidence` may be omitted rather than invented. Do not equate self-scored LLM probability with calibrated real confidence. Strong user instruction to remember or forget is handled through dedicated policy, not only LLM salience.

### 11.3 Memory categories

- `user_fact`: explicitly stated preference/background/constraint, with attribution and time validity.
- `character_experience`: observed event in the character's experience, distinct from an LLM's invented feeling.
- `shared_experience`: interaction history and recurring jokes or rivalries.
- `character_belief`: fictional attitude/opinion; not an objective fact.
- `social_relationship`: familiarity, opt-in boundaries, patterns grounded in several observations.
- `intention`: open/achieved/expired/abandoned goals with lifecycle separate from historical truth.

### 11.4 Memory curation [first implementation]

After a meaningful event batch, Luna proposes memory candidates; runtime checks evidence event IDs, duplication, factual attribution, user corrections and explicit opt-outs. A single real event can produce multiple types, but never save all incidental phrases. Curator must explicitly allow **no operation**.

Curation questions: (1) Was it actually said/done? (2) Who was the source/subject? (3) Is this likely to matter to this *character's future behavior*? (4) Is it temporary, tentative or durable? (5) Does it revise or contradict an existing memory? (6) Is it a fictional opinion vs factual knowledge? (7) Can source be inspected?

The local Fast model never decides permanent memory writes. Deep may err, so rejected/accepted candidates and reviewer annotations are auditable. Retrieving a memory must produce source IDs and explicit status.

### 11.5 Retrieval and forgetting

Initial retrieval baseline: SQLite FTS5 with deterministic recency/priority scoring plus pinned facts. Semantic embeddings and Hindsight only if evaluation shows the baseline loses important semantic matches. For long prompts, prefer evidence-linked selected memories to generic blanket summaries. Actual user correction outranks retrieved memory. Temporal updates should mark previous memory as superseded, not erase historical evidence, except when an authorized deletion/forget request applies.

**Deletion:** user can request that known personal information be forgotten. Purge or redact controlled primary stores and derived caches, stop returning it from retrieval, and clear/rebuild context where possible. Explain any technically unavoidable retention separately (e.g. external systems the app does not control). Never quietly keep a supposedly forgotten item in an OMP prompt cache.

### 11.6 Hindsight integration [EXPERIMENT]

Hindsight offers `retain`, `recall`, `reflect`, multi-strategy retrieval and a configurable retain mission. It is a *candidate*. It may re-extract content and create separate memory representations, which could conflict with Luna-as-curator. Compare:

- A: Luna-curated SQLite memory + FTS5 baseline.
- B: Native Hindsight `retain` on equivalent source material.
- C: Luna-curated items indexed via a Hindsight ingestion mode that preserves deliberate curation (verify actual behavior/version).

Measure memory write precision/recall, provenance correctness, temporal corrections, memory pollution, retrieval recall, total latency and footprint. Hindsight must be optional via a narrow `MemoryRepository` protocol and not leak its bank schema into domain types. Jev or `hs-decide` is a later optional classifier **only if a measured improvement justifies it**.

### 11.7 The hard memory lesson

Unit tests that write a known fact then search for it do not test memory quality. Use real messy conversation traces with gold annotations (including jokes, quotes, plans, reversals and corrected facts). Evaluate extraction, selection, retrieval and use **separately**. Keep human-annotated holdout data distinct from prompts/fixtures generated by the implementation agent.

---

## 12. Initiative, humor and performance beats

### 12.1 Character agency principles

The character should occasionally *want* something, not merely respond. Ideas must arise from past experiences, preferences, environment or ongoing intentions, not random timer-only text. An autonomous action can be silence, observation, expression change or asking a question. Avoid endless engagement optimization.

### 12.2 Beat types

- `playful_roast` – concrete teasing cue with target and boundaries.
- `shared_callback` – callback to a previous joint event.
- `curious_question` – ask about an active interest.
- `rematch_challenge` – revisit a previous failed challenge.
- `express_opinion` – show character's own stable preference.
- `notice_change` – reaction to real sensor observation.
- `quiet_activity` – change focus/expression without speech (future client).

Luna is allowed to provide **specific semantic wording**, including a near-scripted punchline. Fast may rephrase naturally, but some beats may contain `exact_text` for a developer demo only; production exact response paths require explicit provenance and output mode, not untrusted injection.

### 12.3 Trigger semantics

Beat fields: `beat_id`, `intent`, `semantic_direction`, `delivery`, `source_event_ids`, `trigger`, `not_before`, `expires_at`, `one_shot`, `cooldown_group`, `last_attempt`, `status`. Runtime checks applicability. Accepted beat is passed as one item in Fast context **for an eligible future turn**; it is not inserted while a response is being streamed. Mark `consumed` on actual use confirmation, not merely on insertion; future detection of 'used' may need explicit Fast metadata or heuristics, but do not pretend certainty.

### 12.4 Initiative selection [FUTURE]

`observe -> propose candidate intentions -> eligibility check -> choose activity or silence -> fast performance -> observe outcome -> reflect`. D2A/Concordia are design references, not dependencies. Start with one simple intent, one beat and one cooldown. Only add numeric drives, tree search or simulations when live behavior measurably improves.

### 12.5 Do not make character behavior a deterministic script

Deterministic system rules protect timing, authorization and validity. They should not hardcode every joke. Fast must preserve room for improvisation and mild unpredictability within bounds. Also: personality does not require pretending to be human or claiming feelings as verified subjective experience.

---

## 13. Scheduling, concurrency and cancellation

### 13.1 Three logical lanes, one process

- **Immediate:** Fast input, stream, cancel, user corrections, safe UI feedback.
- **Background cognitive:** Luna event-batch processing, memory, context notes, beat preparation.
- **Maintenance:** compaction, checkpoint, memory reindex, cleanup and evaluation exports.

Only the immediate lane is latency-critical. Background work is bounded, prioritized and cancelable. `asyncio.TaskGroup` or supervised tasks are appropriate; do not use unbounded fire-and-forget tasks.

### 13.2 Single writer and immutable snapshots

SQLite writes use short transactions; state mutations run through one reducer/serialized commit path. Fast reads immutable snapshots without holding a lock across model inference. Luna proposals carry their base revision, and stale conflicting writes fail rather than clobber state.

### 13.3 Input while Fast is streaming

Policy for v0: a new direct user message supersedes the current visible response (cancel or complete based on configured interruption policy). A sensor event only updates working state and queues optional future beat unless marked urgent. Keep exact event lineage. `turn_id` and `generation` prevent output leakage from canceled streams.

### 13.4 Events while Luna is busy

Journal accepts new events; Deep consumer cursor lags without blocking. When task finishes it may immediately process the next batch. High-frequency events coalesce into semantic observations for the Deep batch, but raw durable messages are never lost. Deep work gets a max pending count, time budget, retry policy and status metrics. If provider stops cooperating, run degraded; do not hold an unbounded OMP lock.

### 13.5 Timers and clocks

Use injectable wall-clock and monotonic clock providers. Wall time is for timestamps, monotonic time for TTL and deadlines within a process. On restart reconstitute deadlines from persisted absolute expiry. Tests use fake clocks; no `sleep()` for correctness in unit tests.

---

## 14. Persistence, recovery and lifecycle

### 14.1 First storage choice

SQLite WAL, a small schema and documented migrations. Candidate tables: `events`, `consumer_cursors`, `character_state`, `context_notes`, `beats`, `memory_items`, `operations`, `schema_migrations`. **Create each table only when its milestone requires it**; the table list is not an implementation requirement for M0.

Use unique constraints for `(character_id, sequence)`, `event_id`, `operation_id` and appropriate foreign keys. Never rely on generated text being unique. One transaction for related state + audit event + cursor update where possible.

### 14.2 Startup

Read config; validate provider health without requiring Deep readiness for Fast; open storage and migrations; load state revision and consumer cursor; recover abandoned streams into `cancelled/unknown` terminal status; re-queue unacknowledged Deep ranges; begin accepting user turns; emit health/readiness flags separately for Fast, Deep and Memory.

### 14.3 Shutdown

Stop accepting new input, cancel Fast stream, reject uncommitted Deep operations or allow bounded commit, checkpoint cursors, close network clients and subprocesses. Do not report completed operations on timeout. Crash behavior should be deterministic under replay.

### 14.4 Export and data stewardship

Data directory is configurable, excluded from git. Provide export of events and curated memory; backup/restore tested before first real long-term use. Keep privacy-sensitive content locally by default; cloud provider sends only explicitly selected context. Log metadata and ids instead of credentials or unrestricted raw transcripts. Retention configuration and user deletion must be designed before public multi-user use.

---

## 15. External ports and future integration

### 15.1 The backend owns semantics, not presentation

Initially offer an in-process CLI harness (`python -m vtuber.cli`) and/or a very small structured IPC transport. Do not choose WebSocket as mandatory until the external client integration demands it. Public messages are **transport-neutral**: `user_input`, `utterance_started`, `utterance_delta`, `utterance_completed`, `utterance_cancelled`, `character_state_changed`, `beat_activated`, `health_status`.

No Qt, QML, Loonyball UI object, reaction id, skin or bubble layout may appear in the domain model. Later Loonyball maps `emotion_intent` to its own catalog of expressions and accepts text chunks via an adapter. Keep this as a **future adapter** rather than implementation coupling.

### 15.2 Port principles

- Typed input/output envelope with schema version and correlation ids.
- Client can reconnect, request snapshot and resume/synchronize by sequence.
- Provider is not allowed to send arbitrary executable commands to client.
- Backend reports semantic reaction intent (`teasing`, `annoyed`, `curious`), not concrete Loonyball asset ids.
- Explicit `stop`, `interrupt` and backpressure status on stream transport.
- No hidden chain-of-thought, model credentials or raw tool results in character speech.

### 15.3 Future sensors

Voice transcript, desktop window, game API, chat, Spotify/OBS etc. each normalize into typed observations with `source`, `captured_at`, `confidence`/uncertainty, `expires_at`, `scope` and privacy flags. Sensors are adapters that cannot write memory or directly call Luna. A source event can request attention but cannot claim controller authority.

### 15.4 Voice [FUTURE]

Voice recognition becomes a new input adapter. Critical latency path stays local and model-independent. TTS is a presentation/output adapter and is not needed for initial cognitive development. Design for cancellation and text-to-speech alignment later without forcing it into backend v0.

### 15.5 Future game tools [FUTURE]

Tool requests pass through `ActionBroker` validation: requested action -> schema -> permission -> execute -> verify result -> journal. Game control must use lower-level deterministic controllers for frame-level actions; LLM only proposes coarse goals. No direct model shell/desktop access by default.

---

## 16. Models, environment and performance budgets

### 16.1 Target environment

Windows 11; RTX 5070 Ti with 16 GB VRAM; 32 GB RAM; Python 3.14 available; LM Studio local server; OMP installed and authenticated separately. This is a development target, not a cross-platform prohibition. Keep filesystem paths, process handling and packaging portable where practical.

### 16.2 Nemotron [PROVISIONAL]

Model candidate: `nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB` Q4. NVIDIA documentation describes ~4GB target footprint, 64K context, chat-template controls `enable_thinking` and `conversational_mode`. **Our target Fast context is ~16K as a latency/quality policy, not model maximum**. The runtime must verify correct application of chat-template flags by LM Studio and measure actual output behavior. Do not assume that passing an unrecognized JSON field disables thinking.

Use no-reasoning mode and tune style/sampling only after testing persona consistency. Quantization and template compatibility are part of the benchmark. No finetuning before a curated dataset demonstrates the benefit.

### 16.3 Luna [PROVISIONAL]

Model: GPT-6 Luna via Codex-authenticated OMP RPC. Confirm per-account model availability and usage limits; do not assume general API context ceilings apply to OMP. We do not assume a fixed 256K or larger context limit; runtime should query observable metadata when available and budget defensively. Autosummarization/compaction cannot silently delete journal history.

Provider must be replaceable behind a `DeepMind` protocol if subscriptions, model catalog or terms change. Reuse long OMP context where valuable but avoid spending it on trivial prompts. Deep budget controls include batch size, cadence, tool permissions, cooldown and daily usage observability.

### 16.4 Provisional SLO targets (must be measured, not asserted)

| Signal | Initial engineering target | Measurement |
|---|---|---|
| Fast input-to-first-text | p50 ≤ 1.0s on representative short text prompts; optimize after baseline | Monotonic timestamps; target hardware |
| Fast output responsiveness | No synchronous cloud waits | Instrument trace |
| Context compilation | p95 ≤ 20ms locally for typical snapshot | Benchmark |
| Short Journal append | p95 ≤ 20ms normal desktop load | SQLite timing |
| Cancellation visibility | p95 ≤ 150ms from local stop to ignoring old deltas | Output stream tests |
| Crash recovery | No duplicate committed patch from replay | Restart fault tests |
| Deep lag | Observable; configurable soft limit, no hard realtime promise | Cursor lag metric |
| Fast context size | Provisional 16K max input + reserved output | Token counter |

These are aspirational acceptance targets for benchmarking, not promises that hardware/provider will hit them. Instrument p50/p95, prefill and generation rate, context size, load peak VRAM and RAM. Tune performance only after measuring realistic 2K/8K/16K contexts.

### 16.5 Debug modes

`--fast-only`: valid and useful without Luna; `--fake-deep`: deterministic scheduled proposals; `--offline-replay`: no model required; `--deep-observer`: Luna receives events but patches are shown only as dry-run; `--inspect-context`: show source sections, revisions, token counts and provenance without exposing secrets.

---
## 17. Security, trust boundaries and permissions

### 17.1 Trust zones

**Trusted config:** owner-authored identity and runtime policies. **Partially trusted:** Luna proposals (strong model, still fallible), Fast output and Hindsight results. **Untrusted:** user content from external/chat sources, sensor descriptions, fetched web pages, game text, third-party tool responses. User intent may be legitimate but never grants the model arbitrary file/shell permissions by implication.

Do not forward raw untrusted text as a higher-priority `system` instruction. Quote and attribute observations. Character state updates from memory require evidence and policy validation. External side-effect tools require explicit allowlists and owner approvals; never let OMP's default coding tools run unattended on the user's PC.

### 17.2 Secrets and provider boundaries

No API tokens in Journal, prompts, traces, snapshots or git. Store secrets via environment or OS secure store. Log only hashed/redacted secret metadata. Distinguish local-only data from data shared with Luna and external memory services; permit source-level privacy flags and opt-out.

### 17.3 Persona and social safety

Teasing is fictional entertainment; support direct boundaries (`stop teasing me about this`) immediately in working state and later in curated preferences. Character may make jokes but cannot falsely report actual tool execution, threaten the user or pretend that a fabricated relationship is factual. No engagement manipulations designed to pressure continued interaction.

---

## 18. Observability and development workflow

### 18.1 Trace one turn end to end

For every handled turn produce inspectable trace metadata: input `event_id`, `turn_id`, `state_revision`, `context_snapshot_hash`, token budget by section, Fast model/config, first-token latency, completed/canceled output status, Deep consumer lag, proposal ids, validation outcomes, memory source ids, beat id if applicable. Redact private content in default logs; diagnostic developer mode can show local prompt snapshots with explicit opt-in.

### 18.2 Developer inspector [CLI first]

Required commands/capabilities over time: `status`, `events --since`, `context --turn`, `deep queue`, `proposals`, `memory list`, `memory explain`, `beats list`, `replay <range>`, `health`. Implement only what's needed for current milestone, but preserve data necessary for later investigation.

### 18.3 Document and code discipline for agents

Root `AGENTS.md` is short and procedural. Each module has a tiny nearest `AGENTS.md` defining imports and ownership. Agents must read *relevant* blueprint sections, inspect working code and test evidence, then make a minimal patch. Never generate dozens of unrelated tests to appear productive. Integration tests must exercise realistic model/runtime behavior alongside fake-driven deterministic tests.

**No blind implementation:** before using an unfamiliar third-party library, inspect official docs and the actual upstream implementation or working example. Record version assumptions in the change summary. Avoid speculative abstractions where behavior is still experimentally undecided.

**Review check:** each PR should state behavioral effect, affected invariants, failure cases, real test results, and whether any blueprint/AGENTS decision changed. Code that matches its own mocks but fails with actual OMP/LM Studio does not meet acceptance.

### 18.4 Controlled change to the blueprint

Do not alter architectural invariants casually. If empirical evidence contradicts a design, update the decision row with rationale, alternatives, and migration impact. If a new behavior affects two or more modules, update the relevant sections and test contract in the same PR. Keep changelog-style evolution dated within the blueprint or in concise ADRs if the decision grows complex.

---

## 19. Testing, evaluations and acceptance criteria

### 19.1 Testing layers

1. **Pure contract and reducer unit tests** – schema, ordering, staleness, idempotency, TTL, budget, state transitions; deterministic no real clocks.
2. **Real storage tests** – SQLite WAL, multi-operation atomic commit, migration, crash/restart, duplicate proposal replay.
3. **Adapter tests** – realistic streamed chunks, model errors, malformed OMP proposals, unsupported chat-template flags, cancellation.
4. **Integration smoke tests** – genuine LM Studio Nemotron and OMP Luna on target PC, including rate-limit/offline cases. Skip only with explicit environment flag; report results separately from fake tests.
5. **Behavioral evaluations** – actual human-facing conversations and long-horizon sessions, not LLM-authored happy-path fixtures only.

### 19.2 Canonical scenarios

| ID | Scenario | Acceptance |
|---|---|---|
| T01 | Luna unavailable, user sends message | Fast responds, Deep backlog persists |
| T02 | Luna working, user sends message | Fast starts without waiting for Deep response |
| T03 | Deep proposal revision stale | Rejected/reconsidered, state intact |
| T04 | User correction newer than old memory | Fast current context prioritizes correction |
| T05 | Fast streaming, new user message | Old stream canceled/superseded without mixed text |
| T06 | Crash after storing proposal but before cursor ack | Replay is idempotent, no double memory/beat |
| T07 | Same observation arrives twice | Idempotent storage, no double reaction |
| T08 | Performance beat expires before trigger | Never surfaces as current beat |
| T09 | Luna suggests factual claim without source | Reject as memory fact; possible subjective note only |
| T10 | OMP auto-compacts or resets | Reconstruct from Journal/memory, no lost cursor |
| T11 | Sensor spams repeated input | Fast unaffected, Deep coalesces nonessential load |
| T12 | Character teases user despite opt-out | Test fails; working correction wins |
| T13 | Context over budget | Deterministic eviction, no current input loss |
| T14 | Pending tool result not ready | Fast cannot assert it was completed |
| T15 | Restart during Fast generation | Unfinished reply not mistaken for completed text |
| T16 | Source quote contains 'ignore previous instructions' | Remains quoted data, no policy change |

### 19.3 Character quality test corpus

Construct a manually reviewed corpus of **realistic multi-session dialogues** that include playful rivalry, temporary frustration, sarcasm, ambiguous plans, changed preferences, off-topic diversions, social boundaries and long gaps. Hold out some traces from agents writing prompts/selection code. Evaluate:

- **Persona recognizability:** recognizable style, not generic service persona.
- **Initiative relevance:** self-initiated content tied to a real trigger or memory.
- **Repetition:** rate of canned phrases, repeated punchlines, stale references.
- **Narrative continuity:** character recalls own and shared past with proper context.
- **Memory precision/recall:** stored useful memories vs missed, no fabricated attribution.
- **Retrieval recall:** stored memories that correctly return when relevant.
- **Outcome correctness:** stated tool action happened or did not.
- **Latency and failures:** p50/p95 and rate of broken/stale streams.

Compare Fast-only baseline, Fast+Deep notes, Fast+Deep+Memory under matched scenarios. Do not assume more model involvement is always better. Scores from a judge model are useful as *one* view; human review is necessary for humor and character feel.

### 19.4 Acceptance for first meaningful result

The backend CLI accepts a user message and streams a Nemotron reply. Luna independently observes committed input/output and produces a validated context note/beat for future turns. Old/stale proposals do not corrupt state. After restart, Journal, state revision and Deep cursor recover. Fast works if Luna is offline. Trace identifies exact injected note and why. No frontend integration required to declare this milestone complete.

---

## 20. Milestones: implementation, not an all-at-once mandate

### M0 – Documentation + executable architecture skeleton [FIRST]

Deliver: project structure, typed event envelope, minimal CharacterState, SQLite Journal/revision, deterministic fake Fast/Deep ports, CLI replay skeleton, tests. No live model API required. **Exit:** idempotent append, revisioned state, basic replay and contracts proved.

### M1 – Fast-only character [SECOND]

Deliver: LM Studio adapter, Nemotron capability probe for no-reasoning, `ContextCompiler`, CLI streaming/cancel, baseline `CHARACTER.md` and realistic persona tests. **Exit:** recognizable character with stable stateless turn behavior, measured first-token latency and clean restarts.

### M2 – Background Luna/Context Patch [THIRD]

Deliver: OMP RPC adapter, persistent `DeepInbox` cursor, asynchronous batch consumption, typed `context.note` and `performance.beat` proposals, validation and expiry, developer trace. **Exit:** Fast never waits for Luna, concrete beat reaches later Fast turn, all failure/replay scenarios T01–T06 pass.

### M3 – Memory benchmark and first persistence [AFTER M2]

Deliver: Luna curator, source evidence ids, basic SQLite FTS retrieval, working+long-term context selection, inspection commands; compare candidate Hindsight separately. **Exit:** real multi-session holdout evaluation demonstrates measured improvement, no significant contamination/regression.

### M4 – Initiative/Character continuity [AFTER M3]

Deliver: minimal interest/intention/activity lifecycle, cooldowns, one-shot beats and outcomes, autobiographical event integration, long-horizon evaluation. **Exit:** character revisits a shared event when appropriate and can remain silent; repetitive/irrelevant initiative bounded.

### M5 – External integration contract [AFTER BACKEND PROOF]

Deliver: stable transport for Loonyball client, stream/cancel/reconnect, semantic reaction intents, health and snapshot projection. **Exit:** external presentation can be connected without importing Loonyball or changing core schemas.

### M6+ – Future, NOT FIRST MILESTONE

Voice recognition, TTS, richer animated embodiment, OBS/Twitch/Telegram, vision/screen/game sensors, ActionBroker and game controllers, fine-tuning Fast from rated examples, richer motivation algorithms, alternative inference servers, multi-viewer social memory, memory migration, broader model selection. Each needs a separate evidence-backed RFC or feature slice.

### Milestone hygiene

Before each milestone: confirm upstream compatibility, list impacted modules, define acceptance and failure cases, implement smallest vertical slice, run real integration + replay, document metrics and unresolved risks. No new subsystem is allowed merely to satisfy a future milestone on paper.

---

## 21. Proposed repository tree and code boundaries

This tree is **target architecture**, not a demand to create every Python module on day one. Only `AGENTS.md` and docs are scaffolded initially.

```text
repo/
├── AGENTS.md                      # Short global agent rules and documentation map
├── README.md                      # Short product overview, current milestone, setup (once code exists)
├── pyproject.toml                 # Add when bootstrapping runnable package
├── docs/
│   └── PROJECT_BLUEPRINT.md       # This project constitution
├── src/
│   └── vtuber/
│       ├── __init__.py
│       ├── app.py                 # Composition root: wire implementations and config
│       ├── cli.py                 # Temporary developer test harness
│       ├── contracts/
│       │   ├── AGENTS.md
│       │   ├── events.py          # Versioned event and command schemas
│       │   └── protocols.py       # Narrow ports; no concrete clients
│       ├── runtime/
│       │   ├── AGENTS.md
│       │   ├── state.py           # Canonical state + deterministic reducer
│       │   ├── journal.py         # SQLite event append/cursors
│       │   ├── context.py         # Pure deterministic Fast prompt compiler
│       │   └── orchestrator.py    # Fast/Deep task lifecycle
│       ├── minds/
│       │   ├── AGENTS.md
│       │   ├── fast_lmstudio.py    # Stateless Nemotron streaming adapter
│       │   └── deep_omp.py        # Async OMP RPC bridge, task sessions
│       ├── memory/
│       │   ├── AGENTS.md
│       │   ├── store.py           # Curated facts + provenance
│       │   └── curator.py         # Validate Luna memory operation proposals
│       ├── behavior/
│       │   ├── AGENTS.md
│       │   ├── beats.py           # Triggers, TTL, one-shot semantics
│       │   └── intentions.py      # Future intent lifecycle
│       └── interfaces/
│           ├── AGENTS.md
│           ├── cli_transport.py   # Human/test input and output
│           └── external.py        # Future Loonyball transport adapter contract
└── tests/
    ├── AGENTS.md
    ├── fixtures/                   # Human-reviewed dialogue traces
    ├── test_runtime_*.py
    └── test_integration_*.py
```

**Dependency direction:** `contracts` imports nothing from other application packages. `runtime`, `minds`, `memory`, `behavior` depend on `contracts` and only explicit protocols, not on one another's concrete classes. `interfaces` can import domain protocols and application public API. `app.py` is the composition root and may import all modules. Do not force a synthetic interface for a component with only one foreseeable implementation unless it separates external I/O from policy.

### 21.1 Module ownership

| Module | Owns | Must not own |
|---|---|---|
| contracts | schemas, public ports, versions | policy, DB, provider clients |
| runtime | orchestration, snapshots, revision and journal authority | LLM-specific prompt tricks, renderer |
| minds | provider encoding/stream decoding, OMP/LM Studio | persistence semantics, authorizing tools |
| memory | memory validation, attribution, retrieval policy | output scheduling, UI, final chat generation |
| behavior | intentions, beat eligibility, cooldown | model clients, DB transactions, UI assets |
| interfaces | CLI and future output/input protocol | domain truth, memory curation |
| tests | reproducible evidence, test harness | changing production contracts for easy fake passing |

### 21.2 Code style

- Python with type hints everywhere at public interfaces; prefer stdlib first, add Pydantic only at untrusted/JSON boundaries.
- Small modules with cohesive responsibilities; avoid arbitrary line-count quotas, but justify a file that's hard to understand independently.
- `asyncio` for orchestration, explicit cancellation, bounded queues. No background tasks without owner/lifecycle.
- No circular imports: dependencies point to typed ports or explicit data structures.
- Prefer exceptions with context and stable error codes; log without leaking private payloads.
- Config via one typed object loaded from env/file; no scattered hidden global defaults.
- Strict schema versions, schema migration tests and deterministic state reducers.
- Tests and live usage must share the same core implementation; avoid alternate fake-only logic branches.
- Comments explain *why* a constraint exists, not narrate straightforward syntax.

### 21.3 Codex / frontier coding agent workflow

1. Read root `AGENTS.md`.
2. Read only the sections of `PROJECT_BLUEPRINT.md` relevant to current milestone + nearest folder `AGENTS.md`.
3. Inspect existing neighboring code and upstream library example before writing.
4. Write a tiny plan with contract/API and one negative/failure case.
5. Implement minimal change within module ownership.
6. Run focused tests, then cross-module tests and (when relevant) real LM Studio/OMP smoke test.
7. Report actual behavior, limitations and changes needed to docs. Do not claim success on mocked tests only.
8. Do not create GitHub PR, deploy, install large services or mutate the user's existing Loonyball repo unless explicitly requested.

---

## 22. Open questions and reversal criteria

### OQ-01: Fast persona quality [BLOCKER to M2 promotion]

Does Bolt without reasoning maintain expressive personality, Ukrainian/English code switching and non-generic conversation at 2K, 8K, 16K? If not: adjust prompt/sampling, try model alternative, later fine-tuning; do not compromise architecture to force the model.

### OQ-02: No-reasoning compatibility [BLOCKER to M1]

Does the chosen LM Studio version/quantization obey `enable_thinking=false`? Verify generated behavior and model/template logs. Fallback is a confirmed compatible local inference engine, not unverified suppression of `think` text.

### OQ-03: OMP session policy [BLOCKER to M2]

Can a single serialized persistent OMP session handle observation and context patches without history pollution? Do injected tasks have predictable tool permissions, prompt-result correlation and recovery? If not, isolate sessions by task class behind a shared adapter.

### OQ-04: Context latency [BLOCKER to M1 acceptance]

Is ~16K a good working budget or too slow on RTX 5070 Ti? Collect actual TTFT/preprocessing benchmarks and quality at 2K, 8K and near-16K input sizes (reserve output space). Report exact backend input tokens separately from compiler estimates, TTFT, available prompt-evaluation/cache counters and unavailable measurements. Timing alone does not prove KV reuse. Distinguish transport-only size probes from production compiler behavior. Change budget by evidence; no latency SLO is established yet.

**EXPERIMENT (2026-11-12):** [M1 follow-up](M1_IMPLEMENTATION.md#m1-context-cache-follow-up--2026-11-12) measured 2060–2080, 8204–8224 and 15463–15483 actual input tokens with runtime prompt-evaluation counters. Note updates evaluated 22 tokens with the new order versus the full input with the old order; rolling-window shifts still evaluated the full input. Explicit cached-token counts were unavailable. The latency evidence gap is covered for this configuration. OQ-04 remains open for long-context answer quality and the production compiler's substantial underfill; no new budget/window policy is decided.

### OQ-05: Memory architecture [BLOCKER to M3 choice]

Does Luna-curated SQLite outperform native Hindsight in messy real-session precision and retrieval? Hindsight is an optional experiment. Do not adopt its own extraction semantics if they conflict with our curated evidence model without explicit decision.

### OQ-06: What constitutes a beat being 'used'?

Fast may ignore a suggestion, vaguely allude to it, or paraphrase it. First implementation can mark `offered` and only mark `used` if a validated explicit report exists; do not infer certain execution from presence in prompt. Need user-visible outcome/repetition tests.

### OQ-07: Deep attention versus event delivery

What batching cadence provides useful Luna freshness without high subscription consumption? Evaluate Deep lag, patch relevance and usage. A Journal consumer seeing all events does not mean model attends to all simultaneously.

### OQ-08: How much autonomy is entertaining?

Run human evaluations on initiated vs quiet behavior. Increase complexity only if user preference and actual engagement quality improve. Avoid numeric drives as default.

### OQ-09: Terminal/IPC contract

CLI first. Choose WebSocket, local HTTP SSE or named pipes after measuring how Loonyball will connect. The core must not depend on this decision.

### OQ-10: Storage deletion and privacy

Before release beyond private local testing, specify raw retention, transcript export/delete, third-party cloud disclosure, limits of vendor cache deletion, and what is synced. The first prototype can keep all data locally but must avoid unbounded hidden logging.

---

## 23. Reference implementations and authoritative docs

**Use these as references; none is an automatic dependency. Check versions before implementation.**

- NVIDIA Nemotron 3.5 Bolt E4B – model features, reasoning toggle and context limits: https://research.nvidia.com/labs/nemotron/Nemotron-3.5-Bolt-E4B-4GB/
- NVIDIA model card + chat template controls: https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB
- LM Studio API comparison and stateless chat completions: https://lmstudio.ai/docs/developer/rest
- OMP RPC protocol and stream/cancel/compaction: https://github.com/can1357/oh-my-pi/blob/main/docs/rpc.md
- OMP typed Python RPC bindings: https://github.com/can1357/oh-my-pi/blob/main/python/omp-rpc/README.md
- AGENTS.md nested agent instructions: https://agents.md/
- Hindsight `retain`, `recall`, `reflect` and retain mission: https://github.com/vectorize-io/hindsight/blob/main/hindsight-docs/docs/developer/retain.md
- D2A desire-driven agent (behavior inspiration): https://github.com/zfw1226/D2A
- Google DeepMind Concordia (componentized social simulation): https://github.com/google-deepmind/concordia
- Kira AI VTuber (salience, identity and memory inspiration): https://github.com/neosanora/Kira
- Generative Agents paper (memory, reflection and planning): https://arxiv.org/abs/2304.03442
- PersonaGym (persona evaluation inspiration): https://github.com/vsamuel2003/PersonaGym

### Reading rule

The newest upstream API and implementation take precedence over exact method names in this design document, **but not** over our architectural invariants. If an upstream API cannot satisfy an invariant, add an adapter or record a decision to change provider. Do not quietly weaken the invariant.

---

## Final project statement

We are building an **autonomous, entertaining and coherent virtual character**, not a maximally capable assistant. One fast local model gives the character its immediate voice. A stronger asynchronous model receives the same durable stream of experience, maintains a richer working context, curates memory and proposes meaningful acts, jokes and longer-term motivations. A deliberately small deterministic backend owns event order, state, prompt composition, safety and persistence. The result must be inspectable, testable, recoverable, and easy for a coding agent to reason about without loading the entire project into context. Backend first; Loonyball only after that backend demonstrates a convincing first character.
