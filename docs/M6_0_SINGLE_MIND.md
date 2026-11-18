# M6.0 Single Mind

Status **EXPERIMENT**. Base `fa7c5d7` in SheetHappiness/liac-ai.

## Task 1 transport decision

**GO with Bun.** Node 22.23.3 passes the syntax check but cannot load the
published TypeScript entry point of `@oh-my-pi/pi-ai` 18.22.1
(`ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING`). The package declares Bun
1.4.4 or newer. The user approved Bun for the optional bridge after the
standalone probe succeeded. `pi-ai` and its public model catalog are both
pinned at 18.22.1 in the isolated lockfile.

Run from the worktree root on Windows:

```powershell
Push-Location tools/luna-bridge
npm ci --ignore-scripts
Pop-Location
node --check tools/luna-bridge/probe.mjs
node tools/luna-bridge/probe.mjs --list
npx --yes --package=bun@1.4.4 bun --no-env-file tools/luna-bridge/probe.mjs --list
npx --yes --package=bun@1.4.4 bun --no-env-file tools/luna-bridge/probe.mjs --login
npx --yes --package=bun@1.4.4 bun --no-env-file tools/luna-bridge/probe.mjs --reasoning low
npx --yes --package=bun@1.4.4 bun --no-env-file tools/luna-bridge/probe.mjs --reasoning off
```

The Bun probe listed the exact `openai-codex/gpt-6-luna` model offline and
again through authenticated discovery. Browser OAuth uses the library's
loopback flow and the isolated, ignored `.data/m6-auth/` credential store.
The ordinary stdout report includes only model, capability, validation and
timing metadata. The wire hook compared the exact model, `low` request effort,
two synthetic prompt items and two tool names in memory.

| Matched `low` trial | First event (ms) | First tool delta (ms) | First usable fragment (ms) | Completed (ms) |
| --- | ---: | ---: | ---: | ---: |
| 1 | 449 | 862 | 958 | 1025 |
| 2 | 519 | 885 | 949 | 1057 |
| 3 | 498 | 919 | 987 | 1096 |
| 4 | 533 | 1183 | 1259 | 1352 |
| 5 | 576 | 1024 | 1069 | 1163 |
| Median | 519 | 919 | 987 | 1096 |

Five of five measured requests produced a single completed `speak`, with
strictly parsed stream arguments matching the terminal call. The provider
reported 81 input and 21 output tokens per trial, with zero cache reads and
writes. An exploratory request successfully returned a tool call while the
initial probe failed to detect the short fragment from the SDK's throttled
partial arguments. The measured run used the raw argument deltas to detect
the ASCII fixture's first usable fragment. The active catalog advertised
`low`, `medium`, `high`, `xhigh` and `max`. **`off` unavailable** on the
observed route. The probe declined it before inference.

The offline M5.0 baseline on Python 3.14.7 ran 165 tests with 164 passing.
`test_desktop.WindowTests.test_chat_context_selection_and_offline_history`
errored because `MainWindow.context` is absent.

## Task 2 transport verification

The same authenticated Bun subprocess handled two turns from Python 3.14.7
through `LunaStream`. The final standalone run used synthetic prompts and a
short probe system prompt.

| Decision | First tool delta (ms) | First speech fragment (ms) | Completed (ms) | Input / output tokens |
| --- | ---: | ---: | ---: | ---: |
| `speak` | 1017 | 1116 | 1238 | 78 / 24 |
| `stay_silent` | 2069 | — | 2105 | 76 / 16 |

The speech turn streamed seven provisional deltas and their concatenation
matched the final message. Silence delivered zero text deltas and a complete
tool call. Both reported zero cache reads and writes. The timings are for
the standalone transport. The first `speak_delta` is decoded preview text.
Only a validated terminal `result` carries a completed decision to Python.
A third live turn was cancelled after its first preview, and a subsequent
turn returned a valid silence decision with no stale frames.

Offline checks use a Python subprocess fixture and the pure JS decoder:

```powershell
$env:PYTHONPATH='src;tests;vendor/omp-rpc/src'
python -m unittest test_luna_stream -v
node --test tools/luna-bridge/speak_stream.test.mjs tools/luna-bridge/request_privacy.test.mjs
node --check tools/luna-bridge/bridge.mjs
python -m unittest discover -s tests -v
```

The final run passed six focused Python tests and seven Node tests. The full
Python suite had 170 passes out of 171 tests, with the same baseline desktop
error.

Independent review found raw SDK logging, a race on repeated cancellation,
and duplicate JSON fields. Regression tests reproduced each issue before the
fix. Both JS entry points clear the inherited `PI_REQ_DEBUG` flag and set the
pinned SDK's `PI_TEST_RUNTIME` guard for automatic HTTP 400/413 request dumps.
That guard also makes the dedicated SDK process headless and redirects its
general SDK log directory to the Bun test temp location. A synthetic 400/413
check intercepted disk writes and confirmed both were suppressed. The final
live bridge smoke inherited `PI_REQ_DEBUG=1` and produced no debug dumps.

The Python adapter holds its process lock through bounded cancellation cleanup,
including repeated cancellation. Tool decisions require raw JSON argument stream
evidence matching the provider's completed call. Missing deltas, duplicate
properties, malformed arguments and stale frames cannot authorize a decision.

## Text console

Use the source checkout and Python 3.12 or newer. Fake mode uses the same
Perception Bus, Journal and SingleMind Runtime as Luna. It requires no Bun,
provider login or local model server.

```powershell
$env:PYTHONPATH='src;tests;vendor/omp-rpc/src'
python -m vtuber.m6 --backend fake --db .data/m6-fake.sqlite3
python -m vtuber.m6 --backend luna --reasoning low --db .data/m6-0.sqlite3
```

The Luna command expects the bridge dependencies and OAuth login from Task 1.
Use `--bun` with the executable path when Bun is outside `PATH`. For example,
`$bunExe = npx --yes --package=bun@1.4.4 bun -e 'console.log(process.execPath)'`
locates the pinned `npx` installation. Type text and use `/quit` to drain
pending input and finish the last turn. `[Provisional]` marks streaming text.
`[Final]` shows the completed reply. Silence produces no spoken line.

Keep the experiment on its own ignored SQLite file. The M6 prompt uses the
character identity, one short operating instruction and up to 40 recent canonical
dialogue events. Only completed M6 tool calls replay as matched call/result
pairs. Legacy replies remain plain assistant text. Ambient events stay in the
Journal. On restart, unfinished inputs close as cancelled without regeneration.
The projection keeps the newest event suffix that fits a 63 KiB JSON budget,
leaving room in the 64 KiB bridge frame. Each tool call stays paired with its
result. Oversized current input closes as failed, and later short inputs can
still run. The M5.0 CLI keeps its original entry point and flags.

## End-to-end acceptance

Python 3.14.7, Bun 1.4.4 and pi-ai 18.22.1 ran one authenticated
`openai-codex/gpt-6-luna` `low` session through the console, Perception Bus,
SingleMind Runtime and fresh `.data/m6-0.sqlite3`. A test driver fed synthetic
console lines and captured timings at the bridge boundary. The first prompt
arrived as a two-line burst. Timings start at bridge turn receipt and exclude
the Bus settling window.

| Trial | Completed action | First event (ms) | First tool delta (ms) | First decoded speech (ms) | Completed (ms) | Input / output tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `speak` | 892 | 1246 | 1393 | 1475 | 104 / 25 |
| 2 | `speak` | 396 | 773 | 925 | 959 | 159 / 23 |
| 3 | `speak` | 512 | 1808 | 1942 | 2055 | 210 / 26 |
| 4 | `stay_silent` | 534 | 1018 | — | 1056 | 271 / 16 |
| 5 | `speak` | 480 | 2297 | 2426 | 2494 | 318 / 22 |
| 6 | `stay_silent` | 536 | 1020 | — | 1059 | 370 / 16 |
| 7 | `speak` | 479 | 956 | 1086 | 1204 | 413 / 26 |
| p50 | | 512 | 1020 | 1393 | 1204 | |

All seven outcomes matched the scenarios. The Journal held eight raw
perceptions, seven canonical inputs, seven completed replies with distinct
tool-call IDs, and zero unfinished inputs. Replayed tool results grew from zero
to six across the session. All five speech previews matched their final text
and both silence turns emitted zero preview fragments. Usage reported zero
cache reads and writes, with zero provider or tool-validation failures. The
first-speech p50 uses five speaking turns. The other medians use all seven.
The sample is too small for a useful p95. `off` remains unavailable on this route.
An additional `python -m vtuber.m6 --backend luna` entry-point smoke with a
separate scratch database rendered a completed text reply and exited cleanly.
After adding the history budget, a synthetic oversized input closed as failed
and a subsequent short prompt completed with real Luna in the same database.
An offline pi-ai payload inspection confirmed the replayed call and result IDs
matched on the wire for both actions and the latest user text appeared once.

Offline verification:

```powershell
python -m unittest test_luna_stream test_m6_context test_single_mind test_m6_cli test_perception_runtime -v
python -m unittest discover -s tests -v
node --test tools/luna-bridge/speak_stream.test.mjs tools/luna-bridge/request_privacy.test.mjs
git diff --check
```

The focused run passed 41 tests on Python 3.12.14 and 3.14.7. Node passed seven.
The fake console smoke grouped two quick lines into one reply and closed with
zero unfinished inputs. The full Python suite passed 188 of 189 tests. Its only
error remained the baseline `MainWindow.context` desktop regression.

Independent review confirmed that oversized history could block later turns
at the bridge limit. The reviewer assessed the byte-budget fix in `74fb7cb`
and gave a **GO** for the local M6 text experiment. A completed Journal event
records the validated tool decision. Console notifications remain ephemeral.

This milestone leaves Wake/Attention, Live State, VLM, M4.8 compaction
adaptation, TTS and external actions for later work. The measurements cover
text and tool streaming. Audio delivery and first-audio latency remain unmeasured.
