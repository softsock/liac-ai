import asyncio
import json
import os
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from tests._fixtures import ScriptedMind
from vtuber.contracts.events import Event
from vtuber.contracts.mind import MindDecision
from vtuber.runtime.journal import Journal


def request(identifier, op, **fields):
    return json.dumps({'id': identifier, 'op': op, **fields}, ensure_ascii=False).encode() + b'\n'


class HubProcessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db = Path(directory) / 'hub.sqlite3'

    async def start(self, *arguments):
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-X', 'utf8', '-m', 'vtuber.hub', '--db', str(self.db), *arguments,
            env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)},
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=1024 * 1024,
        )

        async def cleanup():
            if process.returncode is None:
                process.kill()
            await process.communicate()

        self.addAsyncCleanup(cleanup)
        return process

    async def frame(self, process):
        line = await asyncio.wait_for(process.stdout.readline(), 5)
        if not line:
            self.fail((await process.stderr.read()).decode())
        return json.loads(line)

    async def send(self, process, data):
        process.stdin.write(data)
        await asyncio.wait_for(process.stdin.drain(), 5)

    async def test_unicode_chat_and_scene_update_context_once_and_replay_after_restart(self):
        process = await self.start('--backend', 'fake')
        self.assertEqual(await self.frame(process), {'type': 'ready', 'version': 1})
        await self.send(process, request(1, 'set_scene', text='Синя чашка ☕'))
        self.assertEqual(await self.frame(process), {'type': 'response', 'id': 1, 'ok': True, 'result': None})
        await self.send(process, request(2, 'inspect'))
        inspection = (await self.frame(process))['result']
        self.assertEqual(inspection['snapshot']['wake']['reason'], 'ambient_only')
        self.assertEqual(inspection['snapshot']['live_state'][0]['text'], 'Синя чашка ☕')
        self.assertEqual(inspection['dialogue'], [])

        await self.send(process, request(3, 'send_chat', text='Привіт 🦉'))
        turn = (await self.frame(process))['result']['turn_id']
        outputs = [(await self.frame(process))['output'] for _ in range(3)]
        self.assertEqual([out['kind'] for out in outputs], ['reply.started', 'reply.delta', 'reply.completed'])
        self.assertTrue(all(out['turn_id'] == turn for out in outputs))
        self.assertEqual(outputs[-1]['text'], 'You said: Привіт 🦉')
        await self.send(process, request(4, 'inspect'))
        inspection = (await self.frame(process))['result']
        self.assertTrue(inspection['snapshot']['context']['sensor_included'])
        dialogue = inspection['dialogue']
        self.assertEqual([event['text'] for event in dialogue], ['Привіт 🦉', 'You said: Привіт 🦉'])
        self.assertEqual(dialogue[-1]['action'], 'speak')
        self.assertEqual(set(dialogue[-1]), {'sequence', 'event_id', 'turn_id', 'kind', 'source',
                                            'occurred_at', 'text', 'action'})
        self.assertEqual([event['kind'] for event in inspection['activity']],
                         ['character.reply.completed', 'character.reply.started', 'user.message.completed',
                          'perception.received', 'perception.received'])

        await self.send(process, request(5, 'shutdown'))
        self.assertEqual((await self.frame(process))['id'], 5)
        self.assertEqual(await asyncio.wait_for(process.wait(), 5), 0)
        restarted = await self.start('--backend', 'fake')
        await self.frame(restarted)
        await self.send(restarted, request(1, 'inspect'))
        restored = (await self.frame(restarted))['result']
        self.assertEqual(restored['dialogue'], dialogue)
        self.assertEqual(restored['snapshot']['live_state'], [])
        restarted.stdin.close()
        self.assertEqual(await asyncio.wait_for(restarted.wait(), 5), 0)

    async def test_bad_and_overlong_frames_do_not_consume_next_request(self):
        process = await self.start('--backend', 'fake')
        await self.frame(process)
        await self.send(process, b'{\xff}\n' + request(1, 'unknown') + request(2, 'send_chat', text='  ')
                        + request(3, 'set_scene', text='🦉' * 2049)
                        + b'{"id":4,"op":"send_chat","text":"\\ud800"}\n'
                        + (b'x' * 150_000) + b'\n' + request(5, 'inspect'))
        failures = [await self.frame(process) for _ in range(6)]
        self.assertEqual([(frame['id'], frame['error']) for frame in failures],
                         [(None, 'invalid_frame'), (1, 'invalid_request'), (2, 'invalid_text'),
                          (3, 'text_too_large'), (4, 'invalid_text'), (None, 'frame_too_large')])
        self.assertTrue(all(frame['type'] == 'response' and frame['ok'] is False for frame in failures))
        self.assertEqual((await self.frame(process))['result']['activity'], [])
        await self.send(process, request(6, 'shutdown'))
        await self.frame(process)
        self.assertEqual(await asyncio.wait_for(process.wait(), 5), 0)

    async def test_dialogue_preserves_full_eight_kib_chat_and_echo(self):
        process = await self.start('--backend', 'fake')
        await self.frame(process)
        prompt = 'é' * 4096
        await self.send(process, request(1, 'send_chat', text=prompt))
        self.assertTrue((await self.frame(process))['ok'])
        outputs = [(await self.frame(process))['output'] for _ in range(3)]
        self.assertEqual(outputs[-1]['text'], 'You said: ' + prompt)
        await self.send(process, request(2, 'inspect'))
        dialogue = (await self.frame(process))['result']['dialogue']
        self.assertEqual([event['text'] for event in dialogue], [prompt, 'You said: ' + prompt])
        process.stdin.close()
        self.assertEqual(await asyncio.wait_for(process.wait(), 5), 0)

    async def test_recent_views_exclude_unprojected_events_and_keep_frames_bounded(self):
        def seed():
            with closing(Journal(self.db)) as journal:
                journal.append_many(tuple(Event.create('primary', kind, {'text': text}, turn_id=f'turn-{i}')
                    for i in range(80)
                    for kind, text in (('user.message.completed', f'{i} ' + '\x01' * 9_000),
                                       ('character.reply.completed', '\x02' * 9_000),
                                       ('deep.result', 'private'))))

        await asyncio.to_thread(seed)
        process = await self.start('--backend', 'fake')
        await self.frame(process)
        await self.send(process, request(1, 'inspect'))
        result = (await self.frame(process))['result']
        activity, dialogue = result['activity'], result['dialogue']
        self.assertEqual((len(activity), len(dialogue)), (100, 40))
        self.assertEqual((activity[0]['sequence'], activity[-1]['sequence']), (239, 91))
        self.assertEqual((dialogue[0]['sequence'], dialogue[-1]['sequence']), (181, 239))
        for events, limit in ((activity, 512), (dialogue, 16 * 1024)):
            for event in events:
                self.assertTrue(event['text'].endswith('…'))
                self.assertLessEqual(len(json.dumps(event['text'], ensure_ascii=False).encode()) - 2, limit)
        self.assertGreater(len(json.dumps(dialogue[0]['text'], ensure_ascii=False).encode()) - 2, 8192)
        self.assertTrue(dialogue[0]['text'].startswith('60 \x01'))
        process.stdin.close()
        self.assertEqual(await asyncio.wait_for(process.wait(), 5), 0)

    async def test_missing_bun_is_a_structured_startup_failure(self):
        process = await self.start('--backend', 'luna', '--bun', str(self.db / 'missing-bun.exe'))
        self.assertEqual(await self.frame(process), {'type': 'fatal', 'error': 'bun_not_found'})
        self.assertNotEqual(await asyncio.wait_for(process.wait(), 5), 0)


class HubRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cancels_in_flight_after_a_silent_turn_was_committed(self):
        from vtuber.hub import run_hub

        entered = asyncio.Event()
        cancelled = asyncio.Event()
        silent = asyncio.Event()
        frames = []

        async def hold(messages, preview):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        async def requests():
            yield request(1, 'send_chat', text='First turn')
            await silent.wait()
            yield request(2, 'send_chat', text='Hold this turn')
            await entered.wait()
            yield request(3, 'shutdown')

        def emit(frame):
            frames.append(frame)
            if frame.get('output', {}).get('kind') == 'reply.completed':
                silent.set()

        directory = self.enterContext(tempfile.TemporaryDirectory())
        db = Path(directory) / 'hub.sqlite3'
        mind = ScriptedMind(MindDecision('stay_silent', tool_call_id='quiet'), hold)
        await asyncio.wait_for(run_hub(db, mind, requests(), emit), 5)
        self.assertTrue(cancelled.is_set())
        outputs = [frame['output'] for frame in frames if frame['type'] == 'output']
        self.assertEqual([(out['kind'], out['text']) for out in outputs], [
            ('reply.started', ''), ('reply.completed', ''), ('reply.started', ''), ('reply.cancelled', 'shutdown'),
        ])
        response = frames[-1]
        self.assertEqual((response['type'], response['id'], response['ok']), ('response', 3, True))
        inspection = response['result']
        self.assertIsInstance(inspection, dict)
        self.assertEqual(set(inspection), {'snapshot', 'activity', 'dialogue'})
        self.assertEqual(inspection['snapshot']['runtime'], {'state': 'idle', 'turn_id': None})
        terminal = inspection['dialogue'][-1]
        self.assertEqual((terminal['kind'], terminal['turn_id'], terminal['text']),
                         ('character.reply.cancelled', outputs[-1]['turn_id'], 'shutdown'))
        self.assertEqual(inspection['activity'][0], terminal)
        with closing(Journal(db)) as journal:
            terminals = [event for event in journal.read('primary')
                         if event.kind in ('character.reply.completed', 'character.reply.cancelled')]
            self.assertEqual([(event.kind, event.payload.get('action')) for event in terminals],
                             [('character.reply.completed', 'stay_silent'), ('character.reply.cancelled', None)])
