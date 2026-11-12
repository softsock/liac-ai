# Contracts

Own frozen envelopes, snapshots, typed proposals and Fast/Deep/output ports.
Import only the standard library and sibling contracts. No SQLite, CLI or model
clients. Payload JSON is immutable; `Event.payload` returns a fresh decoded copy.
Fast ports return closeable async generators and cooperate with cancellation.
Context epochs and compaction proposals are frozen, separate from note revisions.
Snapshots include terminal turn boundaries so cancelled turns can be compacted
without retaining partial speech. Future summary sources prove provenance only.

`deep.py` defines versioned DeepRequest/DeepResult/DeepDecision. The Runtime assigns operation IDs and dependency metadata; models supply only note/summary data and evidence IDs.
