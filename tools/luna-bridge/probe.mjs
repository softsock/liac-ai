import { spawn } from "node:child_process";
import { mkdir, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const provider = "openai-codex";
const modelId = "gpt-6-luna";
const authDir = new URL("../../.data/m6-auth/", import.meta.url);
const authDb = new URL("codex.sqlite", authDir);
const systemPrompt = "Choose one tool. Speak only through speak, or use stay_silent.";
const userText = "Please greet me with the words Hello from Luna.";
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

function report(fields) {
    console.log(JSON.stringify({ provider, model: modelId, ...fields }));
}

function fail(kind) {
    report({ status: "error", kind });
    process.exitCode = 1;
}

async function trial(streamSimple, model, apiKey, reasoning) {
    const start = performance.now();
    const elapsed = () => Math.round(performance.now() - start);
    let firstEventMs;
    let firstToolDeltaMs;
    let firstSpeakFragmentMs;
    let payload;
    const argsByIndex = new Map();
    const stream = streamSimple(model, {
        systemPrompt,
        messages: [{ role: "user", content: userText, timestamp: Date.now() }],
        tools,
    }, {
        apiKey,
        ...(reasoning === "off" ? { disableReasoning: true } : { reasoning }),
        maxTokens: 256,
        signal: AbortSignal.timeout(30_000),
        onPayload(body) {
            const input = Array.isArray(body.input) ? body.input : [];
            const texts = input.flatMap(item => (item.content ?? []).map(part => part.text));
            payload = {
                modelMatches: body.model === modelId,
                reasoningMatches: body.reasoning?.effort === (reasoning === "off" ? "none" : reasoning),
                promptMatches: JSON.stringify(texts) === JSON.stringify([systemPrompt, userText]),
                toolsMatch: JSON.stringify(body.tools?.map(tool => tool.name)) ===
                    JSON.stringify(tools.map(tool => tool.name)),
                inputItems: input.length,
            };
            if (!payload.modelMatches || !payload.reasoningMatches ||
                !payload.promptMatches || !payload.toolsMatch) {
                throw new Error("Unexpected probe request shape");
            }
        },
    });
    for await (const event of stream) {
        firstEventMs ??= elapsed();
        if (event.type === "toolcall_delta") {
            firstToolDeltaMs ??= elapsed();
            const index = event.contentIndex;
            const raw = (argsByIndex.get(index) ?? "") + event.delta;
            argsByIndex.set(index, raw);
            const call = event.partial.content[index];
            // shortcut: this measures plain ASCII probe text, use the full decoder for live dialogue.
            if (call?.name === "speak" && /"message"\s*:\s*"[A-Za-z]/.test(raw)) {
                firstSpeakFragmentMs ??= elapsed();
            }
        }
    }
    const final = await stream.result();
    const completedMs = elapsed();
    const calls = final.content.filter(item => item.type === "toolCall");
    const deltas = [...argsByIndex.values()];
    let parsed;
    if (deltas.length === 1) {
        try {
            parsed = JSON.parse(deltas[0]);
        } catch {}
    }
    const call = calls[0];
    const finalTool = ["speak", "stay_silent"].includes(call?.name) ? call.name : null;
    const passed = final.model === modelId && final.provider === provider && final.stopReason === "toolUse" && calls.length === 1 &&
        finalTool === "speak" && typeof call.id === "string" && call.id.length > 0 &&
        typeof parsed?.message === "string" && parsed.message.trim().length > 0 &&
        Object.keys(parsed).length === 1 && call.arguments?.message === parsed.message &&
        firstSpeakFragmentMs !== undefined && payload?.modelMatches &&
        payload.reasoningMatches && payload.promptMatches && payload.toolsMatch;
    const kind = final.stopReason === "error" ? "provider_error" : "stream_or_payload_mismatch";
    return {
        status: passed ? "ok" : "error",
        kind: passed ? undefined : kind,
        reasoning,
        firstEventMs,
        firstToolDeltaMs,
        firstSpeakFragmentMs,
        completedMs,
        finalTool,
        argumentsMatch: typeof parsed?.message === "string" && call?.arguments?.message === parsed.message,
        payload,
        usage: final.usage && {
            input: final.usage.input,
            output: final.usage.output,
            cacheRead: final.usage.cacheRead,
            cacheWrite: final.usage.cacheWrite,
        },
    };
}

const args = process.argv.slice(2).join(" ");
if (!["--list", "--login", "--reasoning low", "--reasoning off"].includes(args)) {
    console.error("Usage: probe.mjs --list | --login | --reasoning low | --reasoning off");
    process.exit(2);
}

let stage = "dependency_load";
let storage;
try {
    process.env.PI_CODING_AGENT_DIR = fileURLToPath(authDir);
    delete process.env.PI_REQ_DEBUG;
    // pi-ai 18.22.1 uses this guard to suppress automatic 400/413 request dumps.
    process.env.PI_TEST_RUNTIME = "1";
    const { AuthStorage, streamSimple } = await import("@oh-my-pi/pi-ai");
    const { fetchCodexModels, getBundledModels, getSupportedEfforts } = await import("@oh-my-pi/pi-catalog");
    stage = "catalog_lookup";
    const model = getBundledModels(provider).find(item => item.id === modelId);
    if (!model) {
        fail("model_missing_from_bundled_catalog");
    } else if (args === "--list") {
        report({ status: "ok", source: "bundled_catalog", efforts: getSupportedEfforts(model) });
    } else if (args !== "--login" && !(await stat(authDb).then(() => true, () => false))) {
        fail("isolated_oauth_missing_run_login");
    } else {
        stage = "auth_storage";
        await mkdir(authDir, { recursive: true, mode: 0o700 });
        storage = await AuthStorage.create(fileURLToPath(authDb));
        if (args === "--login") {
            stage = "oauth_login";
            const identity = await storage.oauth.login(provider, {
                signal: AbortSignal.timeout(120_000),
                onAuth({ launchUrl }) {
                    if (!launchUrl || !/^http:\/\/(localhost|127\.0\.0\.1):1455\//.test(launchUrl)) {
                        throw new Error("Missing OAuth loopback launch URL");
                    }
                    const browser = spawn("rundll32.exe", ["url.dll,FileProtocolHandler", launchUrl], {
                        stdio: "ignore",
                        windowsHide: true,
                    });
                    browser.on("error", () => fail("browser_launch_failed"));
                    browser.unref();
                    report({ status: "waiting_for_browser_login" });
                },
                // AuthStorage otherwise races the browser callback against its paste prompt.
                onManualCodeInput: () => new Promise(() => {}),
                onPrompt: async () => { throw new Error("Unexpected OAuth prompt"); },
            });
            if (identity?.type === "oauth") {
                report({ status: "oauth_stored" });
            } else {
                fail("oauth_not_stored");
            }
        } else {
            stage = "oauth_access";
            await storage.credentials.reload();
            const auth = await storage.oauth.access(provider);
            if (!auth) {
                fail("isolated_oauth_missing_run_login");
            } else {
                stage = "live_model_discovery";
                let liveEfforts;
                const discovery = await fetchCodexModels({
                    accessToken: auth.accessToken,
                    accountId: auth.accountId,
                    signal: AbortSignal.timeout(15_000),
                    async fetchFn(url, options) {
                        const response = await fetch(url, options);
                        if (response.ok) {
                            const body = await response.clone().json().catch(() => null);
                            const rows = body?.models ?? body?.data;
                            const entry = Array.isArray(rows) &&
                                rows.find(row => (row?.slug ?? row?.id) === modelId);
                            const levels = entry?.supported_reasoning_levels;
                            if (Array.isArray(levels)) {
                                liveEfforts = ["off", "none", "minimal", "low", "medium", "high", "xhigh", "max"]
                                    .filter(effort => levels.some(level => level?.effort === effort));
                            }
                        }
                        return response;
                    },
                });
                report({
                    status: "live_discovery",
                    httpStatus: discovery?.rejectedStatus,
                    exactModelListed: discovery?.models.some(item => item.id === modelId),
                    efforts: liveEfforts,
                });
                if (discovery && !discovery.models.some(item => item.id === modelId)) {
                    fail("model_missing_from_live_catalog");
                } else if (args === "--reasoning off" &&
                    !liveEfforts?.some(effort => effort === "off" || effort === "none")) {
                    fail("off_not_advertised");
                } else {
                    stage = "tool_stream";
                    const reasoning = args === "--reasoning off" ? "off" : "low";
                    for (let index = 1; index <= 5; index++) {
                        const result = await trial(streamSimple, model, auth.accessToken, reasoning);
                        report({ trial: index, ...result });
                        if (result.status !== "ok") process.exitCode = 1;
                    }
                }
            }
        }
    }
} catch (error) {
    if (stage === "dependency_load" && error.code === "ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING") {
        fail("pi_ai_requires_bun");
    } else {
        fail(stage);
    }
} finally {
    storage?.close();
}
