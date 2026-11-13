"""Run a private conversation simulation or inspect its saved summary."""
import argparse
import asyncio
import json
import math
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

from vtuber.app import Config
from vtuber.minds.lmstudio import LMStudioSettings
from vtuber.minds.omp import OMPSettings
from vtuber.lab.archive import RunReader
from vtuber.lab.host import LabHost,config_from_dict


def scenario(name='skin-creator'):
    if name != 'skin-creator':
        return json.loads(Path(name).read_text(encoding='utf-8'))
    return json.loads(files('vtuber.lab').joinpath('scenarios/skin-creator.json').read_text(encoding='utf-8'))


async def run(args):
    if args.resume:
        reader = RunReader(args.resume)
        config = config_from_dict(reader.manifest['config'])
        options = reader.manifest['simulation']
    else:
        config = Config(fast_backend='lmstudio',deep_backend='luna',deep_timeout=90,
            lmstudio=LMStudioSettings(endpoint=args.endpoint,model=args.model),
            omp=OMPSettings(args.omp_executable,args.luna_model,request_timeout=85),
            tokenizer=args.tokenizer,initiative_enabled=args.enable_initiative,
            context_tokens=args.context_tokens)
        options = dict(scenario=scenario(args.scenario),turns=args.turns,
            duration_seconds=args.duration_seconds,seed=args.seed,pause_scale=args.pause_scale,
            simulator_model=args.simulator_model,omp_executable=args.omp_executable)
    async with LabHost(config,args.output_root,simulation=options,resume=args.resume,
                       status=lambda value: print(json.dumps(value),flush=True)) as host:
        print(json.dumps({'run_path':str(host.archive.path)}),flush=True)
        while not host.simulation_task.done():
            await host.capture()
            await asyncio.sleep(.2)
        result = await host.simulation_task
        host.result = 'completed' if result['phase'] in ('completed','duration_reached') else 'stopped'
        await host.drain()
        path = host.archive.path
    from vtuber.lab.report import summarize_run
    from vtuber.lab.archive import write_json
    summary = await asyncio.to_thread(summarize_run,RunReader(path))
    await asyncio.to_thread(write_json,path/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


def main():
    parser = argparse.ArgumentParser(description='LIAC headless conversation lab')
    parser.add_argument('--resume',type=Path)
    parser.add_argument('--scenario',default='skin-creator')
    parser.add_argument('--turns',type=int,default=120)
    parser.add_argument('--duration-seconds',type=float)
    parser.add_argument('--pause-scale',type=float,default=1)
    parser.add_argument('--seed',type=int)
    parser.add_argument('--output-root',type=Path,default=Path('.data/lab'))
    parser.add_argument('--simulator-model',default='openai-codex/gpt-6-luna')
    parser.add_argument('--luna-model',default='openai-codex/gpt-6-luna')
    parser.add_argument('--omp-executable',default='omp')
    parser.add_argument('--endpoint',default='http://127.0.0.1:1230')
    parser.add_argument('--model',default='liac-nemotron')
    parser.add_argument('--tokenizer',type=Path,default=Path('.data/tokenizers/nemotron.json'))
    parser.add_argument('--context-tokens',type=int,default=16384)
    parser.add_argument('--enable-initiative',action='store_true')
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='report':
        report = argparse.ArgumentParser(description='Summarize recorded history without inference')
        report.add_argument('path',type=Path)
        report.add_argument('--judge-model')
        report.add_argument('--omp-executable',default='omp')
        args = report.parse_args(sys.argv[2:])
        from vtuber.lab.report import summarize_run,assess_run
        from vtuber.lab.archive import write_json
        reader = RunReader(args.path)
        result = summarize_run(reader)
        write_json(args.path/'summary.json',result)
        if args.judge_model:
            assessment = asyncio.run(assess_run(reader,OMPSettings(args.omp_executable,args.judge_model,
                args.path/'judge',request_timeout=85)))
            write_json(args.path/'assessment.json',assessment)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    args = parser.parse_args()
    if (args.turns <= 0 or not math.isfinite(args.pause_scale) or args.pause_scale <= 0
            or (args.duration_seconds is not None and
                (not math.isfinite(args.duration_seconds) or args.duration_seconds <= 0))):
        parser.error('Turn, duration and pause budgets must be positive')
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print('Simulation interrupted; recorded history is preserved.')


if __name__ == '__main__':
    main()
