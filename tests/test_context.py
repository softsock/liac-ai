import unittest

from vtuber.contracts.events import Event, UserMessage
from vtuber.contracts.state import CharacterState, FastSnapshot
from vtuber.context import ContextBudgetExceeded, ContextCompiler


class ContextTests(unittest.TestCase):
    def test_roles_current_dedup_and_newest_whole_history(self):
        current = UserMessage("current")
        events = (
            Event.create("primary", "user.message.completed", {"text": "x" * 1000}),
            Event.create("primary", "character.reply.completed", {"text": "newest"}),
            current.as_event(),
        )
        snapshot = FastSnapshot(CharacterState("primary", 3, "a note"), 5, events)
        compiled = ContextCompiler("Identity", context_tokens=900, output_tokens=100).compile(snapshot, current)
        self.assertEqual([m.role for m in compiled.messages], ["system", "user", "assistant", "user"])
        self.assertEqual(compiled.messages[-1].content, "current")
        self.assertIn("a note", compiled.messages[1].content)
        self.assertNotIn("a note", compiled.messages[0].content)
        self.assertEqual(compiled.history_included, 1)
        self.assertEqual(compiled.history_dropped, 1)
        self.assertLessEqual(compiled.estimated_input_tokens + 100, 900)
        self.assertEqual(compiled, ContextCompiler("Identity", 900, 100).compile(snapshot, current))

    def test_required_input_is_rejected_whole_instead_of_truncated(self):
        with self.assertRaises(ContextBudgetExceeded):
            ContextCompiler("Identity", 600, 100).compile(
                FastSnapshot(CharacterState("primary"), 0, ()), UserMessage("я" * 1000))
