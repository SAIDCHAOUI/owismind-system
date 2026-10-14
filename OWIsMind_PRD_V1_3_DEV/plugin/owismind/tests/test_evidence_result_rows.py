# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_evidence_result_rows.py
"""Full-result paging (/evidence/result-rows): the pure pieces, DSS-free.

The agents keep only a short excerpt of each SQL result; the Evidence tables page
through the FULL result by re-running the agent's OWN stored SELECT. What makes
that safe is proven here: the re-run gate (sql_parse.check_rerunnable_select), the
wrapping builders, the payload validator, the item picker and the positional,
JSON-safe row conversion.
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
sys.path.insert(0, _HERE)

import _dss_stub  # noqa: E402

_dss_stub.install()

from owismind.evidence.query_builders import (  # noqa: E402
    build_result_count_query,
    build_result_page_query,
)
from owismind.evidence.service import pick_result_item  # noqa: E402
from owismind.evidence.sql_parse import check_rerunnable_select, cte_names, tokenize  # noqa: E402
from owismind.security.validation import (  # noqa: E402
    MAX_ROWS_LIMIT,
    MAX_ROWS_OFFSET,
    ValidationError,
    validate_evidence_result_rows_request,
)


class RerunGateTests(unittest.TestCase):
    def test_plain_aggregate_select_passes_and_strips_semicolon(self):
        g = check_rerunnable_select(
            'SELECT "Account_name", SUM("Revenue") AS rev FROM "public"."P_drive" '
            "WHERE \"Phase\" = 'ACTUALS' GROUP BY 1 ORDER BY rev DESC;")
        self.assertTrue(g["ok"])
        self.assertFalse(g["sql"].endswith(";"))
        self.assertEqual(g["tables"], [{"schema": "public", "table": "P_drive"}])

    def test_cte_names_are_not_source_tables(self):
        g = check_rerunnable_select(
            "WITH base AS (SELECT a, b FROM t1 WHERE a = 1), "
            "agg (k) AS MATERIALIZED (SELECT a FROM base) "
            "SELECT * FROM agg JOIN base ON agg.k = base.a")
        self.assertTrue(g["ok"])
        self.assertEqual([t["table"] for t in g["tables"]], ["t1"])

    def test_cte_names_helper(self):
        toks, _ = tokenize('WITH RECURSIVE x AS (SELECT 1), "Y" AS NOT MATERIALIZED (SELECT 2) SELECT 1')
        self.assertEqual(cte_names(toks), {"x", "y"})

    def test_rejects_writes_and_side_effects(self):
        for sql in (
            "SELECT * INTO new_t FROM t",
            "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d",
            "SELECT pg_sleep(100) FROM t",
            'SELECT "pg_read_file"(\'x\') FROM t',
            "SELECT lo_export(1, '/tmp/x') FROM t",
            "SELECT set_config('a', 'b', false) FROM t",
            "SELECT * FROM t FOR UPDATE; SELECT 1",
            "SELECT a FROM t UNION SELECT a FROM secret",
            "UPDATE t SET a = 1",
            "SELECT 'a\\b' FROM t",
            "SELECT 1 -- comment",
        ):
            self.assertFalse(check_rerunnable_select(sql)["ok"], sql)

    def test_rejects_non_select_and_garbage(self):
        for sql in (None, "", "   ", "EXPLAIN SELECT 1", "SELECT (1", "SELECT 1"):
            self.assertFalse(check_rerunnable_select(sql)["ok"], repr(sql))

    def test_string_literal_with_banned_word_passes(self):
        g = check_rerunnable_select("SELECT a FROM t WHERE status = 'delete'")
        self.assertTrue(g["ok"])


class BuilderTests(unittest.TestCase):
    def test_page_query_wraps_and_bounds(self):
        q = build_result_page_query("SELECT a FROM t ORDER BY a", 101, 40)
        self.assertTrue(q.startswith("SELECT * FROM ("))
        self.assertIn("SELECT a FROM t ORDER BY a", q)
        self.assertTrue(q.endswith("AS owi_result LIMIT 101 OFFSET 40"))

    def test_count_query_wraps(self):
        q = build_result_count_query("SELECT a FROM t")
        self.assertTrue(q.startswith("SELECT COUNT(*) AS n FROM ("))
        self.assertTrue(q.endswith(") AS owi_result"))

    def test_bounds_are_coerced_to_int(self):
        with self.assertRaises(ValueError):
            build_result_page_query("SELECT 1 FROM t", "1; DROP", 0)


class ValidationTests(unittest.TestCase):
    def test_defaults_and_clamps(self):
        ex, sid, limit, offset = validate_evidence_result_rows_request(
            {"exchange_id": "e1", "limit": 10_000, "offset": 99_999})
        self.assertEqual((ex, sid), ("e1", None))
        self.assertEqual(limit, MAX_ROWS_LIMIT)
        self.assertEqual(offset, MAX_ROWS_OFFSET)

    def test_sql_id_shape(self):
        self.assertEqual(validate_evidence_result_rows_request(
            {"exchange_id": "e1", "sql_id": "s-2"})[1], "s-2")
        for bad in ("", 3, "x" * 301, ["a"]):
            with self.assertRaises(ValidationError):
                validate_evidence_result_rows_request({"exchange_id": "e1", "sql_id": bad})

    def test_exchange_required(self):
        with self.assertRaises(ValidationError):
            validate_evidence_result_rows_request({})
        with self.assertRaises(ValidationError):
            validate_evidence_result_rows_request(None)


class PickItemTests(unittest.TestCase):
    ITEMS = [{"sql": "a", "sql_id": "s1"}, {"sql": "b", "sql_id": "s2"},
             {"sql": "c", "sql_id": "dup"}, {"sql": "d", "sql_id": "dup"}]

    def test_active_item_without_sql_id(self):
        self.assertIs(pick_result_item(self.ITEMS, self.ITEMS[1], None), self.ITEMS[1])

    def test_unique_sql_id(self):
        self.assertIs(pick_result_item(self.ITEMS, self.ITEMS[1], "s1"), self.ITEMS[0])

    def test_missing_or_ambiguous_sql_id_is_none(self):
        self.assertIsNone(pick_result_item(self.ITEMS, self.ITEMS[1], "nope"))
        self.assertIsNone(pick_result_item(self.ITEMS, self.ITEMS[1], "dup"))


class MatrixTests(unittest.TestCase):
    def setUp(self):
        import pandas
        if not hasattr(pandas, "DataFrame"):  # the DSS stub, not real pandas
            self.skipTest("pandas not available")

    def test_positional_rows_keep_duplicate_names_and_null_safety(self):
        import pandas as pd
        from owismind.storage.serialization import frame_to_json_safe_matrix
        df = pd.DataFrame([[1, float("nan"), pd.Timestamp("2026-01-02"), "x" * 400]],
                          columns=["a", "a", "d", "s"])
        cols, rows = frame_to_json_safe_matrix(df, 256)
        self.assertEqual(cols, ["a", "a", "d", "s"])
        self.assertEqual(rows[0][0], 1)
        self.assertIsInstance(rows[0][0], int)
        self.assertIsNone(rows[0][1])
        self.assertTrue(rows[0][2].startswith("2026-01-02"))
        self.assertEqual(len(rows[0][3]), 256)


if __name__ == "__main__":
    unittest.main()
