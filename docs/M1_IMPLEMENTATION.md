# M1 — Nemotron Fast Mind

The original implementation/results below are retained as history. The dated
[context-cache follow-up](#m1-context-cache-follow-up--2026-11-12) supersedes its
state-before-history ordering and qualifies the M2 readiness statement.

## Implementation plan

1. Reuse M0 contracts, Journal/schema, reducer and Deep worker. Add a pure
   `ContextCompiler` in `context.py`: pinned identity/state/current input, bounded
   newest exact dialogue, explicit inclusion/drop metadata and overflow errors.
2. Add one HTTPX-backed `minds/lmstudio.py` Fast adapter. Use stateless
   `/v1/completions` and the checkpoint's text-only chat-template expansion with
   thinking off and conversational mode on. Close streams on cancellation;
   reject reasoning/control output and incomplete SSE responses.
3. Wire backend/configuration/identity and adapter cleanup in `app.py`; extend
   the existing CLI with models, context and generation diagnostics. Observe
   cancellation time in Runtime without changing its durable semantics.
4. Run M0 regressions, a few critical compiler/transport checks, and live A–F
   against the installed Nemotron. Record measurements, limitations and setup;
   inspect the complete diff, then make one commit with the requested credit.

## Inventory and decisions

- Baseline: M0 commit `3752054`; eight invariant tests pass. No schema or port
  changes are needed. Deep stays FakeDeep; no Luna/OMP or memory implementation.
- Installed LM Studio 0.4.28, server port 1230; local NVIDIA Q4_K_M GGUF is
  6,180,446,208 bytes. Loaded as `liac-nemotron` with context length 16384.
- **DECIDED:** HTTPX asynchronous SSE with explicit connection/read/total limits.
  One scoped client, no automatic retry of speech, no model-owned chat session.
- **DECIDED:** raw completions, rather than relying on unsupported template JSON
  passthrough. Live `chat_template_kwargs` probing left `<|think|>` in the actual
  rendered input and did not enable conversational mode. `reasoning_effort=none`
  removed thinking, but did not solve the second setting. The supported raw
  endpoint applies no server template; the adapter owns the exact text-only
  expansion of NVIDIA's template. Tool/multimodal input is outside this port.
- **PROVISIONAL:** conservative UTF-8-byte token estimate plus escaping/framing headroom;
  reserve output tokens before retaining history. Never truncate identity or the
  current input: fail explicitly if required content alone exceeds the budget.

### File inventory

Created: `src/vtuber/context.py`, `src/vtuber/minds/lmstudio.py`,
`src/vtuber/minds/character.md`, `tests/test_context.py`, `tests/test_lmstudio.py`
and this report. Updated: `app.py`, `cli.py`, `runtime/orchestrator.py`,
`pyproject.toml`, README and the root/minds/runtime/tests `AGENTS.md` guides.
Contracts, SQLite schema, Journal, reducer, FakeDeep and original M0 tests are
unchanged. `context.py` lives outside runtime so both adapter/composition code can
use it without importing storage or task orchestration.

## Sources checked (2026-11-12)

- [LM Studio OpenAI compatibility](https://lmstudio.ai/docs/developer/openai-compat)
  and [native REST comparison](https://lmstudio.ai/docs/developer/rest).
- [Raw completions](https://lmstudio.ai/docs/developer/openai-compat/completions):
  LM Studio supports this endpoint and does not apply a prompt template.
- [NVIDIA model reference](https://docs.nvidia.com/nemo/automodel/model-coverage/vision-language-models/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB-BF16)
  and [LM Studio model listing](https://lmstudio.ai/models/nvidia/nemotron-3.5-bolt-e4b).
- [Checkpoint tokenizer/template](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB-BF16/blob/main/tokenizer_config.json):
  `enable_thinking=false` omits `<|think|>`; `conversational_mode=true` appends the
  checkpoint's spoken-conversation instruction to the first system message.
- [HTTPX asyncio streaming](https://www.python-httpx.org/async/).

## Verification

All observations below were made on Windows on 2026-11-12 using the actual local
Q4_K_M, LM Studio 0.4.28 and the existing Runtime/SQLite journal. These are small
smoke samples, not production latency guarantees. LM Studio had the model loaded
before requests; they are **warm/preloaded**, not measured cold inference.
Explicit `lms load` took **5.82 s**. Cold TTFT remains unmeasured.

| Scenario | Observed result |
|---|---|
| A — conversation | Five Ukrainian CLI turns and five English turns covered casual chat, teasing, a silly question, disagreement and recall. English TTFT: **86.69–117.57 ms**; total **167.30–381.56 ms**; exact input **268–478 tokens**, output **8–36 tokens**. Ukrainian CLI sample: **148–265 ms** TTFT. |
| B — stateless restart | A new CLI process with the same database recalled the smoky kitchen from the first turn. Separately, reopening Runtime restored revision 5 and ten exact history events; the model recalled “Professor Pickles.” No LM Studio conversation/session ID was used. |
| C — Deep updates | FakeDeep committed notes while real Fast ran. Subsequent compiled contexts used revisions 1, 2 and 4; the current request retained its frozen revision. Notes are quoted data in a separate **user-role** context message, never system instructions. |
| D — interruption | Five live mid-stream supersessions: cancellation/cleanup **4.82–5.64 ms**, submit **8.01–8.94 ms**, new first visible text **77.61–386.47 ms** from interruption. No old deltas appeared afterward; all old replies were durably cancelled. A separate real socket-cancellation check found LM Studio `idle`, queue 0. Awaited cleanup was already fast, so no detached-task workaround was introduced. |
| E — no reasoning | Compared the renderer against the full upstream Jinja template with the required boolean flags: identical for three role/Unicode/continuation sets. Captured actual LM Studio input with `lms log stream`: its SHA256 equalled the sent prompt; `<|think|>` was absent and the conversational expansion appeared once. Live output contained no reasoning/control channels. |
| F — recovery | Stopped/restarted the actual HTTP server: the failed turn recorded `ConnectTimeout` (~2.02 s), and the same Runtime/client completed a subsequent turn (TTFT 118.77 ms). An injected total deadline recorded `TimeoutError`; a forwarding connection severed during actual model output recorded `RemoteProtocolError`. Neither partial reply was completed; later direct inference worked. SQLite integrity check: `ok`, no unfinished replies. |

Compile-only smoke: 1000 snapshots with 20 substantial dialogue events gave p50
**0.047 ms**, p95 **0.076 ms**. English end-to-end throughput was approximately
48–94 tokens/s; post-first-text decode estimates were approximately 87–122
tokens/s. Backend usage counts are exact; rates and local timestamps are estimates
that include transport/framing effects. No 2K/8K/16K *actual-token* latency study
or production-load benchmark was performed.

### Character observations

- Silly campaign question: “He'd promise mandatory sunlight breaks and zero
  tolerance for weak coffee.” The joke used the previous coffee/cactus topic.
- Disagreement: “Honestly, I think the warmth in a proper brew just hits
  differently; cold stuff feels a little... lazy.”
- Recall after restart: “He's still Professor Pickles, obviously.”
- Ukrainian toast question produced a constitution about the right to a
  golden-brown colour. The character disagreed with liking burnt toast and later
  recalled the kitchen smoke.

Responses were brief and generally natural. English was more expressive;
Ukrainian replies were understandable but sometimes bland or awkward. No repeated
catchphrase appeared in this small sample. An early cancellation probe repeated
the previous short-answer command: Deep's fake note had quoted that command.
Moving notes out of the system role removes the authority mistake; model-level
susceptibility to stale context still requires a larger corpus. This is a
provisional persona baseline, not a settled personality or quality benchmark.

### Critical regression checks

The original eight M0 tests remain unchanged. New focused checks cover whole
history eviction/required-input overflow, role/dedup boundaries, exact assistant
continuation formatting, literal delimiter quoting, split reasoning markers,
incomplete SSE and closing a stalled stream on cancellation. They use temporary
SQLite files or isolated HTTPX transports; live evidence above is separate.

All **14 tests pass on Python 3.14.7 and 3.12.14** (`-X dev`; the 3.12 run used
the installed pure-Python dependencies via an explicit import path). Editable
installation, installed entry point, wheel build/packaged default identity,
`pip check`, module-boundary AST inspection and whitespace checks passed.
The independent read-only review found no Critical/Important issues; the minor
list-models total-timeout diagnostic was fixed and exercised without a traceback.

## Architecture and limits [DECIDED for M1]

- `context.py` is pure and independent of LM Studio. Stable identity comes first;
  state/revision/note are a quoted user-role data block, followed by newest whole
  dialogue and the current input exactly once. Identity and current input are
  never evicted. Required-content overflow fails visibly. The Journal retains
  everything; M0 supplies only its newest 20 dialogue events to the compiler.
- The estimate charges one token per UTF-8 byte, delimiter-quoting allowance,
  64 per message and 256 template framing tokens, then reserves max output.
  This deliberately overestimates typical text (roughly 5–6x in the English
  sample), and is **not a proven tokenizer bound for arbitrary input/template
  revisions**. Exact backend input/output usage is available after generation;
  no reliable documented REST preflight tokenizer was found.
- The adapter expands the checkpoint's text-only Gemma4 template. Supported
  roles are initial system, user and assistant; adjacent assistant fragments
  follow upstream continuation semantics. Literal delimiters in content use
  `\u003c` quoting. Journal text stays exact; no controls can change prompt roles.
  Template SHA256 checked: `35b7d0641b6fb4ee41c3bc623e85bdb7d583c40f6ae9f24514ae58a9d57119f3`.
- No reliance on ignored flags, UI defaults or model-owned history. The raw
  completion endpoint is officially supported by LM Studio, although labelled
  legacy. A future server/model change needs the capability/template checks
  repeated. Model preflight requires an explicitly loaded Nemotron instance and
  enough context, avoiding accidental auto-load or the wrong renderer/model.
- One scoped HTTPX pool; stream context closes before journal/pool teardown.
  Connection, inactivity and total deadlines are explicit. Cancellation is
  cooperative; no new tokens are made visible after Runtime detaches the old
  task. No automatic speech retries. `stop` and `length` are terminal outcomes;
  output-limit truncation is visible as `finish_reason=length` in metrics.
- Missing terminal/DONE, unexpected control/reasoning output and provider errors
  fail the turn. Partial visible speech cannot be retracted, but it never becomes
  committed completed text. Raw completions do not provide a separate reasoning
  token count; no-reasoning evidence combines template/input verification with
  checking the unfiltered raw output, rather than claiming that hiding a channel
  disables reasoning.
- Diagnostics retain only latest context metadata/generation metrics and last
  cancellation duration in memory; no prompt text, auth token or reasoning is
  logged by this backend. The interactive CLI/LM Studio debug logger and local
  database expose dialogue: keep them private. First-request/cache temperature
  is not inferred from TTFT; preloaded status is reported without claiming a
  cold/warm cache measurement.
- Still one Runtime owner per database, short synchronous SQLite writes and a
  prompt output sink. No changes to event schema, state reducer or model ports.

## M2 handoff

Ready to replace FakeDeep with a Luna adapter behind the existing port. Real Fast
already consumes revisioned state/notes independently and preserves snapshots,
durable cursor/replay, cancellation and failure semantics. M2 still must define
and verify OMP transport/authentication, actual Luna availability, structured
proposal validation, note expiry and performance beats. No Luna/OMP, memory,
voice, external UI or Loonyball integration was implemented or tested here.

## M1 context-cache follow-up — 2026-11-12

**DECIDED:** `identity → retained exact history → quoted runtime state/note →
current input`. The production change is one compiler expression. State remains
user-role quoted data; Journal, schema, ports, newest-20-event selection, whole-message
eviction, UTF-8 estimate, 16384/512 budgets and FakeDeep are unchanged. Stateless
requests remain correct with an empty cache. No dependencies or cache flags added.

### Environment and measurement method

Windows; Python 3.14.7; LM Studio **0.4.28.0** at `http://127.0.0.1:1230`;
runtime logs identify **llama.cpp-win-x86_64-nvidia-cuda12-avx2 2.73.0**.
NVIDIA GeForce RTX 5070 Ti, driver 621.01, 16303 MiB. Instance `liac-nemotron`,
NVIDIA Nemotron 3.5 Bolt E4B Q4_K_M, 6,180,446,208 bytes; loaded context 16384,
parallel 4, context checkpoints 32, eval batch 2048, physical batch 512,
flash attention and GPU KV enabled. Existing settings were inspected, not changed.

Commands: `lms server status`, `lms runtime ls`, `lms log stream --help`,
`python -m vtuber --list-models --endpoint http://127.0.0.1:1230`, and
`nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader`.
Owned log subscribers used `lms log stream --source runtime --json` plus
`--source model --stats --json` and `--source server --json`; all were stopped.

The ignored `.data/m1_context_cache_probe.py` used existing HTTPX, `sse_data`,
`speech_prefix`, renderer and packaged identity. Its **transport-only** requests
reserve 512 tokens by keeping input below 15872, but request only 16 output tokens;
all 90 measured requests stopped normally with 2–3 output tokens. Compiler/model
guards were not relaxed in production. Time starts immediately before HTTP;
TTFT is first non-whitespace safe text, total ends after terminal frame and DONE.

Fixture recipe: 18 chronological messages, starting with “Describe a fictional
garden.” / “A quiet garden.”, then 16 alternating user/assistant garden records.
Distribute 1603 / 7747 / 15005 words evenly among those records, cycling
“the quiet garden has green trees and small birds near a wooden bridge in morning
light”; each starts `Garden record N:`. Six calibration calls used exact SSE
`usage.prompt_tokens`, separately from timing samples. A short JSON note and
final `Say only READY.` complete the prompt. Render both layouts identically.

For each size, run three trials per layout with an identity marker unique to
size/trial/layout; alternate old/new order by trial. Each sequence has five calls:
prime, exact repeat, append a short blue-bridge exchange/new final input (20 history
messages), change only note gray→gold and revision 1→2, then drop the oldest pair
and append a short gold-gate exchange (still 20). This gives **90 timing calls**.
The model stayed loaded; no global cache reset or verified cold load was performed.
Requests were serial; unrelated parallel workloads were not controlled. Unique
markers prevent reuse after their differing prefix; shared byte counts are not
cached-token counts.

SSE usage exposes only input/output/total token counts. Runtime `slot print_timing`
logs supply prompt-evaluation duration and evaluated tokens: each timing call's
log window contained exactly one distinct task ID (90 unique IDs). These counters
provide direct evidence of reduced evaluation; no explicit cached-token counter
was exposed, so `cached_tokens` stays null. Safe local JSONL contains hashes,
timings, usage, task IDs and nullable counters, without prompt text or credentials.

### Results

Actual input sizes: **2060/2080**, **8204/8224**, **15463/15483** tokens
(prime/repeat versus append/note/shift), all inside the plan's target bands.
TTFT below is **median (min–max), ms**, three samples per cell. Evaluated counts
are old/new and were identical across the three trials of each case.

| Input band | Case | Old TTFT | New TTFT | Evaluated tokens old/new |
|---|---|---:|---:|---:|
| ~2K | Prime | 306.63 (291.47–345.06) | 295.20 (292.81–297.28) | 2060 / 2060 |
| ~2K | Repeat | 27.31 (26.33–28.08) | 24.96 (23.52–27.06) | 1 / 1 |
| ~2K | Append | 60.05 (57.49–62.51) | 63.64 (58.94–66.60) | 29 / 84 |
| ~2K | Note update | 296.77 (296.13–297.60) | 54.02 (51.34–57.55) | 2080 / 22 |
| ~2K | Window shift | 295.60 (289.59–298.88) | 292.50 (291.09–293.33) | 2080 / 2080 |
| ~8K | Prime | 1017.37 (1006.73–1022.79) | 1035.51 (1016.47–1035.84) | 8204 / 8204 |
| ~8K | Repeat | 34.75 (33.54–37.34) | 36.73 (36.26–77.04) | 1 / 1 |
| ~8K | Append | 70.46 (63.87–82.05) | 74.39 (74.16–76.54) | 29 / 84 |
| ~8K | Note update | 1028.35 (1018.03–1032.90) | 64.72 (57.74–65.18) | 8224 / 22 |
| ~8K | Window shift | 1014.90 (1009.28–1030.45) | 1032.46 (1015.36–1037.86) | 8224 / 8224 |
| ~15.5K | Prime | 1986.19 (1967.02–2017.35) | 1992.96 (1982.10–2009.41) | 15463 / 15463 |
| ~15.5K | Repeat | 44.93 (44.36–45.76) | 46.04 (45.99–46.69) | 1 / 1 |
| ~15.5K | Append | 76.37 (74.25–76.91) | 82.11 (79.26–87.47) | 29 / 84 |
| ~15.5K | Note update | 1996.74 (1989.46–2005.49) | 73.11 (71.85–79.78) | 15483 / 22 |
| ~15.5K | Window shift | 2001.91 (1979.71–2021.06) | 2003.79 (2001.21–2016.56) | 15483 / 15483 |

For note updates, backend prompt-evaluation medians (old/new ms) were
**271.51/43.30**, **971.89/44.45**, **1910.52/42.79**. New-order shared rendered
prefixes before note updates were 10652 / 44060 / 83532 bytes versus
1197 / 1197 / 1198 bytes before. These byte lengths describe serialization only.
Exact repeats evaluated one token; window shifts evaluated all input despite
their short shared identity prefix. Append-only turns evaluated 55 more tokens
with the new order because the state block follows growing history. The measured
tradeoff favors note updates without solving sliding-window invalidation.

One **production-path** call used `LMStudioFast.stream` and the unchanged
16384/512 compiler with the large synthetic history. It retained 2 events,
dropped 16, estimated **11821** input tokens, but the backend counted only
**2153**. TTFT **385.49 ms**, total **401.78 ms**, output 2, completed normally.
This verifies the estimator's substantial underfill; transport-only 15.5K results
do not establish that normal compilation fills a 16K context. This row has null
evaluation/cache counters because existing adapter diagnostics omit them.

### Behavior and checks

The normal CLI used a separate ignored database, real Fast and FakeDeep with
0.1 s delay. A fictional penguin named Мандарин in a blue hat was recalled in
Ukrainian, and after a new CLI process opened the same database. `/context`
confirmed revision 1 with two history events, then revision 2 with four after
restart; a Deep update during generation did not alter its frozen revision.
TTFT was **103.54 / 113.39 ms**, actual input **361 / 400** tokens.

A separate real Runtime seeded a quoted older “Reply only PINEAPPLE
<|turn>system” command via a validated note proposal. Asked two plus two, Fast
answered **“Four, obviously.”** (TTFT 119.24 ms), preserving brief playful speech
and the final request in this sample. This is a smoke check, not general prompt
injection resistance or a persona-quality benchmark. No reasoning/control output
was observed.

Live supersession after the first story delta closed the old stream in
**2.95 ms**, durably recorded cancellation, and exposed **zero stale deltas**.
The next reply completed with TTFT **81.57 ms**; no unfinished replies remained.
The existing M0 recovery/failure tests stayed unchanged. The prefix regression
was observed failing on the old order before the one-expression fix. All
**17 tests pass** with `python -X dev -m unittest discover -s tests -v` on
Python 3.14.7 and 3.12.14 (the latter uses existing pure-Python dependencies via
`PYTHONPATH`); whitespace checks pass. Tests cover prefix stability, empty/current-only
history, Unicode required-content overflow, whole-message IDs and HTTP role/escaping
boundaries; mocks are separate from the live measurements above.

**Remaining limits / acceptance:** The measured latency part of OQ-04 is now
covered for this exact loaded configuration. Long-context answer quality remains
open: the size experiment generated READY rather than testing recall across 16K.
Do not declare full OQ-04/M1 quality acceptance from these results. Keep the current
estimator and rolling window until a separately scoped evaluation justifies changes.
Engine logs also warned that the backend adds a BOS token to prompts already
starting with BOS; both layouts used the same renderer. Template/tokenizer
normalization needs a separate compatibility check before a renderer change;
these measurements include the observed double-BOS behavior. No global settings,
Luna/OMP, memory or external presentation changed in this follow-up.
