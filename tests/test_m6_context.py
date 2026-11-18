import json
import unittest
from contextlib import closing
from dataclasses import replace

from tests._fixtures import batch, perception
from vtuber.contracts.events import Event, UserMessage
from vtuber.minds.m6_context import build_m6_messages
from vtuber.runtime.journal import EventConflict, Journal


def reply(text, **payload):
    return Event.create('primary', 'character.reply.completed', {'text': text, **payload},
                        occurred_at='2026-11-18T00:00:00+00:00')


class M6ContextTests(unittest.TestCase):
    def test_existing_m5_ingestion_unchanged(self):
        first = perception('one', content='first')
        ambient = perception('ambient', delivery='ambient')
        second = perception('two', content='second')
        with closing(Journal(':memory:')) as journal:
            accept = journal.accept_local_perceptions
            first_message = accept('primary', batch(first, ambient, first))
            self.assertEqual(first_message.text, 'first')
            self.assertEqual([e.event_id for e in journal.read('primary')],
                             ['one', 'ambient', first_message.event_id])
            self.assertEqual(journal.get('one').occurred_at, first.occurred_at)
            self.assertIsNone(accept('primary', batch(ambient, first)))
            with self.assertRaises(EventConflict):
                accept('primary', batch(second, replace(first, content='conflict')))
            with self.assertRaises(ValueError):
                accept('primary', batch(second, replace(first, author_id='other')))
            self.assertIsNone(journal.get('two'))
            self.assertEqual(accept('primary', batch(first, second)).text, 'second')

    def test_m6_tool_replay_uses_stable_call_id(self):
        user = UserMessage('First').as_event()
        current = UserMessage('Latest').as_event()
        event = reply('Hello!', action='speak', tool_call_id='call_real|fc_real')
        event = replace(event, turn_id=user.turn_id)
        context = build_m6_messages('You are Liac.', current, ((user, event),))
        _, _, call, result, _ = context.messages
        self.assertEqual(call['content'], [{'type': 'toolCall', 'name': 'speak',
                                           'id': 'call_real|fc_real', 'arguments': {'message': 'Hello!'}}])
        self.assertEqual((call['role'], call['api'], call['provider'], call['model'], call['stopReason']),
                         ('assistant', 'openai-codex-responses', 'openai-codex', 'gpt-6-luna', 'toolUse'))
        self.assertEqual(result['role'], 'toolResult')
        self.assertEqual(result['toolCallId'], 'call_real|fc_real')
        self.assertEqual(result['toolName'], 'speak')
        self.assertFalse(result['isError'])
        self.assertEqual(build_m6_messages('You are Liac.', current, ((user, event),)), context)

    def test_stay_silent_replay(self):
        user = UserMessage('First').as_event()
        event = replace(reply('', action='stay_silent', tool_call_id='quiet'), turn_id=user.turn_id)
        context = build_m6_messages('Identity', UserMessage('Latest').as_event(), ((user, event),))
        _, _, call, result, _ = context.messages
        self.assertEqual(call['content'], [{'type': 'toolCall', 'name': 'stay_silent',
                                           'id': 'quiet', 'arguments': {}}])
        self.assertEqual((result['toolCallId'], result['toolName']), ('quiet', 'stay_silent'))

    def test_legacy_reply_remains_plain_text(self):
        user = UserMessage('First').as_event()
        event = replace(reply('Legacy'), turn_id=user.turn_id)
        context = build_m6_messages('Identity', UserMessage('Latest').as_event(), ((user, event),))
        _, _, legacy, _ = context.messages
        self.assertEqual(legacy['role'], 'assistant')
        self.assertEqual(legacy['content'], [{'type': 'text', 'text': 'Legacy'}])

    def test_current_user_message_only_once(self):
        current = UserMessage('Latest').as_event()
        system, user = build_m6_messages('You are Liac.', current).messages
        self.assertEqual(system['role'], 'system')
        self.assertTrue(system['content'].startswith('You are Liac.'))
        self.assertIn('stay_silent', system['content'])
        self.assertEqual((user['role'], user['content']), ('user', 'Latest'))

    def test_oversized_history_cannot_block_next_turn(self):
        oversized = '⚙"' * 20_000
        current = UserMessage('Latest').as_event()
        old = UserMessage(oversized).as_event()
        previous = replace(reply('Short reply', action='speak', tool_call_id='call_previous'),
                           turn_id=old.turn_id)
        newest = UserMessage('Kept').as_event()
        silent = replace(reply('', action='stay_silent', tool_call_id='quiet'), turn_id=newest.turn_id)
        context = build_m6_messages('Identity', current, ((old, previous), (newest, silent)))
        messages = context.messages
        self.assertEqual([message['role'] for message in messages],
                         ['system', 'user', 'assistant', 'toolResult', 'user'])
        self.assertEqual(messages[1]['content'], 'Kept')
        self.assertEqual(messages[2]['content'][0]['id'], 'quiet')
        self.assertEqual(messages[3]['toolCallId'], 'quiet')
        self.assertEqual(messages[-1]['content'], 'Latest')
        self.assertLess(len(json.dumps(messages, ensure_ascii=False).encode()), 64 * 1024)
        with self.assertRaises(ValueError):
            build_m6_messages('Identity', old)

    def test_latest_message_has_priority_over_sensor_block(self):
        observation = perception('screen', kind='state', delivery='ambient', content='⚙' * 240)
        current = UserMessage('x' * 63_900).as_event()
        messages = build_m6_messages('Identity', current, observations=(observation,)).messages
        self.assertEqual([message['role'] for message in messages], ['system', 'user'])
        self.assertEqual(messages[-1]['content'], current.payload['text'])
