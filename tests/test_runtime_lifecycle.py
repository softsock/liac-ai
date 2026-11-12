import asyncio
import tempfile
import unittest
from pathlib import Path

from vtuber.contracts.events import UserMessage
from vtuber.contracts.context import CompactionProposal, ContextItem
from vtuber.contracts.state import NoteProposal
from vtuber.context import ContextCompiler
from vtuber.minds.fake import FakeDeep, FakeFast
from vtuber.runtime.journal import Journal
from vtuber.runtime.orchestrator import Runtime


class RuntimeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_epoch_and_note_updates_do_not_mutate_active_fast_snapshot(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        captured = []
        class StalledFast:
            async def stream(self, snapshot, message):
                captured.append(snapshot)
                if len(captured) == 2:
                    entered.set()
                    await resume.wait()
                yield 'reply'
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / 'runtime.sqlite3')
            try:
                compiler = ContextCompiler('Identity')
                async with Runtime('primary', journal, StalledFast(), FakeDeep(100), lambda _: None,
                                   context_policy=compiler) as runtime:
                    first = UserMessage('anchor')
                    await (await runtime.submit(first))
                    cutoff = journal.high_watermark('primary')
                    second = UserMessage('second')
                    task = await runtime.submit(second)
                    await entered.wait()
                    original = captured[-1]
                    original_hash = compiler.compile(original, second).metadata()['sha256']
                    journal.apply_note(NoteProposal('note', 'primary', 0, cutoff, (first.event_id,), 'updated note'))
                    proposal = CompactionProposal('async', 'primary', 0, 1, cutoff, cutoff,
                                                  (ContextItem('anchor', (first.event_id,)),))
                    self.assertTrue(runtime.apply_compaction(proposal).accepted)
                    self.assertEqual(runtime.fast_diagnostics['last_compaction']['omitted_source_count'], 1)
                    self.assertEqual(captured[-1], original)
                    self.assertEqual(compiler.compile(captured[-1], second).metadata()['sha256'], original_hash)
                    resume.set()
                    await task
                    await (await runtime.submit(UserMessage('third')))
                    self.assertEqual((captured[-1].epoch.version, captured[-1].state.revision), (1, 1))
            finally:
                journal.close()

    async def test_epoch_pressure_restart_and_rejected_input_have_terminal_events(self):
        captured = []
        class Fast:
            async def stream(self, snapshot, message):
                captured.append(snapshot)
                yield 'READY'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'runtime.sqlite3'
            journal = Journal(path)
            compiler = ContextCompiler('Identity', 2400, 100)
            try:
                async with Runtime('primary', journal, Fast(), FakeDeep(100), lambda _: None,
                                   context_policy=compiler) as runtime:
                    for i in range(24):
                        task = await runtime.submit(UserMessage(f'fact {i} ' + 'garden ' * 30))
                        self.assertIsNotNone(task)
                        await task
                    epoch = journal.context_epoch('primary')
                    self.assertGreaterEqual(epoch.version, 2)
                journal.close()
                journal = Journal(path)
                self.assertEqual(journal.context_epoch('primary'), epoch)
                async with Runtime('primary', journal, Fast(), FakeDeep(100), lambda _: None,
                                   context_policy=compiler) as runtime:
                    await (await runtime.submit(UserMessage('after restart')))
                    self.assertEqual(captured[-1].epoch.version, epoch.version)
                    before, calls = journal.context_epoch('primary'), len(captured)
                    oversized = UserMessage('я' * 3000)
                    self.assertIsNone(await runtime.submit(oversized))
                    self.assertEqual(journal.get(f'reply_terminal_{oversized.event_id}').payload['reason'], 'ContextBudgetExceeded')
                    self.assertEqual(journal.context_epoch('primary'), before)
                    self.assertEqual(len(captured), calls)
                    self.assertIsNone(await runtime.submit(oversized))
                    self.assertEqual(journal.unfinished_replies('primary'), ())
            finally:
                journal.close()

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
