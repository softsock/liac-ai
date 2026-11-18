import { stat } from "node:fs/promises";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

import { completedArguments, SpeakStream } from "./speak_stream.mjs";

const provider = "openai-codex";
const modelId = "gpt-6-luna";
const authDir = new URL("../../.data/m6-auth/", import.meta.url);
process.env.PI_CODING_AGENT_DIR = fileURLToPath(authDir);
delete process.env.PI_REQ_DEBUG;
// pi-ai 18.22.1 uses this guard to suppress automatic 400/413 request dumps.
process.env.PI_TEST_RUNTIME = "1";

const tools = [
    {
        name: "speak",
        description: "Say a short message.",
        parameters: {
            type: "object",
            properties: { message: { type: "string" } },
            required: ["message"],
            additionalProperties: false,
        },
    },
    {
        name: "stay_silent",
        description: "Say nothing.",
        parameters: { type: "object", properties: {}, additionalProperties: false },
    },
];

function send(id, type, fields) {
    process.stdout.write(JSON.stringify({ id, type, ...fields }) + "\n");
}

async function run() {
    const { AuthStorage, streamSimple } = await import("@oh-my-pi/pi-ai");
    const { getBundledModel } = await import("@oh-my-pi/pi-catalog");
    const model = getBundledModel(provider, modelId);
    const db = new URL("codex.sqlite", authDir);
    const auth = await stat(db).then(() => AuthStorage.create(fileURLToPath(db)), () => null);
    let active;
    try {
        await auth?.credentials.reload();
        const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
        try {
            for await (const line of input) {
                if (Buffer.byteLength(line) >= 65_536) break;
                const frame = JSON.parse(line);
                if (frame.type === "shutdown") break;
                if (frame.type === "cancel" && frame.id === active?.id) active.controller.abort();
                if (frame.type !== "turn") continue;
                if (active) {
                    if (frame.id !== active.id) send(frame.id, "error", { kind: "busy" });
                    continue;
                }
                if (frame.reasoning !== "low" || typeof frame.system !== "string" ||
                    !Array.isArray(frame.messages) || typeof frame.id !== "string") {
                    send(frame.id, "error", { kind: "invalid_request" });
                    continue;
                }
                const controller = new AbortController();
                active = {
                    id: frame.id,
                    controller,
                    task: turn(frame, controller.signal).finally(() => { active = undefined; }),
                };
            }
        } finally {
            input.close();
            active?.controller.abort();
            await active?.task;
        }
    } finally {
        auth?.close();
    }

    async function turn(frame, cancelled) {
        const { id, system, messages } = frame;
        const signal = AbortSignal.any([cancelled, AbortSignal.timeout(30_000)]);
        const start = performance.now();
        const elapsed = () => Math.round(performance.now() - start);
        const timings = {};
        let errorKind = "oauth_unavailable";
        try {
            const oauth = await auth?.oauth.access(provider, undefined, { signal });
            if (!oauth) throw new Error("OAuth unavailable");
            signal.throwIfAborted();
            errorKind = "provider_error";
            const fragments = new SpeakStream();
            let completed;
            const stream = streamSimple(model, { systemPrompt: system, messages, tools }, {
                apiKey: oauth.accessToken,
                reasoning: "low",
                maxTokens: 256,
                hideThinkingSummary: true,
                toolChoice: "required",
                signal,
                onPayload(payload) {
                    if (payload.model !== modelId || payload.reasoning?.effort !== "low") {
                        errorKind = "request_mismatch";
                        throw new Error("Unexpected Luna request");
                    }
                },
            });
            for await (const event of stream) {
                signal.throwIfAborted();
                timings.first_event_ms ??= elapsed();
                if (event.type === "toolcall_delta") {
                    timings.first_tool_delta_ms ??= elapsed();
                    const index = event.contentIndex;
                    const name = event.partial.content[index]?.name;
                    const text = fragments.push(index, name, event.delta);
                    if (text) {
                        timings.first_speak_fragment_ms ??= elapsed();
                        send(id, "speak_delta", { text });
                    }
                } else if (event.type === "toolcall_end") {
                    completed = event;
                }
            }
            const final = await stream.result();
            signal.throwIfAborted();
            if (final.stopReason === "error") throw new Error("Luna request failed");
            errorKind = "invalid_tool_call";
            const calls = final.content.filter(item => item.type === "toolCall");
            const call = calls[0];
            if (final.stopReason !== "toolUse" || calls.length !== 1 ||
                !completed || !call.id || call.id !== completed.toolCall.id ||
                call.name !== completed.toolCall.name || final.model !== modelId ||
                final.provider !== provider) throw new Error("Expected one completed Luna tool call");
            const args = completedArguments(call.name, fragments.raw(completed.contentIndex), call.arguments);
            if (!args) throw new Error("Invalid Luna tool arguments");
            timings.completed_ms = elapsed();
            const { input, output, cacheRead, cacheWrite } = final.usage;
            send(id, "result", {
                action: call.name,
                message: args.message ?? "",
                tool_call_id: call.id,
                usage: { input, output, cacheRead, cacheWrite },
                timings,
            });
        } catch {
            send(id, "error", { kind: cancelled.aborted ? "cancelled" : errorKind });
        }
    }
}

run().catch(() => { process.exitCode = 1; });
