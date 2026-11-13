import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from vtuber.contracts.events import Event, UserMessage
from vtuber.contracts.context import ContextItem, CompactionProposal
from vtuber.contracts.state import NoteProposal
from vtuber.runtime.journal import EventConflict, Journal


class JournalTests(unittest.TestCase):
    def exchange(self, text='anchor', character='primary'):
        message = UserMessage(text, character)
        user = self.journal.append(message.as_event())
        reply = self.journal.append(Event.create(character, 'character.reply.completed', {'text': 'reply'},
                                                turn_id=message.turn_id))
        return user, reply

    def compact(self, user, reply, **changes):
        p = CompactionProposal('compact-1', user.character_id, 0, 0, reply.sequence,
                               reply.sequence, (ContextItem(user.payload['text'], (user.event_id,)),))
        return replace(p, **changes)

    def test_v1_migration_preserves_state_cursor_and_events(self):
        user, reply = self.exchange()
        self.journal.apply_note(self.proposal(user), cursor_from=0)
        state, cursor, events = self.journal.snapshot('primary'), self.journal.cursor('primary'), self.journal.read('primary')
        self.journal.close()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TABLE IF EXISTS context_epochs')
            db.execute('PRAGMA user_version=1')
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.journal.context_epoch('primary').version, 0)
        self.assertEqual(self.journal.snapshot('primary'), state)
        self.assertEqual(self.journal.cursor('primary'), cursor)
        self.assertEqual(self.journal.read('primary'), events)

    def test_epoch_and_audit_rollback_and_restart(self):
        user, reply = self.exchange()
        proposal = self.compact(user, reply)
        with closing(sqlite3.connect(self.path, isolation_level=None)) as db:
            db.execute("""CREATE TRIGGER reject_epoch BEFORE INSERT ON events
                WHEN json_extract(NEW.content, '$.kind') = 'context.epoch.applied'
                BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.journal.apply_compaction(proposal)
        self.assertEqual(self.journal.context_epoch('primary').version, 0)
        self.assertIsNone(self.journal.get('compaction_compact-1'))
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TRIGGER reject_epoch')
        self.assertTrue(self.journal.apply_compaction(proposal).accepted)
        epoch = self.journal.context_epoch('primary')
        self.assertEqual((epoch.version, epoch.compacted_through_sequence), (1, reply.sequence))
        self.assertEqual((self.journal.snapshot('primary').revision, self.journal.cursor('primary')), (0, 0))
        self.journal.close()
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        self.assertEqual(self.journal.context_epoch('primary'), epoch)

    def test_compaction_replay_conflicts_and_invalid_ranges(self):
        user, reply = self.exchange()
        foreign, _ = self.exchange(character='other')
        unfinished = self.journal.append(UserMessage('not answered').as_event())
        p = self.compact(user, reply)
        cases = [
            (dict(based_on_epoch=1), 'epoch_conflict'),
            (dict(based_on_revision=1), 'revision_conflict'),
            (dict(compacted_through_sequence=user.sequence), 'invalid_cutoff'),
            (dict(compacted_through_sequence=unfinished.sequence, observed_through_sequence=unfinished.sequence), 'invalid_cutoff'),
            (dict(observed_through_sequence=True), 'invalid_watermark'),
            (dict(compacted_through_sequence=1000), 'invalid_watermark'),
            (dict(items=(ContextItem('wrong', (user.event_id,)),)), 'invalid_extract'),
            (dict(items=(ContextItem('text', ('missing',)),)), 'invalid_source'),
            (dict(items=(ContextItem('text', (foreign.event_id,)),)), 'invalid_source'),
            (dict(items=(ContextItem('not answered', (unfinished.event_id,)),)), 'invalid_source'),
            (dict(items=(ContextItem('', (user.event_id,)),)), 'invalid_item'),
            (dict(items=(ContextItem('text', (user.event_id,), kind='unknown'),)), 'invalid_item'),
            (dict(compacted_through_sequence=0, items=()), 'no_change'),
        ]
        for i, (changes, reason) in enumerate(cases):
            with self.subTest(reason=reason, changes=changes):
                invalid = replace(p, proposal_id=f'invalid-{i}', **changes)
                result = self.journal.apply_compaction(invalid)
                self.assertEqual(result.reason, reason)
                self.assertFalse(result.accepted)
                self.assertEqual(self.journal.apply_compaction(invalid), result)
                self.assertEqual(self.journal.context_epoch('primary').version, 0)
        result = self.journal.apply_compaction(p)
        self.assertTrue(result.accepted)
        self.assertEqual(self.journal.apply_compaction(p), result)
        with self.assertRaises(EventConflict):
            self.journal.apply_compaction(replace(p, items=()))

    def test_late_compaction_preserves_newer_exact_turns(self):
        user, reply = self.exchange()
        p = self.compact(user, reply)
        later = self.exchange('later')
        self.assertTrue(self.journal.apply_compaction(p).accepted)
        snapshot = self.journal.fast_snapshot('primary')
        self.assertEqual(snapshot.recent_dialogue, later)
        self.assertEqual(snapshot.epoch.version, 1)

    def test_snapshot_exposes_cancelled_turn_boundary_without_partial_speech(self):
        message = UserMessage('cancel this')
        self.journal.append(message.as_event())
        ended = self.journal.append(Event.create('primary', 'character.reply.cancelled',
                                                {'reason': 'superseded'}, turn_id=message.turn_id))
        snapshot = self.journal.fast_snapshot('primary')
        self.assertEqual(snapshot.terminal_turns, ((message.turn_id, ended.sequence),))
        self.assertEqual([e.payload['text'] for e in snapshot.recent_dialogue], ['cancel this'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "journal.sqlite3"
        self.journal = Journal(self.path)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.journal.close)

    def event(self, text="hello", character="primary"):
        return Event.create(character, "user.message.completed", {"text": text})

    def proposal(self, event):
        return NoteProposal("proposal-1", event.character_id, 0, event.sequence,
                            (event.event_id,), "Remember hello")

    def test_duplicate_is_noop_and_conflicting_content_fails(self):
        event = self.event()
        first = self.journal.append(event)
        self.assertEqual(self.journal.append(event), first)
        with self.assertRaises(EventConflict):
            self.journal.append(replace(event, payload_json='{"text":"changed"}'))
        self.assertEqual(len(self.journal.read("primary")), 1)

    def test_sequence_is_per_character_and_survives_restart(self):
        self.assertEqual(self.journal.append(self.event()).sequence, 1)
        self.assertEqual(self.journal.append(self.event(character="other")).sequence, 1)
        self.journal.close()
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        second = self.journal.append(self.event("again"))
        self.assertEqual(second.sequence, 2)
        self.assertEqual(self.journal.read("primary", after=1), (second,))

    def test_state_audit_cursor_rollback_together_on_failed_write(self):
        event = self.journal.append(self.event())
        with closing(sqlite3.connect(self.path, isolation_level=None)) as db:
            db.execute("""CREATE TRIGGER reject_patch BEFORE INSERT ON events
                WHEN json_extract(NEW.content, '$.kind') = 'state.patch.applied'
                BEGIN SELECT RAISE(ABORT, 'injected disk-write failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.journal.apply_note(self.proposal(event), cursor_from=0)
        self.assertEqual(self.journal.snapshot("primary").revision, 0)
        self.assertEqual(self.journal.cursor("primary"), 0)
        self.assertEqual(len(self.journal.read("primary")), 1)
        with closing(sqlite3.connect(self.path, isolation_level=None)) as db:
            db.execute("DROP TRIGGER reject_patch")
        self.assertTrue(self.journal.apply_note(self.proposal(event), cursor_from=0).accepted)

    def test_revision_rejection_deduplication_and_persistent_acknowledgement(self):
        event = self.journal.append(self.event())
        proposal = self.proposal(event)
        result = self.journal.apply_note(proposal, cursor_from=0)
        self.assertTrue(result.accepted)
        self.assertEqual(self.journal.apply_note(proposal, cursor_from=0), result)
        with self.assertRaises(EventConflict):
            self.journal.apply_note(replace(proposal, note="conflicting reuse"))
        stale = replace(proposal, proposal_id="stale", note="must not overwrite")
        rejection = self.journal.apply_note(stale)
        self.assertFalse(rejection.accepted)
        self.assertEqual(rejection.reason, "revision_conflict")
        self.journal.close()
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        state = self.journal.snapshot("primary")
        self.assertEqual((state.revision, state.context_note), (1, "Remember hello"))
        self.assertEqual(self.journal.cursor("primary"), event.sequence)
        self.assertEqual([e.kind for e in self.journal.read("primary")],
                         ["user.message.completed", "state.patch.applied", "state.patch.rejected"])

    def test_duplicate_proposal_acknowledges_a_previously_unacked_batch(self):
        event = self.journal.append(self.event())
        proposal = self.proposal(event)
        original = self.journal.apply_note(proposal)
        self.assertEqual(self.journal.cursor("primary"), 0)
        self.assertEqual(self.journal.apply_note(proposal, cursor_from=0), original)
        self.assertEqual(self.journal.cursor("primary"), event.sequence)
        self.assertEqual(self.journal.snapshot("primary").revision, 1)
