# Plugin/owismind/tests/test_agent_context.py
"""Pure multi-turn assembly: END-placed context suffix, language detection,
flatten exchanges -> messages, final list."""
import os, sys, unittest
from datetime import datetime
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.agents.context import (  # noqa: E402
    build_user_suffix, detect_prompt_language, flatten_exchanges_to_messages,
    build_completion_messages, build_screen_state,
)


class SuffixTests(unittest.TestCase):
    def test_suffix_contains_name_and_date(self):
        s = build_user_suffix("Said Chaoui", datetime(2026, 6, 9, 14, 30))
        self.assertIn("Said Chaoui", s)
        self.assertIn("2026", s)
        self.assertTrue(s.startswith("\n\n"))  # appended block, separated from the message

    def test_suffix_without_name(self):
        s = build_user_suffix(None, datetime(2026, 6, 9, 14, 30))
        self.assertIn("2026", s)  # still emits the date, no crash

    def test_suffix_adds_valid_mode_and_lang_tokens(self):
        s = build_user_suffix("X", datetime(2026, 6, 9, 14, 30),
                              webapp_lang="en", prompt_lang="fr", mode="claude")
        self.assertIn("⟦owi:mode=claude⟧", s)
        self.assertIn("⟦owi:lang=fr⟧", s)
        self.assertIn("Web app language: English", s)

    def test_suffix_language_imperative_is_last_line(self):
        # The load-bearing reply-language rule must sit in the highest-recency slot.
        s = build_user_suffix("X", datetime(2026, 6, 9, 14, 30), prompt_lang="fr")
        last = s.strip().splitlines()[-1]
        self.assertIn("reply in French", last)
        self.assertIn("priority", last)

    def test_suffix_ignores_unknown_mode_and_lang(self):
        s = build_user_suffix("X", datetime(2026, 6, 9, 14, 30),
                              webapp_lang="zz", prompt_lang="zz", mode="turbo")
        self.assertNotIn("owi:mode", s)
        self.assertNotIn("owi:lang", s)
        self.assertNotIn("Web app language", s)

    def test_suffix_no_tokens_by_default(self):
        s = build_user_suffix("X", datetime(2026, 6, 9, 14, 30))
        self.assertNotIn("owi:mode", s)
        self.assertNotIn("owi:lang", s)


class DetectLanguageTests(unittest.TestCase):
    def test_french_accents(self):
        self.assertEqual(detect_prompt_language("Quelle est l'évolution des revenus ?"), "fr")

    def test_french_markers(self):
        self.assertEqual(detect_prompt_language("montre les revenus du client"), "fr")

    def test_english_markers(self):
        self.assertEqual(detect_prompt_language("What is the revenue trend?"), "en")

    def test_neutral_falls_back_to_default(self):
        self.assertEqual(detect_prompt_language("42", default="en"), "en")
        self.assertEqual(detect_prompt_language("", default="fr"), "fr")
        self.assertEqual(detect_prompt_language("   ", default="en"), "en")

    def test_add_forecast_is_french(self):
        # The exact failing case from production: a follow-up in French.
        self.assertEqual(detect_prompt_language("tu peux rajouter le forecast ?"), "fr")

    def test_add_forecast_english(self):
        self.assertEqual(detect_prompt_language("can you add the forecast?"), "en")

    def test_terse_english_revenue_not_mistaken_for_french(self):
        # 'revenu' (FR) must NOT match inside 'revenue' (EN) - word-boundary matching.
        self.assertEqual(detect_prompt_language("revenue EVPL 2026", default="en"), "en")
        self.assertEqual(detect_prompt_language("revenue figures", default="en"), "en")

    def test_french_revenus_still_french(self):
        self.assertEqual(detect_prompt_language("revenus EVPL 2026", default="fr"), "fr")

    def test_english_add_word_boundary(self):
        # 'add' matches as a whole word, not inside other tokens.
        self.assertEqual(detect_prompt_language("add the budget series", default="fr"), "en")


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
    def test_history_then_current_with_suffix(self):
        history = [{"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"}]
        out = build_completion_messages(history, "now?", "\n\n[SFX]")
        self.assertEqual(out[:2], history)
        self.assertEqual(out[-1], {"role": "user", "content": "now?\n\n[SFX]"})

    def test_empty_history(self):
        out = build_completion_messages([], "hi", "\n\n[SFX]")
        self.assertEqual(out, [{"role": "user", "content": "hi\n\n[SFX]"}])

    def test_no_suffix(self):
        out = build_completion_messages([], "hi", "")
        self.assertEqual(out, [{"role": "user", "content": "hi"}])


class ScreenStateTests(unittest.TestCase):
    def test_empty_when_nothing_on_screen(self):
        self.assertEqual(build_screen_state([]), "")
        self.assertEqual(build_screen_state(None), "")

    def test_chart_artifact_described_with_columns(self):
        arts = [{"kind": "chart", "title": "Monthly revenue 2026",
                 "chart": {"type": "line", "x": "month", "y": ["actuals", "budget"]}}]
        s = build_screen_state(arts, last_answer_excerpt="Revenue peaked in March.")
        self.assertTrue(s.startswith("\n\n[ON SCREEN NOW"))
        self.assertIn("line chart", s)
        self.assertIn("Monthly revenue 2026", s)
        self.assertIn("x=month", s)
        self.assertIn("actuals", s)            # column surfaced
        self.assertIn("Revenue peaked in March.", s)
        self.assertIn("call the specialist", s)  # honesty firewall preserved

    def test_kpi_and_active_tab(self):
        arts = [{"kind": "kpi", "title": "Revenue YTD",
                 "kpi": {"label": "Revenue YTD", "value": "Revenue_EUR"}}]
        s = build_screen_state(arts, active_tab="chart")
        self.assertIn("KPI card", s)
        self.assertIn("Revenue_EUR", s)
        self.assertIn("'chart' tab", s)

    def test_bounded_artifacts(self):
        arts = [{"kind": "table", "title": "T%d" % i} for i in range(10)]
        s = build_screen_state(arts)
        # capped at MAX_SCREEN_ARTIFACTS (4)
        self.assertEqual(s.count("a table"), 4)


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
