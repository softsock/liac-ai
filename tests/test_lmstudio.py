import asyncio
import unittest

import httpx

from vtuber.context import ChatMessage, ContextCompiler
from vtuber.contracts.events import UserMessage
from vtuber.contracts.state import CharacterState, FastSnapshot
from vtuber.minds.lmstudio import LMStudioFast, LMStudioSettings, StreamProtocolError, render_nemotron


class LMStudioTests(unittest.IsolatedAsyncioTestCase):
    def test_adjacent_assistant_fragments_follow_the_checkpoint_template(self):
        prompt = render_nemotron((ChatMessage("system", "Identity"), ChatMessage("user", "hi"),
            ChatMessage("assistant", "one"), ChatMessage("assistant", "two"), ChatMessage("user", "next")))
        self.assertIn("<|turn>model\nonetwo<turn|>\n<|turn>user\nnext", prompt)
        self.assertNotIn("<|think|>", prompt)

    def test_literal_control_tokens_cannot_change_roles_or_poison_history(self):
        prompt = render_nemotron((ChatMessage("system", "Identity"),
            ChatMessage("user", "What is <|think|>?"), ChatMessage("user", "hello")))
        self.assertNotIn("<|think|>", prompt)
        self.assertIn(r"\u003c|think|>", prompt)

    async def test_broken_streams_never_complete_or_expose_split_reasoning(self):
        for chunks in (
            [b'data: {"choices":[{"text":"partial","finish_reason":null}]}\n\n'],
            [b'data: {"choices":[{"text":"<|chan","finish_reason":null}]}\n\n',
             b'data: {"choices":[{"text":"nel>thought secret","finish_reason":null}]}\n\n'],
            [b'data: {"choices":[{"text":"one"},{"text":"two"}]}\n\n'],
            [b'data: {"choices":[{"text":"  ","finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'],
        ):
            with self.subTest(chunks=chunks):
                class Stream(httpx.AsyncByteStream):
                    closed = False

                    async def __aiter__(self):
                        for chunk in chunks:
                            yield chunk

                    async def aclose(self):
                        self.closed = True

                stream = Stream()
                async def handle(request):
                    if request.url.path == "/api/v1/models":
                        return httpx.Response(200, json={"models": [{"key": "nvidia-nemotron-3.5-bolt-e4b-4gb",
                            "loaded_instances": [{"id": "test", "config": {"context_length": 16384}}]}]})
                    return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

                async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://local") as client:
                    fast = LMStudioFast(client, ContextCompiler("Identity"), LMStudioSettings(model="test"), {})
                    visible = []
                    with self.assertRaises(StreamProtocolError):
                        async for part in fast.stream(FastSnapshot(CharacterState("primary"), 0, ()), UserMessage("hello")):
                            visible.append(part)
                    self.assertNotIn("secret", "".join(visible))
                    self.assertNotIn("<|", "".join(visible))
                    self.assertTrue(stream.closed)

    async def test_cancellation_closes_a_stalled_http_stream(self):
        entered = asyncio.Event()
        class Stream(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                entered.set()
                await asyncio.Event().wait()
                yield b""

            async def aclose(self):
                self.closed = True

        stream = Stream()
        async def handle(request):
            if request.url.path == "/api/v1/models":
                return httpx.Response(200, json={"models": [{"key": "nvidia-nemotron-3.5-bolt-e4b-4gb",
                    "loaded_instances": [{"id": "test", "config": {"context_length": 16384}}]}]})
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://local") as client:
            fast = LMStudioFast(client, ContextCompiler("Identity"), LMStudioSettings(model="test"), {})
            async def consume():
                async for _ in fast.stream(FastSnapshot(CharacterState("primary"), 0, ()), UserMessage("hello")):
                    pass
            task = asyncio.create_task(consume())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
            self.assertTrue(stream.closed)
            self.assertEqual(fast.diagnostics["generation"]["status"], "cancelled")
