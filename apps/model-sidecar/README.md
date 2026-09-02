# Lilavel model sidecar

This is a small long-lived direct model boundary for independent requests. It
discovers OMP authentication through `discoverAuthStorage`, selects the
bundled `openai-codex/gpt-5.6-luna` model, and invokes pi-ai's `streamSimple`
without an agent loop, tools, or provider session state.

The importable API is `createModelSidecar`. Call `start()` once, then call
`generate(prompt)` and consume the returned handle's `result` promise. Text is
made available immediately through the `text_delta` event sink. Call
`cancel(requestId)` to abort the active request and `close()` during shutdown.

The persistent protocol host is `bun run protocol`. It reads UTF-8 JSONL
commands from stdin and writes only version-one JSONL protocol events to
stdout. The supported commands are:

```json
{"protocol_version":1,"type":"generate","generation_id":"uuid","epoch":1,"prompt":"Reply exactly OK."}
{"protocol_version":1,"type":"cancel","generation_id":"uuid","epoch":1}
{"protocol_version":1,"type":"health"}
{"protocol_version":1,"type":"shutdown"}
```

The host emits `ready` before accepting generations, forwards genuine
incremental `text_delta` events, emits one terminal generation event, and
awaits provider cleanup before accepting the next generation. Core owns
generation lifecycle and semantic state; the host owns only provider and
process transport state.

For a local diagnostic run, use `bun run smoke -- "prompt"`. Its stdout is
diagnostic event JSON lines. It performs no login flow and does not print
credentials, request text, provider errors, headers, or tokens. The temporary
live probes are `bun run probe -- cancel-recovery` and `bun run probe -- isolation`;
both use the same sidecar process for their checks.
