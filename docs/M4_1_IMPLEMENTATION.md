# M4.1 — Attention Engine

Implemented on `codex/m4-1-attention` from desktop inspector `c6c8b24`, which
contains M2 `fc20df6`. The user explicitly changed the original M2-only base to
desktop. [Execution plan](superpowers/plans/2026-11-13-m4-1-attention-engine.md).
No memory store, Performance Beats, autonomous speech or new agents/dependencies.

## Architecture and contracts

The existing `DeepWorker` still owns one serialized background pipeline and OMP
session. Each completed-turn batch can propose a note, semantic compaction and
attention in one schema-v2 result. Fast owns its frozen snapshot and never waits
for Luna. No signal enters `ContextCompiler` or Nemotron's instructions.

`AttentionProposal` contains kind, significance, outcome, reason, source IDs,
optional relative TTL, optional target ID/version and explicitly superseded IDs.
The frozen persisted `AttentionSignal` adds Runtime-owned identity, character,
version, observation watermark, processing status and UTC timestamps/expiry.
`AttentionView(through_sequence, signals)` is a read-only M4.2 boundary, not an
authorization to speak or evidence that a beat was used.

Kinds: topic/mood change, callback, open loop, correction, boundary, opportunity,
other. Significance: low/normal/high. Outcomes `notice/defer/ignore` become
`noticed/deferred/ignored`. Later Runtime transitions include `superseded/expired`.
Terminal signals do not revive. An empty list is normal: ignore need not produce
one record for each mundane message.

Luna interprets semantics with the existing single character identity. Runtime
validates enum/text/count bounds, captured IDs, same-character canonical evidence,
watermarks, target versions and conflicting updates. Hash-based creation identity
uses character + kind + sorted source IDs, independent of generated wording.
Historical keys are retained in `attention_provenance`, so updating A→A+B→A+B+C
cannot make a later paraphrase of A or A+B a new signal.
Semantic duplicates citing different sources still require Luna to reuse a target;
hashes cannot solve that semantic problem. Updates retain original provenance.

## Persistence, scheduling and expiry

SQLite v3 additively creates `attention_signals`; old events, notes, epochs and Deep
cursors remain. Signal/lifecycle audit, note/epoch changes and acknowledgement
share the existing transaction. An injected final-audit insertion failure proves
all roll back. M2 audit replay supports its old fingerprint/decision shape; new
schema-v1 results are refused. Back up data before migration: old applications
cannot open v3. The committed EXE is still the desktop milestone build; launch
current sources to use attention, with a separate database when comparing builds.

Complete-turn raw batches remain chronological, grouping input accumulated while
Luna is busy. Runtime cannot know semantic importance before the model evaluates
it. Captured active signals are ordered boundary/correction first, then high to
low significance, newest observed watermark, stable ID. Original source events
are supplied again, including after epoch/OMP restart. Important pending semantic
constraints thus precede minor opportunities; an in-flight request is not preempted.

Deferred signals are reconsidered in the next normal completed-turn batch, not a
second request or timer loop. Compaction remains combined in the same inference
under pressure with the M1.5 fallback preserved. Expiry/audit tails cannot trigger
new model work. Failed requests retain cursor and use existing bounded retries.

Optional TTL is 1..86400 seconds from the newest cited Journal `recorded_at`, not
result arrival. Absolute UTC expiry survives restart; cached monotonic deadlines
also prevent backward wall-clock jumps extending existing in-process signals.
Reconsidering the same evidence cannot extend/remove a finite expiry; genuinely
newer evidence is required. Deadline-cache changes roll back with SQLite failures.
Expiry is maintained during batch preparation, application and inspection. It
means stale, never consumed. No-TTL promises/boundaries remain until superseded.

## Inspection

```text
/attention
/attention noticed 20
/attention deferred 20
/attention-source EVENT_ID
/status
```

Filters also include ignored/superseded/expired; count is 1..100. Output includes
reason, status, sources and expiry; cross-character source lookup is refused.
Desktop's existing request/response/decision JSON automatically exposes the new
fields. Dedicated UI controls and EXE rebuild are outside this change.

## Real-provider evaluation (2026-11-13)

Private evidence: `.data/m4-1/run-0641423528`, with production traces under
`traces/run-7cdfb64207044601a795ca936b9ba21d`. Run:

```powershell
python scripts/verify_m4_1_attention.py --omp-executable C:/Users/shtvl/AppData/Local/omp/omp.exe
```

The fixture labels preceded inference (`--self-check` checks them). Nine dialogue
turns used real loaded `liac-nemotron`, 16384 context, endpoint port 1230 and real
`openai-codex/gpt-6-luna` through OMP. All 13 Fast turns across the conversation,
restart and fault scenarios completed; tokenizer/provider counts matched. Four
started while real OMP inference was active. No shared model settings changed.

| Scenario | Observed behavior |
|---|---|
| Loss and promise | No forced loss joke; one source-backed open replay promise. |
| Topic/mood shift | Forest-walk topic and calmer mood noticed, citing prior disappointment. |
| Return/correction | Existing replay loop updated and former topic superseded; Golden Otters correction noticed. No separate callback-kind signal: strict category recall misses it, though the connection is explicit in the open-loop update. |
| Stop teasing | High-significance boundary noticed with source; no automatic command/speech. Primary run had no teasing-opportunity signal to cancel, so it alone does not establish live supersession of one. |
| Three mundane repeats | Zero new attention signals; no manufactured activity. |
| Busy/deferred | Completed input retained while OMP worked. Held-delivery scenario produced a real deferred open-loop signal and updated it on new input. Delay itself was injected after real inference. |
| Restart | Runtime stopped with cursor 0 and completed input through 3; new Runtime/OMP recovered it and committed a source-backed open loop. |
| Unavailable | Missing OMP executable was injected; real Fast still completed with unacknowledged input retained. |

Manual primary-conversation evaluation: five new signals, all grounded and
appropriate (5/5 on this tiny synthetic sample), zero obvious semantic duplicates,
zero new signals from three mundane turns. Important labeled source episodes
promise/topic/callback/correction/boundary: 4/5 have the expected strict category;
the callback is instead represented by updating its existing open loop. This is
not a holdout benchmark or a general quality guarantee. Autonomous reactions are
zero by construction and are not counted as semantic accuracy.

One real Luna result attempted an invalid target/category update and was rejected;
bounded retry reanalyzed the same input successfully. Failed proposals did not
advance cursor. This is an observed protocol reliability cost, not hidden repair.

A supplemental two-turn check used **real Luna with FakeFast** and restarted
Runtime/OMP between turns (private `.data/m4-1/supplemental-boundary`). Luna first
deferred a specifically earned Swiss-cheese-goalie callback, then on “stop jokes”
created a high boundary and explicitly superseded that callback (version 1→2).
This directly verifies deferred-source restoration and semantic supersession
after restart. It does not supply real Fast latency/character-speech evidence.
The two supplemental calls took 9.067/7.906 seconds and reported 5498 input + 619
output tokens, cost-field sum 0.0008593; these are separate from the table below.

| Timing | p50 | p95 (nearest rank) |
|---|---:|---:|
| Fast adapter TTFT, 9 dialogue turns | 123.38 ms | 162.35 ms |
| Submit to first visible delta, same 9 | 130.00 ms | 167.91 ms |
| Submit to completion, same 9 | 302.35 ms | 355.48 ms |
| Fast adapter TTFT, all 13 scenario turns | 121.73 ms | 271.43 ms |

Ten committed Deep calls: analysis median 8864.64 ms, range 2664.58–15546.94 ms;
commit median 2.08 ms, range 1.483–2.869 ms. Eleven completed OMP calls reported
42405 input, 4610 output and 86784 cache-read tokens; total 133799. Reported summed
cost field: 0.00741334 (provider-reported units, not a billing guarantee). Cancelled
or incomplete calls without final usage are not included. These are combined
attention/context calls: per-attention cost is not separately measurable.

A matched baseline attempt used an immutable desktop/M2 source snapshot and the
same fixture/settings, but LM Studio was unavailable (`httpx.ConnectTimeout`, no
listener on 1230). No paired speedup/regression claim follows. M2's historical
TTFT is not comparable to this shorter fixture. KV reuse was not rebenchmarked.

## Checks and readiness

Current invariant suite passes 100 tests on Python 3.14.7 and 3.12.14. Checks include
source/target rejection, migration, old audit replay, whole-batch rollback,
deduplication, lifecycle/clock rollback, busy correction batching, streaming,
cancellation and existing Qt worker/trace tests. Fake checks do not prove semantic
provider quality. Live results above cover the six requested scenario classes.

One fresh read-only reviewer found three important edge cases: same-evidence TTL
extension, historical-provenance deduplication after updates, and rollback of
in-memory monotonic deadlines. All three were reproduced with failing tests,
fixed in one pass, and verified by the full suite. No minor findings were deferred.

Execution rulings: the approved planning files were absent on the initially
selected `main`, so their decisions were reconstructed from the chat; the user's
desktop-base override was preserved. No shared provider reload was attempted to
obtain a baseline after it became unavailable, leaving comparison unmeasured.
The reviewer set aside broader semantic recall, baseline performance, M4.2 beat
consumption, EXE rebuilding and open-signal retention policy; these remain explicit
limits rather than implied implementation guarantees.

M4.2 can read fresh noticed signals and their evidence. It must compare the view's
watermark against current completed input, recheck expiry and current boundaries,
then separately propose/validate beats. No claim/consumption protocol exists yet.
No durable signal is a verified fact or an executable instruction.

Limits: one source-backed synthetic dialogue is small; semantic target mistakes
can cost retries. Active no-TTL signal growth has no new eviction policy; existing
512 KiB request/64 KiB response caps fail explicitly without dropping evidence or
advancing cursor. No long-term retrieval, unattended deferred inference, automatic
reaction, dedicated attention desktop pane or updated EXE is supplied.
