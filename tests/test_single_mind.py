import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from tests._fixtures import ScriptedMind, batch, perception
from vtuber.contracts.events import Event, UserMessage
from vtuber.contracts.mind import MindDecision
from vtuber.runtime.journal import Journal
from vtuber.runtime.single_mind import SingleMindRuntime


class SingleMindRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / 'runtime.sqlite3'
        self.journal = Journal(self.path)
        self.addCleanup(lambda: self.journal.close())
        self.outputs = []

    async def start(self, mind):
        runtime = SingleMindRuntime('primary', self.journal, mind, self.outputs.append, identity='You are Liac.')
        await runtime.start()
        self.addAsyncCleanup(runtime.close)
        return runtime

    def events(self, kind, *, limit=100):
        return tuple(event for event in self.journal.read('primary', limit=limit) if event.kind == kind)

    async def test_direct_burst_starts_one_luna_turn(self):
        async def speak(messages, preview):
            user, = self.events('user.message.completed')
            started, = self.events('character.reply.started')
            self.assertEqual(started.event_id, f'reply_started_{user.event_id}')
            self.assertEqual(started.causation_id, user.event_id)
            self.assertEqual([m['content'] for m in messages if m['role'] == 'user'], ['first\nsecond'])
            preview('Hel')
            self.assertFalse(self.events('character.reply.completed'))
            return MindDecision('speak', 'Hello!', 'speak-id')

        mind = ScriptedMind(speak)
        runtime = await self.start(mind)
        await (await runtime.submit_perceptions(batch(perception('one', content='first'),
                                                       perception('two', content='second'))))
        user, = self.events('user.message.completed')
        terminal, = self.events('character.reply.completed')
        self.assertEqual(terminal.event_id, f'reply_terminal_{user.event_id}')
        self.assertEqual(terminal.turn_id, user.turn_id)
        self.assertEqual(terminal.payload, {'text': 'Hello!', 'action': 'speak', 'tool_call_id': 'speak-id',
                                            'snapshot_revision': 0})
        self.assertEqual([(out.kind, out.text) for out in self.outputs],
                         [('reply.started', ''), ('reply.delta', 'Hel'), ('reply.completed', 'Hello!')])
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())
        self.assertEqual(len(mind.calls), 1)

    async def test_ambient_only_no_inference(self):
        mind = ScriptedMind()
        runtime = await self.start(mind)
        self.assertIsNone(await runtime.submit_perceptions(batch(perception('ambient', delivery='ambient'),
                                                                  perception('noise', delivery='noise'))))
        ambient, = self.events('perception.received')
        self.assertEqual(ambient.event_id, 'ambient')
        self.assertEqual(mind.calls, [])
        self.assertEqual(self.outputs, [])

    async def test_replay_no_second_speech(self):
        mind = ScriptedMind(MindDecision('speak', 'Hi', 'once'))
        runtime = await self.start(mind)
        incoming = batch(perception('same'))
        await (await runtime.submit_perceptions(incoming))
        self.assertIsNone(await runtime.submit_perceptions(incoming))
        self.assertEqual(len(self.events('character.reply.completed')), 1)
        self.assertEqual(len(mind.calls), 1)

    async def test_silence_is_completed_without_text(self):
        runtime = await self.start(ScriptedMind(MindDecision('stay_silent', tool_call_id='quiet')))
        await (await runtime.submit_perceptions(batch(perception('quiet'))))
        terminal, = self.events('character.reply.completed')
        self.assertEqual(terminal.payload['action'], 'stay_silent')
        self.assertEqual(terminal.payload['text'], '')
        self.assertEqual([(out.kind, out.text) for out in self.outputs],
                         [('reply.started', ''), ('reply.completed', '')])

    async def test_superseded_turn_cannot_emit_late_text(self):
        entered = asyncio.Event()
        previous_callbacks = []

        async def old_turn(messages, preview):
            previous_callbacks.append(preview)
            preview('Provisional')
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                preview('Late')
                return MindDecision('speak', 'Stale result', 'stale')

        runtime = await self.start(ScriptedMind(old_turn, MindDecision('speak', 'Current', 'current')))
        old_task = await runtime.submit_perceptions(batch(perception('old')))
        await asyncio.wait_for(entered.wait(), 1)
        newest = await runtime.submit_perceptions(batch(perception('new')))
        await newest
        previous_callbacks[0]('Very late')
        self.assertTrue(old_task.done())
        old, = self.events('character.reply.cancelled')
        current, = self.events('character.reply.completed')
        self.assertEqual(old.payload, {'reason': 'superseded', 'snapshot_revision': 0})
        self.assertEqual(current.payload['text'], 'Current')
        self.assertEqual([out.text for out in self.outputs if out.kind == 'reply.delta'], ['Provisional'])

    async def test_restart_closes_unfinished_without_regeneration(self):
        prior = UserMessage('Earlier question')
        self.journal.append_many((prior.as_event(), Event.create('primary',
            'character.reply.completed', {'text': 'Earlier answer', 'action': 'speak', 'tool_call_id': 'old-call'},
            turn_id=prior.turn_id, causation_id=prior.event_id)))
        before_start = self.journal.accept_local_perceptions('primary', batch(perception('accepted')))
        after_start = self.journal.accept_local_perceptions('primary', batch(perception('already-visible')))
        self.journal.append(Event.create('primary', 'character.reply.started', {'snapshot_revision': 7},
                            event_id=f'reply_started_{after_start.event_id}', turn_id=after_start.turn_id,
                            causation_id=after_start.event_id))
        self.journal.close()
        self.journal = Journal(self.path)
        mind = ScriptedMind(MindDecision('stay_silent', tool_call_id='quiet'))
        runtime = await self.start(mind)
        self.assertIsNone(await runtime.submit_perceptions(batch(perception('already-visible',
            occurred_at=after_start.occurred_at))))
        recovered = self.events('character.reply.cancelled')
        self.assertEqual([e.causation_id for e in recovered], [before_start.event_id, after_start.event_id])
        self.assertEqual([e.payload for e in recovered], [
            {'reason': 'process_restarted', 'snapshot_revision': revision} for revision in (0, 7)])
        self.assertFalse(mind.calls)
        self.assertFalse(self.outputs)
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())
        await (await runtime.submit_perceptions(batch(perception('new', content='Latest'))))
        _, previous_user, call, result, latest = mind.calls[0]
        self.assertEqual((previous_user['content'], latest['content']), ('Earlier question', 'Latest'))
        self.assertEqual((call['content'][0]['id'], result['toolCallId']), ('old-call', 'old-call'))

    async def test_only_complete_tool_call_commits(self):
        async def interrupted(messages, preview):
            preview('Incomplete')
            raise RuntimeError('Private provider diagnostic')

        runtime = await self.start(ScriptedMind(interrupted, MindDecision('speak', 'Missing ID')))
        await (await runtime.submit_perceptions(batch(perception('interrupted'))))
        await (await runtime.submit_perceptions(batch(perception('missing-id'))))
        self.assertEqual(self.events('character.reply.completed'), ())
        failures = self.events('character.reply.failed')
        self.assertEqual(len(failures), 2)
        self.assertTrue(all('text' not in e.payload for e in failures))
        self.assertEqual(failures[0].payload['reason'], 'RuntimeError')
        self.assertNotIn('Private provider diagnostic', json.dumps(runtime.snapshot()))

    async def test_close_before_generation_leaves_a_terminal(self):
        mind = ScriptedMind()
        runtime = await self.start(mind)
        task = await runtime.submit_perceptions(batch(perception('closing')))
        await runtime.close()
        self.assertTrue(task.cancelled())
        self.assertEqual(mind.calls, [])
        terminal, = self.events('character.reply.cancelled')
        self.assertEqual(terminal.payload['reason'], 'shutdown')
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())

    async def test_task_cancelled_before_generation_closes_turn(self):
        mind = ScriptedMind()
        runtime = await self.start(mind)
        task = await runtime.submit_perceptions(batch(perception('cancel-before-start')))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(mind.calls, [])
        self.assertEqual(runtime.snapshot()['runtime'], {'state': 'idle', 'turn_id': None})
        terminal, = self.events('character.reply.cancelled')
        self.assertEqual(terminal.payload['reason'], 'cancelled')

    async def test_replays_last_twenty_completed_turns_despite_cancelled_inputs(self):
        for i in range(21):
            user = UserMessage(f'Question {i}')
            self.journal.append_many((user.as_event(), Event.create('primary',
                'character.reply.completed', {'text': f'Legacy reply {i}'}, turn_id=user.turn_id)))
        for i in range(41):
            user = UserMessage(f'Cancelled {i}')
            self.journal.append_many((user.as_event(), Event.create('primary',
                'character.reply.cancelled', {'reason': 'superseded'}, turn_id=user.turn_id)))
        mind = ScriptedMind(MindDecision('stay_silent', tool_call_id='quiet'))
        runtime = await self.start(mind)
        await (await runtime.submit_perceptions(batch(perception('current', content='Latest'))))
        request, = mind.calls
        self.assertEqual([item['content'] for item in request if item['role'] == 'user'],
                         [f'Question {i}' for i in range(1, 21)] + ['Latest'])
        self.assertEqual([item['content'][0]['text'] for item in request if item['role'] == 'assistant'],
                         [f'Legacy reply {i}' for i in range(1, 21)])
        self.assertEqual(len(self.events('character.reply.cancelled', limit=150)), 41)
        self.assertTrue(runtime.snapshot()['context']['older_history_omitted'])

    async def test_snapshot_tracks_turn_and_observes_committed_terminal(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def speak(messages, preview):
            preview('Hello')
            entered.set()
            await release.wait()
            return MindDecision('speak', 'Hello', 'call', {'input': 12, 'output': 4})

        runtime = await self.start(ScriptedMind(speak))
        self.assertEqual(runtime.snapshot()['runtime'], {'state': 'idle', 'turn_id': None})
        terminal_snapshots = []

        def output(event):
            if event.kind == 'reply.completed':
                terminal_snapshots.append((runtime.snapshot(), self.events('character.reply.completed')))

        runtime.output = output
        task = await runtime.submit_perceptions(batch(perception('hello')))
        await asyncio.wait_for(entered.wait(), 1)
        active = runtime.snapshot()
        turn, = self.events('user.message.completed')
        self.assertEqual(active['runtime'], {'state': 'generating', 'turn_id': turn.turn_id})
        self.assertEqual(active['perception']['id'], 'hello')
        self.assertEqual(active['wake'], {'decision': True, 'reason': 'new_direct'})
        self.assertIsNone(active['generation']['first_tool_delta_ms'])
        frame, = runtime.mind.calls
        frame_bytes = len(json.dumps(frame, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        self.assertEqual(active['context']['frame_bytes'], frame_bytes)
        self.assertEqual(active['context']['history_turns'], 0)
        json.dumps(active)
        release.set()
        await task
        (terminal, commits), = terminal_snapshots
        self.assertEqual(len(commits), 1)
        self.assertEqual(terminal['runtime'], {'state': 'idle', 'turn_id': None})
        self.assertEqual(terminal['generation']['last_action'], 'speak')
        self.assertGreaterEqual(terminal['generation']['duration_ms'], 0)
        terminal['generation']['usage']['input'] = -1
        self.assertEqual(runtime.snapshot()['generation']['usage']['input'], 12)

    async def test_snapshot_records_safe_failure_and_next_short_turn_recovers(self):
        mind = ScriptedMind(MindDecision('stay_silent', tool_call_id='quiet'))
        runtime = await self.start(mind)
        await (await runtime.submit_perceptions(batch(perception('large', content='x' * 65_000))))
        failed = runtime.snapshot()
        self.assertEqual(mind.calls, [])
        self.assertEqual(failed['runtime'], {'state': 'failed', 'turn_id': None})
        self.assertEqual(failed['errors']['code'], 'ContextBudgetExceeded')
        self.assertIsNone(failed['context']['frame_bytes'])
        await (await runtime.submit_perceptions(batch(perception('short', content='Latest'))))
        self.assertEqual([m['role'] for m in mind.calls[0]], ['system', 'user'])
        self.assertEqual(runtime.snapshot()['runtime']['state'], 'idle')
        self.assertEqual(runtime.snapshot()['generation']['last_action'], 'stay_silent')
