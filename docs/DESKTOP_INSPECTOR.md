# Desktop runtime inspector

Implemented on `codex/desktop-inspector` from M2 `fc20df6`, 2026-11-13.

## Behavior

One PySide6 Widgets window owns chat, streaming, Fast cancellation, Deep retry,
connection settings, request timeline, context inspection and offline trace load.
Fast turns and Luna attempts retain distinct IDs and phases. Batch snapshots link
Luna evidence to dialogue turn IDs; Luna is not forced into one-to-one chat turns.

Input/output, exact Fast messages/template prompt, Luna role/request/session text,
metrics, raw JSON, canonical events and current state are inspectable. Accepted
and rejected proposals expose before/after note and epoch differences. Fake input
is labelled as a snapshot rather than pretending to have a model wire prompt.

## Boundaries and persistence

Qt runs only in `desktop/`. One worker thread creates the asyncio loop, Runtime,
Journal and adapters; widgets receive Qt signals and marshal commands into that
loop. Close/stop await Runtime/OMP cleanup without blocking the GUI. A separate
stdlib thread pool reads selected immutable trace files; stale reads are discarded.
No domain schema or model/compaction policy changes. Explicit `cancel_fast()` now
records `user_cancelled`, distinct from supersession or shutdown.

`TraceSink` is an optional observational callback. Core CLI defaults to no full
capture. Desktop saves immutable payload files plus a JSONL index in a unique
ignored `.data/traces/run-*`. No per-token domain events, credentials or headers.
OMP history retains visible text and summary messages; thinking content,
signatures and provider internals are omitted. This is not the provider HTTP body.
Local data is private, unencrypted and not intended for publication.

128 MiB capture cap per run: recording stops with a visible error, chat continues,
and nothing is deleted. Interrupted index tails are ignored; imported filenames
and resolved paths are checked. Historical requests without terminal records are
shown as unfinished/interrupted. UI previews cap at 200,000 characters, with the
full original file accessible separately. The chat/Journal views have explicit
display bounds; canonical SQLite history is retained.

## Verification

Python 3.14.7, Qt/PySide6 6.12.0 on Windows. Optional dependency uses only
`PySide6-Essentials>=6.10,<7`; headless core does not import Qt.

Focused tests cover immutable/correlated snapshots, exact Fast prompt parity,
nonfatal failed capture, storage limit, partial index, path traversal rejection,
partial cancellation, OMP view/provenance and reasoning omission. Real SQLite
plus offscreen Qt exercise worker lifecycle, stream/cancel/retry/stop/reopen,
request selection, JSON readability and offline history/filtering.

An offscreen suite initially crashed during Qt/interpreter teardown after tests
passed. Explicit QApplication test shutdown alone did not reliably fix it.
Replacing the Qt QRunnable/QThreadPool reader with a joined stdlib executor
passed three checks but was not sufficient: a later extra window reproduced the
abort. The tests were retaining closed (hidden, not destroyed) top-level windows
and popup widgets. Explicit deferred deletion before QApplication shutdown,
plus joining finished native worker threads, resolves that reproduced teardown.
Five consecutive desktop-process runs and full Python 3.12/3.14 suites exited 0.
The native entry point also deletes its window before Python finalization.

Native real-provider run `run-dded0c1fb73f4c038aa1d5ca4e5a9d6d` recorded two full
Fast/Luna cycles (18 trace boundaries). Fast acknowledged the fictional green hat,
then answered `Green.`. TTFT was 104.2 and 108.1 ms, a smoke sample rather than a
benchmark. Both real Luna decisions were `applied`; session history grew from
0 to 2 prior messages. Exact Fast prompt and Luna OMP context were viewed in the
actual window. Owned application/OMP processes exited on native close; stderr
was empty. No KV cache evaluation-token measurements were collected here.

Final English UI run `run-bc92b8e08b35462da49b9b26ccddb978` restored the earlier
conversation, completed a purple-hat correction through both real models, and
showed the accepted note difference in Changes. The bounded OMP history query
returned successfully with no history error. An older run was then opened through
the native folder picker while Runtime was stopped. The final window remains
open for the user with models stopped.

Final automated result: **83 tests pass** on Python **3.12.14 and 3.14.7**, with
process exit checked. The normal isolated wheel build contains desktop and trace
modules. A no-build-isolation attempt failed because this venv lacks setuptools;
the default pip build installs its declared build backend and succeeds. Core
imports with Qt, SDK and tokenizers explicitly unavailable also pass.

## Independent review and decisions

One fresh read-only review found two Important issues: optional paginated OMP
history retrieval could exhaust Deep's inference budget, and transient brainstorm
server state was not ignored. History now uses one pinned SDK command with a
**100 ms** response deadline, reports missing history explicitly, and is skipped
once capture stops. Slow/failing observation and disabled-capture cases were
reproduced RED then passed. `.superpowers/` is ignored; no server token/state is
part of the deliverable.

The reviewer labelled response/error precedence Minor; it was treated as Important
because an invalid Luna result must not appear successful. A reproducing test
failed before the Response tab was changed to retain both raw text and terminal
failure/decision. Full suites pass after this single review-fix pass.

Implementation calls: reuse the isolated worktree with a separate branch; follow
the user's explicit instruction to skip mockups/design handoffs; use one stdlib
reader thread; bound widget previews while retaining raw files. History uses the
pinned SDK's internal command boundary because its public paginated getter has no
per-operation timeout. If the local RPC is busy, context history may be unavailable
rather than delaying inference for the SDK's full timeout. No vendor edits.

Review exclusions were judged explicitly: model quality/policy remain unchanged;
native/provider evidence comes from the parent checks above; maximum-size trace
responsiveness was inspected and bounded but not stress-benchmarked. No deferred
Minor findings remain. Publication requires explicit user authorization.

## Limits

### Windows executable

Install build dependencies in the development environment, then run:

```powershell
python -m pip install pyinstaller '.[desktop,nemotron]' -r requirements-luna.txt
./scripts/build-inspector.ps1 -Python ./.venv/Scripts/python.exe
```

The single-file `LIAC-Inspector.exe` is written to the repository root and included
in Git at the user's request. Python, Qt, HTTPX, the local tokenizer library and the pinned OMP SDK are
included; models, tokenizer JSON, OMP executable, credentials and private data are
not. The executable defaults to `.data` beside itself, independently of the
working directory; `--root PATH` overrides this. LM Studio and authenticated OMP
must still be available externally. The executable is unsigned.

Built with PyInstaller 6.22.3 and Python 3.14.7. The build script prioritizes
Windows System32 during DLL discovery: an initial build incorrectly collected
Poppler's incompatible ICU DLL from the host PATH and failed importing QtWidgets.
The corrected build excludes that vendor ICU and opens from an unrelated working
directory with paths rooted beside the executable. No tokenizer data or private
`.data` files are bundled.

Executable smoke check (Windows, 2026-11-13): the 57,126,240-byte build opened
from the temporary directory, loaded the external tokenizer, streamed a real
Nemotron response and applied a real Luna update through bundled OMP SDK code.
Trace `run-42924bd1ca8f48078587aa4ae2647089` contains nine request boundaries;
an isolated `exe-smoke.sqlite3` kept the normal conversation untouched. Stop
finished and the owned OMP process exited; stderr was empty. All 83 source tests
also passed on Python 3.14.7. No clean-machine or other-Windows-version check.

### Runtime limitations

- OMP's internal prompt transformations/provider wire body are not exposed.
- Full contexts are available only for requests recorded with developer capture.
- Inspectors show source evidence, not a guarantee of model semantic correctness.
- One Runtime owner per database; close the matching CLI before desktop use.
- Provider authentication, remote access, replay inference and memory/beat
  functionality remain outside this change.
