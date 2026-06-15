# Plugin/owismind/tests/test_agent_context.py
"""Pure multi-turn assembly: prefix, flatten exchanges -> messages, final list."""
import os, sys, unittest
from datetime import datetime
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.agents.context import (  # noqa: E402
    build_user_prefix, flatten_exchanges_to_messages, build_completion_messages,
)


class PrefixTests(unittest.TestCase):
    def test_prefix_contains_name_and_date(self):
        p = build_user_prefix("Said Chaoui", datetime(2026, 6, 9, 14, 30))
        self.assertIn("Said Chaoui", p)
        self.assertIn("2026", p)
        self.assertTrue(p.endswith(" "))  # trailing space so it joins onto the message

    def test_prefix_without_name(self):
        p = build_user_prefix(None, datetime(2026, 6, 9, 14, 30))
        self.assertIn("2026", p)  # still emits the date, no crash

    def test_prefix_adds_valid_mode_token(self):
        p = build_user_prefix("X", datetime(2026, 6, 9, 14, 30), mode="high")
        self.assertIn("⟦owi:mode=high⟧", p)
        self.assertTrue(p.endswith(" "))

    def test_prefix_ignores_unknown_mode(self):
        p = build_user_prefix("X", datetime(2026, 6, 9, 14, 30), mode="turbo")
        self.assertNotIn("owi:mode", p)

    def test_prefix_no_mode_token_by_default(self):
        p = build_user_prefix("X", datetime(2026, 6, 9, 14, 30))
        self.assertNotIn("owi:mode", p)


class FlattenTests(unittest.TestCase):
    def _rows(self):
        # chronological (oldest -> newest)
        return [
            {"user_text": "u1", "assistant_text": "a1"},
            {"user_text": "u2", "assistant_text": "a2"},
            {"user_text": "u3", "assistant_text": None},  # failed/no answer
        ]

    def test_order_and_roles(self):
        msgs = flatten_exchanges_to_messages(self._rows(), 10)
        self.assertEqual(
            msgs,
            [
                {"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"}, {"role": "assistant", "content": "a2"},
                {"role": "user", "content": "u3"},
            ],
        )

    def test_trims_to_last_n_messages(self):
        msgs = flatten_exchanges_to_messages(self._rows(), 2)
        self.assertEqual(msgs, [{"role": "assistant", "content": "a2"}, {"role": "user", "content": "u3"}])

    def test_skips_empty(self):
        rows = [{"user_text": "", "assistant_text": "a"}, {"user_text": "u", "assistant_text": ""}]
        self.assertEqual(
            flatten_exchanges_to_messages(rows, 10),
            [{"role": "assistant", "content": "a"}, {"role": "user", "content": "u"}],
        )


class BuildTests(unittest.TestCase):
    def test_history_then_current_prefixed(self):
        history = [{"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"}]
        out = build_completion_messages(history, "now?", "[PFX] ")
        self.assertEqual(out[:2], history)
        self.assertEqual(out[-1], {"role": "user", "content": "[PFX] now?"})

    def test_empty_history(self):
        out = build_completion_messages([], "hi", "[PFX] ")
        self.assertEqual(out, [{"role": "user", "content": "[PFX] hi"}])


class SqlContextTests(unittest.TestCase):
    def test_format_sql_context_empty(self):
        from owismind.agents.context import _format_sql_context
        self.assertEqual(_format_sql_context(None), "")
        self.assertEqual(_format_sql_context([]), "")

    def test_format_sql_context_joins_and_bounds(self):
        from owismind.agents.context import _format_sql_context
        out = _format_sql_context([{"sql": "SELECT 1"}, {"sql": "SELECT 2"}])
        self.assertIn("SELECT 1", out)
        self.assertIn("SELECT 2", out)
        self.assertTrue(out.startswith("\n\n"))

    def test_flatten_appends_sql_to_assistant(self):
        rows = [{"user_text": "u1", "assistant_text": "a1", "generated_sql": [{"sql": "SELECT 42"}]}]
        msgs = flatten_exchanges_to_messages(rows, 10)
        self.assertEqual(msgs[0], {"role": "user", "content": "u1"})
        self.assertEqual(msgs[1]["role"], "assistant")
        self.assertIn("a1", msgs[1]["content"])
        self.assertIn("SELECT 42", msgs[1]["content"])

    def test_flatten_no_sql_unchanged(self):
        rows = [{"user_text": "u", "assistant_text": "a"}]
        msgs = flatten_exchanges_to_messages(rows, 10)
        self.assertEqual(msgs[1], {"role": "assistant", "content": "a"})

if __name__ == "__main__":
    unittest.main()
