"""SQLite owns the document; the file is an atomic, recoverable projection."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vtuber.app import Config, open_runtime
from vtuber.contracts.events import UserMessage
from vtuber.runtime.context_file import context_file_path, write_context


class ContextFileTests(unittest.TestCase):
    def test_exact_bytes_and_failed_replacement_preserves_document(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'nested'/'context.md'
            write_context(path, '# Context\r\n🙂\r\n')
            expected = '# Context\r\n🙂\r\n'.encode('utf-8')
            self.assertEqual(path.read_bytes(), expected)
            with patch('vtuber.runtime.context_file.os.replace', side_effect=OSError):
                with self.assertRaises(OSError):
                    write_context(path, 'replacement')
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(list(path.parent.iterdir()), [path])
            write_context(path, '')
            self.assertEqual(path.read_bytes(), b'')

    def test_paths_isolate_databases_and_untrusted_character_ids(self):
        root = Path('example').resolve()
        first = context_file_path(root/'one.db', '../../escape')
        self.assertTrue(first.is_relative_to(root/'one.db.contexts'))
        self.assertEqual(first.name, 'context.md')
        self.assertNotEqual(first, context_file_path(root/'two.db', '../../escape'))
        self.assertNotEqual(first, context_file_path(root/'one.db', 'primary'))


class ContextRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_joins_writer_without_blocking_fast(self):
        import threading
        from vtuber.runtime.journal import Journal
        from vtuber.runtime.orchestrator import Runtime
        from vtuber.minds.fake import FakeFast, FakeDeep
        entered, release = threading.Event(), threading.Event()
        def held_write(path, text):
            entered.set()
            release.wait(2)
            write_context(path, text)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'context.md'
            journal = Journal(Path(folder)/'runtime.db')
            runtime = Runtime('primary', journal, FakeFast(0), FakeDeep(10), lambda _: None,
                              context_path=path)
            try:
                with patch('vtuber.runtime.deep.write_context', side_effect=held_write):
                    await runtime.start()
                    async with asyncio.timeout(1):
                        while not entered.is_set():
                            await asyncio.sleep(.001)
                    await asyncio.wait_for(await runtime.submit(UserMessage('Fast stays available.')), 1)
                    closing = asyncio.create_task(runtime.close())
                    await asyncio.sleep(.02)
                    self.assertFalse(closing.done())
                    release.set()
                    await asyncio.wait_for(closing, 1)
                    self.assertEqual(path.read_bytes(), b'')
            finally:
                release.set()
                await runtime.close()
                journal.close()

    async def test_restart_repairs_file_and_export_failure_keeps_committed_state(self):
        async def until(predicate):
            async with asyncio.timeout(2):
                while not predicate():
                    await asyncio.sleep(.005)
        with tempfile.TemporaryDirectory() as folder:
            config = Config(db=Path(folder)/'runtime.db', fast_delay=0, deep_delay=0)
            path = context_file_path(config.db, 'primary')
            with patch('vtuber.runtime.deep.write_context', side_effect=OSError('private detail')):
                async with open_runtime(config, lambda _: None) as runtime:
                    await (await runtime.submit(UserMessage('Remember the green hat.')))
                    await until(lambda: runtime.journal.snapshot('primary').revision == 1)
                    await until(lambda: runtime.deep_diagnostics.get('context_export_error') == 'OSError')
                    state = runtime.journal.snapshot('primary')
                    cursor = runtime.journal.cursor('primary')
                    self.assertGreater(cursor, 0)
                    self.assertNotIn('private detail', str(runtime.deep_diagnostics))
            write_context(path, 'stale file is not authoritative')
            async with open_runtime(config, lambda _: None) as runtime:
                await until(lambda: path.read_text(encoding='utf-8') == state.context_note)
                self.assertEqual(runtime.journal.snapshot('primary'), state)
                self.assertGreaterEqual(runtime.journal.cursor('primary'), cursor)
                self.assertEqual(runtime.journal._db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
