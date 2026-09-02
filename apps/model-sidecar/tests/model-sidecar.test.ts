import { afterEach, describe, expect, test } from "bun:test";
import type { ApiKeyResolver, AssistantMessage, AssistantMessageEvent, Context, Model, SimpleStreamOptions } from "@oh-my-pi/pi-ai";
import {
  createModelSidecar,
  type AuthStorageLike,
  type SidecarEvent,
  type SidecarModel,
  type StreamSimple,
} from "../src/index.js";

const model = {
  id: "gpt-5.6-luna",
  provider: "openai-codex",
  api: "openai-codex-responses",
  baseUrl: "https://example.invalid",
} as SidecarModel;

function event(type: "start" | "text_delta" | "done", delta = ""): AssistantMessageEvent {
  if (type === "text_delta") return { type, contentIndex: 0, delta, partial: {} as AssistantMessage };
  if (type === "done") return { type, reason: "stop", message: {} as AssistantMessage };
  return { type, partial: {} as AssistantMessage };
}

class FakeAuth implements AuthStorageLike {
  resolverCalls: Array<{ provider: string; options?: Parameters<AuthStorageLike["resolver"]>[1] }> = [];
  resolverContexts: Array<{ lastChance: boolean; error: unknown }> = [];
  closed = false;

  resolver(provider: string, options?: Parameters<AuthStorageLike["resolver"]>[1]): ApiKeyResolver {
    this.resolverCalls.push({ provider, options });
    return async (context) => {
      this.resolverContexts.push({ lastChance: context.lastChance, error: context.error });
      return "test-bearer";
    };
  }

  close() {
    this.closed = true;
  }
}

function makeStream(factory: (context: Context, options?: SimpleStreamOptions) => AsyncIterable<AssistantMessageEvent>): StreamSimple {
  return ((_: Model<"openai-codex-responses">, context, options) => factory(context, options)) as StreamSimple;
}

const openHandles: Array<{ close: () => Promise<void> }> = [];
afterEach(async () => {
  while (openHandles.length) await openHandles.pop()?.close();
});

describe("ModelSidecar", () => {
  test("loads and validates the exact bundled Luna model", async () => {
    const sidecar = createModelSidecar({
      auth: new FakeAuth(),
      stream: makeStream(async function* () {
        yield event("done");
      }),
    });

    await sidecar.start();
    expect(sidecar.model).toMatchObject({
      id: "gpt-5.6-luna",
      provider: "openai-codex",
      api: "openai-codex-responses",
    });
    await sidecar.close();
  });

  test("starts, correlates one request, and closes auth", async () => {
    const auth = new FakeAuth();
    const events: SidecarEvent[] = [];
    const sidecar = createModelSidecar({
      auth,
      model,
      stream: makeStream(async function* () {
        yield event("start");
        yield event("text_delta", "first");
        yield event("text_delta", " second");
        yield event("done");
      }),
      onEvent: (item) => events.push(item),
    });
    openHandles.push(sidecar);

    await sidecar.start();
    const handle = sidecar.generate("private prompt must not be in events");
    const result = await handle.result;

    expect(result).toEqual({ requestId: handle.requestId, status: "completed", text: "first second" });
    expect(events.map((item) => item.type)).toEqual([
      "ready",
      "request_received",
      "provider_dispatch",
      "provider_first_event",
      "text_delta",
      "text_delta",
      "completed",
    ]);
    expect(new Set(events.filter((item) => item.requestId).map((item) => item.requestId))).toEqual(new Set([handle.requestId]));
    expect(events.find((item) => item.type === "text_delta" && item.delta === "first")).toBeDefined();

    await sidecar.close();
    expect(auth.closed).toBe(true);
  });

  test("passes genuine deltas before completion instead of buffering final text", async () => {
    let releaseSecond: (() => void) | undefined;
    const second = new Promise<void>((resolve) => {
      releaseSecond = resolve;
    });
    const observed: SidecarEvent[] = [];
    const sidecar = createModelSidecar({
      auth: new FakeAuth(),
      model,
      stream: makeStream(async function* () {
        yield event("text_delta", "now");
        await second;
        yield event("text_delta", " later");
        yield event("done");
      }),
      onEvent: (item) => observed.push(item),
    });
    openHandles.push(sidecar);
    await sidecar.start();
    const handle = sidecar.generate("streaming");

    while (!observed.some((item) => item.type === "text_delta" && item.delta === "now")) await Promise.resolve();
    expect(observed.some((item) => item.type === "completed")).toBe(false);
    expect(observed.filter((item) => item.type === "text_delta").map((item) => item.delta)).toEqual(["now"]);

    releaseSecond?.();
    await handle.result;
    expect(observed.filter((item) => item.type === "text_delta").map((item) => item.delta)).toEqual(["now", " later"]);
  });

  test("cancels the active request and recovers ready state", async () => {
    let attempts = 0;
    let releaseCleanup: (() => void) | undefined;
    let cleanupFinished = false;
    const cleanupGate = new Promise<void>((resolve) => {
      releaseCleanup = resolve;
    });
    const sidecar = createModelSidecar({
      auth: new FakeAuth(),
      model,
      stream: makeStream(async function* (_context, options) {
        if (attempts++ === 0) {
          try {
            await new Promise<void>((resolve) => options?.signal?.addEventListener("abort", () => resolve(), { once: true }));
            return;
          } finally {
            await cleanupGate;
            cleanupFinished = true;
          }
        }
        yield event("text_delta", "recovered");
        yield event("done");
      }),
    });
    openHandles.push(sidecar);
    await sidecar.start();
    const cancelled = sidecar.generate("cancel me");
    expect(sidecar.cancel(cancelled.requestId)).toBe(true);
    await Promise.resolve();
    expect(sidecar.state).toBe("busy");
    releaseCleanup?.();
    await expect(cancelled.result).resolves.toMatchObject({ status: "cancelled", text: "" });
    expect(cleanupFinished).toBe(true);
    expect(sidecar.state).toBe("ready");

    const retry = sidecar.generate("try again");
    await expect(retry.result).resolves.toMatchObject({ status: "completed", text: "recovered" });
    expect(sidecar.state).toBe("ready");
  });

  test("uses the auth resolver boundary and omits tools and provider session state", async () => {
    const auth = new FakeAuth();
    let capturedContext: Context | undefined;
    let capturedOptions: SimpleStreamOptions | undefined;
    const sidecar = createModelSidecar({
      auth,
      model,
      stream: makeStream(async function* (context, options) {
        capturedContext = context;
        capturedOptions = options;
        if (!options) throw new Error("test stream options missing");
        const optionsForTest = options;
        const resolver = optionsForTest?.apiKey;
        if (typeof resolver === "function") {
          await resolver({ lastChance: false, error: undefined, signal: optionsForTest.signal });
          await resolver({ lastChance: true, error: new Error("simulated auth failure"), signal: optionsForTest.signal });
        }
        yield event("text_delta", "ok");
        yield event("done");
      }),
    });
    openHandles.push(sidecar);
    await sidecar.start();
    const handle = sidecar.generate("auth boundary");
    await handle.result;

    expect(Object.hasOwn(capturedContext ?? {}, "tools")).toBe(false);
    expect(capturedContext?.messages).toHaveLength(1);
    expect(Object.hasOwn(capturedOptions ?? {}, "statefulResponses")).toBe(false);
    expect(Object.hasOwn(capturedOptions ?? {}, "sessionId")).toBe(false);
    expect(Object.hasOwn(capturedOptions ?? {}, "providerSessionState")).toBe(false);
    expect(capturedOptions?.preferWebsockets).toBe(false);
    expect(auth.resolverCalls).toEqual([
      { provider: "openai-codex", options: { sessionId: handle.requestId, modelId: "gpt-5.6-luna", baseUrl: "https://example.invalid" } },
    ]);
    expect(auth.resolverContexts.map(({ lastChance }) => lastChance)).toEqual([false, true]);
  });

  test("records latency marks in causal order", async () => {
    let now = 100;
    const observed: SidecarEvent[] = [];
    const sidecar = createModelSidecar({
      auth: new FakeAuth(),
      model,
      now: () => now,
      stream: makeStream(async function* () {
        now = 120;
        yield event("text_delta", "timed");
        now = 140;
        yield event("done");
      }),
      onEvent: (item) => observed.push(item),
    });
    openHandles.push(sidecar);
    await sidecar.start();
    await sidecar.generate("latency").result;

    const finalEvent = observed.find((item) => item.type === "completed");
    expect(finalEvent?.metadata.marks).toMatchObject({
      requestReceived: 0,
      providerDispatch: 0,
      providerFirstEvent: 20,
      firstNonEmptyDelta: 20,
      completion: 40,
    });
    const marks = finalEvent?.metadata.marks;
    expect(marks?.requestReceived).toBeLessThanOrEqual(marks?.providerDispatch ?? -1);
    expect(marks?.providerDispatch).toBeLessThanOrEqual(marks?.providerFirstEvent ?? -1);
    expect(marks?.providerFirstEvent).toBeLessThanOrEqual(marks?.firstNonEmptyDelta ?? -1);
    expect(marks?.firstNonEmptyDelta).toBeLessThanOrEqual(marks?.completion ?? -1);
  });
});
