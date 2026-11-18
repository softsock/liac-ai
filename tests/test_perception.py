import unittest
from dataclasses import FrozenInstanceError, replace

from tests._fixtures import perception
from vtuber.contracts.perception import PerceptionBatch


class PerceptionTests(unittest.TestCase):
    def test_frozen_records_preserve_text_and_author_identity(self):
        item = perception(content='Display name: Alex\n  original text  ', author_id='user-42')
        self.assertEqual(item.author_id, 'user-42')
        self.assertEqual(item.content, 'Display name: Alex\n  original text  ')
        with self.assertRaises(FrozenInstanceError):
            item.content = 'changed'
        batch = PerceptionBatch('local', (item,), 'quiet')
        with self.assertRaises(FrozenInstanceError):
            batch.items = ()

    def test_invalid_fields_raise_value_error(self):
        for field, values in {
            'perception_id': ['', ' ', None, 7], 'source': ['', ' ', None],
            'conversation_key': ['', ' ', None], 'kind': ['image', None, []],
            'delivery': ['urgent', None, []], 'content': ['', ' ', None, 7],
            'author_id': ['', ' ', 7], 'dedupe_key': ['', ' ', 7],
            'occurred_at': ['', None, 7, 'yesterday', '2026-11-17',
                            '2026-11-17T12:00:00', '2026-11-17T12:00:00+01:00'],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    perception(**{field: value})

    def test_utc_z_and_empty_noise_are_valid(self):
        item = perception(occurred_at='2026-11-17T12:00:00Z', delivery='noise', content='')
        self.assertEqual(item.content, '')

    def test_batch_rejects_empty_mutable_or_mismatched_items(self):
        item = perception()
        for key, items, reason in [('', (item,), 'quiet'), ('local', (), 'quiet'),
                ('local', [item], 'quiet'), ('elsewhere', (item,), 'quiet'),
                ('local', (object(),), 'quiet'), ('local', (item,), 'timeout')]:
            with self.subTest(key=key, items=items, reason=reason), self.assertRaises(ValueError):
                PerceptionBatch(key, items, reason)

    def test_batch_preserves_ingress_order_not_source_time(self):
        first = perception('first', occurred_at='2026-11-17T12:00:01Z')
        second = replace(first, perception_id='second', occurred_at='2026-11-17T11:00:00Z')
        self.assertEqual(PerceptionBatch('local', (first, second), 'immediate').items,
                         (first, second))
