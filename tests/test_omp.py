import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from vtuber.minds.omp import OMPSettings, OMPTransport
from vtuber.contracts.deep import DeepUnavailable


class Client:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.release = threading.Event()
        self.entered = threading.Event()
        self.stopped = False
        self.stop_result = True
        self.status = 'completed'
        self.message = {'stopReason': 'stop', 'usage': {}}
    def start(self): return self
    def get_state(self): return SimpleNamespace(session_id='session', model=SimpleNamespace(id='gpt-6-luna', provider='openai-codex'))
    def prompt_and_wait(self, prompt, timeout):
        self.entered.set()
        self.release.wait(2)
        return SimpleNamespace(result=SimpleNamespace(status=self.status, session_settled=True),
            assistant_message=self.message, require_assistant_text=lambda: '{}')
    def abort(self): self.release.set()
    def stop(self):
        self.stopped = True
        self.release.set()
        return self.stop_result


class OMPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.transport = OMPTransport(OMPSettings(data_dir=Path(self.folder.name)), 'identity', {})
        self.clients = []
        def create(**kwargs):
            client = Client(**kwargs)
            self.clients.append(client)
            return client
        self.patcher = patch('vtuber.minds.omp.sdk_client', side_effect=create)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addAsyncCleanup(self.transport.close)

    async def entered(self):
        for _ in range(100):
            if self.clients and self.clients[-1].entered.is_set(): return
            await asyncio.sleep(.005)
        self.fail('SDK did not enter prompt')

    async def test_sdk_wait_is_off_loop(self):
        task = asyncio.create_task(self.transport.request('{}'))
        await self.entered()
        self.assertFalse(task.done())
        self.clients[-1].release.set()
        self.assertEqual(await task, '{}')
        self.assertEqual(self.clients[-1].kwargs['tools'], ())

    async def test_cancel_joins_old_operation_before_restart(self):
        task = asyncio.create_task(self.transport.request('{}'))
        await self.entered()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(self.clients[0].stopped)
        second = asyncio.create_task(self.transport.request('{}'))
        while len(self.clients) < 2: await asyncio.sleep(.005)
        self.clients[-1].release.set()
        await second

    async def test_unconfirmed_stop_latches_unsafe(self):
        task = asyncio.create_task(self.transport.request('{}'))
        await self.entered()
        self.clients[-1].stop_result = False
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        with self.assertRaises(RuntimeError): await self.transport.request('{}')
        self.assertEqual(len(self.clients), 1)

    async def test_rpc_result_not_ack_is_completion(self):
        task = asyncio.create_task(self.transport.request('{}'))
        await self.entered()
        self.clients[-1].status = 'aborted'
        self.clients[-1].release.set()
        with self.assertRaises(ValueError): await task
        self.assertTrue(self.clients[-1].stopped)

    async def test_limits(self):
        with self.assertRaises(ValueError): await self.transport.request('x'*524289)
        self.assertFalse(self.clients)

    async def test_usage_limit_does_not_spawn_repeated_children(self):
        task = asyncio.create_task(self.transport.request('{}'))
        await self.entered()
        self.clients[-1].message = {'stopReason':'error','errorMessage':'usage_limit_reached'}
        self.clients[-1].release.set()
        with self.assertRaises(DeepUnavailable): await task
        with self.assertRaises(DeepUnavailable): await self.transport.request('{}')
        self.assertEqual(len(self.clients),1)

    async def test_cancel_during_error_cleanup_is_not_swallowed(self):
        stop_entered, stop_release = threading.Event(), threading.Event()
        class Broken(Client):
            def start(self): raise ConnectionError()
            def stop(self):
                stop_entered.set()
                stop_release.wait(2)
                return True
        with patch('vtuber.minds.omp.sdk_client',side_effect=lambda **kwargs:Broken(**kwargs)):
            task=asyncio.create_task(self.transport.request('{}'))
            for _ in range(100):
                if stop_entered.is_set():break
                await asyncio.sleep(.005)
            self.assertTrue(stop_entered.is_set())
            task.cancel()
            stop_release.set()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(self.transport.diagnostics['cleanup_confirmed'])

    async def test_cancel_during_failing_construction_is_preserved(self):
        loop=asyncio.get_running_loop()
        errors=[]
        previous=loop.get_exception_handler()
        loop.set_exception_handler(lambda loop,context:errors.append(context))
        self.addCleanup(loop.set_exception_handler,previous)
        entered, release = threading.Event(), threading.Event()
        def create(**kwargs):
            entered.set()
            release.wait(2)
            raise ImportError('optional SDK unavailable')
        with patch('vtuber.minds.omp.sdk_client',side_effect=create):
            task=asyncio.create_task(self.transport.request('{}'))
            for _ in range(100):
                if entered.is_set():break
                await asyncio.sleep(.005)
            self.assertTrue(entered.is_set())
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(errors,[])
