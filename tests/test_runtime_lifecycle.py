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
    async def test_clock_correction_does_not_strand_initiative(self):
        from datetime import datetime, timedelta
        from unittest.mock import patch
        from vtuber.contracts.deep import DeepResult, InitiativeProposal
        from vtuber.contracts.events import utc_now
        wall, monotonic = [datetime.fromisoformat(utc_now())], [100.0]
        async def elapsed(seconds):
            monotonic[0] += seconds + .01
            wall[0] -= timedelta(minutes=5)
            await asyncio.sleep(0)
        journal = Journal(':memory:')
        try:
            async with Runtime('primary', journal, FakeFast(0), FakeDeep(100), lambda _: None,
                initiative_enabled=True, initiative_cooldown_seconds=0) as runtime:
                user = UserMessage('unfinished hat')
                await (await runtime.submit(user))
                request = journal.deep_request('primary', request_id='clock', initiative_allowed=True)
                result = DeepResult(2, request.request_id, initiative=InitiativeProposal('hat', 'unfinished', (user.event_id,)))
                decision = journal.apply_deep(request, result)
                wall[0] = datetime.fromisoformat(request.captured_at)
                with patch('vtuber.runtime.orchestrator.utc_now', lambda: wall[0].isoformat()), \
                     patch('vtuber.runtime.journal.utc_now', lambda: wall[0].isoformat()), \
                     patch('vtuber.runtime.orchestrator.perf_counter', lambda: monotonic[0]), \
                     patch('vtuber.runtime.orchestrator.initiative_delay', elapsed):
                    runtime._on_deep_decision(request, result, decision)
                    await runtime._initiative_task
                    await runtime._fast_task
                    self.assertIsNone(journal.pending_initiative('primary'))
                    self.assertEqual(len([e for e in journal.read('primary', limit=100)
                        if e.kind == 'character.initiative.started']), 1)
        finally:
            journal.close()

    async def test_user_wins_initiative_race(self):
        from vtuber.contracts.deep import DeepResult, InitiativeProposal
        from vtuber.contracts.events import CharacterInitiative
        from unittest.mock import patch
        entered, release, ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls, outputs = [], []
        class Fast:
            async def stream(self, snapshot, message):
                calls.append(message)
                if isinstance(message, CharacterInitiative):
                    entered.set()
                    yield 'first'
                    await release.wait()
                yield 'done'
        class Deep:
            async def propose(self, request):
                return DeepResult(2, request.request_id, initiative=InitiativeProposal(
                    'A hat joke', 'Unfinished design', (next(e.event_id for e in reversed(request.events)
                    if e.kind == 'user.message.completed'),))) if request.initiative_allowed else DeepResult(2, request.request_id)
        async def wait_ready(seconds):
            ready.set()
            await release.wait()
        async def until(predicate):
            async with asyncio.timeout(3):
                while not predicate():
                    await asyncio.sleep(0)
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder)/'race.db')
            try:
                async with Runtime('primary', journal, Fast(), Deep(), outputs.append,
                    initiative_enabled=True, initiative_delay_seconds=0, initiative_ttl_seconds=30,
                    initiative_cooldown_seconds=0) as runtime:
                    with patch('vtuber.runtime.orchestrator.initiative_delay', wait_ready):
                        first = UserMessage('unfinished hat')
                        await (await runtime.submit(first))
                        await ready.wait()
                        pending = journal.pending_initiative('primary')
                        # A none result never rearms or withdraws the owned opportunity.
                        task = runtime._initiative_task
                        runtime._on_deep_decision(None, None, None)
                        self.assertIs(runtime._initiative_task, task)
                        self.assertEqual(journal.pending_initiative('primary'), pending)
                        queued = asyncio.create_task(runtime.submit(UserMessage('No jokes, new topic')))
                        release.set()
                        await (await queued)
                    self.assertFalse(any(isinstance(m, CharacterInitiative) for m in calls))
                    release.clear()
                    await until(entered.is_set)
                    active = calls[-1]
                    self.assertIsInstance(active, CharacterInitiative)
                    await (await runtime.submit(UserMessage('Stop and listen')))
                    self.assertEqual(journal.get('reply_terminal_'+active.event_id).kind, 'character.reply.cancelled')
                    self.assertEqual(len([e for e in journal.read('primary', limit=1000)
                        if e.causation_id == active.event_id and e.kind.startswith('character.reply.')
                        and e.kind != 'character.reply.started']), 1)
                    await runtime.cancel_fast()
            finally:
                journal.close()

    async def test_initiative_close_and_recovery(self):
        from vtuber.contracts.deep import DeepResult, InitiativeProposal
        from vtuber.contracts.events import Event
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'recovery.db'
            journal = Journal(path)
            try:
                user = UserMessage('unfinished hat')
                journal.append(user.as_event())
                journal.append(Event.create('primary', 'character.reply.completed', {'text': 'okay'}, turn_id=user.turn_id))
                request = journal.deep_request('primary', request_id='pending-crash', initiative_allowed=True)
                journal.apply_deep(request, DeepResult(2, request.request_id, initiative=InitiativeProposal(
                    'hat', 'unfinished', (user.event_id,), 0, 120)))
                pending = journal.pending_initiative('primary')
                # Crash after atomic claim, before the task runs its first instruction.
                message = journal.claim_initiative(pending.event_id, journal.fast_snapshot('primary'))
                journal.close()
                journal = Journal(path)
                async with Runtime('primary', journal, FakeFast(0), FakeDeep(100), lambda _: None,
                    initiative_enabled=True, initiative_delay_seconds=0) as runtime:
                    self.assertEqual(journal.get('reply_terminal_'+message.event_id).payload['reason'], 'process_restarted')
                    self.assertIsNone(journal.pending_initiative('primary'))
                    self.assertEqual(journal.unfinished_inputs('primary'), ())
                self.assertEqual(journal._db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            finally:
                journal.close()

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
