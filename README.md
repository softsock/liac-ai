# liac-ai

An autonomous AI VTuber backend. **M0** implements the Character Runtime with fake
Fast and Deep minds: Fast streams immediately while Deep observes durable events
in the background and proposes a context note for future turns.

## Run

Python 3.12+; no runtime dependencies. From the repository root in PowerShell:

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

Type text to start a turn. Commands: `/state`, `/events [1..100]`, `/status`,
`/retry` (wake a failed Deep consumer), `/help`, `/quit`. EOF and Ctrl+C also
close the runtime. New messages cancel the previous response.

To see independence clearly, run `python -m vtuber --deep-delay 5`. Send a message,
then another before Deep finishes. After `[deep.completed ...]`, inspect `/state`
and send a third message: its `[rN]` and `note` reflect the committed update.

`--db PATH` selects storage (default `.data/character.sqlite3`); `--character ID`
selects the character. `--fast-delay` controls chunk delay, `--deep-timeout` bounds
a Deep call. Restart with the same database to inspect persisted history/state.
The local inspector displays raw messages; keep its output and database private.

## Structure and checks

- `src/vtuber/contracts/`: frozen events, state, snapshots and model ports.
- `src/vtuber/runtime/`: SQLite Journal, reducer and Fast/Deep lifecycle.
- `src/vtuber/minds/fake.py`: deterministic cancelable fake adapters.
- `app.py`: configuration/composition; `cli.py`: engineering inspector.
- `tests/`: critical persistence/atomicity checks using stdlib `unittest`.

```powershell
python -m unittest discover -s tests -v
```

See [M0 decisions and verification](docs/M0_IMPLEMENTATION.md) for delivery
semantics and evidence; [PROJECT_BLUEPRINT](docs/PROJECT_BLUEPRINT.md) describes
the wider project. One runtime owns a database at a time. Adapters must cooperate
with cancellation. LM Studio/Nemotron and OMP are subsequent integration work.
