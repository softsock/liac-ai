# M6.1 – Attention, Live State, and bounded context

**EXPERIMENT** · Opt-in Single Mind path on `codex/m6-1-attention-live-state`.

## Attention and context

- Newly accepted local direct chat wakes Luna once per batch. Ambient observations never start or cancel a turn. Noise is ignored. Replaying a perception ID, including within one batch, cannot refresh Live State or wake Luna again.
- Live State keeps the latest ambient `state` or `observation` per source and kind for the supported local conversation. It holds up to eight entries in memory with a 120-second monotonic lifetime. Other conversation events can be journaled without displacing local observations. A turn freezes its local view before generation.
- The context compiler reserves space for the identity and latest user input, then fits the bounded sensor block and a contiguous suffix of up to 20 completed turns. The 63 KiB cap measures compact UTF-8 JSON for the message array, leaving space for the 64 KiB JSONL bridge envelope. If identity and latest input exceed the cap, Runtime records a technical failure before calling Luna.
- SQLite Journal remains authoritative. M6 joins prior user messages and completed replies by character and turn ID. It projects legacy speech as assistant text and replays both `speak` and `stay_silent` with their original tool-call IDs and matching results. Failed, cancelled, and unfinished turns stay in Journal. Startup closes unfinished turns without regenerating them.

[M4.8 Hot/Cold](M4_8_CONTEXT_HANDOFF.md) contributes two rules here. Cut at complete turn boundaries and freeze the selected context for the duration of a request. The recent suffix is the hot history and older events remain available in Journal. Two short live turns provide initial token and timing measurements. Consolidation thresholds and semantic summaries remain future work.

## Monitoring for VTuber Hub

Call `SingleMindRuntime.snapshot()` on its owning asyncio loop. Combine the detached JSON-serializable snapshot with existing `RuntimeOutput` for streaming and terminal events.

| Field | Contents |
| --- | --- |
| `runtime` | `idle`, `generating`, or `failed` and the active turn ID |
| `model` | Model name, reasoning effort, and bridge process status. `running` means the subprocess is alive |
| `perception`, `wake` | Latest accepted local metadata and latest local wake decision with its reason |
| `live_state` | Current local observations with bounded text and remaining lifetime in seconds |
| `context` | Last compiled turn ID, message-array bytes, included historical turn count, sensor inclusion, and whether older completed history was omitted |
| `generation` | Turn ID, bridge first tool delta and duration, Runtime duration, model usage, and last completed action |
| `errors` | Last technical error code and turn ID |

Missing measurements are null. The bridge reports provider timings with the completed result. Runtime updates terminal diagnostics after the Journal commit and before publishing the terminal output.

## Fake and local acceptance

On Windows with Python 3.14, all 58 focused tests passed. The full suite passed 205 of 206 tests. The sole error also reproduced at the baseline in `test_desktop.WindowTests.test_chat_context_selection_and_offline_history` because the test still reads `MainWindow.context`. Both the M6 fake CLI and legacy Fast/Deep fake CLI exited successfully after one committed reply in separate temporary databases.

| Scenario | Result |
| --- | --- |
| Direct chat → `speak` | One generation and one committed reply |
| `/scene` only | Live State updated with no request |
| `/scene` followed by a question | Sensor block appeared immediately before the latest input |
| Ambient update during generation | Active frame stayed fixed and the next turn received the update |
| `stay_silent` | Committed as an empty reply with no visible final speech |
| Restart | Earlier tool history replayed on the next user input and unfinished turns did not restart |
| Long history | Completed turns stayed intact under both the byte and turn caps |

Run focused or full checks from the repository root with the project dependencies installed.

```powershell
$env:PYTHONPATH='src;vendor/omp-rpc/src'
python -m unittest tests.test_m6_attention tests.test_m6_context tests.test_single_mind tests.test_m6_cli tests.test_perception_runtime tests.test_luna_stream -v
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest discover -s tests -v
```

## Live GPT-6 Luna Low acceptance

A two-turn check used the Python M6 console path, the existing authenticated Bun bridge, synthetic input, and a temporary Journal. Each standalone scene update produced zero requests. Luna named the blue mug from the first scene, then recalled the blue mug from its prior `speak` turn after the current scene switched to a green notebook.

| Turn | Frame bytes | Prior turns | Input tokens | Output tokens | Cache read | Cache write | First tool delta | Bridge duration | Runtime duration |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Scene question | 631 | 0 | 166 | 26 | 0 | 0 | 2,474 ms | 2,782 ms | 2,998 ms |
| Follow-up after scene change | 1,577 | 1 | 236 | 23 | 0 | 0 | 1,849 ms | 2,155 ms | 2,157 ms |

The live check covered two short spoken turns. Silence, restart, in-flight scene changes, and long history were exercised with fakes.

[M6.1.5 VTuber Hub](M6_1_5_VTUBER_HUB.md) uses this snapshot and `RuntimeOutput` over local JSONL IPC. VLM and TTS follow the Hub.
