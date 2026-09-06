# LILAVEL-ARAS-M3D — Integrated adversarial enforcement evaluation

Status: COMPLETED
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel` - canonical Lilavel repository checkout
Branch / worktree: `feat/conversation-core`
Base commit: `a7d0b8cca2a38961513838d220e6bc01cadfd82d`
Last checkpoint commit: `a7d0b8cca2a38961513838d220e6bc01cadfd82d`

## Goal

Evaluate the three accepted M3 mechanisms together: `PROTO-02` shared
Protocol V2 corpus, `OWN-01` Core dependency-direction AST guard, and
`AUTH-02` Discord diagnostics allowlist/sentinel coverage. Prove deterministic
violation detection, clean recovery, specificity, nearby legitimate-state
resistance, and honest scope.

## Scope

- Read-only baseline and restored-state validation across Core, sidecar, and
  Discord-edge checks.
- Disposable one-sided protocol drift, forbidden Core import, and diagnostics
  leakage mutations, each fully reverted.
- Existing tests for nearby legitimate forms and an independent read-only
  evidence review.
- This M3D work record only; no implementation or commit.

## Preflight

- `C:\Lilavel`; branch `feat/conversation-core`; HEAD and last checkpoint
  `a7d0b8cca2a38961513838d220e6bc01cadfd82d`.
- Index/worktree were clean before this record; no staged or unrelated changes.
- Completed records present: M3A, M3B, M3C-1, M3C-2, and M3C-3. No stale active
  record was present before M3D.

## Non-goals

- No new enforcement mechanism, hooks, rules, CI, sandbox, generic scanner,
  architecture framework, runtime/product feature, or `ART-01` work.
- No real credentials/user data and no live/provider/Discord/restart claim
  without direct evidence.

## Exit criteria

- Integrated deterministic baseline passes.
- Each representative violation fails the intended existing guard, with clear
  evidence; each mutation is fully reverted and the restored checks pass.
- Existing nearby legitimate states pass; no sabotage artifacts remain.
- Independent review finds no material evidence or scope overclaim.
- Live/external/platform-specific limits remain explicitly `UNVERIFIED`.

## Current implementation state

`PROTO-02`, `OWN-01`, and `AUTH-02` are implemented and checkpointed at the
base commit. The starting Git index/worktree was clean. All three disposable
violations failed through their intended existing guards, all mutations were
restored from HEAD, and the final integrated deterministic validation is green.

## Adversarial results

- `PROTO-02`: `PASS` detection/recovery/specificity. In
  `apps/model-sidecar/src/protocol.ts`, a disposable TypeScript `assertVersion`
  mutation accepted V3 without editing `testdata/protocol-v2/cases.json`.
  `npx --yes bun@1.4.0 test tests/protocol.test.ts -t "shared corpus:
  command-version-three"` failed with `Expected: true / Received: false` at
  `tests/protocol.test.ts:70`; after full restoration, sidecar typecheck and
  all 36 protocol tests passed.
- `OWN-01`: `PASS` detection/recovery/specificity. A disposable `import
  discord` in `apps/core/src/lilavel_core/sidecar_protocol.py` caused
  `uv run --locked pytest tests/test_architecture_boundaries.py` to fail
  `test_core_source_has_no_direct_discord_imports`, identifying
  `src\\lilavel_core\\sidecar_protocol.py:6: forbidden import 'discord'`;
  after restoration, the guard passed 3 tests and the Core protocol target
  passed 47 tests.
- `AUTH-02`: `PASS` detection/recovery/specificity. A disposable
  `request_url="m3d-request-url-sentinel"` field in the runtime
  `http_request_start` emission caused
  `uv run --locked pytest tests/test_diagnostics.py -k
  "all_diagnostic_event_paths_use_allowlists_and_drop_sensitive_sentinels"`
  to fail with `unexpected fields for http_request_start: {'request_url'}`;
  after full source restoration, diagnostics/semantic checks passed 29 tests.

## False-positive resistance

- `PROTO-02`: the same 36-test protocol consumer suite passes current valid V2
  cases and normalized semantics after restoration.
- `OWN-01`: the existing guard suite passes comments, strings, Core imports,
  and the non-violation fixture alongside the forbidden-import fixture (3
  passed); this remains a source-import guard, not semantic ownership proof.
- `AUTH-02`: the existing diagnostics test covers all eight current event kinds,
  checks each event against its allowlist, and passes with the fake sentinels
  absent (within the 29-test diagnostics/semantic target).

## Remaining work

None for the M3D evaluation scope. No implementation correction or new guard
was necessary.

## Next safe action

Human review/checkpoint is the next safe action. A later phase may separately
scope agent-readable runtime/observability work; M3D creates no M4 files.

## Validation

- Baseline frozen setup: `PASS` — `uv sync --locked` and `uv lock --check`
  from `apps/core` and `apps/discord-edge`; `npx --yes bun@1.4.0 install
  --frozen-lockfile` from `apps/model-sidecar`.
- Baseline targeted: `PASS` — Core
  `uv run --locked pytest tests/test_sidecar_protocol.py
  tests/test_architecture_boundaries.py` (50 passed); sidecar
  `npx --yes bun@1.4.0 run check` and
  `npx --yes bun@1.4.0 test tests/protocol.test.ts` (36 passed); Discord
  `uv run --locked pytest tests/test_diagnostics.py tests/test_semantic.py`
  (29 passed).
- Baseline package quality: `PASS` — Ruff check/format and Pyright passed for
  Core and Discord; `git diff --check` passed. The Discord suite reported only
  the existing Python 3.13 `audioop` deprecation warning.
- Deterministic adversarial scenarios: `PASS` — each accepted mechanism
  rejected its representative mutation, each mutation was fully reverted, and
  the corresponding targeted checks recovered.
- Restored Core package: `PASS` — `uv lock --check`, Ruff check/format,
  Pyright, and `uv run --locked pytest` (118 passed).
- Restored Discord package: `PASS` — `uv lock --check`, Ruff check/format,
  Pyright, and `uv run --locked pytest` (62 passed, one existing `audioop`
  deprecation warning).
- Restored sidecar package: `PASS` — frozen install, `npx --yes
  bun@1.4.0 run check`, and `npx --yes bun@1.4.0 test` (64 passed).
- Restored whitespace/state: `PASS` — `git diff --check`; no source, test,
  corpus, staged, temporary, or sabotage artifact remained.
- Live/provider/Discord/restart/full external end-to-end: `UNVERIFIED` — not
  exercised and not claimed by this offline evaluation.

## Independent read-only evaluation

`RESULT: PASS` — a separate read-only review confirmed that both protocol
tests resolve `testdata/protocol-v2/cases.json`, the failure mutations targeted
implementation paths rather than tests or corpus, and the restored guarded
paths have no tracked diff. `git diff --cached --name-status` was empty and
`git ls-files --others --exclude-standard` contained only the M3D record before
closure. Existing M3C limitations were retained: OWN-01 is a narrow Core
source-import guard rather than semantic ownership or manifest/dynamic-import
enforcement, and AUTH-02 covers the current Discord diagnostics serializer and
exercised callsites rather than arbitrary logging or a repository-wide scanner.
No live or external result was promoted to `PASS`.

## M3D verdict

| Mechanism | Detection | Recovery | Specificity | False-positive resistance | Scope honesty | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| PROTO-02 | PASS | PASS | PASS | PASS | PASS | PASS |
| OWN-01 | PASS | PASS | PASS | PASS | PASS | PASS |
| AUTH-02 | PASS | PASS | PASS | PASS | PASS | PASS |

Overall M3D verdict: `PASS`. The repository mechanically rejected one
representative violation for each accepted mechanism and returned to green
after every exact restoration.

## M3 system assessment

1. `RESULT`: Yes. The three source-level sabotage cases failed through their
   intended guards, not through direct test edits.
2. `RESULT`: The mechanisms stayed narrow: shared examples, one package-local
   AST guard, and diagnostics allowlists/sentinels; no hooks, CI, generic
   scanner, framework, or product/runtime feature was added.
3. `RESULT`: For these three selected invariants, enforcement now reduces
   reliance on instruction-following because representative drift fails
   deterministically in package tests. It is not a general correctness proof.
4. `RESULT`: No unacceptable false-positive or observed maintenance cost
   appeared in the exercised nearby legitimate states. Ongoing maintenance is
   explicit: both protocol consumers must keep consuming the corpus and new
   diagnostics event kinds require an intentional allowlist update.
5. `RESULT`: Canonical conversation semantics/history, provider auth and live
   behavior, lifecycle races and process containment, restart behavior, live
   Discord delivery, and diagnostics outside the guarded serializer remain
   docs/process/runtime/test-scope concerns rather than M3-wide guarantees.
6. `RESULT`: M3 is complete for the accepted PROTO-02/OWN-01/AUTH-02 scope.
   This is a human-review checkpoint, not a claim that Lilavel has blanket
   architecture or security enforcement.

## Handoff

- Git/checkout state: canonical `C:\Lilavel`, branch
  `feat/conversation-core`, HEAD/checkpoint
  `a7d0b8cca2a38961513838d220e6bc01cadfd82d`; no commit was created by M3D.
- Uncommitted changes: only this completed work record after its authorized
  active-to-completed move; nothing staged and no source/test/corpus diff.
- Blockers/unknowns: live/provider/Discord/restart/full end-to-end evidence is
  `UNVERIFIED`; OWN-01 and AUTH-02 limitations above remain in force.
- Completion: M3D exit criteria are satisfied; no implementation correction,
  new mechanism, `ART-01`, or M4 file was added.
- Next safe action: human review, then separately scope the next major phase
  if accepted.
