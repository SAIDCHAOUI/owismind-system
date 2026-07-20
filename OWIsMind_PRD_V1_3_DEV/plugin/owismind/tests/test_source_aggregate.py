# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_source_aggregate.py
"""Source Data Explorer safe aggregation: type classifiers + the service pipeline.

Two layers are exercised here:
  - ``sql_config.is_numeric_type`` / ``is_temporal_type`` (pure schema-type gates), and
  - ``source_service.source_aggregate`` with the dataiku-bound seams stubbed
    (``_resolve_source`` + ``_run_source_query`` monkeypatched), so the SQL fragments,
    the type gating, the truncation flag, and the two-query totals contract are provable
    without a DSS instance (project TEST-01 idiom).

The request validator lives in test_source_validation.py; the pure SQL builder in
test_evidence_query_builders.py. This file is the service + classifier layer.
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
    """Minimal import-time stubs (NO install - the README's "(or a stub)" idiom).

    source_service imports evidence.service (and, transitively, dataiku / SQLExecutor2 /
    dataiku.sql / pandas) at module load. The functions under test never touch them (the
    executing seams are monkeypatched), so bare stubs suffice - and existing stubs from
    sibling test files are EXTENDED, never replaced (unittest discover shares sys.modules).
    ``toSQL`` mirrors the sibling proof file: a value renders as its ``repr`` so quoted
    SQL fragments stay readable in assertions.
    """
    dk = sys.modules.get("dataiku")
    if dk is None:
        dk = types.ModuleType("dataiku")
        sys.modules["dataiku"] = dk
    if not hasattr(dk, "SQLExecutor2"):
        dk.SQLExecutor2 = type("SQLExecutor2", (), {})
    if not hasattr(dk, "Dataset"):
        dk.Dataset = type("Dataset", (), {})
    sql_mod = sys.modules.get("dataiku.sql")
    if sql_mod is None:
        sql_mod = types.ModuleType("dataiku.sql")
        sys.modules["dataiku.sql"] = sql_mod
    if not hasattr(sql_mod, "Constant"):
        sql_mod.Constant = lambda value: value
    if not hasattr(sql_mod, "toSQL"):
        sql_mod.toSQL = lambda constant, dialect=None: repr(constant)
    if not hasattr(sql_mod, "Dialects"):
        sql_mod.Dialects = type("Dialects", (), {"POSTGRES": "postgres"})
    dk.sql = sql_mod
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.ModuleType("pandas")


_ensure_dataiku_stub()

from owismind.evidence import source_service  # noqa: E402
from owismind.evidence.service import EvidenceError  # noqa: E402
from owismind.storage.sql_config import is_numeric_type, is_temporal_type  # noqa: E402


class TypeClassifierTests(unittest.TestCase):
    def test_numeric_accepts_dataiku_and_pg_names(self):
        for t in ("bigint", "int", "double", "float", "decimal", "smallint", "tinyint",
                  "integer", "int8", "numeric", "real", "double precision", "money",
                  "BigInt", "  DOUBLE  "):
            self.assertTrue(is_numeric_type(t), t)

    def test_numeric_rejects_non_numbers(self):
        for t in ("string", "date", "boolean", "timestamp", "text", "varchar",
                  "", None, 5, "time"):
            self.assertFalse(is_numeric_type(t), t)

    def test_temporal_accepts_date_and_timestamps(self):
        for t in ("date", "datetime", "timestamp", "timestamptz",
                  "timestamp with time zone", "timestamp without time zone",
                  "DATE", "  Timestamp  "):
            self.assertTrue(is_temporal_type(t), t)

    def test_temporal_rejects_non_temporal(self):
        # Bare "time" / "interval" are excluded (calendar bucketing is undefined there),
        # as are numbers, strings, empty and None.
        for t in ("time", "timetz", "interval", "string", "bigint", "double",
                  "boolean", "", None, 5):
            self.assertFalse(is_temporal_type(t), t)


def _ctx(columns):
    """A resolved-source context stub: label/dataset/table_ref + columns + colmap."""
    colmap = {}
    for c in columns:
        colmap[c["name"].lower()] = c["name"]
    return {
        "label": "L", "dataset": "DS", "table_ref": 'public."T"',
        "columns": columns, "colmap": colmap,
    }


class _Recorder:
    """Stands in for ``_run_source_query``: records each query, returns canned rows."""

    def __init__(self, *returns):
        self.queries = []
        self._returns = list(returns)

    def __call__(self, ctx, query, op_name):
        self.queries.append(query)
        return self._returns.pop(0) if self._returns else []


class AggregateServiceTests(unittest.TestCase):
    def setUp(self):
        self._orig_resolve = source_service._resolve_source
        self._orig_run = source_service._run_source_query

    def tearDown(self):
        source_service._resolve_source = self._orig_resolve
        source_service._run_source_query = self._orig_run

    def _patch(self, columns, recorder):
        source_service._resolve_source = lambda ak, sid: _ctx(columns)
        source_service._run_source_query = recorder

    _COLS = [
        {"name": "country", "type": "string"},
        {"name": "amount", "type": "double"},
        {"name": "created", "type": "date"},
    ]

    def test_ungrouped_single_query_no_totals(self):
        rec = _Recorder([{"m0": 5, "m1": 99.0}])
        self._patch(self._COLS, rec)
        out = source_service.source_aggregate(
            "ag_x", 0, "", [],
            group=None,
            measures=[{"fn": "count", "column": None},
                      {"fn": "sum", "column": "amount"}],
            limit=50,
        )
        # Exactly ONE query (no totals query when ungrouped), LIMIT 1, no GROUP BY/ORDER BY.
        self.assertEqual(len(rec.queries), 1)
        q = rec.queries[0]
        self.assertIn("COUNT(*) AS m0", q)
        self.assertIn('SUM("amount") AS m1', q)
        self.assertNotIn("GROUP BY", q)
        self.assertNotIn("ORDER BY", q)
        self.assertIn("LIMIT 1", q)
        self.assertEqual(out, {"rows": [{"m0": 5, "m1": 99.0}], "totals": None,
                               "truncated": False})

    def test_grouped_two_queries_ordered_by_measure(self):
        # 3 rows returned but limit 2 -> truncated, rows capped to 2. Group query first,
        # totals query second.
        rec = _Recorder(
            [{"key": "FR", "m0": 3}, {"key": "DE", "m0": 2}, {"key": "IT", "m0": 1}],
            [{"m0": 6}],
        )
        self._patch(self._COLS, rec)
        out = source_service.source_aggregate(
            "ag_x", 0, "", [],
            group={"column": "country", "bucket": None},
            measures=[{"fn": "count", "column": None}],
            limit=2,
        )
        self.assertEqual(len(rec.queries), 2)
        group_q, totals_q = rec.queries
        self.assertIn('"country" AS key', group_q)
        self.assertIn('GROUP BY "country"', group_q)
        self.assertIn("ORDER BY m0 DESC NULLS LAST", group_q)   # ranked by the first measure
        self.assertIn("LIMIT 3", group_q)            # limit + 1 for truncation detection
        # Totals query: same measures, no GROUP BY, LIMIT 1.
        self.assertNotIn("GROUP BY", totals_q)
        self.assertIn("LIMIT 1", totals_q)
        self.assertEqual(out["rows"], [{"key": "FR", "m0": 3}, {"key": "DE", "m0": 2}])
        self.assertEqual(out["totals"], {"m0": 6})
        self.assertTrue(out["truncated"])

    def test_not_truncated_when_within_cap(self):
        rec = _Recorder([{"key": "FR", "m0": 3}], [{"m0": 3}])
        self._patch(self._COLS, rec)
        out = source_service.source_aggregate(
            "ag_x", 0, "", [], group={"column": "country", "bucket": None},
            measures=[{"fn": "count", "column": None}], limit=50)
        self.assertFalse(out["truncated"])
        self.assertEqual(out["rows"], [{"key": "FR", "m0": 3}])

    def test_bucketed_group_uses_date_trunc_and_key_asc(self):
        rec = _Recorder([{"key": "2025-01-01", "m0": 10}], [{"m0": 10}])
        self._patch(self._COLS, rec)
        source_service.source_aggregate(
            "ag_x", 0, "", [], group={"column": "created", "bucket": "month"},
            measures=[{"fn": "count", "column": None}], limit=50)
        group_q = rec.queries[0]
        self.assertIn('DATE_TRUNC(\'month\', "created") AS key', group_q)
        self.assertIn('GROUP BY DATE_TRUNC(\'month\', "created")', group_q)
        self.assertIn("ORDER BY key DESC NULLS LAST", group_q)   # newest buckets kept under the cap

    def test_measure_expressions_per_function(self):
        rec = _Recorder([{"m0": 1, "m1": 1, "m2": 1, "m3": 1, "m4": 1}])
        self._patch(self._COLS, rec)
        source_service.source_aggregate(
            "ag_x", 0, "", [], group=None,
            measures=[{"fn": "count_distinct", "column": "country"},
                      {"fn": "sum", "column": "amount"},
                      {"fn": "avg", "column": "amount"},
                      {"fn": "min", "column": "amount"},
                      {"fn": "max", "column": "amount"}],
            limit=50)
        q = rec.queries[0]
        self.assertIn('COUNT(DISTINCT "country") AS m0', q)
        self.assertIn('SUM("amount") AS m1', q)
        self.assertIn('AVG("amount") AS m2', q)
        self.assertIn('MIN("amount") AS m3', q)
        self.assertIn('MAX("amount") AS m4', q)

    def test_sum_on_non_numeric_rejected(self):
        rec = _Recorder()
        self._patch(self._COLS, rec)
        with self.assertRaises(EvidenceError) as ctx:
            source_service.source_aggregate(
                "ag_x", 0, "", [], group=None,
                measures=[{"fn": "sum", "column": "country"}], limit=50)
        self.assertEqual(ctx.exception.code, "invalid_aggregate_column")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(rec.queries, [])   # rejected before any query is issued

    def test_min_max_count_distinct_accept_non_numeric(self):
        rec = _Recorder([{"m0": 1, "m1": 1, "m2": 1}])
        self._patch(self._COLS, rec)
        source_service.source_aggregate(
            "ag_x", 0, "", [], group=None,
            measures=[{"fn": "min", "column": "country"},
                      {"fn": "max", "column": "country"},
                      {"fn": "count_distinct", "column": "country"}],
            limit=50)
        self.assertEqual(len(rec.queries), 1)

    def test_unknown_measure_column_rejected(self):
        rec = _Recorder()
        self._patch(self._COLS, rec)
        with self.assertRaises(EvidenceError) as ctx:
            source_service.source_aggregate(
                "ag_x", 0, "", [], group=None,
                measures=[{"fn": "sum", "column": "nope"}], limit=50)
        self.assertEqual(ctx.exception.code, "invalid_aggregate_column")

    def test_bucket_on_non_temporal_rejected(self):
        rec = _Recorder()
        self._patch(self._COLS, rec)
        with self.assertRaises(EvidenceError) as ctx:
            source_service.source_aggregate(
                "ag_x", 0, "", [], group={"column": "country", "bucket": "month"},
                measures=[{"fn": "count", "column": None}], limit=50)
        self.assertEqual(ctx.exception.code, "invalid_group_bucket")
        self.assertEqual(ctx.exception.status, 400)

    def test_unknown_group_column_rejected(self):
        rec = _Recorder()
        self._patch(self._COLS, rec)
        with self.assertRaises(EvidenceError) as ctx:
            source_service.source_aggregate(
                "ag_x", 0, "", [], group={"column": "nope", "bucket": None},
                measures=[{"fn": "count", "column": None}], limit=50)
        self.assertEqual(ctx.exception.code, "invalid_filter_column")

    def test_filters_and_search_applied_to_both_queries(self):
        rec = _Recorder([{"key": "FR", "m0": 1}], [{"m0": 1}])
        self._patch(self._COLS, rec)
        source_service.source_aggregate(
            "ag_x", 0, "alg",
            [{"column": "country", "op": "=", "values": ["FR"]}],
            group={"column": "country", "bucket": None},
            measures=[{"fn": "count", "column": None}], limit=50)
        # Both the group query AND the totals query carry the same WHERE (filter + the
        # accent-folded ILIKE search over all columns) - the totals must match the groups.
        for q in rec.queries:
            self.assertIn('"country" = ', q)
            self.assertIn("ILIKE", q)
            self.assertIn("concat_ws", q)

    def test_median_measure_expression(self):
        # median renders the ordered-set aggregate PERCENTILE_CONT(0.5) over a numeric column.
        rec = _Recorder([{"m0": 42.0}])
        self._patch(self._COLS, rec)
        source_service.source_aggregate(
            "ag_x", 0, "", [], group=None,
            measures=[{"fn": "median", "column": "amount"}], limit=50)
        self.assertIn(
            'PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "amount") AS m0',
            rec.queries[0])

    def test_median_on_non_numeric_rejected(self):
        # median obeys the same numeric gate as sum/avg (rejected before any query).
        rec = _Recorder()
        self._patch(self._COLS, rec)
        with self.assertRaises(EvidenceError) as ctx:
            source_service.source_aggregate(
                "ag_x", 0, "", [], group=None,
                measures=[{"fn": "median", "column": "country"}], limit=50)
        self.assertEqual(ctx.exception.code, "invalid_aggregate_column")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(rec.queries, [])

    def test_between_filter_reaches_grouped_and_totals_queries(self):
        # A BETWEEN date-range chip is rendered as-is and applied to BOTH bounded queries.
        rec = _Recorder([{"key": "FR", "m0": 1}], [{"m0": 1}])
        self._patch(self._COLS, rec)
        source_service.source_aggregate(
            "ag_x", 0, "",
            [{"column": "created", "op": "BETWEEN",
              "values": ["2025-01-01", "2025-12-31"]}],
            group={"column": "country", "bucket": None},
            measures=[{"fn": "count", "column": None}], limit=50)
        self.assertEqual(len(rec.queries), 2)
        for q in rec.queries:
            self.assertIn('"created" BETWEEN', q)
            self.assertIn("2025-01-01", q)
            self.assertIn("2025-12-31", q)

    def test_between_filter_reaches_rows_query(self):
        # The SAME _source_conditions renders BETWEEN for the row window too.
        rec = _Recorder([{"country": "FR"}])
        self._patch(self._COLS, rec)
        source_service.source_rows(
            "ag_x", 0, "",
            [{"column": "created", "op": "BETWEEN",
              "values": ["2025-01-01", "2025-12-31"]}],
            limit=50, offset=0, sort=None)
        self.assertEqual(len(rec.queries), 1)
        q = rec.queries[0]
        self.assertIn('"created" BETWEEN', q)
        self.assertIn("2025-01-01", q)
        self.assertIn("2025-12-31", q)


if __name__ == "__main__":
    unittest.main()
