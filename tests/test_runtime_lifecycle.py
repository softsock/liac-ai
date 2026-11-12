import asyncio
import tempfile
import unittest
from pathlib import Path

from vtuber.contracts.events import UserMessage
from vtuber.minds.fake import FakeDeep, FakeFast
from vtuber.runtime.journal import Journal
from vtuber.runtime.orchestrator import Runtime


class RuntimeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_adapter_cannot_finish_as_completed(self):
        entered = asyncio.Event()

        class FinishingOnCancel:
            async def stream(self, snapshot, message):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    return
                yield "unreachable"

        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / "runtime.sqlite3")
            try:
                async with Runtime("primary", journal, FinishingOnCancel(), FakeDeep(10), lambda _: None) as runtime:
                    first = UserMessage("first")
                    await runtime.submit(first)
                    await entered.wait()
                    await runtime.submit(UserMessage("supersedes first"))
                    self.assertEqual(journal.get(f"reply_terminal_{first.event_id}").kind,
                                     "character.reply.cancelled")
            finally:
                journal.close()

    async def test_immediate_supersession_and_shutdown_leave_terminal_events(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / "runtime.sqlite3")
            output = []
            try:
                async with Runtime("primary", journal, FakeFast(0), FakeDeep(10), output.append) as runtime:
                    first = UserMessage("first")
                    second = UserMessage("second")
                    await runtime.submit(first)
                    task = await runtime.submit(second)
                    await task
                    events = journal.read("primary")
                    first_terminal = [e.kind for e in events if e.turn_id == first.turn_id and
                                      e.kind in ("character.reply.cancelled", "character.reply.completed")]
                    self.assertEqual(first_terminal, ["character.reply.cancelled"])
                    self.assertEqual(journal.snapshot("primary").revision, 0)
                    third = UserMessage("cancel before the task starts")
                    await runtime.submit(third)
                self.assertEqual(journal.unfinished_replies("primary"), ())
                self.assertEqual(journal.get(f"reply_terminal_{third.event_id}").kind,
                                 "character.reply.cancelled")
                self.assertFalse(any(e.kind == "deep.completed" for e in output))
            finally:
                journal.close()

    async def test_adapter_failure_does_not_complete_partial_speech(self):
        class BrokenFast:
            async def stream(self, snapshot, message):
                yield "partial"
                raise ConnectionError("private provider detail")

        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / "runtime.sqlite3")
            try:
                async with Runtime("primary", journal, BrokenFast(), FakeDeep(10), lambda _: None) as runtime:
                    message = UserMessage("hello")
                    await (await runtime.submit(message))
                    terminal = journal.get(f"reply_terminal_{message.event_id}")
                    self.assertEqual(terminal.kind, "character.reply.failed")
                    self.assertEqual(terminal.payload["reason"], "ConnectionError")
                    self.assertNotIn("text", terminal.payload)
                    self.assertNotIn("private", terminal.payload_json)
            finally:
                journal.close()
