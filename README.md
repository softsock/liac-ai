# liac-ai

An autonomous AI VTuber backend. **M1** adds real NVIDIA Nemotron Fast streaming
through local LM Studio. Deep remains a deterministic fake: it observes the
durable journal asynchronously and proposes notes for subsequent turns.

## Run

Python 3.12+ and HTTPX. From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m vtuber
```

After installation, `python -m vtuber` or `vtuber` also works with the environment
active. On POSIX use `.venv/bin/python`. For a source-only run without installation:

```powershell
$env:PYTHONPATH = 'src'
python -m vtuber
```

The default `--fast-backend fake` works without a model server.

Type text to start a turn. Commands: `/state`, `/events [1..100]`, `/status`,
`/context`, `/metrics`, `/retry` (wake a failed Deep consumer), `/help`, `/quit`. EOF and Ctrl+C also
close the runtime. New messages cancel the previous response.

To see independence clearly, run `python -m vtuber --deep-delay 5`. Send a message,
then another before Deep finishes. After `[deep.completed ...]`, inspect `/state`
and send a third message: its `[rN]` and `note` reflect the committed update.

`--db PATH` selects storage (default `.data/character.sqlite3`); `--character ID`
selects the character. `--fast-delay` controls chunk delay, `--deep-timeout` bounds
a Deep call. Restart with the same database to inspect persisted history/state.
The local inspector displays raw messages; keep its output and database private.

## Real Nemotron through LM Studio

Install LM Studio separately and download **NVIDIA Nemotron 3.5 Bolt E4B** GGUF.
The verified local file was NVIDIA's Q4_K_M, 6.18 GB. Start the server and load
the model explicitly; this backend does not download or automatically load models:

```powershell
lms server start
lms server status
lms ls
lms load nvidia-nemotron-3.5-bolt-e4b-4gb --context-length 16384 --identifier liac-nemotron -y
.\.venv\Scripts\python -m vtuber --list-models --endpoint http://127.0.0.1:1230
.\.venv\Scripts\python -m vtuber --fast-backend lmstudio --endpoint http://127.0.0.1:1230 --model liac-nemotron
```

Use the origin printed by `lms server status`: this machine uses **1230**, while
the CLI default is **1234**. `--model` must match a `loaded_instances[].id` from
`--list-models`. The loaded context must be at least `--context-tokens`.
For an authenticated server, set `LMSTUDIO_API_TOKEN` in the environment.

Each turn uses stateless **`POST /v1/completions`**, HTTPX and SSE. The adapter
renders NVIDIA's text-only template with `enable_thinking=false` and
`conversational_mode=true`; the endpoint applies no additional template. This
avoids LM Studio silently ignoring `chat_template_kwargs`. No global model
settings need changing. Reasoning/control output causes a failed turn.

Edit [character.md](src/vtuber/minds/character.md), or pass `--identity path/to/soul.md`;
identity loads once at startup. The compiler orders identity, retained exact history,
quoted state/note, then current input. History comes from M0's bounded 20-event
dialogue window; changing a note preserves the prefix when retained history stays
unchanged. A longer note can evict history under budget pressure. It reserves
output space and rejects oversized required content instead of truncating it. Its UTF-8 byte estimate is deliberately
conservative, **not an exact tokenizer count**; it can substantially underfill 16K.

On the verified LM Studio runtime, a synthetic ~15.5K-token note update evaluated
22 input tokens with this order, versus 15483 with the previous order (median TTFT
73 versus 1997 ms). Shifting the history window still evaluated the full input.
Explicit cache counts were unavailable. Reuse depends on the loaded engine/settings; these are local
measurements, not a latency guarantee. See the [follow-up results](docs/M1_IMPLEMENTATION.md#m1-context-cache-follow-up--2026-11-12)
for exact sizes, counters, production-compiler limits and remaining acceptance gaps.

Useful settings: `--context-tokens 16384 --max-output-tokens 512 --temperature 1
--top-p 0.95 --connect-timeout 2 --read-timeout 15 --generation-timeout 45`.
Read timeout measures inactivity; generation timeout bounds the whole request.
`/context` shows included/dropped event IDs, counts, revision and hashes; `/metrics`
shows last-turn TTFT, duration, exact backend token usage when available, throughput
and last cancellation time. `/status` adds model/configuration details. These
inspectors omit prompt text and do not insert diagnostics into character speech.

## Structure and checks

- `src/vtuber/contracts/`: frozen events, state, snapshots and model ports.
- `src/vtuber/runtime/`: SQLite Journal, reducer and Fast/Deep lifecycle.
- `src/vtuber/context.py`: model-independent deterministic ContextCompiler.
- `src/vtuber/minds/`: fake adapters, Nemotron renderer/HTTP adapter and identity.
- `app.py`: configuration/composition; `cli.py`: engineering inspector.
- `tests/`: critical persistence/atomicity checks using stdlib `unittest`.

```powershell
python -m unittest discover -s tests -v
```

See [M0 decisions and verification](docs/M0_IMPLEMENTATION.md) for delivery
semantics and [M1 decisions and live results](docs/M1_IMPLEMENTATION.md) for
provider evidence; [PROJECT_BLUEPRINT](docs/PROJECT_BLUEPRINT.md) describes
the wider project. One runtime owns a database at a time. Adapters must cooperate
with cancellation. GPT-6 Luna/OMP is M2; it is not connected in this milestone.
