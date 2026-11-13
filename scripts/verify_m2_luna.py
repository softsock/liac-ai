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
    assert callable(markdown_context)
    assert callable(initiative)
    from vtuber.contracts.events import CharacterInitiative
    sample = CharacterInitiative('hat', 'unfinished', 'primary', 'i', 't', 'now', 'p')
    assert sample.as_event().kind == 'character.initiative.started'
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
        self.started = {}
        self.finished = {}
        self.outputs = []

    def output(self, item):
        self.outputs.append(item)
        if item.kind == 'reply.started': self.started[item.turn_id] = perf_counter()
        if item.kind == 'reply.delta': self.first.setdefault(item.turn_id, perf_counter())
        if item.kind in ('reply.completed', 'reply.failed', 'reply.cancelled'):
            self.finished[item.turn_id] = perf_counter()

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


async def markdown_context(evidence):
    from vtuber.runtime.context_file import context_file_path
    for budget in (1024, 2048):
        config = evidence.config(f'markdown-{budget}', working_context_tokens=budget)
        decisions = []
        def trace(kind, request_id, data):
            if kind == 'deep.decision':
                decisions.append(data)
        async with open_runtime(config, evidence.output, trace=trace) as runtime:
            async def settled(terminal):
                await until(lambda: runtime.journal.cursor('primary') >= terminal
                    or runtime.deep_diagnostics.get('degraded'))
                assert runtime.journal.cursor('primary') >= terminal, runtime.deep_diagnostics
            answer, terminal, _ = await evidence.send(runtime,
                "I'm making Skin Creator. I've redesigned its vintage interface three times before releasing version 1. "
                "I enjoy a little playful teasing about my endless redesigns. Keep replies short.", budget=budget)
            await settled(terminal)
            evidence.save('markdown_document', budget=budget, stage='earned_idea',
                document=runtime.journal.snapshot('primary').context_note, answer=answer)
            answer, terminal, _ = await evidence.send(runtime,
                "Guess what, I'm tempted to redesign Skin Creator again. What do you think?", budget=budget)
            await settled(terminal)
            evidence.save('markdown_document', budget=budget, stage='influence',
                document=runtime.journal.snapshot('primary').context_note, answer=answer)
            real, ready, release = runtime.deep, asyncio.Event(), asyncio.Event()
            correction_pending, correction_release = asyncio.Event(), asyncio.Event()
            class Held:
                once = True
                async def propose(self, request):
                    if not self.once:
                        correction_pending.set()
                        await correction_release.wait()
                    result = await real.propose(request)
                    if self.once:
                        self.once = False
                        ready.set()
                        await release.wait()
                    return result
            runtime._deep_worker.mind = Held()
            try:
                await evidence.send(runtime, "Maybe Skin Creator 2 will arrive before version 1. Another redesign!", budget=budget)
                await asyncio.wait_for(ready.wait(), 90)
                answer, terminal, _ = await evidence.send(runtime,
                    "Stop teasing me about redesigns. Drop that joke. I've frozen the layout and moved to keyboard "
                    "accessibility testing. Please talk seriously about the testing now.", budget=budget, injected_hold=True)
                release.set()
                await asyncio.wait_for(correction_pending.wait(), 10)
                stale = runtime.journal.snapshot('primary').context_note
                answer, terminal, _ = await evidence.send(runtime,
                    "How should I check the keyboard navigation? Keep it brief.", budget=budget,
                    stale_document_after_correction=True)
                evidence.save('markdown_document', budget=budget, stage='late_context_behavior',
                    document=stale, answer=answer, injected_hold=True)
                correction_release.set()
                await settled(terminal)
            finally:
                release.set()
                correction_release.set()
            evidence.save('markdown_document', budget=budget, stage='correction_after_held_result',
                document=runtime.journal.snapshot('primary').context_note, answer=answer,
                decisions=decisions, injected_hold=True)
            before = runtime.journal.snapshot('primary')
            _, terminal, _ = await evidence.send(runtime, 'Okay.', budget=budget)
            await settled(terminal)
            state = runtime.journal.snapshot('primary')
            evidence.save('markdown_noop', budget=budget, unchanged=state == before,
                document=state.context_note)
            assert runtime.journal._db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        path = context_file_path(config.db, 'primary')
        path.write_text('stale projection', encoding='utf-8')
        async with open_runtime(config, evidence.output) as runtime:
            await until(lambda: path.read_bytes() == state.context_note.encode('utf-8'))
            assert runtime.journal.snapshot('primary') == state
            evidence.save('markdown_restart', budget=budget, recovered=True, revision=state.revision)


async def initiative(evidence):
    from vtuber.contracts.deep import InitiativeProposal
    from vtuber.runtime.context_file import context_file_path

    class Observed:
        def __init__(self, real, hold=False):
            self.real, self.hold = real, hold
            self.calls = 0
            self.ready, self.release = asyncio.Event(), asyncio.Event()

        async def propose(self, request):
            self.calls += 1
            result = await self.real.propose(request)
            evidence.save('initiative_deep', request_id=request.request_id, call=self.calls,
                allowed=request.initiative_allowed, result=asdict(result), injected_hold=self.hold,
                usage=dict(runtime.deep_diagnostics.get('usage', {})))
            if self.hold:
                self.hold = False
                self.ready.set()
                await self.release.wait()
            return result

    def events(runtime, kind):
        return [e for e in runtime.journal.read('primary', limit=10000) if e.kind == kind]

    async def settle(runtime, sequence):
        await until(lambda: runtime.journal.cursor('primary') >= sequence or runtime.deep_error, 100)
        if runtime.deep_error:
            raise RuntimeError('Live Deep failed: '+runtime.deep_error)

    config = evidence.config('initiative-natural', initiative_enabled=True)
    async with open_runtime(config, evidence.output) as runtime:
        observed = Observed(runtime.deep)
        runtime._deep_worker.mind = observed
        for text in (
            "Skin Creator version 1 is still unreleased and I'm redesigning it again. The save button is a swimming pool; maybe version 2 will arrive first.",
            "I keep redesigning that button instead of releasing version 1. I might put a tiny diving board next to it. I'll stare at the layout for a bit."):
            _, sequence, _ = await evidence.send(runtime, text, scenario='A-natural')
            await settle(runtime, sequence)
            await asyncio.sleep(7)
            if events(runtime, 'character.initiative.started'):
                break
        await until(lambda: runtime._fast_task is None or runtime._fast_task.done())
        starts = events(runtime, 'character.initiative.started')
        for started in starts:
            terminal = runtime.journal.get('reply_terminal_'+started.event_id)
            assert terminal and terminal.kind == 'character.reply.completed'
            assert not any(e.kind == 'user.message.completed' and e.turn_id == started.turn_id
                           for e in runtime.journal.read('primary', limit=10000))
            evidence.save('initiative_utterance', scenario='A', event_id=started.event_id,
                opportunity=started.payload, answer=terminal.payload['text'],
                first_delta_observed=started.turn_id in evidence.first,
                **timings(evidence.started[started.turn_id], evidence.first.get(started.turn_id),
                    evidence.finished[started.turn_id], runtime.fast_diagnostics.get('generation', {}).get('ttft_ms')),
                generation=dict(runtime.fast_diagnostics.get('generation', {})))
        calls = observed.calls
        await asyncio.sleep(7)
        assert observed.calls == calls, 'Autonomous-only tail triggered more Deep work'
        state = runtime.journal.snapshot('primary')
        count = len(starts)
        evidence.save('initiative_natural', scenario='A/D', autonomous_count=count,
            timer_triggered_calls=observed.calls-calls, deep_calls=calls,
            document=state.context_note, deep=dict(runtime.deep_diagnostics))
    projection = context_file_path(config.db, 'primary')
    projection.write_text('stale projection', encoding='utf-8')
    async with open_runtime(config, evidence.output) as runtime:
        observed = Observed(runtime.deep)
        runtime._deep_worker.mind = observed
        await until(lambda: projection.read_text(encoding='utf-8') == state.context_note)
        await asyncio.sleep(2)
        assert runtime.journal.snapshot('primary') == state
        assert len(events(runtime, 'character.initiative.started')) == count
        assert runtime.journal._db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        evidence.save('initiative_recovery', scenario='D/F', repeated=False,
            unfinished=len(runtime.journal.unfinished_inputs('primary')), deep_calls=observed.calls, integrity='ok')

    config = evidence.config('initiative-silence', initiative_enabled=True)
    async with open_runtime(config, evidence.output) as runtime:
        observed = Observed(runtime.deep)
        runtime._deep_worker.mind = observed
        for text in ('Hi Liac. Just saying hello.', "Okay, that is all for now. Nothing else on my mind. See you later."):
            _, sequence, _ = await evidence.send(runtime, text, scenario='B')
            await settle(runtime, sequence)
        calls = observed.calls
        await asyncio.sleep(8)
        evidence.save('initiative_silence', scenario='B', autonomous_count=len(events(runtime, 'character.initiative.started')),
            timer_triggered_calls=observed.calls-calls, deep_calls=observed.calls,
            document=runtime.journal.snapshot('primary').context_note)
        assert observed.calls == calls

    config = evidence.config('initiative-stale', initiative_enabled=True)
    async with open_runtime(config, evidence.output) as runtime:
        observed = Observed(runtime.deep, hold=True)
        runtime._deep_worker.mind = observed
        await evidence.send(runtime,
            "Skin Creator version 1 is still unreleased and I'm redesigning it again. The save button is a swimming pool; maybe version 2 will arrive first.", scenario='C')
        await asyncio.wait_for(observed.ready.wait(), 100)
        try:
            _, sequence, _ = await evidence.send(runtime,
                "Stop the redesign jokes. The layout is finished. I am checking keyboard navigation now; please be serious.", scenario='C/E/G-held-real')
            assert not observed.release.is_set(), 'Fast waited for held Deep'
        finally:
            observed.release.set()
        await settle(runtime, sequence)
        evidence.save('initiative_stale', scenario='C/E/G', injected_delivery_hold=True,
            starts=len(events(runtime, 'character.initiative.started')),
            decisions=[e.payload['decision'] for e in events(runtime, 'deep.batch.completed')],
            document=runtime.journal.snapshot('primary').context_note, deep_calls=observed.calls)

    # A controlled stream hold tests cancellation using actual provider chunks.
    from contextlib import aclosing
    from vtuber.contracts.events import CharacterInitiative
    config = evidence.config('initiative-stream-race', initiative_enabled=True,
        initiative_delay_seconds=1, initiative_cooldown_seconds=2)
    async with open_runtime(config, evidence.output) as runtime:
        observed = Observed(runtime.deep)
        runtime._deep_worker.mind = observed
        real_fast = runtime.fast
        streaming = asyncio.Event()
        class HeldStream:
            async def stream(self, snapshot, message):
                async with aclosing(real_fast.stream(snapshot, message)) as stream:
                    async for chunk in stream:
                        yield chunk
                        if isinstance(message, CharacterInitiative):
                            streaming.set()
                            await asyncio.Event().wait()
        runtime.fast = HeldStream()
        _, sequence, _ = await evidence.send(runtime,
            "Skin Creator version 1 is still unreleased and I'm redesigning it again. The save button is a swimming pool; maybe version 2 will arrive first.", scenario='E-prelude')
        await settle(runtime, sequence)
        try:
            await asyncio.wait_for(streaming.wait(), 8)
        except TimeoutError:
            evidence.save('initiative_stream_race', scenario='E', tested=False, reason='Luna chose silence')
        else:
            active = events(runtime, 'character.initiative.started')[-1]
            await evidence.send(runtime, 'Stop that thought. The layout is done. Just say okay.', scenario='E-user-priority')
            terminal = runtime.journal.get('reply_terminal_'+active.event_id)
            assert terminal.kind == 'character.reply.cancelled'
            assert not any(e.turn_id == active.turn_id for e in runtime.journal.recent_dialogue('primary', 1000))
            assert len([e for e in runtime.journal.read('primary', limit=10000)
                if e.causation_id == active.event_id and e.kind in (
                    'character.reply.completed', 'character.reply.failed', 'character.reply.cancelled')]) == 1
            evidence.save('initiative_stream_race', scenario='E', tested=True,
                injected_stream_hold=True, terminal=terminal.kind, leaked_partial_in_history=False,
                cancellation_ms=runtime.last_cancellation_ms)

    config = evidence.config('initiative-deep-busy', initiative_enabled=True)
    async with open_runtime(config, evidence.output) as runtime:
        observed = Observed(runtime.deep)
        runtime._deep_worker.mind = observed
        await evidence.send(runtime, 'The green save button is finally working. There is a small duck icon now.', scenario='G-first')
        await until(lambda: runtime.deep_diagnostics.get('lifecycle') == 'analyzing')
        await evidence.send(runtime, 'What is a good tiny sound for a duck-shaped save button?', scenario='G-deep-analyzing')
        evidence.save('initiative_fast_independence', scenario='G',
            deep_still_analyzing=runtime.deep_diagnostics.get('lifecycle') == 'analyzing',
            deep_calls=observed.calls, generation=dict(runtime.fast_diagnostics.get('generation', {})))


async def main(args):
    evidence=Evidence(args)
    if args.phase in ('all','long'):await long_conversation(evidence)
    if args.phase in ('all','scenarios'):await scenarios(evidence)
    if args.phase == 'markdown':await markdown_context(evidence)
    if args.phase == 'initiative':await initiative(evidence)
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
    parser.add_argument('--phase',choices=('all','long','scenarios','offline','cli','markdown','initiative'),default='all')
    parser.add_argument('--trials',type=int,default=3)
    arguments=parser.parse_args()
    if arguments.self_check:self_check()
    else:asyncio.run(main(arguments))
