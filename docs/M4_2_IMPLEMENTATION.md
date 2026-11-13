# M4.2 — Luna-managed Markdown working context

Implemented on `codex/m4-2-markdown-context`, from fetched `origin/main`
`ec46c3e3524c92bf6c18da0d69f53276c0c76298`, 2026-11-13.
[Requirements](superpowers/specs/2026-11-13-m4-2-markdown-context-requirements.md)
and [revised plan](superpowers/plans/2026-11-13-m4-2-markdown-context.md).
No Attention Engine, scheduler, new application agent, dependency or schema migration.
Derived `*.contexts/` directories are Git-ignored even for custom DB paths.

## Contract and persistence

The existing `context_note` column, `NoteProposal.note` and schema-v1 JSON field
`note.text` now hold one whole free-form Markdown document. No heading is mandatory.
Luna receives canonical events, prior document, immutable epoch and its configured
budget through the existing serialized OMP session. Canonical evidence overrides
disposable session recollection. Almost-ready lines are optional ideas for Fast.

A replacement needs valid same-character sources, the captured revision and epoch.
Changed text increments the revision once; identical text is accepted `no_change`;
`text:""` clears; `note:null` preserves. Empty clears still need evidence. State,
epoch, operation audits, batch decision and cursor commit in one SQLite transaction.
A budget rejection rejects the entire batch, including bundled compaction. Historical
request fingerprints omit the new budget at its compatible default of 2048; explicit
nondefault budgets participate in replay/conflicting-ID checks. Schema remains v2;
existing v1 additive migration and raw-event/cursor/epoch preservation checks pass.

Ordinary newer dialogue does **not** invalidate a valid result. Its cursor only
acknowledges the captured range, so the next batch sees newer turns. Revision/epoch
conflicts still reject. CAS does not recognize arbitrary semantic contradictions:
current exact corrections take precedence through the authored identity and tail
policy, and Luna removes superseded ideas on the next update. This is model behavior,
not a deterministic guarantee of obedience.

`Config.working_context_tokens` / `--working-context-tokens` defaults to **2048**;
positive integers below the full input allowance are valid. Validation measures the
incremental whole-rendered prompt cost of the document against an empty document.
The default fake counter is conservative; real Fast uses the pinned exact tokenizer.
Only actual text consumes capacity. A separate **32768 UTF-8 byte** structural ceiling
bounds the document; existing 64-KiB response and 512-KiB request gates still apply.
Lowering the cap preserves legacy stored text on startup. Full-prompt overflow still
fails rather than truncating required text or dropping individual history messages.
Short live documents did not approach either cap; these trials do not prove 2048 is
better than 1024. Keep 2048 initially to leave room for a larger current perspective,
and tune from longer conversations rather than treating either number as final.

`context.md` is a projection at
`<db filename>.contexts/<SHA-256(character ID UTF-8)>/context.md` beside the DB.
Two standard-library helpers derive the isolated path and write UTF-8 bytes to a
same-directory temporary file, close it and `os.replace`. Failed replacement leaves
the previous file whole. The existing Deep worker serializes startup refresh and
post-change writes off-loop; close joins an in-flight write. No inference or file
await spans a database transaction or submit lock. A file `OSError` records its class
only in `context_export_error`; DB/cursor stay committed. Retry on next changed
document or restart. Manual file edits are never input. There is no exporter service,
watcher, queue, manifest, periodic retry or generalized recovery framework.

## Fast prompt and cache

Order: identity → immutable epoch → growing exact history → one raw Markdown tail
with a fixed precedence wrapper → current user input. Even empty Markdown retains
its block. Revision, character ID and timestamps are absent from that block. The
stable prefix/hash and rendered history bytes stay unchanged when only Markdown
changes. Renderer escaping, one backend BOS, 512 output + 32 margin, stateless raw
completions, tokenizer parity, stream cancellation and frozen snapshots remain.

On the existing NVIDIA Nemotron Q4_K_M, loaded with 16384 context as `liac-nemotron`
on localhost:1230, three matched serial trials used **5950-token** full prompts:

| Changed region | Backend evaluated tokens (3 trials) | TTFT ms (3 trials) |
|---|---|---|
| Markdown tail | 16 / 16 / 16 | 73.72 / 58.78 / 63.21 |
| Epoch block | 5950 / 5950 / 5950 | 720.90 / 722.70 / 725.45 |

Each case separately primed the identical baseline, preserving identity/history/input.
The epoch case changed the early block to isolate invalidation; it was a controlled
prompt comparison, not an actual Journal compaction. LM Studio runtime log timing
records were attributed to one serial task each; no double BOS. `cached_tokens`
was not exposed. These evaluated-token counts support reuse here; TTFT alone does
not, and other engines/configurations may differ.

## Actual dialogues and lifecycle checks

Actual providers: Nemotron above and OMP `openai-codex/gpt-6-luna`; existing binary,
SDK and local tokenizer were reused. The user authorized starting the existing
model/server. No download, model reload or shared cache setting change occurred.
Private transcripts, databases and raw logs remain ignored under `.data/m4-2-*`
and `.data/m2-*`; the excerpts below use synthetic fictional conversation content.

The first dialogue revealed needless rewriting after `Okay` at 1024. At 2048 it
already returned no change. The Deep role was tightened to avoid recapping Fast's
latest answer or acknowledging trivial acknowledgements. A full repeat then kept
the document/revision unchanged after `Okay` at **both budgets**.

One real 1024-token-budget document contained:

> Optional playful angle: joke that version 1 may already be auditioning for version 4.

Fast chose its own line on the following turn:

> Are you sure Version 1 isn't good enough yet?

Luna subsequently replaced this with an optional sequel angle and then removed it
following the user's boundary. The free-form wording varied across runs; this
shows suggestions remain optional, not a fixed script. Because the shared exact
history also supports teasing, this dialogue alone does not isolate a causal effect
of that specific line. The accessibility document supplied concrete next checks
(tab order, focus, dialogs), and Fast naturally answered about keyboard navigation.

A deliberately held real Luna result was delivered after the user said to stop
teasing and freeze the layout. All corresponding batch decisions acknowledged;
Luna then replaced the old redesign perspective with serious accessibility testing.
Both budgets restored a deliberately stale file from SQLite on restart, preserving
state and passing `PRAGMA integrity_check`. The additional held-update run paused correction analysis after committing the stale
document. Fast still answered seriously at 1024 ("Tab through all interactive
elements...") and 2048 ("Try tabbing through every interactive element...") while
that stale document still invited redesign teasing. Subsequent Luna updates removed
the joke. At 2048 an earlier document's optional "fourth redesign" angle preceded
Fast's "Oh, here we go with round four? You just need to ship it already."

The final held-update run retained no-op at 1024 but rewrote at 2048 after `Okay`.
Thus unchanged output is supported and observed at both budgets, but the model's
judgment of whether an acknowledgement warrants an update remains variable; the
prompt refinement did not make no-op selection deterministic.

The existing long phase ran one trial: **30 Fast turns**, two semantic epoch switches,
maximum recorded input **12859**, and **23 turns while Deep was analyzing**. All six
recall probes succeeded (green hat, amethyst, Hazel, Saffron, noon, fish tax), including
green after restart, with no unfinished reply. Semantic switches occurred after
75% pressure rather than waiting for the window to fill. The offline phase forced
90% fallback: reconstructed pre-transition input **15190** versus threshold **14256**,
epoch advanced while cursor stayed 0, and real Luna recovered afterward. The existing
real CLI passed twice, including restart/green recall. These are one-run acceptance
checks, not a reliability or throughput benchmark.

## Reproduction and deterministic verification

Use the repository environment with `PYTHONPATH=src` if not installed in this
worktree. Commands executed (default endpoint/model/tokenizer shown above):

```powershell
python -m unittest discover -s tests -v
python scripts/verify_m2_luna.py --self-check
python scripts/verify_m2_luna.py --phase markdown --omp-executable C:/Users/shtvl/AppData/Local/omp/omp.exe --output .data/m4-2-late-correction.jsonl
python scripts/verify_m1_5_context.py --phase markdown-cache --output .data/m4-2-cache.jsonl
python scripts/verify_m2_luna.py --phase long --trials 1 --omp-executable C:/Users/shtvl/AppData/Local/omp/omp.exe --output .data/m4-2-long.jsonl
python scripts/verify_m2_luna.py --phase offline --omp-executable C:/Users/shtvl/AppData/Local/omp/omp.exe --output .data/m4-2-offline.jsonl
python scripts/verify_m2_luna.py --phase cli --omp-executable C:/Users/shtvl/AppData/Local/omp/omp.exe --output .data/m4-2-cli.jsonl
git diff --check
```

The current suite has **94 passing tests**, including optional Qt desktop tests.
Focused checks cover UTF-8 bounds/raw whitespace/clear/no-op; exact tail/hash/escaping;
configured cap and rejected bundled compaction; normal delayed inputs; replay and
legacy fingerprint compatibility; v1/v2 preservation; transaction rollback with long
and empty documents; atomic file failure/recovery/integrity; Fast during a blocked
file write and close joining it; original epoch/tokenizer/transport cancellation.
Existing verifier defaults remain compatible; only opt-in `markdown` and
`markdown-cache` phases were added. M1.5's inline counter-attribution assertions ran
before live calls. No new verifier script or generic scenario infrastructure.

M4.1 remains reverted. All implemented behavior fits the existing state/observer/
compiler boundaries; richer attention, scheduling and memory remain FUTURE.

## Execution decisions

Implementation stayed inline with one independent final reviewer, rather than
per-task agents; no Astra. The requested single final commit replaces per-task
commits. Existing `.venv` packages were reused with `PYTHONPATH=src` selecting this
worktree; a clean-environment install was not checked. Private tokenizer data was
copied locally, not committed. This avoids installs but leaves environment drift
outside this verification. Custom `*.contexts/` directories are ignored for privacy;
a user-created directory with that suffix will also be ignored. The final review
uses the full uncommitted working-tree diff and new files because the one allowed
commit comes after review; there is no immutable intermediate commit range.

Final independent review found no Critical, Important or Minor issues and
independently reran all 94 tests, verifier self-check/counter assertions and
whitespace checks. Review boundaries: one Runtime owns a database; concurrent
owners remain unsupported. Universal model obedience and cache reuse on other
engines are not established by these measurements; rerun acceptance after changing
providers. These boundaries preserve the existing ownership contract and avoid
claiming guarantees the implementation cannot provide.
