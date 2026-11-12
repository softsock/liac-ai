# M2 — Luna: Asynchronous Deep Mind via OMP

Implemented from M1.5 `656a12b` on `codex/m2-luna-omp`, 2026-11-12.
The existing isolated worktree was reused with a new branch; M1.5's ref remains
unchanged. [Requirements](superpowers/specs/2026-11-12-m2-luna-requirements.md)
and [approved Native plan](superpowers/plans/2026-11-12-m2-luna-omp.md) accompany
the implementation. Memory Store and a beat scheduler are not implemented.

## OMP lifecycle and confinement

`minds/omp.py` wraps the official synchronous Python `RpcClient` off-loop, with
one serialized owned process/session. The SDK owns JSONL correlation, protocol
negotiation, streaming and frame decoding. A command acknowledgement is not a
finished inference: require correlated completed/settled `prompt_result` and a
final assistant message with `stopReason=stop`. Output is bounded to 64 KiB;
serialized evidence above 512 KiB fails explicitly without cursor advancement.
There is no JSON repair or assumption of provider constrained decoding.

The independently installed binary is **OMP 18.12.6** at
`C:/Users/shtvl/AppData/Local/omp/omp.exe`. Only the unmodified **444207-byte,
18-file Python SDK subtree** is vendored, pinned to upstream
`45c35e40c46166dc726ccc52f5d27f40f2449f99`, with license and per-file SHA-256
manifest. `.gitattributes` preserves those bytes on Windows. The fake backend
does not import or require the SDK; install it explicitly through
`requirements-luna.txt`. No OMP engine build or service installation.

Actual model selection was verified as **openai-codex/gpt-6-luna**, advertised
context **272000**, `supportsStrictMode=False`, using existing provider auth.
No credentials were copied or printed. Sessions/workspace are private under
`.data/luna` by default. Built-in tools, extensions, skills, rules and LSP are
disabled, with project-MCP/discovery isolation and blank profile overrides.
This is application confinement, **not an OS security sandbox**. Global OMP
configuration/authentication remain an external dependency.

Startup is lazy and never gates Fast. Timeout/cancellation aborts and stops the
owned child off-loop, then joins the operation before permitting another child.
Repeated cancellation cannot release that lifecycle lock early. A non-True stop
result or unconfirmed operation cleanup latches the transport unsafe until a new
Runtime. New processes rebuild disposable Luna context from canonical requests;
session files are not authoritative. Composition closes Runtime, OMP, Journal,
then the Fast HTTP pool. No unrelated process is killed.

The initial live transport probe parsed JSON in **1511 ms**, abort acknowledged
in **14 ms**, and `--continue` restored the same session ID. The production
adapter separately completed a JSON probe in **2100 ms**, cancelled real work and
confirmed cleanup. Session-resume capability is verified, but production recovery
intentionally rebuilds rather than blindly trusting an uncertain transcript.

## Observation, proposals and durable acknowledgement

`contracts/deep.py` defines frozen `DeepRequest`, `DeepResult(schema_version=1)`
and `DeepDecision`. One `runtime/deep.py` worker observes completed turns even
while subsequent Fast turns run. The nominal 100-event cap is soft: a single
large complete turn may exceed it; interleaved superseded turns wait until all
included users have terminal outcomes. User text, exact completed replies and
relevant lifecycle events stay together. Cancelled/failed turns contain their
status, never partial speech. Audit-only tails are acknowledged without inference.

Only two optional proposal types are implemented:

- Replacement working note, maximum **1000 characters**, with evidence IDs.
- Semantic `CompactionProposal` containing at most **32 summary items**, at most
  **32 source IDs/item** and **8000 characters/item**, additionally constrained by
  M1.5's **2048-token** incremental epoch-block budget (scaled for small windows).

Both null is an explicit no-op. Runtime assigns operation IDs and all authority
metadata from the captured request. Model JSON cannot change character, versions,
cutoff or identity. Duplicate/unknown keys, nonfinite values, boolean versions,
unsupported operations and invented evidence reject. Notes can cite supplied
current/past snapshot evidence and previous epoch provenance, not just the new
batch. Journal independently verifies the actual same-character source events.
Source attribution does not prove a semantic interpretation is true.

`Journal.apply_deep()` validates against the pre-batch state and atomically writes
epoch, note, operation decisions, batch decision and cursor. Compaction precedes
the batch's own note increment, avoiding a self-created revision conflict.
Identical request/result replay returns the original decision; conflicting reuse
fails. Injected failure at batch-audit insertion rolls everything back. SQLite
schema remains v2 and raw Journal records are never deleted.

Changed note revision invalidates dependent notes/compaction; changed epoch
invalidates both notes and compaction because every request exposes epoch context. New dialogue alone does not invalidate an older legal
cutoff. Stale batches apply no partial update, record rejection and leave cursor
unchanged. Fresh analysis gets new IDs/current bases; important source input is
still available. No silent rebase. Failed/malformed/budget-rejected requests also
leave input unacknowledged. Retry delays are **1/2/4/8/16 seconds**, then degraded
wait; `/retry` interrupts a backoff. Audit writes cannot trigger an inference loop.

`usage_limit_reached` was observed live. It now records a bounded provider status
and latches Deep until Runtime restart after availability returns, rather than
spawning repeated children. Fast and durable input remain usable. Other transient
transport errors use bounded retry. Diagnostics expose lifecycle, model/session,
usage, error class, analysis/commit timing, watermark and decision, never hidden
reasoning, credentials or unrestricted transcripts.

## Semantic epochs and character continuity

Both minds receive the single authored `character.md` identity. `deep.md` only
explains the hidden role: causal continuity, corrections, promises, optional humor
and specific future performance ideas. Fast writes the final utterance. One
working note can suggest a beat; scheduling, TTL and one-shot execution are FUTURE.

At **75%** of the Fast input allowance, Runtime signals background preparation.
Defaults remain **16384 − 512 output − 32 margin = 15840 input**; trigger **11880**,
fallback above **14256**. Luna receives eligible raw dialogue plus original
sources behind existing epoch items, and prepares source-backed semantic summaries.
The new epoch switches atomically. Messages newer than its cutoff remain exact;
an active Fast generation retains its frozen snapshot. Repeated no-op preparation
at the same epoch/revision/cutoff is coalesced until new evidence or `/retry`.
Restart reconstructs pending work from cursor and persisted context pressure.

If Luna is late/offline, M1.5's synchronous deterministic fallback still runs at
90%. Required identity/note/current-input overflow still fails durably before Fast
HTTP. Stateless Nemotron rendering, BOS handling, exact tokenizer counting and
provider parity verification are unchanged. Early pressure currently adds an
extra local count on submit; its CPU cost is included in measurements below.

## Live acceptance and measurements

Environment: same RTX 5070 Ti, LM Studio **0.4.28**, CUDA12 llama.cpp **2.73.0**,
preloaded `liac-nemotron` Q4_K_M, context 16384, endpoint port **1230** as M1.5.
No shared model settings/reload were changed. The real verifier is
`scripts/verify_m2_luna.py`; `--self-check` needs no providers. Its default command:

```powershell
python scripts/verify_m2_luna.py --omp-executable C:/Users/shtvl/AppData/Local/omp/omp.exe --output .data/m2-results.jsonl
```

Private evidence stays ignored. Completed conversation samples are run
`m2-3bf89194e3` trials 0/1 and replacement run `m2-d31d73b35f` trial 0.
The original third trial reached one epoch then hit a provider usage limit; it
is retained in the evidence but excluded from the completed-trial distribution.
After a new Runtime launch the provider became available without auth changes.
Thus there are **three complete trials, six semantic switches, 69 garden turns**,
18 individual recall turns and three post-restart recall turns. Provider/local
Fast prompt-token equality was asserted on every recorded completed turn.

| Fast metric | All 69 garden turns p50 / p95 | 57 turns started during Luna inference p50 / p95 |
|---|---:|---:|
| Adapter TTFT | 354.85 / 513.92 ms | 359.15 / 524.31 ms |
| Submit to first visible delta | 381.94 / 557.12 ms | 389.63 / 557.22 ms |
| Local preparation | 19.84 / 35.47 ms | 21.82 / 37.65 ms |
| Compile | 10.44 / 18.32 ms | 11.74 / 18.42 ms |
| Submit to completion | 406.62 / 580.17 ms | 413.20 / 581.08 ms |

p95 uses nearest rank. Semantic preparation took **7.67–14.12 seconds** in these
six switches, with atomic commit **3.25–3.95 ms**. Fast had continued before the
verifier waited at the pressure boundary; that deliberate verifier wait is not
Runtime behavior. This sample does not isolate a causal TTFT cost of concurrent
Deep work. M1.5 ordinary TTFT was 337.71/404.91 ms, but lengths, note contents and
sampling differ: no speedup or matched regression claim. M2 did not recapture
llama.cpp evaluated-token logs; exact KV reuse percentages remain unmeasured here.

| Scenario | Actual outcome |
|---|---|
| A — observation | Real Luna saw canonical user/Fast text and committed useful source-backed notes, including the fictional penguin. |
| B — independence | 57 garden turns began during real Luna inference. In `m2-81caf85c11`, a verifier held a real completed Luna result: another Fast reply completed in 359.57 ms while cursor stayed unchanged. The held-delivery delay is injected, not provider latency. |
| C — retention | After two semantic epochs, green hat, amethyst stone, Hazel bridge, Saffron boat, noon promise and fish-tax joke all recalled: **18/18** checks across three trials. Green recalled after Runtime/OMP restart **3/3**. No loss in this fixture; not a general retention guarantee. |
| D — preparation | Background preparation triggered at 75% before fallback; six semantic epochs committed. Frozen active snapshots and late newer-turn preservation are pinned by focused tests. Commit-while-streaming is not separately isolated in the timing sample. |
| E — recovery | Three Runtime reopenings restored epoch/cursor, consumed unfinished Deep ranges and left zero unfinished Fast replies. In `m2-81caf85c11`, the verifier killed only the owned OMP child during real analysis; fresh-session retry advanced cursor **11 → 16**. |
| F — stale result | Held real result based on revision 0 rejected after an external revision-1 note. Cursor remained 0; fresh Luna analysis committed revision 2 and acknowledged the range. Old/new decisions are durable. |
| G — unavailable | Missing executable left cursor 0 while 14 real Fast turns crossed 90% and produced fallback epoch 1. Restoring executable plus `/retry` yielded a real Luna note/revision 1. Fallback preparation **454.26 ms**, submit-first **1093.02 ms** in that run. |

Real Fast supersession in the same acceptance run cancelled in **5.48 ms**, with
one durable cancelled terminal. Owned processes were closed after each run.

**Failed sample retained:** genuine CLI run `m2-13ab358584` exited cleanly twice,
restored history and a committed note, but its short second-process hat question
elicited “I haven't been told what color hat Mandarin wears” despite exact history.
The first note focused on Fast's refusal to say READY rather than the hat fact.
This is a model/curation-quality failure; persistence alone cannot guarantee recall.
That run also exposed overly narrow note-source validation: prior snapshot IDs
were supplied but rejected. A RED→GREEN regression now permits those canonical
sources. The failed recall is not retroactively counted as passed. A later genuine CLI
run `m2-663221da4c`, using an explicit fictional-story introduction, completed
real Deep analysis in both processes and recalled green after restart.

## Verification, decisions and limits

Stdlib suite: **67 tests pass on Python 3.12.14 and 3.14.7**, including batch rollback/replay, terminal
boundaries, source/schema rejection, held Deep independence, bounded retry,
interruptible manual retry, quota latch, off-loop SDK operation and confirmed
cancellation. Both suites ran with `-X dev`; wheel build includes deep.md, the 18 SDK hashes
match upstream, fake startup works without optional packages, and six live DBs
returned `integrity_check=ok`. Existing M1.5 migration, exact token/template and stream checks remain.

Execution decisions: reused the isolated worktree on a new branch; one final
implementation commit; additional local pressure count; note evidence accepts
supplied snapshot/epoch provenance; quota failure latches until restart; exact
vendor bytes preserved. Costs are the old workspace path, uncommitted intermediate
work, extra local CPU, reliance on semantic attribution and manual quota recovery.

One Runtime owns one DB. Entire supplied evidence is bounded by the 512-KiB
transport gate; an oversized complete turn remains unacknowledged/degraded rather
than silently truncated. SDK session history may grow/compact; canonical requests
remain the recovery source. Full-history retrieval, semantic truth, adversarial
persona consistency, provider auth portability, OS isolation and physical
power-loss durability are not established. M3 should evaluate permanent memory
and retrieval separately, with holdout facts and failed recalls retained.

Final Native review: one fresh GPT-6.1 Terra reviewer found two Important issues,
no Critical/Minor: a persisted user without reply.started blocked closed-prefix
observation after crash, and note-only results missed epoch dependency checks.
Both reproduced RED and passed after fixes. Startup now gives every accepted
input without a terminal a durable process_restarted cancellation, including
never-started replies; it does not regenerate speech.

Final verification also reproduced a shutdown race on Python 3.12: cancellation
arriving during an already-failing OMP cleanup was swallowed, allowing worker
retry after close. Regression checks now cover cancellation during error cleanup
and failing SDK construction, plus a Deep adapter that swallows cancellation.
Cleanup preserves cancellation, joins owned work and avoids Python 3.14 shield
exception logging; an explicit worker stop flag prevents post-close commits/retry.
All fixes are RED→GREEN in the single final fix pass; full suites are green.
A final real Luna JSON/cancel/confirmed-close smoke passed after these changes.

Reviewer exclusions were independently handled: root collected live A–G evidence
and SDK hashes; >512-KiB evidence remains the explicit degraded/replayable limit.
No second reviewer or deferred Minor findings. Early quota/CLI failures remain
in the report. No push, PR or merge is part of this implementation.
