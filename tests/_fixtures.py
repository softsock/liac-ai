from vtuber.contracts.mind import MindDecision
from vtuber.contracts.perception import Perception, PerceptionBatch


def perception(identifier='p1', **changes):
    values = dict(perception_id=identifier, kind='chat', source='local',
                  conversation_key='local', content='hello',
                  occurred_at='2026-11-17T12:00:00+00:00', delivery='direct')
    return Perception(**(values | changes))


def batch(*items):
    return PerceptionBatch(items[0].conversation_key, items, 'quiet')


class ScriptedMind:
    def __init__(self, *scripts):
        self.calls = []
        self.scripts = iter(scripts)

    async def generate(self, messages, *, on_speak_delta=None):
        self.calls.append(messages)
        scripted = next(self.scripts)
        if isinstance(scripted, MindDecision):
            return scripted
        return await scripted(messages, on_speak_delta)
