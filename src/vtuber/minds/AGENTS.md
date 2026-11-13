# Minds

Own adapter-specific generation only. Depend on contracts, the pure ContextCompiler,
HTTPX and standard-library helpers, never runtime, SQLite or CLI. Fast streams strings; Deep returns typed
proposals. Adapters receive immutable data and must release resources on asyncio
cancellation. Nemotron uses raw stateless completions and the verified text-only
checkpoint template: thinking off, conversational mode on. Do not replace this
with unverified request flags. Keep control/reasoning markers out of speech,
including across chunk boundaries; require terminal SSE frames. `character.md`
is the single authored identity. Fakes do not establish provider compatibility.
`nemotron.py` owns the shared renderer and optional local tokenizer. Never use
network tokenization per turn or silently fall back to a heuristic for real Fast.
The pinned GGUF adds BOS; wire prompts omit it and local counts add it exactly once.
Verify provider/local parity at startup; a later usage mismatch latches generation
off until revalidation. Do not bundle tokenizer assets or require tokenizers in fake mode.

`omp.py` wraps the pinned official synchronous SDK off-loop; cancellation must join owned calls and confirm process exit before reconnect. `luna.py` strictly parses schema v2, including bounded attention proposals; `deep.md` is a role instruction, not a second identity. Disable tools/discovery and keep provider credentials out of diagnostics.

Luna decides semantic relevance; do not add keyword rules. Empty attention is normal.
Targets/supersession must reference captured signals, keeping kind and version;
Runtime assigns IDs/status/time. Notes cannot be an alternate beat execution path.

Optional traces capture actual rendered Fast prompts, Luna request/response and
text-visible OMP session context. Never recompile a newer snapshot for a historical
trace, capture auth headers or call a session view the exact provider request.
Opaque signatures, provider payloads and reasoning content are omitted.
