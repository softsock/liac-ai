import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

for (const script of ["probe.mjs", "bridge.mjs"]) {
    test(`${script} disables request dumps before loading pi-ai`, () => {
        const entry = new URL(script, import.meta.url).href;
        const child = spawnSync(process.execPath, ["--input-type=module", "--eval", `
            import { registerHooks } from "node:module";
            registerHooks({
                resolve(id, context, next) {
                    if (id !== "@oh-my-pi/pi-ai") return next(id, context);
                    const disabled = process.env.PI_REQ_DEBUG !== "1" && process.env.PI_TEST_RUNTIME === "1";
                    console.log(disabled ? "debug disabled" : "debug enabled");
                    throw new Error("Stop before importing the SDK");
                },
            });
            process.argv = [process.execPath, ${JSON.stringify(entry)}, "--list"];
            await import(${JSON.stringify(entry)});
        `], { encoding: "utf8", env: { ...process.env, PI_REQ_DEBUG: "1", PI_TEST_RUNTIME: "0" } });

        assert.match(child.stdout, /^debug disabled$/m);
    });
}
