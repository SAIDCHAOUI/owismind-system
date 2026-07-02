# Plugin/owismind/tests/test_evidence_service_proof.py
"""Trust-layer proof helpers of evidence/service.py (pure, DSS-free).

The service pipeline itself is dataiku-bound (owner-scoped SQL read, dataset
discovery, live schema, execution), but every trust-layer block of
/evidence/meta and the drill-down gates of /evidence/rows are computed by PURE
module-level functions precisely so the honesty rules are provable here
(project TEST-01 idiom): verification ladder, queries[] summary, drill-down
derivation + rendering, captured-result block, explain normalization.
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
    """Minimal import-time stubs (NO install - the README's "(or a stub)" idiom).

    service.py imports dataiku/SQLExecutor2 (and, transitively, dataiku.sql +
    pandas) at module load. The functions under test never touch them, so bare
    stubs are enough - and existing stubs from sibling test files are extended,
    never replaced (unittest discover shares one sys.modules).
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

from owismind.evidence.service import (  # noqa: E402
    EvidenceError,
    MAX_DROPPED_DISPLAY,
    MAX_EXPLANATION_STEPS,
    build_drill_conditions,
    build_dropped_display,
    build_explanation,
    build_result_block,
    compute_verification,
    derive_drilldown,
    effective_where_complete,
    has_captured_result,
    item_matches_candidates,
    results_by_sql_map,
    matched_source_tables,
    source_url_for_run,
    with_source_urls,
    normalize_explain,
    predicate_display,
    summarize_queries,
    verification_level,
)


def _explain(**over):
    """A fully-trustable explain dict; tests degrade it one gate at a time."""
    base = {
        "ok": True, "reason": None, "steps": [],
        "where_complete": True, "dropped_where": [],
        "group_keys": ["customer"], "single_source": True,
        "select_understood": True, "has_set_op": False,
        "has_recursive_cte": False, "calc_resolved": True,
    }
    base.update(over)
    return base


def _pred(pid, column="phase", op="=", values=("ACTUALS",)):
    return {"id": pid, "column": column, "op": op, "values": list(values),
            "editable": op in ("=", "IN")}


# Stub quoters for the rendering tests (render_predicate takes them injected).
def _quote_ident(name):
    return '"' + name + '"'


def _quote_value(value):
    return "<{!r}>".format(value)


class NormalizeExplainTests(unittest.TestCase):
    def test_garbage_in_safe_defaults(self):
        # A missing/partial/malformed explainer can only ever UNDER-claim.
        for garbage in (None, "x", [], 42, {"ok": "yes-ish", "steps": "nope"}):
            out = normalize_explain(garbage)
            self.assertFalse(out["where_complete"], msg=repr(garbage))
            self.assertFalse(out["single_source"])
            self.assertFalse(out["select_understood"])
            self.assertEqual(out["steps"], [])
            self.assertEqual(out["group_keys"], [])

    def test_truthy_ok_coerced(self):
        self.assertTrue(normalize_explain({"ok": True})["ok"])
        self.assertFalse(normalize_explain({"ok": 0})["ok"])

    def test_steps_filtered_and_capped(self):
        raw = [{"kind": "filter_eq", "params": ["phase", "ACTUALS"]},
               {"no_kind": 1}, "junk", {"kind": 7},
               {"kind": "group", "params": "not-a-list"}]
        raw += [{"kind": "opaque", "params": []}] * 20
        out = normalize_explain(_explain(steps=raw))
        self.assertLessEqual(len(out["steps"]), MAX_EXPLANATION_STEPS)
        self.assertEqual(out["steps"][0],
                         {"kind": "filter_eq", "params": ["phase", "ACTUALS"]})
        # Malformed params degrade to [] instead of leaking a non-list shape.
        self.assertEqual(out["steps"][1], {"kind": "group", "params": []})
        for step in out["steps"]:
            self.assertIsInstance(step["kind"], str)
            self.assertIsInstance(step["params"], list)

    def test_lists_type_filtered(self):
        out = normalize_explain(_explain(group_keys=["a", 3, None, "b"],
                                         dropped_where=["x > avg(y)", 9]))
        self.assertEqual(out["group_keys"], ["a", "b"])
        self.assertEqual(out["dropped_where"], ["x > avg(y)"])


class VerificationLadderTests(unittest.TestCase):
    """The deterministic level ladder (frozen contract §2) - honesty matrix."""

    def test_not_matched_is_declared(self):
        # Matrix: invalid SQL / unmapped table -> the degraded 'declared' claim.
        self.assertEqual(
            verification_level(_explain(), False, 5, True), "declared")

    def test_explain_not_ok_is_source_identified(self):
        # Matrix: WHERE could not be assessed (explainer failed/absent).
        self.assertEqual(
            verification_level(_explain(ok=False), True, 3, True),
            "source_identified")

    def test_scope_exact(self):
        # Complete WHERE + single source + no set-op, even with ZERO predicate
        # (SELECT * FROM t IS an exact scope: the whole table). calc_resolved
        # is off here so the level stops one rung below calc_decomposed.
        self.assertEqual(
            verification_level(_explain(calc_resolved=False), True, 0, True),
            "scope_exact")

    def test_calc_decomposed_requires_understood_and_resolved(self):
        v = compute_verification(_explain(), True, [_pred(0)], [_pred(0)], 0, True)
        self.assertEqual(v["level"], "calc_decomposed")
        # select_understood alone is NOT enough (group/order/having + CTE DAG).
        v2 = compute_verification(_explain(calc_resolved=False),
                                  True, [_pred(0)], [_pred(0)], 0, True)
        self.assertEqual(v2["level"], "scope_exact")
        v3 = compute_verification(_explain(select_understood=False),
                                  True, [_pred(0)], [_pred(0)], 0, True)
        self.assertEqual(v3["level"], "scope_exact")

    def test_dropped_conjunct_gives_scope_partial(self):
        # explain saw a conjunct it could not decompose -> completeness broken.
        v = compute_verification(
            _explain(where_complete=False, dropped_where=["x > avg(y)"]),
            True, [_pred(0)], [_pred(0)], 0, False)
        self.assertEqual(v["level"], "scope_partial")
        self.assertFalse(v["where_complete"])

    def test_colmap_drop_breaks_where_complete(self):
        # explain says complete, but ONE predicate did not resolve on the LIVE
        # schema: the rebuilt scope is silently wider -> never scope_exact.
        v = compute_verification(_explain(), True,
                                 [_pred(0), _pred(1, column="ghost")],
                                 [_pred(0)], 1, False)
        self.assertFalse(v["where_complete"])
        self.assertEqual(v["level"], "scope_partial")
        self.assertEqual(v["dropped_predicates"], 1)

    def test_incomplete_where_without_mapped_predicate_is_source_identified(self):
        v = compute_verification(_explain(where_complete=False), True, [], [], 0, False)
        self.assertEqual(v["level"], "source_identified")

    def test_set_op_blocks_scope_exact(self):
        v = compute_verification(_explain(has_set_op=True),
                                 True, [_pred(0)], [_pred(0)], 0, False)
        self.assertEqual(v["level"], "scope_partial")

    def test_self_join_is_not_single_source(self):
        # The explainer reports single_source=False for self-joins (frozen rule).
        v = compute_verification(_explain(single_source=False),
                                 True, [_pred(0)], [_pred(0)], 0, False)
        self.assertEqual(v["level"], "scope_partial")
        self.assertFalse(v["single_source"])

    def test_dropped_counts_and_display(self):
        parsed = [_pred(0), _pred(1, column="other", op=">", values=(10,)),
                  _pred(2, column="ghost", op="IN", values=("a", "b"))]
        kept = [parsed[0]]
        v = compute_verification(
            _explain(where_complete=False, dropped_where=["c1 ~ 'x'", "c2 > c3"]),
            True, parsed, kept, 1, False)
        # (3 parsed - 1 kept) + 2 explain conjuncts = 4, the EXACT count.
        self.assertEqual(v["dropped_predicates"], 4)
        self.assertIn("other > 10", v["dropped_display"])
        self.assertIn("ghost IN a, b", v["dropped_display"])
        self.assertIn("c1 ~ 'x'", v["dropped_display"])
        self.assertLessEqual(len(v["dropped_display"]), MAX_DROPPED_DISPLAY)

    def test_dropped_display_capped_at_ten(self):
        parsed = [_pred(i, column="c{}".format(i)) for i in range(15)]
        out = build_dropped_display(parsed, ["x"] * 5)
        self.assertEqual(len(out), MAX_DROPPED_DISPLAY)

    def test_result_captured_is_orthogonal(self):
        for captured in (True, False):
            v = compute_verification(_explain(ok=False), True, [], [], 0, captured)
            self.assertEqual(v["result_captured"], captured)
            self.assertEqual(v["level"], "source_identified")

    def test_effective_where_complete_formula(self):
        self.assertTrue(effective_where_complete(_explain(), 0))
        self.assertFalse(effective_where_complete(_explain(), 1))
        self.assertFalse(effective_where_complete(_explain(where_complete=False), 0))

    def test_predicate_display_shapes(self):
        self.assertEqual(predicate_display(_pred(0)), "phase = ACTUALS")
        self.assertEqual(
            predicate_display({"column": "x", "op": "IS NULL", "values": []}),
            "x IS NULL")
        # Display strings are bounded (a pathological IN-list cannot bloat meta).
        long = predicate_display(_pred(0, values=tuple(["v" * 50] * 10)))
        self.assertLessEqual(len(long), 120)


class SummarizeQueriesTests(unittest.TestCase):
    def test_basic_summary_shape(self):
        items = [{"sql": "SELECT 1", "success": True, "row_count": 12},
                 {"sql": "SELECT 2", "success": 0, "row_count": None}]
        out = summarize_queries(items, [True, False])
        self.assertEqual(out, [
            {"index": 1, "success": True, "row_count": 12,
             "matched": True, "result_captured": False},
            {"index": 2, "success": False, "row_count": None,
             "matched": False, "result_captured": False},
        ])

    def test_optional_tags_only_when_present(self):
        items = [{"sql": "s", "success": True, "row_count": 1,
                  "step_index": 2, "agent_key": "salesdrive"},
                 {"sql": "s2", "success": True, "row_count": 1}]
        out = summarize_queries(items, [True, True])
        self.assertEqual(out[0]["step_index"], 2)
        self.assertEqual(out[0]["agent_key"], "salesdrive")
        self.assertNotIn("step_index", out[1])
        self.assertNotIn("agent_key", out[1])

    def test_malformed_tags_dropped(self):
        items = [{"sql": "s", "success": True, "row_count": 1,
                  "step_index": True, "agent_key": 42}]
        out = summarize_queries(items, [False])
        self.assertNotIn("step_index", out[0])  # bool is not a step index
        self.assertNotIn("agent_key", out[0])

    def test_result_captured_per_item(self):
        ok = {"sql": "s", "success": True, "row_count": 1,
              "result": {"columns": ["a"], "rows": [[1]], "truncated": False}}
        malformed = {"sql": "s", "success": True, "row_count": 1,
                     "result": {"columns": "a"}}
        out = summarize_queries([ok, malformed], [True, True])
        self.assertTrue(out[0]["result_captured"])
        self.assertFalse(out[1]["result_captured"])

    def test_missing_flags_default_false_and_non_dicts_skipped(self):
        items = [{"sql": "a", "success": True, "row_count": 1}, "junk",
                 {"sql": "b", "success": True, "row_count": "12"}]
        out = summarize_queries(items, [])
        self.assertEqual(len(out), 2)
        self.assertFalse(out[0]["matched"])
        self.assertIsNone(out[1]["row_count"])  # malformed count -> honest None


class ItemMatchTests(unittest.TestCase):
    CANDIDATES = [{"name": "DRIVE_Revenues", "table": "drive_revenues",
                   "schema": "public"}]

    def test_matching_table(self):
        self.assertTrue(item_matches_candidates(
            "SELECT * FROM public.drive_revenues WHERE phase = 'ACTUALS'",
            self.CANDIDATES))

    def test_join_arm_matching(self):
        # Any source table of the item matching a candidate counts as matched.
        self.assertTrue(item_matches_candidates(
            "SELECT a.x FROM other_t a JOIN drive_revenues r ON a.id = r.id",
            self.CANDIDATES))

    def test_non_matching_table(self):
        self.assertFalse(item_matches_candidates(
            "SELECT * FROM somewhere_else", self.CANDIDATES))

    def test_invalid_sql_never_matches_never_raises(self):
        self.assertFalse(item_matches_candidates("DELETE FROM x", self.CANDIDATES))
        self.assertFalse(item_matches_candidates(None, self.CANDIDATES))


class MatchedSourceTablesTests(unittest.TestCase):
    """The DISTINCT matched-source list driving the multi-table selector (pure)."""

    CANDIDATES = [
        {"name": "DRIVE_Revenues", "table": "drive_revenues", "schema": "public"},
        {"name": "Tickets", "table": "tickets", "schema": "public"},
    ]

    def test_single_source_one_entry(self):
        parsed = [{"table": "drive_revenues", "schema": "public"}]
        out = matched_source_tables(parsed, self.CANDIDATES)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["dataset"], "DRIVE_Revenues")
        self.assertEqual(out[0]["table"], "drive_revenues")
        self.assertEqual(out[0]["label"], "DRIVE_Revenues")

    def test_two_distinct_sources_first_seen_order(self):
        parsed = [{"table": "tickets", "schema": "public"},
                  {"table": "drive_revenues", "schema": "public"}]
        out = matched_source_tables(parsed, self.CANDIDATES)
        self.assertEqual([e["dataset"] for e in out], ["Tickets", "DRIVE_Revenues"])

    def test_duplicate_table_collapses(self):
        # The SAME dataset referenced twice (e.g. a self-join) yields ONE entry.
        parsed = [{"table": "drive_revenues", "schema": "public"},
                  {"table": "drive_revenues", "schema": None}]
        out = matched_source_tables(parsed, self.CANDIDATES)
        self.assertEqual(len(out), 1)

    def test_unmatched_tables_excluded(self):
        parsed = [{"table": "elsewhere", "schema": "public"},
                  {"table": "tickets", "schema": "public"}]
        out = matched_source_tables(parsed, self.CANDIDATES)
        self.assertEqual([e["dataset"] for e in out], ["Tickets"])

    def test_malformed_input_never_raises(self):
        self.assertEqual(matched_source_tables(None, self.CANDIDATES), [])
        self.assertEqual(matched_source_tables(["not a dict"], self.CANDIDATES), [])
        self.assertEqual(matched_source_tables([{"table": "tickets"}], None), [])


class SourceUrlTests(unittest.TestCase):
    """The dataset source link configured on the agent (stamped on each captured
    SQL item by the orchestrator) reaches the Evidence meta."""

    def test_url_from_active_item_then_fallback(self):
        active = {"sql": "s", "source_url": "https://dss/active"}
        items = [{"sql": "a"}, active, {"sql": "b", "source_url": "https://dss/other"}]
        self.assertEqual(source_url_for_run(active, items), "https://dss/active")
        # No url on the active item -> fall back to any item that carries one.
        items2 = [{"sql": "a"}, {"sql": "b", "source_url": "https://dss/other"}]
        self.assertEqual(source_url_for_run({"sql": "s"}, items2), "https://dss/other")

    def test_url_empty_when_unconfigured(self):
        self.assertEqual(source_url_for_run({"sql": "s"}, [{"sql": "a"}]), "")
        self.assertEqual(source_url_for_run(None, None), "")

    def test_with_source_urls_single_source_only(self):
        one = [{"dataset": "DRIVE_Revenues", "table": "t"}]
        out = with_source_urls(one, "https://dss/d")
        self.assertEqual(out[0]["url"], "https://dss/d")
        # Multi-source is left untouched (no per-dataset link mapping).
        two = [{"dataset": "A"}, {"dataset": "B"}]
        self.assertEqual(with_source_urls(two, "https://dss/d"), two)
        # No url -> unchanged.
        self.assertEqual(with_source_urls(one, ""), one)


class ResultBlockTests(unittest.TestCase):
    def test_captured_block(self):
        item = {"sql": "s", "success": True, "row_count": 12,
                "result": {"columns": ["customer", "total"],
                           "rows": [["AT", 1234.5]], "truncated": False}}
        out = build_result_block(item)
        self.assertEqual(out, {"captured": True,
                               "columns": ["customer", "total"],
                               "rows": [["AT", 1234.5]],
                               "row_count": 12, "truncated": False})

    def test_row_count_is_the_agent_declared_count(self):
        # Captured rows may be truncated: row_count NEVER comes from len(rows).
        item = {"sql": "s", "success": True, "row_count": 500,
                "result": {"columns": ["a"], "rows": [[1]], "truncated": True}}
        out = build_result_block(item)
        self.assertEqual(out["row_count"], 500)
        self.assertTrue(out["truncated"])

    def test_not_captured_is_honest(self):
        out = build_result_block({"sql": "s", "success": True, "row_count": 7})
        self.assertEqual(out, {"captured": False, "row_count": 7})

    def test_malformed_result_and_row_count(self):
        self.assertFalse(has_captured_result({"result": {"columns": "x"}}))
        out = build_result_block({"row_count": True, "result": "junk"})
        self.assertEqual(out, {"captured": False, "row_count": None})
        self.assertEqual(build_result_block(None),
                         {"captured": False, "row_count": None})


class ExplanationBlockTests(unittest.TestCase):
    def test_build_explanation(self):
        explain = normalize_explain(_explain(
            steps=[{"kind": "source", "params": ["DRIVE_Revenues"]}]))
        self.assertEqual(build_explanation(explain),
                         {"ok": True,
                          "steps": [{"kind": "source", "params": ["DRIVE_Revenues"]}]})
        self.assertEqual(build_explanation({"ok": False}),
                         {"ok": False, "steps": []})


class DrilldownTests(unittest.TestCase):
    COLMAP = {"customer": "Customer", "phase": "Phase", "total": "Total"}

    def test_available_with_live_casing(self):
        out = derive_drilldown(_explain(group_keys=["CUSTOMER", "phase"]),
                               self.COLMAP, True)
        self.assertEqual(out, {"available": True,
                               "columns": ["Customer", "Phase"], "reason": None})

    def test_no_group_by_is_no_group_keys(self):
        # Matrix: a query without GROUP BY is not drillable.
        out = derive_drilldown(_explain(group_keys=[]), self.COLMAP, True)
        self.assertEqual(out, {"available": False, "columns": [],
                               "reason": "no_group_keys"})

    def test_group_keys_not_on_live_schema(self):
        out = derive_drilldown(_explain(group_keys=["ghost"]), self.COLMAP, True)
        self.assertEqual(out["reason"], "no_group_keys")
        self.assertFalse(out["available"])

    def test_multi_source(self):
        # Matrix: joins (self-join included) refuse the drill, stable code.
        out = derive_drilldown(_explain(single_source=False), self.COLMAP, True)
        self.assertEqual(out["reason"], "multi_source")

    def test_incomplete_where(self):
        # Matrix: a drill under an incomplete WHERE would lie about the group.
        out = derive_drilldown(_explain(), self.COLMAP, False)
        self.assertEqual(out["reason"], "incomplete_where")

    def test_set_op(self):
        out = derive_drilldown(_explain(has_set_op=True), self.COLMAP, True)
        self.assertEqual(out["reason"], "set_op")

    def test_more_keys_than_the_drill_cap_refuses(self):
        # CONTRACT-01: a drill that cannot constrain EVERY group key would show
        # a SUPERSET of the group - more than 8 drillable keys means NO drill.
        colmap = {"c{}".format(i): "C{}".format(i) for i in range(9)}
        keys = ["c{}".format(i) for i in range(9)]
        out = derive_drilldown(_explain(group_keys=keys), colmap, True)
        self.assertEqual(out, {"available": False, "columns": [],
                               "reason": "not_supported"})

    def test_explain_not_ok_or_recursive_cte_not_supported(self):
        self.assertEqual(derive_drilldown(_explain(ok=False), self.COLMAP, True),
                         {"available": False, "columns": [],
                          "reason": "not_supported"})
        out = derive_drilldown(_explain(has_recursive_cte=True), self.COLMAP, True)
        self.assertEqual(out["reason"], "not_supported")

    def test_gate_order_is_stable(self):
        # When several gates fail, the reason follows the documented order.
        out = derive_drilldown(_explain(has_set_op=True, single_source=False),
                               self.COLMAP, False)
        self.assertEqual(out["reason"], "set_op")


class DrillConditionsTests(unittest.TestCase):
    COLMAP = {"customer": "Customer", "phase": "Phase"}
    ALLOWED = ["Customer", "Phase"]

    def _render(self, drill):
        return build_drill_conditions(drill, self.ALLOWED, self.COLMAP,
                                      _quote_ident, _quote_value)

    def test_equality_rendering(self):
        self.assertEqual(self._render([{"column": "Customer", "value": "AT"}]),
                         ['"Customer" = <\'AT\'>'])

    def test_null_renders_is_null(self):
        self.assertEqual(self._render([{"column": "Phase", "value": None}]),
                         ['"Phase" IS NULL'])

    def test_case_insensitive_resolves_live_casing(self):
        self.assertEqual(self._render([{"column": "CUSTOMER", "value": 1}]),
                         ['"Customer" = <1>'])

    def test_unknown_column_is_invalid_drill_400(self):
        with self.assertRaises(EvidenceError) as ctx:
            self._render([{"column": "Total", "value": 1}])  # not drillable
        self.assertEqual(ctx.exception.code, "invalid_drill")
        self.assertEqual(ctx.exception.status, 400)

    def test_entry_count_mirror_cap(self):
        nine = [{"column": "Customer", "value": i} for i in range(9)]
        with self.assertRaises(EvidenceError) as ctx:
            self._render(nine)
        self.assertEqual(ctx.exception.code, "invalid_drill")

    def test_malformed_entry_rejected(self):
        for bad in (["x"], [{"value": 1}], [{"column": 7, "value": 1}]):
            with self.assertRaises(EvidenceError, msg=repr(bad)):
                self._render(bad)

    def test_empty_drill_renders_nothing(self):
        self.assertEqual(self._render([]), [])


class TestResultsBySqlMap(unittest.TestCase):
    """Per-artifact binding map: captured + UNAMBIGUOUS sql_ids only."""

    def _item(self, sql_id, cols=("a",), rows=(("1",),)):
        return {"sql": "SELECT 1", "success": True, "sql_id": sql_id,
                "result": {"columns": list(cols), "rows": [list(r) for r in rows]}}

    def test_maps_captured_items_by_sql_id(self):
        out = results_by_sql_map([self._item("s1q1"), self._item("s2q1")])
        self.assertEqual(set(out.keys()), {"s1q1", "s2q1"})
        self.assertTrue(out["s1q1"]["captured"])

    def test_excludes_items_without_capture_or_id(self):
        no_result = {"sql": "SELECT 1", "success": True, "sql_id": "s3q1"}
        no_id = self._item(None)
        out = results_by_sql_map([no_result, no_id, self._item("s1q1")])
        self.assertEqual(set(out.keys()), {"s1q1"})

    def test_excludes_ambiguous_duplicate_ids_entirely(self):
        # Two items share the same sql_id (historical fan-out collision): the
        # binding must degrade honestly, never pick one of the duplicates.
        out = results_by_sql_map(
            [self._item("s2q1", cols=("m",)), self._item("s2q1", cols=("n",)),
             self._item("s5q1")])
        self.assertEqual(set(out.keys()), {"s5q1"})

    def test_empty_and_malformed_inputs(self):
        self.assertEqual(results_by_sql_map(None), {})
        self.assertEqual(results_by_sql_map(["junk", 42]), {})


if __name__ == "__main__":
    unittest.main()
