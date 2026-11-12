import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from vtuber.contracts.events import Event
from vtuber.contracts.state import NoteProposal
from vtuber.runtime.journal import EventConflict, Journal


class JournalTests(unittest.TestCase):
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
