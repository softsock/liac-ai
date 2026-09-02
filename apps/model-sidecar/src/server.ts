import { createModelSidecar, type GenerationHandle, type ModelSidecar, type SidecarEvent } from "./index.js";
import {
  encodeEvent,
  parseCommand,
  PROTOCOL_LIMITS,
  readProtocolLines,
  type ProtocolCommand,
  type ProtocolErrorCode,
  type ProtocolEvent,
} from "./protocol.js";

const DEFAULT_STARTUP_TIMEOUT_MS = 30_000;
const DEFAULT_SHUTDOWN_TIMEOUT_MS = 5_000;
const DEFAULT_TERMINAL_CLEANUP_TIMEOUT_MS = 5_000;
const MAX_PENDING_FRAMES = 64;
const MAX_PENDING_BYTES = PROTOCOL_LIMITS.maxFrameBytes * 2;

export interface ProtocolOutput {
  write(chunk: string): boolean;
  once(event: "drain", listener: () => void): unknown;
}

export type SidecarFactory = (onEvent: (event: SidecarEvent) => void) => ModelSidecar;

export interface ProtocolServerOptions {
  input?: ReadableStream<Uint8Array>;
  output?: ProtocolOutput;
  createSidecar?: SidecarFactory;
  startupTimeoutMs?: number;
  shutdownTimeoutMs?: number;
  terminalCleanupTimeoutMs?: number;
  forceExit?: (code: number) => void;
}

class ProtocolWriter {
  readonly #output: ProtocolOutput;
  readonly #onFailure: (error: Error) => void;
  readonly #queue: string[] = [];
  #pendingBytes = 0;
  #drainPromise: Promise<void> | undefined;
  #failure: Error | undefined;
  #closed = false;

  constructor(output: ProtocolOutput, onFailure: (error: Error) => void) {
    this.#output = output;
    this.#onFailure = onFailure;
  }

  write(event: ProtocolEvent): boolean {
    if (this.#closed || this.#failure) return false;
    let line: string;
    try {
      line = encodeEvent(event);
    } catch (error) {
      this.#fail(error instanceof Error ? error : new Error("protocol encoding failed"));
      return false;
    }
    const bytes = new TextEncoder().encode(line).length;
    if (this.#queue.length >= MAX_PENDING_FRAMES || this.#pendingBytes + bytes > MAX_PENDING_BYTES) {
      this.#fail(new Error("protocol output buffer limit exceeded"));
      return false;
    }
    this.#queue.push(line);
    this.#pendingBytes += bytes;
    this.#startDrain();
    return true;
  }

  async flush(): Promise<void> {
    const pending = this.#drainPromise;
    if (pending) await pending;
    if (this.#failure) throw this.#failure;
  }

  async close(): Promise<void> {
    this.#closed = true;
    await this.flush();
  }

  #startDrain(): void {
    if (this.#drainPromise) return;
    const pending = this.#drain();
    this.#drainPromise = pending;
    void pending
      .catch(() => undefined)
      .finally(() => {
        if (this.#drainPromise === pending) this.#drainPromise = undefined;
      });
  }

  async #drain(): Promise<void> {
    while (this.#queue.length > 0) {
      const line = this.#queue.shift();
      if (line === undefined) return;
      this.#pendingBytes -= new TextEncoder().encode(line).length;
      let accepted: boolean;
      try {
        accepted = this.#output.write(line);
      } catch (error) {
        this.#fail(error instanceof Error ? error : new Error("protocol output failed"));
        throw this.#failure;
      }
      if (!accepted) await new Promise<void>((resolve) => this.#output.once("drain", resolve));
    }
  }

  #fail(error: Error): void {
    if (this.#failure) return;
    this.#failure = error;
    this.#queue.length = 0;
    this.#pendingBytes = 0;
    this.#onFailure(error);
  }
}

interface ActiveGeneration {
  readonly generationId: string;
  readonly epoch: number;
  readonly finished: Promise<void>;
  readonly resolveFinished: () => void;
  handle: GenerationHandle | undefined;
  cancelRequested: boolean;
  terminal: boolean;
  responseBytes: number;
}

export class ProtocolServer {
  readonly #input: ReadableStream<Uint8Array>;
  readonly #writer: ProtocolWriter;
  readonly #sidecar: ModelSidecar;
  readonly #startupTimeoutMs: number;
  readonly #shutdownTimeoutMs: number;
  readonly #terminalCleanupTimeoutMs: number;
  readonly #forceExit: (code: number) => void;
  #active: ActiveGeneration | undefined;
  #closing = false;
  #fatal = false;
  #readySeen = false;
  #startupFailureSeen = false;

  constructor(options: ProtocolServerOptions = {}) {
    this.#input = options.input ?? Bun.stdin.stream();
    this.#startupTimeoutMs = options.startupTimeoutMs ?? DEFAULT_STARTUP_TIMEOUT_MS;
    this.#shutdownTimeoutMs = options.shutdownTimeoutMs ?? DEFAULT_SHUTDOWN_TIMEOUT_MS;
    this.#terminalCleanupTimeoutMs = options.terminalCleanupTimeoutMs ?? DEFAULT_TERMINAL_CLEANUP_TIMEOUT_MS;
    this.#forceExit = options.forceExit ?? ((code) => process.exit(code));
    this.#writer = new ProtocolWriter(
      options.output ?? (process.stdout as unknown as ProtocolOutput),
      () => {
        this.#fatal = true;
        if (this.#active?.handle) this.#sidecar.cancel(this.#active.generationId, this.#active.epoch);
      },
    );
    const onEvent = (event: SidecarEvent): void => this.#handleSidecarEvent(event);
    this.#sidecar = options.createSidecar?.(onEvent) ?? createModelSidecar({ onEvent });
  }

  async run(): Promise<number> {
    try {
      await this.#withTimeout(this.#sidecar.start(), this.#startupTimeoutMs);
      await this.#writer.flush();
      if (!this.#readySeen) throw new Error("sidecar did not emit ready");
    } catch {
      if (!this.#startupFailureSeen) this.#writeFailed(undefined, undefined, "startup_error");
      await this.#finishAfterFailure();
      return 1;
    }

    let exitCode = 0;
    try {
      for await (const line of readProtocolLines(this.#input)) {
        if (this.#fatal) {
          exitCode = 1;
          break;
        }
        let command: ProtocolCommand;
        try {
          command = parseCommand(line);
        } catch {
          this.#writeFailed(undefined, undefined, "protocol_error");
          exitCode = 1;
          break;
        }
        const keepRunning = await this.#dispatch(command);
        if (!keepRunning) break;
      }
    } catch {
      this.#writeFailed(undefined, undefined, "protocol_error");
      exitCode = 1;
    }

    if (!this.#closing) {
      const closed = await this.#closeSidecar();
      if (!closed) exitCode = 1;
    }
    await this.#writer.flush().catch(() => {
      exitCode = 1;
    });
    return this.#fatal ? 1 : exitCode;
  }

  async #dispatch(command: ProtocolCommand): Promise<boolean> {
    switch (command.type) {
      case "generate":
        await this.#generate(command);
        return true;
      case "cancel":
        this.#cancel(command.generation_id, command.epoch);
        return true;
      case "health":
        this.#writeHealth();
        return true;
      case "shutdown":
        this.#closing = true;
        if (!(await this.#closeSidecar())) return false;
        this.#writeEvent({ protocol_version: 1, type: "shutdown" });
        await this.#writer.flush().catch(() => undefined);
        return false;
    }
  }

  async #generate(command: Extract<ProtocolCommand, { type: "generate" }>): Promise<void> {
    const active = this.#active;
    if (active?.terminal) {
      const finished = await this.#withTimeout(active.finished, this.#terminalCleanupTimeoutMs).then(
        () => true,
        () => false,
      );
      if (!finished) {
        this.#writeFailed(command.generation_id, command.epoch, "provider_error");
        return;
      }
    }
    if (this.#active) {
      this.#writeFailed(command.generation_id, command.epoch, "busy");
      return;
    }

    let resolveFinished!: () => void;
    const finished = new Promise<void>((resolve) => {
      resolveFinished = resolve;
    });
    const pending: ActiveGeneration = {
      generationId: command.generation_id,
      epoch: command.epoch,
      finished,
      resolveFinished,
      handle: undefined,
      cancelRequested: false,
      terminal: false,
      responseBytes: 0,
    };
    this.#active = pending;
    try {
      const handle = this.#sidecar.generate(command.prompt, {
        generationId: command.generation_id,
        epoch: command.epoch,
      });
      pending.handle = handle;
      void this.#observeGeneration(pending, handle);
    } catch {
      pending.terminal = true;
      this.#writeFailed(command.generation_id, command.epoch, "provider_error");
      this.#finishActive(pending);
    }
  }

  #cancel(generationId: string, epoch: number): void {
    const active = this.#active;
    if (!active || active.generationId !== generationId || active.epoch !== epoch || active.terminal) {
      this.#writeFailed(generationId, epoch, "not_active");
      return;
    }
    if (active.cancelRequested) return;
    active.cancelRequested = true;
    if (!this.#sidecar.cancel(generationId, epoch)) this.#writeFailed(generationId, epoch, "not_active");
  }

  async #observeGeneration(active: ActiveGeneration, handle: GenerationHandle): Promise<void> {
    try {
      const result = await handle.result;
      if (!active.terminal) {
        active.terminal = true;
        this.#writeEvent(
          result.status === "completed"
            ? { protocol_version: 1, type: "completed", generation_id: active.generationId, epoch: active.epoch }
            : { protocol_version: 1, type: "cancelled", generation_id: active.generationId, epoch: active.epoch },
        );
      }
    } catch {
      if (!active.terminal) {
        active.terminal = true;
        this.#writeFailed(active.generationId, active.epoch, "provider_error");
      }
    } finally {
      this.#finishActive(active);
    }
  }

  #handleSidecarEvent(event: SidecarEvent): void {
    switch (event.type) {
      case "ready":
        this.#readySeen = true;
        this.#writeEvent({
          protocol_version: 1,
          type: "ready",
          provider: event.metadata.provider ?? "openai-codex",
          model_id: event.metadata.modelId ?? "gpt-5.6-luna",
          api: event.metadata.api ?? "openai-codex-responses",
        });
        return;
      case "request_received": {
        const active = this.#active;
        if (active && this.#matches(active, event) && !active.terminal) {
          this.#writeEvent({
            protocol_version: 1,
            type: "accepted",
            generation_id: active.generationId,
            epoch: active.epoch,
          });
        }
        return;
      }
      case "text_delta": {
        const active = this.#active;
        if (!active || !this.#matches(active, event) || active.cancelRequested || active.terminal) return;
        const deltaBytes = new TextEncoder().encode(event.delta).length;
        if (active.responseBytes + deltaBytes > PROTOCOL_LIMITS.maxResponseBytes) {
          active.cancelRequested = true;
          active.terminal = true;
          this.#writeFailed(active.generationId, active.epoch, "output_limit");
          this.#sidecar.cancel(active.generationId, active.epoch);
          return;
        }
        active.responseBytes += deltaBytes;
        for (const delta of splitDelta(event.delta)) {
          this.#writeEvent({
            protocol_version: 1,
            type: "text_delta",
            generation_id: active.generationId,
            epoch: active.epoch,
            delta,
          });
        }
        return;
      }
      case "completed": {
        const active = this.#active;
        if (!active || !this.#matches(active, event) || active.terminal) return;
        active.terminal = true;
        this.#writeEvent({
          protocol_version: 1,
          type: "completed",
          generation_id: active.generationId,
          epoch: active.epoch,
        });
        return;
      }
      case "cancelled": {
        const active = this.#active;
        if (!active || !this.#matches(active, event) || active.terminal) return;
        active.terminal = true;
        this.#writeEvent({
          protocol_version: 1,
          type: "cancelled",
          generation_id: active.generationId,
          epoch: active.epoch,
        });
        return;
      }
      case "error":
        this.#handleSidecarError(event);
        return;
      case "provider_dispatch":
      case "provider_first_event":
        return;
    }
  }

  #handleSidecarError(event: Extract<SidecarEvent, { type: "error" }>): void {
    const code = toProtocolErrorCode(event.code);
    if (!event.requestId) {
      this.#startupFailureSeen = code === "startup_error";
      this.#writeFailed(undefined, undefined, code);
      return;
    }
    const active = this.#active;
    if (!active || !this.#matches(active, event) || active.terminal) return;
    active.terminal = true;
    this.#writeFailed(active.generationId, active.epoch, code);
  }

  #writeHealth(): void {
    const state = this.#sidecar.state === "new" ? "starting" : this.#sidecar.state;
    this.#writeEvent({ protocol_version: 1, type: "health", state });
  }

  #writeFailed(generationId: string | undefined, epoch: number | undefined, code: ProtocolErrorCode): void {
    if (generationId !== undefined && epoch !== undefined) {
      this.#writeEvent({ protocol_version: 1, type: "failed", generation_id: generationId, epoch, code });
    } else {
      this.#writeEvent({ protocol_version: 1, type: "failed", code });
    }
  }

  #writeEvent(event: ProtocolEvent): void {
    this.#writer.write(event);
  }

  #matches(active: ActiveGeneration, event: SidecarEvent): boolean {
    return event.requestId === active.generationId && (event.epoch === undefined || event.epoch === active.epoch);
  }

  #finishActive(active: ActiveGeneration): void {
    if (this.#active !== active) return;
    this.#active = undefined;
    active.resolveFinished();
  }

  async #closeSidecar(): Promise<boolean> {
    try {
      await this.#withTimeout(this.#sidecar.close(), this.#shutdownTimeoutMs);
      return true;
    } catch {
      this.#fatal = true;
      this.#forceExit(1);
      return false;
    }
  }

  async #finishAfterFailure(): Promise<void> {
    await this.#closeSidecar();
    await this.#writer.flush().catch(() => undefined);
  }

  async #withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        promise,
        new Promise<T>((_, reject) => {
          timer = setTimeout(() => reject(new Error("protocol operation timed out")), timeoutMs);
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }
}

function splitDelta(delta: string): string[] {
  const chunks: string[] = [];
  let current = "";
  const encoder = new TextEncoder();
  for (const character of delta) {
    const candidate = current + character;
    if (current.length > 0 && encoder.encode(candidate).length > PROTOCOL_LIMITS.maxDeltaBytes) {
      chunks.push(current);
      current = character;
    } else {
      current = candidate;
    }
  }
  if (current.length > 0) chunks.push(current);
  return chunks;
}

function toProtocolErrorCode(code: string): ProtocolErrorCode {
  if (
    code === "busy" ||
    code === "not_ready" ||
    code === "closed" ||
    code === "not_active" ||
    code === "startup_error" ||
    code === "provider_error" ||
    code === "unsupported_output" ||
    code === "protocol_error" ||
    code === "output_limit" ||
    code === "cancelled"
  ) {
    return code;
  }
  if (code === "response_limit") return "output_limit";
  return "provider_error";
}

export async function runProtocolServer(options?: ProtocolServerOptions): Promise<number> {
  return new ProtocolServer(options).run();
}
