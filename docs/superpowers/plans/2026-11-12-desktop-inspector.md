# Desktop Inspector Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for Native execution.

**Goal:** Converse and inspect Fast/Luna requests in one PySide6 desktop window.

**Architecture:** Keep Qt outside core. Inject observational trace callbacks at
actual request/decision boundaries. One asyncio worker owns Runtime and Journal;
Qt receives signals and loads persisted trace detail on selection.

**Tech Stack:** Python 3.12+, PySide6 Widgets, stdlib asyncio/JSON/threading.

**Spec:** `docs/superpowers/specs/2026-11-12-desktop-inspector-design.md`

## Global Constraints

- Native implementation; no Astra subagents; one fresh final reviewer.
- Existing CLI, model policy and Journal schema remain compatible.
- Full contexts only in ignored local diagnostic storage; never credentials.
- No commit/push without further user authorization.
- User explicitly skipped mockups/questions; proceed without approval handoff.

## Review Focus

- Close during OMP startup/inference must release owned processes.
- A failed trace write must not fail a model turn or acknowledge a Deep batch.
- Rapid supersession must retain each request's own context and partial status.
- Large/reopened traces must remain inspectable without running models.
- Missing Qt or provider setup must fail clearly without breaking CLI.

### Task 1: Durable observational traces

**Files:** `contracts/trace.py`, `tracing.py`, `app.py`, `minds/lmstudio.py`,
`minds/luna.py`, `minds/omp.py`, `runtime/deep.py`, `runtime/orchestrator.py`;
`tests/test_tracing.py`.

**Interfaces:** `TraceSink(kind: str, request_id: str, data: dict) -> None`;
`TraceRecorder(root: Path, max_bytes=134217728)` callable, indexed JSONL and
immutable per-record payloads. `read_trace(path: Path)` for history.

- [x] Add failing tests: exact Fast payload correlated by turn, Luna raw/parsed
  payload and decision, immutable saved data, failed sink isolation, size cap,
  unfinished history and cancellation. Run focused unittest; observe RED.
- [x] Implement optional trace injection with safe emission. Capture existing
  actual prompt/results, never recompile a live Fast snapshot for display.
- [x] Run focused and full unittest suite; compare recorded hashes to prompt.

### Task 2: Threaded desktop controller

**Files:** `desktop/bridge.py`, `desktop/__init__.py`, optional dependency;
`tests/test_desktop.py`.

**Interfaces:** worker owns loop, Runtime and trace run; Qt signals send only
copies/IDs. Commands start, submit, cancel, retry and stop marshal into loop.
`Runtime.cancel_fast()` is a public lifecycle-safe command.

- [x] Test fake-backed start, streaming, supersession, stop during active Fast,
  error and restart; observe RED before implementation.
- [x] Install optional PySide6 and implement worker/controller with graceful
  asynchronous stop and no Qt imports in core. Reuse Config/open_runtime.
- [x] Run controller tests and full suite, including no-Qt core import.

### Task 3: Desktop UI and launch

**Files:** `desktop/window.py`, `desktop/__main__.py`, launcher, GUI tests,
`README.md`, relevant `AGENTS.md`, blueprint inspector note and implementation
report.

**Interfaces:** `MainWindow` owns controller; setup form creates Config. Chat,
request list and detail tabs consume worker notifications and TraceRecorder
history. Selected context read from immutable payload files on demand.

- [x] Test UI streaming, selecting Fast/Luna context, filtering, reopening old
  traces, missing setup and responsive close; observe RED.
- [x] Implement standard widgets, bounded text display, clear status and private
  capture notice. Add simple launcher resolving repository paths.
- [x] Run full tests, launch real window, exercise actual models if available,
  inspect recorded prompts and cleanup. Document actual results and limits.
- [x] One fresh final review of all tracked/untracked changes, fix substantive
  findings with reproducing tests. Finish with work uncommitted for review.
