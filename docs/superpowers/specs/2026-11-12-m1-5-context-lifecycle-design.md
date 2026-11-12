# M1.5 Context Lifecycle Design

Status: approved 2026-11-12; implemented with evidence in [M1.5 report](../../M1_5_IMPLEMENTATION.md).

## Intent and scope

Implement the user's M1.5 request on `codex/m1-context-cache`, based on
`e3bd3ae`. Replace the newest-20-event rolling window with durable context
epochs, count the actual Nemotron prompt locally, remove the verified duplicate
BOS, and expose a validated compaction boundary for future asynchronous Luna.
Keep stateless LM Studio requests, SQLite as authority, immutable Fast snapshots,
and FakeDeep. Implementing Luna/OMP, semantic memory, retrieval, beats and external
interfaces belongs to later milestones.

The request authorizes one meaningful implementation commit after verification.
It does not request a push, PR, merge, model reload or global settings change.
Use the previously selected Native execution method after plan review.

## Findings checked on 2026-11-12

- Root and contracts/runtime/minds/tests instructions were read. Current branch
  is correct, worktree was clean, and all 17 existing tests passed on Python 3.14.7.
- `ContextCompiler` currently counts UTF-8 bytes plus overhead; Runtime supplies
  at most 20 dialogue events. M1's production sample estimated 11821 tokens but
  LM Studio counted 2153. Its transport experiment reached 15483 input tokens.
- M1's ~15.5K medians: append 82.11 ms / 84 evaluated tokens; note change
  73.11 ms / 22; rolling-window shift 2003.79 ms / 15483. These are baseline
  measurements, not acceptance guarantees for another workload.
- `liac-nemotron` remains loaded and idle, context 16384, parallel 4. Selected
  engine is CUDA12 llama.cpp 2.73.0. The actual local GGUF is
  `C:/ai/models/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB/Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf`.
  Its metadata says Gemma4, BOS ID 2, EOS ID 1, `add_bos_token=true`.
- Two serial compatibility calls returned READY. Current renderer: input 49,
  evaluated 49, duplicate-BOS warning present. Removing only its leading BOS:
  input 48, evaluated 48, warning absent. TTFT was 282.94/50.80 ms, but two
  unmatched requests do not establish a performance improvement.
- NVIDIA's old BF16 repository URL redirects to
  `nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-BF16`. Inspected revision:
  `49843eed8db1f1c616c47af75cfd36e07aec0667`.
  `tokenizer.json`: 32169626 bytes; SHA-256
  `cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f`.
  It is BPE with byte fallback and explicit special IDs; its postprocessor adds
  no BOS. Matching it against the installed GGUF remains an implementation gate.
- `tokenizers==0.22.2` publishes a Windows cp39-abi3 wheel; it requires
  `huggingface-hub`. Neither is currently installed. No dependencies were installed
  for planning. SDK tokenization is server-backed, so it is only a possible
  calibration oracle, not the production per-turn counter.

## Approaches and proposed choice

1. Increase the rolling window and calibrate a byte heuristic: small change, but
   still periodically loses the prefix and lacks reliable multilingual budgeting.
2. **Durable epochs plus local NVIDIA tokenizer (proposed):** one optional
   tokenizer dependency, small additive SQLite migration, exact rendered-prompt
   counting subject to live parity verification. No second model/runtime.
3. Add a separate llama.cpp tokenizer service or permanent provider chat: adds
   process/session ownership and does not meet the local stateless budgeting goal.

These alternatives were evaluated before approval; option 2 was accepted. The
mechanisms are one project: epoch transitions require token counts,
and their value must be checked through the actual runtime, renderer and provider.

## Epoch data and ownership

Add frozen contracts in `contracts/context.py`:

- `ContextItem(text, source_event_ids, kind="extract", truncated=False)`;
  `kind` is `extract` or `summary`. Both remain quoted, source-attributed data.
- `ContextEpoch(version=0, compacted_through_sequence=0, items=())`.
- `CompactionProposal(proposal_id, character_id, based_on_epoch,
  based_on_revision, observed_through_sequence, compacted_through_sequence, items)`.
- `CompactionResult(accepted, epoch_version, reason)`.

Extend `FastSnapshot` with a default empty `epoch`; retain its existing
`recent_dialogue` field name, but remove the twenty-event cap from production
snapshot construction. Store every committed epoch in a new `context_epochs`
table keyed by `(character_id, version)`. Highest committed version is active;
version zero is the implicit empty initial epoch. Upgrade SQLite `user_version`
from 1 to 2 transactionally without rewriting events, notes or Deep cursors.

An epoch's compacted block and cutoff never change. Its exact history is all
dialogue after the cutoff through the snapshot watermark. Raw Journal events
remain intact. Only completed reply text enters history; cancelled/failed output
never does. Keep user messages from those turns, grouped by turn ID when choosing
a cutoff. Never cut through an unfinished turn or split a completed exchange.

Journal atomically validates proposal identity, exact base epoch and note revision,
watermarks, terminal-turn boundary, item types and character-scoped evidence;
inserts the new epoch and applied/rejected audit. Replays return the original
result; conflicting reuse of a proposal ID fails. Rejection leaves epoch/state
intact. An epoch switch does not increment the separate note revision or advance
the Deep cursor. Runtime checks the token budget before Journal commits.
Bound proposals to 32 items, 32 source IDs/item and 8000 characters/item; reject
booleans as integer revisions/watermarks and malformed IDs before SQLite binding.

An asynchronous provider may propose compaction against an older event watermark.
Later turns stay exact after its cutoff; proposals cannot erase them. A changed
base epoch or note revision is rejected, never silently rebased. An active Fast
generator keeps its original frozen snapshot if another epoch is committed.

## Prompt and budget

Order: **identity → frozen quoted epoch items → growing exact epoch history →
quoted current state/note → current user → generation prefix**. Empty epoch items
produce no block. State/summary metadata, timestamps and hashes never enter the
identity/history prefix accidentally. Keep escaped role/control delimiters, one
system identity, thinking off and conversational mode on.

Move the renderer and its constants to `minds/nemotron.py`; LM Studio imports the
same renderer used by `NemotronTokenCounter`. The wire renderer omits leading
`<bos>` because the verified backend supplies it. Count
`len(tokenizer.encode(rendered, add_special_tokens=False).ids) + 1` for backend
BOS. Disable tokenizer truncation/padding. Load one explicitly supplied local
file once; verify its pinned hash and special IDs. Do not download at startup or
fall back silently to the old estimator for real Fast. Keep fake mode dependency
free with an explicitly labelled conservative counter.

Proposed defaults: context **16384**, output **512**, extra budget margin **32**;
maximum counted input **15840**. Transition soft limit is
`floor(0.90 * (context - output - margin))`, **14256** by default. This is a policy
choice, not an inference-engine limit. Small contexts scale the optional budgets
down. Count complete rendered candidates, including spoken instruction, wrappers,
escaping, role boundaries, generation prefix and backend BOS; do not add separately
tokenized message counts and claim exactness.

Real startup performs one short compatibility generation, comparing local count
against provider `prompt_tokens`; mismatch or absent usage fails clearly before
accepting input. A calibration corpus during implementation also checks Ukrainian,
English, emoji, combining marks, whitespace, code, literal control markers and
2K/8K/near-limit prompts. Any mismatch blocks the exact-counter acceptance; fix
the tokenizer/template correspondence rather than inventing an unproven factor.
No tokenization HTTP/SDK call occurs on the turn path. Provider usage mismatches
later are visible diagnostics and stop subsequent real turns until restart and
revalidation. The 32-token margin is headroom, not a proof for an incorrect counter.

Identity, active note and current input are required whole. If they alone exceed
the hard budget, fail that turn before HTTP with a durable failure; do not compact
them. No individual history message slides out inside an epoch: a compiler either
fits the supplied epoch or asks Runtime to transition it.

## Deterministic M1.5 transition policy

Run local preparation at the next submitted turn; no wait for Deep or Luna. If the
full candidate exceeds the soft limit and there is material to compact, prepare
and atomically apply one proposal, then freeze the resulting snapshot. Hard budget
pressure also triggers preparation, including a large input/note jump.

Keep the newest **three terminal turns**, whole, up to **2048 tokens** of incremental
rendered cost as overlap. Set the cutoff before that suffix. Build quoted extract
items from previous epoch items plus newly compacted dialogue. Preserve the oldest
user extract as an anchor, then select the newest remaining extracts; render them
chronologically. Each extract is at most **256 tokens** including its attribution;
truncate only these explicitly marked optional excerpts at Unicode boundaries.
Extracts also obey the proposal's 8000-character limit.
Total incremental compact-block budget is **2048 tokens**, including wrappers.
Preserve complete overlap turns whenever they fit; oversized recent turns may
be represented by marked excerpts rather than an over-budget exact overlap.

Finally fit the entire new candidate under the hard limit: remove oldest optional
overlap turns first, then non-anchor excerpts oldest first, then the anchor if
necessary. Record omitted source IDs/counts in bounded diagnostics. A summary-only
reduction may keep the same cutoff but must change items; never create a no-op
epoch or retry indefinitely. If nothing can be reduced, keep the fitting epoch
or fail required-content overflow. Commit no speculative epoch for an input that
cannot fit even without optional material.

This is extractive retention, not semantic understanding. It preserves the bounded
anchor, selected recent evidence and required note/input, but cannot guarantee
every important old fact survives. Current corrections remain later raw input;
old quotations never gain policy authority. M2 can replace the extractor through
the same proposal boundary. A full new-epoch prefill is expected and measured.

## Diagnostics, verification and completion

Expose epoch version/cutoff, summary source IDs, exact-history range/count,
local input count/method/tokenizer fingerprint, limit/reserve/margin/headroom,
compile time, actual provider count/difference and prompt/prefix hashes through
existing `/context`, `/metrics`, `/status`. No raw excerpts or credentials in
default diagnostics. Keep native runtime log parsing in a verification script,
not in the production adapter; unavailable cache counters stay null.

Critical automated checks cover additive migration/rollback/replay, stale/cross-
character proposals and unfinished cutoffs, frozen snapshots, >20-event prefix
growth, whole required content, exact boundary rejection and stream cancellation.
Run genuine CLI sessions across two transitions and a process restart; retain a
fictional anchor fact, apply a newer correction, change Deep notes while Fast
streams, and supersede a live reply. Also test semantic recall near the real
context limit; READY-only timing is insufficient for quality acceptance.

Repeat M1's 2K/8K/near-15.5K append/note/shift transport controls, separately from
at least 30 actual Runtime turns per three serial trials. Capture counted/actual
input, TTFT, compilation, prompt evaluation, task attribution, epoch transition
cost and context utilization. Aggregate p50/p95 and per-transition observations;
separate warm reuse from prime/restart and unavailable counters. Cache loss must
never affect correctness. Preserve the model's existing settings.

Update README, relevant AGENTS, blueprint §§7/9.4/20/OQ-04 and write
`docs/M1_5_IMPLEMENTATION.md` with actual results, dependency/setup choices,
retention limits and M2 readiness. Leave original M1 results historical. Native
execution ends with one fresh non-Astra reviewer, appropriate tests and one
implementation commit including softsock's co-author trailer.

## Primary references

- [NVIDIA tokenizer and template, pinned revision](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-BF16/tree/49843eed8db1f1c616c47af75cfd36e07aec0667)
- [Tokenizers 0.22.2 Python interface](https://github.com/huggingface/tokenizers/blob/v0.22.2/bindings/python/py_src/tokenizers/__init__.pyi)
- [LM Studio tokenization](https://lmstudio.ai/docs/python/tokenization)
- [llama.cpp server: BOS and prefix caching](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
  describes upstream behavior; the installed LM Studio engine is verified locally.
- [M1 live baseline](../../M1_IMPLEMENTATION.md#m1-context-cache-follow-up--2026-11-12)
- [Project blueprint](../../PROJECT_BLUEPRINT.md)
