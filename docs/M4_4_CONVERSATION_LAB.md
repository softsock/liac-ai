# M4.4 — Conversation Lab

Implemented from local M4.3 `8f42dfa` on `codex/m4-4-conversation-lab`.
[Plan](superpowers/plans/2026-11-13-m4-4-conversation-lab.md) and
[requirements](superpowers/specs/2026-11-13-m4-4-conversation-lab-requirements.md).
No push/PR. Full long-running provider acceptance was deferred by the user
during implementation. The observations below are partial evidence.

## Architecture and ownership

```text
PySide6 widgets <--- copied signals ---> RuntimeWorker / asyncio owner
                                           |
Headless CLI -------------------------- LabHost
                                           |-- real Runtime / canonical SQLite
                                           |-- public output -> human simulator
                                           |-- bounded trace queue -> writer thread
                                           `-- immutable run archive -> offline reader
```

The existing RuntimeWorker, detail reader and Widgets layout are retained.
LabHost shares composition across desktop/headless clients. Manual chat keeps
its configured database; every simulation allocates a fresh `runtime.sqlite3`
under `.data/lab/run-*`. Liac still has one canonical Journal and context.
Archived Journal envelopes are observations, never another write path.

The simulator owns separate OMP workspace/session/history and role instructions.
Only visible user/character messages enter its controller; cancelled fragments
are marked interrupted. It receives its own life scenario, not Liac's Markdown,
Deep proposals, diagnostics or hidden state. Scenario evaluation criteria are
excluded from its role. Session changes recreate the simulator session while
preserving visible dialogue. Tools/discovery remain disabled through the existing
OMP isolation. No character or Luna instruction changes were made for evaluation.

## Using the source Lab

Install the existing optional desktop/Nemotron dependencies and pinned OMP SDK
as described in README. Use `Start-Inspector.cmd` or:

```powershell
python -m vtuber.desktop --root .
```

The committed `LIAC-Inspector.exe` has not been rebuilt for M4.4.

- Conversation rows distinguish Real user, Simulated user, Liac reply and Liac
  initiative; stream text is updated by turn ID. Cancelled output remains visibly
  partial. Session boundaries are separate rows in replay.
- The process list filters Fast, Luna, Runtime, Context, Initiative and Simulator.
  Live phases/progress arrive before model completion. Clicking speech selects
  its process; archive lookup can also expose associated Deep evidence.
- Input/Prompt, Output/Proposals, Context/Diff, Metrics, Journal and Raw JSON
  retain exact captured data. Context Timeline selects historical Markdown and
  epoch; it does not recompile an old turn with today's state.
- `Enable initiative` is off by default and applies when Runtime starts.
  Existing timing parameters and M4.3 guards are unchanged.
- Simulation controls select a scenario, turn/duration budget and independent
  simulator model. Manual input pauses the simulator before submission; Resume
  generates from the new dialogue. Stop simulation stops the test client;
  top-level Stop closes Runtime and owned providers.
- Reported provider cost is shown separately for Luna and Simulator and is an
  estimate, not billing confirmation. Missing counters are unavailable.

Conversation uses a Qt list model, with a maximum 1000 visible live rows. Timeline
retains its existing list widget with the same bound. Archived pages are 200 rows;
Earlier/Later navigate saved rows. Refresh archive after Stop loads full history.
Details load on the existing joined reader executor; stale generation results
cannot overwrite the current selection. Preview text remains capped at 200,000
characters. Inference/SQLite access never runs on the GUI thread.

## Headless simulation and replay

```powershell
python -m vtuber.lab --turns 12 --enable-initiative --omp-executable "$env:LOCALAPPDATA/omp/omp.exe"
python -m vtuber.lab --turns 120 --enable-initiative --omp-executable "$env:LOCALAPPDATA/omp/omp.exe"
python -m vtuber.lab --resume .data/lab/run-EXAMPLE
python -m vtuber.desktop --root . --replay .data/lab/run-EXAMPLE
python -m vtuber.lab report .data/lab/run-EXAMPLE
```

The initial scenario covers introduction, Skin Creator, return, corrections and
ordinary conversation. It supplies private facts and possible events, not fixed
messages. Turns count simulated user submissions; autonomous speech is counted
separately. Duration is real monotonic elapsed time, including pauses. The first
reached budget stops the run; the simulated human can finish early.

Default waits are real; the simulator may choose silence or a session break.
`--pause-scale` scales only those waits. A scale of 0.1 is accelerated scheduling,
not several hours of real execution; Journal timestamps are never forged. Seed
only controls local fallback pause choices, not deterministic remote responses.
Visible transcript supplied to the simulator is bounded to a recent 96 KiB window
with an explicit older-message omission count. No alternate Liac summary is added.

Explicit continuation restores recorded configuration and completed visible
history, uses a new immutable capture segment and permits only one owner via an
OS file lock. It does not replay a stale generated simulator action. Runtime's
existing restart behavior cancels abandoned inputs/pending initiatives. Offline
Open run never starts inference or opens the database for mutation.

## Capture format, privacy and availability

Each run has `run.json`, `index.jsonl`, immutable numbered JSON payloads, and a
simulation database. Continued runs add `segments/run-*`. The manifest records
code SHA/dirty state, allowlisted settings, scenario, seed, elapsed time, progress,
status and capture omissions. No environment dump, auth headers or credentials.
Snapshots/role text/transcripts are private and unencrypted; keep `.data/` ignored.

Capture uses the existing TraceRecorder behind one owned writer thread. Enqueue
freezes values; disk writes and close/join stay off-loop. Bounds are 128 MiB trace
storage across segments, 256 queued records, 8 MiB queued payloads and 2 MiB per
record. An oversized record becomes an omission marker. Queue/storage/disk failure
stops capture visibly while chat continues; the manifest exposes gaps. Database
size is separate from the diagnostic cap. Captured files are never auto-deleted.

Exact Fast prompts come from LMStudioFast's actual renderer. Luna/Simulator views
contain submitted prompts, configured roles and available text-visible OMP session
context; **provider HTTP bodies and hidden reasoning remain unavailable**. The
existing 100 ms optional history observation limit remains. Numeric reasoning-token
usage is accounting, not reasoning text. Provider/cache counters are reported only
when exposed and attributable; TTFT alone is not a cache-hit measurement.

Technical summaries include unique calls, TTFT nearest-rank p50/p95 with sample
count, usage/cost by actor, compactions, sequence lag, failures/cancellations and
initiative proposed/claimed/spoken/cancelled/expired. Claimed does not mean spoken.
Interrupted/capped archives are partial. Literal scenario matches are evidence
references, not semantic correctness judgments.

Optional `report RUN_PATH --judge-model MODEL --omp-executable PATH` uses a fresh
tools-disabled judge session after the run. It sees public dialogue and criteria,
not Luna internals; responses retain raw text and are explicitly subjective.
Judge transcript input is bounded to 384 KiB and reports omitted rows.

## Actual evidence collected before testing was deferred

Windows, existing loaded `liac-nemotron` Q4_K_M / 16384 context at localhost:1230,
existing pinned tokenizer and OMP `openai-codex/gpt-6-luna`. No model download or
shared LM Studio setting change. All model content was synthetic test dialogue.

Manual native run `run-2e95ba929ce140fc867dc188084283dd`:

- Two real user turns, three completed Fast calls, two completed Luna calls and
  one autonomous utterance. Native UI displayed the exact Fast prompt and OMP
  role/session view. Runtime stopped normally; capture reported no loss.
- User mentioned unreleased Skin Creator, a blue accent and a save button like
  a swimming pool. Luna call `deep_e059c359fa064d3db5e5cfd5eb51b4af` proposed an
  initiative. Its event-backed proposal led to character-origin turn
  `initiative_turn_initiative_deep_e059c359fa064d3db5e5cfd5eb51b4af`; Nemotron said
  “Тоді 2.0 буде першою, яка вспіла.” No synthetic user input was inserted.
- User corrected the accent to orange and asked to stop redesign jokes. Call
  `deep_c3f4122f1c884150b2ed0b230fd8abb7` accepted a new Markdown update. Fast's
  response respected the correction but sounded somewhat generic/assistant-like.
- Captured chain: conversation.input → fast.started/context/progress/finished →
  deep.started/phase/prompt → omp.context/completed → deep.response/decision →
  initiative proposal/claim → autonomous Fast → later correction/Markdown diff.
- TTFT p50 **155.19 ms**, p95 **220.21 ms**, n=3; 1438 prompt/95 output tokens.
  OMP-reported Luna cost total **$0.00094956**. KV counters were unavailable.

Accelerated smoke `run-a8d4056c3ffd449996b4f9bca01578b3`:

- Stopped at the user's request after **5 simulated messages**, 5 completed Fast
  calls, 5 completed Luna calls and a transition into session 2. Six simulator
  calls completed. Recorded scheduling reached 169.71 seconds before a planned
  72-second actual inter-session wait (720 seconds scaled by 0.1).
- This is **not** a completed 12-turn test, 100–150-turn run or multi-hour soak.
  The process was interrupted; its original manifest remained running and replay
  labels it running-or-interrupted with partial evidence.
- TTFT p50 **122.33 ms**, p95 **155.59 ms**, n=5; 2839 prompt/207 output tokens.
  OMP-reported costs: Luna **$0.00235368**, simulator **$0.00126416**. KV counters
  were unavailable. No compaction or autonomous speech occurred in this sample.
- The simulator made ordinary short Ukrainian conversation, mentioned Pixel and
  tea, then left for a session break. Full correction/continuity coverage remains
  unverified. No judge call or further live test was made after the user deferred it.

## Local verification and remaining limits

Baseline 100 tests passed. The intermediate suite passed 107 tests before later
focused refinements. Focused checks cover bounded/immutable queued capture while
disk writing is held, nonfatal capture errors, archive/restart ownership, historical
snapshot lookup, initiative-to-Luna links, malformed simulator actions, stale-action
suppression after manual pause, failed setup cleanup, paged model bounds, stale
detail completion, Qt shutdown and offline replay. They establish mechanics, not
long-horizon provider compatibility or character quality.

Full long-provider testing, a completed smoke, multi-hour UI responsiveness,
real compaction/pressure/restart/concurrency acceptance and subjective assessment
are deferred. Native Computer Use was stopped by the user's Escape key; no further
window actions were performed. The source tooling is available for that later run.
