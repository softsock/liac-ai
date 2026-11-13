import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from vtuber.app import Config, open_runtime
from vtuber.contracts.events import UserMessage


class ArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_preserves_history_and_has_one_owner(self):
        from vtuber.lab.archive import RunArchive,RunReader
        with tempfile.TemporaryDirectory() as folder:
            config = Config(fast_delay=0,deep_delay=0)
            archive = await asyncio.to_thread(RunArchive.create,Path(folder),config,scenario={'id':'test'})
            with self.assertRaises(ValueError):
                await asyncio.to_thread(RunArchive.resume,archive.path)
            async with open_runtime(Config(db=archive.db,fast_delay=0,deep_delay=0),archive.observe_output,
                                    trace=archive.trace) as runtime:
                await (await runtime.submit(UserMessage('hello')))
                await runtime.close()
                await archive.capture(runtime)
            await archive.close('stopped')
            resumed = await asyncio.to_thread(RunArchive.resume,archive.path)
            await resumed.close('stopped')
            reader = RunReader(archive.path)
            self.assertEqual(len(reader.manifest['segments']),2)
            self.assertEqual(len([r for r in reader.conversation if r['role']=='user']),1)

    async def test_initiative_links_back_to_its_luna_proposal(self):
        from vtuber.lab.archive import RunReader
        from vtuber.tracing import TraceRecorder
        with tempfile.TemporaryDirectory() as folder:
            trace = TraceRecorder(Path(folder))
            trace('deep.started','deep_idea',{'request':{'events':[{'turn_id':'user1'}]}})
            trace('fast.started','autonomous',{'message':{'proposal_id':'initiative_deep_idea'}})
            reader = RunReader(trace.path)
            self.assertIn('deep.started',[r['kind'] for r in reader.related('autonomous')])

    async def test_context_at_turn_survives_correction_and_compaction(self):
        from vtuber.lab.archive import RunArchive, RunReader
        with tempfile.TemporaryDirectory() as folder:
            archive = await asyncio.to_thread(RunArchive.create, Path(folder), Config())
            async with open_runtime(Config(db=archive.db, fast_delay=0, deep_delay=0),
                                    archive.observe_output, trace=archive.trace) as runtime:
                first = UserMessage('Version 1')
                await (await runtime.submit(first))
                await archive.capture(runtime)
                for _ in range(100):
                    if runtime.journal.snapshot('primary').revision:
                        break
                    await asyncio.sleep(.01)
                second = UserMessage('Correction: Version 2')
                await (await runtime.submit(second))
                await runtime.close()
                await archive.capture(runtime)
            await archive.close('completed')
            reader = RunReader(archive.path)
            self.assertEqual(len(reader.page('conversation')), 4)
            linked = reader.related(first.turn_id)
            fast = next(r for r in linked if r['kind'] == 'fast.started')
            self.assertEqual(fast['data']['snapshot']['state']['context_note'], '')
            self.assertEqual(reader.context_at(fast['data']['snapshot']['through_sequence'])['markdown'], '')
            self.assertTrue(reader.related(second.turn_id))

    async def test_interrupted_and_legacy_run_are_read_only(self):
        from vtuber.lab.archive import RunReader
        from vtuber.tracing import TraceRecorder
        with tempfile.TemporaryDirectory() as folder:
            trace = TraceRecorder(Path(folder))
            trace('fast.started', 'turn_old', {'message': {'text':'hi','turn_id':'turn_old'}})
            with (trace.path/'index.jsonl').open('a') as stream:
                stream.write('{')
            reader = RunReader(trace.path)
            self.assertEqual(reader.page('conversation')[0]['text'], 'hi')
            self.assertEqual(reader.context_at(99)['status'], 'unavailable')
            self.assertEqual(len(reader.related('turn_old')), 1)


class SimulationTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_simulator_setup_closes_owned_runtime(self):
        from vtuber.lab.host import LabHost
        with tempfile.TemporaryDirectory() as folder:
            host = LabHost(Config(),Path(folder),simulation={
                'scenario':{'id':'test'},'turns':1,'simulator_model':''})
            with self.assertRaises(ValueError):
                await host.__aenter__()
            self.assertTrue(host.runtime._stopping)
            self.assertFalse(host.archive.trace.thread.is_alive())

    async def test_summary_counts_attempts_and_missing_metrics_honestly(self):
        from vtuber.lab.report import summarize_run
        from vtuber.lab.archive import RunReader
        from vtuber.tracing import TraceRecorder
        with tempfile.TemporaryDirectory() as folder:
            trace = TraceRecorder(Path(folder))
            trace('fast.started','a',{'message':{'text':'hello'}})
            trace('fast.finished','a',{'status':'completed','text':'hi',
                'metrics':{'generation':{'ttft_ms':10,'prompt_tokens':20,'output_tokens':2}}})
            trace('fast.started','b',{'message':{'text':'bye'}})
            trace('fast.finished','b',{'status':'cancelled','partial':'by',
                'metrics':{'generation':{'ttft_ms':30}}})
            report = summarize_run(RunReader(trace.path))
            self.assertEqual(report['ttft_ms'],{'p50':10,'p95':30,'samples':2})
            self.assertEqual(report['turns']['user'],2)
            self.assertEqual(report['fast']['prompt_tokens'],20)
            self.assertIsNone(report['fast']['cached_tokens'])
            self.assertEqual(report['cancelled_replies'],1)

    async def test_manual_pause_stop_invalidate_inflight_action(self):
        from vtuber.lab.simulation import SimulationController, SimulationAction
        entered, release = asyncio.Event(), asyncio.Event()
        class Held:
            closed = False
            async def next_action(self, history, **kwargs):
                entered.set()
                await release.wait()
                return SimulationAction('message', 'stale')
            async def close(self):
                self.closed = True
        submitted = []
        async def submit(message):
            submitted.append(message)
        simulator = Held()
        control = SimulationController(simulator, submit, character_id='primary')
        task = asyncio.create_task(control.run(turns=1, duration_seconds=5))
        await asyncio.wait_for(entered.wait(), 2)
        control.manual_input()
        release.set()
        await asyncio.sleep(.05)
        self.assertEqual(submitted, [])
        await control.stop()
        await task
        self.assertTrue(simulator.closed)

    async def test_simulator_sees_only_public_conversation(self):
        from vtuber.lab.simulator import render_simulator_prompt
        from vtuber.lab.simulation import VisibleMessage, parse_action
        prompt = render_simulator_prompt((VisibleMessage('t','user','hello','manual',1),),
                                          session=1, remaining_turns=12)
        self.assertIn('hello', prompt)
        self.assertNotIn('context_note', prompt)
        for bad in ['{"kind":"silence","wait_seconds":true}',
                    '{"kind":"message","text":""}', '{"kind":"hack"}',
                    '{"kind":"silence","wait_seconds":0}',
                    '{"kind":"message","text":"hi","context":"secret"}']:
            with self.assertRaises(ValueError):
                parse_action(bad)
