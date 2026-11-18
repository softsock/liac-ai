import assert from "node:assert/strict";
import test from "node:test";
import { SpeakStream, completedArguments } from "./speak_stream.mjs";

test("decodes fragments across a split key, escapes and a surrogate pair", () => {
    const stream = new SpeakStream();
    const chunks = ['{ "mes', 'sage": "hello\\', '"\\\\ ', '\\uD83', 'D', '\\uDE00', '"}'];
    assert.deepEqual(chunks.map(chunk => stream.push(0, "speak", chunk)),
        ["", "hello", '"\\ ', "", "", "😀", ""]);
    assert.deepEqual(completedArguments("speak", stream.raw(0), { message: 'hello"\\ 😀' }),
        { message: 'hello"\\ 😀' });
});

test("does not switch speech to another tool index", () => {
    const stream = new SpeakStream();
    assert.equal(stream.push(1, "stay_silent", "{}"), "");
    assert.equal(stream.push(2, "speak", '{"message":"hi'), "hi");
    assert.equal(stream.push(7, "speak", '{"message":"other"}'), "");
    assert.equal(stream.push(2, "speak", '!"}'), "!");
});

test("preview cannot authorize malformed, incomplete or mismatched arguments", () => {
    const stream = new SpeakStream();
    assert.equal(stream.push(0, "speak", '{"message":"partial'), "partial");
    assert.equal(completedArguments("speak", stream.raw(0), { message: "partial" }), null);
    assert.equal(completedArguments("speak", '{"message":"hi"}', { message: "else" }), null);
    assert.equal(completedArguments("speak", '{"message":"hi","extra":true}', { message: "hi" }), null);
    assert.equal(completedArguments("stay_silent", '{"message":"x"}', {}), null);
    assert.deepEqual(completedArguments("stay_silent", "{}", {}), {});
});

test("rejects duplicate fields and final objects without raw argument evidence", () => {
    const stream = new SpeakStream();
    const raw = '{"message":"first","message":"second"}';
    assert.equal(stream.push(0, "speak", raw), "first");
    assert.equal(completedArguments("speak", raw, { message: "second" }), null);
    assert.equal(completedArguments("speak", "", { message: "repaired" }), null);
    assert.equal(completedArguments("stay_silent", "", {}), null);
});

test("never previews an invalid UTF-16 code unit", () => {
    const stream = new SpeakStream();
    assert.equal(stream.push(0, "speak", '{"message":"\\uDE00"}'), "");
});
