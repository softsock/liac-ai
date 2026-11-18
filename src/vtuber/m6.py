"""Opt-in local text console for the M6.0 experiment."""

import argparse
import asyncio
import shutil
from contextlib import aclosing, closing
from importlib.resources import files
from pathlib import Path

from vtuber.cli import input_lines
from vtuber.contracts.events import RuntimeOutput, new_id, utc_now
from vtuber.contracts.mind import SingleMindPort
from vtuber.contracts.perception import Perception
from vtuber.minds.fake import FakeSingleMind
from vtuber.minds.luna_stream import LunaStream
from vtuber.runtime.journal import Journal
from vtuber.runtime.perception_bus import PerceptionBus, PerceptionQueueFull
from vtuber.runtime.single_mind import SingleMindRuntime


class ConsoleOutput:
    def __init__(self) -> None:
        self._previewing = False

    def __call__(self, output: RuntimeOutput) -> None:
        if output.kind == 'reply.delta':
            prefix = '' if self._previewing else '[Provisional] '
            print(prefix + output.text, end='', flush=True)
            self._previewing = True
        elif output.kind in ('reply.completed', 'reply.cancelled', 'reply.failed'):
            if self._previewing:
                print(flush=True)
                self._previewing = False
            if output.kind == 'reply.completed' and output.text:
                print(f'[Final] {output.text}', flush=True)
            elif output.kind in ('reply.cancelled', 'reply.failed'):
                print(f'[{output.kind.removeprefix("reply.").capitalize()}] {output.text}', flush=True)


async def run_console(db: Path, mind: SingleMindPort) -> None:
    identity = files('vtuber.minds').joinpath('character.md').read_text(encoding='utf-8')
    bus = PerceptionBus()
    with closing(Journal(db)) as journal:
        runtime = SingleMindRuntime('primary', journal, mind, ConsoleOutput(), identity=identity)
        await runtime.start()

        async def drain() -> None:
            latest = None
            while (batch := await bus.drain()) is not None:
                latest = await runtime.submit_perceptions(batch) or latest
            if latest is not None:
                await latest

        print('Liac Single Mind | Enter text, /scene <description> or /quit.', flush=True)
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(drain(), name='m6-perception-drain')
                try:
                    async with aclosing(input_lines()) as lines:
                        async for line in lines:
                            if line.strip() in ('/quit', '/exit'):
                                break
                            if line.strip():
                                scene = line.strip().startswith('/scene ')
                                content = line.strip()[7:] if scene else line
                                if not content.strip():
                                    continue
                                try:
                                    await bus.publish(Perception(new_id('perception'),
                                        'state' if scene else 'chat',
                                        'manual:scene' if scene else 'local', 'local',
                                        content, utc_now(), delivery='ambient' if scene else 'direct'))
                                except PerceptionQueueFull as error:
                                    print(str(error), flush=True)
                finally:
                    await bus.close()
        finally:
            await runtime.close()


async def _run_luna(db: Path, bun: str, bridge: Path, reasoning: str) -> None:
    mind = LunaStream((bun, '--no-env-file', str(bridge)), reasoning=reasoning)
    try:
        await run_console(db, mind)
    finally:
        await mind.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Liac M6.0 text-only Single Mind experiment')
    parser.add_argument('--backend', choices=('fake', 'luna'), default='fake')
    parser.add_argument('--db', type=Path, help='SQLite database (default depends on backend)')
    parser.add_argument('--reasoning', choices=('low',), default='low')
    parser.add_argument('--bun', default='bun', help='Bun executable for the Luna backend')
    args = parser.parse_args()
    try:
        if args.backend == 'fake':
            asyncio.run(run_console(args.db or Path('.data/m6-fake.sqlite3'), FakeSingleMind()))
        else:
            bun = shutil.which(args.bun)
            if bun is None:
                parser.error('Luna requires Bun on PATH or an explicit --bun executable')
            bridge = Path(__file__).resolve().parents[2] / 'tools/luna-bridge/bridge.mjs'
            if not bridge.is_file():
                parser.error('Run the Luna backend from the Liac source checkout with its bridge installed')
            asyncio.run(_run_luna(args.db or Path('.data/m6-0.sqlite3'), bun, bridge, args.reasoning))
    except KeyboardInterrupt:
        print('\nSingle Mind interrupted.', flush=True)


if __name__ == '__main__':
    main()
