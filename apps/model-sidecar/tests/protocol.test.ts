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
      protocol_version: 1,
      type: "generate",
      generation_id: "generation-1",
      epoch: 3,
      prompt: "Reply exactly OK.",
    };
    const event = {
      protocol_version: 1 as const,
      type: "text_delta" as const,
      generation_id: "generation-1",
      epoch: 3,
      delta: "OK",
    };

    expect(parseCommand(encodeCommand(command).trim())).toEqual(command);
    expect(JSON.parse(encodeEvent(event)) as typeof event).toEqual(event);
  });

  test("rejects unknown fields, invalid versions, and oversized values", () => {
    expect(() => parseCommand('{"protocol_version":1,"type":"health","extra":true}')).toThrow();
    expect(() => parseCommand('{"protocol_version":2,"type":"health"}')).toThrow();
    expect(() =>
      parseCommand(
        JSON.stringify({
          protocol_version: 1,
          type: "generate",
          generation_id: "generation-1",
          epoch: 1,
          prompt: "x".repeat(PROTOCOL_LIMITS.maxPromptBytes + 1),
        }),
      ),
    ).toThrow();
    expect(() =>
      encodeEvent({
        protocol_version: 1,
        type: "text_delta",
        generation_id: "generation-1",
        epoch: 1,
        delta: "",
      }),
    ).toThrow();
  });

  test("preserves UTF-8 line framing across chunk boundaries", async () => {
    const encoded = new TextEncoder().encode(
      '{"protocol_version":1,"type":"health"}\r\n{"protocol_version":1,"type":"shutdown"}\n',
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
      '{"protocol_version":1,"type":"health"}',
      '{"protocol_version":1,"type":"shutdown"}',
    ]);
  });
});
