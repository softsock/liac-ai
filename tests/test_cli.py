import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from vtuber.app import Config
from vtuber.cli import run
from vtuber.runtime.journal import Journal


class CLITests(unittest.IsolatedAsyncioTestCase):
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
