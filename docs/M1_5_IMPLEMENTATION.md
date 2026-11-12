# M1.5 — Context Lifecycle & KV Cache Optimization

Implemented on `codex/m1-context-cache`, based on `e3bd3ae`, 2026-11-12.
M1's report remains historical. This milestone replaces its rolling window and
byte estimate, retaining stateless LM Studio, SQLite authority and FakeDeep.

## Context epochs

Schema v2 adds immutable `(character_id, version)` epoch records. Version zero
is implicit. Migration from v1 is additive: original events, notes and Deep
cursors are preserved. A coherent snapshot contains state, epoch, watermark,
all subsequent exact dialogue and terminal-turn boundaries, including cancelled
and failed turns. Partial replies never become completed history.

Order: **identity → frozen quoted epoch items → growing exact history → quoted
active state/note → current input → generation prefix**. A note update changes
the mutable tail. No individual history messages disappear within an epoch.
An active Fast snapshot is immutable even if a note or epoch commits concurrently.

At the next input above **14256** counted tokens (90% of the input allowance),
the pure policy prepares a deterministic proposal. It keeps up to three newest
whole terminal turns within 2048 incremental tokens. A separate 2048-token block
holds an oldest-user anchor and newest source-backed extracts, chronologically
ordered. Each extract has a 256-token attribution-inclusive cap and 8000-character
ceiling; optional excerpts may be explicitly marked truncated. Small windows scale
the optional caps down. Required identity, active note and current input stay whole.
Under hard pressure, reduce optional overlap, non-anchor items, then anchor last.
Required overflow produces a durable started/failed pair before model HTTP.

Journal validates types, sources, watermarks and terminal boundaries; compares
both base epoch and note revision; and commits epoch plus applied/rejected decision
atomically. Proposals are replayable; conflicting reuse fails. Late proposals
preserve newer raw turns. Stale bases reject without rebasing. Switching does not
change note revision or Deep acknowledgement. Original journal evidence is retained.
Diagnostics report source omissions without exposing excerpt text.

The asynchronous `CompactionProposal`/`ContextPolicy` boundary accepts future Luna
summaries as quoted data. Source IDs establish provenance, not semantic truth.
M1.5 fallback is extractive and does **not** preserve every important fact.

## Local tokens and template compatibility

One optional direct dependency: `tokenizers==0.22.2`; HTTPX remains the only core
runtime dependency. Its declared transitive dependencies include huggingface-hub;
no Transformers, Torch or second service was installed. Fake startup never imports
the tokenizer. The 32,169,626-byte asset stays ignored under `.data/tokenizers/`.

NVIDIA revision `49843eed8db1f1c616c47af75cfd36e07aec0667`, SHA-256
`cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f`.
The loader checks hash and BOS/EOS/turn IDs, disables padding/truncation and loads
once. Count the complete shared renderer with `add_special_tokens=False`, plus
one BOS supplied by the verified GGUF. The wire renderer omits its old literal BOS;
corrected live calls have no duplicate-BOS warning. Controls stay escaped; thinking
is off, conversational mode on. No per-turn tokenization network request occurs.

The local count exactly matched provider `usage.prompt_tokens` for **16/16**
calibration prompts, covering Ukrainian, English, emoji/ZWJ, combining marks,
whitespace, code, literal controls, Chinese/Japanese/Arabic and long input. Count
range **47–15647** after the whitespace-preservation fix. Local load took **759 ms**;
near-limit counting about **26 ms** in that probe. All 90 final production
generations also matched provider usage.
Startup independently makes one short nonstreaming compatibility generation;
absent/mismatching usage refuses input. A later mismatch fails the turn and latches
generation off pending restart/revalidation. Visible partial output cannot be
retracted, but a failed stream never becomes committed completed speech.

Default budget: **16384 − 512 output − 32 margin = 15840 input**. Required blocks,
wrappers, spoken instruction, escaping and generation framing are included in
the count. Section diagnostics are incremental full-prompt differences, not a
sum of separately tokenized messages. Fake counts remain labelled conservative.

## Live environment and procedure

Same M1 machine/settings: Windows, Python 3.14.7, RTX 5070 Ti 16 GB, LM Studio
0.4.28.0 at `http://127.0.0.1:1230`, CUDA12 llama.cpp **2.73.0**, loaded
`liac-nemotron` Nemotron 3.5 Bolt E4B Q4_K_M (6,180,446,208 bytes). Context 16384,
parallel 4, context checkpoints 32, eval batch 2048/physical 512, flash attention
and GPU KV as previously configured. No model reload or global settings change.
GGUF metadata confirms BOS=2, EOS=1, `add_bos_token=true`.

Reproduce from the root after README setup:

```powershell
python scripts/verify_m1_5_context.py --endpoint http://127.0.0.1:1230 --model liac-nemotron --tokenizer .data/tokenizers/nemotron.json --output .data/m1-5-results.jsonl
```

`--phase controls|runtime|cli` allows separate serial runs; defaults are all phases
and three trials. The script validates its log-attribution parser, uses existing
HTTP/SSE/control helpers and actual Runtime/composition, and always terminates its
hidden owned log subscriber. Private raw logs/databases stay in ignored `.data/`;
JSONL exposes counts, hashes, IDs, timing and recall outcomes, not prompt text.
It never kills LM Studio. Calibration is excluded from timing summaries.

Evidence runs: controls `0bb8669cbd7c` in `.data/m1-5-results.jsonl`, final
production/asynchronous `974671870ce4` and CLI `b90686419ee0` in
`.data/m1-5-final-results.jsonl`; local tokenizer corpus in
`.data/m1-5-tokenizer-parity.json`. Earlier production/CLI runs were repeated after
review fixed inherited whitespace trimming; the transport garden fixtures have
no boundary whitespace and their serialized prompts are unchanged.
Runtime log windows yielded exactly one distinct evaluation task for every
control/production timing request. **Explicit cached-token counts are unavailable**
and remain null; evaluated tokens are a separate measured counter. No cold-cache
reset was performed; unrelated parallel workloads were not controlled.

## Matched transport controls and M1 comparison

Reused M1's 18-message garden recipe and 1603/7747/15005-word sizes, followed
by prime/repeat/append/note update/rolling shift. Three trials, two variants,
**90 calls**. Reference combines old note-before-history order with literal BOS;
corrected variant uses current history-before-note order and single backend BOS.
These measure both template/order differences, not an isolated BOS speed effect.
Actual counts differ slightly because of trial markers and BOS; report exact work.

| Band | Reference input prime/append | Corrected input prime/append |
|---|---:|---:|
| ~2K | 2074 / 2094 | 2068 / 2088 |
| ~8K | 8218 / 8238 | 8212 / 8232 |
| ~15.5K | 15477 / 15497 | 15471 / 15491 |

Median **TTFT ms / evaluated tokens**, three samples per cell:

| Band | Case | Reference | Corrected |
|---|---|---:|---:|
| ~2K | Prime | 296.77 / 2074 | 289.42 / 2068 |
| ~2K | Repeat | 24.87 / 1 | 27.68 / 1 |
| ~2K | Append | 57.03 / 29 | 61.68 / 84 |
| ~2K | Note | 296.55 / 2094 | 60.07 / 22 |
| ~2K | Shift | 289.58 / 2094 | 298.58 / 2088 |
| ~8K | Prime | 996.67 / 8218 | 999.63 / 8212 |
| ~8K | Repeat | 37.24 / 1 | 34.77 / 1 |
| ~8K | Append | 66.79 / 29 | 69.81 / 84 |
| ~8K | Note | 990.91 / 8238 | 66.88 / 22 |
| ~8K | Shift | 1007.48 / 8238 | 1013.02 / 8232 |
| ~15.5K | Prime | 1932.26 / 15477 | 1946.24 / 15471 |
| ~15.5K | Repeat | 44.50 / 1 | 43.70 / 1 |
| ~15.5K | Append | 78.72 / 29 | 78.12 / 84 |
| ~15.5K | Note | 1942.95 / 15497 | 73.05 / 22 |
| ~15.5K | Shift | 1974.24 / 15497 | 1973.21 / 15491 |

Historical M1 current-order ~15.5K medians: append **82.11/84**, note **73.11/22**,
shift **2003.79/15483**. New controls show comparable behavior with slightly
different input counts; they do not prove a general speedup. Large note updates
reuse the history prefix; rolling shifts still evaluate the entire input.

## Production utilization, epochs and latency

**Three serial trials × 30 actual Runtime turns = 90 turns**, real 16384/512
compiler/adapter guards. Each turn appends ~1020 words of garden filler, short
speech plus fictional facts; FakeDeep updates notes independently. All generations
completed with matching local/provider counts, zero double-BOS warnings and
append-only exact IDs within each epoch. Peak input **13952**, **88.1%** of 15840;
M1's production sample had only 2153 actual tokens despite estimating 11821.
The previous production underfill is removed for this workload.

All trials switched at zero-based turns **13 and 23**. Each new epoch first
prompt was **4452–4464** and **4424–4428** tokens respectively, fully evaluated
once. Subsequent turns resumed suffix reuse. Large new user inputs plus moving
the previous turn ahead of the mutable note tail still require ~2185 evaluated
tokens per ordinary turn; this is bounded suffix work, not a fully cached prompt.
For warmed non-transition prompts above 8K, **36/45 (80%)** evaluated under 25%
of input. The nine misses were near the lower 8K boundary; no cache guarantee.

| Production group | Samples | TTFT p50 / p95 ms | Local preparation p50 / p95 ms | Submit-to-finish p50 / p95 ms |
|---|---:|---:|---:|---:|
| All | 90 | 338.73 / 551.08 | 12.13 / 466.13 | 380.24 / 1067.18 |
| Ordinary, after first turn | 81 | 337.71 / 404.91 | 11.97 / 20.28 | 378.90 / 478.90 |
| Epoch transitions | 6 | 581.89 / 588.48 | 479.30 / 492.22 | 1071.52 / 1102.21 |

Adapter TTFT starts after Runtime preparation, includes compilation/model guard,
and ends at first safe speech. Submit-to-finish includes local preparation plus
all output. Quantiles use median and nearest-rank p95; transition cost is reported
separately. Production compilation p50/p95 was **12.88/21.57 ms**. Uncached standalone
2K/8K/15.3K compilation p50 was **2.48/12.30/25.73 ms**, p95
**3.47/13.31/28.57 ms**. Near-limit compilation exceeds the blueprint's aspirational
20 ms; transitions synchronously block the event loop for about half a second.
Future asynchronous Luna can avoid fallback extraction on Fast's critical path.

## Retention, real CLI, Deep and cancellation

At the near-limit turn (13940–13952 tokens), all three trials correctly recalled the
blue hat, amethyst stone, Hazel bridge and Saffron boat. After two transitions
and reopening the database, all three retained the fictional Мандарин anchor
and answered the newer **green** hat correction. Stone/bridge/boat were absent
from the retained projection and **none was recalled** after restart. This is an
observed loss of old secondary facts, not evidence of broad memory quality.
The correction was introduced as the current input at the second transition,
then retained as exact new-epoch history; it was not semantically summarized.

The actual `python -m vtuber` CLI ran 30 sequential live turns through two epochs,
exited and reopened the same DB in a new process. A Ukrainian question recalled
the green hat; epoch version remained **2**, unfinished replies **0**.

During another real streamed story, delayed FakeDeep committed a note without
waiting for Fast. An older-range compaction then committed in **2.40 ms** while
Fast retained epoch/revision **0/0** and identical frozen context diagnostics.
Supersession closed that stream in **2.34 ms**, left **zero stale deltas** and
one cancellation terminal. Next Fast used epoch/revision **1/1**; unfinished
replies **0**. No reasoning/control markers reached speech in these checks.

## Verification and M2 readiness

Critical stdlib unittest suite: **37 tests** passed on Python **3.14.7 and 3.12.14**
with `-X dev`; fake CLI startup, whitespace and asset exclusion checks passed.
Checks cover v1 migration/integrity, atomic rollback/restart, replay/conflicts,
invalid sources/ranges/unfinished cutoffs, frozen snapshots, >20-event history,
required-input overflow, exact budget boundary, tokenizer verification/latching,
stream faults and cancellation/closure. Live evidence is separate from mocks.

One fresh GPT-6.1 Terra review found an inherited `.strip()` in the renderer that
altered whitespace-sensitive input. Wire and CLI regressions failed first, then
passed with message whitespace preserved (identity normalization stays separate).
Tokenizer parity and all production/CLI measurements were repeated afterward.
No Critical findings, deferred Minor findings or declined review areas remained.

Execution decisions: added a defaulted immutable `terminal_turns` tuple because
dialogue alone cannot locate cancelled/failed boundaries (extra snapshot metadata);
reviewed the staged patch instead of an empty commit range (reviewer must include
new files); retained one final commit as requested (intermediate changes were
uncommitted); preserved message whitespace instead of the inherited template trim
(whitespace-sensitive prompts intentionally differ from M1). These decisions and
their costs preserve the approved behavior without extra services or abstractions.

Ready for M2's **integration boundary**: durable proposals, provenance/CAS/replay,
immutable snapshots and nonblocking application are in place. M2 still needs
actual Luna/OMP transport/authentication, structured output validation, semantic
retention/evaluation and scheduling. Luna/OMP, retrieval, semantic memory, voice,
beats and external interfaces were neither implemented nor tested here.

Limits: one Runtime owner per DB; v2 databases require v2 code; growing epochs
remain bounded by prompt budget rather than a fixed event count; fallback extract
selection is synchronous and lossy. Prefix/cache behavior depends on the exact
loaded engine. Summary truth, broad persona/long-context quality and physical
cache cold-start behavior remain unverified. No push, PR or merge was requested.
