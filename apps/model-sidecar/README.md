# Lilavel model sidecar

This is a small long-lived direct model boundary for independent diagnostic
requests. It discovers OMP authentication through `discoverAuthStorage`,
selects the bundled `openai-codex/gpt-5.6-luna` model, and invokes pi-ai's
`streamSimple` without an agent loop, tools, or provider session state.

The importable API is `createModelSidecar`. Call `start()` once, then call
`generate(prompt)` and consume the returned handle's `result` promise. Text is
made available immediately through the `text_delta` event sink. Call
`cancel(requestId)` to abort the active request and `close()` during shutdown.

For a local diagnostic run, use `bun run smoke -- "prompt"`. Its stdout is
structured event JSON lines. It performs no login flow and does not print
credentials, request text, provider errors, headers, or tokens. The temporary
live probes are `bun run probe -- cancel-recovery` and `bun run probe -- isolation`;
both use the same sidecar process for their checks.
