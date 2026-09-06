import { describe, expect, test } from "bun:test";
import {
  encodeCommand,
  encodeEvent,
  parseCommand,
  PROTOCOL_LIMITS,
  type ProtocolCommand,
} from "../src/protocol.js";

describe("sidecar protocol", () => {
  test("round-trips the minimal command and event shapes", () => {
    const command: ProtocolCommand = {
      protocol_version: 2,
      type: "generate",
      generation_id: "generation-1",
      epoch: 3,
      prompt: "Reply exactly OK.",
    };
    const event = {
      protocol_version: 2 as const,
      type: "text_delta" as const,
      generation_id: "generation-1",
      epoch: 3,
      delta: "OK",
    };

    expect(parseCommand(encodeCommand(command).trim())).toEqual(command);
    expect(JSON.parse(encodeEvent(event)) as typeof event).toEqual(event);
    expect(
      JSON.parse(
        encodeEvent({
          protocol_version: 2,
          type: "failed",
          generation_id: "generation-1",
          epoch: 3,
          code: "cleanup_timeout",
        }),
      ),
    ).toMatchObject({ type: "failed", code: "cleanup_timeout" });
  });

  test("round-trips caller-owned structured context with only role and text", () => {
    const command: ProtocolCommand = {
      protocol_version: 2,
      type: "generate",
      generation_id: "generation-structured",
      epoch: 4,
      messages: [
        { role: "user", text: "Remember the word quartz." },
        { role: "assistant", text: "ACK_1" },
        { role: "user", text: "What was the word?" },
      ],
    };

    expect(parseCommand(encodeCommand(command).trim())).toEqual(command);
    expect(JSON.parse(encodeCommand(command))).toEqual(command);
  });

  test("round-trips optional trusted guidance and keeps it separate from messages", () => {
    const command: ProtocolCommand = {
      protocol_version: 2,
      type: "generate",
      generation_id: "generation-guided",
      epoch: 5,
      messages: [{ role: "user", text: "hello" }],
      system_prompt: ["trusted identity", "trusted behavior"],
    };

    expect(parseCommand(encodeCommand(command).trim())).toEqual(command);
    expect(JSON.parse(encodeCommand(command))).toMatchObject({ system_prompt: command.system_prompt });
  });

  test("rejects unknown fields, invalid versions, and oversized values", () => {
    expect(() => parseCommand('{"protocol_version":2,"type":"health","extra":true}')).toThrow();
    expect(() => parseCommand('{"protocol_version":1,"type":"health"}')).toThrow();
    expect(() => parseCommand('{"protocol_version":2.0,"type":"health"}')).toThrow();
    expect(() => parseCommand('{"protocol_version":2,"type":"generate","generation_id":"x","epoch":1.0,"prompt":"x"}')).toThrow();
    expect(() => parseCommand('{"protocol_version":2,"type":"health","type":"health"}')).toThrow();
    expect(() => parseCommand('{"protocol_version":2,"type":"generate","generation_id":"x","epoch":1,"prompt":"x","system_prompt":[],"system_prompt":[]}')).toThrow();
    expect(() =>
      parseCommand(
        JSON.stringify({
          protocol_version: 2,
          type: "generate",
          generation_id: "generation-1",
          epoch: 1,
          messages: [{ role: "developer", text: "not supported" }],
        }),
      ),
    ).toThrow();
    expect(() =>
      parseCommand(
        JSON.stringify({
          protocol_version: 2,
          type: "generate",
          generation_id: "generation-1",
          epoch: 1,
          prompt: "legacy",
          messages: [{ role: "user", text: "ambiguous" }],
        }),
      ),
    ).toThrow();
    expect(() =>
      parseCommand(
        JSON.stringify({
          protocol_version: 2,
          type: "generate",
          generation_id: "generation-1",
          epoch: 1,
          prompt: "x".repeat(PROTOCOL_LIMITS.maxPromptBytes + 1),
        }),
      ),
    ).toThrow();
    expect(() =>
      encodeEvent({
        protocol_version: 2,
        type: "text_delta",
        generation_id: "generation-1",
        epoch: 1,
        delta: "",
      }),
    ).toThrow();
    expect(() =>
      parseCommand(
        JSON.stringify({
          protocol_version: 2,
          type: "generate",
          generation_id: "generation-1",
          epoch: 1,
          messages: [{ role: "user", text: "hello" }],
          system_prompt: [" ", " "]
        }),
      ),
    ).toThrow();
  });

  test("preserves UTF-8 line framing across chunk boundaries", async () => {
    const encoded = new TextEncoder().encode(
      '{"protocol_version":2,"type":"health"}\r\n{"protocol_version":2,"type":"shutdown"}\n',
    );
    const input = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoded.subarray(0, 17));
        controller.enqueue(encoded.subarray(17));
        controller.close();
      },
    });
    const lines: string[] = [];
    for await (const line of (await import("../src/protocol.js")).readProtocolLines(input)) lines.push(line);

    expect(lines).toEqual([
      '{"protocol_version":2,"type":"health"}',
      '{"protocol_version":2,"type":"shutdown"}',
    ]);
  });
});
