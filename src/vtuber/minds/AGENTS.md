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

`omp.py` wraps the pinned official synchronous SDK off-loop; cancellation must join owned calls and confirm process exit before reconnect. `luna.py` strictly parses versioned JSON; `deep.md` is a role instruction, not a second identity. Disable tools/discovery and keep provider credentials out of diagnostics.

Optional traces capture actual rendered Fast prompts, Luna request/response and
text-visible OMP session context. Never recompile a newer snapshot for a historical
trace, capture auth headers or call a session view the exact provider request.
Opaque signatures, provider payloads and reasoning content are omitted.

M4.5 parses strict schema-v3 direct Markdown/summary/initiative. Validate types,
size and finite delay, not evidence or relevance. M4.7 supersedes the director role:
Bolt owns personality, preferences, speech and decisions. Luna organizes experience,
compaction and open threads without prescribing behavior. Bolt behavioral regressions
belong in separate fine-tuning, not corrective code or personality instructions.
Keep Markdown at the prompt tail. Initiative is a legacy experimental capability,
disabled and outside the M4.7 role contract. None preserves pending work; cancel
explicitly withdraws it. See docs/superpowers/specs/2026-11-16-m4-7-bolt-luna-roles.md.

## M6 opt-in Luna

`m6_context.py` projects complete native speech-tool calls and a small quoted,
untrusted sensor frame; no Bolt/Deep instructions. `luna_stream.py` uses the
minimal Bun/pi-ai bridge and a single active turn. M6 requires native
`speak` / `stay_silent`, not JSON-only prose or OMP coding-agent prompts.
Legacy adapters above remain untouched.
