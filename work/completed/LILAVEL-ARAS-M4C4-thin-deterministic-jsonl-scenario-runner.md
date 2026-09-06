# LILAVEL-ARAS-M4C-4 — Thin Deterministic JSONL Scenario Runner

Status: COMPLETED
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel`
Branch / worktree: `feat/conversation-core`
Base commit: `4e9dd93f37d7c0e6facb9e2f83575b5d249d6899`
Last checkpoint commit: `4e9dd93f37d7c0e6facb9e2f83575b5d249d6899`

## Goal

Create the smallest deterministic, offline, repo-local JSONL runner that
exposes bounded Core, physical sidecar, and feasible Discord presentation
evidence for fresh-agent runtime questions without becoming a simulator,
logging framework, or semantic authority. RESULT: complete for the selected
scenario set.

## Scope

- One explicit entrypoint: `apps/discord-edge/scripts/scenario_runner.py`.
- Reuse of Core/physical/Discord evidence, the committed fake sidecar, and the
  existing Core semantic test double; no production lifecycle duplication.
- Focused runner tests, package README navigation, usefulness/privacy proofs,
  and M4D handoff.

## Non-goals

- No live provider or Discord access, credentials, generic replay framework,
  telemetry stack, durable runtime-evidence store, protocol redesign, ART-01,
  or M4D evaluation.
- No commit, merge, or mutation of unrelated work.

## Exit criteria

- Durable M4C-1/2/3 integration verified before implementation.
- Supported scenarios emit safe, source-separated JSONL only.
- `success`, `sidecar-failure`, and `malformed-frame` join Core semantic and
  physical generation evidence; `discord-interruption` joins Core and Discord
  presentation evidence.
- Focused/package/quality/privacy/usefulness/review checks pass with live
  limits stated precisely.

## Current implementation state

The durable integration gate passed before mutation at
`4e9dd93f37d7c0e6facb9e2f83575b5d249d6899`: M4C-1
`6bcbc74f7e41f8cda870d54a37677442ca548909`, M4C-2
`a48b4275f0bb9a9462bfee2bfe15aabafac4038c`, and M4C-3
`da5cd69050d45b0543ae1ec3d611e530cb56c0c5` all returned ancestor success;
the M4C-I record existed in `HEAD`; the starting worktree was clean and five
commits ahead of origin.

The chosen architecture is A: one repo-local Python CLI in the Discord edge
dev environment, with a fixed registry and safe source projections. B, a
pytest-backed command, was rejected because test-runner output and internals
would become part of the agent contract. C, a production package debug entry
point, was rejected because it would couple diagnostics to distribution/runtime
behavior. The runner uses the existing Core fake by loading its test module,
but calls no pytest APIs; the real sidecar fixture is used for physical paths.

## Scenario inventory and selection

| Scenario surface | Existing infrastructure | Boundary / output | Offline / selected |
| --- | --- | --- | --- |
| Successful generation | `tests/fixtures/fake_sidecar.py` normal mode, `ModelRuntime`, `ConversationCore` | Core + physical; `run_id` to `generation_id`/`epoch` | yes / v1 |
| Cancellation | Core `FakeRuntime`, `ConversationRun.cancel`, fixture cancellation modes | Core cancellation and safe terminal | yes / used by supersession |
| Supersession | `apps/core/tests/test_conversation.py` `FakeRuntime` late-delta path | Core `generation_bound`, `cancel_requested`, `delta_discarded`, terminal/commit | yes / v1; no physical surface by double design |
| Malformed frame | `fake_sidecar.py` `malformed-after-accepted` | Core + physical `protocol_error` terminal | yes / v1 |
| Crash / poisoning | `fake_sidecar.py` `crash-after-accepted`; adversarial fixture covers poison races | Core + physical `sidecar_crashed`; poison variants remain inventory | yes / crash v1 |
| Persistence restart | `SQLiteConversationStore`, `tests/test_persistence.py` | durable canonical history, separate from ephemeral runtime evidence | local / omitted to avoid runner state mutation |
| Discord interruption | production `DiscordTextEdge`, `DiscordDiagnostics`, existing Core fake pattern, local transport double | Core run to flush/operation/request/outcome | yes / v1 |

## Runner contract

Command: `uv run --locked python scripts/scenario_runner.py <scenario>` from
`apps/discord-edge`. Supported names are `success`, `supersession`,
`sidecar-failure`, `malformed-frame`, and `discord-interruption`.

Each stdout line is one JSON object with `record_type` (`scenario`, `evidence`,
or `result`), `scenario`, `surface`, and deterministic `ordering`. Core
evidence retains source sequence, scope, run/message identities, generation
identity, safe result/reason/failure codes, and aggregate discard counts.
Physical evidence retains generation identity, protocol event category, safe
terminal code, and aggregate delta counts/bytes. Discord evidence retains only
allowlisted correlation IDs, operation categories, response status, and typed
presentation outcome. There are no timestamps, text, URLs, headers, bodies,
exception messages, credentials, provider/session IDs, or Discord IDs. An
unexpected runner failure emits only stderr and exits nonzero.

## Usefulness and privacy proofs

- `success` JSONL alone joins the Core `generation_bound` run to the physical
  generation creation/protocol/terminal records and shows assistant commit.
- `supersession` JSONL alone identifies the old run and generation identity,
  `cancel_requested(reason=superseded)`, one `delta_discarded` aggregate with
  `reason=not_current`, old `run_terminal=superseded` without commit, and new
  run commit. Its result explicitly says physical evidence was not invoked by
  the semantic test double; no physical claim is made there.
- `sidecar-failure` and `malformed-frame` JSONL alone show typed physical
  failure categories (`sidecar_crashed` / `protocol_error`) and semantic
  failed terminals without assistant commit.
- `discord-interruption` JSONL alone joins each `core_run_id` through flush,
  operation, HTTP request/response, and presentation outcome; it shows old
  `interrupted/superseded` and new `completed`.
- A temporary sensitive input sentinel was passed through the success path;
  the exact renderer used for stdout omitted it, and every rendered line
  remained valid JSON. Tests also assert no URL, timing, request/body, channel,
  or message sentinels appear in the stream.

## Validation

- Durable integration gate: PASS — actual ancestry checks for M4C-1/2/3,
  M4C-I tree presence, clean pre-mutation worktree.
- Runner checks: PASS — 10 focused tests; all five commands succeed, including
  expected typed failure observations; repeated success has stable structural
  relations; unknown scenario is nonzero with no traceback.
- Core: PASS — `uv sync --locked`, lock check, Ruff check/format, Pyright, full
  pytest: `127 passed`.
- Discord edge: PASS — lock check, Ruff check/format, Pyright, full pytest:
  `78 passed`, one existing `audioop` deprecation warning.
- Model sidecar: PASS — frozen Bun install, typecheck, full suite: `65 passed`;
  explicit PROTO-02 protocol suite: `36 passed`.
- Explicit M3 checks: PASS — Core PROTO-02/OWN-01 target `50 passed`; Discord
  AUTH-02 diagnostics/semantic target `31 passed`.
- Whitespace/state: PASS — `git diff --check`, runner format/ruff checks, no
  staged changes, no sabotage artifact.
- Live provider, live Discord, restart, and external E2E: UNVERIFIED/BLOCKED —
  intentionally not run and not claimed by this offline runner.

## Independent read-only review

RESULT: PASS. The runner keeps source surfaces distinct, uses explicit static
scenario names, does not duplicate production lifecycle semantics, emits no
raw content or unsafe diagnostics, has no credential/network requirement, and
uses in-memory Core stores. The semantic-double limitation is visible in both
the result and documentation. No generic simulator, plugin discovery,
telemetry framework, durable evidence writer, or M4D evaluation was added.

## Remaining work

None for M4C-4. Human review is the next decision boundary for M4D.

## Next safe action

Begin `M4D — Fresh-Agent Runtime Debug Eval` against the documented JSONL
contract; keep live/provider/Discord/restart questions explicitly unverified.

## Handoff

- Git/checkout state: canonical `feat/conversation-core` at
  `4e9dd93f37d7c0e6facb9e2f83575b5d249d6899`, five commits ahead of origin.
- Uncommitted changes: README modification, runner, tests, and this work
  record are intentionally uncommitted; no staged changes.
- Blockers/unknowns: live provider/Discord, restart, and external E2E remain
  unverified; the two semantic-double scenarios intentionally have no physical
  evidence surface.
- Next safe action: human gate, then fresh-agent M4D evaluation.
