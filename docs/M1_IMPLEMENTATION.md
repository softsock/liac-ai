# M1 — Nemotron Fast Mind

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
