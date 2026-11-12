"""Opt-in M2 acceptance using production Runtime, Nemotron and Luna. Private output."""
import argparse
import asyncio
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from vtuber.app import Config, open_runtime
from vtuber.contracts.events import UserMessage
from vtuber.contracts.state import NoteProposal
from vtuber.minds.lmstudio import LMStudioSettings
from vtuber.minds.omp import OMPSettings


def timings(start, first, finish, adapter):
    return {'submit_first_ms': (first-start)*1000 if first is not None else None,
            'wall_ms': (finish-start)*1000, 'adapter_ttft_ms': adapter}


def self_check():
    assert timings(1, 1.5, 2, 42) == {'submit_first_ms': 500, 'wall_ms': 1000, 'adapter_ttft_ms': 42}
    assert timings(1, None, 2, None)['submit_first_ms'] is None
    print('measurement self-check PASS')


async def until(predicate, timeout=90):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.05)


class Evidence:
    def __init__(self, args):
        self.args = args
        self.folder = args.output.parent / ('m2-'+uuid4().hex[:10])
        self.folder.mkdir(parents=True)
        self.first = {}
        self.outputs = []

    def output(self, item):
        self.outputs.append(item)
        if item.kind == 'reply.delta': self.first.setdefault(item.turn_id, perf_counter())

    def save(self, phase, **data):
        row = {'phase': phase, 'run': self.folder.name, **data}
        with self.args.output.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')
        print(json.dumps(row, ensure_ascii=False), flush=True)

    def config(self, name, **overrides):
        return replace(Config(db=self.folder/(name+'.db'), fast_backend='lmstudio', deep_backend='luna',
            deep_timeout=90, tokenizer=self.args.tokenizer,
            lmstudio=LMStudioSettings(endpoint=self.args.endpoint, model=self.args.model),
            omp=OMPSettings(self.args.omp_executable, self.args.luna_model, self.folder/(name+'-omp'),request_timeout=85)), **overrides)

    async def send(self, runtime, text, **tags):
        message = UserMessage(text)
        before = runtime.journal.context_epoch('primary').version
        deep_active = runtime.deep_diagnostics.get('lifecycle') == 'analyzing'
        start = perf_counter()
        task = await runtime.submit(message)
        assert task is not None, 'Fast input rejected'
        await task
        finish = perf_counter()
        terminal = runtime.journal.get('reply_terminal_'+message.event_id)
        assert terminal.kind == 'character.reply.completed', terminal.payload
        diagnostics = runtime.fast_diagnostics
        context, generation = diagnostics['context'], diagnostics['generation']
        assert context['input_tokens'] == generation['prompt_tokens']
        answer = terminal.payload['text']
        with (self.folder/'transcript.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'input':text,'answer':answer,'event_id':message.event_id,**tags},ensure_ascii=False)+'\n')
        self.save('fast', **tags, event_id=message.event_id, epoch=context['epoch_version'],
            transition=context['epoch_version'] != before, tokens=context['input_tokens'],
            deep_active=deep_active, preparation_ms=diagnostics['preparation_ms'],
            compile_ms=context['compile_ms'], **timings(start,self.first.get(message.turn_id),finish,generation['ttft_ms']))
        return answer, terminal.sequence, context


FILLER = ' '.join(('the quiet garden has green trees and small birds near a wooden bridge in morning light'.split()*64)[:1020])
FACTS = {0:'Our fictional penguin is named Mandarin and wears a blue hat.',
    1:'Our fictional stone is amethyst.', 2:'Our bridge is named Hazel.',
    3:'Our boat is named Saffron.', 4:'Correction: Mandarin now wears a GREEN hat, replacing blue.',
    5:'We promised to meet at the bridge tomorrow at noon.',
    6:'Our shared joke: the penguin charges a fish tax for every pun.'}
QUESTIONS = [('green','What color hat does Mandarin wear now?'),
    ('amethyst','What is our fictional stone?'), ('hazel','What is our bridge called?'),
    ('saffron','What is our boat called?'), ('noon','When did we promise to meet?'),
    ('fish','What is our shared penguin joke?')]


async def long_conversation(evidence):
    for trial in range(evidence.args.trials):
        config = evidence.config('trial-'+str(trial))
        async with open_runtime(config, evidence.output) as runtime:
            for index in range(60):
                epoch = runtime.journal.context_epoch('primary').version
                _, _, context = await evidence.send(runtime,
                    FACTS.get(index, f'Garden record {index}.')+'\nQuoted irrelevant filler: '+FILLER+'\nSay only READY.',
                    trial=trial, turn=index)
                if context['input_tokens'] >= 11880:
                    start = perf_counter()
                    await until(lambda: runtime.journal.context_epoch('primary').version > epoch
                                or runtime.deep_diagnostics.get('provider_status') == 'usage_limit_reached')
                    if runtime.deep_diagnostics.get('provider_status'):
                        evidence.save('blocked', scenario='long', trial=trial, deep=dict(runtime.deep_diagnostics))
                        return
                    current = runtime.journal.context_epoch('primary')
                    evidence.save('semantic_switch', trial=trial, epoch=current.version,
                        wait_ms=(perf_counter()-start)*1000, deep=dict(runtime.deep_diagnostics),
                        items=[asdict(item) for item in current.items])
                if runtime.journal.context_epoch('primary').version >= 2:
                    break
            assert runtime.journal.context_epoch('primary').version >= 2
            for word, question in QUESTIONS:
                answer, _, _ = await evidence.send(runtime, question+' Answer briefly.', trial=trial, recall=word)
                evidence.save('recall', trial=trial, fact=word, retained=word in answer.lower(), answer=answer)
            cursor = runtime.journal.cursor('primary')
            evidence.save('before_restart', trial=trial, cursor=cursor, epoch=runtime.journal.context_epoch('primary').version)
        async with open_runtime(config, evidence.output) as runtime:
            answer, terminal, _ = await evidence.send(runtime, 'What color hat does Mandarin wear now?',trial=trial,restart=True)
            await until(lambda: runtime.journal.cursor('primary') >= terminal)
            evidence.save('restart',trial=trial, green='green' in answer.lower(),
                cursor=runtime.journal.cursor('primary'), prior_cursor=cursor,
                epoch=runtime.journal.context_epoch('primary').version, unfinished=len(runtime.journal.unfinished_replies('primary')))


async def scenarios(evidence):
    config = evidence.config('async')
    async with open_runtime(config, evidence.output) as runtime:
        real = runtime.deep
        ready, release = asyncio.Event(), asyncio.Event()
        class Held:
            async def propose(self, request):
                result = await real.propose(request)
                ready.set()
                await release.wait()
                return result
        runtime._deep_worker.mind = Held()
        await evidence.send(runtime, 'Our penguin Mandarin wears a blue hat. Answer briefly.', scenario='B')
        await until(ready.is_set)
        before = runtime.journal.cursor('primary')
        await evidence.send(runtime, 'Our boat is Saffron. Answer briefly.',scenario='B-held-real-result')
        assert runtime.journal.cursor('primary') == before
        source = runtime.journal.recent_dialogue('primary')[0]
        runtime.journal.apply_note(NoteProposal('external', 'primary', 0,
            runtime.journal.high_watermark('primary'), (source.event_id,), 'External updated note.'))
        runtime._deep_worker.mind = real
        release.set()
        await until(lambda: any(e.kind=='deep.batch.rejected' for e in runtime.journal.read('primary',limit=1000)))
        await until(lambda: runtime.journal.snapshot('primary').revision > 1)
        evidence.save('stale_recovered',cursor=runtime.journal.cursor('primary'),revision=runtime.journal.snapshot('primary').revision,
            decisions=[e.payload for e in runtime.journal.read('primary',limit=1000) if e.kind.startswith('deep.batch.')])
        # Kill only our SDK-owned child during a real Deep inference.
        await evidence.send(runtime, 'Remember that our stone is amethyst. Answer briefly.',scenario='E')
        await until(lambda:runtime.deep_diagnostics.get('lifecycle')=='analyzing')
        old_cursor=runtime.journal.cursor('primary')
        client=real.transport._client
        process=client._process
        process.kill()
        await until(lambda:runtime.journal.cursor('primary')>old_cursor)
        evidence.save('owned_child_kill_recovered',prior_cursor=old_cursor,cursor=runtime.journal.cursor('primary'),deep=dict(runtime.deep_diagnostics))
        # Cancellation of real Fast while Deep remains independent.
        first=UserMessage('Tell a long whimsical garden story in many paragraphs.')
        await runtime.submit(first)
        await until(lambda:first.turn_id in evidence.first)
        await evidence.send(runtime,'Say READY.',scenario='supersession')
        terminal=runtime.journal.get('reply_terminal_'+first.event_id)
        assert terminal.kind=='character.reply.cancelled'
        evidence.save('cancellation',ms=runtime.last_cancellation_ms,terminal=terminal.kind)
    await offline(evidence)


async def offline(evidence):
    # Separate offline-start path; recover the same adapter with a corrected executable.
    config=evidence.config('offline')
    config=replace(config,omp=replace(config.omp,executable=str(evidence.folder/'missing-omp.exe')))
    async with open_runtime(config,evidence.output) as runtime:
        for index in range(18):
            await evidence.send(runtime,f'Garden record {index}. '+FILLER+' Say READY.',scenario='G',turn=index)
            if runtime.journal.context_epoch('primary').version: break
        assert runtime.journal.context_epoch('primary').version
        evidence.save('offline_fallback',epoch=runtime.journal.context_epoch('primary').version,cursor=runtime.journal.cursor('primary'))
        runtime.deep.transport.settings=replace(config.omp,executable=evidence.args.omp_executable)
        runtime.retry_deep()
        await until(lambda:runtime.journal.snapshot('primary').revision>0
                    or runtime.deep_diagnostics.get('provider_status')=='usage_limit_reached')
        evidence.save('offline_recovery',revision=runtime.journal.snapshot('primary').revision,
            recovered=runtime.journal.snapshot('primary').revision>0,deep=dict(runtime.deep_diagnostics))


async def cli(evidence):
    config=evidence.config('cli')
    command=[sys.executable,'-m','vtuber','--db',str(config.db),'--fast-backend','lmstudio',
        '--endpoint',evidence.args.endpoint,'--model',evidence.args.model,'--tokenizer',str(evidence.args.tokenizer),
        '--deep-backend','luna','--omp-executable',evidence.args.omp_executable,'--luna-data',str(config.omp.data_dir)]
    for index in range(2):
        process=await asyncio.create_subprocess_exec(*command,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
        seen=[]
        async def read():
            while data:=await process.stdout.readline():
                line=data.decode('utf-8',errors='replace');seen.append(line)
        reader=asyncio.create_task(read())
        try:
            process.stdin.write(('In our fictional story, Mandarin is a penguin. His hat is GREEN. Please acknowledge in one short sentence.\n' if index==0 else "In our fictional story, what color is Mandarin's hat? Answer with the color only.\n").encode());await process.stdin.drain()
            await until(lambda:any('deep.completed' in line or 'deep.failed' in line for line in seen))
            process.stdin.write(b'/status\n/quit\n');await process.stdin.drain()
            await asyncio.wait_for(process.wait(),20);await reader
            assert process.returncode==0
            (evidence.folder/f'cli-{index}.log').write_text(''.join(seen),encoding='utf-8')
            evidence.save('cli',restart=bool(index),exit_code=process.returncode,
                deep_completed=any('deep.completed' in line for line in seen),
                green='green' in ''.join(seen).lower())
        finally:
            if process.returncode is None:process.kill();await process.wait()
            await reader


async def main(args):
    evidence=Evidence(args)
    if args.phase in ('all','long'):await long_conversation(evidence)
    if args.phase in ('all','scenarios'):await scenarios(evidence)
    if args.phase == 'offline':await offline(evidence)
    if args.phase in ('all','cli'):await cli(evidence)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-check',action='store_true')
    parser.add_argument('--endpoint',default='http://127.0.0.1:1230')
    parser.add_argument('--model',default='liac-nemotron')
    parser.add_argument('--tokenizer',type=Path,default=Path('.data/tokenizers/nemotron.json'))
    parser.add_argument('--omp-executable',default='omp')
    parser.add_argument('--luna-model',default='openai-codex/gpt-6-luna')
    parser.add_argument('--output',type=Path,default=Path('.data/m2-results.jsonl'))
    parser.add_argument('--phase',choices=('all','long','scenarios','offline','cli'),default='all')
    parser.add_argument('--trials',type=int,default=3)
    arguments=parser.parse_args()
    if arguments.self_check:self_check()
    else:asyncio.run(main(arguments))
