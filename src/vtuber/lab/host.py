"""Shared composition for headless and Qt clients; simulator gets public text only."""
import asyncio
from dataclasses import replace
from pathlib import Path

from vtuber.app import Config,open_runtime
from vtuber.minds.lmstudio import LMStudioSettings
from vtuber.lab.archive import RunArchive, RunReader
from vtuber.lab.simulation import SimulationController, VisibleMessage
from vtuber.lab.simulator import OMPUserSimulator
from vtuber.minds.omp import OMPSettings


def config_from_dict(data: dict) -> Config:
    data = dict(data)
    data['db'] = Path(data['db'])
    data['tokenizer'] = Path(data['tokenizer'])
    if data.get('identity'):
        data['identity'] = Path(data['identity'])
    data['lmstudio'] = LMStudioSettings(**data['lmstudio'])
    omp = dict(data['omp'])
    omp['data_dir'] = Path(omp['data_dir'])
    data['omp'] = OMPSettings(**omp)
    return Config(**data)


class LabHost:
    def __init__(self, config, root, *, simulation=None, resume=None, output=None, status=None, input_message=None):
        self.config, self.root, self.options, self.resume_path = config, root, simulation, resume
        self.output, self.on_status = output, status
        self.controller = None
        self.simulation_task = None
        self._visible = []
        self._origins = {}
        self._partials = {}
        self.result = 'stopped'
        self.reason = None
        self.input_message = input_message
        self.usage = {'luna':{},'simulator':{}}
        self._checkpoint = 0

    @property
    def error(self):
        return self.archive.trace.error

    def __call__(self,kind,request_id,data):
        actor = {'omp.completed':'luna','simulator.omp.completed':'simulator'}.get(kind)
        if actor:
            for key,value in data.get('usage',{}).items():
                if type(value) in (int,float):
                    self.usage[actor][key] = self.usage[actor].get(key,0)+value
                elif key=='cost' and isinstance(value,dict):
                    amount = value.get('total')
                    if type(amount) in (int,float):
                        self.usage[actor]['cost_total'] = self.usage[actor].get('cost_total',0)+amount
        self.archive.trace(kind,request_id,data)

    async def __aenter__(self):
        if self.resume_path:
            self.archive = await asyncio.to_thread(RunArchive.resume, self.resume_path)
            self.config = config_from_dict(self.archive.manifest['config'])
            self.options = self.archive.manifest['simulation']
        else:
            self.archive = await asyncio.to_thread(RunArchive.create, self.root, self.config,
                scenario=self.options.get('scenario') if self.options else None,
                seed=self.options.get('seed') if self.options else None)
        if self.options:
            self.config = replace(self.config,db=self.archive.db,
                omp=replace(self.config.omp,data_dir=self.archive.path/'luna'))
            self.archive.manifest['simulation'] = self.options
        self.manager = open_runtime(self.config,self._output,trace=self)
        try:
            self.runtime = await self.manager.__aenter__()
            if self.options:
                await self._start_controller()
            return self
        except BaseException as error:
            if hasattr(self,'runtime'):
                await self.manager.__aexit__(type(error),error,error.__traceback__)
            await self.archive.close('failed',type(error).__name__)
            raise

    async def _start_controller(self):
        options = self.options
        prior = await asyncio.to_thread(RunReader,self.archive.path) if self.resume_path else None
        if prior:
            observed_turns = sum(r['role']=='user' and r['origin']=='simulated' for r in prior.conversation)
            self.archive.manifest['turns'] = max(self.archive.manifest.get('turns',0),observed_turns)
            self.archive.manifest['session'] = max([r.get('session',1) or 1 for r in prior.conversation]+[1])
        settings = OMPSettings(options.get('omp_executable',self.config.omp.executable),
            options.get('simulator_model',self.config.omp.model),self.archive.path/'simulator',request_timeout=85)
        simulator = OMPUserSimulator(settings,options['scenario'],trace=self)
        self.controller = SimulationController(simulator,self.runtime.submit,
            character_id=self.config.character_id,trace=self.archive.trace,
            pause_scale=options.get('pause_scale',1),seed=options.get('seed'),
            initial_turns=self.archive.manifest.get('turns',0),
            initial_elapsed=self.archive.manifest.get('elapsed_seconds',0),
            session=self.archive.manifest.get('session',1),
            on_input=self._input,on_status=self.on_status)
        if prior:
            for row in prior.conversation:
                if row['role'] in ('user','assistant'):
                    self.controller.observe(VisibleMessage(row['turn_id'],row['role'],row['text'],
                        row['origin'],row.get('session',1)))
        self.simulation_task = asyncio.create_task(self.controller.run(turns=options.get('turns'),
            duration_seconds=options.get('duration_seconds')),name='liac-simulation')

    def _input(self, message, origin='manual', session=1):
        self._origins[message.turn_id] = origin
        self.archive.input(message,origin,session)
        if self.input_message:
            self.input_message(dict(turn_id=message.turn_id,text=message.text,role='user',
                                    origin=origin,session=session,status='completed'))

    async def submit(self,text):
        from vtuber.contracts.events import UserMessage
        if self.controller:
            self.controller.manual_input()
        message = UserMessage(text,self.config.character_id)
        session = self.controller.session if self.controller else 1
        self._input(message,'manual',session)
        if self.controller:
            self.controller.observe(VisibleMessage(message.turn_id,'user',text,'manual',session))
        return await self.runtime.submit(message)

    def _output(self, output):
        if output.kind != 'reply.delta':
            self.archive.observe_output(output)
        if output.kind == 'reply.delta':
            self._partials[output.turn_id] = self._partials.get(output.turn_id,'')+output.text
        elif output.kind in ('reply.completed','reply.cancelled','reply.failed'):
            partial = self._partials.pop(output.turn_id,'')
            if self.controller and (output.kind == 'reply.completed' or partial):
                text = output.text if output.kind == 'reply.completed' else partial+' [interrupted]'
                self.controller.observe(VisibleMessage(output.turn_id,'assistant',text,
                    'initiative' if output.turn_id.startswith('initiative_turn_') else 'reply',self.controller.session))
        if self.output:
            self.output(output)

    async def capture(self):
        state = await self.archive.capture(self.runtime)
        state['usage'] = self.usage
        if self.controller:
            self.archive.manifest.update(turns=self.controller.turns,session=self.controller.session)
        from time import monotonic
        if monotonic()-self._checkpoint >= 15:
            from vtuber.lab.archive import write_json
            self._checkpoint = monotonic()
            self.archive.manifest['elapsed_seconds'] = (self.archive._previous_elapsed+
                                                        monotonic()-self.archive._started)
            await asyncio.to_thread(write_json,self.archive.path/'run.json',self.archive.manifest)
        return state

    async def drain(self,timeout=90):
        async def settled():
            while self.runtime.deep_diagnostics.get('lifecycle') in ('starting','analyzing'):
                await asyncio.sleep(.2)
                await self.capture()
        try:
            await asyncio.wait_for(settled(),timeout)
        except TimeoutError:
            self.reason = 'Deep drain timeout; unfinished call is recorded as cancelled'

    async def __aexit__(self,kind,error,tb):
        try:
            if self.controller:
                await self.controller.stop()
            if self.simulation_task:
                await asyncio.gather(self.simulation_task,return_exceptions=True)
            await self.runtime.close()
            await self.capture()
            await self.manager.__aexit__(kind,error,tb)
        finally:
            await self.archive.close('failed' if error else self.result,
                                     type(error).__name__ if error else self.reason)
