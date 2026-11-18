import asyncio
import json
import sys
import unittest

from vtuber.contracts.mind import MindDecision
from vtuber.minds.luna_stream import LunaStream, LunaStreamError


FIXTURE = """
import json, sys, time
slow_cancel = False
for line in sys.stdin:
    frame = json.loads(line)
    kind = frame["type"]
    if kind == "shutdown":
        break
    identifier = frame["id"]
    def send(frame_type, **fields):
        print(json.dumps(dict(type=frame_type, id=identifier, **fields)), flush=True)
    if kind == "cancel":
        if slow_cancel:
            time.sleep(0.3)
        send("speak_delta", text="stale")
        send("error", kind="cancelled")
        continue
    assert frame["system"] == "Identity"
    assert frame["reasoning"] == "low"
    text = frame["messages"][0]["content"]
    if text == "error":
        print(json.dumps(dict(type="error", id=identifier, kind="provider_error")), flush=True)
    elif text in ("cancel", "cancel_twice"):
        slow_cancel = text == "cancel_twice"
        send("speak_delta", text="early")
    elif text == "invalid":
        send("result", action="speak", message="", tool_call_id="call_1")
    elif text == "silence":
        send("result", action="stay_silent", message="", tool_call_id="call_2")
    else:
        send("speak_delta", text="Hel")
        send("speak_delta", text="lo!")
        send("result", action="speak", message="Hello!", tool_call_id="call_1",
             usage={"input": 5, "output": 2}, timings={"first_tool_delta_ms": 12, "completed_ms": 18})
"""


class LunaStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mind = LunaStream((sys.executable, "-u", "-c", FIXTURE), system="Identity")
        self.addAsyncCleanup(self.mind.close)

    def generate(self, text, callback=None):
        return self.mind.generate(({"role": "user", "content": text},), on_speak_delta=callback)

    async def test_fake_bridge_speak_and_silence(self):
        self.assertEqual(self.mind.model_status(),
                         {"name": "gpt-6-luna", "reasoning": "low", "bridge": "not_started"})
        deltas = []
        decision = await self.generate("speak", deltas.append)
        self.assertEqual(self.mind.model_status()["bridge"], "running")
        self.assertEqual(deltas, ["Hel", "lo!"])
        self.assertEqual(decision, MindDecision("speak", "Hello!", "call_1", {"input": 5, "output": 2}))
        self.assertEqual(self.mind.last_timings, {"first_tool_delta_ms": 12, "completed_ms": 18})
        self.assertEqual(await self.generate("silence", self.fail), MindDecision("stay_silent", "", "call_2"))
        self.assertEqual(self.mind.last_timings, {})

    async def test_projected_system_message_is_sent_separately(self):
        mind = LunaStream((sys.executable, "-u", "-c", FIXTURE), system="Fallback")
        self.addAsyncCleanup(mind.close)
        decision = await mind.generate(({"role": "system", "content": "Identity"},
                                        {"role": "user", "content": "silence"}))
        self.assertEqual(decision.action, "stay_silent")

    async def test_bridge_error_is_visible(self):
        with self.assertRaisesRegex(LunaStreamError, "provider_error") as raised:
            await self.generate("error")
        self.assertEqual(raised.exception.code, "provider_error")
        self.assertEqual(self.mind.model_status()["bridge"], "unavailable")
        with self.assertRaises(LunaStreamError):
            await self.generate("invalid")

    async def test_cancel_stops_deltas(self):
        first = asyncio.Event()
        deltas = []

        def on_delta(delta):
            deltas.append(delta)
            first.set()

        task = asyncio.create_task(self.generate("cancel", on_delta))
        await asyncio.wait_for(first.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(deltas, ["early"])
        self.assertEqual((await self.generate("silence")).action, "stay_silent")

    async def test_repeated_cancellation_drains_old_turn_before_next(self):
        first = asyncio.Event()
        task = asyncio.create_task(self.generate("cancel_twice", lambda _: first.set()))
        await asyncio.wait_for(first.wait(), 2)
        task.cancel()
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((await self.generate("silence")).action, "stay_silent")

    async def test_close_joins_owned_process(self):
        await self.generate("silence")
        process = self.mind._process
        await self.mind.close()
        self.assertEqual(process.returncode, 0)
        with self.assertRaises(LunaStreamError):
            await self.generate("silence")

    async def test_missing_executable_reports_startup_failure(self):
        mind = LunaStream(("missing-bun-for-unit-test-547479",), system="Identity")
        self.addAsyncCleanup(mind.close)
        with self.assertRaisesRegex(LunaStreamError, "startup_failed"):
            await mind.generate(({"role": "user", "content": "hi"},))
        self.assertEqual(mind.model_status()["bridge"], "unavailable")
