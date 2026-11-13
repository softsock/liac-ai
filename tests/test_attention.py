import json
import asyncio
import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import replace

from vtuber.contracts.deep import DeepRequest
from vtuber.contracts.deep import DeepResult
from vtuber.contracts.attention import AttentionProposal
from vtuber.contracts.events import Event
from vtuber.contracts.state import CharacterState, FastSnapshot
from vtuber.minds.luna import parse_result
from vtuber.runtime.journal import Journal, EventConflict


def proposal(**changes):
    return dict(kind='opportunity', significance='normal', outcome='notice',
                reason='An optional shared joke, not a command.', source_event_ids=['source'],
                ttl_seconds=300, target_signal_id=None, target_version=None, supersedes=[], **changes)


class AttentionProtocolTests(unittest.TestCase):
    def setUp(self):
        event = replace(Event.create('primary', 'user.message.completed', {'text': 'lost match'},
                                    event_id='source'), sequence=1)
        self.request = DeepRequest('request', FastSnapshot(CharacterState('primary'), 1, (event,)), 0, (event,))

    def parse(self, values):
        return parse_result(json.dumps(dict(schema_version=2, note=None, compaction=None, attention=values)), self.request)

    def test_attention_outcomes_and_empty(self):
        self.assertEqual(self.parse([]).attention, ())
        for outcome in ('notice', 'defer', 'ignore'):
            value = proposal()
            value['outcome'] = outcome
            result = self.parse([value])
            self.assertEqual(result.attention[0].outcome, outcome)
            self.assertEqual(result.attention[0].source_event_ids, ('source',))

    def test_attention_untrusted_fields(self):
        for field, value in [('kind', []), ('outcome', 'execute'), ('significance', 'urgent'),
                             ('ttl_seconds', True), ('ttl_seconds', 86401), ('ttl_seconds', 0),
                             ('source_event_ids', ['foreign']), ('source_event_ids', ['source'] * 2),
                             ('target_signal_id', 'invented'), ('target_version', True),
                             ('supersedes', ['invented']), ('reason', 'x' * 1001), ('signal_id', 'authority')]:
            item = proposal()
            item[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.parse([item])
        with self.assertRaises(ValueError):
            self.parse([proposal()] * 17)


class AttentionJournalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'attention.db'
        self.now = datetime.now(timezone.utc)
        self.journal = Journal(self.path)
        self.addCleanup(lambda: self.journal.close())

    def turn(self, text='lost match', character='primary'):
        from vtuber.contracts.events import UserMessage
        message = UserMessage(text, character)
        source = self.journal.append(message.as_event())
        self.journal.append(Event.create(character, 'character.reply.completed', {'text': 'noted'},
                                        turn_id=message.turn_id))
        return source

    def request(self, name='request'):
        return self.journal.deep_request('primary', request_id=name)

    def result(self, request, source, **changes):
        values = dict(kind='opportunity', significance='normal', outcome='notice', reason='Optional joke.',
                      source_event_ids=(source.event_id,), ttl_seconds=300)
        values.update(changes)
        return DeepResult(2, request.request_id, attention=(AttentionProposal(**values),))

    def test_atomic_replay_and_deduplication(self):
        source = self.turn()
        req = self.request()
        result = self.result(req, source)
        decision = self.journal.apply_deep(req, result)
        self.assertTrue(decision.acknowledged)
        self.assertEqual(self.journal.apply_deep(req, result), decision)
        with self.assertRaises(EventConflict):
            self.journal.apply_deep(req, replace(result, attention=()))
        self.turn('again')
        req2 = self.request('second')
        self.journal.apply_deep(req2, self.result(req2, source, reason='Paraphrased idea.'))
        signals = self.journal.attention_signals('primary')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_id, decision.attention_signal_ids[0])
        self.assertIsNone(self.request('audit-only'))

    def test_rollback_with_cursor_and_lifecycle(self):
        from vtuber.contracts.context import CompactionProposal, ContextItem
        from vtuber.contracts.state import NoteProposal
        source = self.turn()
        req = self.journal.deep_request('primary', request_id='combined', compact=True)
        result = replace(self.result(req, source), note=NoteProposal('combined:note', 'primary', 0,
            req.snapshot.through_sequence, (source.event_id,), 'Keep the correction.'),
            compaction=CompactionProposal('combined:epoch', 'primary', 0, 0, req.snapshot.through_sequence,
                req.compaction.cutoff, (ContextItem('A completed match.', (source.event_id,), 'summary'),)))
        self.journal._db.execute("CREATE TRIGGER fail_deep BEFORE INSERT ON events WHEN json_extract(NEW.content, '$.kind')='deep.batch.completed' BEGIN SELECT RAISE(FAIL,'test'); END")
        with self.assertRaises(Exception):
            self.journal.apply_deep(req, result)
        self.assertEqual(self.journal.attention_signals('primary'), ())
        self.assertEqual(self.journal.cursor('primary'), 0)
        self.assertEqual(self.journal.snapshot('primary').revision, 0)
        self.assertEqual(self.journal.context_epoch('primary').version, 0)
        self.assertFalse(any(e.kind.startswith('attention.') for e in self.journal.read('primary')))

    def test_target_update_supersedes_and_priority(self):
        source = self.turn()
        req = self.request()
        self.journal.apply_deep(req, self.result(req, source, outcome='defer'))
        old, = self.journal.attention_signals('primary')
        correction = self.turn('Please stop teasing me.')
        req = self.request('correction')
        self.assertEqual(req.attention_context[0], old)
        self.assertIn(source.event_id, [e.event_id for e in req.attention_sources])
        self.journal.apply_deep(req, self.result(req, correction, kind='boundary', significance='high',
                                               ttl_seconds=None, supersedes=(old.signal_id,)))
        candidates = self.journal.attention_candidates('primary')
        self.assertEqual([s.kind for s in candidates.signals], ['boundary'])
        self.assertEqual(candidates.through_sequence, req.snapshot.through_sequence)
        self.assertEqual(self.journal.attention_signals('primary', status='superseded')[0].signal_id, old.signal_id)
        self.turn('boundary repeated')
        req2 = self.request('update')
        boundary = candidates.signals[0]
        self.journal.apply_deep(req2, self.result(req2, correction, kind='boundary', ttl_seconds=None,
            target_signal_id=boundary.signal_id, target_version=boundary.version, outcome='defer'))
        updated = self.journal.attention_signals('primary', status='deferred')[0]
        self.assertEqual(updated.version, 2)
        self.assertIn(correction.event_id, updated.source_event_ids)

    def test_foreign_sources_and_stale_target_rejected(self):
        source = self.turn()
        foreign = self.turn('private', 'other')
        req = self.request()
        with self.assertRaises(ValueError):
            self.journal.apply_deep(req, self.result(req, foreign))
        self.assertEqual(self.journal.cursor('primary'), 0)
        self.journal.apply_deep(req, self.result(req, source))
        old, = self.journal.attention_signals('primary')
        self.turn('next')
        req = self.request('stale')
        with self.assertRaises(ValueError):
            self.journal.apply_deep(req, self.result(req, source, target_signal_id=old.signal_id, target_version=True))

    def test_expiry_during_analysis_does_not_revive_with_wall_clock_rollback(self):
        self.journal.close()
        ticks = [0.0]
        wall = [datetime.now(timezone.utc)]
        self.journal = Journal(self.path, clock=lambda: wall[0], monotonic=lambda: ticks[0])
        source = self.turn()
        req = self.request()
        self.journal.apply_deep(req, self.result(req, source, ttl_seconds=5))
        old, = self.journal.attention_signals('primary')
        self.turn('next')
        req = self.request('after')
        ticks[0] = 6
        wall[0] -= timedelta(hours=1)
        with self.assertRaises(ValueError):
            self.journal.apply_deep(req, self.result(req, source, ttl_seconds=None,
                target_signal_id=old.signal_id, target_version=old.version))

    def test_conflicting_operations_cannot_partially_supersede(self):
        source = self.turn()
        req = self.request()
        self.journal.apply_deep(req, self.result(req, source))
        old, = self.journal.attention_signals('primary')
        correction = self.turn('stop joking')
        req = self.request('conflict')
        first = self.result(req, correction, kind='boundary', supersedes=(old.signal_id,)).attention[0]
        second = replace(first, kind='correction')
        with self.assertRaises(ValueError):
            self.journal.apply_deep(req, DeepResult(2, req.request_id, attention=(first, second)))
        self.assertEqual(self.journal.attention_signals('primary')[0].status, 'noticed')

    def test_expiry_restart_and_clock_rollback(self):
        source = self.turn()
        req = self.request()
        self.journal.apply_deep(req, self.result(req, source, ttl_seconds=1))
        self.journal.close()
        self.journal = Journal(self.path, clock=lambda: self.now + timedelta(seconds=10))
        self.assertEqual(self.journal.expire_attention('primary'), 1)
        self.assertEqual(self.journal.expire_attention('primary'), 0)
        self.assertEqual(self.journal.attention_candidates('primary').signals, ())
        self.journal.close()
        self.journal = Journal(self.path, clock=lambda: self.now - timedelta(seconds=10))
        self.assertEqual(self.journal.attention_signals('primary')[0].status, 'expired')

    def test_v2_migration_and_read_bounds(self):
        source = self.turn()
        self.journal._db.execute('PRAGMA user_version=2')
        self.journal.close()
        self.journal = Journal(self.path)
        self.assertEqual(self.journal.get(source.event_id), source)
        self.assertEqual(self.journal._db.execute('PRAGMA user_version').fetchone()[0], 3)
        for limit in (0, 101, True):
            with self.assertRaises(ValueError):
                self.journal.attention_signals('primary', limit=limit)

    def test_same_evidence_cannot_extend_or_remove_expiry(self):
        source = self.turn()
        req = self.request()
        self.journal.apply_deep(req, self.result(req, source, ttl_seconds=300))
        original, = self.journal.attention_signals('primary')
        for index, ttl in enumerate((86400, None)):
            self.turn('unrelated new input')
            req = self.request('extend' + str(index))
            current, = self.journal.attention_signals('primary')
            self.journal.apply_deep(req, self.result(req, source, ttl_seconds=ttl,
                target_signal_id=current.signal_id, target_version=current.version))
            updated, = self.journal.attention_signals('primary')
            self.assertEqual(updated.expires_at, original.expires_at)

    def test_historical_provenance_remains_deduplicated_after_update(self):
        first = self.turn('A')
        req = self.request()
        self.journal.apply_deep(req, self.result(req, first))
        for index, name in enumerate(('B', 'C')):
            second = self.turn(name)
            req = self.request('update' + name)
            old, = self.journal.attention_signals('primary')
            self.journal.apply_deep(req, self.result(req, second,
                target_signal_id=old.signal_id, target_version=old.version))
            if index == 0:
                intermediate, = self.journal.attention_signals('primary')
        self.journal.close()
        self.journal = Journal(self.path)
        for index, sources in enumerate(((first.event_id,), intermediate.source_event_ids)):
            self.turn('paraphrase')
            req = self.request('duplicate' + str(index))
            self.journal.apply_deep(req, self.result(req, first, source_event_ids=sources, reason='A again'))
            self.assertEqual(len(self.journal.attention_signals('primary')), 1)

    def test_expiry_rollback_preserves_monotonic_deadlines(self):
        self.journal.close()
        ticks, wall = [0.0], [datetime.now(timezone.utc)]
        self.journal = Journal(self.path, clock=lambda: wall[0], monotonic=lambda: ticks[0])
        source = self.turn()
        req = self.request()
        first = self.result(req, source, ttl_seconds=5).attention[0]
        self.journal.apply_deep(req, DeepResult(2, req.request_id,
            attention=(first, replace(first, kind='topic_change'))))
        self.journal._db.execute("""CREATE TRIGGER fail_expiry BEFORE INSERT ON events
            WHEN json_extract(NEW.content, '$.kind')='attention.signal.expired'
            AND (SELECT COUNT(*) FROM events WHERE json_extract(content, '$.kind')='attention.signal.expired')=1
            BEGIN SELECT RAISE(FAIL,'second expiry'); END""")
        ticks[0] = 6
        wall[0] -= timedelta(hours=1)
        with self.assertRaises(Exception):
            self.journal.expire_attention('primary')
        self.journal._db.execute('DROP TRIGGER fail_expiry')
        self.assertEqual(self.journal.expire_attention('primary'), 2)
        self.assertEqual(len(self.journal.attention_signals('primary', status='expired')), 2)

    def test_monotonic_expiry_survives_wall_clock_rollback(self):
        self.journal.close()
        ticks = [0.0]
        wall = [datetime.now(timezone.utc)]
        self.journal = Journal(self.path, clock=lambda: wall[0], monotonic=lambda: ticks[0])
        source = self.turn()
        req = self.request()
        self.journal.apply_deep(req, self.result(req, source, ttl_seconds=5))
        self.journal.expire_attention('primary')
        ticks[0] = 6
        wall[0] -= timedelta(hours=1)
        self.assertEqual(self.journal.expire_attention('primary'), 1)

    def test_legacy_audit_replay(self):
        from dataclasses import asdict
        from hashlib import sha256
        from vtuber.contracts.events import canonical_json
        self.turn()
        req = self.request('legacy')
        request_dict = {k: v for k, v in asdict(req).items() if k not in ('attention_context', 'attention_sources')}
        result_dict = {'schema_version': 1, 'request_id': 'legacy', 'note': None, 'compaction': None}
        fingerprint = sha256(canonical_json({'request': request_dict, 'result': result_dict,
                                             'compaction_error': None}).encode()).hexdigest()
        decision = dict(request_id='legacy', note=None, compaction=None, acknowledged=True, reason='applied')
        self.journal.append(Event.create('primary', 'deep.batch.completed',
            {'fingerprint': fingerprint, 'decision': decision}, event_id='deep_legacy'))
        replay = self.journal.apply_deep(req, DeepResult(1, 'legacy'))
        self.assertTrue(replay.acknowledged)
        self.assertEqual(replay.attention_signal_ids, ())


class AttentionWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_batches_preserve_correction_and_fast_independence(self):
        from vtuber.contracts.events import UserMessage
        from vtuber.minds.fake import FakeFast
        from vtuber.runtime.orchestrator import Runtime
        entered, release, done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        requests = []
        active = 0
        maximum = 0

        class Mind:
            async def propose(self, req):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                requests.append(req)
                try:
                    if len(requests) == 1:
                        entered.set()
                        await release.wait()
                        source = next(e for e in req.events if e.kind == 'user.message.completed')
                        return DeepResult(2, req.request_id, attention=(AttentionProposal('opportunity', 'low',
                            'defer', 'Wait for a better moment.', (source.event_id,), 300),))
                    signal, = req.attention_context
                    source = next(e for e in req.events if e.kind == 'user.message.completed')
                    return DeepResult(2, req.request_id, attention=(AttentionProposal('boundary', 'high',
                        'notice', 'The user asked to stop teasing.', (source.event_id,), supersedes=(signal.signal_id,)),))
                finally:
                    active -= 1

        completions = []
        def output(item):
            if item.kind == 'deep.completed':
                completions.append(item)
                if len(completions) == 2:
                    done.set()

        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / 'busy.db')
            try:
                async with Runtime('primary', journal, FakeFast(0), Mind(), output) as runtime:
                    await (await runtime.submit(UserMessage('I lost the match.')))
                    await asyncio.wait_for(entered.wait(), 1)
                    correction = UserMessage('Please stop teasing.')
                    await asyncio.wait_for(await runtime.submit(correction), 1)
                    self.assertEqual(len(requests), 1)
                    release.set()
                    await asyncio.wait_for(done.wait(), 1)
                    self.assertEqual(maximum, 1)
                    self.assertIn(correction.event_id, [e.event_id for e in requests[1].events])
                    self.assertEqual(journal.attention_candidates('primary').signals[0].kind, 'boundary')
                    self.assertEqual(runtime.deep_diagnostics['attention_pending'], 1)
                    self.assertIsNone(journal.deep_request('primary', request_id='no-poll'))
            finally:
                journal.close()
