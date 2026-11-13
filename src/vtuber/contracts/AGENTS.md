# Contracts

Own frozen envelopes, snapshots, typed proposals and Fast/Deep/output ports.
Import only the standard library and sibling contracts. No SQLite, CLI or model
clients. Payload JSON is immutable; `Event.payload` returns a fresh decoded copy.
Fast ports return closeable async generators and cooperate with cancellation.
Context epochs and compaction proposals are frozen, separate from note revisions.
Snapshots include terminal turn boundaries so cancelled turns can be compacted
without retaining partial speech. Future summary sources prove provenance only.

`deep.py` defines versioned DeepRequest/DeepResult/DeepDecision. The Runtime assigns operation IDs and dependency metadata; models supply only note/summary data and evidence IDs.

M4.2 keeps legacy `context_note`/`note` names for the whole Markdown document.
DeepRequest carries the configured token cap; null preserves, empty clears, and
identical replacement is a no-op. Authority fields remain runtime-owned.

M4.3 appends optional initiative fields and accepts v1/v2 Deep envelopes.
`InitiativeProposal` carries bounded intent/reason/evidence; `InitiativeCancel`
explicitly withdraws. Null/none preserves. `FastInput` distinguishes real user
messages from `CharacterInitiative`; only completed speech becomes dialogue.
