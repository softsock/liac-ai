# Contracts

Own frozen envelopes, snapshots, typed proposals and Fast/Deep/output ports.
Import only the standard library and sibling contracts. No SQLite, CLI or model
clients. Payload JSON is immutable; `Event.payload` returns a fresh decoded copy.
Fast ports return closeable async generators and cooperate with cancellation.
