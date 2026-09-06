# LILAVEL-ARAS-M4C-I — Runtime Evidence Integration

Status: COMPLETED
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel`, isolated integration worktree `C:\Lilavel-m4c-integration`
Branch / worktree: `work/m4c-runtime-evidence-integration` / `C:\Lilavel-m4c-integration`
Base commit: `6bcbc74f7e41f8cda870d54a37677442ca548909` (committed M4C-1)
Last checkpoint commit: none; no integration commit was created

## Goal

Integrate the clean committed M4C-2 and M4C-3 checkpoints and prove Git,
semantic, privacy, enforcement, and deterministic-validation compatibility
without implementing M4C-4 or merging back to the canonical checkout.

## Commit-state gate

The actual pre-integration state passed the checkpoint gate:

| Checkout | Branch | HEAD | Status | Checkpoint evidence |
| --- | --- | --- | --- | --- |
| `C:\Lilavel` | `feat/conversation-core` | `6bcbc74f7e41f8cda870d54a37677442ca548909` | clean, tracking `origin/feat/conversation-core` | committed M4C-1 and record |
| `C:\Lilavel-m4c-2` | `work/m4c-2-physical-sidecar-evidence` | `a48b4275f0bb9a9462bfee2bfe15aabafac4038c` | clean | implementation plus `LILAVEL-ARAS-M4C2-physical-generation-sidecar-evidence.md` committed |
| `C:\Lilavel-m4c-3` | `work/m4c-3-discord-presentation-correlation` | `da5cd69050d45b0543ae1ec3d611e530cb56c0c5` | clean | implementation plus `LILAVEL-ARAS-M4C3-discord-presentation-correlation.md` committed |

Both task SHAs are descendants of M4C-1; `merge-base --is-ancestor` returned
success for each. No unrelated changes were present in either task worktree.
The existing task records retain some pre-checkpoint handoff wording, but
actual Git state is authoritative; this record records the verified SHAs.

## Integration strategy and conflict status

- No stale `C:\Lilavel-m4c-integration` path or
  `work/m4c-runtime-evidence-integration` branch existed.
- Created the isolated worktree/branch from M4C-1.
- Used a read-only three-way merge preview of
  `a48b4275f0bb9a9462bfee2bfe15aabafac4038c` and
  `da5cd69050d45b0543ae1ec3d611e530cb56c0c5`.
- Preview tree: `fb476b22da856fcec58fec79c1bb917c85701882`.
- Textual conflicts: none.
- The preview tree was materialized into the integration index/worktree
  without a merge, cherry-pick, or resolution commit. `HEAD` remains the
  M4C-1 base, and both exact task checkpoint SHAs remain the history authority.
- Conflict index entries: none. `git diff --check`: PASS.

The task ownership paths are disjoint: M4C-2 changes Core/runtime/sidecar
surfaces; M4C-3 changes Discord diagnostics/presentation surfaces. No semantic
conflict required resolution.

## Semantic compatibility audit

RESULT: PASS.

1. `run_id` retains one semantic meaning: one Core conversation turn and its
   transient assistant candidate.
2. `generation_id + epoch` remain the physical-generation identity owned by
   Core/runtime and the existing protocol.
3. Sidecar `requestId == generation_id` remains a tested alias on the current
   Core-host path, not provider semantic truth. Direct sidecar callers without
   `GenerationIdentity` remain outside Core correlation.
4. `core_run_id` is only an edge-local diagnostic copy of Core `run_id`; it is
   not added to Core history, model requests, persistence, or the protocol.
5. Discord channel/message IDs remain edge-local admission/dedupe/presentation
   metadata and are not promoted into Core evidence or canonical identity.
6. Provider/session IDs remain transport/auth-boundary details and are not
   retained in Core evidence or promoted to semantic identity.
7. Runtime evidence remains bounded, ephemeral diagnostic evidence; it does
   not enter canonical history or durable provenance storage.
8. No duplicate or conflicting correlation abstraction appeared. The existing
   Core join is `run_id -> generation_id + epoch`; the edge join is
   `core_run_id -> flush_id -> operation_id -> request_id`.
9. No hidden M4C-2/M4C-3 dependency appeared after integration. The only
   shared contract is the already-committed M4C-1 `run_id` seam.

## Combined evidence-chain proof

The current deterministic surfaces prove the joins separately:

```text
Core semantic branch:
run_id
  -> generation_bound(generation_id, epoch)
  -> physical generation_created/protocol_event/generation_terminal
  -> sidecar requestId alias and terminal protocol evidence

Discord presentation branch:
run_id == edge-local core_run_id
  -> flush_id
  -> operation_id
  -> HTTP request_id
  -> presentation_outcome
```

Core lifecycle evidence tests prove accepted runs, cancellation,
supersession, late-delta aggregation, failure, assistant-commit boundaries,
and bounded/snapshot-isolated records. Physical evidence tests prove accepted,
delta-count-only, completed, cancelled, failed, crash, bounded, and
snapshot-isolated projections. Sidecar tests prove the Core generation alias
and unchanged protocol shapes. Discord tests prove completion, supersession,
concurrency isolation, safe failure outcomes, and flush/operation/request
joins.

There is still no single deterministic scenario that exercises Core semantic,
physical sidecar, and Discord presentation branches in one run. No runner was
built here. That missing single-scenario join is explicitly M4C-4 scope.

## Privacy and security regression

RESULT: PASS.

- Core and physical evidence retain IDs, safe enums/codes, counts, and byte
  lengths only; raw message text and raw deltas are absent.
- Diagnostics do not emit auth/token/header/URL/body/exception-message values.
  Exception output is reduced to a type name; rate-limit bucket values are
  hashed; stdout/stderr and protocol boundaries remain unchanged.
- Discord diagnostics use positive per-event allowlists, including the new
  correlated fields, and adversarial sensitive-sentinel coverage remains green.
- Provider/session and Discord IDs are not promoted across their ownership
  boundaries.
- Partial, cancelled, superseded, failed, stale, or interrupted assistant
  output remains non-canonical; the Core commit boundary is unchanged.
- AUTH-02 diagnostics allowlist/redaction coverage passed.

## M3 enforcement preservation

RESULT: PASS. No new enforcement mechanism was introduced.

- PROTO-02: Core shared-protocol and architecture target `50 passed`; sidecar
  shared Protocol V2 corpus target `36 pass`.
- OWN-01: Core dependency-direction guard included in the `50 passed` target.
- AUTH-02: Discord diagnostics/semantic target `31 passed`, including the
  allowlist and sensitive-sentinel guard.

## Deterministic validation matrix

All commands were run from the integrated worktree on Windows.

| Surface | Validation | Result |
| --- | --- | --- |
| Core | `uv sync --locked`, `uv lock --check` | PASS |
| Core | Ruff check and format check | PASS |
| Core | Pyright | PASS — 0 errors, warnings, or informations |
| Core | full `uv run --locked pytest` | PASS — `127 passed` |
| Core | M4C-1 runtime-evidence target | PASS — `5 passed` |
| Core | M4C-2 physical-evidence target | PASS — `4 passed` |
| Sidecar | frozen Bun install | PASS |
| Sidecar | TypeScript check | PASS |
| Sidecar | full Bun suite | PASS — `65 pass`, `0 fail`, `217 expect()` |
| Sidecar | Core generation alias target | PASS — `1 pass` |
| Sidecar | protocol server lifecycle target | PASS — `1 pass` |
| Discord | `uv sync --locked`, `uv lock --check` | PASS |
| Discord | Ruff check and format check | PASS |
| Discord | Pyright | PASS — 0 errors, warnings, or informations |
| Discord | full `uv run --locked pytest` | PASS — `68 passed` |
| Discord | M4C-3 diagnostics target | PASS — `3 passed` |
| Discord | M4C-3 edge correlation target | PASS — `4 passed` |
| Repository | `git diff --check` and conflict-index check | PASS |

Discord tests emitted only the existing non-causal Python `audioop`
deprecation warning. The one malformed focused command was corrected and the
intended focused tests then passed; it was not a test failure.

## Independent read-only review

RESULT: PASS.

A separate read-only pass over the materialized combined tree checked:

- semantic identity conflation and duplicate evidence concepts;
- Core-to-Discord ownership direction and circular dependencies;
- privacy/redaction and positive allowlist behavior;
- Protocol V2 corpus parity and stdout framing;
- merge-resolution behavior and disjoint task paths;
- partial-output/canonical-commit boundaries;
- hidden cross-branch assumptions and M4C-4 overreach.

No material issue was found. The combined tree contains no implementation,
runner, replay, or sabotage artifact for M4C-4.

## Verdict

| Dimension | Verdict |
| --- | --- |
| Git compatibility | PASS |
| Semantic compatibility | PASS |
| Correlation coherence | PASS, with the documented M4C-4 single-scenario gap |
| Privacy/redaction integrity | PASS |
| M3 enforcement preservation | PASS |
| Deterministic validation | PASS |
| Maintenance/complexity impact | PASS — bounded projections, unchanged protocol, disjoint ownership |

Overall M4C-I verdict: `PASS`.

## Limitations

- No live provider/auth execution, live Discord delivery, restart
  reconstruction, or full external E2E was run or claimed.
- Deterministic fixtures do not establish provider entitlement, quota, timing,
  Discord connectivity, or restart behavior.
- The integrated tree is intentionally uncommitted; no durable integration
  checkpoint exists yet.

## Handoff and recommendation

- Canonical `C:\Lilavel` remains clean at M4C-1
  `6bcbc74f7e41f8cda870d54a37677442ca548909`.
- M4C-2 remains clean at `a48b4275f0bb9a9462bfee2bfe15aabafac4038c`.
- M4C-3 remains clean at `da5cd69050d45b0543ae1ec3d611e530cb56c0c5`.
- Integration remains isolated at `C:\Lilavel-m4c-integration`, branch
  `work/m4c-runtime-evidence-integration`, with `HEAD` still at M4C-1 and the
  validated combined tree plus this completed record uncommitted.

Exact recommendation: perform a human M4C-I checkpoint review first. If
accepted, explicitly checkpoint the combined tree in the integration branch
and then explicitly merge/cherry-pick that checkpoint into
`feat/conversation-core`; do not merge automatically from this run. Start
`M4C-4 — Thin Deterministic JSONL Scenario Runner` only from that durable
integrated checkpoint, reusing the three stable evidence surfaces and keeping
the single-scenario join bounded to the approved M4C-4 scope.
