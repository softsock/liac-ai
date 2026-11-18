import asyncio
import io
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests._fixtures import ScriptedMind
from vtuber.contracts.mind import MindDecision
from vtuber.m6 import FakeSingleMind, run_console
from vtuber.runtime.journal import Journal


class M6ConsoleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db = Path(directory) / 'm6.sqlite3'
        self.output = self.enterContext(redirect_stdout(io.StringIO()))

    def events(self, kind):
        with closing(Journal(self.db)) as journal:
            return tuple(event for event in journal.read('primary') if event.kind == kind)

    async def test_fake_console_burst_one_reply(self):
        async def lines():
            for line in ('first', 'second', '/quit'):
                yield line

        with patch('vtuber.m6.input_lines', lines):
            await run_console(self.db, FakeSingleMind())
        user, = self.events('user.message.completed')
        reply, = self.events('character.reply.completed')
        self.assertEqual(user.payload['text'], 'first\nsecond')
        self.assertEqual(reply.payload['action'], 'speak')
        rendered = self.output.getvalue()
        self.assertEqual(rendered.count('[Provisional] '), 1)
        self.assertEqual(rendered.count('[Final] '), 1)

    async def test_quit_drains_then_closes(self):
        entered = asyncio.Event()
        finish = asyncio.Event()

        async def lines():
            for line in ('last', '/quit', 'ignored'):
                yield line

        async def silence(messages, preview):
            entered.set()
            await finish.wait()
            return MindDecision('stay_silent', tool_call_id='quiet')

        with patch('vtuber.m6.input_lines', lines):
            async with asyncio.TaskGroup() as group:
                console = group.create_task(run_console(self.db, ScriptedMind(silence)))
                await asyncio.wait_for(entered.wait(), 2)
                self.assertFalse(console.done())
                finish.set()
        user, = self.events('user.message.completed')
        reply, = self.events('character.reply.completed')
        self.assertEqual(user.payload['text'], 'last')
        self.assertEqual(reply.payload['action'], 'stay_silent')
        self.assertNotIn('[Final]', self.output.getvalue())


    async def test_manual_scene_updates_next_context_without_speaking(self):
        async def lines():
            yield '/scene Window shows a puzzle'
            yield 'What is visible?'
            yield '/quit'

        mind = ScriptedMind(MindDecision('speak', 'A puzzle.', 'call-scene'))
        with patch('vtuber.m6.input_lines', lines):
            await run_console(self.db, mind)
        self.assertEqual(len(mind.calls), 1)
        self.assertIn('Window shows a puzzle', str(mind.calls[0][-2]))
        self.assertEqual(mind.calls[0][-1]['content'], 'What is visible?')
        self.assertEqual(len(self.events('user.message.completed')), 1)
        self.assertEqual(len(self.events('character.reply.completed')), 1)

    async def test_stdin_keeps_reading_during_generation(self):
        entered = asyncio.Event()

        async def lines():
            yield 'first'
            await asyncio.wait_for(entered.wait(), 3)
            yield 'second'
            yield '/quit'

        async def held(messages, preview):
            entered.set()
            await asyncio.Future()

        mind = ScriptedMind(held, MindDecision('speak', 'Current', 'new'))
        with patch('vtuber.m6.input_lines', lines):
            await asyncio.wait_for(run_console(self.db, mind), 4)
        cancelled, = self.events('character.reply.cancelled')
        completed, = self.events('character.reply.completed')
        self.assertEqual(cancelled.payload['reason'], 'superseded')
        self.assertEqual(completed.payload['text'], 'Current')
