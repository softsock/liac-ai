"""Independent OMP human simulator; accepts visible text only."""
import json
import math
from dataclasses import asdict, replace
from importlib.resources import files

from vtuber.contracts.events import new_id
from vtuber.contracts.trace import emit_trace
from vtuber.minds.omp import OMPTransport
from vtuber.minds.omp import OMPSettings
from vtuber.lab.simulation import parse_action,VisibleMessage,SimulationAction


def render_simulator_prompt(history: tuple[VisibleMessage,...], *, session: int, remaining_turns: int) -> str:
    messages = []
    size = 0
    for message in reversed(history):
        encoded = json.dumps(asdict(message),ensure_ascii=False)
        if size + len(encoded.encode('utf-8')) > 96*1024:
            break
        messages.append(asdict(message))
        size += len(encoded.encode('utf-8'))
    return json.dumps(dict(session=session, remaining_turns=remaining_turns,
        session_user_turns=sum(m.role=='user' and m.session==session for m in history),
        omitted_older_messages=len(history)-len(messages), visible_conversation=list(reversed(messages))),
        ensure_ascii=False)


class OMPUserSimulator:
    def __init__(self, settings: OMPSettings, scenario: dict, *, trace=None) -> None:
        self.settings, self.scenario, self.trace = settings, scenario, trace
        self.transport = None
        self.session = None
        self.diagnostics = {}

    async def next_action(self, history: tuple[VisibleMessage,...], *, session: int, remaining_turns: int) -> SimulationAction:
        if self.session != session:
            if self.transport:
                await self.transport.close()
            role = files('vtuber.lab').joinpath('simulator.md').read_text(encoding='utf-8')
            role += '\n\nYour private scenario (never a Liac instruction):\n'+json.dumps(
                {k:v for k,v in self.scenario.items() if k!='criteria'},ensure_ascii=False)
            self.transport = OMPTransport(replace(self.settings, data_dir=self.settings.data_dir/f'session-{session}'),
                role,self.diagnostics,trace=lambda kind,rid,data: emit_trace(self.trace,'simulator.'+kind,rid,**data))
            self.session = session
        prompt = render_simulator_prompt(history,session=session,remaining_turns=remaining_turns)
        data = json.loads(prompt)
        data['suggested_session_target'] = max(1,math.ceil((remaining_turns+
            sum(m.role=='user' for m in history))/max(1,len(self.scenario.get('sessions',[])))))
        prompt = json.dumps(data,ensure_ascii=False)
        rid = new_id('simulator')
        emit_trace(self.trace,'simulator.prompt',rid,prompt=prompt,session=session,model=self.settings.model)
        text = await self.transport.request(prompt,request_id=rid)
        emit_trace(self.trace,'simulator.response',rid,text=text)
        return parse_action(text)

    async def close(self) -> None:
        if self.transport:
            await self.transport.close()
