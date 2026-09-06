# LILAVEL-ARAS-M4B — Runtime Evidence Model

Status: COMPLETED
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel` - canonical Lilavel repository checkout
Branch / worktree: `feat/conversation-core`
Base commit: `fdbd66d2c22b88afe1540f6301f8130efc988fff`
Last checkpoint commit: `fdbd66d2c22b88afe1540f6301f8130efc988fff`

## Goal

Define the minimum agent-readable runtime evidence and correlation contract
needed for a fresh Codex agent to explain one Lilavel interaction without
broad source archaeology, while preserving semantic ownership, privacy
boundaries, and validation semantics.

## Scope and non-goals

- Read-only verification of the completed M4A baseline against current Core,
  model-sidecar, Discord-edge, fixture, test, and architecture surfaces.
- A bounded runtime evidence model, evidence tiers, boundary responsibilities,
  replay/debug interface requirements, design alternatives, and M4C slices.
- No runtime, source, test, canonical documentation, config, hook, CI,
  observability-platform, replay-tool, provider/auth, Discord identity, voice,
  streamer, or memory implementation.

## Preflight and M4A verification

- Actual current checkout: `C:\Lilavel`.
- Actual branch: `feat/conversation-core`.
- Actual HEAD/origin: `fdbd66d2c22b88afe1540f6301f8130efc988fff`.
- Worktree/index were clean before the permitted M4B record was created; no
  unrelated changes were present.
- The committed M4A record is present at
  `work/completed/LILAVEL-ARAS-M4A-runtime-legibility-baseline.md`.
  Its historical base is `a7d0b8c`; the current HEAD is the later commit that
  added the committed M3D/M4A records. M4B used current source and Git state,
  not the historical SHA as an assumption.
- Current deterministic validation: Core `118 passed`; sidecar typecheck and
  `64 passed`; Discord edge `62 passed` with the existing `audioop`
  deprecation warning only.
- Live/provider/Discord evidence was not attempted. Missing credentials remain
  `BLOCKED`/live evidence unavailable, not a repository design failure.

### Verified M4A findings

- `ConversationCore` owns `scope_id`, `run_id`, canonical message IDs,
  assistant commit, and semantic terminal status. `ModelRuntime` owns
  `generation_id`, `epoch`, admission, physical cancellation, terminal
  settlement, fail-closed poisoning, and local health state.
- Core protocol V2 carries only generation identity (`generation_id`, `epoch`)
  across the process boundary. It carries no `run_id`, `scope_id`, or message
  identity. This is intentional semantic separation, but it leaves the join
  implicit.
- The sidecar already has a typed internal observer with `requestId` (the
  sidecar-local name for the Core-supplied generation identity), `epoch`, local
  monotonic timing marks, provider/model/API metadata, event classes, and safe
  counts. The protocol server uses the observer to drive protocol frames; Core
  does not retain or expose a cross-boundary diagnostic bundle.
- Core has no retained/queryable lifecycle trace. `health()` is a current
  runtime snapshot, not a lifecycle history, and Core drains sidecar stderr.
- Fixtures cover successful streaming, cancellation, supersession, late
  deltas, malformed frames, process failure, cleanup poisoning, and SQLite
  restart, but they are test-oriented. There is no documented offline
  conversation runner, fake-sidecar CLI, or local fake Discord end-to-end
  command.
- Discord diagnostics retain safe presenter/HTTP timing events with local
  `flush_id`, `operation_id`, and HTTP `request_id`. They intentionally omit
  message text, headers, bodies, exception messages, channel IDs, and Discord
  message IDs; they currently have no semantic Core run correlation.
- Existing canonical `evidence_records` are provenance rows linked to
  canonical messages and intentionally are not a runtime event log.

## Minimal identity and correlation contract

### Identity classifications

| Identity | Meaning / owner | Created and propagated | Persistence | Diagnostic use | Minimal-chain rule |
| --- | --- | --- | --- | --- | --- |
| `scope_id` | Provider-neutral semantic/persistence scope owned by Core/store | Caller or `ConversationCore`; Core history/store only | Durable with file-backed store; ephemeral for `:memory:` | Core trace only by default; caller-supplied values are not automatically safe to export | Root of Core evidence; must not enter sidecar or Discord diagnostics by default |
| `user_message_id` | Durable Core canonical user-message identity | Core on `start_turn`; store writes it immediately | Canonical and durable when the store is durable | Safe as an opaque Core ID | Required on `turn_accepted`; never a provider or Discord identity |
| `run_id` | One semantic turn and its transient assistant candidate | Core on `start_turn`; presentation edge may receive it from `ConversationRun` | Process-lifetime only unless a future separate runtime artifact records it | Safe as an opaque allowlisted correlation key | Required on every Core semantic event and the edge presentation context |
| `assistant_message_id` | Core candidate identity reserved for a successful assistant commit | Core on `start_turn`; store accepts it only on commit | Durable only if assistant output commits canonically | Safe as an opaque Core ID | Required on commit evidence; reservation alone is not a canonical commit |
| `generation_id` | One physical runtime generation | `ModelRuntime.generate`; sent through V2 protocol | Ephemeral | Safe opaque runtime key | Required with `epoch` for physical/runtime and sidecar evidence |
| `epoch` | Monotonic generation discriminator used for stale-event rejection | `ModelRuntime` | Ephemeral | Safe numeric runtime key | Required with `generation_id`; not semantic history |
| sidecar `requestId` | Sidecar-local request label; current protocol server sets it equal to `generation_id` | `ModelSidecar.generate` / identity passed by server | Ephemeral | Use only as a namespaced sidecar alias | Must not become a second canonical identity or be persisted |
| `evidence_id` | Durable provenance row for a canonical source message | SQLite store when canonical message is written | Durable with `evidence_records` | Safe opaque provenance key | Optional only after canonical source exists; not required for failed/partial runs |
| Discord `flush_id` / `operation_id` / HTTP `request_id` | Edge-local presentation and HTTP diagnostic sequence IDs | Discord diagnostics instance | Process-lifetime only | Safe in existing allowlisted edge diagnostics | Join to `core_run_id` at the edge; never enter Core |
| Discord channel/message IDs | Transport admission/dedupe and remote presentation metadata | Discord edge/API | Edge-local/in-memory in current slice | Not in current diagnostic allowlist | Must remain edge-local; never become semantic conversation identity |
| Provider/session/request IDs | External provider transport identity | Provider/sidecar boundary | Live/external only | Optional external evidence, redacted and non-canonical | Must not cross into Core semantic state or drive product behavior |

### Minimal graph

```text
scope_id
  └─ user_message_id ── turn_accepted
       └─ run_id ── generation_bound ── generation_id + epoch
            ├─ sidecar requestId (alias only) ── sidecar diagnostic events
            ├─ cancel_requested / delta_discarded / generation_terminal
            ├─ assistant_message_id ── assistant_commit ── evidence_id (if committed)
            ├─ run_terminal
            └─ edge core_run_id ── flush_id ── operation_id ── HTTP request_id
```

Correlation is a join, not an ownership transfer. The Core trace maps
`run_id` to `generation_id`/`epoch`; the sidecar needs no semantic ID in its
wire protocol; the edge receives only the semantic run correlation needed to
label its own presentation diagnostics. Discord/provider IDs remain leaves.

## Minimum lifecycle evidence vocabulary

These are typed records for a narrow lifecycle trace, not a generic event bus.
Common fields are a local sequence number, owner/source, monotonic observation
time, and only the correlation IDs allowed for that source. No record contains
raw prompt, delta, or exception text by default.

| Fact/event | Owner and emission point | Required fields | Persistence / availability | Existing signal |
| --- | --- | --- | --- | --- |
| `turn_accepted` | Core immediately after the user canonical append and run creation succeed | `scope_id`, `run_id`, `user_message_id`, reserved `assistant_message_id`, optional predecessor/superseded run ID | Ephemeral runtime evidence; deterministic with fake runtime and SQLite | Derivable from `start_turn` and canonical store, but not retained as a run record |
| `generation_bound` | Core when `runtime_generate()` returns the physical generation handle | `run_id`, `generation_id`, `epoch` | Ephemeral; deterministic offline | Derivable from the private run/runtime bridge; currently not queryable afterward |
| `cancel_requested` | Core on the first semantic cancel/supersede request | `run_id`, reason `cancelled` or `superseded`, optional generation identity | Ephemeral; deterministic | Derivable from `ConversationRun.request_cancel()` and runtime cancel calls |
| `delta_discarded` | Core/runtime when late, cancelled, stale, or non-current output is rejected; aggregate per generation/reason | `run_id` if known, `generation_id`, `epoch`, discard reason, count, byte count | Ephemeral; deterministic with fixtures; no text | Current guards return/drop the delta but retain no count or reason |
| `generation_terminal` | `ModelRuntime` after physical completion/cancellation/failure settlement | `generation_id`, `epoch`, physical status, normalized failure domain/code when known, discard summary if available | Ephemeral; deterministic for fixtures; process/Windows/provider details retain their stated limits | Derivable from handle/protocol events, but not retained as a lifecycle trace |
| `assistant_commit` | Core around the SQLite assistant commit point, claiming `committed` only after the store write succeeds | `run_id`, `assistant_message_id`, outcome `committed`/`not_committed`/`persistence_failed`/`superseded`/`cancelled`, optional `evidence_id` after commit | Ephemeral link to canonical/provenance records; deterministic local persistence | Derivable from canonical rows, evidence rows, and outcome, but not linked in one runtime record |
| `run_terminal` | Core when `ConversationRun` settles | `run_id`, semantic status `completed`/`cancelled`/`superseded`/`failed`, optional generation identity, canonical-commit outcome, safe failure domain/code | Ephemeral; deterministic with fake/fixture runtime | Derivable from terminal semantic event/outcome, but not retained after the run |
| `presentation_outcome` | Discord edge after presenter completion/interruption/failure, if presentation exists | `core_run_id`, presentation status, safe counts, local last flush/operation IDs when available | Edge-local opt-in diagnostics; deterministic with fake sink; live HTTP remains live | Presenter and diagnostics know this locally, but currently lack Core correlation |

Failure domains are normalized only where current signals support them:
`protocol` (`ProtocolViolation`/`protocol_error`), `process`
(`SidecarCrashed`/pipe/exit), `provider-facing` (sidecar-reported provider
code, without claiming root cause), `cleanup` (cleanup/cancellation/shutdown
timeout or error), `persistence` (`PersistenceError`), `semantic` (Core
admission/context/settlement), and `unknown`. Raw exception messages, stack
traces, provider bodies, and tokens are never required fields.

`run_terminal` is deliberately separate from `generation_terminal`: a physical
completion does not prove that Core accepted the result. Supersession,
cancellation, stale output, or a persistence failure can prevent canonical
assistant commit.

## Evidence tiers

| Tier | Authority and lifetime | Storage and allowed content | Partial/sensitive data | Product semantics |
| --- | --- | --- | --- | --- |
| Canonical semantic state/history | Core/store; in-memory or durable according to configured store | `conversation_messages`, Core message IDs, roles, order, canonical text | Full canonical user/assistant text is allowed only under the existing canonical contract; partial candidate text is not canonical | Yes; sole semantic authority |
| Durable provenance evidence | Core/store; same durability as the canonical source | Existing `evidence_records`: `evidence_id`, source message ID/role, provenance kind, timestamps; no text copy | No partial text; no new secrets or interpretation | No; provenance only, per ADR-005 |
| Ephemeral runtime diagnostic evidence | Owning Core/runtime/edge component; bounded to the process or exported run | Typed lifecycle IDs, statuses, codes, timestamps, counts/byte lengths, safe provider/model metadata, local edge IDs | No raw partial text/deltas by default; no auth headers/tokens/bodies or exception messages | No; never update history, cancellation semantics, or product state |
| External/live evidence | Provider/sidecar/Discord service as observed by its edge; operation/process lifetime | Redacted provider/Discord status and local diagnostics; external references only if explicitly allowlisted | No credentials or raw payloads; response/session IDs remain external and non-canonical | No; live evidence cannot become deterministic proof |

Runtime diagnostics must not be inserted into the current `evidence_records`
table: that table requires a canonical source and has provenance semantics, not
execution-trace semantics. If durable runtime capture is later needed, it must
be a separately approved artifact/schema.

## Core evidence boundary

### Compared mechanisms

Scores use 1–5; higher is better for agent readability, correlation quality,
testability, and lower-risk qualities. For complexity, coupling, privacy risk,
and maintenance, lower is better.

| Option | Complexity | Runtime coupling | Agent readability | Correlation | Privacy risk | Testability | Maintenance | Disposition |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A. Synchronous structured observer callback plus existing sidecar/Discord diagnostics | 3 | 2 | 3 | 4 | 2 | 5 | 3 | Viable adapter seam, but a subscriber must be attached before events occur |
| B. Bounded in-memory Core lifecycle trace with read-only snapshot | 2 | 1 | 5 | 4 | 2 | 5 | 2 | Recommended Core surface |
| C. Unified repo-local JSONL diagnostic sink | 5 | 5 | 5 | 5 | 5 | 3 | 5 | Reject: premature sink/platform design, I/O/privacy coupling, and no need for a generic event bus |

Recommendation: use B as the narrow Core contract. Append typed records after
the owning state transition to a bounded, thread-safe, read-only snapshot. A
future thin exporter or deterministic runner may subscribe/read the snapshot,
but an exporter must never be able to block or alter lifecycle settlement.

Do not write Core evidence to sidecar stdout (protocol-only) or rely on Core
stderr as the primary query surface (currently drained, unordered, and not a
safe schema). Reuse `health()` for the current snapshot only; reuse existing
semantic/runtime event objects as source signals, not as the retained evidence
store. A fixed bounded trace is necessary for post-run fresh-agent debugging;
durable trace storage is not necessary for M4B.

## Sidecar boundary recommendation

- Keep the V2 wire contract unchanged for M4B: `generation_id` and `epoch` are
  sufficient for Core↔sidecar correlation. Do not put `run_id`, `scope_id`,
  canonical message IDs, or Discord IDs in the protocol.
- Project the existing sidecar observer into safe diagnostic records using
  `generation_id`/`epoch` names. Treat internal `requestId` as an alias, not a
  new identity. Retain event class, relative marks, provider/model/API names,
  provider event class, error code, and safe lengths/counts where needed.
- Do not capture raw `text_delta` from the observer in a diagnostic export.
  The protocol stream is the transport of candidate output; a diagnostic
  projection records only counts/lengths by default.
- Provider `sessionId`/response/request references remain sidecar/provider
  transport evidence. The current resolver receives the sidecar request label,
  but that does not make it semantic conversation identity.
- `ready`/`health` remain local readiness facts and do not prove provider
  endpoint, quota, entitlement, or successful live interaction.

## Discord boundary recommendation

- Add only an edge presentation context keyed by `core_run_id` (the existing
  `ConversationRun.run_id`) to future allowlisted diagnostics. This joins
  existing `presenter_flush_id` → `operation_id` → HTTP `request_id` records to
  Core without reversing ownership.
- A `presentation_outcome` summary may report safe status/counts and local IDs;
  it must not report message text, raw errors, headers, bodies, channel IDs, or
  Discord message IDs by default.
- Discord channel/message IDs remain edge-local admission/dedupe/presentation
  metadata. They must not enter Core history, model requests, Core traces, or
  canonical identity. No Discord ID is needed for the minimal semantic chain.
- Any new `core_run_id`/optional Core message-ID fields require explicit
  AUTH-02-style per-event allowlist updates and adversarial sentinel tests.
  No generic scanner or broad logging API is required.
- Current token handling and `AllowedMentions.none()` behavior remain outside
  the evidence contract. Missing bot credentials remain `BLOCKED`.

## Thin deterministic replay/debug interface requirements

This is a future runner contract, not an implementation in M4B. It should be
a bounded scenario selector over existing fixtures, not a general simulator.
Use JSON input and JSONL output. The runner must keep the sidecar protocol
pipe separate from the agent-readable evidence stream.

Common input: scenario name, synthetic turn text/actions, fixture mode, and an
optional temporary file-backed SQLite path for restart. Common output: one
metadata line with scenario and evidence status, ordered safe evidence records,
and one summary line containing semantic outcome, canonical-commit state,
failure domain/code, and explicit `unknown`/`live` fields. Do not echo raw text
or partial deltas by default.

| Scenario | Existing reusable surfaces | Minimum inputs | Minimum output | Availability |
| --- | --- | --- | --- | --- |
| Successful generation | Core `FakeRuntime`/structured fixture; conversation/persistence tests | One synthetic user turn and deterministic response fixture | `turn_accepted`, `generation_bound`, physical completed, assistant committed with canonical/evidence IDs, `run_terminal=completed` | Deterministic/offline |
| Cancellation | Core conversation tests and `structured_sidecar.py`/`fake_sidecar.py` cancellation mode | One turn, one partial fixture delta, cancel action | `cancel_requested=cancelled`, any discarded-delta summary, physical cancelled, no assistant commit, `run_terminal=cancelled`; no partial text | Deterministic/offline |
| Supersession | Core supersession test plus `fake_sidecar.py`/adversarial fixture | Two turns with a cancellation gate | Old run `cancel_requested=superseded`, late discard, old `run_terminal=superseded`; new run completion/commit; predecessor link | Deterministic/offline |
| Malformed sidecar frame | `fake_sidecar.py malformed-after-accepted`, Core runtime/protocol tests | Fixture mode and one turn | `generation_terminal=failure`, `failure_domain=protocol`, Core/runtime failed state, no assistant commit; exact safe code only | Deterministic/offline |
| Sidecar crash/poisoning | `crash-after-accepted`, `cleanup-timeout`, `cancel-never-terminal`, adversarial fixtures | Failure mode and bounded timeout | Process or cleanup failure classification, poisoned/non-reusable state, one terminal result, no recovery claim unless a separate recovery action is exercised | Deterministic; containment details platform-specific |
| Persistence restart | `SQLiteConversationStore` restart tests | Durable temp DB, stable `scope_id`, success then partial cancel | Pre/post restart canonical IDs/order and provenance IDs; user survives; partial assistant absent; runtime trace marked ephemeral | Deterministic local SQLite |
| Interrupted Discord presentation | Fake channels/sinks, presenter and diagnostics tests | One correlated run, injected sink error/cancellation during flush/edit | `presentation_outcome=interrupted` or `transport_error`, flush/operation/request IDs, no raw payloads, Core canonical state unchanged | Deterministic fake edge; live delivery unverified |

Tests remain tests and runtime traces remain runtime evidence. A runner result
must state which fixture/surface produced it; fixture output must not be
presented as live provider or live Discord evidence.

## Safety, privacy, and epistemic constraints

- Never emit raw auth headers, tokens, cookies, API keys, or session secrets.
- Do not emit raw user text, assistant deltas, partial candidate output,
  provider payloads, response bodies, URLs, or exception messages by default.
  Counts, byte lengths, safe enum values, and types are sufficient.
- Do not represent provider/session/request IDs as semantic identity; do not
  represent Discord channel/message IDs as canonical conversation state.
- Do not promote partial, cancelled, superseded, failed, stale, or interrupted
  assistant output into canonical history.
- Live/provider/Discord evidence stays live evidence; it is not deterministic
  proof. `ready`/`health`, a fixture pass, or a screenshot cannot establish
  live provider, restart, or Discord delivery behavior.
- `scope_id` may be caller-supplied; it is Core evidence only unless an
  explicit future redaction/allowlist decision makes external export safe.
- Any future capture of sidecar observer events must use a positive projection
  allowlist and strip `text_delta.delta` before export. Any new Discord fields
  must be added to explicit AUTH-02 event allowlists and sentinel tests.
- No generic event bus, telemetry platform, replay service, provider expansion,
  voice/streamer/memory surface, or broad repository scanner is justified by
  this contract.

## Recommended minimal Runtime Evidence Contract

1. Core owns and retains a bounded, in-memory typed trace with
   `turn_accepted`, `generation_bound`, `cancel_requested`,
   `delta_discarded`, `assistant_commit`, and `run_terminal` facts.
2. `ModelRuntime`/sidecar evidence reports physical generation events keyed by
   `generation_id`+`epoch`; Core joins them to `run_id` through
   `generation_bound`. `requestId` is a sidecar alias only.
3. Canonical messages and `evidence_records` remain the only durable semantic
   and provenance authorities. Runtime evidence is not stored there.
4. The Discord edge adds `core_run_id` only to an explicit safe diagnostic
   context and keeps flush/HTTP IDs edge-local. Channel/message/provider IDs
   never cross into Core semantics.
5. A future offline JSONL runner exercises only the named deterministic
   scenarios, emits safe ordered evidence plus status/unknown fields, and
   clearly separates deterministic, platform-specific, and live evidence.

This is the narrowest contract that lets a fresh agent answer accepted-turn,
physical-generation, cancel/supersede, late-discard, canonical-commit,
failure-domain, persistence, and presentation-correlation questions without
turning Lilavel into an observability platform.

## M4C slicing recommendation

| Slice | Goal and owned surfaces | Dependencies / validation | Human gate / parallelism |
| --- | --- | --- | --- |
| M4C-1 Core semantic trace | Core lifecycle records and bounded snapshot in `apps/core/src/lilavel_core/conversation.py` plus the smallest focused tests | Contract approval; Core success/cancel/supersede/failure/persistence tests; prove no raw text | Gate identity/privacy/commit semantics; can parallelize with M4C-2 and M4C-3 only in disjoint worktrees after contract freeze |
| M4C-2 Physical generation evidence | Runtime generation binding/discard summary and safe projection of the existing sidecar observer in Core/runtime and sidecar-owned surfaces | M4C-1 field contract; protocol tests, malformed/crash/poison fixtures; preserve stdout protocol and provider-neutral boundary | Gate failure-domain/late-delta semantics; parallelizable with M4C-3 after shared contract, otherwise serialize shared exports |
| M4C-3 Discord presentation correlation | Edge-local `core_run_id` context and `presentation_outcome` projection in Discord edge diagnostics/presenter tests | M4C-1 contract; AUTH-02 allowlist/sentinel tests; fake sink interruption tests; no channel/message IDs | Gate redaction and replaceable-edge ownership; parallelizable with M4C-1/2 in isolated paths |
| M4C-4 Thin deterministic runner | One bounded scenario runner over existing fixtures with JSONL evidence/summary output | M4C-1/2/3 stable contracts; all seven scenarios, explicit status classification, no raw content | Gate fresh-agent usability; serialize after the boundary slices |
| M4C-5 Runtime-evidence evaluation | Fresh-agent question matrix and evidence completeness/ambiguity checks | M4C-4 output; deterministic only, with live/provider/Discord remaining blocked or unknown | Human `PASS | REVISE | BLOCKED`; do not expand scope from failed live access |

Default recommendation: freeze the contract and then use one writer per owned
surface. M4C-1/2/3 may be independently reviewed or implemented in isolated
worktrees; integration and evaluation remain serialized. No slice should add a
platform telemetry dependency or modify canonical history semantics.

## Exit and handoff

- M4B exit criteria: SATISFIED for the read-only design scope.
- Runtime/source/tests/docs/config/hooks/CI: unchanged by M4B.
- Permitted work-record transition: active record moved to this completed
  record; it is intentionally uncommitted.
- Current Git after closure: only the untracked completed M4B work record is
  expected; nothing is staged and no unrelated changes are present.
- Live provider, live Discord, external restart, and full end-to-end evidence:
  `BLOCKED` or `UNVERIFIED` as applicable; not promoted by this design.
- Next safe action: human review of the identity/evidence contract, then an
  explicitly authorized M4C implementation slice.
