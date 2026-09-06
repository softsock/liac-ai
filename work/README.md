# Execution continuity contract

`work/` stores compact execution state for substantial, bounded work items. It
helps work survive an agent, session, or context handoff without turning chat
history into a repository dependency.

`work/` is not permanent architecture truth, a backlog, an issue tracker, a
prompt archive, a chat transcript, or a chain-of-thought store. Repository code,
canonical documentation, and Git outrank stale work records. External research
is evidence, not automatic repository truth.

## Stable unit

The stable unit is the `WORK ITEM`. Agents, sessions, and context are
disposable. A branch or worktree is an execution location, not work-item
identity.

## When to create a work record

Create a record only for substantial work likely to span investigation,
implementation, validation, handoff, or multiple agent runs. A trivial fix or
docs-only edit does not need a record unless continuity value is real.

Use one record under `work/active/` for each substantial in-progress work item.
Do not create placeholder files merely to represent empty directories.

## Lifecycle states

Use exactly these statuses:

- `PROPOSED`
- `ACTIVE`
- `BLOCKED`
- `COMPLETED`
- `SUPERSEDED`
- `ABANDONED`

Do not add status vocabulary.

## Claim labels

Use these labels when applicable:

- `FACT`
- `DECISION`
- `PROPOSAL`
- `HYPOTHESIS`
- `RESULT`
- `OPEN_QUESTION`
- `UNKNOWN`

Do not add `TEMPORARY` as an epistemic label. Describe a temporary workaround
as a `FACT` or `DECISION` with an explicit removal or revisit condition. Empty
claim sections may be omitted; boilerplate placeholders are not required.

## Minimal active-record shape

Use a compact Markdown record. The following is an inline skeleton, not a
separate template file; omit optional sections and empty claims.

```markdown
# <ID> — <short title>

Status: PROPOSED | ACTIVE | BLOCKED | COMPLETED | SUPERSEDED | ABANDONED
Updated: YYYY-MM-DD
Repository / checkout: <repository and checkout identity>
Branch / worktree: <branch or worktree, when relevant>
Base commit: <commit>
Last checkpoint commit: <commit or none>

## Goal
<bounded outcome>

## Scope
- <owned paths and work included>

## Non-goals
- <explicit exclusions>

## Exit criteria
- <observable completion conditions>

## Current implementation state
<what is true now>

## Remaining work
- <unfinished in-scope work>

## Next safe action
<nearest reversible, in-scope continuation that needs no new consequential
decision>

## Validation
- <deterministic/live/platform-specific>: <PASS/FAIL/BLOCKED/UNVERIFIED> — <scope>

## Handoff
- Git/checkout state: <state and checkpoint>
- Uncommitted changes: <explicit state>
- Blockers/unknowns: <state>
- Next safe action: <one continuation>
```

Optional sections, only when needed, are `Why now`, `Target`, `Owner`, claim
sections, `Blockers`, and a research evidence capsule. `Owner` is not required;
when used, it means execution-scope ownership (the work item, worktree, or
owned paths), never model identity. Names such as Astra, Sol, or Luna do not
define work-item identity.

`Next safe action` is required for `ACTIVE` work. It is the nearest reversible,
in-scope continuation that does not require a new consequential decision. It is
not a 20-step micro-plan.

## Update policy

Update a record only at a material state transition:

- task start;
- a material fact or result is discovered;
- a decision is accepted;
- a blocker appears or clears;
- scope materially changes;
- checkpoint or handoff;
- closure.

Do not maintain a per-command or per-progress diary.

## Git and checkpoint semantics

Actual Git state always wins. For repository work, record the base commit and
last checkpoint commit. Call out uncommitted work explicitly at handoff; never
imply it is durable. A work record does not preserve uncommitted code.

## Validation semantics

Reuse the vocabulary in [`docs/VALIDATION.md`](../docs/VALIDATION.md):

- validation kinds are deterministic, live, and platform-specific;
- results are `PASS`, `FAIL`, `BLOCKED`, or `UNVERIFIED` where applicable;
- `BLOCKED` is neither `PASS` nor `FAIL`.

Task-specific results belong in the work record or an evidence artifact. Update
`docs/VALIDATION.md` only when the reusable validation contract itself changes.

## Research evidence capsule

When research materially informs a work item, use a compact capsule rather than
copying research chat into the repository:

```markdown
### Research evidence capsule
Question: <question>
Evidence:
- Source: <source>
  Access context: <date/context, when relevant>
  Exact claim supported: <claim>
Applicable finding for Lilavel/work item: <finding>
Limitations/unknowns: <limits>
Disposition: PROPOSAL | HYPOTHESIS | RESULT | UNKNOWN
```

## Promotion boundary

Promote execution knowledge only when it is durable and supported:

| Knowledge | Durable home |
| --- | --- |
| Current ownership or invariant | [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) |
| Current technology or provider role | [`docs/STACK.md`](../docs/STACK.md) |
| Reusable validation rule | [`docs/VALIDATION.md`](../docs/VALIDATION.md) |
| Consequential accepted decision | [`docs/decisions/`](../docs/decisions/) |
| Package behavior | Nearby package docs or tests |
| One-run or raw result | Runtime/evaluation artifact or work record |
| Transient plan, scratch, or unsupported rationale | Nowhere |

`PROPOSAL`, `HYPOTHESIS`, `UNVERIFIED`, and failed `RESULT` claims do not
silently become canonical decisions.

## Handoff rule

Before handoff, record at minimum:

- current Git and checkout state;
- last checkpoint;
- current implementation state;
- remaining work;
- blockers and unknowns;
- validation state;
- next safe action;
- any uncommitted changes.

An incoming agent must reconcile the record against actual Git state before
acting.

## Parallel and worktree rule

- One substantial work item gets one record.
- One record has one active writer or execution scope at a time.
- Parallel agents or worktrees use separate records and disjoint owned paths.
- Related records may link, but they do not share mutable status.
- Integration gets its own record only when integration has meaningful exit
  criteria.

## Closure and retention

Before marking a record `COMPLETED`:

- re-check actual repository state;
- satisfy the exit criteria;
- record validation precisely;
- mark missing checks `BLOCKED` or `UNVERIFIED`;
- reconcile claims;
- promote durable knowledge or explicitly state that none was promoted;
- record unresolved items;
- ensure handoff and checkpoint state is durable, or explicitly say it is not.

Retain only substantial completed records with useful execution provenance.
Compact them into closure capsules, not diaries. Trivial or zero-value work may
have no completed record; `work/completed/` must not become an archive dump.

## Fresh-agent bootstrap

For a new substantial task, inspect in this order:

1. Git preflight.
2. [`AGENTS.md`](../AGENTS.md).
3. [`README.md`](../README.md).
4. Relevant canonical docs: architecture, stack, validation, and applicable
   decisions.
5. This contract.
6. The matching active work record.
7. Scoped package docs, tests, and source needed for the next action.

For a narrow task, unrelated package docs or decisions may be skipped.
