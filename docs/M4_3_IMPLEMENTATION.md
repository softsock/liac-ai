# M4.3 — Initiative & Character Continuity

Implemented from M4.2 `bea6abc` in the existing `codex/m4-2-markdown-context`
branch, as explicitly requested at execution. No push or PR.
[Plan](superpowers/plans/2026-11-13-m4-3-initiative.md) and
[original requirements](superpowers/specs/2026-11-13-m4-3-initiative-requirements.md).

## Small execution contract

Luna maintains interests, unfinished threads, optional lines and boundaries in
the same free-form Markdown context. No required headings or numeric psychology.
Schema-v2 Deep results append `initiative`: null or `{action:"none"}` preserves
the existing intent and original deadlines; `{action:"cancel",reason}` explicitly
withdraws it; `{action:"speak",intent,reason,source_event_ids}` proposes content.
Optional `delay_seconds`/`ttl_seconds` use captured configuration when omitted.
Text is bounded to 1000 characters per intent/reason; evidence must be real,
same-character canonical events supplied to that request. Old schema-v1 remains valid.
Default new fields are omitted from historical replay fingerprints.

Runtime assigns IDs, user anchor, post-batch revision/epoch and absolute deadlines.
Proposal, Markdown, epoch, batch audit and acknowledgement commit atomically.
Late ordinary input may still permit a valid Markdown update, while suppressing
stale speech. A stale cancellation cannot withdraw a newer pending proposal.
None alone never withdraws an intent; changed execution dependencies still may.

## Execution, history and recovery

One owned readiness task waits for an accepted opportunity, cooldown and idle Fast.
It yields to queued real inputs and checks again under the normal input lock.
Context preparation precedes atomic claim. Claim rechecks the actual snapshot,
anchor, revision/epoch, deadline, cooldown and durable one-attempt guard, then
consumes the opportunity and appends `character.initiative.started` plus
`character.reply.started` in one transaction. A local epoch transition invalidates
the opportunity; it is never silently rebased. No transaction spans an await.

Both origins share compiler, tokenizer, Nemotron, streaming, output kinds,
cancellation and exactly one terminal per input. The autonomous final control
is explicitly character-origin; it never becomes a `user.message.completed`.
Only completed speech enters assistant history. An autonomous-only tail remains
available to the next ordinary Deep batch (or genuine compaction) without
starting another inference cycle. Timers never notify Deep.

At most one attempt per latest real user event; exact normalized intent plus
evidence is also durably suppressed. Attempts include failed/cancelled streams.
New user input or explicit Cancel Fast closes pending work; an active autonomous
stream cancels before the user stream starts. Shutdown joins owned work.
Startup durably cancels pending opportunities and every accepted input lacking
a terminal, including a crash before the Fast task's first instruction.

## Configuration and timing

Initiative is off by default (`--enable-initiative` to opt in). The desktop stays
off and restores completed autonomous speech through its existing Fast history view.
Delay 5 seconds, TTL 120 seconds, cooldown 60 seconds are configurable experiments.
Require finite nonnegative delay/cooldown, positive TTL and delay < TTL; reject
booleans. Delay/TTL start at request capture, so Luna inference may exhaust delay
or TTL. Readiness anchors UTC at arming and projects it with monotonic elapsed
time through context preparation and atomic claim. Changing wall time during a
wait cannot strand its opportunity. Wall timestamps support durable audit/cooldown;
restart never resumes.

## Live acceptance (2026-11-13)

Real OMP `openai-codex/gpt-6-luna` and loaded local `liac-nemotron` (16384 context,
pinned tokenizer); no downloads or shared model-setting changes. Synthetic
conversations and raw evidence remain ignored under `.data/`.

- A first natural Skin Creator trial produced two no-idea results: Fast had already
  teased the button redesign and the user was returning to work. Luna explicitly
  chose not to pile on. This is retained as a failed initiative-elicitation trial.
- A subsequent unforced trial said version 2 might arrive before unreleased v1.
  Luna proposed pointing out that v1 could be obsolete before birth, citing the
  actual user event. Nemotron independently said: “So you're building a whole new
  thing while the first one hasn't even left the drawing board yet? That's quite
  a production schedule.” One autonomous turn, no fabricated user input. It fits
  the topic; it remains a question followed by a dry observation, rather than
  proof that repetitive-question behavior is solved. Autonomous TTFT 305.69 ms,
  509 prompt tokens, 32 output tokens, local/provider count difference zero.
- B: greeting then “See you later” produced silence, two ordinary Deep calls and
  zero timer-triggered calls in the observed window.
- C: a held **real** Luna pool/changelog joke arrived after “stop redesign jokes,
  layout finished, checking keyboard navigation.” Speech was suppressed as stale;
  the following real Luna explicitly cancelled the old idea and updated Markdown.
  Another held result updated Markdown normally while newer Fast completed.
- D/F: reopening the same real conversation DB restored the document (including
  deliberate projection corruption), did not repeat speech, had no unfinished
  inputs, and returned `ok` from SQLite integrity checking.

- E: a real Luna proposal and actual Nemotron stream were held after the first
  chunk, then superseded by user input. Cancellation took 5.15 ms; one cancelled
  terminal, no partial autonomous speech in canonical history. The new reply's
  TTFT was 111.34 ms. The exact readiness-before-lock race is deterministic-test
  evidence; the live test exercises arrival during actual streaming.
- G: Fast completed an ordinary reply while real Luna was still `analyzing`,
  with TTFT 94.53 ms and 228.42 ms submit-to-completion. No injected Deep hold.
- A repeat of the natural script chose silence again; initiative is not reliable
  on every topical opening. A separate actual cache-measurement conversation
  produced another spontaneous line: “Version 2 arriving before one sounds less
  like a roadmap and more like some accidental time travel.” No generic question.

None/preserve with a pending deadline, explicit withdrawal, claim duplication and
crash boundaries have focused deterministic regression checks. Live no-idea and
explicit-cancel outputs were observed separately; a paired live no-idea response
while an accepted intent was still waiting was not forced. Initial 5/120/60 timings
were used for natural trials; stream cancellation used 1/120/2 to expose the race,
not to claim better conversational rhythm. No timing optimum is established.

## Costs, cache and limits

The successful A trial needed one ordinary Deep call; its OMP usage reported
2269 input, 544 output (including 334 reasoning), 2813 total tokens, estimated
cost $0.0004989. These are provider-reported accounting values, not a billing
guarantee. The completed autonomous tail caused zero extra calls during the
observed wait; the next real user batch still pays to observe its outcome.
Real dialogue remains the main acceptance evidence; fakes establish invariants only.

Three serial controlled trials each independently primed the identical baseline
with fixed identity/epoch/history/Markdown. Backend counters attributed exactly
one runtime task per measured window:

| Change | Full prompt | Evaluated tokens | TTFT (three trials) |
|---|---:|---:|---|
| Final user → initiative control only | 5969 | 70 | 60.79, 63.22, 65.91 ms |
| Production tail (control + wrapper target wording) | 5970 | 93 | 64.84, 63.52, 63.76 ms |

Stable early messages are identical. These counters demonstrate reuse for a long
stable prefix, not zero cost. The real autonomous Runtime turn in a short history
evaluated all 486 prompt tokens, TTFT 312.62 ms, 20 output tokens, local/provider
count difference zero. Small prompts and growing history may have no useful cache
reuse. `cached_tokens` itself was unavailable; evaluated-token counters were
available, so no cache-hit number was inferred from TTFT. An earlier overlapping
probe had an ambiguous window and was discarded; serial reruns supplied the table.

Private evidence: `.data/m4-3-initiative.jsonl` (three behavioral runs),
`.data/m4-3-cache-serial.jsonl` (table), `.data/m4-3-cache-final.jsonl` (another
three controlled trials plus actual autonomous turn). These are local ignored
artifacts, intentionally absent from another checkout.

## Verification

Baseline: 94 unittest checks. Current implementation: 100 checks, including Qt
offscreen tests, plus verifier measurement self-check and actual provider trials.
The six added tests concentrate on protocol trust boundaries, atomic lifecycle,
late speech suppression, race/cancellation, restart and clock corrections; existing prefix/replay/
configuration checks were extended. No new dependency or DB schema migration.
An independent whole-diff review found one stranded-waiter bug after backward
wall-clock correction. Its regression failed first, then passed with monotonic
eligibility projection; the full suite passed after the fix. No other actionable
findings in the five requested focus areas. Long-term naturalness and provider/cache
results remain bounded by these recorded trials; the reviewer did not run providers.

No scheduler framework, second memory/projection, Markdown execution parser,
semantic duplicate classifier, new UI controls, sensors, voice or extra agents.
Across new user anchors, semantic repetition and appropriateness remain Luna's
judgment. Short trials do not establish long-term naturalness or optimal timing.
