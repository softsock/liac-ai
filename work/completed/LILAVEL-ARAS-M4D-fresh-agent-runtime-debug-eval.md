# LILAVEL-ARAS-M4D — Fresh-agent runtime debug evaluation

Status: COMPLETED
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel` canonical checkout; evaluated snapshot was a clean export/clone of verified M4C-4 commit `f564e95b8a388bf644f0a1cd9182048b7ebe2899`
Branch / worktree: canonical `fix/p0.3-lifecycle-contract`; evaluation clone detached at `f564e95…`
Base commit: `ab68efea84ab5a44486482743446647fea0f5ea7`
Last checkpoint commit: `ab68efea84ab5a44486482743446647fea0f5ea7`

## Goal and scope

ARAS is for making Lilavel runtime behavior explainable to a fresh agent from
bounded, privacy-safe repository evidence while preserving Core semantic
ownership and honest deterministic/live evidence boundaries.

This evaluation measured runner discoverability, JSONL usefulness, identity
correlation, evidence-status discipline, source archaeology, and correctness
for four blind runtime questions plus one evidence-joining counterfactual. It
did not change runtime/source/tests/docs/config/hooks/CI, add scenarios, use
credentials, call provider/Discord services, or commit.

## Preflight and evaluated state

- Actual canonical checkout: `C:\Lilavel`, branch `fix/p0.3-lifecycle-contract`, HEAD `ab68efea84ab5a44486482743446647fea0f5ea7`.
- Initial canonical status was not clean: only untracked `apps/discord-edge/` generated cache/venv artifacts were present; no staged or tracked diff was present.
- M4C-4 was not an ancestor of canonical HEAD. The verified commit `f564e95…` was present on `origin/feat/conversation-core` and contained the runner, tests, README, and completed M4C-4 record.
- To avoid switching or changing the canonical checkout, blind agents and deterministic commands used a temporary clean snapshot/real Git clone at `f564e95…`. The snapshot deviation is a limitation, not a claim that the canonical checkout was clean.
- Runner command: `uv run --locked python scripts/scenario_runner.py <scenario>` from `apps/discord-edge`.
- Supported scenarios: `success`, `supersession`, `sidecar-failure`, `malformed-frame`, `discord-interruption`.
- Focused runner validation in the real Git clone: `10 passed`, one existing `audioop` deprecation warning. All five scenario commands exited `0`; the two typed failure scenarios intentionally returned `result=failed` with `expected_failure=true`.

## M4A baseline used for comparison

The completed M4A record reported:

- Fresh-agent debugging efficiency: `1/3`.
- Runtime/identity correlation: `1/3`.
- Replay/debug usability: `1/3`.
- Typical debugging: about five file surfaces plus source inference for supersession.
- Sidecar causality: runtime/source/test archaeology was required.
- No reusable one-command runtime trace or persisted cross-boundary evidence bundle.

## Blind fresh-agent setup and limitations

Five independent `gpt-5.6-luna` agents at maximum reasoning were started with
`fork_context=false`: Tasks A–D each had a separate agent, and the
counterfactual had a fifth. Each received only repository access to the
evaluated snapshot, repo-local instructions/docs, and its bounded question;
none received M4A–M4D context, source hints, expected answers, or credentials.

The delegation API exposed final answers and self-reported audit trails, not
complete tool traces, exact file-open counts, wall-clock times, or step counts.
Archaeology counts below are conservative lower bounds from those audit
trails. The first exported snapshot lacked `.git`; this caused one
non-runner-specific repository-state test failure, which was removed as an
environment artifact by rerunning the focused suite in a real Git clone.

## Task results

### Task A — Supersession / canonicality

Result: correct.

- Old semantic run bound to `fake-generation-1`, epoch `1`; replacement bound to `fake-generation-2`, epoch `2`.
- Cancellation was requested for the old run with reason `superseded`.
- One late delta was discarded as `not_current` (`1` event, `16` bytes).
- Old generation ended `cancelled`; old semantic run ended `superseded`; assistant commit was false.
- Replacement completed and committed the assistant response.
- `offline=true`, `evidence_surfaces=["core"]`; physical evidence was explicitly not invoked by the semantic test double.

The agent correctly separated deterministic Core/fake-generation evidence from
live provider generation identity, provider cancellation timing, response
races, and Discord delivery. It discovered and ran the runner, but then read
Core implementation and tests plus several docs to explain why canonicality
held. Archaeology: `MODERATE`, at least four source/test files.

### Task B — Sidecar failure classification

Result: correct.

- Failure was primarily a physical/runtime failure: `sidecar_crashed`.
- One semantic `run_id` correlated to one physical `generation_id`, epoch `1`.
- Physical sequence was generation created → valid `accepted` protocol event → failed terminal with `sidecar_crashed`.
- Core mapped the terminal run to `failed` with generic semantic `failure_code=provider_error`; no assistant was committed; runtime state was `failed`.
- The runner returned an expected typed observation with process exit `0`.
- It was not classified as malformed protocol or semantic-state failure.

The agent correctly stated that provider rejection, authentication, quota,
entitlement, endpoint availability, and model-side causality were not proven.
It used the runner and a focused test, then inspected the fake sidecar, runtime,
conversation, and related tests. Archaeology: `HEAVY`, more than five source/test
surfaces by the audit trail.

### Task C — Discord presentation correlation

Result: correct after a setup detour.

- Old semantic `run_id` / `core_run_id` bound to `fake-generation-1`, epoch `1`; its presentation chain was `flush 1 → POST operation 1 → request 1`, then `flush 2 → PATCH operation 2 → request 2`.
- Old presentation outcome was `interrupted`, reason `superseded`, with `flush_count=2` and `terminal_flush_count=1`; the interruption marker was presented.
- New semantic run bound to `fake-generation-2`, epoch `2`; its chain was `flush 3 → POST operation 3 → request 3`, then a final `flush 4` with no network operation.
- New presentation outcome was `completed`, with `flush_count=2` and `terminal_flush_count=1`; the new assistant committed.
- `core_run_id` was the parent join key; operation records carried `presenter_flush_id`; HTTP records carried `request_id` plus operation/flush references.
- Discord channel IDs, inbound/outbound Discord message IDs, provider/session IDs, and edge-local diagnostic IDs were correctly kept non-canonical.

The agent first tried a raw Python invocation and hit an import/setup failure,
then used a working local `uv`/`PYTHONPATH` invocation. It read runner, edge,
presenter, Core, diagnostics, and scenario/test surfaces. Archaeology:
`HEAVY`; the setup detour reduced runner discoverability to partial rather than
clean first-command success.

### Task D — Evidence-status discipline

Result: correct and conservative.

Directly proven offline by the runner:

- `success`: Core completion, physical fake-sidecar completion, run-to-generation join, and assistant commit.
- `supersession`: cancellation/supersession, late-delta discard, no old assistant commit, and replacement commit; intentionally no physical surface.
- `sidecar-failure`: typed `sidecar_crashed`, failed runtime/run, no assistant commit.
- `malformed-frame`: typed `protocol_error`, failed runtime/run, no assistant commit.
- `discord-interruption`: local fake presentation interruption/completion and Core-run-to-flush/operation/request/outcome joins; intentionally no physical sidecar surface.

Still LIVE/BLOCKED/UNVERIFIED:

- Real Luna/provider execution, supported auth, endpoint/entitlement/quota, provider response/timing, and provider-side cancellation causality: `UNVERIFIED` here; requires a live check.
- Real Discord gateway/DM ingress, remote delivery/edit/delete, reconnect/resume, rate limits, and real Discord IDs: `UNVERIFIED` here; requires a live check.
- A credential-free live Discord probe would be `BLOCKED` by missing `LILAVEL_DISCORD_BOT_TOKEN`, not evidence that Discord is unavailable.
- Full provider-to-Discord E2E, process restart/reconstruction, and general replay: `UNVERIFIED`.
- Provider personality, memory, retrieval, reflection, voice, and streamer behavior: outside this slice and unverified.

The agent ran all five scenarios and read validation semantics plus broad source,
tests, and work records. Archaeology: `HEAVY`; this task’s intentionally broad
status inventory required more than the runner alone.

## Counterfactual sanity check

A fifth fresh agent was asked to derive a relation by joining JSONL records,
not by quoting documentation. It correctly joined the run bound to
`fake-generation-1` with the `interrupted/superseded` presentation and joined
the second run bound to `fake-generation-2` with the `completed` presentation,
including `2` total flushes and `1` terminal flush for each. It also correctly
read the ordering as serialized output order rather than timestamp evidence.

This was derived from the JSONL evidence itself using a `ConvertFrom-Json`
join. Only the identity-boundary explanation needed supporting docs. The
counterfactual therefore passed its purpose: the runner was composable evidence,
not merely a verbatim answer lookup. Archaeology: `LIGHT`, limited to runner/
scenario-test confirmation plus docs.

## Blind score table

Scores are `0–3`: factual correctness, correlation correctness,
evidence-status discipline, source-archeology efficiency, and runner
discoverability/use.

| Task | Fact | Correlation | Status | Archaeology | Runner | Total / 15 | Archaeology class | JSONL alone |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| A supersession | 3 | 3 | 3 | 2 | 3 | 14 | MODERATE | No; source confirmed the causal explanation |
| B sidecar failure | 3 | 3 | 3 | 1 | 3 | 13 | HEAVY | Partial; source explained fixture/process mapping |
| C Discord presentation | 3 | 3 | 3 | 1 | 2 | 12 | HEAVY | Partial; JSONL carried joins/outcomes |
| D evidence status | 3 | 3 | 3 | 1 | 3 | 13 | HEAVY | No; validation/docs supported the full inventory |
| **A–D average** | **3.0** | **3.0** | **3.0** | **1.25** | **2.75** | **13.0 / 15** | **3/4 heavy** | — |
| Counterfactual | 3 | 3 | 3 | 2 | 3 | 14 | LIGHT | Yes for the composition/join |

Critical failure check: no agent treated partial output as canonical, promoted
provider/session/Discord IDs to semantic identity, claimed live provider
causality, missed the required run-to-generation or run-to-presentation joins,
or ignored the runner entirely. The main negative signal was unnecessary
source expansion after the runner had already supplied most task facts.

## Source-archaeology measurement

Audit-trail lower bounds for source/test files inspected were approximately:

- A: `≥4` (`MODERATE`).
- B: `>5` (`HEAVY`).
- C: `>5` (`HEAVY`).
- D: broad Core/sidecar/Discord source and test inspection (`HEAVY`).
- Counterfactual: about `2` source/test files plus docs (`LIGHT`).

Agent timing and exact step counts were unavailable. Against M4A’s typical
`~5` file surfaces plus source inference, the required A–D average did not
materially fall; three tasks remained moderate/heavy. The runner did reduce
the amount of inference needed for identity joins and typed terminal outcomes,
but not the agents’ tendency to validate or explain those outcomes by tracing
implementation.

## Before / after comparison

| Dimension | M4A before | M4D after | Finding |
| --- | ---: | ---: | --- |
| Runtime surface discoverability | 2/3 | 3/3 eventual | All agents found/used the runner; C needed an import/setup detour. |
| Identity correlation | 1/3 | 3/3 on covered joins | `run_id → generation_id/epoch` and `core_run_id → presentation chain` were answered correctly. |
| Replay/debug usability | 1/3 | 2/3 | A deterministic JSONL observation surface now exists; it is not a general replay framework or durable evidence store. |
| Fresh-agent debugging efficiency | 1/3 | 2/3 | Answers were correct and evidence-grounded, but source archaeology remained high. |
| Evidence-status discipline | 3/3 | 3/3 | Offline, LIVE, BLOCKED, and UNVERIFIED boundaries remained explicit. |

Conclusion: correctness and correlation improved materially; average source
archaeology did not. The runner became the natural first tool for most agents,
but not yet the only or sufficient tool for causal explanations and broad
evidence-status inventories.

## M4 verdict

`PARTIAL`

Evidence for the verdict:

- M4C-4 was operational and its focused tests passed `10/10` in a real Git clone.
- All five bounded scenarios were deterministic, offline, typed, privacy-safe, and process-successful.
- Four independent fresh agents were factually correct, correlated the required identities, and maintained evidence-status discipline; A–D averaged `13/15`.
- The counterfactual showed that JSONL records could be joined compositionally.
- The primary M4A target—substantial reduction in fresh-agent source archaeology—was not met across the required task set.
- The canonical checkout did not contain the post-M4C-4 commit, so this is a result for the verified M4C-4 snapshot, not proof that the current canonical branch has M4C-4 integrated.

M4 is therefore useful infrastructure with real bounded leverage, but not a
clear enough fresh-agent efficiency win to justify another harness layer yet.

## STOP/GO recommendation

`PAUSE` — return to Lilavel product work. Do not automatically start M5.

The runner has enough developer value to retain: it makes bounded cancellation,
failure, correlation, presentation, and privacy questions quickly inspectable.
The measured process tax is also real: agents still broaden into source/test
tracing, and the evaluation itself required snapshot/checkout care. Revisit
ARAS only when a concrete product debugging task demonstrates a missing
evidence surface or when the current runner is repeatedly insufficient. If
that happens, first simplify the evaluation/harness path or target one observed
pain, rather than adding a broader telemetry or replay layer.

## Human-readable compressed ARAS state

### What ARAS is for

Make Lilavel’s local runtime behavior legible to fresh agents through small,
deterministic, privacy-safe evidence surfaces while keeping Core semantic state,
provider transport, and Discord presentation in their existing ownership
boundaries.

### DONE

- M4A runtime-legibility baseline.
- M4B minimum evidence/correlation model.
- M4C-1 Core semantic lifecycle evidence.
- M4C-2 physical generation/sidecar evidence.
- M4C-3 Discord presentation correlation.
- M4C-I integration and M4C-4 thin deterministic JSONL runner.
- M4D fresh-agent evaluation: `PARTIAL`; no implementation changes.

### CURRENT / NEXT

- Current: bounded runner is useful, but fresh-agent efficiency gains are incomplete.
- Next: product work; revisit only after a concrete runtime-debugging pain appears.

### EXPLICITLY NOT NOW

- No M5 or broad observability/replay platform.
- No live provider/Discord claims, credential work, restart proof, voice, memory, or streamer expansion.
- No promotion of deterministic fixture evidence into live behavior claims.

### Proven capabilities

1. Core run-to-generation/epoch correlation for supported physical scenarios.
2. Supersession cancellation, late-delta discard, and canonical assistant-commit classification.
3. Typed sidecar-crash and malformed-protocol failure classification.
4. Deterministic Core/physical evidence JSONL with stable structural ordering.
5. Discord `core_run_id` to flush/operation/request/presentation-outcome joins.
6. Local interrupted-versus-completed presentation outcomes and terminal flush counts.
7. Safe omission of raw text, URLs, headers, bodies, credentials, provider/session IDs, and Discord IDs.
8. Explicit deterministic/offline versus LIVE/BLOCKED/UNVERIFIED status handling.

### Known limitations

- The current canonical checkout is on a branch without M4C-4; this evaluation used a verified temporary snapshot.
- Scenarios use fake sidecars, semantic doubles, and local HTTP doubles; they do not prove live provider, Discord, restart, or full E2E behavior.
- Supersession and Discord-interruption intentionally have no physical sidecar evidence surface.
- Fresh agents still perform moderate/heavy source archaeology for causal or broad status questions; exact timing/step telemetry is unavailable.
- The runner is a bounded observation surface, not a durable evidence store or general replay framework; generated IDs vary per invocation.

## What changed for Work chats

These are M1–M4 capabilities and working rules at the evaluated M4C-4
checkpoint, not a claim that the older canonical branch has them integrated.

REPO IS THE CONTEXT; CHAT IS THE CURRENT INTENT.

- Stable context lives in the repo; chat mainly supplies the current goal,
  scope, and human decisions. Shorter future prompts are possible; prompt
  savings were not measured by M4D.
- Fresh agents can reconstruct architecture from `AGENTS.md`, canonical docs,
  and ADRs, without a full retelling of earlier chats.
- Substantial tasks can continue across sessions through `work/` plus Git;
  M2D demonstrated fresh-agent handoff. Records do not preserve uncommitted code.
- Current Git, code, and canonical docs outrank stale records and reconstructed
  chats. Use `FACT`, `DECISION`, `PROPOSAL`, `HYPOTHESIS`, `RESULT`, and `UNKNOWN`
  where applicable; proposals and hypotheses do not become accepted decisions.
- A recorded next safe action supports more autonomous reversible, in-scope
  execution; consequential, destructive, external, or scope-expanding actions
  retain human gates where authorization is not already established.
- Selected invariants have tested mechanical backstops: shared-protocol drift,
  forbidden Core-to-Discord imports, and leakage on guarded diagnostics surfaces.
- The scenario runner is a deterministic debugging entrypoint with joinable
  JSONL; it covers the five bounded scenarios listed above.
- Supported evidence joins connect semantic runs to physical generation/epoch
  and sidecar events, or to Discord flush/operation/request/outcome chains.
  These are scenario-specific joins, not proof of live provider-to-Discord E2E.
- Parallel Work chats have an exercised safe path: isolated worktrees, disjoint
  ownership, and committed-checkpoint integration gates; coordination is manual.
- Validation distinguishes `PASS`, `FAIL`, `BLOCKED`, and `UNVERIFIED`, with
  deterministic, platform-specific, and live evidence kept separate.

### Still not solved

- Hard debugging still requires substantial source archaeology: A was
  `MODERATE`, B–D `HEAVY`; correctness did not remove that cost.
- Branch/worktree management still creates human cognitive load.
- No automatic dependency/orchestration layer or reusable skill framework yet.
- Keep these demand-driven. M4 remains `PARTIAL`; retain `PAUSE`, return to
  product work, and do not automatically build another ARAS layer now.

## Closure and handoff

- Exit criteria: satisfied for the evaluated M4C-4 snapshot; four tasks scored, runner use measured, archaeology measured, before/after comparison completed, counterfactual included, verdict/recommendation/compressed state recorded.
- Validation: deterministic runner/tests `PASS`; live provider, live Discord, external restart, and full E2E `UNVERIFIED` or `BLOCKED` as applicable.
- Canonical Git state after evaluation: unchanged HEAD `ab68ef…` on `fix/p0.3-lifecycle-contract`; no commit created.
- Uncommitted changes: this task-owned completed record is untracked; pre-existing untracked `apps/discord-edge/` generated artifacts remain untouched. No runtime/source/tests/docs/config/hooks/CI files were changed.
- No durable implementation checkpoint was created in the canonical checkout. The temporary evaluation snapshot/clone is disposable intermediate state.
