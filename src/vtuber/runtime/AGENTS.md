# Runtime

Bolt owns personality and decisions; Luna preserves experience; Runtime owns execution. Keep one serialized Deep worker,
short atomic state/result/cursor transactions and frozen Fast snapshots. No
transaction spans inference. Technical failures preserve the cursor; audit-only
and autonomous-only tails cannot create inference loops.

Markdown is applied directly without evidence, revision/epoch approval or
semantic dependencies. SQLite remains authoritative; context.md is an off-loop
projection. Startup and changed commits export; close joins owned writes.

Epochs retain complete-turn boundaries, local budgets and monotonic cutoffs.
Budget-only fallback is explicitly degraded, preserving canonical history and
pending Luna recovery even after pressure falls or the process restarts.

Initiative is a legacy experimental capability, disabled and outside the M4.7 role
contract. The opt-in transport remains one pending intent: none preserves, speak replaces, cancel withdraws.
Keep delay, consume-once, input locking, user priority and owned-task cancellation.
No relevance guards, TTL, cooldown or revision expiry. Restart cancels pending work
and unfinished inputs. Trace failures cannot affect domain work. Keep provider
clients outside Runtime and credentials/configuration out of domain events.

## M6 opt-in runtime (not the legacy Fast/Deep worker)

`single_mind.py` runs one Luna decision at a time. Ambient `state` and
`observation` events update temporary conversation-scoped `LiveState`;
they do not wake Luna or cancel streaming. A direct local message captures a
frozen sensory snapshot after the existing Journal transaction. Do not move
cognition into this runtime or add a second worker for attention.
