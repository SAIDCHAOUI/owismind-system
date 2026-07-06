# Plugin/owismind/tests/test_evidence_aggregate.py
"""Evidence exact-totals path: the SHARED aggregate core + the /evidence/aggregate
service + its validator, plus a regression lock on /evidence/rows for =/IN filters.

Three layers are exercised here, all DSS-free (project TEST-01 idiom):
  - ``aggregate_core.build_aggregate_plan`` direct (type gates + plan shapes), the
    single engine both /source/aggregate and /evidence/aggregate consume;
  - ``service.evidence_aggregate`` with the dataiku-bound seams stubbed
    (``_context`` + ``_run_evidence_query`` monkeypatched), proving locked chips,
    a BETWEEN filter and a drill all reach BOTH bounded queries, the ORDER / cap
    rules, and the totals-only-when-grouped contract; and
  - ``validate_evidence_aggregate_request`` (shape / whitelist / stable codes) with a
    regression that /evidence/rows still renders =/IN filters byte-identically.

The source-explorer twin lives in test_source_aggregate.py; the pure SQL builder in
test_evidence_query_builders.py.
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
    """Minimal import-time stubs (NO install - the README's "(or a stub)" idiom).

    service.py imports dataiku / SQLExecutor2 / dataiku.sql / pandas at module load, and
    aggregate_core imports EvidenceError from service. The functions under test never
    touch the executing seams (monkeypatched), so bare stubs suffice - and existing stubs
    from sibling test files are EXTENDED, never replaced (unittest discover shares one
    sys.modules). ``toSQL`` mirrors the sibling proof files: a value renders as its
    ``repr`` so quoted SQL fragments stay readable in assertions.
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

from owismind.evidence import service  # noqa: E402
from owismind.evidence.aggregate_core import build_aggregate_plan  # noqa: E402
from owismind.evidence.service import EvidenceError  # noqa: E402
from owismind.security.validation import (  # noqa: E402
    MAX_AGG_GROUP_ROWS,
    ValidationError,
    validate_evidence_aggregate_request,
    validate_evidence_rows_request,
)


_COLS = [
    {"name": "country", "type": "string"},
    {"name": "amount", "type": "double"},
    {"name": "created", "type": "date"},
]


def _colmap(columns):
    return {c["name"].lower(): c["name"] for c in columns}


# --- 1. Shared aggregate core (build_aggregate_plan): gates + plan shapes ----------


class BuildAggregatePlanTests(unittest.TestCase):
    def _plan(self, group, measures, columns=None):
        columns = columns or _COLS
        return build_aggregate_plan(columns, _colmap(columns), group, measures)

    def test_ungrouped_plan_shape(self):
        plan = self._plan(None, [{"fn": "count", "column": None},
                                 {"fn": "sum", "column": "amount"}])
        self.assertEqual(plan["measure_exprs"], ["COUNT(*) AS m0", 'SUM("amount") AS m1'])
        # Ungrouped: select == measures, no GROUP BY, no ORDER BY.
        self.assertEqual(plan["select_exprs"], plan["measure_exprs"])
        self.assertEqual(plan["group_exprs"], [])
        self.assertIsNone(plan["order_expr"])
        self.assertIsNone(plan["order_dir"])

    def test_grouped_plan_ranks_by_first_measure(self):
        plan = self._plan({"column": "country", "bucket": None},
                          [{"fn": "count", "column": None}])
        self.assertEqual(plan["select_exprs"], ['"country" AS key', "COUNT(*) AS m0"])
        self.assertEqual(plan["group_exprs"], ['"country"'])
        self.assertEqual((plan["order_expr"], plan["order_dir"]), ("m0", "desc"))

    def test_bucketed_plan_is_date_trunc_key_desc(self):
        plan = self._plan({"column": "created", "bucket": "month"},
                          [{"fn": "count", "column": None}])
        self.assertEqual(plan["select_exprs"][0], 'DATE_TRUNC(\'month\', "created") AS key')
        self.assertEqual(plan["group_exprs"], ['DATE_TRUNC(\'month\', "created")'])
        self.assertEqual((plan["order_expr"], plan["order_dir"]), ("key", "desc"))

    def test_measure_expressions_per_function(self):
        plan = self._plan(None, [{"fn": "count_distinct", "column": "country"},
                                 {"fn": "sum", "column": "amount"},
                                 {"fn": "avg", "column": "amount"},
                                 {"fn": "median", "column": "amount"},
                                 {"fn": "min", "column": "amount"},
                                 {"fn": "max", "column": "amount"}])
        self.assertEqual(plan["measure_exprs"], [
            'COUNT(DISTINCT "country") AS m0',
            'SUM("amount") AS m1',
            'AVG("amount") AS m2',
            'PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "amount") AS m3',
            'MIN("amount") AS m4',
            'MAX("amount") AS m5',
        ])

    def test_sum_avg_median_on_non_numeric_rejected(self):
        for fn in ("sum", "avg", "median"):
            with self.assertRaises(EvidenceError) as ctx:
                self._plan(None, [{"fn": fn, "column": "country"}])
            self.assertEqual(ctx.exception.code, "invalid_aggregate_column")
            self.assertEqual(ctx.exception.status, 400)

    def test_min_max_count_distinct_accept_non_numeric(self):
        plan = self._plan(None, [{"fn": "min", "column": "country"},
                                 {"fn": "max", "column": "country"},
                                 {"fn": "count_distinct", "column": "country"}])
        self.assertEqual(len(plan["measure_exprs"]), 3)

    def test_unknown_measure_column_rejected(self):
        with self.assertRaises(EvidenceError) as ctx:
            self._plan(None, [{"fn": "sum", "column": "nope"}])
        self.assertEqual(ctx.exception.code, "invalid_aggregate_column")

    def test_unknown_group_column_rejected(self):
        with self.assertRaises(EvidenceError) as ctx:
            self._plan({"column": "nope", "bucket": None},
                       [{"fn": "count", "column": None}])
        self.assertEqual(ctx.exception.code, "invalid_filter_column")

    def test_bucket_on_non_temporal_rejected(self):
        with self.assertRaises(EvidenceError) as ctx:
            self._plan({"column": "country", "bucket": "month"},
                       [{"fn": "count", "column": None}])
        self.assertEqual(ctx.exception.code, "invalid_group_bucket")
        self.assertEqual(ctx.exception.status, 400)

    def test_measures_gated_before_group(self):
        # A bad measure is caught before the group column is even looked at.
        with self.assertRaises(EvidenceError) as ctx:
            self._plan({"column": "nope", "bucket": None},
                       [{"fn": "sum", "column": "country"}])
        self.assertEqual(ctx.exception.code, "invalid_aggregate_column")


# --- 2. service.evidence_aggregate: conditions reach both queries, order, totals ---


class _Recorder:
    """Stands in for ``_run_evidence_query``: records each query, returns canned rows."""

    def __init__(self, *returns):
        self.queries = []
        self._returns = list(returns)

    def __call__(self, ctx, query, op_name):
        self.queries.append(query)
        return self._returns.pop(0) if self._returns else []


def _ctx(columns, predicates=None, advanced=None):
    """An evidence context stub: dataset/table_ref + columns/colmap + predicates."""
    return {
        "dataset": "DS", "table_ref": 'public."T"',
        "columns": columns, "colmap": _colmap(columns),
        "predicates": predicates or [], "advanced": advanced,
        "sql": "SELECT * FROM t",
    }


class EvidenceAggregateServiceTests(unittest.TestCase):
    def setUp(self):
        self._orig_context = service._context
        self._orig_run = service._run_evidence_query
        self._orig_drill = service._drill_conditions

    def tearDown(self):
        service._context = self._orig_context
        service._run_evidence_query = self._orig_run
        service._drill_conditions = self._orig_drill

    def _patch(self, ctx, recorder):
        service._context = lambda uid, eid, preferred_table=None: ctx
        service._run_evidence_query = recorder

    def test_ungrouped_single_query_no_totals(self):
        rec = _Recorder([{"m0": 5, "m1": 99.0}])
        self._patch(_ctx(_COLS), rec)
        out = service.evidence_aggregate(
            "u", "ex", [], [], False, "", group=None,
            measures=[{"fn": "count", "column": None},
                      {"fn": "sum", "column": "amount"}], limit=50)
        self.assertEqual(len(rec.queries), 1)   # no totals query when ungrouped
        q = rec.queries[0]
        self.assertIn("COUNT(*) AS m0", q)
        self.assertIn('SUM("amount") AS m1', q)
        self.assertNotIn("GROUP BY", q)
        self.assertNotIn("ORDER BY", q)
        self.assertIn("LIMIT 1", q)
        self.assertEqual(out, {"rows": [{"m0": 5, "m1": 99.0}], "totals": None,
                               "truncated": False})

    def test_grouped_two_queries_ordered_by_measure_truncation(self):
        rec = _Recorder(
            [{"key": "FR", "m0": 3}, {"key": "DE", "m0": 2}, {"key": "IT", "m0": 1}],
            [{"m0": 6}],
        )
        self._patch(_ctx(_COLS), rec)
        out = service.evidence_aggregate(
            "u", "ex", [], [], False, "",
            group={"column": "country", "bucket": None},
            measures=[{"fn": "count", "column": None}], limit=2)
        self.assertEqual(len(rec.queries), 2)
        group_q, totals_q = rec.queries
        self.assertIn('"country" AS key', group_q)
        self.assertIn('GROUP BY "country"', group_q)
        self.assertIn("ORDER BY m0 DESC NULLS LAST", group_q)
        self.assertIn("LIMIT 3", group_q)          # limit + 1 for truncation detection
        self.assertNotIn("GROUP BY", totals_q)
        self.assertIn("LIMIT 1", totals_q)
        self.assertEqual(out["rows"], [{"key": "FR", "m0": 3}, {"key": "DE", "m0": 2}])
        self.assertEqual(out["totals"], {"m0": 6})
        self.assertTrue(out["truncated"])

    def test_not_truncated_within_cap(self):
        rec = _Recorder([{"key": "FR", "m0": 3}], [{"m0": 3}])
        self._patch(_ctx(_COLS), rec)
        out = service.evidence_aggregate(
            "u", "ex", [], [], False, "",
            group={"column": "country", "bucket": None},
            measures=[{"fn": "count", "column": None}], limit=50)
        self.assertFalse(out["truncated"])
        self.assertEqual(out["rows"], [{"key": "FR", "m0": 3}])

    def test_bucketed_group_uses_date_trunc_key_desc(self):
        rec = _Recorder([{"key": "2025-01-01", "m0": 10}], [{"m0": 10}])
        self._patch(_ctx(_COLS), rec)
        service.evidence_aggregate(
            "u", "ex", [], [], False, "",
            group={"column": "created", "bucket": "month"},
            measures=[{"fn": "count", "column": None}], limit=50)
        group_q = rec.queries[0]
        self.assertIn('DATE_TRUNC(\'month\', "created") AS key', group_q)
        self.assertIn("ORDER BY key DESC NULLS LAST", group_q)

    def test_locked_chip_and_between_filter_reach_both_queries(self):
        # A locked (non-editable) chip kept by id + a client BETWEEN date-range chip must
        # both scope the grouped AND the totals query, so the totals match the groups.
        locked = {"id": 5, "column": "country", "op": "=", "values": ["FR"],
                  "editable": False}
        rec = _Recorder([{"key": "FR", "m0": 1}], [{"m0": 1}])
        self._patch(_ctx(_COLS, predicates=[locked]), rec)
        service.evidence_aggregate(
            "u", "ex",
            [{"column": "created", "op": "BETWEEN",
              "values": ["2025-01-01", "2025-12-31"]}],
            [5], False, "",
            group={"column": "country", "bucket": None},
            measures=[{"fn": "count", "column": None}], limit=50)
        self.assertEqual(len(rec.queries), 2)
        for q in rec.queries:
            self.assertIn('"country" = ', q)            # the locked chip
            self.assertIn('"created" BETWEEN', q)        # the BETWEEN client filter
            self.assertIn("2025-01-01", q)
            self.assertIn("2025-12-31", q)

    def test_drill_reaches_both_queries(self):
        # Drill conditions (re-derived server-side) scope BOTH bounded queries too. The
        # server-side derivation is proven elsewhere; here we inject a marker condition.
        service._drill_conditions = lambda ctx, drill: ['"country" IS NULL']
        rec = _Recorder([{"key": "FR", "m0": 1}], [{"m0": 1}])
        self._patch(_ctx(_COLS), rec)
        service.evidence_aggregate(
            "u", "ex", [], [], False, "",
            drill=[{"column": "country", "value": None}],
            group={"column": "country", "bucket": None},
            measures=[{"fn": "count", "column": None}], limit=50)
        self.assertEqual(len(rec.queries), 2)
        for q in rec.queries:
            self.assertIn('"country" IS NULL', q)

    def test_free_text_search_reaches_both_queries(self):
        rec = _Recorder([{"key": "FR", "m0": 1}], [{"m0": 1}])
        self._patch(_ctx(_COLS), rec)
        service.evidence_aggregate(
            "u", "ex", [], [], False, "alg",
            group={"column": "country", "bucket": None},
            measures=[{"fn": "count", "column": None}], limit=50)
        for q in rec.queries:
            self.assertIn("ILIKE", q)
            self.assertIn("concat_ws", q)

    def test_advanced_fragment_only_when_included(self):
        rec = _Recorder([{"m0": 1}])
        self._patch(_ctx(_COLS, advanced='"amount" > 0'), rec)
        service.evidence_aggregate(
            "u", "ex", [], [], True, "", group=None,
            measures=[{"fn": "count", "column": None}], limit=50)
        self.assertIn('"amount" > 0', rec.queries[0])

    def test_bad_measure_rejected_before_any_query(self):
        rec = _Recorder()
        self._patch(_ctx(_COLS), rec)
        with self.assertRaises(EvidenceError) as ctx:
            service.evidence_aggregate(
                "u", "ex", [], [], False, "", group=None,
                measures=[{"fn": "sum", "column": "country"}], limit=50)
        self.assertEqual(ctx.exception.code, "invalid_aggregate_column")
        self.assertEqual(rec.queries, [])


# --- 3. validator: shape / whitelist / stable codes, BETWEEN now accepted ----------


def _agg_payload(**over):
    base = {
        "exchange_id": "ex1",
        "filters": [{"column": "region", "op": "=", "values": ["EU"]}],
        "kept_ids": [5],
        "include_advanced": True,
        "q": "  algerie ",
        "drill": [{"column": "phase", "value": None}],
        "table": "DS",
        "group": {"column": "country", "bucket": None},
        "measures": [{"fn": "count", "column": None},
                     {"fn": "sum", "column": "amount"}],
        "limit": 20,
    }
    base.update(over)
    return base


class AggregateValidatorTests(unittest.TestCase):
    def test_happy_path_tuple_order(self):
        (exchange_id, filters, kept_ids, include_advanced, q, drill, table,
         group, measures, limit) = validate_evidence_aggregate_request(_agg_payload())
        self.assertEqual(exchange_id, "ex1")
        self.assertEqual(filters, [{"column": "region", "op": "=", "values": ["EU"]}])
        self.assertEqual(kept_ids, [5])
        self.assertTrue(include_advanced)
        self.assertEqual(q, "algerie")               # cleaned like /source/rows
        self.assertEqual(drill, [{"column": "phase", "value": None}])
        self.assertEqual(table, "DS")
        self.assertEqual(group, {"column": "country", "bucket": None})
        self.assertEqual(measures, [{"fn": "count", "column": None},
                                    {"fn": "sum", "column": "amount"}])
        self.assertEqual(limit, 20)

    def test_defaults(self):
        # Only exchange_id + measures are load-bearing; the rest defaults.
        (exchange_id, filters, kept_ids, include_advanced, q, drill, table,
         group, measures, limit) = validate_evidence_aggregate_request(
            {"exchange_id": "e", "measures": [{"fn": "count", "column": None}]})
        self.assertEqual((filters, kept_ids, include_advanced, q, drill, table, group),
                         ([], [], False, "", [], None, None))
        self.assertEqual(limit, MAX_AGG_GROUP_ROWS)   # clamp default

    def test_between_accepted_on_aggregate(self):
        out = validate_evidence_aggregate_request(_agg_payload(
            filters=[{"column": "created", "op": "BETWEEN",
                      "values": ["2025-01-01", "2025-12-31"]}]))
        self.assertEqual(out[1], [{"column": "created", "op": "BETWEEN",
                                   "values": ["2025-01-01", "2025-12-31"]}])

    def test_between_accepted_on_rows_too(self):
        # The unification: /evidence/rows takes the same date-range chip (filters index 1).
        out = validate_evidence_rows_request({
            "exchange_id": "ex1",
            "filters": [{"column": "created", "op": "BETWEEN",
                         "values": ["2025-01-01", "2025-12-31"]}]})[1]
        self.assertEqual(out, [{"column": "created", "op": "BETWEEN",
                                "values": ["2025-01-01", "2025-12-31"]}])

    def test_limit_clamped_never_raises(self):
        self.assertEqual(validate_evidence_aggregate_request(_agg_payload(limit=9999))[9],
                         MAX_AGG_GROUP_ROWS)
        self.assertEqual(validate_evidence_aggregate_request(_agg_payload(limit=0))[9], 1)
        self.assertEqual(validate_evidence_aggregate_request(_agg_payload(limit="x"))[9],
                         MAX_AGG_GROUP_ROWS)

    def test_stable_codes(self):
        bad = [
            ("nope", "invalid_payload"),
            ({"measures": [{"fn": "count", "column": None}]}, "invalid_exchange_id"),
            (_agg_payload(filters=[{"column": "c", "op": ">=", "values": [1]}]),
             "invalid_filter_op"),
            (_agg_payload(filters=[{"column": "c", "op": "BETWEEN", "values": [1]}]),
             "invalid_filter_values"),
            (_agg_payload(kept_ids=[-1]), "invalid_kept_ids"),
            (_agg_payload(drill="nope"), "invalid_drill"),
            (_agg_payload(measures=[]), "invalid_aggregate"),
            (_agg_payload(measures="nope"), "invalid_aggregate"),
            (_agg_payload(measures=[{"fn": "count", "column": "x"}]), "invalid_aggregate"),
            (_agg_payload(group=5), "invalid_group"),
            (_agg_payload(group={"column": "c", "bucket": "week"}), "invalid_group_bucket"),
        ]
        for payload, code in bad:
            with self.assertRaises(ValidationError, msg=code) as ctx:
                validate_evidence_aggregate_request(payload)
            self.assertEqual(ctx.exception.code, code)


# --- 4. Regression: /evidence/rows renders =/IN filters byte-identically -----------


class EvidenceRowsRegressionTests(unittest.TestCase):
    """The evidence_rows refactor (WHERE assembly extracted to _evidence_conditions)
    must leave the =/IN + locked-chip rendering unchanged."""

    def setUp(self):
        self._orig_context = service._context
        self._orig_run = service._run_evidence_query

    def tearDown(self):
        service._context = self._orig_context
        service._run_evidence_query = self._orig_run

    def test_eq_in_and_locked_chip_rendering_unchanged(self):
        locked = {"id": 5, "column": "country", "op": "=", "values": ["FR"],
                  "editable": False}
        rec = _Recorder([{"country": "FR"}])
        service._context = lambda uid, eid, preferred_table=None: _ctx(
            _COLS, predicates=[locked])
        service._run_evidence_query = rec
        out = service.evidence_rows(
            "u", "ex",
            [{"column": "amount", "op": "IN", "values": [10, 20]},
             {"column": "created", "op": "=", "values": ["2025-01-01"]}],
            [5], False, 50, 0, None)
        self.assertEqual(len(rec.queries), 1)
        q = rec.queries[0]
        # Locked chip re-derived from the stored SQL (kept by id).
        self.assertIn('"country" = ', q)
        # Editable client filters normalized exactly as before (single '=' stays '=',
        # multi-value becomes IN) - no BETWEEN path taken here.
        self.assertIn('"amount" IN (', q)
        self.assertIn('"created" = ', q)
        self.assertNotIn("BETWEEN", q)
        self.assertEqual(out, {"rows": [{"country": "FR"}], "has_more": False,
                               "offset": 0})


if __name__ == "__main__":
    unittest.main()
