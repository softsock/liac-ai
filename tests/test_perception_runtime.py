import asyncio
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from tests._fixtures import batch, perception
from vtuber.context import ContextCompiler
from vtuber.contracts.deep import DeepResult
from vtuber.contracts.events import Event, UserMessage
from vtuber.minds.fake import FakeDeep, FakeFast
from vtuber.runtime.journal import EventConflict, Journal
from vtuber.runtime.orchestrator import Runtime
from vtuber.runtime.perception_bus import PerceptionBus


class RecordingFast:
    def __init__(self, hold=False):
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        if not hold:
            self.release.set()

    async def stream(self, snapshot, message):
        self.calls.append((snapshot, message))
        self.entered.set()
        await self.release.wait()
        async for chunk in FakeFast(0).stream(snapshot, message):
            yield chunk


class RecordingDeep:
    def __init__(self):
        self.requests = []

    async def propose(self, request):
        self.requests.append(request)
        return DeepResult(3, request.request_id)


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.001)


class PerceptionJournalTests(unittest.TestCase):
    def setUp(self):
        self.journal = Journal(':memory:')
        self.addCleanup(self.journal.close)

    def test_append_many_is_atomic_on_conflict(self):
        existing = Event.create('primary', 'perception.received', {'text': 'first'}, event_id='existing')
        self.journal.append(existing)
        new = Event.create('primary', 'perception.received', {'text': 'new'}, event_id='new')
        with self.assertRaises(EventConflict):
            self.journal.append_many((new, replace(existing, source='conflicting')))
        self.assertIsNone(self.journal.get('new'))
        self.assertEqual(self.journal.high_watermark('primary'), 1)

    def test_append_many_preserves_sequence_and_idempotency(self):
        events = tuple(Event.create('primary', 'perception.received', {'text': str(i)},
                                   event_id=f'raw-{i}') for i in range(3))
        stored = self.journal.append_many(events)
        self.assertEqual([e.sequence for e in stored], [1, 2, 3])
        self.assertEqual(self.journal.append_many(events), stored)
        self.assertEqual(self.journal.high_watermark('primary'), 3)
        self.assertEqual(self.journal.append_many(()), ())

    def test_raw_perceptions_are_not_deep_observations(self):
        message = UserMessage('canonical chat')
        raw = Event.create('primary', 'perception.received', {'content': 'ambient secret'})
        terminal = Event.create('primary', 'character.reply.completed', {'text': 'reply'}, turn_id=message.turn_id)
        self.journal.append_many((message.as_event(), raw, terminal))
        request = self.journal.deep_request('primary', request_id='observations')
        self.assertEqual([e.kind for e in request.events],
                         ['user.message.completed', 'character.reply.completed'])
        self.assertEqual(request.snapshot.through_sequence, 3)


class PerceptionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'perceptions.sqlite3'
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        self.outputs = []

    async def start(self, *, fast=None, deep=None, compiler=None):
        runtime = Runtime('primary', self.journal, fast or FakeFast(0),
                          deep or FakeDeep(100), self.outputs.append, context_policy=compiler)
        await runtime.start()
        self.addAsyncCleanup(runtime.close)
        return runtime

    def events(self, kind):
        return tuple(e for e in self.journal.read('primary', limit=1000) if e.kind == kind)

    async def test_three_local_messages_one_fast_reply(self):
        fast = RecordingFast()
        runtime = await self.start(fast=fast)
        await (await runtime.submit_perceptions(batch(
            perception('1', content='first'), perception('2', content='second'),
            perception('3', content='third'))))
        self.assertEqual(len(fast.calls), 1)
        self.assertEqual(fast.calls[0][1].text, 'first\nsecond\nthird')
        self.assertEqual(len(self.events('perception.received')), 3)
        self.assertEqual(len(self.events('user.message.completed')), 1)
        self.assertEqual(len(self.events('character.reply.completed')), 1)
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())

    async def test_each_raw_event_has_provenance(self):
        runtime = await self.start()
        original = perception('source-id', content='  exact\nraw text  ', author_id='user-17', dedupe_key='stable')
        await (await runtime.submit_perceptions(batch(original)))
        raw = self.journal.get('source-id')
        self.assertEqual(raw.kind, 'perception.received')
        self.assertEqual(raw.payload, asdict(original))
        self.assertEqual(raw.source, 'local')
        self.assertEqual(raw.occurred_at, original.occurred_at)
        self.assertIsNone(raw.turn_id)
        self.assertEqual(self.events('user.message.completed')[0].payload['text'], original.content)

    async def test_replay_does_not_speak_twice(self):
        fast = RecordingFast()
        runtime = await self.start(fast=fast)
        first, second, third = (perception(str(i), content=f'line {i}') for i in range(3))
        await (await runtime.submit_perceptions(batch(first, second)))
        self.assertIsNone(await runtime.submit_perceptions(batch(second, first)))
        await (await runtime.submit_perceptions(batch(first, third, third)))
        self.assertIsNone(await runtime.submit_perceptions(batch(third)))
        self.assertEqual([message.text for _, message in fast.calls], ['line 0\nline 1', 'line 2'])
        self.assertEqual(len(self.events('perception.received')), 3)
        self.assertEqual(len(self.events('character.reply.completed')), 2)

    async def test_conflicting_replay_rolls_back_new_raw_and_dialogue(self):
        fast = RecordingFast()
        runtime = await self.start(fast=fast)
        first = perception('known')
        await (await runtime.submit_perceptions(batch(first)))
        before = self.journal.high_watermark('primary')
        with self.assertRaises(EventConflict):
            await runtime.submit_perceptions(batch(perception('new'), replace(first, content='conflict')))
        self.assertIsNone(self.journal.get('new'))
        self.assertEqual(self.journal.high_watermark('primary'), before)
        self.assertEqual(len(fast.calls), 1)
        with self.assertRaises(EventConflict):
            await runtime.submit_perceptions(batch(perception('same'), perception('same', content='different')))
        self.assertIsNone(self.journal.get('same'))

    async def test_ambient_only_never_starts_fast(self):
        fast, deep = RecordingFast(), RecordingDeep()
        runtime = await self.start(fast=fast, deep=deep)
        ambient = perception('ambient', kind='observation', source='sensor', delivery='ambient')
        self.assertIsNone(await runtime.submit_perceptions(batch(ambient, perception('noise', delivery='noise'))))
        await asyncio.sleep(.02)
        self.assertEqual([e.event_id for e in self.events('perception.received')], ['ambient'])
        self.assertEqual(self.events('user.message.completed'), ())
        self.assertEqual(fast.calls, [])
        self.assertEqual(deep.requests, [])

    async def test_active_fast_snapshot_unchanged_by_ambient(self):
        fast = RecordingFast(hold=True)
        runtime = await self.start(fast=fast)
        active = await runtime.submit_perceptions(batch(perception('chat')))
        await asyncio.wait_for(fast.entered.wait(), 1)
        snapshot = fast.calls[0][0]
        frozen = asdict(snapshot)
        await runtime.submit_perceptions(batch(perception('live', delivery='ambient', kind='observation')))
        self.assertFalse(active.done())
        self.assertEqual(asdict(snapshot), frozen)
        self.assertEqual(self.journal.fast_snapshot('primary').recent_dialogue, snapshot.recent_dialogue)
        fast.release.set()
        await active
        self.assertEqual(len(self.events('character.reply.completed')), 1)
        self.assertEqual(self.events('character.reply.cancelled'), ())

    async def test_other_conversation_not_merged(self):
        runtime = await self.start()
        for changes in ({'conversation_key': 'other'}, {'source': 'discord'}, {'kind': 'voice'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                await runtime.submit_perceptions(batch(perception('unsupported', **changes)))
        with self.assertRaises(ValueError):
            await runtime.submit_perceptions(batch(perception('a', author_id='a'), perception('b', author_id='b')))
        self.assertEqual(self.journal.high_watermark('primary'), 0)
        ambient = perception('other-ambient', conversation_key='other', delivery='ambient')
        self.assertIsNone(await runtime.submit_perceptions(batch(ambient)))
        await (await runtime.submit_perceptions(batch(perception('local'))))
        self.assertEqual(self.events('user.message.completed')[0].payload['text'], 'hello')

    async def test_incomplete_group_recovered_after_restart(self):
        fast = RecordingFast()
        runtime = await self.start(fast=fast)
        original = batch(perception('crash-1'), perception('crash-2'))
        with patch.object(runtime, '_start_fast', side_effect=RuntimeError('simulated crash')):
            with self.assertRaises(RuntimeError):
                await runtime.submit_perceptions(original)
        message, = self.events('user.message.completed')
        self.assertIsNone(self.journal.get(f'reply_started_{message.event_id}'))
        await runtime.close()
        self.journal.close()
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        restarted = await self.start(fast=fast)
        terminal = self.journal.get(f'reply_terminal_{message.event_id}')
        self.assertEqual(terminal.kind, 'character.reply.cancelled')
        self.assertEqual(terminal.payload['reason'], 'process_restarted')
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())
        self.assertEqual(len(self.events('perception.received')), 2)
        self.assertIsNone(await restarted.submit_perceptions(original))
        self.assertEqual(fast.calls, [])

    async def test_deep_sees_one_completed_group(self):
        deep = RecordingDeep()
        runtime = await self.start(deep=deep)
        # Both a same-batch ambient item and an earlier one must stay audit-only.
        await runtime.submit_perceptions(batch(perception('earlier', content='private ambient', delivery='ambient')))
        await (await runtime.submit_perceptions(batch(perception('1'), perception('2'),
            perception('mixed', content='mixed ambient', delivery='ambient'))))
        await until(lambda: bool(deep.requests))
        await asyncio.sleep(.02)
        self.assertEqual(len(deep.requests), 1)
        request, = deep.requests
        self.assertEqual(sum(e.kind == 'user.message.completed' for e in request.events), 1)
        self.assertEqual(sum(e.kind == 'character.reply.completed' for e in request.events), 1)
        self.assertFalse(any(e.kind == 'perception.received' for e in request.events))
        self.assertEqual(len(request.snapshot.terminal_turns), 1)
        self.assertIsNone(self.journal.deep_request('primary', request_id='settled'))
        await runtime.submit_perceptions(batch(perception('later', delivery='ambient')))
        await (await runtime.submit(UserMessage('ordinary path still works')))
        await until(lambda: len(deep.requests) == 2)
        self.assertFalse(any(e.kind == 'perception.received' for e in deep.requests[-1].events))

    async def test_ambient_backlog_does_not_strand_next_dialogue(self):
        deep = RecordingDeep()
        runtime = await self.start(deep=deep)
        await asyncio.sleep(0)
        await runtime.submit_perceptions(batch(*(perception(f'ambient-{i}', delivery='ambient')
                                                  for i in range(250))))
        self.assertEqual(deep.requests, [])
        await (await runtime.submit_perceptions(batch(perception('after-backlog'))))
        await until(lambda: len(deep.requests) == 1)
        terminal, = self.events('character.reply.completed')
        self.assertGreaterEqual(self.journal.cursor('primary'), terminal.sequence)
        self.assertFalse(any(e.kind == 'perception.received' for e in deep.requests[0].events))
        await asyncio.sleep(.02)
        self.assertEqual(len(deep.requests), 1)

    async def test_group_does_not_change_hot_cold_selector(self):
        compiler = ContextCompiler('Identity', token_counter=lambda ms: sum(len(m.content) for m in ms))
        runtime = await self.start(compiler=compiler)
        await (await runtime.submit(UserMessage('old ' * 250)))
        await (await runtime.submit_perceptions(batch(perception('hot-1', content='x' * 600),
                                                       perception('hot-2', content='y' * 600))))
        users = self.events('user.message.completed')
        terminals = self.events('character.reply.completed')
        self.assertEqual(len(users), 2)
        snapshot = self.journal.fast_snapshot('primary')
        self.assertEqual(compiler.semantic_cutoff(snapshot), terminals[0].sequence)
        request = self.journal.deep_request('primary', request_id='compact-group', compact=True,
                                            cutoff_selector=compiler.semantic_cutoff)
        self.assertEqual(request.compaction.cutoff, terminals[0].sequence)
        self.assertEqual([e.event_id for e in request.compaction.events],
                         [users[0].event_id, terminals[0].event_id])
        self.assertEqual(snapshot.recent_dialogue[-2].payload['text'], 'x' * 600 + '\n' + 'y' * 600)

    async def test_direct_group_supersedes_active_fast_once(self):
        fast = RecordingFast(hold=True)
        runtime = await self.start(fast=fast)
        first = UserMessage('old stream')
        active = await runtime.submit(first)
        await asyncio.wait_for(fast.entered.wait(), 1)
        replacement = await runtime.submit_perceptions(batch(perception('new-1'), perception('new-2')))
        self.assertTrue(active.cancelled())
        self.assertEqual(self.journal.get(f'reply_terminal_{first.event_id}').payload['reason'], 'superseded')
        fast.release.set()
        await replacement
        self.assertEqual(len(fast.calls), 2)
        self.assertEqual(len(self.events('character.reply.cancelled')), 1)
        self.assertEqual(len(self.events('character.reply.completed')), 1)

    async def test_closed_runtime_rejects_without_persisting(self):
        runtime = await self.start()
        await runtime.close()
        with self.assertRaises(RuntimeError):
            await runtime.submit_perceptions(batch(perception()))
        self.assertEqual(self.journal.high_watermark('primary'), 0)

    async def test_live_like_burst_full_pipeline(self):
        async with asyncio.timeout(3):
            fast, deep = RecordingFast(), RecordingDeep()
            runtime = await self.start(fast=fast, deep=deep)
            bus = PerceptionBus(text_gap=.06, live_gap=.02, max_window=1)
            draining = asyncio.create_task(bus.drain())
            self.addAsyncCleanup(bus.close)
            try:
                for i, text in enumerate(('first line', 'second line', 'third line')):
                    await bus.publish(perception(f'pipeline-{i}', content=text))
                    await asyncio.sleep(.015)
                grouped = await draining
                await (await runtime.submit_perceptions(grouped))
            finally:
                draining.cancel()
                await asyncio.gather(draining, return_exceptions=True)
            terminal, = self.events('character.reply.completed')
            await until(lambda: self.journal.cursor('primary') >= terminal.sequence)
            self.assertEqual([e.event_id for e in self.events('perception.received')],
                             ['pipeline-0', 'pipeline-1', 'pipeline-2'])
            user, = self.events('user.message.completed')
            self.assertEqual(user.payload['text'], 'first line\nsecond line\nthird line')
            self.assertEqual(user.turn_id, terminal.turn_id)
            self.assertEqual(self.journal.unfinished_inputs('primary'), ())
            self.assertEqual(self.journal.fast_snapshot('primary').terminal_turns,
                             ((user.turn_id, terminal.sequence),))
            self.assertEqual(len(deep.requests), 1)
            self.assertEqual(len(fast.calls), 1)
            await bus.publish(perception('pipeline-ambient', kind='observation', delivery='ambient'))
            self.assertFalse(await bus.publish(perception('pipeline-noise', delivery='noise')))
            self.assertIsNone(await runtime.submit_perceptions(await bus.drain()))
            await asyncio.sleep(.03)
            self.assertEqual(len(deep.requests), 1)
            self.assertEqual(len(fast.calls), 1)
            self.assertIsNotNone(self.journal.get('pipeline-ambient'))
            self.assertIsNone(self.journal.get('pipeline-noise'))
            self.assertIsNone(self.journal.deep_request('primary', request_id='no-extra-loop'))
            await bus.close()
            self.assertIsNone(await bus.drain())
