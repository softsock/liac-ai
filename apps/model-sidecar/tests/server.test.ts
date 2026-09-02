import { describe, expect, test } from "bun:test";
import type { ApiKeyResolver, AssistantMessage, AssistantMessageEvent, Context, Model, SimpleStreamOptions } from "@oh-my-pi/pi-ai";
import {
  createModelSidecar,
  type AuthStorageLike,
  type SidecarEvent,
  type SidecarModel,
  type StreamSimple,
} from "../src/index.js";
import { ProtocolServer, type ProtocolOutput } from "../src/server.js";

const model = {
  id: "gpt-5.6-luna",
  provider: "openai-codex",
  api: "openai-codex-responses",
  baseUrl: "https://example.invalid",
} as SidecarModel;

function providerEvent(type: "text_delta" | "done", delta = ""): AssistantMessageEvent {
  if (type === "text_delta") return { type, contentIndex: 0, delta, partial: {} as AssistantMessage };
  return { type, reason: "stop", message: {} as AssistantMessage };
}

class FakeAuth implements AuthStorageLike {
  resolver(_provider: string, _options?: Parameters<AuthStorageLike["resolver"]>[1]): ApiKeyResolver {
    return async () => "test-bearer";
  }

  close(): void {}
}

function makeStream(
  factory: (context: Context, options?: SimpleStreamOptions) => AsyncIterable<AssistantMessageEvent>,
): StreamSimple {
  return ((_: Model<"openai-codex-responses">, context, options) => factory(context, options)) as StreamSimple;
}

class InputQueue {
  readonly stream: ReadableStream<Uint8Array>;
  readonly #encoder = new TextEncoder();
  #controller: ReadableStreamDefaultController<Uint8Array> | undefined;

  constructor() {
    this.stream = new ReadableStream<Uint8Array>({
      start: (controller) => {
        this.#controller = controller;
      },
    });
  }

  push(value: string): void {
    this.#controller?.enqueue(this.#encoder.encode(`${value}\n`));
  }
}

class CaptureOutput implements ProtocolOutput {
  readonly chunks: string[] = [];

  write(chunk: string): boolean {
    this.chunks.push(chunk);
    return true;
  }

  once(_event: "drain", listener: () => void): unknown {
    listener();
    return this;
  }

  frames(): Array<Record<string, unknown>> {
    return this.chunks.map((chunk) => JSON.parse(chunk) as Record<string, unknown>);
  }
}

function command(type: "generate" | "cancel", generationId: string, epoch: number, prompt?: string): string {
  if (type === "generate") {
    return JSON.stringify({ protocol_version: 1, type, generation_id: generationId, epoch, prompt });
  }
  return JSON.stringify({ protocol_version: 1, type, generation_id: generationId, epoch });
}

test("protocol server performs ready, genuine streaming, cancellation, recovery, and shutdown", async () => {
  const input = new InputQueue();
  const output = new CaptureOutput();
  let cancelledCommandSent = false;
  let recoveryCommandSent = false;
  const server = new ProtocolServer({
    input: input.stream,
    output,
    createSidecar: (onEvent) =>
      createModelSidecar({
        auth: new FakeAuth(),
        model,
        stream: makeStream(async function* (context, options) {
          const prompt = context.messages[0]?.content;
          if (typeof prompt !== "string" || prompt === "cancel") {
            yield providerEvent("text_delta", "before-cancel");
            await new Promise<void>((resolve) => {
              if (options?.signal?.aborted) resolve();
              else options?.signal?.addEventListener("abort", () => resolve(), { once: true });
            });
            return;
          }
          yield providerEvent("text_delta", "recovered");
          yield providerEvent("done");
        }),
        onEvent: (event) => {
          onEvent(event);
          if (event.type === "text_delta" && event.delta === "before-cancel" && !cancelledCommandSent) {
            cancelledCommandSent = true;
            input.push(command("cancel", event.requestId ?? "", event.epoch ?? 0));
          }
          if (event.type === "cancelled" && !recoveryCommandSent) {
            recoveryCommandSent = true;
            input.push(command("generate", "recovery", (event.epoch ?? 0) + 1, "recovery"));
          }
          if (event.type === "completed" && event.requestId === "recovery") {
            input.push(JSON.stringify({ protocol_version: 1, type: "shutdown" }));
          }
        },
      }),
  });

  input.push(command("generate", "first", 1, "cancel"));
  const exitCode = await server.run();
  const frames = output.frames();

  expect(exitCode).toBe(0);
  expect(frames.map((frame) => frame.type)).toEqual([
    "ready",
    "accepted",
    "text_delta",
    "cancelled",
    "accepted",
    "text_delta",
    "completed",
    "shutdown",
  ]);
  expect(frames.filter((frame) => frame.type === "text_delta").map((frame) => frame.delta)).toEqual([
    "before-cancel",
    "recovered",
  ]);
  expect(frames.filter((frame) => frame.type === "accepted").map((frame) => frame.generation_id)).toEqual([
    "first",
    "recovery",
  ]);
});

test("protocol server reports malformed input without hanging or corrupting stdout", async () => {
  const input = new InputQueue();
  const output = new CaptureOutput();
  const server = new ProtocolServer({
    input: input.stream,
    output,
    createSidecar: (onEvent) => createModelSidecar({ auth: new FakeAuth(), model, onEvent }),
  });
  input.push("not-json");

  const exitCode = await server.run();
  expect(exitCode).toBe(1);
  expect(output.frames()).toEqual([
    { protocol_version: 1, type: "ready", provider: "openai-codex", model_id: "gpt-5.6-luna", api: "openai-codex-responses" },
    { protocol_version: 1, type: "failed", code: "protocol_error" },
  ]);
});

test("protocol server fails startup when the sidecar omits the ready handshake", async () => {
  const output = new CaptureOutput();
  const server = new ProtocolServer({
    input: new InputQueue().stream,
    output,
    createSidecar: () =>
      createModelSidecar({
        auth: new FakeAuth(),
        model,
        onEvent: () => undefined,
      }),
  });

  expect(await server.run()).toBe(1);
  expect(output.frames()).toEqual([{ protocol_version: 1, type: "failed", code: "startup_error" }]);
});
