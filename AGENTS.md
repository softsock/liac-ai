# Lilavel Development Contract

## Project

Lilavel is a communication-first AI system. Natural, responsive text interaction is the current primary product priority.

Do not invent requirements for areas that are not yet defined by the repository. The long-term AI-character/streamer direction is context, not a current implementation specification.

## Authority and scope

- Tracked repository contents and Git history are authoritative. Reconstructed chat logs are secondary leads, not historical evidence.
- Never invent requirements or historical rationale; use `UNKNOWN` when the repository and approved evidence do not support a claim.
- Core owns implemented semantic conversation state and boundaries. The provider/model sidecar owns provider/process transport; Discord is a replaceable transport/presentation edge.
- Do not infer future streamer requirements from product direction. Implement only requirements established by the current repository, an approved work plan, or an explicit human decision.

## Repository Authority

This repository's implementation and documentation are authoritative. External projects may inform consequential decisions, but their architecture and assumptions do not automatically apply to Lilavel.

## Research and Multi-Agent Work

For consequential decisions involving model providers, inference transports, streaming protocols, or external runtimes, verify the relevant behavior with targeted research or a controlled experiment before committing to architecture. Use multiple agents only when independent investigation or verification materially reduces uncertainty.

When agents modify files concurrently, their ownership must not overlap.

## Secrets

Never place credentials, OAuth tokens, API keys, service tokens, cookies, or other secrets in:

- source code;
- prompts;
- committed configuration;
- test fixtures;
- logs;
- documentation.

Use only the supported authentication mechanism or auth-discovery boundary of the relevant provider or runtime.

Never manually extract, copy, replay, persist, or expose authentication material merely to simplify an integration.

## Git

Inspect the worktree before making changes.

Agents normally commit completed, validated task work unless the task explicitly requires an uncommitted result.

Before committing:

- review the final diff;
- run the relevant validation;
- ensure the commit contains only work belonging to the completed task.

If the worktree already contains changes before a new task begins:

- if they clearly belong to a completed previous task, validate and commit them as a checkpoint before starting new work;
- never sweep ambiguous, unrelated, incomplete, or user-owned changes into a commit.

Stage only task-owned files.

## Verification

Do not report a validation step as passing unless it was actually executed. Use the repository's authoritative validation commands once they exist; do not substitute guessed tooling. Reports should distinguish verified results from remaining uncertainty.

The model-sidecar protocol host reserves stdout for version-two JSONL frames. Human-readable diagnostics must use stderr so they cannot corrupt protocol framing.

Distinguish deterministic, live/provider-dependent, platform-specific, `BLOCKED`, and unverified validation. `BLOCKED` is neither `PASS` nor `FAIL`.

## Navigation

- [Architecture](docs/ARCHITECTURE.md) — current ownership, flows, and invariants.
- [Stack](docs/STACK.md) — current technology roles.
- [Validation](docs/VALIDATION.md) — package checks, live checks, and result semantics.
- [Decisions](docs/decisions/) — the five current architectural decisions.
- Scoped package contracts: [Core](apps/core/README.md), [model sidecar](apps/model-sidecar/README.md), and [Discord edge](apps/discord-edge/README.md).
- [Execution continuity](work/README.md) — substantial in-progress work uses this contract and a record under `work/active/` when such work exists; records are execution state and never override current Git or canonical docs. Do not duplicate the schema here.

## Maintaining This File

Keep this file limited to recurring, Lilavel-specific rules. Move substantial subsystem-specific guidance to a nearby scoped `AGENTS.md` instead of expanding this file indefinitely.
