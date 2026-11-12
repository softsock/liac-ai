# liac-ai

An autonomous AI VTuber backend. **M1.5** adds durable context epochs and local
token budgeting for NVIDIA Nemotron through LM Studio. Deep remains a deterministic fake: it observes the
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

Install the optional tokenizer and download its pinned 32 MB data file once:

```powershell
python -m pip install -e '.[nemotron]'
New-Item -ItemType Directory -Force .data/tokenizers | Out-Null
Invoke-WebRequest 'https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-BF16/resolve/49843eed8db1f1c616c47af75cfd36e07aec0667/tokenizer.json' -OutFile .data/tokenizers/nemotron.json
Get-FileHash .data/tokenizers/nemotron.json -Algorithm SHA256
```

Expected SHA-256: `cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f`.
The loader validates it; `--tokenizer PATH` selects another local copy of that
same asset. Fake mode needs neither file nor optional dependency. No tokenizer
download or server tokenization call occurs on the turn path. Startup makes one
short compatibility generation; absent/mismatching provider usage refuses startup.

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
identity loads once at startup. Prompt order is identity → frozen quoted epoch
extracts → growing exact history → quoted state/note → current input. The full
rendered template is counted locally, including the backend's single BOS token.
Default input allowance is **15840**: 16384 context minus 512 output minus 32
margin. Identity, active note and current input stay whole; overflow fails durably.

At the next submitted turn above 90% of that allowance, Runtime prepares an atomic
SQLite epoch switch. The fallback keeps a bounded oldest-user anchor, recent
extracts and up to three recent whole turns within token caps. Raw journal data
is never deleted. Extracts can omit important facts; this is not semantic memory.
Epochs survive restart; asynchronous proposals never alter an active Fast snapshot.
Within an epoch the prefix grows instead of sliding. A switch normally needs a
new prefill. Cache reuse depends on the loaded engine, and correctness must hold
without it. See [M1.5 decisions and measurements](docs/M1_5_IMPLEMENTATION.md)
and the historical [M1 baseline](docs/M1_IMPLEMENTATION.md).

Useful settings: `--context-tokens 16384 --max-output-tokens 512 --temperature 1
--top-p 0.95 --connect-timeout 2 --read-timeout 15 --generation-timeout 45`.
Read timeout measures inactivity; generation timeout bounds the whole request.
`/context` shows the frozen epoch/cutoff, source IDs, exact history, budget,
count method/fingerprint, section deltas, compilation time and hashes; `/metrics`
shows last-turn TTFT, duration, exact backend token usage when available, throughput
and local/provider count difference, preparation and cancellation time. `/status`
adds the latest committed epoch and model/configuration details. These
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
python scripts/verify_m1_5_context.py --endpoint http://127.0.0.1:1230 --model liac-nemotron --tokenizer .data/tokenizers/nemotron.json --output .data/m1-5-results.jsonl
```

See [M0 decisions and verification](docs/M0_IMPLEMENTATION.md) for delivery
semantics and [M1 decisions and live results](docs/M1_IMPLEMENTATION.md) for
provider evidence, and [M1.5](docs/M1_5_IMPLEMENTATION.md) for epochs/cache verification.
The opt-in live script runs three serial trials, genuine CLI sessions and restart/
Deep/cancel checks; private raw logs and databases stay under ignored `.data/`.
[PROJECT_BLUEPRINT](docs/PROJECT_BLUEPRINT.md) describes
the wider project. One runtime owns a database at a time. Adapters must cooperate
with cancellation. GPT-6 Luna/OMP is M2; it is not connected in this milestone.
