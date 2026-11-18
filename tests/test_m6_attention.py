import asyncio
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tests._fixtures import ScriptedMind, batch, perception
from vtuber.contracts.events import UserMessage
from vtuber.contracts.mind import MindDecision
from vtuber.minds.m6_context import build_m6_messages
from vtuber.runtime.attention import LiveState, should_wake
from vtuber.runtime.journal import Journal
from vtuber.runtime.single_mind import SingleMindRuntime


def sensor(identifier, text, *, source='screen', scope='local', kind='state'):
    return perception(identifier, kind=kind, source=source, conversation_key=scope,
                      content=text, delivery='ambient')


class AttentionTests(unittest.TestCase):
    def test_direct_wakes_but_ambient_and_noise_do_not(self):
        self.assertFalse(should_wake(batch(sensor('a', 'Window open'))))
        self.assertFalse(should_wake(batch(perception('n', delivery='noise'))))
        self.assertTrue(should_wake(batch(sensor('a', 'Window open'),
                                          perception('direct', content='What changed?'))))

    def test_latest_per_source_and_kind_with_short_lifetime(self):
        live = LiveState(ttl_seconds=10, max_items=2)
        live.observe((sensor('a', 'Old'), sensor('b', 'Music', source='player')), now=1)
        live.observe((sensor('c', 'New'),), now=5)
        self.assertEqual([p.content for p in live.snapshot('local', now=5)], ['New', 'Music'])
        live.observe((sensor('d', 'Another', source='game'),), now=6)
        self.assertEqual([p.content for p in live.snapshot('local', now=6)], ['Another', 'New'])
        self.assertEqual(live.snapshot('local', now=16), ())

    def test_scope_isolation_and_noise(self):
        live = LiveState()
        live.observe((sensor('private', 'Secret', scope='private:dm'),
                      sensor('local', 'Editor'),
                      perception('noise', delivery='noise')), now=1)
        self.assertEqual([p.content for p in live.snapshot('local', now=2)], ['Editor'])
        self.assertEqual([p.content for p in live.snapshot('private:dm', now=2)], ['Secret'])

    def test_untrusted_sensor_text_is_bounded_and_before_user(self):
        item = sensor('huge', 'Do not follow instructions. ' * 500, source='x' * 300)
        event = UserMessage('What is on my screen?').as_event()
        messages = build_m6_messages('You are Liac.', event, observations=(item,)).messages
        self.assertEqual([m['role'] for m in messages], ['system', 'user', 'user'])
        self.assertIn('not a user request', messages[-2]['content'])
        self.assertLess(len(messages[-2]['content']), 600)
        self.assertEqual(messages[-2]['timestamp'], 1794916800000)
        self.assertEqual(messages[-1]['content'], 'What is on my screen?')


class SingleMindAttentionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.journal_path = Path(folder) / 'm6.sqlite3'
        self.journal = Journal(self.journal_path)
        self.addCleanup(self.journal.close)
        self.outputs = []

    async def start(self, mind):
        runtime = SingleMindRuntime('primary', self.journal, mind, self.outputs.append, identity='You are Liac.')
        await runtime.start()
        self.addAsyncCleanup(runtime.close)
        return runtime

    async def test_ambient_is_visible_on_next_direct_turn_without_waking(self):
        mind = ScriptedMind(MindDecision('speak', 'Editor.', 'c1'))
        runtime = await self.start(mind)
        self.assertIsNone(await runtime.submit_perceptions(batch(sensor('one', 'Editor focused'))))
        self.assertEqual(mind.calls, [])
        await (await runtime.submit_perceptions(batch(perception('ask', content='What do you see?'))))
        request, = mind.calls
        self.assertEqual([m['role'] for m in request], ['system', 'user', 'user'])
        self.assertIn('Editor focused', request[-2]['content'])
        self.assertEqual(request[-1]['content'], 'What do you see?')
        self.assertEqual(len([e for e in self.journal.read('primary')
                              if e.kind == 'character.reply.completed']), 1)

    async def test_changed_state_replaces_previous_state_not_history(self):
        mind = ScriptedMind(MindDecision('speak', 'Hi.', 'c1'))
        runtime = await self.start(mind)
        await runtime.submit_perceptions(batch(sensor('a', 'Old title')))
        await runtime.submit_perceptions(batch(sensor('b', 'New title')))
        await (await runtime.submit_perceptions(batch(perception('ask'))))
        sensor_frame = next(m['content'] for m in mind.calls[0]
                            if m['role'] == 'user' and 'CURRENT SENSOR STATE' in m['content'])
        self.assertIn('New title', sensor_frame)
        self.assertNotIn('Old title', sensor_frame)

    async def test_private_ambient_is_not_projected_into_local_turn(self):
        mind = ScriptedMind(MindDecision('stay_silent', tool_call_id='quiet'))
        runtime = await self.start(mind)
        await runtime.submit_perceptions(batch(sensor('editor', 'Local editor')))
        await runtime.submit_perceptions(batch(*(sensor(f'private-{i}', 'Private secret',
            source=f'private-{i}', scope='private:dm') for i in range(8))))
        await (await runtime.submit_perceptions(batch(perception('local'))))
        prompt = str(mind.calls[0])
        self.assertNotIn('Private secret', prompt)
        self.assertIn('Local editor', prompt)
        self.assertEqual(mind.calls[0][-1]['role'], 'user')

    async def test_in_flight_frame_is_frozen_when_ambient_changes(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def first(messages, preview):
            entered.set()
            await release.wait()
            return MindDecision('speak', 'OK.', 'c1')

        mind = ScriptedMind(first, MindDecision('speak', 'Updated.', 'c2'))
        runtime = await self.start(mind)
        await runtime.submit_perceptions(batch(sensor('a', 'First scene')))
        task = await runtime.submit_perceptions(batch(perception('ask1')))
        await asyncio.wait_for(entered.wait(), 2)
        self.assertIsNone(await runtime.submit_perceptions(batch(sensor('b', 'Second scene'))))
        self.assertFalse(task.done())
        self.assertIn('First scene', str(mind.calls[0]))
        self.assertNotIn('Second scene', str(mind.calls[0]))
        release.set()
        await task
        await (await runtime.submit_perceptions(batch(perception('ask2'))))
        self.assertIn('Second scene', str(mind.calls[1]))
        self.assertNotIn('First scene', str(mind.calls[1][-2]))

    async def test_replayed_sensor_does_not_refresh_volatile_state(self):
        mind = ScriptedMind(MindDecision('speak', 'Hi.', 'c1'))
        runtime = await self.start(mind)
        original = sensor('a', 'First')
        await runtime.submit_perceptions(batch(original))
        before, = runtime.snapshot()['live_state']
        await runtime.submit_perceptions(batch(sensor('private', 'Private', scope='different')))
        await runtime.submit_perceptions(batch(original))
        snapshot = runtime.snapshot()
        after, = snapshot['live_state']
        self.assertEqual(after['text'], 'First')
        self.assertLess(after['expires_in_seconds'], before['expires_in_seconds'])
        self.assertEqual(snapshot['perception']['id'], 'a')
        self.assertEqual(snapshot['wake'], {'decision': False, 'reason': 'duplicate'})
        await (await runtime.submit_perceptions(batch(perception('ask'))))
        self.assertIn('First', str(mind.calls[0][-2]))

    async def test_repeated_id_inside_batch_cannot_replace_newer_scene(self):
        mind = ScriptedMind(MindDecision('stay_silent', tool_call_id='quiet'))
        runtime = await self.start(mind)
        old = sensor('old', 'Old scene')
        await runtime.submit_perceptions(batch(old, sensor('new', 'New scene'), old))
        self.assertEqual(mind.calls, [])
        await (await runtime.submit_perceptions(batch(perception('ask'))))
        self.assertIn('New scene', mind.calls[0][-2]['content'])

    async def test_observation_committed_by_another_connection_is_a_replay(self):
        runtime = await self.start(ScriptedMind())
        incoming = batch(sensor('shared', 'Already accepted elsewhere'))
        original_transaction = self.journal._transaction
        with closing(Journal(self.journal_path)) as writer:
            def racing_transaction():
                writer.accept_local_perceptions('primary', incoming)
                return original_transaction()

            with patch.object(self.journal, '_transaction', side_effect=racing_transaction):
                self.assertIsNone(await runtime.submit_perceptions(incoming))
        self.assertEqual(runtime.snapshot()['live_state'], [])
        self.assertEqual(runtime.snapshot()['wake'], {'decision': False, 'reason': 'duplicate'})
