# Desktop runtime inspector

## Intent and scope

The contributor needs one PySide6 desktop window to converse with the character
and inspect every Fast turn and Luna batch, including context and decisions.
User chose desktop over a local web interface and explicitly skipped mockups and
further design questions. Implement Native in the existing isolated worktree.
Application UI and code comments must use English only.

## Approaches

- Local web UI: convenient text inspection, but user declined the browser as UI.
- PySide6 Widgets: selected by user; use standard splitters, lists, text views,
  forms and tabs. No QML, embedded browser, qasync or web server.

## Behavior

- One window owns one Runtime. Start/stop, connection and file settings, chat
  streaming, cancel current Fast, and retry Deep are available together.
- Settings cover fake/real backends, LM Studio origin/model, tokenizer, OMP
  executable/model and database. Existing CLI behavior remains unchanged.
- A combined chronological request list distinguishes Fast turns, Luna attempts
  and Runtime decisions. IDs connect a Luna batch to its observed dialogue.
- Selecting a request shows input, output, context, metrics, and raw structured
  data. Search/filter and copy are available. Partial/cancelled/failed output is
  explicitly labelled, never represented as a completed utterance.
- Fast capture contains exact compiled messages and rendered prompt at the
  adapter boundary, plus budget, hashes, configuration and measured usage.
- Luna capture contains configured role/identity, canonical request, OMP session
  ID, available session messages, raw response, parsed proposal and Runtime
  acceptance/rejection. OMP session history is labelled as session history, not
  the exact provider HTTP body. Hidden reasoning and unavailable wire data are
  not reconstructed. Trace failures do not invalidate successful model work.
- State view includes note, epoch/items, consumer lag, lifecycle and errors.
  Before/after values accompany Deep decisions and local fallback switches.
- Historical traces can be opened without starting models. Old Journal events
  remain inspectable, but missing historical prompts are labelled unavailable.

## Ownership and concurrency

Qt GUI runs on the main thread. A worker thread runs one asyncio event loop,
creates and closes the Runtime/Journal on that thread, and relays immutable
notifications through queued Qt signals. GUI never touches a live SQLite handle.
Submission/cancel/retry/stop are marshalled to that loop; shutdown awaits Fast,
Deep and OMP cleanup without blocking the GUI or using QThread.terminate.
The desktop adapter depends on the composition root; core modules never import
Qt. Optional desktop dependency must not affect headless CLI use.

## Trace boundary and privacy

Use a small stdlib trace sink injected by the composition root. Capture request
boundaries and terminal records rather than persisting every token as a domain
event. Private snapshots live in ignored `.data/traces/`, separate from Journal.
Each run has a unique directory. No credentials, environment dumps or headers.
Local developer UI explicitly states that full contexts are being recorded.
Bound trace storage per run (default 128 MiB); reaching the limit or I/O failure
stops recording with a visible error, leaves chat running and deletes nothing.
Load selected payloads on demand; avoid retaining every full prompt in GUI RAM.
On reopened traces mark unfinished requests as interrupted rather than complete.

## Verification and limits

Pin focused tests for trace immutability/correlation, failure isolation/storage
limit, cancellation, Deep rejection, worker lifecycle, restart/history and GUI
streaming. Run existing unittest suite. Verify the real desktop window, then
real Nemotron/Luna when locally available; distinguish offline tests from live
provider results. No changes to model policy, compaction or domain schema.

## Builder decisions

Use optional `desktop` extra, `python -m vtuber.desktop`, a plain Qt Widgets
layout and a repository-relative launcher. Exact colors and widget arrangement
are implementation choices. Use installed provider credentials; authentication
management, charts, remote access, automatic deletion and replay inference are
outside this task.

Qt threading follows [QThread documentation](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html)
and [signals/slots](https://doc.qt.io/qtforpython-6/tutorials/basictutorial/signals_and_slots.html).
