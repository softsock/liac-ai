import { test } from "bun:test";

test("sidecar entrypoint imports", async () => {
  await import("../src/index");
});
