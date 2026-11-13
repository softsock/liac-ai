import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from vtuber.app import Config, open_runtime
from vtuber.contracts.events import UserMessage
from vtuber.tracing import TraceRecorder, read_trace


class TraceTests(unittest.TestCase):
    def test_saved_payload_is_immutable_and_limit_is_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            trace = TraceRecorder(Path(folder), max_bytes=4096)
            payload = {'nested': ['green']}
            trace('fast.context', 'turn', payload)
            payload['nested'].append('blue')
            rows = read_trace(trace.path)
            self.assertEqual(json.loads((trace.path / rows[0]['file']).read_text(encoding='utf-8'))['data'],
                             {'nested': ['green']})
            trace('fast.context', 'too-large', {'text': 'x' * 4096})
            self.assertIn('limit', trace.error)
            self.assertEqual(len(read_trace(trace.path)), 1)

    def test_partial_index_line_is_not_a_completed_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'index.jsonl').write_text('{"kind":', encoding='utf-8')
            self.assertEqual(read_trace(path), [])

    def test_trace_directory_failure_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'not-a-directory'
            root.write_text('occupied', encoding='utf-8')
            trace = TraceRecorder(root)
            trace('fast.context', 'turn', {'prompt': 'hello'})
            self.assertIn('capture stopped', trace.error)

    def test_history_rejects_paths_outside_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'run'
            path.mkdir()
            (root / 'private.json').write_text('{}', encoding='utf-8')
            (path / 'index.jsonl').write_text(json.dumps({'file': '../private.json', 'sequence': 1,
                'kind': 'fast.context', 'request_id': 'turn', 'time': 'today'}) + '\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_trace(path)


class RuntimeTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_capture_is_immutable_bounded_and_off_loop(self):
        from threading import Event
        from vtuber.tracing import QueuedTraceRecorder
        with tempfile.TemporaryDirectory() as folder:
            trace = QueuedTraceRecorder(Path(folder))
            entered, release = Event(), Event()
            original = trace.recorder.__class__.__call__
            from unittest.mock import patch
            def held(writer, *args):
                entered.set()
                release.wait(5)
                original(writer, *args)
            try:
                with patch.object(type(trace.recorder), '__call__', held):
                    data = {'nested': ['green']}
                    trace('test', 'first', data)
                    data['nested'].append('blue')
                    await asyncio.to_thread(entered.wait, 2)
                    for i in range(300):
                        trace('test', str(i), {})
                    self.assertIn('queue', trace.error)
                    async with open_runtime(Config(db=Path(folder)/'db', fast_delay=0), lambda _: None,
                                            trace=trace) as runtime:
                        message = UserMessage('hello')
                        await asyncio.wait_for(await runtime.submit(message), 1)
                        self.assertEqual(runtime.journal.get('reply_terminal_'+message.event_id).kind,
                                         'character.reply.completed')
                    release.set()
                    await trace.aclose()
            finally:
                release.set()
                await trace.aclose()
            self.assertFalse(trace.thread.is_alive())
            row = read_trace(trace.path)[0]
            self.assertEqual(json.loads((trace.path/row['file']).read_text())['data']['nested'], ['green'])

    async def test_user_cancel_preserves_partial_and_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            trace = TraceRecorder(Path(folder) / 'traces')
            chunks = []
            async with open_runtime(Config(db=Path(folder) / 'journal.db', fast_delay=.01),
                                    lambda output: chunks.append(output), trace=trace) as runtime:
                message = UserMessage('long ' * 100)
                await runtime.submit(message)
                async with asyncio.timeout(3):
                    while not any(o.kind == 'reply.delta' for o in chunks):
                        await asyncio.sleep(.005)
                await runtime.cancel_fast()
                terminal = runtime.journal.get('reply_terminal_' + message.event_id)
                self.assertEqual(terminal.payload['reason'], 'user_cancelled')
            row = next(r for r in read_trace(trace.path) if r['kind'] == 'fast.finished')
            data = json.loads((trace.path / row['file']).read_text(encoding='utf-8'))['data']
            self.assertEqual(data['status'], 'cancelled')
            self.assertTrue(data['partial'])
            self.assertEqual(data['text'], '')
    async def test_turn_and_deep_decision_are_correlated(self):
        with tempfile.TemporaryDirectory() as folder:
            trace = TraceRecorder(Path(folder) / 'traces')
            message = UserMessage('green hat')
            async with open_runtime(Config(db=Path(folder) / 'journal.db', fast_delay=0, deep_delay=0),
                                    lambda _: None, trace=trace) as runtime:
                task = await runtime.submit(message)
                await task
                async with asyncio.timeout(3):
                    while runtime.journal.cursor('primary') < 3:
                        await asyncio.sleep(.005)
            rows = read_trace(trace.path)
            self.assertTrue(any(r['kind'] == 'fast.started' and r['request_id'] == message.turn_id for r in rows))
            self.assertTrue(any(r['kind'] == 'fast.finished' and r['request_id'] == message.turn_id for r in rows))
            decisions = [r for r in rows if r['kind'] == 'deep.decision']
            self.assertTrue(decisions)
            data = json.loads((trace.path / decisions[-1]['file']).read_text(encoding='utf-8'))['data']
            self.assertTrue(data['decision']['acknowledged'])
            self.assertEqual(data['after']['state']['context_note'], 'Last user message: green hat')

    async def test_broken_trace_does_not_break_fast_or_deep(self):
        def broken(*args):
            raise OSError('disk unavailable')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertLogs('vtuber.contracts.trace', level='WARNING'):
                async with open_runtime(Config(db=Path(folder) / 'journal.db', fast_delay=0, deep_delay=0),
                                        lambda _: None, trace=broken) as runtime:
                    message = UserMessage('hello')
                    await (await runtime.submit(message))
                    async with asyncio.timeout(3):
                        while runtime.journal.cursor('primary') < 3:
                            await asyncio.sleep(.005)
                    self.assertEqual(runtime.journal.get('reply_terminal_' + message.event_id).kind,
                                     'character.reply.completed')
