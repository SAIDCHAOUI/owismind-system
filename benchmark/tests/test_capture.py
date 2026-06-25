"""Tests for benchmark.agent_capture (footer -> complete answer).

Proves: extract_generated_sql returns the expected items with capped results;
extract_usage sums correctly; flatten_result_cells returns the cell strings;
assemble_full_answer includes the text AND the serialized result rows (the key
fix - the answer is not text-only). Stdlib only, no DSS.
"""

import unittest

from benchmark import agent_capture as cap
from benchmark.tests.fixtures import footer_traces as fx


class TestExtractGeneratedSql(unittest.TestCase):
    def test_two_sql_items_found(self):
        items = cap.extract_generated_sql(fx.TWO_SQL_INNER_TRACE)
        self.assertEqual(len(items), 2)
        # Item shape contract.
        for it in items:
            self.assertEqual(set(it.keys()), {"sql", "success", "row_count", "result"})
            self.assertIsInstance(it["sql"], str)
            self.assertIsInstance(it["success"], bool)
            self.assertIsInstance(it["row_count"], int)

    def test_first_item_list_of_lists_with_columns(self):
        items = cap.extract_generated_sql(fx.TWO_SQL_INNER_TRACE)
        first = items[0]
        self.assertTrue(first["success"])
        self.assertEqual(first["row_count"], 2)
        self.assertIn("GROUP BY account_name", first["sql"])
        self.assertEqual(first["result"]["columns"], ["account_name", "revenue"])
        self.assertEqual(first["result"]["rows"][0], ["Maroc Telecom", 1234567.89])
        self.assertEqual(first["result"]["rows"][1], ["Airbus", 987654.0])

    def test_second_item_list_of_dicts_columns_from_keys(self):
        items = cap.extract_generated_sql(fx.TWO_SQL_INNER_TRACE)
        second = items[1]
        self.assertEqual(second["row_count"], 3)
        self.assertEqual(second["result"]["columns"], ["phase", "total"])
        self.assertEqual(second["result"]["rows"][0], ["ACTUALS", 5000000])
        self.assertEqual(len(second["result"]["rows"]), 3)

    def test_non_sql_span_is_ignored(self):
        # The attribute_lookup span must not appear as a SQL item.
        items = cap.extract_generated_sql(fx.TWO_SQL_INNER_TRACE)
        self.assertEqual(len(items), 2)

    def test_no_sql_returns_empty(self):
        self.assertEqual(cap.extract_generated_sql(fx.NO_SQL_TRACE), [])

    def test_result_caps_applied(self):
        items = cap.extract_generated_sql(fx.BIG_RESULT_TRACE)
        self.assertEqual(len(items), 1)
        result = items[0]["result"]
        self.assertEqual(len(result["columns"]), cap.MAX_RESULT_COLS)
        self.assertLessEqual(len(result["rows"]), cap.MAX_RESULT_ROWS)
        # Every kept row is conformed to the capped column count.
        for row in result["rows"]:
            self.assertEqual(len(row), cap.MAX_RESULT_COLS)

    def test_malformed_trace_is_safe(self):
        self.assertEqual(cap.extract_generated_sql(None), [])
        self.assertEqual(cap.extract_generated_sql("not a trace"), [])
        self.assertEqual(cap.extract_generated_sql([]), [])

    def test_newest_wins_cap(self):
        # Build a trace with MAX_SQL_ITEMS + 5 spans; only the newest cap survive.
        n = cap.MAX_SQL_ITEMS + 5
        spans = [
            fx.make_sql_span("semantic-model-query",
                             "SELECT {0}".format(i), True, i)
            for i in range(n)
        ]
        trace = {"root": {"children": spans}}
        items = cap.extract_generated_sql(trace)
        self.assertEqual(len(items), cap.MAX_SQL_ITEMS)
        # Newest wins: the last span (row_count n-1) must be kept.
        self.assertEqual(items[-1]["row_count"], n - 1)


class TestExtractUsage(unittest.TestCase):
    def test_sum_over_nested_usages(self):
        usage = cap.extract_usage(fx.TWO_SQL_INNER_TRACE)
        # 1200+800, 300+150, 1500+950, 0.012+0.009
        self.assertEqual(usage["promptTokens"], 2000)
        self.assertEqual(usage["completionTokens"], 450)
        self.assertEqual(usage["totalTokens"], 2450)
        self.assertAlmostEqual(usage["estimatedCost"], 0.021, places=6)

    def test_multi_usage_summation(self):
        usage = cap.extract_usage(fx.MULTI_USAGE_TRACE)
        self.assertEqual(usage["promptTokens"], 33)   # 10 + 20 + 3
        self.assertEqual(usage["completionTokens"], 13)  # 5 + 7 + 1
        self.assertEqual(usage["totalTokens"], 46)    # 15 + 27 + 4
        self.assertAlmostEqual(usage["estimatedCost"], 0.0035, places=6)

    def test_usage_shape_and_empty(self):
        usage = cap.extract_usage(None)
        self.assertEqual(
            set(usage.keys()),
            {"promptTokens", "completionTokens", "totalTokens", "estimatedCost"},
        )
        self.assertEqual(usage["totalTokens"], 0)
        self.assertEqual(usage["estimatedCost"], 0.0)


class TestExtractArtifacts(unittest.TestCase):
    def test_normalized_and_raw_artifacts(self):
        arts = cap.extract_artifacts(fx.ARTIFACT_EVENTS)
        self.assertEqual(len(arts), 2)
        kinds = sorted(a["kind"] for a in arts)
        self.assertEqual(kinds, ["chart", "kpi"])

    def test_empty_when_no_artifacts(self):
        self.assertEqual(cap.extract_artifacts([{"type": "answer_delta", "text": "x"}]), [])
        self.assertEqual(cap.extract_artifacts(None), [])


class TestFlattenResultCells(unittest.TestCase):
    def test_returns_all_cells_stringified(self):
        items = cap.extract_generated_sql(fx.TWO_SQL_INNER_TRACE)
        cells = cap.flatten_result_cells(items)
        # 2 rows x 2 cols + 3 rows x 2 cols = 10 cells.
        self.assertEqual(len(cells), 10)
        self.assertTrue(all(isinstance(c, str) for c in cells))
        self.assertIn("1234567.89", cells)
        self.assertIn("Maroc Telecom", cells)
        self.assertIn("ACTUALS", cells)

    def test_safe_on_garbage(self):
        self.assertEqual(cap.flatten_result_cells(None), [])
        self.assertEqual(cap.flatten_result_cells([{"result": None}]), [])


class TestAssembleFullAnswer(unittest.TestCase):
    def test_includes_text_and_serialized_rows(self):
        items = cap.extract_generated_sql(fx.TWO_SQL_INNER_TRACE)
        arts = cap.extract_artifacts(fx.ARTIFACT_EVENTS)
        text = "The top account is Maroc Telecom."
        full = cap.assemble_full_answer(text, items, arts)
        # The final text is present.
        self.assertIn("The top account is Maroc Telecom.", full)
        # The serialized result rows are present (the key fix).
        self.assertIn("1234567.89", full)
        self.assertIn("Maroc Telecom", full)
        self.assertIn("account_name", full)  # header
        self.assertIn("ACTUALS", full)
        # The artifacts summary is present.
        self.assertIn("chart", full)

    def test_text_only_when_no_sql(self):
        full = cap.assemble_full_answer("Just text.", [], [])
        self.assertEqual(full, "Just text.")

    def test_data_present_even_when_text_empty(self):
        # The answer can live entirely in the table: full_answer must still carry it.
        items = cap.extract_generated_sql(fx.TWO_SQL_INNER_TRACE)
        full = cap.assemble_full_answer("", items, [])
        self.assertIn("1234567.89", full)
        self.assertIn("Data results", full)

    def test_never_raises_on_bad_input(self):
        self.assertEqual(cap.assemble_full_answer(None, None, None), "")


if __name__ == "__main__":
    unittest.main()
