# Plugin/owismind/tests/test_agent_context.py
"""Pure multi-turn assembly: END-placed context suffix, language detection,
flatten exchanges -> messages, final list."""
import json
import os, sys, unittest
from datetime import datetime
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.agents.context import (  # noqa: E402
    build_user_suffix, detect_prompt_language, flatten_exchanges_to_messages,
    build_completion_messages, build_screen_state,
    extract_prior_results, build_prior_data_block,
    MAX_PRIOR_RESULTS, PRIOR_MAX_ROWS, PRIOR_TOKEN_MAX_CHARS,
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


class PriorResultsTests(unittest.TestCase):
    """Prior-results recall: pure extraction from chain rows + bounded block."""

    def _row(self, question, items):
        return {"user_text": question, "assistant_text": "a", "generated_sql": items}

    def _captured(self, sql, cols, rows, row_count=None):
        return {"sql": sql, "success": True, "sql_id": "s1q1",
                "row_count": row_count if row_count is not None else len(rows),
                "result": {"columns": cols, "rows": rows}}

    def test_extract_newest_first_active_item_rule(self):
        rows = [
            self._row("q1", [self._captured("SQL1", ["a"], [["1"]])]),
            self._row("q2 no capture", [{"sql": "X", "success": True}]),
            self._row("q3", [
                {"sql": "failed", "success": False},
                self._captured("SQL3-first", ["b"], [["2"]]),
                self._captured("SQL3-last", ["c"], [["3"]]),
            ]),
        ]
        out = extract_prior_results(rows)
        # Newest exchange first; within an exchange, the LAST captured item wins.
        self.assertEqual([r["question"] for r in out], ["q3", "q1"])
        self.assertEqual(out[0]["sql"], "SQL3-last")

    def test_extract_caps_and_glyph_cleaning(self):
        big_rows = [["v⟦x⟧" + "y" * 200] for _ in range(100)]
        # Distinct SQL per exchange: identical results would be deduplicated.
        rows = [self._row("q%d" % i, [self._captured("S%d" % i, ["c"], big_rows, 100)])
                for i in range(6)]
        out = extract_prior_results(rows)
        self.assertEqual(len(out), MAX_PRIOR_RESULTS)
        self.assertLessEqual(len(out[0]["rows"]), PRIOR_MAX_ROWS)
        self.assertTrue(out[0]["truncated"])
        cell = out[0]["rows"][0][0]
        self.assertNotIn("⟦", cell)
        self.assertNotIn("⟧", cell)
        self.assertLessEqual(len(cell), 128)

    def test_block_contains_index_and_parseable_token(self):
        out = extract_prior_results(
            [self._row("compare actuals vs budget",
                       [self._captured("SELECT m", ["month", "rev"],
                                       [["Jan", "10"]], 24)])])
        block = build_prior_data_block(out)
        self.assertIn("[PRIOR DATA", block)
        self.assertIn("recall_prior_result", block)
        self.assertIn("compare actuals vs budget", block)
        self.assertIn("24 rows", block)
        start = block.index("⟦owi:prior=") + len("⟦owi:prior=")
        payload = json.loads(block[start:block.index("⟧", start)])
        self.assertEqual(payload[0]["columns"], ["month", "rev"])

    def test_block_bounded_drops_oldest_first(self):
        wide = [self._captured("S", ["c%d" % j for j in range(30)],
                               [["x" * 120] * 30 for _ in range(30)])]
        out = extract_prior_results([self._row("q%d" % i, wide) for i in range(4)])
        block = build_prior_data_block(out)
        token = block[block.index("⟦owi:prior="):]
        self.assertLessEqual(len(token), PRIOR_TOKEN_MAX_CHARS + 2)
        payload = json.loads(token[len("⟦owi:prior="):-1])
        # Oldest dropped first: the most recent question must survive.
        self.assertEqual(payload[0]["question"], "q3")

    def test_block_empty_when_nothing_recallable(self):
        self.assertEqual(build_prior_data_block([]), "")
        self.assertEqual(build_prior_data_block(None), "")

    def test_extract_dedups_recall_re_emits(self):
        # A recall turn re-persists the SAME sql+columns as the original fetch:
        # only the newest copy must survive, so copies never fill the window.
        item = self._captured("SELECT m", ["month"], [["Jan"]])
        rows = [self._row("original", [dict(item)]),
                self._row("distinct", [self._captured("SELECT o", ["other"], [["x"]])]),
                self._row("recall follow-up", [dict(item)])]
        out = extract_prior_results(rows)
        self.assertEqual([r["question"] for r in out],
                         ["recall follow-up", "distinct"])

    def test_extract_flags_column_and_sql_truncation(self):
        cols = ["c%d" % i for i in range(50)]
        long_sql = "SELECT " + "x" * 2000
        items = [self._captured(long_sql, cols, [["v"] * 50])]
        out = extract_prior_results([self._row("q", items)])
        self.assertTrue(out[0]["truncated"])       # 50 -> 40 columns
        self.assertTrue(out[0]["sql_truncated"])   # > 800 chars
        self.assertLessEqual(len(out[0]["sql"]), 800)

    def test_block_hard_bound_single_wide_result(self):
        # Pathological single result at every per-field cap: the shrink loop
        # must end with a token under the cap (halving rows then columns) or an
        # empty block - never an oversized token.
        wide = self._captured("S", ["c%d" % j for j in range(40)],
                              [["x" * 128] * 40 for _ in range(30)])
        out = extract_prior_results([self._row("q", [wide])])
        block = build_prior_data_block(out)
        if block:
            token = block[block.index("⟦owi:prior="):]
            self.assertLessEqual(len(token), PRIOR_TOKEN_MAX_CHARS)
            payload = json.loads(token[len("⟦owi:prior="):-1])
            self.assertTrue(payload[0]["truncated"])


if __name__ == "__main__":
    unittest.main()
