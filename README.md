# liac-ai

An autonomous AI VTuber backend. M4.2 lets optional GPT-6 Luna manage a Markdown
working context through the asynchronous M2 pipeline. M2 connects Luna through OMP as
an asynchronous Deep Mind alongside local Nemotron. Durable context epochs,
exact local token budgeting and deterministic offline fallback remain from M1.5.

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
extracts → growing exact history → Luna Markdown working context → current input. The full
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
with cancellation. Optional GPT-6 Luna/OMP is available in M2 below.

## Luna-managed Markdown context (M4.2)

Luna replaces one free-form Markdown document asynchronously. Suggested Threads
and almost-ready lines are optional; Fast chooses how to use them. Current user
corrections take precedence over older ideas, including delayed updates. Revision
and epoch conflicts still reject; an ordinary newer input alone does not.

`--working-context-tokens 2048` is the initial configurable cap; use `1024` for a
smaller working perspective. Only the document's actual rendered cost consumes
Fast's allowance, with no preallocated reserve. New proposals are locally counted
before the atomic SQLite batch commits. A separate 32768-byte UTF-8 ceiling bounds
transport/storage. Lowering the cap preserves existing stored content; required
full-prompt overflow still fails instead of silently discarding history.

SQLite is authoritative. The readable projection is
`<db filename>.contexts/<SHA-256 of character ID>/context.md` beside the DB.
It contains only Markdown, written via atomic replacement after a changed commit
and rebuilt on startup. Manual edits are never imported. A file error leaves the
DB and Deep cursor committed; `/status` reports `context_export_error`. Retry is
on the next changed document or restart. Keep the DB, projection and traces private.
The existing `context_note`/`note` field names and schema v2 remain compatible.
`note:null` preserves the document, `text:""` clears it, and identical text is an
accepted no-op without a revision bump.

See [M4.2 implementation and actual evidence](docs/M4_2_IMPLEMENTATION.md).

## Luna Deep Mind (M2)

Install the optional pinned official Python SDK with `python -m pip install -r requirements-luna.txt`. Use an independently installed OMP 18.12.6 and existing authenticated `openai-codex` provider. No credentials are copied by this repository.

```powershell
python -m vtuber --fast-backend lmstudio --endpoint http://127.0.0.1:1230 --model liac-nemotron --deep-backend luna --luna-model openai-codex/gpt-6-luna --deep-timeout 60
```

`--omp-executable PATH` selects OMP; `--luna-data PATH` owns its workspace/session files (default `.data/luna`). The default Deep backend remains fake. `/status` and `/metrics` show bounded Deep lifecycle/usage/decision diagnostics; `/retry` starts a new retry cycle. Tools, extensions, skills, rules, LSP and project MCP discovery are disabled. This is application confinement, not an OS sandbox. Keep private runtime/session data out of Git and use one Runtime owner per database.

Deep observes whole completed turns and proposes one working note plus optional semantic epoch. Preparation starts at 75% of the input budget; the 90% deterministic fallback continues when Luna is late/offline. Current Fast streams keep their frozen snapshot. Failed/stale batches retain the durable cursor and retry at 1/2/4/8/16 seconds, then remain degraded until new input or `/retry`. New processes rebuild Luna's disposable context from canonical evidence; the Journal remains authoritative. Summary sources prove provenance, not correctness. Notes can suggest a performance idea; a beat scheduler and permanent Memory Store remain future work.

Provider `usage_limit_reached` latches Deep without repeated child launches; restart Runtime after provider availability returns. See [M2 results and limits](docs/M2_IMPLEMENTATION.md), including the interrupted quota sample and a failed short CLI recall.

## Desktop chat and inspector

Install the optional Widgets dependency in your virtual environment:

```powershell
python -m pip install -e '.[desktop,nemotron]'
python -m pip install -r requirements-luna.txt
python -m vtuber.desktop --root .
```

On Windows, double-click **`Start-Inspector.cmd` in this worktree**. It resolves
the project directory and uses this checkout's `.venv`, or the main checkout's
`.venv` when running inside a linked worktree. An alternate interpreter can be
selected with `./scripts/start-inspector.ps1 -Python C:/path/to/python.exe`.
Startup logs stay in `.data/desktop/`. This avoids relying on the terminal's cwd.

Alternatively, launch **`LIAC-Inspector.exe`** from the repository root when built.
It includes Python and Qt and stores `.data` beside the executable. LM Studio,
OMP and the tokenizer JSON remain external. See the
[Windows build instructions](docs/DESKTOP_INSPECTOR.md#windows-executable).

Choose backend and paths in **Settings**, then **Start**. Real mode needs
the tokenizer setup above, loaded LM Studio model and existing OMP authentication.
`fake / fake` works offline. Chat streams in the center; **Ctrl+Enter** sends,
**Cancel Fast** cancels speech, and **Retry Deep** wakes the observer.
Stop Runtime before opening another trace or changing connection settings.
Do not run another CLI/desktop owner against the same SQLite database.

The left timeline records Fast turns and Luna attempts with their IDs and phases.
Select any phase to inspect that request's input, output, context, metrics and
before/after note/epoch changes. Search matches IDs or event kinds; process filter
selects Fast, Luna or Runtime. **JSON** shows the original selected record;
**Open JSON** opens its complete local file. Text previews are capped at
200,000 characters. Chat displays the latest 5,000 blocks; startup restores up to
1,000 canonical dialogue messages; Journal tab shows the latest 500 events. Full
canonical history remains in SQLite, and request traces remain on disk.

**Context** distinguishes the exact rendered Fast prompt from Luna's configured
system prompt, submitted JSON and text-visible OMP session history. OMP's internal
provider HTTP body is unavailable and is not reconstructed. Reasoning blocks,
opaque signatures and provider payloads are omitted. Raw model JSON, validation
errors and rejected Runtime decisions remain inspectable.

Developer mode records private full contexts under ignored `.data/traces/run-*`.
**Open trace…** opens a saved run without launching models; old Journal data
does not magically recover missing prompts. Capture is bounded to 128 MiB per run;
disk failure/limit stops capture visibly without deleting data or stopping chat.
Trace persistence happens at request boundaries, not on every token. See
[desktop implementation and verification](docs/DESKTOP_INSPECTOR.md).

## Optional character initiative (M4.3)

Autonomous speech is off by default. To let Luna occasionally propose a relevant
line which Nemotron delivers through the ordinary Fast stream:

```powershell
python -m vtuber --fast-backend lmstudio --endpoint http://127.0.0.1:1230 --model liac-nemotron --deep-backend luna --enable-initiative
```

`--initiative-delay-seconds 5`, `--initiative-ttl-seconds 120` and
`--initiative-cooldown-seconds 60` are configurable experimental defaults.
Delay/TTL run from Luna request capture, so inference time counts toward both.
Luna may provide proposal-specific delay/TTL. Require finite `0 <= delay < TTL`
and nonnegative cooldown. Tune conversational rhythm from actual dialogue.

Markdown remains the sole free-form working perspective. A separate bounded
`speak` proposal carries intent, reason and canonical evidence. `none` preserves
a pending intent; explicit `cancel` withdraws it. Runtime never interrupts Fast,
gives new user input priority, and permits one attempt per real user anchor.
An attempt is consumed even when its stream fails or is cancelled. Timers check
existing opportunities and never call Luna. Restart cancels pending work instead
of resuming speech. Completed autonomous speech is real assistant history; its
input is `character.initiative.started`, never a fabricated user message.

The desktop keeps initiative off; existing chat history displays completed
autonomous speech as Fast. See [implementation and live evidence](docs/M4_3_IMPLEMENTATION.md).
Opt-in acceptance: `python scripts/verify_m2_luna.py --phase initiative`; controlled
cache probes: `python scripts/verify_m1_5_context.py --phase initiative-cache`.
