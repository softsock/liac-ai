import tempfile
import unittest
import asyncio
from unittest.mock import patch
from pathlib import Path

from vtuber.contracts.context import CompactionProposal, ContextItem
from vtuber.contracts.deep import DeepResult
from vtuber.contracts.events import Event, UserMessage
from vtuber.contracts.state import NoteProposal
from vtuber.runtime.journal import EventConflict, Journal
from vtuber.runtime.deep import DeepWorker
from vtuber.minds.fake import FakeFast
from vtuber.runtime.orchestrator import Runtime


class DeepJournalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.journal = Journal(Path(self.folder.name) / 'deep.db')
        self.addCleanup(self.journal.close)

    def user(self, text='hello'):
        message = UserMessage(text)
        self.journal.append(message.as_event())
        return message

    def finish(self, message, kind='completed'):
        return self.journal.append(Event.create('primary', 'character.reply.'+kind,
            {'text': 'actual reply'} if kind == 'completed' else {'reason': 'test'},
            turn_id=message.turn_id, causation_id=message.event_id))

    def result(self, request, compact=False):
        source = request.events[0].event_id
        return DeepResult(1, request.request_id,
            NoteProposal(request.request_id+':note', 'primary', request.snapshot.state.revision,
                request.snapshot.through_sequence, (source,), 'new note'),
            CompactionProposal(request.request_id+':epoch', 'primary', request.snapshot.epoch.version,
                request.snapshot.state.revision, request.snapshot.through_sequence,
                request.compaction.cutoff, (ContextItem('summary', (source,), 'summary'),)) if compact else None)

    def test_markdown_replace_clear_and_no_change(self):
        from dataclasses import replace
        for index, (text, revision, reason) in enumerate([
                ('  # Custom\n' + 'x'*1100 + '\n ', 1, 'applied'),
                ('  # Custom\n' + 'x'*1100 + '\n ', 1, 'no_change'),
                ('', 2, 'applied'), ('', 2, 'no_change'), (None, 2, None)]):
            self.finish(self.user())
            request = self.journal.deep_request('primary', request_id=f'markdown-{index}')
            result = self.result(request)
            result = replace(result, note=replace(result.note, note=text) if text is not None else None)
            decision = self.journal.apply_deep(request, result)
            self.assertTrue(decision.acknowledged)
            self.assertEqual(decision.note.reason if decision.note else None, reason)
            self.journal.close()
            self.journal = Journal(Path(self.folder.name) / 'deep.db')
            self.addCleanup(self.journal.close)
            self.assertEqual(self.journal.snapshot('primary').revision, revision)
            self.assertEqual(self.journal.snapshot('primary').context_note, text or '')
            self.assertGreaterEqual(self.journal.cursor('primary'), request.snapshot.through_sequence)

    def test_budget_rejects_whole_batch_and_fingerprints_request(self):
        from dataclasses import replace
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='markdown-budget', compact=True, working_context_tokens=1024)
        self.assertEqual(request.working_context_tokens, 1024)
        result = self.result(request, True)
        decision = self.journal.apply_deep(request, result, context_error='working_context_budget_exceeded')
        self.assertFalse(decision.acknowledged)
        self.assertEqual(self.journal.snapshot('primary').revision, 0)
        self.assertEqual(self.journal.context_epoch('primary').version, 0)
        self.assertEqual(self.journal.cursor('primary'), 0)
        self.assertEqual(self.journal.apply_deep(request, result, context_error='working_context_budget_exceeded'), decision)
        with self.assertRaises(EventConflict):
            self.journal.apply_deep(replace(request, working_context_tokens=2048), result, context_error='working_context_budget_exceeded')

    def test_new_dialogue_does_not_invalidate_document(self):
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='late-document')
        newer = self.user('Stop joking about this project.')
        decision = self.journal.apply_deep(request, self.result(request))
        self.assertTrue(decision.acknowledged)
        self.assertEqual(self.journal.cursor('primary'), request.snapshot.through_sequence)
        snapshot = self.journal.fast_snapshot('primary')
        self.assertIn(newer.event_id, [e.event_id for e in snapshot.recent_dialogue])
        from vtuber.context import ContextCompiler
        compiled = ContextCompiler('Current corrections outrank old suggestions.').compile(snapshot, UserMessage('next'))
        self.assertIn('Stop joking about this project.', [m.content for m in compiled.messages])
        self.assertIn('current user corrections take precedence', compiled.messages[-2].content)

    def test_closed_prefix_batching(self):
        first = self.user()
        self.assertIsNone(self.journal.deep_request('primary', request_id='open'))
        second = self.user('second')
        self.finish(first, 'cancelled')
        self.assertIsNone(self.journal.deep_request('primary', request_id='interleaved'))
        terminal = self.finish(second)
        request = self.journal.deep_request('primary', request_id='closed', max_events=1)
        self.assertEqual(request.snapshot.through_sequence, terminal.sequence)
        self.assertEqual(len(request.events), 4)
        self.assertEqual(request.events[-1].payload['text'], 'actual reply')

    def test_deep_atomic_rollback(self):
        from dataclasses import replace
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='atomic', compact=True)
        self.journal._db.execute("CREATE TRIGGER fail_deep BEFORE INSERT ON events WHEN json_extract(NEW.content, '$.kind')='deep.batch.completed' BEGIN SELECT RAISE(FAIL,'test'); END")
        for text in ('# Context\n' + 'x'*1100, ''):
            result = self.result(request, True)
            result = replace(result, note=replace(result.note, note=text))
            with self.assertRaises(Exception):
                self.journal.apply_deep(request, result)
        self.assertEqual(self.journal.snapshot('primary').revision, 0)
        self.assertEqual(self.journal.context_epoch('primary').version, 0)
        self.assertEqual(self.journal.cursor('primary'), 0)
        self.assertEqual(self.journal._db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_deep_replay(self):
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='replay')
        result = self.result(request)
        decision = self.journal.apply_deep(request, result)
        self.assertEqual(self.journal.apply_deep(request, result), decision)
        with self.assertRaises(EventConflict):
            self.journal.apply_deep(request, DeepResult(1, 'replay'))

    def test_budget_rejection_is_durable_and_replayable(self):
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='budget', compact=True)
        decision = self.journal.apply_deep(request, self.result(request, True), compaction_error='context_budget_exceeded')
        self.assertFalse(decision.acknowledged)
        self.assertEqual(self.journal.cursor('primary'), 0)
        self.assertEqual(self.journal.snapshot('primary').revision, 0)
        self.assertEqual(self.journal.context_epoch('primary').version, 0)
        self.assertEqual(self.journal.get('compaction_budget:epoch').kind, 'context.epoch.rejected')

    def test_default_budget_replays_legacy_batch_fingerprint(self):
        from dataclasses import asdict
        from hashlib import sha256
        from vtuber.contracts.events import canonical_json
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='legacy')
        result = self.result(request)
        self.journal.apply_deep(request, result)
        data = asdict(request)
        del data['working_context_tokens']
        legacy = sha256(canonical_json({'request': data, 'result': asdict(result),
            'compaction_error': None}).encode()).hexdigest()
        self.assertEqual(self.journal.get('deep_legacy').payload['fingerprint'], legacy)
        self.assertTrue(self.journal.apply_deep(request, result).acknowledged)

    def test_audit_tail_is_not_observation(self):
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='no-op')
        self.journal.apply_deep(request, DeepResult(1, 'no-op'))
        self.assertIsNone(self.journal.deep_request('primary', request_id='tail'))
        self.assertEqual(self.journal.cursor('primary'), self.journal.high_watermark('primary'))

    def test_stale_reconsideration(self):
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='old', compact=True)
        source = request.events[0].event_id
        self.journal.apply_note(NoteProposal('other', 'primary', 0, 2, (source,), 'other note'))
        decision = self.journal.apply_deep(request, self.result(request, True))
        self.assertFalse(decision.acknowledged)
        self.assertEqual(self.journal.cursor('primary'), 0)
        fresh = self.journal.deep_request('primary', request_id='fresh', compact=True)
        self.assertTrue(self.journal.apply_deep(fresh, self.result(fresh, True)).acknowledged)

    def test_note_only_epoch_dependency_rejects(self):
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='old-note', compact=True)
        self.journal.apply_compaction(self.result(request, True).compaction)
        result = self.journal.apply_deep(request, self.result(request))
        self.assertFalse(result.acknowledged)
        self.assertEqual(result.reason, 'epoch_conflict')
        self.assertEqual(self.journal.snapshot('primary').revision, 0)
        self.assertEqual(self.journal.cursor('primary'), 0)

    def test_late_epoch_preserves_new_turns(self):
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='late', compact=True)
        newer = self.user('green correction')
        self.finish(newer)
        decision = self.journal.apply_deep(request, self.result(request, True))
        self.assertTrue(decision.acknowledged)
        self.assertIn(newer.event_id, [e.event_id for e in self.journal.fast_snapshot('primary').recent_dialogue])
        self.assertEqual(self.journal.snapshot('primary').revision, 1)
        self.assertEqual(self.journal.context_epoch('primary').version, 1)


class DeepWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_does_not_apply_result_from_cancellation_swallowing_adapter(self):
        entered=asyncio.Event()
        class Deep:
            async def propose(self,request):
                entered.set()
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:return DeepResult(1,request.request_id)
        with tempfile.TemporaryDirectory() as folder:
            journal=Journal(Path(folder)/'runtime.db')
            try:
                runtime=Runtime('primary',journal,FakeFast(0),Deep(),lambda _:None)
                await runtime.start()
                await(await runtime.submit(UserMessage('before close')))
                await asyncio.wait_for(entered.wait(),1)
                await asyncio.wait_for(runtime.close(),.2)
                self.assertEqual(journal.cursor('primary'),0)
            finally:journal.close()

    async def test_restart_recovers_user_without_started_event(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'runtime.db'
            journal = Journal(path)
            orphan = UserMessage('accepted before crash')
            journal.append(orphan.as_event())
            journal.close()
            journal = Journal(path)
            class Deep:
                async def propose(self, request): return DeepResult(1,request.request_id)
            try:
                async with Runtime('primary',journal,FakeFast(0),Deep(),lambda _:None) as runtime:
                    await(await runtime.submit(UserMessage('after restart')))
                    for _ in range(100):
                        if journal.cursor('primary')>=journal.high_watermark('primary'):break
                        await asyncio.sleep(.001)
                    terminal=journal.get('reply_terminal_'+orphan.event_id)
                    self.assertIsNotNone(terminal)
                    self.assertEqual(terminal.kind,'character.reply.cancelled')
                    self.assertGreater(journal.cursor('primary'),0)
                    self.assertEqual(journal.unfinished_replies('primary'),())
            finally: journal.close()

    async def test_retry_interrupts_backoff(self):
        entered, again = asyncio.Event(), asyncio.Event()
        class Deep:
            calls = 0
            async def propose(self, request):
                self.calls += 1
                if self.calls > 1: again.set()
                raise ConnectionError()
        async def delay(seconds):
            entered.set()
            await asyncio.Event().wait()
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder)/'runtime.db')
            message = UserMessage('one')
            journal.append(message.as_event())
            journal.append(Event.create('primary','character.reply.completed',{'text':'reply'},turn_id=message.turn_id))
            worker = DeepWorker('primary',journal,Deep(),lambda _:None,timeout=1,context_policy=None,diagnostics={})
            try:
                with patch('vtuber.runtime.deep.retry_delay',side_effect=delay):
                    worker.start()
                    await asyncio.wait_for(entered.wait(),1)
                    worker.retry()
                    await asyncio.wait_for(again.wait(),.2)
            finally:
                await worker.close()
                journal.close()

    async def test_one_worker_coalesces_pressure(self):
        class Policy:
            input_limit = 100
            working_context_tokens = 20
            def validate_working_context(self, text): pass
            def input_tokens(self, snapshot, message): return 75
            def prepare_epoch(self, snapshot, message): return None
            def validate_compaction(self, snapshot, proposal): pass
        class Deep:
            calls = 0
            compactions = []
            async def propose(self, request):
                self.calls += 1
                self.compactions.append(request.compaction)
                return DeepResult(1, request.request_id)
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder)/'runtime.db')
            deep = Deep()
            try:
                async with Runtime('primary', journal, FakeFast(0), deep, lambda _:None,
                                   context_policy=Policy()) as runtime:
                    await (await runtime.submit(UserMessage('one')))
                    await asyncio.sleep(.05)
                    calls = deep.calls
                    self.assertGreater(calls, 0)
                    await asyncio.sleep(.05)
                    self.assertEqual(deep.calls, calls)
                    self.assertTrue(any(deep.compactions))
                    self.assertIsNone(runtime.deep_error)
            finally: journal.close()

    async def test_slow_luna_does_not_gate_fast(self):
        entered, release = asyncio.Event(), asyncio.Event()
        requests = []
        class Deep:
            async def propose(self, request):
                requests.append(request)
                entered.set()
                await release.wait()
                return DeepResult(1, request.request_id, NoteProposal(request.request_id+':note',
                    'primary', request.snapshot.state.revision, request.snapshot.through_sequence,
                    (request.events[0].event_id,), '# Context\nA useful future angle.'))
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder)/'runtime.db')
            try:
                async with Runtime('primary', journal, FakeFast(0), Deep(), lambda _:None) as runtime:
                    await (await runtime.submit(UserMessage('one')))
                    await asyncio.wait_for(entered.wait(), 1)
                    self.assertEqual(requests[0].events[-1].kind, 'character.reply.completed')
                    await asyncio.wait_for(await runtime.submit(UserMessage('two')), 1)
                    self.assertEqual(journal.cursor('primary'), 0)
                    release.set()
                    async with asyncio.timeout(1):
                        while journal.snapshot('primary').revision == 0:
                            await asyncio.sleep(.001)
                    self.assertTrue(all(e.payload['decision']['acknowledged'] for e in
                        journal.read('primary') if e.kind == 'deep.batch.completed'))
                    self.assertEqual(journal.snapshot('primary').context_note, '# Context\nA useful future angle.')
            finally: journal.close()

    async def test_offline_retry_is_bounded(self):
        class Deep:
            calls = 0
            async def propose(self, request):
                self.calls += 1
                raise ConnectionError()
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder)/'runtime.db')
            message = UserMessage('one')
            journal.append(message.as_event())
            journal.append(Event.create('primary', 'character.reply.completed', {'text':'reply'}, turn_id=message.turn_id))
            diagnostics, delays = {}, []
            worker = DeepWorker('primary', journal, Deep(), lambda _:None, timeout=1,
                context_policy=None, diagnostics=diagnostics)
            async def delay(seconds): delays.append(seconds)
            try:
                with patch('vtuber.runtime.deep.retry_delay', side_effect=delay):
                    worker.start()
                    for _ in range(50):
                        await asyncio.sleep(0)
                        if diagnostics.get('degraded'): break
                    self.assertEqual(delays, [1,2,4,8,16])
                    self.assertEqual(worker.mind.calls, 6)
                    self.assertEqual(journal.cursor('primary'), 0)
            finally:
                await worker.close()
                journal.close()

    async def test_pressure_thresholds(self):
        from vtuber.context import ContextCompiler
        from vtuber.contracts.state import FastSnapshot, CharacterState
        compiler = ContextCompiler('identity', token_counter=lambda _:11880)
        snapshot = FastSnapshot(CharacterState('primary'),0,())
        self.assertEqual(compiler.input_tokens(snapshot, UserMessage('hi')), 11880)
        self.assertEqual(compiler.input_limit*3//4, 11880)
