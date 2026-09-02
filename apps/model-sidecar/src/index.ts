import { randomUUID } from "node:crypto";
import {
  streamSimple,
  type ApiKeyResolver,
  type AssistantMessageEvent,
  type Context,
  type Message,
  type Model,
  type SimpleStreamOptions,
} from "@oh-my-pi/pi-ai";
import { discoverAuthStorage } from "@oh-my-pi/pi-ai/auth-broker";
import { getBundledModel } from "@oh-my-pi/pi-catalog";

const PROVIDER = "openai-codex";
const MODEL_ID = "gpt-5.6-luna";
const API = "openai-codex-responses";

export type SidecarState = "new" | "starting" | "ready" | "busy" | "failed" | "closed";

export interface AuthStorageLike {
  resolver(
    provider: string,
    options?: { sessionId?: string; modelId?: string; baseUrl?: string },
  ): ApiKeyResolver;
  close(): void;
}

export type SidecarModel = Model<"openai-codex-responses">;

export type StreamSimple = (
  model: SidecarModel,
  context: Context,
  options?: SimpleStreamOptions,
) => AsyncIterable<AssistantMessageEvent>;

export interface LatencyMarks {
  requestReceived?: number;
  providerDispatch?: number;
  providerFirstEvent?: number;
  firstNonEmptyDelta?: number;
  completion?: number;
  cancellation?: number;
}

export interface SidecarEventMetadata {
  marks: LatencyMarks;
  modelId?: string;
  provider?: string;
  api?: string;
}

interface SidecarEventBase {
  requestId?: string;
  atMs: number;
  metadata: SidecarEventMetadata;
}

export type SidecarEvent =
  | (SidecarEventBase & { type: "ready" })
  | (SidecarEventBase & { type: "request_received" })
  | (SidecarEventBase & { type: "provider_dispatch" })
  | (SidecarEventBase & { type: "provider_first_event"; providerEventType: AssistantMessageEvent["type"] })
  | (SidecarEventBase & { type: "text_delta"; delta: string })
  | (SidecarEventBase & { type: "completed"; textLength: number })
  | (SidecarEventBase & { type: "cancelled" })
  | (SidecarEventBase & { type: "error"; code: SidecarErrorCode });

export type SidecarErrorCode =
  | "busy"
  | "not_ready"
  | "closed"
  | "startup_error"
  | "provider_error"
  | "unsupported_output"
  | "cancelled";

export interface GenerationResult {
  requestId: string;
  status: "completed" | "cancelled";
  text: string;
}

export interface GenerationHandle {
  requestId: string;
  result: Promise<GenerationResult>;
}

export interface ModelSidecarOptions {
  auth?: AuthStorageLike;
  discoverAuth?: () => Promise<AuthStorageLike>;
  model?: SidecarModel;
  loadModel?: () => SidecarModel;
  stream?: StreamSimple;
  onEvent?: (event: SidecarEvent) => void;
  now?: () => number;
  createRequestId?: () => string;
}

export class SidecarError extends Error {
  readonly code: SidecarErrorCode;

  constructor(code: SidecarErrorCode) {
    super(code);
    this.name = "SidecarError";
    this.code = code;
  }
}

interface ActiveRequest {
  requestId: string;
  controller: AbortController;
  promise: Promise<GenerationResult>;
}

interface RequestDiagnostics {
  readonly requestId: string;
  readonly startedAt: number;
  readonly marks: LatencyMarks;
}

function defaultModel(): SidecarModel {
  return getBundledModel<"openai-codex-responses">(PROVIDER, MODEL_ID);
}

function validateModel(model: SidecarModel): SidecarModel {
  if (model.provider !== PROVIDER || model.id !== MODEL_ID || model.api !== API) {
    throw new SidecarError("startup_error");
  }
  return model;
}

function defaultStream(
  model: SidecarModel,
  context: Context,
  options?: SimpleStreamOptions,
): AsyncIterable<AssistantMessageEvent> {
  return streamSimple(model, context, options);
}

function isAbortError(error: unknown): boolean {
  return error instanceof SidecarError && error.code === "cancelled";
}

export class ModelSidecar {
  #state: SidecarState = "new";
  #auth: AuthStorageLike | undefined;
  #model: SidecarModel | undefined;
  #active: ActiveRequest | undefined;
  #startPromise: Promise<void> | undefined;
  #closePromise: Promise<void> | undefined;
  #closed = false;
  readonly #discoverAuth: () => Promise<AuthStorageLike>;
  readonly #loadModel: () => SidecarModel;
  readonly #stream: StreamSimple;
  readonly #onEvent: (event: SidecarEvent) => void;
  readonly #now: () => number;
  readonly #createRequestId: () => string;

  constructor(options: ModelSidecarOptions = {}) {
    this.#auth = options.auth;
    this.#model = options.model ? validateModel(options.model) : undefined;
    this.#discoverAuth = options.discoverAuth ?? (async () => discoverAuthStorage());
    this.#loadModel = options.loadModel ?? defaultModel;
    this.#stream = options.stream ?? defaultStream;
    this.#onEvent = options.onEvent ?? (() => undefined);
    this.#now = options.now ?? (() => performance.now());
    this.#createRequestId = options.createRequestId ?? (() => randomUUID());
  }

  get state(): SidecarState {
    return this.#state;
  }

  get model(): SidecarModel | undefined {
    return this.#model;
  }

  async start(): Promise<void> {
    if (this.#state === "ready" || this.#state === "busy") return;
    if (this.#state === "closed" || this.#closed) throw new SidecarError("closed");
    if (this.#startPromise) return this.#startPromise;

    this.#state = "starting";
    this.#startPromise = this.#startInternal();
    return this.#startPromise;
  }

  generate(prompt: string): GenerationHandle {
    const requestId = this.#createRequestId();
    if (this.#closed || this.#state === "closed") return this.#rejectedHandle(requestId, "closed");
    if (this.#state !== "ready") return this.#rejectedHandle(requestId, "not_ready");
    if (this.#active) return this.#rejectedHandle(requestId, "busy");

    const model = this.#model;
    const auth = this.#auth;
    if (!model || !auth) return this.#rejectedHandle(requestId, "not_ready");

    const diagnostics: RequestDiagnostics = {
      requestId,
      startedAt: this.#now(),
      marks: { requestReceived: 0 },
    };
    const controller = new AbortController();
    this.#state = "busy";
    this.#emit("request_received", diagnostics, {});

    const promise = this.#runRequest(prompt, model, auth, controller, diagnostics);
    this.#active = { requestId, controller, promise };
    const cleanup = () => {
      if (this.#active?.requestId === requestId) this.#active = undefined;
      if (!this.#closed) this.#state = "ready";
    };
    void promise.then(cleanup, cleanup);
    return { requestId, result: promise };
  }

  cancel(requestId: string): boolean {
    if (this.#active?.requestId !== requestId) return false;
    this.#active.controller.abort();
    return true;
  }

  async close(): Promise<void> {
    if (this.#closePromise) return this.#closePromise;
    this.#closePromise = this.#closeInternal();
    return this.#closePromise;
  }

  async #closeInternal(): Promise<void> {
    if (this.#state === "closed") return;
    this.#closed = true;
    this.#active?.controller.abort();
    const activePromise = this.#active?.promise;
    if (activePromise) await activePromise.catch(() => undefined);
    if (this.#startPromise) await this.#startPromise.catch(() => undefined);
    this.#auth?.close();
    this.#auth = undefined;
    this.#state = "closed";
  }

  async #startInternal(): Promise<void> {
    try {
      const auth = this.#auth ?? (await this.#discoverAuth());
      if (this.#closed) {
        auth.close();
        throw new SidecarError("closed");
      }
      this.#auth = auth;
      this.#model = validateModel(this.#model ?? this.#loadModel());
      this.#state = "ready";
      this.#emit("ready", undefined, {});
    } catch (error) {
      if (this.#auth && this.#state !== "closed") this.#auth.close();
      this.#auth = undefined;
      if (!this.#closed) {
        this.#state = "failed";
        this.#emit("error", undefined, { code: "startup_error" });
      }
      if (error instanceof SidecarError && error.code === "closed") throw error;
      throw new SidecarError("startup_error");
    }
  }

  async #runRequest(
    prompt: string,
    model: SidecarModel,
    auth: AuthStorageLike,
    controller: AbortController,
    diagnostics: RequestDiagnostics,
  ): Promise<GenerationResult> {
    let text = "";
    let iterator: AsyncIterator<AssistantMessageEvent> | undefined;
    try {
      const message: Message = { role: "user", content: prompt, timestamp: Date.now() };
      const context: Context = { messages: [message] };
      const apiKey: ApiKeyResolver = auth.resolver(PROVIDER, {
        sessionId: diagnostics.requestId,
        modelId: model.id,
        baseUrl: model.baseUrl,
      });

      this.#mark(diagnostics, "providerDispatch");
      this.#emit("provider_dispatch", diagnostics, {});
      const stream = this.#stream(model, context, {
        apiKey,
        signal: controller.signal,
        preferWebsockets: false,
      });
      iterator = stream[Symbol.asyncIterator]();
      let firstEvent = true;
      while (true) {
        const next = iterator.next();
        const item = await this.#nextOrCancelled(next, controller.signal);
        if (item.done) break;
        const received = item.value;
        if (firstEvent) {
          firstEvent = false;
          this.#mark(diagnostics, "providerFirstEvent");
          this.#emit("provider_first_event", diagnostics, { providerEventType: received.type });
        }
        if (received.type === "text_delta") {
          if (received.delta.length > 0) this.#mark(diagnostics, "firstNonEmptyDelta");
          text += received.delta;
          this.#emit("text_delta", diagnostics, { delta: received.delta });
        } else if (received.type === "error") {
          if (received.reason === "aborted" || controller.signal.aborted) throw new SidecarError("cancelled");
          this.#emit("error", diagnostics, { code: "provider_error" });
          throw new SidecarError("provider_error");
        } else if (received.type === "done" && received.reason === "toolUse") {
          this.#emit("error", diagnostics, { code: "unsupported_output" });
          throw new SidecarError("unsupported_output");
        } else if (received.type === "toolcall_start" || received.type === "toolcall_delta" || received.type === "toolcall_end") {
          this.#emit("error", diagnostics, { code: "unsupported_output" });
          throw new SidecarError("unsupported_output");
        }
        if (received.type === "done") break;
      }
      if (controller.signal.aborted) throw new SidecarError("cancelled");
      this.#mark(diagnostics, "completion");
      this.#emit("completed", diagnostics, { textLength: text.length });
      return { requestId: diagnostics.requestId, status: "completed", text };
    } catch (error) {
      if (controller.signal.aborted || isAbortError(error)) {
        this.#mark(diagnostics, "cancellation");
        this.#emit("cancelled", diagnostics, {});
        return { requestId: diagnostics.requestId, status: "cancelled", text };
      }
      if (error instanceof SidecarError) {
        if (error.code !== "provider_error" && error.code !== "unsupported_output") {
          this.#emit("error", diagnostics, { code: "provider_error" });
        }
        throw error;
      }
      this.#emit("error", diagnostics, { code: "provider_error" });
      throw new SidecarError("provider_error");
    } finally {
      if (iterator) {
        try {
          await iterator.return?.();
        } catch {
          // Provider cleanup must be awaited, but a cleanup error must not
          // replace the already-classified request result.
        }
      }
    }
  }

  async #nextOrCancelled<T>(
    next: Promise<IteratorResult<T>>,
    signal: AbortSignal,
  ): Promise<IteratorResult<T>> {
    if (signal.aborted) throw new SidecarError("cancelled");
    let abortListener: (() => void) | undefined;
    const abort = new Promise<never>((_, reject) => {
      abortListener = () => reject(new SidecarError("cancelled"));
      signal.addEventListener("abort", abortListener, { once: true });
    });
    try {
      return await Promise.race([next, abort]);
    } catch (error) {
      void next.catch(() => undefined);
      throw error;
    } finally {
      if (abortListener) signal.removeEventListener("abort", abortListener);
    }
  }

  #rejectedHandle(requestId: string, code: SidecarErrorCode): GenerationHandle {
    const diagnostics: RequestDiagnostics = {
      requestId,
      startedAt: this.#now(),
      marks: { requestReceived: 0 },
    };
    this.#emit("error", diagnostics, { code });
    return { requestId, result: Promise.reject(new SidecarError(code)) };
  }

  #mark(diagnostics: RequestDiagnostics, name: keyof LatencyMarks): void {
    if (diagnostics.marks[name] !== undefined) return;
    diagnostics.marks[name] = Math.max(0, this.#now() - diagnostics.startedAt);
  }

  #emit<T extends SidecarEvent["type"]>(
    type: T,
    diagnostics: RequestDiagnostics | undefined,
    payload: Omit<Extract<SidecarEvent, { type: T }>, keyof SidecarEventBase | "type">,
  ): void {
    const model = this.#model;
    const event = {
      type,
      ...(diagnostics ? { requestId: diagnostics.requestId } : {}),
      atMs: this.#now(),
      metadata: {
        marks: diagnostics ? { ...diagnostics.marks } : {},
        ...(model ? { modelId: model.id, provider: model.provider, api: model.api } : {}),
      },
      ...payload,
    } as SidecarEvent;
    try {
      this.#onEvent(event);
    } catch {
      // Diagnostic observers cannot change provider lifecycle.
    }
  }
}

export function createModelSidecar(options?: ModelSidecarOptions): ModelSidecar {
  return new ModelSidecar(options);
}
