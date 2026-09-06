# LILAVEL-ARAS-M2C / M3A-P1 — Mechanical Enforcement Audit

Status: ACTIVE
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel` — canonical Lilavel repository checkout
Branch / worktree: `feat/conversation-core` — default checkout
Base commit: `b13dd6732506ea0ce8a34c176c8835bfa1925ea8`
Last checkpoint commit: `b13dd6732506ea0ce8a34c176c8835bfa1925ea8`

## Goal

Perform the first real execution-continuity dogfood task: use this record as the
M2C active-work state while completing a read-only first pass of the M3A
mechanical-enforcement audit, then stop at a meaningful midpoint for a fresh
agent to resume under M2D.

## Scope

- Inspect the repository's canonical ownership, conversation, provider/context,
  protocol, lifecycle, persistence/evidence, validation, artifact/worktree,
  security/auth, and future-scope invariants.
- Classify the current enforcement reality and evidence for each material
  invariant family.
- Keep the only mutable repository path in this phase as this active work
  record.

## Non-goals

- Do not implement enforcement, hooks, rules, linters, tests, runtime changes,
  documentation changes, ADRs, configuration, CI, skills, or agents.
- Do not create completed records or commit this work.
- Do not treat reconstructed chat as repository authority or infer future
  AI-streamer requirements.

## Exit criteria

- Major consequential invariant families are inventoried from checked-out
  repository evidence.
- Each material invariant has a current-strength classification, detectable-
  today assessment, enforcement scope, evidence paths/tests, and unresolved
  uncertainty where applicable.
- A small set of consequential gaps or ambiguities is identified without
  designing the future enforcement architecture.
- The final midpoint state, validation state, and exact M3A-P2 continuation are
  durable in this record and reconcile with actual Git state.

## Current implementation state

FACT: M2B's execution-continuity contract is present at `work/README.md` and
the repository navigation pointer is present in `AGENTS.md`.

FACT: At task start, the canonical checkout was clean before this record was
created; branch, base commit, and checkpoint are recorded above.

FACT: The first-pass audit inspected `README.md`, `AGENTS.md`,
`docs/ARCHITECTURE.md`, `docs/STACK.md`, `docs/VALIDATION.md`, all five current
ADRs, the three package READMEs and manifests, Core conversation/runtime/
persistence/protocol/process-containment code, sidecar protocol/server/provider
adapter code, Discord edge/diagnostics code, focused fixtures/tests, Git history,
ignore rules, and tracked diagnostic artifacts.

DECISION: For this audit, `STRONG` means an executable guard plus focused
deterministic tests for the current stated scope; `PARTIAL` means local
guards/tests exist but a cross-package, platform, or reporting gap remains;
`WEAK` means prose/process or narrow local coverage only; `NONE` means no
current deterministic mechanism was found.

RESULT: M3A-P1 has reached its intentional midpoint. The current inventory and
enforcement reality are recorded below. No future hook, rule, linter, schema,
or other enforcement architecture has been selected or implemented.

### First-pass audit inventory

| ID / title | Source / canonical statement | Failure consequence | Current enforcement layer(s) | Strength | Mechanically detectable today | Scope | Evidence paths / tests | Unresolved uncertainty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OWN-01 Dependency direction | Core owns semantics; Discord is downstream; the sidecar is a transport boundary. | Vendor coupling or semantic ownership inversion. | Package/dependency structure; type/interface boundary; prose. | PARTIAL | Yes for current manifests/imports; no dedicated forbidden-import check. | Cross-package; human-process guard remains. | `apps/core/pyproject.toml`, `apps/discord-edge/pyproject.toml`, `apps/discord-edge/src/lilavel_discord_edge/edge.py`, `docs/ARCHITECTURE.md`. | A future direct import or dependency can bypass the current convention without a repository-wide check. |
| OWN-02 Edge/provider semantic ownership | Discord and the sidecar must not own canonical history, provider continuation, or semantic session state. | Divergent histories or hidden provider-owned behavior. | Type/interface boundary; runtime ownership; unit/integration tests; prose. | PARTIAL | Current paths are inspectable and tested; future additions are not structurally blocked. | Cross-package and runtime. | `conversation.py`, `runtime.py`, `apps/model-sidecar/src/index.ts`, `apps/discord-edge/src/lilavel_discord_edge/edge.py`, ADR-001/002/004, `test_edge.py`, `model-sidecar.test.ts`. | `sessionId` is passed to the auth resolver as the request ID while provider stream continuation fields are omitted; the distinction is tested but not enforced by a semantic type. |
| CONV-01 Canonical turn commit | Accepted user input is stored before model execution; only successful completion commits the assistant. | Lost accepted input or false canonical assistant text. | Runtime guard; type/interface boundary; SQLite transaction; unit/integration tests. | STRONG | Yes on the current Core/store path. | Local Core runtime and persistence. | `apps/core/src/lilavel_core/conversation.py`, `persistence.py`, `test_conversation.py` (`accepted_user_survives_generation_failure`, `successful_assistant_is_committed_once`), `test_persistence.py`. | A custom `ConversationStore` implementation remains an interface contract rather than a repository-wide implementation check. |
| CONV-02 Partial, cancelled, superseded, and stale output | Candidate deltas are transient; inactive or cancelled runs cannot publish or commit them. | Stale output enters history or leaks across turns. | Runtime guard; unit/integration/adversarial tests. | STRONG | Yes on current Core and runtime paths. | Local runtime, cross-thread lifecycle. | `conversation.py`, `runtime.py`, `test_conversation.py` (`supersede...`, `explicit_cancel...`), `test_runtime.py`, `test_runtime_adversarial.py`. | Broad scheduler behavior outside the current one-logical-run contract is intentionally not specified. |
| CTX-01 Caller-owned structured context | Core supplies ordered provider-neutral `role`/`text` context and separate trusted guidance with strict bounds. | Malformed, oversized, or untrusted context crosses the boundary. | Type/interface boundary; parser/schema; unit/integration tests. | STRONG | Yes at the current Python and TypeScript boundaries. | Cross-package protocol boundary. | `sidecar_protocol.py`, `conversation.py`, `apps/model-sidecar/src/protocol.ts`, `test_sidecar_protocol.py`, `test_runtime_structured_context.py`, `protocol.test.ts`, `guidance-server.test.ts`. | Guidance is trusted by caller contract; repository-wide provenance of every future guidance producer is not mechanically checked. |
| CTX-02 Provider/session isolation | Provider session state must not silently become semantic history; the sidecar sends caller context on each request and omits continuation fields. | Non-reproducible hidden history and non-replaceable provider coupling. | Runtime adapter; type/interface boundary; unit tests; prose. | PARTIAL | Current absence is tested; arbitrary future provider behavior is not fully detectable without provider-specific evidence. | Cross-package and provider boundary. | `apps/model-sidecar/src/index.ts`, `model-sidecar.test.ts` (`sends structured context...`, `uses the auth resolver boundary...`), ADR-002, `docs/ARCHITECTURE.md`. | No live/provider check was run; `ready`/`health` are explicitly local-state signals, not provider truth. |
| PROTO-01 Strict version-two framing and shape | Active wire contract is UTF-8 JSONL, version 2, exact fields, bounded values, and no duplicate keys. | Ambiguous frames, corruption, or resource exhaustion. | Parser/schema; runtime guard; unit/adversarial tests. | STRONG | Yes within each current parser/encoder. | Local protocol endpoints. | `sidecar_protocol.py`, `apps/model-sidecar/src/protocol.ts`, `test_sidecar_protocol.py`, `protocol.test.ts`, `server.test.ts`, `test_runtime.py`. | The contract is duplicated in two languages rather than generated from one checked schema. |
| PROTO-02 Python/TypeScript compatibility and stdout integrity | Both protocol hosts must accept the same active shapes; stdout is protocol-only and diagnostics use stderr. | One side accepts what the other rejects, or diagnostics corrupt framing. | Parser/schema; protocol writer; package tests; process convention. | PARTIAL | Current constants and shapes match by static inspection and focused fixtures; no always-on cross-language parity gate. | Cross-package and process boundary. | `sidecar_protocol.py`, `apps/model-sidecar/src/protocol.ts`, `server.ts`, `protocol-cli.ts`, `test_runtime_structured_context.py` (Windows-specific Bun probe), `server.test.ts`. | The Bun cross-process check is platform-gated and was not run in this audit; no shared schema/golden corpus was found. |
| LIFE-01 Generation identity and settlement | Core owns IDs/epochs, rejects invalid active transitions, filters stale events, and settles each handle once. | Double settlement, stale output, or unrecoverable active state. | Runtime guard; bounded queue; unit/adversarial tests. | STRONG | Yes on current runtime paths. | Local Core runtime. | `runtime.py`, `test_runtime.py`, `test_runtime_lifecycle.py`, `test_runtime_adversarial.py`, `apps/model-sidecar/src/server.ts`. | The result is deterministic test evidence only; no live-provider lifecycle run was performed here. |
| LIFE-02 Cancellation, cleanup, poisoning, and containment | Replacement waits for prior settlement; uncertain cleanup or containment fails closed; no automatic restart. | Reuse while provider work/descendants remain alive or false clean shutdown. | Runtime guard; sidecar guard; platform-specific process code; adversarial tests; prose. | PARTIAL | Yes for tested Windows/sidecar cleanup paths; not uniform across platforms or uncancelled providers. | Runtime and platform-specific. | `runtime.py`, `process_containment.py`, `apps/model-sidecar/src/index.ts`, `server.ts`, `test_runtime_lifecycle.py`, `test_process_containment.py`, `server.test.ts`, `model-sidecar.test.ts`. | POSIX does not claim Windows descendant containment, and an un-cancelled hung provider has no separate generation deadline. |
| PERS-01 Canonical/evidence atomicity and idempotency | Canonical message and raw provenance evidence commit together; replay is idempotent and conflicting identity/data fails. | Duplicate, lost, or mismatched canonical/evidence records. | Parser/schema; SQLite constraints; transaction; runtime error path; unit tests. | STRONG | Yes on the implemented SQLite store. | Local persistence. | `apps/core/src/lilavel_core/persistence.py`, `test_persistence.py` (`message_and_evidence_replay...`, atomic failure cases), ADR-005. | Multi-process/concurrent database deployment is outside the current store contract. |
| PERS-02 Evidence and durability qualifiers | Evidence remains raw provenance, not semantic memory; default storage is `:memory:` and durable use is explicit. | Provenance becomes hidden memory or restart durability is overstated. | Schema/interface boundary; runtime storage choice; tests; prose. | PARTIAL | Current implementation and tests expose the distinction; future consumers and claims are not blocked. | Local persistence and reporting. | `persistence.py`, `conversation.py`, Core README, ADR-005, `test_persistence.py` (`restart_reopens...`, `evidence_requires...`). | No current memory/retrieval subsystem exists, so future interpretation is an open boundary rather than a tested behavior. |
| VAL-01 Validation truthfulness | Deterministic, live, platform-specific, BLOCKED, and UNVERIFIED claims must remain distinct. | A fixture or local readiness result is reported as live/platform/provider success. | Prose; package probe status values; Git/process convention; narrow tests. | WEAK | Individual probes distinguish some statuses; repository-wide claim accuracy is not mechanically checked. | Cross-package reporting; human-process-only at the report boundary. | `docs/VALIDATION.md`, `apps/discord-edge/scripts/transport_probe.py`, `apps/discord-edge/tests/test_probe.py`, Core/sidecar live scripts. | There is no shared evidence/report schema binding a claim to command, host, and scope. |
| ART-01 Artifact and worktree hygiene | Temporary diagnostics/probes must not silently become canonical tracked state. | Scratch output, sensitive diagnostics, or stale evidence becomes repository truth/noise. | Git/process convention; package `.gitignore` only. | WEAK | Tracked files are visible to Git, but no policy/guard classifies generated artifacts. | Repository-wide; human-process-only. | `apps/core/.gitignore`, `apps/discord-edge/.gitignore`, tracked `apps/discord-edge/edge-08.jsonl`, `edge-10.jsonl`, `edge-11.jsonl`, `edge-12.jsonl`, `edge-http.jsonl`, `probe-http.jsonl`, Discord README. | UNKNOWN: the tracked JSONL files may be intentional evidence or accidental captures; their canonical status is not stated. |
| AUTH-01 Supported authentication boundary | Provider auth is discovered through the supported broker/storage boundary; credentials are not manually extracted or replayed. | Credential leakage or unsupported auth coupling. | Runtime adapter; interface boundary; focused tests; prose. | PARTIAL | Current code path is inspectable and uses supported discovery; no repository-wide bypass guard exists. | Provider boundary and human process. | `apps/model-sidecar/src/index.ts`, `apps/discord-edge/src/lilavel_discord_edge/edge.py`, `AGENTS.md`, `model-sidecar.test.ts`, `test_edge.py`, `test_probe.py`. | Live auth behavior and all future credential consumers remain unverified. |
| AUTH-02 Secret/diagnostic non-disclosure | Diagnostics must omit tokens, message text, URLs, authorization headers, and raw bucket identifiers. | Secrets or private content enter logs/artifacts. | Runtime redaction; unit tests; prose. | PARTIAL | Current Discord diagnostics redaction is tested; no generic secret scanner or hook covers new files. | Local diagnostics and repository-wide process. | `apps/discord-edge/src/lilavel_discord_edge/diagnostics.py`, `test_diagnostics.py`, package READMEs, `.gitignore` files. | Other future diagnostics and tracked probe artifacts have no common enforcement boundary. |
| FUT-01 Future-scope restraint | AI-streamer direction is context only; current requirements come from the repository or explicit decisions. | Speculative product scope drives current architecture or validation. | Prose; ADR/review convention. | WEAK | No reliable mechanical detector found. | Repository-wide human-process-only. | `AGENTS.md`, `README.md`, `docs/ARCHITECTURE.md`, ADR-004. | Future requirements are intentionally not defined; no stronger claim is justified. |

### Strongest established facts/results

- RESULT: Current Core code has one canonical semantic commit path: accepted
  user input is stored before model execution, while assistant text is
  persisted only after a successful active generation. The focused conversation
  and persistence tests cover failure, cancellation, supersession, stale output,
  idempotency, conflict, and atomic-write cases.
- RESULT: The current version-two protocol has strict Python and TypeScript
  parsers/encoders with matching version, shape, bounds, and duplicate-key
  behavior by static inspection and package-local tests. This is not evidence of
  a shared cross-language enforcement mechanism.
- RESULT: Core/runtime and sidecar lifecycle code has explicit identity,
  settlement, cancellation, cleanup, poisoning, queue, shutdown, and Windows
  containment guards with focused adversarial fixtures. The documented POSIX and
  uncancelled-provider limits remain part of the current contract.
- RESULT: SQLite persistence has schema constraints, a transaction-backed
  canonical/evidence commit, idempotent replay, conflict detection, and explicit
  in-memory-versus-file-backed durability behavior.

### Important gaps and open questions for the handoff

- OPEN_QUESTION: Should protocol compatibility remain two independently tested
  implementations, or does the full M3A audit need to evaluate a shared parity
  evidence boundary? No design choice is made here.
- OPEN_QUESTION: Are the six tracked Discord JSONL files durable evidence,
  fixtures, or accidental diagnostic captures? Their repository status is FACT;
  their intended canonical status is UNKNOWN.
- OPEN_QUESTION: What repository-wide check, if any, could detect ownership
  inversion, secret introduction, or validation-claim conflation without
  duplicating canonical architecture prose? M3A-P1 does not choose one.
- UNKNOWN: No live provider, Discord, package, restart, or full Windows test
  result was generated by this audit. The record therefore does not upgrade any
  existing documentation or test fixture into live/platform evidence.
- UNKNOWN: Whether a provider/auth library can introduce semantic continuation
  outside the explicitly inspected options is not established by this static
  audit.

## M2D / M3A-P2 result

RESULT: The fresh-agent reconstruction passed M2D. Live Git state agrees with
the recorded branch, base/checkpoint, and intentional single uncommitted work
record. The record's `UNVERIFIED` and `UNKNOWN` boundaries were preserved; no
historical rationale or accepted enforcement decision was invented.

RESULT: P2 independently re-checked `OWN-01`/`OWN-02`, `CTX-02`, `PROTO-02`,
`LIFE-02`, `PERS-02`, `VAL-01`, `ART-01`, `AUTH-01`, and `AUTH-02`. The six
Discord JSONL files are tracked facts, introduced by `d2a34d8`, but their
intended canonical role remains UNKNOWN; no deletion or reclassification is
authorized by repository evidence.

### Prioritized enforcement backlog — proposals only

- P1 candidates: `PROTO-02` — parser/schema compatibility test with a shared
  version-two golden corpus; `OWN-01` — structural/import boundary test;
  `AUTH-02` — extend the existing diagnostic serializer allowlist tests.
- P1 conditional gate: `ART-01` — first obtain a human disposition for the
  six tracked captures; only then consider a repo-wide Git/artifact hygiene
  rule for generated diagnostic output.
- Medium candidates: `OWN-02`, `CTX-02`, and `AUTH-01` — extend existing
  cross-package/provider-boundary tests only when the boundary changes; do
  not add a generic semantic scanner.
- Leave as explicit process/prose for now: `LIFE-02`, `PERS-02`, `VAL-01`,
  and `FUT-01`. Their remaining risks are either documented current limits or
  human/reporting judgments that the proposed mechanisms cannot determine.
- No P0 candidate or `NONE` row was established. No Codex rule, sandbox or
  permission boundary, lifecycle hook, CI policy, or new runtime guard was
  selected as an invariant mechanism. Any candidate remains a PROPOSAL until
  separately accepted.

OPEN_QUESTION: Whether to accept the protocol corpus, import-boundary,
diagnostic-allowlist, or conditional artifact proposals. Any accepted
mechanism, artifact disposition, new timeout/containment guarantee, reporting
schema, or canonical-doc/ADR change requires a human/design gate before
implementation.

## Remaining work

- Human/design review of the P2 proposal backlog and the tracked-artifact
  disposition.
- If a proposal is accepted, create a separately scoped implementation work
  item and record its accepted decision before changing source, tests, config,
  hooks, CI, or canonical documentation.
- Perform closure/promotion evaluation only for supported FACT/RESULT claims;
  do not promote proposals, hypotheses, or unverified live/platform claims.

## Next safe action

Human review of the P2 proposals and artifact-status UNKNOWN; until a proposal
is accepted, make no runtime/source/test/configuration/hook/CI/docs changes.
If a proposal is accepted, start a separate bounded implementation record.

## Validation

- deterministic: PASS — live preflight and M2D reconciliation captured
  repository root `C:\Lilavel`, branch `feat/conversation-core`,
  HEAD/checkpoint `b13dd6732506ea0ce8a34c176c8835bfa1925ea8`, and exactly this
  untracked active record as the current change.
- deterministic: PASS — the P1 inventory and the P2 gap re-check used checked-
  out canonical docs, package contracts, manifests, source/test evidence, Git
  history, ignore rules, and artifact metadata without changing them.
- deterministic: PASS — `git diff --check`, active-record contract/field checks,
  referenced-path/link checks, and an independent read-only review were run
  after the P2 update.
- deterministic: PASS — the review checked claim/status drift, proposal-to-
  decision promotion, overengineering, incorrect hook/rule/sandbox use,
  duplicated canonical truth, and missing handoff-critical state.
- package/live/provider/platform-specific: UNVERIFIED — no Core, sidecar,
  Discord, provider, restart, or full Windows test was run in this audit.

## Handoff

- Git/checkout state: canonical `C:\Lilavel`; branch
  `feat/conversation-core`; base and last checkpoint
  `b13dd6732506ea0ce8a34c176c8835bfa1925ea8`; live status has been reconciled.
- Uncommitted changes: exactly this active record is intentionally uncommitted;
  the preflight worktree was clean before its creation. No source, runtime,
  tests, docs, ADRs, configuration, hooks, CI, skills, or agents were modified.
- M2D/P2 state: handoff PASS; the P1 inventory was reconstructed and the P2
  backlog was prioritized read-only. All enforcement mechanisms remain
  proposals; none has been designed as an accepted repository decision or
  implemented.
- Blockers/unknowns: no execution blocker; artifact intent, shared protocol
  parity adoption, repository-wide reporting/ownership/secret boundaries, and
  provider/live/platform claims remain unresolved or UNVERIFIED. Human/design
  review is required before any consequential implementation.
- Exact continuation: human review of the proposal backlog; if accepted,
  create a separate bounded implementation record, otherwise perform supported
  closure/promotion evaluation without broadening scope.
- Next safe action: the human-review action stated above; do not edit another
  path or implement enforcement in this work item.

RESULT: M2D — Fresh-Agent Handoff Eval is PASS, and M3A-P2 read-only
gap-prioritization/design analysis is complete. The record remains ACTIVE
because proposal acceptance, implementation scope, and closure/promotion have
not been decided. No commit was created.
