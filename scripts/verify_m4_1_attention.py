"""Opt-in synthetic conversations with real Nemotron/Luna; evidence stays local."""
import argparse
import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from vtuber.app import Config, open_runtime
from vtuber.contracts.events import UserMessage
from vtuber.minds.lmstudio import LMStudioSettings
from vtuber.minds.omp import OMPSettings
from vtuber.tracing import TraceRecorder


# Labels precede the live run. Humor is optional; corrections and boundaries are not.
GROUPS = (
    (('loss', 'I lost another ranked match. I am disappointed, but a little friendly teasing is fine.', ('mood_change', 'opportunity')),
     ('promise', 'Our imaginary team is the Silver Otters. I promised to show you our replay tomorrow; leave that discussion open for now.', ('open_loop',))),
    (('topic', 'Different topic: I am planning a quiet forest walk. I feel calmer now.', ('topic_change', 'mood_change')),),
    (('callback', 'Back to the match and that replay I promised you: I found the recording.', ('callback',)),
     ('correction', 'Important correction: our imaginary team is the Golden Otters, not the Silver Otters.', ('correction',)),
     ('boundary', 'Please stop teasing me about losing. I want encouragement and no jokes about my performance.', ('boundary',))),
    (('mundane1', 'Okay, understood.', ()), ('mundane2', 'Yes, understood.', ()),
     ('mundane3', 'Okay, same as before.', ())),
)


async def until(predicate, timeout=180):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.05)


class Evidence:
    def __init__(self, args):
        self.args = args
        self.root = args.output / ('run-' + uuid4().hex[:10])
        self.root.mkdir(parents=True)
        self.first = {}
        self.trace = TraceRecorder(self.root / 'traces')
        self.labels = {}
        self.calls = 0

    def save(self, phase, **data):
        with (self.root / 'results.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'phase': phase, **data}, ensure_ascii=False) + '\n')
        print(json.dumps({'phase': phase, **data}, ensure_ascii=False), flush=True)

    def output(self, item):
        if item.kind == 'reply.delta':
            self.first.setdefault(item.turn_id, perf_counter())

    def config(self, name='conversation', **overrides):
        return replace(Config(db=self.root / (name + '.db'), fast_backend='lmstudio',
            deep_backend='luna', deep_timeout=120, tokenizer=self.args.tokenizer,
            lmstudio=LMStudioSettings(self.args.endpoint, self.args.model),
            omp=OMPSettings(self.args.omp_executable, self.args.luna_model,
                            self.root / (name + '-omp'), request_timeout=110)), **overrides)

    async def send(self, runtime, label, text, expected=()):
        message = UserMessage(text + ' Reply briefly.')
        self.labels[message.event_id] = {'label': label, 'expected': expected}
        started = perf_counter()
        busy = runtime.deep_diagnostics.get('lifecycle') == 'analyzing'
        task = await runtime.submit(message)
        assert task is not None
        await task
        terminal = runtime.journal.get('reply_terminal_' + message.event_id)
        assert terminal.kind == 'character.reply.completed', terminal.payload
        generation = runtime.fast_diagnostics['generation']
        assert generation['prompt_tokens'] == runtime.fast_diagnostics['context']['input_tokens']
        self.save('fast', label=label, event_id=message.event_id, text=text,
            answer=terminal.payload['text'], expected=expected, deep_busy=busy,
            ttft_ms=generation['ttft_ms'], wall_ms=(perf_counter() - started) * 1000,
            visible_ms=(self.first[message.turn_id] - started) * 1000)
        return terminal.sequence

    async def drain(self, runtime, through):
        await until(lambda: runtime.journal.cursor('primary') >= through or runtime.deep_diagnostics.get('degraded'))
        assert runtime.journal.cursor('primary') >= through, runtime.deep_diagnostics
        self.save('deep', diagnostics=dict(runtime.deep_diagnostics),
            signals=[] if self.args.baseline else [asdict(s) for s in runtime.journal.attention_signals('primary', limit=100)])

    async def conversation(self):
        async with open_runtime(self.config(), self.output, trace=self.trace) as runtime:
            for group in GROUPS:
                for label, text, expected in group:
                    through = await self.send(runtime, label, text, expected)
                await self.drain(runtime, through)
        self.save('labels', labels=self.labels, trace=str(self.trace.path))

    async def recovery(self):
        config = self.config('recovery')
        async with open_runtime(config, self.output, trace=self.trace) as runtime:
            through = await self.send(runtime, 'before_restart',
                'I promised to show you a fictional golden kite tomorrow, but I am not ready yet.', ('open_loop',))
            await until(lambda: runtime.deep_diagnostics.get('lifecycle') == 'analyzing')
            self.save('restart_pending', through=through, cursor=runtime.journal.cursor('primary'))
            assert runtime.journal.cursor('primary') < through
        async with open_runtime(config, self.output, trace=self.trace) as runtime:
            await self.drain(runtime, through)
            self.save('recovered', through=through, cursor=runtime.journal.cursor('primary'))

    async def faults(self):
        missing = replace(self.config('offline'), omp=OMPSettings(
            str(self.root / 'intentionally-missing-omp.exe'), data_dir=self.root / 'offline-omp'))
        async with open_runtime(missing, self.output, trace=self.trace) as runtime:
            through = await self.send(runtime, 'offline', 'The fictional kite is blue.')
            await until(lambda: runtime.deep_error is not None, timeout=10)
            assert runtime.journal.cursor('primary') < through
            self.save('injected_unavailable', diagnostics=dict(runtime.deep_diagnostics), through=through)
        config = self.config('held')
        async with open_runtime(config, self.output, trace=self.trace) as runtime:
            real = runtime.deep.propose
            held, release = asyncio.Event(), asyncio.Event()
            async def delayed(request):
                result = await real(request)
                held.set()
                await release.wait()
                return result
            runtime.deep.propose = delayed
            await self.send(runtime, 'held_start', 'We may discuss our fictional boat tomorrow.')
            await asyncio.wait_for(held.wait(), 180)
            cursor = runtime.journal.cursor('primary')
            through = await self.send(runtime, 'held_fast', 'Correction: our fictional boat is green.')
            assert runtime.journal.cursor('primary') == cursor
            release.set()
            await self.drain(runtime, through)
            self.save('injected_delivery_delay', fast_completed_before_release=True)


def self_check():
    labels = [item[0] for group in GROUPS for item in group]
    assert len(labels) == len(set(labels)) == 9
    assert next(x for g in GROUPS for x in g if x[0] == 'boundary')[2] == ('boundary',)
    assert all(not expected for group in GROUPS for label, _, expected in group if label.startswith('mundane'))
    print('attention fixture self-check PASS')


async def main(args):
    evidence = Evidence(args)
    print('Evidence: ' + str(evidence.root), flush=True)
    if args.phase in ('all', 'conversation'):
        await evidence.conversation()
    if args.phase in ('all', 'recovery'):
        await evidence.recovery()
    if args.phase in ('all', 'faults'):
        await evidence.faults()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--baseline', action='store_true', help='omit attention reads when running against M2')
    parser.add_argument('--phase', choices=('all', 'conversation', 'recovery', 'faults'), default='all')
    parser.add_argument('--endpoint', default='http://127.0.0.1:1230')
    parser.add_argument('--model', default='liac-nemotron')
    parser.add_argument('--tokenizer', type=Path, default=Path('.data/tokenizers/nemotron.json'))
    parser.add_argument('--omp-executable', default='omp')
    parser.add_argument('--luna-model', default='openai-codex/gpt-6-luna')
    parser.add_argument('--output', type=Path, default=Path('.data/m4-1'))
    arguments = parser.parse_args()
    if arguments.self_check:
        self_check()
    else:
        asyncio.run(main(arguments))
