import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from vtuber.app import Config
from vtuber.app import open_runtime
from vtuber.minds.omp import OMPSettings
from vtuber.contracts.events import UserMessage
import asyncio
from vtuber.cli import run
from vtuber.runtime.journal import Journal


class CLITests(unittest.IsolatedAsyncioTestCase):
    async def test_attention_inspection_and_foreign_source(self):
        from vtuber.contracts.events import Event
        from vtuber.contracts.deep import DeepResult
        from vtuber.contracts.attention import AttentionProposal
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'inspect.db'
            journal = Journal(path)
            try:
                message = UserMessage('Please do not tease me.')
                journal.append(message.as_event())
                journal.append(Event.create('primary', 'character.reply.completed', {'text': 'Understood.'}, turn_id=message.turn_id))
                foreign = journal.append(UserMessage('Private other character', 'other').as_event())
                req = journal.deep_request('primary', request_id='inspect')
                journal.apply_deep(req, DeepResult(2, 'inspect', attention=(AttentionProposal('boundary', 'high',
                    'notice', 'Respect the user boundary.', (message.event_id,)),)))
            finally:
                journal.close()
            async def lines():
                for line in ('/attention noticed 10', '/attention-source ' + message.event_id,
                             '/attention-source ' + foreign.event_id, '/attention nonsense',
                             '/attention 101', '/quit'):
                    yield line
            capture = io.StringIO()
            with patch('vtuber.cli.input_lines', lines), redirect_stdout(capture):
                await run(Config(db=path))
            text = capture.getvalue()
            self.assertIn('Respect the user boundary.', text)
            self.assertIn(message.event_id, text)
            self.assertIn('Please do not tease me.', text)
            self.assertNotIn('Private other character', text)
            self.assertIn('Source not found for this character', text)
            self.assertIn('Usage: /attention', text)

    async def test_missing_omp_does_not_gate_fast(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Config(db=Path(folder)/'test.db', fast_delay=0, deep_backend='luna',
                omp=OMPSettings(executable=str(Path(folder)/'missing.exe'),data_dir=Path(folder)/'omp'))
            async with open_runtime(config, lambda _:None) as runtime:
                await asyncio.wait_for(await runtime.submit(UserMessage('hello')), 1)
                await asyncio.sleep(.1)
                self.assertEqual(runtime.journal.snapshot('primary').revision, 0)
                self.assertEqual(len(runtime.journal.recent_dialogue('primary')), 2)

    async def test_cli_preserves_whitespace_of_user_input(self):
        text = '    indented code\t  '
        async def lines():
            yield text
            yield ' /quit '
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cli.sqlite3'
            with patch('vtuber.cli.input_lines', lines), redirect_stdout(io.StringIO()):
                await run(Config(db=path))
            journal = Journal(path)
            try:
                user, = [e for e in journal.read('primary') if e.kind == 'user.message.completed']
                self.assertEqual(user.payload['text'], text)
            finally:
                journal.close()
