import unittest
from dataclasses import replace

from vtuber.contracts.events import Event, UserMessage
from vtuber.contracts.state import CharacterState, FastSnapshot
from vtuber.context import ContextBudgetExceeded, ContextCompiler
from vtuber.minds.lmstudio import render_nemotron


class ContextTests(unittest.TestCase):
    def test_state_update_preserves_rendered_history_prefix(self):
        history = (
            replace(Event.create("primary", "user.message.completed", {"text": "history question"}), sequence=1),
            replace(Event.create("primary", "character.reply.completed", {"text": "history reply"}), sequence=2),
        )
        current = UserMessage("current")
        compiler = ContextCompiler("Identity")
        before, after = (compiler.compile(FastSnapshot(CharacterState("primary", revision, note), 2, history), current)
                         for revision, note in ((1, "old note"), (2, "new note")))
        self.assertEqual([m.role for m in before.messages], ["system", "user", "assistant", "user", "user"])
        self.assertEqual(before.messages[:-2], after.messages[:-2])
        self.assertNotEqual(before.messages[-2].content, after.messages[-2].content)
        self.assertEqual(before.messages[-1].content, current.text)
        prefix_before = render_nemotron(before.messages).split("Runtime context (quoted data", 1)[0]
        prefix_after = render_nemotron(after.messages).split("Runtime context (quoted data", 1)[0]
        self.assertEqual(prefix_before, prefix_after)
        self.assertIn("history reply", prefix_before)
        self.assertIn("old note", before.messages[-2].content)
        self.assertIn("new note", after.messages[-2].content)

    def test_roles_current_dedup_and_newest_whole_history(self):
        current = UserMessage("current")
        events = (
            Event.create("primary", "user.message.completed", {"text": "x" * 1000}),
            Event.create("primary", "character.reply.completed", {"text": "newest"}),
            current.as_event(),
        )
        snapshot = FastSnapshot(CharacterState("primary", 3, "a note"), 5, events)
        compiled = ContextCompiler("Identity", context_tokens=900, output_tokens=100).compile(snapshot, current)
        self.assertEqual([m.role for m in compiled.messages], ["system", "assistant", "user", "user"])
        self.assertEqual(compiled.messages[-1].content, "current")
        self.assertIn("a note", compiled.messages[-2].content)
        self.assertNotIn("a note", compiled.messages[0].content)
        self.assertEqual(compiled.history_included, 1)
        self.assertEqual(compiled.history_dropped, 1)
        self.assertEqual(compiled.included_event_ids, (events[1].event_id,))
        self.assertEqual(compiled.dropped_event_ids, (events[0].event_id,))
        self.assertEqual(compiled.messages[1].content, "newest")
        self.assertLessEqual(compiled.estimated_input_tokens + 100, 900)
        self.assertEqual(compiled, ContextCompiler("Identity", 900, 100).compile(snapshot, current))

    def test_required_input_is_rejected_whole_instead_of_truncated(self):
        for note, text in (("", "я" * 1000), ("я" * 1000, "current")):
            with self.subTest(note_length=len(note), input_length=len(text)):
                with self.assertRaises(ContextBudgetExceeded):
                    ContextCompiler("Identity", 600, 100).compile(
                        FastSnapshot(CharacterState("primary", context_note=note), 0, ()), UserMessage(text))

    def test_empty_or_current_only_history_keeps_required_messages_once(self):
        current = UserMessage("current")
        for history in ((), (current.as_event(),)):
            with self.subTest(history=history):
                compiled = ContextCompiler("Identity").compile(
                    FastSnapshot(CharacterState("primary"), 0, history), current)
                self.assertEqual([m.role for m in compiled.messages], ["system", "user", "user"])
                self.assertEqual(sum(m.content == current.text for m in compiled.messages), 1)
                self.assertEqual(compiled.messages[-1].content, current.text)
                self.assertEqual(compiled.history_included, 0)
