# LILAVEL-ARAS-M3B — Mechanical Enforcement Design

Status: ACTIVE
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel` — canonical Lilavel repository checkout
Branch / worktree: `feat/conversation-core` — default checkout
Base commit: `8095aba481a3815d00990c985537a86963e803d2`
Last checkpoint commit: `8095aba481a3815d00990c985537a86963e803d2`

## Preflight

- `FACT`: repository is the canonical `C:\Lilavel` checkout.
- `FACT`: branch is `feat/conversation-core`.
- `FACT`: HEAD is `8095aba481a3815d00990c985537a86963e803d2`, `Complete M3A mechanical enforcement audit`.
- `FACT`: `git status --short --branch` was clean at task start; the branch is one commit ahead of `origin/feat/conversation-core`. The ahead commit is prior committed work, not an unrelated working-tree change.
- `FACT`: completed M3A record is present at [`work/completed/ARAS-M3A-mechanical-enforcement-audit.md`](../completed/ARAS-M3A-mechanical-enforcement-audit.md).
- `FACT`: no `work/active/` record existed at task start.
- `FACT`: unrelated working-tree/index changes at task start: none.

## Goal

Design the smallest deterministic enforcement set with the highest practical
ROI for the current Lilavel failure modes and gaps. Preserve the existing
Core/provider/transport ownership boundaries and leave implementation for a
human-reviewed M3C phase.

## Scope

- Evaluate the M3A candidates `PROTO-02`, `OWN-01`, `AUTH-02`, `CTX-02`,
  `OWN-02`, `AUTH-01`, `LIFE-02`, `PERS-02`, `VAL-01`, `FUT-01`, and `ART-01`.
- Inspect the current protocol parsers, package manifests/import topology,
  diagnostics serializers/tests, provider-adapter boundary, lifecycle tests,
  persistence/validation qualifiers, and tracked artifacts.
- Select one required disposition for every candidate.
- Define a bounded future M3C contract for each `IMPLEMENT_NOW` proposal.
- Create and maintain this active work record only during M3B.

## Non-goals

- No runtime, source, test, package, configuration, hook, CI, rule, sandbox,
  permission, canonical-doc, ADR, or ignore-rule implementation in M3B.
- No M3A inventory rewrite, historical-rationale invention, live/provider,
  restart, Windows, Discord, or package-level validation run.
- No artifact deletion, reclassification, ignore-rule change, or path cleanup.
- No generic secret scanner, schema generator, Codex lifecycle hook, or CI
  policy selected merely because it is available.
- No commit.

## Exit criteria

- Every required M3A candidate has exactly one allowed disposition and an
  explicit ten-part justification.
- The implementation shortlist contains no more than four mechanisms and is
  ranked by consequence, detectability, recurrence, false-positive risk,
  maintenance cost, and current architectural importance.
- `PROTO-02` has a bounded cross-language corpus design covering accepted and
  rejected frames, versioning, fixture ownership, duplicated schema truth, and
  stdout/stderr framing boundaries.
- `OWN-01`, `AUTH-02`, `CTX-02`, and `ART-01` receive the requested special
  analysis without claiming more than deterministic evidence establishes.
- Every `IMPLEMENT_NOW` proposal has a bounded M3C contract, acceptance
  criteria, validation, non-goals, rollback/revisit condition, and independence
  assessment.
- M3C work-item structure is selected from coupling and validation boundaries.
- Read-only review finds no overengineering, wrong-layer enforcement,
  proposal-to-decision drift, duplicated canonical truth, ungrounded severity
  or recurrence claims, excessive shortlist size, or artifact-gate bypass.

## Current implementation state

`PROPOSAL`: M3B design only. The repository has no enforcement changes from
this item. Existing enforcement remains authoritative until a human accepts a
future M3C work item. This record is the only intended uncommitted change.

Current repository evidence includes two independently maintained version-two
protocol implementations at
`apps/core/src/lilavel_core/sidecar_protocol.py` and
`apps/model-sidecar/src/protocol.ts`, each with package-local tests; Core has
no runtime dependency on the Discord edge while the edge declares
`lilavel-core`; Discord diagnostics already use a narrow safe-field recorder
and adversarial sentinel tests; and provider/session isolation is already
asserted at the adapter boundary. These are checked-out facts, not new
canonical decisions.

## Candidate disposition summary

| Rank | Candidate | Disposition | Lowest appropriate mechanism | Worth implementing now |
| ---: | --- | --- | --- | --- |
| 1 | `PROTO-02` | `IMPLEMENT_NOW` | Shared language-neutral parser compatibility corpus plus existing framing tests | Yes |
| 2 | `OWN-01` | `IMPLEMENT_NOW` | Package-local AST import-boundary test | Yes |
| 3 | `AUTH-02` | `IMPLEMENT_NOW` | Existing serializer/event tests extended with exact allowlists and adversarial sentinels | Yes |
| — | `CTX-02` | `KEEP_EXISTING_ENFORCEMENT` | Existing provider-adapter contract tests and explicitly bounded live probe | No new mechanism now |
| — | `OWN-02` | `KEEP_EXISTING_ENFORCEMENT` | Existing Core conversation/persistence tests and ownership ADR | No new mechanism now |
| — | `AUTH-01` | `KEEP_EXISTING_ENFORCEMENT` | Supported auth-discovery/resolver boundary and tests | No new mechanism now |
| — | `LIFE-02` | `KEEP_EXISTING_ENFORCEMENT` | Existing cleanup, poisoning, lifecycle, and containment tests | No new mechanism now |
| — | `PERS-02` | `PROCESS_ONLY` | Scoped evidence/claim reporting | No machine mechanism now |
| — | `VAL-01` | `PROCESS_ONLY` | Validation report and work-record discipline | No machine mechanism now |
| — | `FUT-01` | `PROCESS_ONLY` | Human scope review against current repository authority | No machine mechanism now |
| — | `ART-01` | `HUMAN_GATE` | Human artifact-intent decision before any hygiene rule | No |

The three-item shortlist is intentionally small. No hook, rule, sandbox,
permission, or CI job is selected as an invariant engine. CI may execute future
deterministic checks after their local contracts exist, but CI is not itself a
selected mechanism.

## Candidate evaluations

### `PROTO-02` — Python/TypeScript protocol parity and stdout integrity

Disposition: `IMPLEMENT_NOW` (`PROPOSAL`, pending human review before M3C).

1. Invariant/failure mode: Python Core and the Bun host must agree on accepted
   and rejected version-two JSONL command/event semantics, strict fields,
   duplicate handling, bounds, identity, and version rejection. The protocol
   host must emit one newline-delimited protocol frame per stdout record;
   human diagnostics must stay on stderr.
2. Consequence if violated: a valid request can be rejected, an invalid or
   future frame can alter lifecycle state, or stdout pollution can make Core
   fail closed or misread a generation boundary.
3. Existing enforcement: full parsers exist in
   [`apps/core/src/lilavel_core/sidecar_protocol.py`](../../apps/core/src/lilavel_core/sidecar_protocol.py)
   and [`apps/model-sidecar/src/protocol.ts`](../../apps/model-sidecar/src/protocol.ts).
   Local parser tests cover round trips, structured context, guidance, bounds,
   duplicate fields, invalid versions, malformed frames, and UTF-8 chunking.
   `server.ts` owns protocol-only output; Core separates stdout and stderr;
   runtime and server tests cover malformed/truncated framing and output
   backpressure.
4. Residual gap: the two parsers have no shared language-neutral corpus, so
   local tests can remain green while a new field, limit, error classification,
   or version case drifts. Existing stream tests are package-local rather than
   a single cross-language acceptance surface.
5. Proposed mechanism: add a small versioned `testdata/protocol-v2/cases.json`
   corpus containing raw command/event frames and expected `accepted` or
   `rejected` outcomes, with normalized values and stable error reasons only
   where the reason is part of the wire contract. Load it from the existing
   Python and Bun protocol tests. Keep framing assertions in the existing Core
   `_iter_frames`/runtime tests and sidecar `readProtocolLines`/server tests;
   add only the narrow raw-line assertions that are missing.
6. Lowest appropriate layer: a shared parser/schema compatibility test is the
   executable layer that sees both implementations. A hook, rule, sandbox, or
   CI-only check cannot detect semantic parser drift more directly. The
   corpus is test data, not a replacement schema.
7. Expected false-positive risk: low. Raw fixtures preserve duplicate keys,
   numeric spellings, and malformed input without asking a generic JSON parser
   to rewrite them. Error-reason assertions should be limited to stable
   taxonomy cases; broad text-message equality is intentionally excluded.
8. Maintenance cost: medium. A protocol change updates one corpus and two
   small loaders, then runs the two deterministic package checks. This is less
   costly than debugging cross-language drift after a lifecycle change.
9. Recurrence/trigger: high recurrence while Python and TypeScript both own
   the v2 boundary and new fields or limits are added independently.
10. Worth implementing now: yes. The consequence is system-wide, the failure
    is deterministic and highly detectable, and the mechanism does not alter
    runtime behavior.

#### `PROTO-02` design details

- Corpus ownership: `testdata/protocol-v2/cases.json` is owned by the protocol
  boundary and consumed by both package test suites. The current v2 directory
  remains the corpus for v2; an incompatible future wire version gets its own
  versioned corpus rather than silently changing v2 expectations.
- Fixture shape: each case has an ID, `command` or `event` operation, a raw
  frame string, and an expected accepted/rejected result. Valid expected values
  use wire-shaped JSON; the Python adapter normalizes dataclass defaults and
  the TypeScript adapter normalizes omitted optional fields. Rejected cases may
  carry a stable parser reason such as `duplicate_field` or
  `unsupported_version`.
- Accepted cases cover prompt, structured messages, trusted guidance, cancel,
  health, shutdown, all generation event variants, UTF-8, and boundary values.
  Rejected cases cover unknown/duplicate fields, mixed prompt/messages,
  unsupported versions, invalid numeric forms, unsupported roles, empty delta,
  malformed JSON, and size limits.
- Versioning behavior: v2 tests continue to reject v1/v3 frames as
  `unsupported_version`; no v2 fixture authorizes future-version acceptance.
- Stdout/stderr boundary: the corpus does not pretend to test process streams.
  Existing server/runtime checks remain responsible for newline framing,
  truncated EOF, output backpressure, protocol-only stdout, and stderr
  diagnostics. The future M3C acceptance gate must keep those checks green.
- Canonical truth boundary: the Python and TypeScript parser implementations
  remain the schema/behavior authority. The corpus contains examples and
  expected interoperability outcomes only; it is not a generated schema,
  code-generation source, or a second field inventory.

### `OWN-01` — dependency direction

Disposition: `IMPLEMENT_NOW` (`PROPOSAL`, pending human review before M3C).

1. Invariant/failure mode: Core must remain provider-neutral and transport-
   neutral; `lilavel-core` must not import Discord-specific implementation or
   the Discord SDK. The edge may depend on Core, never the reverse.
2. Consequence if violated: Core becomes unavailable without a presentation
   vendor, package installation becomes coupled, and semantic ownership can
   leak into a replaceable edge.
3. Existing enforcement: `apps/core/pyproject.toml` declares no runtime
   dependencies; `apps/discord-edge/pyproject.toml` declares `lilavel-core`
   as a local dependency; Core source imports only its own modules and the
   standard library, while edge code imports Core. ADR-004 and the architecture
   document state the same direction.
4. Residual gap: manifests and current imports are evidence, but neither is a
   source-level assertion that prevents a future direct `discord` or
   `lilavel_discord_edge` import from entering Core when the host happens to
   have that package installed.
5. Proposed mechanism: add a package-local structural test that walks only
   Python files under `apps/core/src/lilavel_core`, parses them with `ast`, and
   rejects absolute import roots `discord`, `lilavel_discord_edge`, and any
   future explicitly named Discord-edge package root. Keep the forbidden set
   narrow and visible in the test.
6. Lowest appropriate layer: a deterministic AST/import test directly checks
   dependency direction without requiring a hook, import-time side effect, or
   whole-repository build graph.
7. Expected false-positive risk: low. AST inspection ignores comments, string
   literals, tests, fixtures, and dynamic import calls. A deliberate future
   architecture change would fail for human review rather than silently pass.
8. Maintenance cost: low. The test is package-local and changes only when the
   repository intentionally adds or renames a transport boundary.
9. Recurrence/trigger: medium recurrence as new edges or integrations are
   added; architectural importance is high because the direction is a core
   replaceability condition.
10. Worth implementing now: yes. It closes a cheap, deterministic gap that
    manifests and documentation do not fully cover.

### `AUTH-02` — diagnostics redaction

Disposition: `IMPLEMENT_NOW` (`PROPOSAL`, pending human review before M3C).

1. Invariant/failure mode: diagnostic metadata must not serialize credentials,
   auth resolver material, request text, provider error messages, headers,
   URLs, bodies, or provider payloads. Safe diagnostics may retain bounded
   types, codes, lengths, timings, statuses, and a one-way rate-limit bucket
   hash. Deliberate streamed `text_delta` output is a separate temporary
   output surface and is not falsely described as universally non-sensitive.
2. Consequence if violated: logs or probe output can expose credentials,
   private prompts, provider internals, or Discord request data.
3. Existing enforcement: `DiscordDiagnostics` stores safe operation/timing,
   status, numeric rate-limit fields, and a truncated bucket hash; it does not
   store URL, headers, body, or exception text. Existing edge tests inject
   secret markers and assert they are absent. Sidecar events are a narrow
   typed union and map failures to codes; sidecar tests verify the supported
   auth resolver boundary and no provider continuation fields.
4. Residual gap: sidecar tests do not yet assert an exact serialized key
   allowlist across every diagnostic event or inject secret markers through a
   provider error/auth-resolver path and inspect the emitted event stream.
   Future event-field expansion could therefore regress redaction despite the
   current type shape. The edge sentinel coverage should also remain explicit
   rather than relying on a generic scanner.
5. Proposed mechanism: extend the existing sidecar event tests with per-event
   and per-metadata exact key allowlists, a prompt/auth/provider-error sentinel
   test, and JSON serialization inspection. Retain/extend the existing edge
   diagnostics adversarial assertions for URL, request headers/body,
   exception text, and bucket values. Do not add a generic secret scanner or a
   new production serializer solely for this gap.
6. Lowest appropriate layer: the existing serializer/event tests observe the
   exact boundary where diagnostic data is assembled, with low noise and no
   provider dependency. A hook or CI scanner would be later and less precise.
7. Expected false-positive risk: low for exact keys and sentinels. The test
   must not reject intentional model-output deltas or claim that a fake
   provider proves all live logging behavior; it checks diagnostic metadata.
8. Maintenance cost: low to medium. New diagnostic fields require an explicit
   allowlist review and a targeted test update, which is the desired friction
   for a security-sensitive surface.
9. Recurrence/trigger: high whenever diagnostics, provider errors, auth
   adapters, or probe output gain fields. Consequence is high even though the
   check is package-local.
10. Worth implementing now: yes. Existing narrow tests make this a small
    extension with a materially better regression boundary than a generic
    scanner.

### `CTX-02` — provider/session isolation

Disposition: `KEEP_EXISTING_ENFORCEMENT`.

1. Invariant/failure mode: each request supplies caller-owned provider-neutral
   context; the sidecar must not retain semantic history or silently use
   provider continuation/session state between requests.
2. Consequence if violated: one conversation or user can receive another
   request's context, and provider state can become an undeclared semantic
   memory owner.
3. Existing enforcement: `toPiAiContext()` builds a fresh adapter context;
   `ModelSidecar` does not retain request context; tests assert provider
   payload/response IDs/tools are absent, `sessionId`,
   `providerSessionState`, and `statefulResponses` are absent, and
   `preferWebsockets` is false. The optional isolation probe is explicitly
   live/provider-dependent.
4. Residual gap: fake-provider tests cannot prove hidden behavior inside a
   real provider implementation, and no deterministic fake can establish a
   live entitlement/session guarantee.
5. Proposed mechanism, if needed: retain the existing adapter contract tests
   and live isolation probe. Add a new sequential fake-request test only when
   a provider upgrade, a second provider adapter, a new continuation option, or
   a reproduced isolation failure creates a concrete gap.
6. Lowest appropriate layer: the current adapter contract is the right
   deterministic layer for caller-owned inputs/options; live semantics remain
   a separate provider check. A generic hook cannot prove either.
7. Expected false-positive risk: low for current option/context assertions;
   high false assurance if a fake test is presented as live-provider proof.
8. Maintenance cost: existing cost is justified; another redundant fake test
   now would add maintenance without extending the proven boundary.
9. Recurrence/trigger: low under the pinned single-provider, stateless
   adapter. Revisit on provider package upgrade, continuation-state change,
   second adapter, or an observed isolation regression.
10. Worth implementing now: no new mechanism. Existing enforcement is retained
    with its live/provider limitation explicitly unverified.

### `OWN-02` — semantic ownership preservation

Disposition: `KEEP_EXISTING_ENFORCEMENT`.

1. Invariant/failure mode: Core alone owns canonical conversation history,
   context composition, generation lifecycle, and canonical assistant commit;
   edges consume runs and never become a second history owner.
2. Consequence if violated: cancellation/supersession can create divergent
   histories or partial assistant text can become canonical.
3. Existing enforcement: `ConversationCore`, its Core-owned store and
   transaction boundary, the Discord edge mapping, ADR-001/004/005, and
   conversation/persistence/edge tests encode the ownership and commit paths.
4. Residual gap: a future edge could violate semantic ownership in behavior
   without being reducible to one reliable import or field-name rule.
5. Proposed mechanism, if any: keep the existing behavior tests and human
   review of new edges. Do not add a broad semantic linter.
6. Lowest appropriate layer: package-local behavior and persistence tests are
   lower-noise than a heuristic source scanner for semantic ownership.
7. Expected false-positive risk: high for generic static detection; current
   targeted tests have low risk.
8. Maintenance cost: adding a new edge should add targeted ownership tests;
   no separate M3B mechanism is justified now.
9. Recurrence/trigger: revisit when another transport, persistence owner, or
   canonical commit path is introduced.
10. Worth implementing now: no new mechanism; existing enforcement remains.

### `AUTH-01` — supported authentication boundary

Disposition: `KEEP_EXISTING_ENFORCEMENT`.

1. Invariant/failure mode: authentication is discovered and resolved through
   the supported provider/auth-storage boundary; credentials are not manually
   extracted, replayed, persisted, or exposed.
2. Consequence if violated: credential disclosure, unsupported auth behavior,
   or a brittle integration that cannot be safely audited.
3. Existing enforcement: the sidecar imports `discoverAuthStorage`, uses the
   auth resolver, closes auth storage, and tests the resolver boundary. AGENTS,
   ADR-002, and the sidecar README prohibit credential workarounds.
4. Residual gap: no static check can reliably distinguish every future
   unsupported auth workaround from legitimate provider code, and supported
   live auth behavior is not established by this design pass.
5. Proposed mechanism, if any: keep the supported boundary and targeted tests;
   require process review for any auth change. Do not add token-shaped regex
   scanning or credential extraction probes.
6. Lowest appropriate layer: the provider's supported auth API plus its narrow
   adapter tests; generic hooks/scanners would be the wrong layer.
7. Expected false-positive risk: high for generic secret or API-call scanning;
   current boundary tests have low risk.
8. Maintenance cost: existing boundary maintenance is low; a scanner would
   create noisy ongoing review cost.
9. Recurrence/trigger: revisit only on auth-provider change, auth failure, or
   a proposed new credential path.
10. Worth implementing now: no new mechanism; existing enforcement remains.

### `LIFE-02` — cleanup and containment

Disposition: `KEEP_EXISTING_ENFORCEMENT`.

1. Invariant/failure mode: provider iterator/result cleanup is confirmed before
   sidecar reuse; cleanup timeout/rejection poisons the sidecar; Core owns
   bounded cancellation/shutdown and process containment.
2. Consequence if violated: leaked provider work, deadlocks, stale output,
   unsafe same-process reuse, or descendant processes surviving shutdown.
3. Existing enforcement: sidecar cleanup deadlines and poison state, protocol
   terminal cleanup waits, Core lifecycle deadlines, Windows Job Object
   containment, and adversarial/lifecycle/process-containment tests.
4. Residual gap: normal deterministic tests do not establish every live
   provider, restart, Windows race, or hostile process interleaving.
5. Proposed mechanism, if any: keep the package-local lifecycle and platform
   checks. Revisit a concrete race with a focused regression test; do not add a
   Codex hook, sandbox, or generic supervisor rule.
6. Lowest appropriate layer: lifecycle state and process-containment code/tests
   directly own the failure mode.
7. Expected false-positive risk: low for current focused tests; a broad race
   checker would likely create false assurance and high noise.
8. Maintenance cost: already material but justified by consequence; another
   mechanism now would duplicate the existing lifecycle contract.
9. Recurrence/trigger: revisit on a reproduced cleanup race, new process
   launcher, restart behavior, or provider iterator contract change.
10. Worth implementing now: no new mechanism; current enforcement remains,
    with live/platform limits unverified.

### `PERS-02` — evidence and durability qualifiers

Disposition: `PROCESS_ONLY`.

1. Invariant/failure mode: persistence and evidence claims must state their
   actual scope: default in-memory behavior, explicit file-backed durability,
   transactional commit boundaries, and unverified restart/crash limits.
2. Consequence if violated: users may treat an ephemeral or package-local
   observation as durable restart-safe truth.
3. Existing enforcement: `persistence.py` and tests define the store and
   transaction behavior; architecture and Core README qualify default memory,
   explicit durable scope, raw evidence, and crash boundaries; validation docs
   separate deterministic and platform-specific results.
4. Residual gap: prose/report claims are contextual and are not mechanically
   bound to every executed command or platform result; restart/crash evidence
   was not generated by M3B.
5. Proposed mechanism, if any: require scoped claim labels in work records and
   validation reports. Do not add a claim parser or a durability linter.
6. Lowest appropriate layer: process/reporting review is lower complexity and
   more accurate than source-level heuristics.
7. Expected false-positive risk: high for a generic claim scanner; low for
   deliberate human review using the existing vocabulary.
8. Maintenance cost: low process cost; a machine rule would be expensive to
   keep aligned with evolving evidence types.
9. Recurrence/trigger: every persistence, restart, crash-recovery, or evidence
   claim; a new automated mechanism would need a concrete repeated failure.
10. Worth implementing now: no machine change; preserve process-only handling.

### `VAL-01` — validation-claim truthfulness

Disposition: `PROCESS_ONLY`.

1. Invariant/failure mode: reports must identify deterministic, live/provider,
   and platform-specific scope and use `PASS`, `FAIL`, `BLOCKED`, or
   `UNVERIFIED` accurately.
2. Consequence if violated: a local fixture result can be mistaken for live,
   restart, Windows, or Discord evidence.
3. Existing enforcement: `docs/VALIDATION.md` defines the result vocabulary and
   authoritative commands; AGENTS requires executed evidence; current work
   records separate package/live/platform scope.
4. Residual gap: claims can be written in chat or a work record and cannot be
   reliably interpreted by a generic source/test rule.
5. Proposed mechanism, if any: retain the work-record/report review gate and
   exact command/result recording. Do not require CI or a prose linter in M3B.
6. Lowest appropriate layer: process and human review, because the invariant
   is about the relationship between a claim and an execution context.
7. Expected false-positive risk: high for automated wording checks; low for a
   scoped review against the validation contract.
8. Maintenance cost: low existing process cost; high/noisy cost for a linter.
9. Recurrence/trigger: every task that reports checks, especially live or
   platform-specific work.
10. Worth implementing now: no machine mechanism; existing process remains.

### `FUT-01` — future-scope restraint

Disposition: `PROCESS_ONLY`.

1. Invariant/failure mode: future AI-streamer/product direction must not be
   treated as a current implementation requirement without repository or human
   authority.
2. Consequence if violated: speculative personality, social, memory, or
   streamer features enter the current architecture and expand scope without a
   decision boundary.
3. Existing enforcement: AGENTS, README, architecture, ADR scope, and current
   package boundaries explicitly limit future streamer/character work.
4. Residual gap: whether a proposed feature is authorized is a product/design
   judgment, not a reliable token or import pattern.
5. Proposed mechanism, if any: continue explicit scope/non-goal review in the
   work record and human gate. No rules, hooks, or future-feature scanner.
6. Lowest appropriate layer: human design authority and task scope; machine
   enforcement would encode unapproved product semantics.
7. Expected false-positive risk: high for automated detection of words or
   package names that may be legitimate bounded experiments.
8. Maintenance cost: low process cost; high cost to maintain speculative rule
   lists.
9. Recurrence/trigger: any request to add future-scope behavior or architecture.
10. Worth implementing now: no machine mechanism; process-only restraint is
    the appropriate control.

### `ART-01` — tracked artifact intent

Disposition: `HUMAN_GATE`.

1. Invariant/failure mode: tracked artifact status must be known before adding
   an ignore rule, deleting captures, rewriting them, or treating them as
   fixtures, evidence, or accidental output.
2. Consequence if violated: useful evidence can be deleted or operational data
   can become an accidental repository contract.
3. Existing enforcement: the six M3A-identified Discord JSONL captures remain
   tracked; their current Git presence is observable, but no checked-out
   documentation identifies their intended canonical role.
4. Residual gap: repository evidence does not resolve owner intent or whether
   the files are fixtures, captures, or accidental artifacts. M3A marked this
   `UNKNOWN`; M3B has not resolved it.
5. Proposed mechanism, if any: obtain a human artifact-intent decision first;
   only then consider a narrowly scoped Git/artifact hygiene rule. No cleanup
   action is authorized in M3B.
6. Lowest appropriate layer: human gate, because artifact meaning is semantic
   intent rather than a safe filename/content heuristic.
7. Expected false-positive risk: high for automated delete/classify/ignore
   rules; the human gate minimizes irreversible misclassification.
8. Maintenance cost: none now; a future hygiene rule should be small and
   reversible after intent is explicit.
9. Recurrence/trigger: human clarification of the six files or a new artifact
   workflow with explicit intent.
10. Worth implementing now: no. Preserve `UNKNOWN` and do not bypass the
    human gate.

## Prioritization result

`RESULT`: the practical shortlist is exactly three items:

1. `PROTO-02` — highest system-wide consequence and recurring cross-language
   drift risk; a shared corpus is directly executable and still small.
2. `OWN-01` — high architectural consequence with a low-cost, low-noise AST
   check that closes a real source-level gap left by manifests.
3. `AUTH-02` — high security consequence with existing narrow tests that can be
   extended to the sidecar event boundary without a generic scanner.

`RESULT`: `CTX-02` is deliberately not a fourth item. Its deterministic
adapter boundary is already tested, while live provider hidden-state behavior
remains outside what fake-provider tests can prove. Adding a redundant fake
test now would increase maintenance without resolving that live limitation.

## Bounded M3C implementation contracts

The following are future contracts only. M3B does not create these files or
modify their listed paths.

### M3C-PROTO-02 — shared protocol compatibility corpus

- Likely owned paths: new `testdata/protocol-v2/cases.json`,
  `apps/core/tests/test_sidecar_protocol.py`,
  `apps/model-sidecar/tests/protocol.test.ts`, and only the existing
  `apps/core/tests/test_runtime.py` / `apps/model-sidecar/tests/server.test.ts`
  framing assertions that are demonstrably missing.
- Intended check: both parsers consume the same raw valid/rejected cases and
  compare normalized accepted values or bounded error reasons; existing
  framing tests continue to assert CRLF/chunk handling, truncated EOF,
  newline-terminated protocol-only output, and diagnostics on stderr.
- Explicit non-goals: JSON Schema/code generation, a third parser, provider or
  auth behavior, live/restart evidence, exact human error text, CI-only truth,
  or accepting future protocol versions.
- Acceptance criteria: both package test suites consume the corpus; all v2
  command/event variants and listed rejection classes are covered; no local
  duplicate case list replaces the corpus; v1/v3 remain rejected; raw output
  remains one frame per line.
- Validation: Core locked checks, sidecar frozen Bun checks, and root
  `git diff --check`; no live/provider check is required.
- Rollback/removal: remove the corpus and both loaders together if the wire
  boundary becomes single-owned or an accepted architecture decision replaces
  it; do not leave one language claiming shared coverage alone.
- Independence: independent from OWN-01 and AUTH-02, but one writer must own
  the shared corpus and both test adapters during implementation.

### M3C-OWN-01 — Core import-direction check

- Likely owned paths: new `apps/core/tests/test_architecture_boundaries.py`.
- Intended check: AST-walk only `apps/core/src/lilavel_core/**/*.py` and fail
  on direct absolute imports rooted at the Discord SDK or Discord edge package.
- Explicit non-goals: scanning tests/docs, whole-repository dependency graphs,
  dynamic imports, subprocess transport paths, semantic behavior, or reverse
  dependency validation outside the named Core source boundary.
- Acceptance criteria: current Core source passes; an accidental direct
  Discord import is deterministically rejected; the forbidden root list is
  narrow and visible; no runtime behavior changes.
- Validation: Core locked checks and `git diff --check`.
- Rollback/removal: remove only if an accepted architecture decision makes
  Core intentionally depend on a transport, together with the corresponding
  ownership-doc change in that separate task.
- Independence: fully independent from the shared corpus and diagnostics
  tests; one Core test writer is sufficient.

### M3C-AUTH-02 — diagnostic allowlist/adversarial coverage

- Likely owned paths: `apps/model-sidecar/tests/model-sidecar.test.ts` and
  `apps/discord-edge/tests/test_diagnostics.py`; production serializers are
  not expected to change if the current behavior satisfies the tests.
- Intended check: exact event/metadata key allowlists plus sentinel absence for
  prompt text, auth material, resolver error text, provider error text, URL,
  request headers/body, and bucket values. Keep intentional `text_delta`
  output semantics separate from diagnostic metadata claims.
- Explicit non-goals: generic secret scanning, live provider proof, credential
  extraction, blocking legitimate model output, or a new diagnostics framework.
- Acceptance criteria: future diagnostic field additions require an explicit
  allowlist/test update; injected markers never appear in diagnostic metadata;
  existing edge safe-field and exception-preservation tests remain green.
- Validation: sidecar frozen Bun checks, Discord-edge locked checks, and
  `git diff --check`; no live auth/provider check is required.
- Rollback/removal: remove or consolidate the duplicate package assertions only
  if the diagnostic boundary is deliberately replaced by one typed serializer;
  preserve an equivalent allowlist at the new boundary.
- Independence: independent from PROTO-02 and OWN-01; the two package test
  paths may be implemented under one AUTH-02 work item because they enforce the
  same diagnostic invariant without sharing mutable source state.

## Recommended M3C work-item structure

`PROPOSAL`: choose option B — separate M3C work items per mechanism:

- one cross-package `PROTO-02` work item for the shared corpus and its two
  adapters;
- one Core-only `OWN-01` work item for the AST import boundary;
- one `AUTH-02` diagnostics-test work item covering the sidecar and Discord
  diagnostic surfaces.

This is based on validation boundaries, not convenience: PROTO-02 requires one
shared fixture writer and two package checks; OWN-01 is a Core-only structural
check; AUTH-02 has two package-local test surfaces but one security invariant.
They have disjoint mutable paths and can be scheduled independently after
human acceptance, while the protocol corpus itself must have one active writer.
Do not create those records until this M3B recommendation is reviewed.

## Validation

- deterministic: `PASS` — actual Git preflight completed at HEAD
  `8095aba481a3815d00990c985537a86963e803d2`, clean index/worktree, canonical
  branch confirmed, M3A completed record present, and no unrelated start-state
  changes found.
- deterministic: `PASS` — `git diff --check` passed for the tracked tree;
  the untracked record had no trailing whitespace, its required work-record
  sections and eleven candidate justifications were present, all internal
  links resolved, and Git showed only the new `work/active/` record scope.
- package/live/provider/platform-specific: `UNVERIFIED` — intentionally not
  run; M3B design facts did not require runtime, package, live provider,
  restart, Discord, or full-Windows execution.
- independent read-only review: `PASS` — a fresh second pass found no
  overengineering, wrong-layer hooks/rules/sandbox use, proposal-to-decision
  drift, duplicated canonical truth, ungrounded recurrence claim, shortlist
  overflow, or ART-01 human-gate bypass. All eleven dispositions are allowed
  values and all three M3C contracts contain bounded paths, checks,
  non-goals, acceptance, validation, rollback, and independence clauses.

## Completion recommendation

`RESULT`: M3B is complete enough to proceed to M3C after human review. The
three mechanisms remain `PROPOSAL`s, so no M3C implementation or additional
active work record should begin until the user accepts the shortlist,
dispositions, M3C split, and the continued `ART-01` human gate.

## Remaining work

- Obtain human review of the three-item shortlist, the no-new-mechanism
  dispositions, the M3C split, and the unresolved `ART-01` gate.
- If accepted, create separate M3C work items and implement only their bounded
  contracts; otherwise revise this record as directed without touching runtime
  or canonical files.

## Next safe action

Run the read-only record validation and independent review, then hand this
design to the user for acceptance before any M3C implementation or additional
work record is created.

## Handoff

- Git/checkout state: canonical `C:\Lilavel`, branch `feat/conversation-core`,
  base/checkpoint `8095aba481a3815d00990c985537a86963e803d2`.
- Uncommitted changes: this new M3B active record only; it is not durable until
  a later user-authorized commit. No runtime/source/tests/config/hooks/CI/docs/
  ADRs changed.
- Blockers/unknowns: human review is required before M3C; `ART-01` remains
  `UNKNOWN` and human-gated; live/provider/restart/full-Windows evidence remains
  outside this design and `UNVERIFIED`.
- Promotion: no canonical knowledge or accepted architecture decision was
  promoted; M3B mechanism choices remain `PROPOSAL`s.
- Next safe action: complete validation/review, then request human acceptance
  of the M3C shortlist.
