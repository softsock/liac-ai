import json
import unittest

from vtuber.contracts.deep import CompactionInput, DeepRequest, DeepResult
from vtuber.contracts.events import Event
from vtuber.contracts.state import CharacterState, FastSnapshot
from vtuber.minds.luna import parse_result, render_request


class LunaParserTests(unittest.TestCase):
    def setUp(self):
        self.event = Event.create('primary', 'user.message.completed', {'text': 'green hat'}, event_id='source')
        from dataclasses import replace
        self.event = replace(self.event, sequence=1)
        self.request = DeepRequest('request', FastSnapshot(CharacterState('primary', 2), 1,
            (self.event,)), 0, (self.event,), CompactionInput(1, (self.event,)))

    def test_parse_note_and_summary(self):
        result = parse_result(json.dumps({'schema_version': 1,
            'note': {'text': 'Remember green.', 'source_event_ids': ['source']},
            'compaction': {'items': [{'text': 'Hat is green.', 'source_event_ids': ['source'], 'kind': 'summary'}]}}), self.request)
        self.assertEqual(result.note.based_on_revision, 2)
        self.assertEqual(result.note.proposal_id, 'request:note')
        self.assertEqual(result.compaction.items[0].source_event_ids, ('source',))
        self.assertEqual(result.compaction.compacted_through_sequence, 1)

    def test_explicit_noop(self):
        self.assertEqual(parse_result('{"schema_version":1,"note":null,"compaction":null}', self.request), DeepResult(1, 'request'))

    def test_note_can_cite_prior_snapshot_history(self):
        from dataclasses import replace
        request = replace(self.request, events=(), compaction=None)
        result = parse_result('{"schema_version":1,"note":{"text":"green hat","source_event_ids":["source"]},"compaction":null}',request)
        self.assertEqual(result.note.source_event_ids, ('source',))

    def test_reject_untrusted_json(self):
        bad = ['{"schema_version":1,"schema_version":1,"note":null,"compaction":null}',
            '{"schema_version":true,"note":null,"compaction":null}',
            '{"schema_version":2,"note":null,"compaction":null}',
            '{"schema_version":1,"note":null}', '```json\n{}\n```', '{} trailing',
            json.dumps({'schema_version': 1, 'note': None, 'compaction': None, 'tools': []})]
        for note in [True, {'text': 'x'*1001, 'source_event_ids': ['source']},
                     {'text': 'x', 'source_event_ids': ['invented']},
                     {'text': 'x', 'source_event_ids': ['source']*33}]:
            bad.append(json.dumps({'schema_version': 1, 'note': note, 'compaction': None}))
        for item in [{'text': 'x'*8001, 'source_event_ids': ['source'], 'kind': 'summary'},
                     {'text': 'x', 'source_event_ids': ['source'], 'kind': 'tool'}]:
            bad.append(json.dumps({'schema_version': 1, 'note': None, 'compaction': {'items': [item]}}))
        bad.append(' '*65537)
        for text in bad:
            with self.subTest(text=text[:100]), self.assertRaises(ValueError):
                parse_result(text, self.request)

    def test_prompt_quotes_evidence(self):
        text = render_request(self.request)
        self.assertIn('green hat', text)
        self.assertEqual(json.loads(text)['request_id'], 'request')


class FakeDeepTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_uses_new_request(self):
        from vtuber.minds.fake import FakeDeep
        event = Event.create('primary', 'user.message.completed', {'text': 'green'}, event_id='source')
        request = DeepRequest('id', FastSnapshot(CharacterState('primary'), 1, (event,)), 0, (event,))
        result = await FakeDeep(0).propose(request)
        self.assertEqual(result.request_id, 'id')
        self.assertEqual(result.note.source_event_ids, ('source',))
