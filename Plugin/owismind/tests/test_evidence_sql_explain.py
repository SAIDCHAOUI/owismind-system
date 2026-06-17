# Plugin/owismind/tests/test_evidence_sql_explain.py
"""evidence.sql_explain: pure business explainer for the trust layer (no dataiku).

Locks the frozen contract consumed by service.normalize_explain: step kinds,
honest completeness flags (under-claim only), identity-lineage group keys, and
the never-raises guarantee - across the full SQL matrix (simple selects,
aggregations, calculations, CTE/window structures, set ops, hostile input).
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.evidence.sql_explain import explain_select  # noqa: E402


def kinds(result):
    return [s["kind"] for s in result["steps"]]


def step(result, kind):
    for s in result["steps"]:
        if s["kind"] == kind:
            return s
    return None


class SimpleSelectTests(unittest.TestCase):
    def test_single_table_text_filter(self):
        r = explain_select("SELECT a FROM t WHERE status = 'open'")
        self.assertTrue(r["ok"])
        self.assertTrue(r["where_complete"])
        self.assertTrue(r["single_source"])
        self.assertEqual(step(r, "filter_eq")["params"], ["status", "open"])

    def test_numeric_and_range_filters(self):
        r = explain_select(
            "SELECT a FROM t WHERE amount >= 100 AND d BETWEEN '2025-01-01' AND '2025-12-31'"
        )
        self.assertEqual(step(r, "filter_gte")["params"][0], "amount")
        self.assertEqual(step(r, "filter_between")["params"],
                         ["d", "2025-01-01", "2025-12-31"])
        self.assertTrue(r["where_complete"])

    def test_null_filters_and_in_list(self):
        r = explain_select(
            "SELECT a FROM t WHERE x IS NULL AND y IS NOT NULL AND z IN ('a', 'b')"
        )
        self.assertIsNotNone(step(r, "filter_null"))
        self.assertIsNotNone(step(r, "filter_notnull"))
        self.assertEqual(step(r, "filter_in")["params"][:2], ["z", "2"])

    def test_not_in_and_like(self):
        r = explain_select("SELECT a FROM t WHERE z NOT IN (1, 2) AND name LIKE 'A%'")
        self.assertIsNotNone(step(r, "filter_notin"))
        self.assertEqual(step(r, "filter_like")["params"], ["name", "A%"])

    def test_sort_without_limit(self):
        r = explain_select("SELECT a FROM t ORDER BY a DESC")
        self.assertEqual(step(r, "sort")["params"], ["a", "desc"])
        self.assertIsNone(step(r, "topn"))

    def test_top_n_requires_order_by(self):
        r = explain_select("SELECT a FROM t ORDER BY a DESC LIMIT 10")
        self.assertEqual(step(r, "topn")["params"], ["10", "a desc"])
        self.assertIsNone(step(r, "limit_arbitrary"))

    def test_top_n_shows_every_ordering_key(self):
        # Tie-breakers decide WHICH rows make the top-N (FP-07): all keys travel.
        r = explain_select(
            "SELECT region, total FROM t ORDER BY year ASC, total DESC LIMIT 10"
        )
        self.assertEqual(step(r, "topn")["params"], ["10", "year asc, total desc"])

    def test_limit_without_order_is_never_topn(self):
        # Anti-lie rule: LIMIT alone is an arbitrary sample, not a ranking.
        r = explain_select("SELECT a FROM t LIMIT 5")
        self.assertIsNone(step(r, "topn"))
        self.assertEqual(step(r, "limit_arbitrary")["params"], ["5"])

    def test_column_alias_keeps_understanding(self):
        r = explain_select("SELECT customer AS client FROM t")
        self.assertTrue(r["select_understood"])

    def test_or_on_single_table_is_advanced_not_dropped(self):
        # Mirrors sql_parse: the panel re-applies the fragment on a plain
        # single-table query, so completeness is preserved.
        r = explain_select("SELECT a FROM t WHERE a = 1 OR b = 2")
        self.assertIsNotNone(step(r, "filter_advanced"))
        self.assertTrue(r["where_complete"])

    def test_or_on_join_is_dropped(self):
        r = explain_select(
            "SELECT a.x FROM t a JOIN u b ON a.id = b.id WHERE a.c = 1 OR b.d = 2"
        )
        self.assertFalse(r["where_complete"])
        self.assertTrue(r["dropped_where"])


class AggregationTests(unittest.TestCase):
    def test_every_aggregate_kind(self):
        r = explain_select(
            "SELECT SUM(a), AVG(b), MIN(c), MAX(d), COUNT(*), COUNT(e), "
            "COUNT(DISTINCT f) FROM t GROUP BY g"
        )
        for kind in ("agg_sum", "agg_avg", "agg_min", "agg_max",
                     "agg_count_star", "agg_count", "agg_count_distinct"):
            self.assertIsNotNone(step(r, kind), kind)
        self.assertTrue(r["select_understood"])

    def test_group_by_simple_key(self):
        r = explain_select("SELECT customer, SUM(rev) FROM t GROUP BY customer")
        self.assertEqual(r["group_keys"], ["customer"])
        self.assertEqual(step(r, "group")["params"], ["customer"])

    def test_group_by_multiple_keys(self):
        r = explain_select("SELECT a, b, SUM(c) FROM t GROUP BY a, b")
        self.assertEqual(r["group_keys"], ["a", "b"])

    def test_group_by_position_resolves_through_items(self):
        r = explain_select("SELECT customer, SUM(rev) FROM t GROUP BY 1")
        self.assertEqual(r["group_keys"], ["customer"])

    def test_group_by_expression_is_excluded_from_keys(self):
        # date_trunc(month) is explainable but NOT a drillable identity key.
        r = explain_select(
            "SELECT date_trunc('month', d) AS m, SUM(rev) FROM t GROUP BY date_trunc('month', d)"
        )
        self.assertEqual(r["group_keys"], [])
        self.assertFalse(r["calc_resolved"])

    def test_having_simple_aggregate(self):
        r = explain_select(
            "SELECT customer, SUM(rev) AS total FROM t GROUP BY customer HAVING SUM(rev) > 1000"
        )
        self.assertIsNotNone(step(r, "having"))
        self.assertTrue(r["calc_resolved"])

    def test_having_opaque_breaks_calc_resolved(self):
        r = explain_select(
            "SELECT customer, SUM(rev) FROM t GROUP BY customer "
            "HAVING SUM(rev) / NULLIF(COUNT(*), 0) > 5"
        )
        self.assertIsNotNone(step(r, "having"))
        self.assertFalse(r["calc_resolved"])

    def test_calc_on_aggregate_ratio(self):
        r = explain_select("SELECT SUM(a) / NULLIF(SUM(b), 0) AS ratio FROM t")
        self.assertIsNotNone(step(r, "calc_ratio"))


class CalculationTests(unittest.TestCase):
    def test_sum_case_when_simple_is_agg_filtered(self):
        r = explain_select(
            "SELECT SUM(CASE WHEN phase = 'BUDGET' THEN amount ELSE 0 END) FROM t GROUP BY c"
        )
        s = step(r, "agg_filtered")
        self.assertEqual(s["params"][0], "SUM")
        self.assertIn("BUDGET", s["params"][2])
        self.assertTrue(r["select_understood"])

    def test_case_with_complex_when_is_opaque(self):
        r = explain_select(
            "SELECT SUM(CASE WHEN a > b THEN amount ELSE 0 END) FROM t"
        )
        self.assertIsNotNone(step(r, "opaque"))
        self.assertFalse(r["select_understood"])

    def test_difference(self):
        r = explain_select("SELECT SUM(a) - SUM(b) AS gap FROM t")
        self.assertIsNotNone(step(r, "calc_diff"))

    def test_percent_factor_100(self):
        r = explain_select("SELECT 100 * a / b AS pct FROM t")
        # Lowest-precedence split sees the ratio first; both readings honest.
        self.assertTrue(step(r, "calc_ratio") or step(r, "calc_percent"))

    def test_rounding_unwraps(self):
        r = explain_select("SELECT ROUND(SUM(a), 2) FROM t GROUP BY c")
        self.assertIsNotNone(step(r, "agg_sum"))

    def test_share_of_total_pattern(self):
        r = explain_select("SELECT SUM(a) / SUM(SUM(a)) OVER () AS share FROM t GROUP BY c")
        self.assertIsNotNone(step(r, "calc_share"))


class StructureTests(unittest.TestCase):
    REVEALING = (
        "WITH client_rev AS (SELECT customer, SUM(revenue) AS total "
        "FROM drive_revenues WHERE phase = 'ACTUALS' AND year = 2025 GROUP BY customer), "
        "ranked AS (SELECT customer, total, SUM(total) OVER () AS grand_total, "
        "SUM(total) OVER (ORDER BY total DESC) AS running FROM client_rev) "
        "SELECT customer, total, ROUND(100.0 * running / grand_total, 1) AS cum_share "
        "FROM ranked WHERE 100.0 * running / grand_total <= 80"
    )

    def test_revealing_example_lineage_and_honesty(self):
        r = explain_select(self.REVEALING)
        self.assertTrue(r["ok"])
        # The group key traces customer -> ranked -> client_rev -> drive_revenues.
        self.assertEqual(r["group_keys"], ["customer"])
        self.assertTrue(r["single_source"])
        # The 80% threshold (window-derived) is honestly NOT reproduced.
        self.assertFalse(r["where_complete"])
        self.assertTrue(any("80" in d for d in r["dropped_where"]))
        for kind in ("source", "filter_eq", "group", "agg_sum", "window_running"):
            self.assertIsNotNone(step(r, kind), kind)

    def test_single_cte_keeps_filters(self):
        r = explain_select(
            "WITH base AS (SELECT * FROM t WHERE year = 2025) SELECT a FROM base"
        )
        self.assertEqual(step(r, "filter_eq")["params"], ["year", "2025"])
        self.assertTrue(r["single_source"])
        self.assertEqual(step(r, "source")["params"], ["t"])

    def test_cte_name_is_never_a_source(self):
        r = explain_select(
            "WITH base AS (SELECT * FROM t) SELECT a FROM base"
        )
        self.assertEqual(step(r, "source")["params"], ["t"])

    def test_window_row_number_and_rank(self):
        r = explain_select(
            "SELECT ROW_NUMBER() OVER (ORDER BY x) AS rn, "
            "RANK() OVER (PARTITION BY p ORDER BY y DESC) AS rk FROM t"
        )
        self.assertIsNotNone(step(r, "window_row_number"))
        self.assertIsNotNone(step(r, "window_rank"))

    def test_running_total(self):
        r = explain_select("SELECT SUM(a) OVER (ORDER BY d) FROM t")
        s = step(r, "window_running")
        self.assertEqual(s["params"][0], "a")
        self.assertIn("d", s["params"][1])

    def test_distinct_step(self):
        r = explain_select("SELECT DISTINCT a FROM t")
        self.assertIsNotNone(step(r, "distinct"))

    def test_union_flags_and_step(self):
        r = explain_select("SELECT a FROM t1 UNION ALL SELECT a FROM t2")
        self.assertTrue(r["has_set_op"])
        self.assertFalse(r["where_complete"])  # unanalysed arms widen the scope
        self.assertEqual(r["group_keys"], [])
        self.assertIsNotNone(step(r, "union"))

    def test_joins_inner_and_left(self):
        r = explain_select(
            "SELECT a.x FROM t a LEFT JOIN u b ON a.id = b.id JOIN v c ON c.id = a.id"
        )
        joins = [s for s in r["steps"] if s["kind"] == "join"]
        self.assertEqual(len(joins), 2)
        self.assertEqual(joins[0]["params"][0], "left")
        self.assertFalse(r["single_source"])

    def test_self_join_is_not_single_source(self):
        r = explain_select("SELECT a.x FROM t a JOIN t b ON a.id = b.id")
        self.assertFalse(r["single_source"])

    def test_derived_subquery_in_from(self):
        r = explain_select(
            "SELECT s.a FROM (SELECT a FROM t WHERE year = 2025) s"
        )
        self.assertEqual(step(r, "source")["params"], ["t"])
        self.assertEqual(step(r, "filter_eq")["params"], ["year", "2025"])
        self.assertTrue(r["single_source"])

    def test_stacked_aggregations_disable_group_keys(self):
        r = explain_select(
            "WITH a AS (SELECT c, SUM(x) AS s FROM t GROUP BY c) "
            "SELECT s, COUNT(*) FROM a GROUP BY s"
        )
        self.assertEqual(r["group_keys"], [])

    def test_recursive_cte_flag(self):
        r = explain_select(
            "WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r) "
            "SELECT n FROM r"
        )
        self.assertTrue(r["has_recursive_cte"])
        self.assertEqual(r["group_keys"], [])
        self.assertFalse(r["calc_resolved"])

    def test_lineage_breaks_on_renamed_computed_column(self):
        # The CTE exposes a COMPUTED column under the grouped name: no identity
        # lineage, so the key must NOT be drillable.
        r = explain_select(
            "WITH base AS (SELECT UPPER(customer) AS customer, rev FROM t) "
            "SELECT customer, SUM(rev) FROM base GROUP BY customer"
        )
        self.assertEqual(r["group_keys"], [])

    def test_lineage_follows_alias_rename_to_source_name(self):
        # The drill must filter the PHYSICAL column: keys carry the SOURCE name
        # at the end of the identity chain, never the outer alias (FP-06).
        r = explain_select(
            "WITH base AS (SELECT customer AS client, rev FROM t) "
            "SELECT client, SUM(rev) FROM base GROUP BY client"
        )
        self.assertEqual(r["group_keys"], ["customer"])

    def test_computed_column_reused_downstream(self):
        r = explain_select(
            "WITH m AS (SELECT c, SUM(x) AS total FROM t GROUP BY c) "
            "SELECT c, total * 2 AS dbl FROM m"
        )
        self.assertTrue(r["ok"])
        self.assertEqual(r["group_keys"], ["c"])


class RobustnessTests(unittest.TestCase):
    def test_never_raises_on_hostile_input(self):
        cases = (
            None, "", "   ", 42, "DROP TABLE x", "UPDATE t SET a = 1",
            "SELECT 1; SELECT 2", "x" * 30000,
            "SELECT a FROM t WHERE (((b = 1)",          # unbalanced
            "SELECT $$weird$$ FROM t",                  # unknown tokens
            "WITH broken AS SELECT 1 SELECT 2",          # malformed WITH
            "SELECT " + "(" * 4000 + "1" + ")" * 4000 + " FROM t",
        )
        for sql in cases:
            r = explain_select(sql)
            self.assertIsInstance(r, dict, repr(sql)[:40])
            self.assertIn("ok", r)

    def test_failure_shape_underclaims_everything(self):
        r = explain_select("NOT SQL AT ALL")
        self.assertFalse(r["ok"])
        self.assertFalse(r["where_complete"])
        self.assertFalse(r["select_understood"])
        self.assertFalse(r["calc_resolved"])
        self.assertEqual(r["steps"], [])
        self.assertEqual(r["group_keys"], [])

    def test_comments_are_masked_for_explanation(self):
        r = explain_select("SELECT a FROM t -- a comment\nWHERE b = 1")
        self.assertTrue(r["ok"])
        self.assertEqual(step(r, "filter_eq")["params"], ["b", "1"])

    def test_block_comment_masked(self):
        r = explain_select("SELECT a /* note */ FROM t WHERE b = 2")
        self.assertTrue(r["ok"])
        self.assertEqual(step(r, "filter_eq")["params"], ["b", "2"])

    def test_trailing_semicolon_tolerated(self):
        self.assertTrue(explain_select("SELECT a FROM t;")["ok"])

    def test_steps_are_bounded(self):
        many = " AND ".join("c{} = {}".format(i, i) for i in range(40))
        r = explain_select("SELECT a FROM t WHERE " + many)
        self.assertLessEqual(len(r["steps"]), 15)

    def test_unknown_select_expression_is_opaque(self):
        r = explain_select("SELECT corr(a, b) FROM t")
        self.assertIsNotNone(step(r, "opaque"))
        self.assertFalse(r["select_understood"])

    def test_subquery_select_item_is_opaque(self):
        r = explain_select("SELECT (SELECT MAX(x) FROM u) AS top FROM t")
        self.assertFalse(r["select_understood"])

    def test_where_subquery_conjunct_is_dropped_on_join(self):
        r = explain_select(
            "SELECT a.x FROM t a JOIN u b ON a.id = b.id "
            "WHERE a.k IN (SELECT k FROM v) AND a.y = 1"
        )
        self.assertFalse(r["where_complete"])
        self.assertTrue(any("SELECT" in d or "select" in d for d in r["dropped_where"]))
        # The simple conjunct still explains.
        self.assertIsNotNone(step(r, "filter_eq"))


class ReviewRegressionTests(unittest.TestCase):
    """Locks the adversarial-review fixes (FP-01/02/04/05/06, CONTRACT-04)."""

    def test_fp01_where_subquery_on_single_table_is_never_complete(self):
        # sql_parse counts the WHERE sub-query as a second scope -> no advanced
        # fragment is ever applied at runtime; explain must agree (FP-01).
        r = explain_select(
            "SELECT region, SUM(revenue) FROM sales "
            "WHERE year IN (SELECT year FROM ref_years) GROUP BY region"
        )
        self.assertFalse(r["where_complete"])
        self.assertTrue(r["dropped_where"])
        self.assertIsNone(step(r, "filter_advanced"))
        self.assertIsNotNone(step(r, "filter_unmapped"))

    def test_fp02_self_join_through_cte_is_not_single_source(self):
        r = explain_select(
            "WITH c AS (SELECT region, revenue FROM sales) "
            "SELECT a.region, SUM(a.revenue) FROM c a JOIN c b "
            "ON a.region = b.region GROUP BY a.region"
        )
        self.assertFalse(r["single_source"])
        # The CTE self-join is visible in the explanation.
        self.assertIsNotNone(step(r, "join"))

    def test_fp04_avg_case_else_zero_is_opaque(self):
        # ELSE 0 weighs an AVG denominator: "only when cond" would lie.
        r = explain_select(
            "SELECT AVG(CASE WHEN phase = 'ACTUALS' THEN revenue ELSE 0 END) FROM t"
        )
        self.assertIsNone(step(r, "agg_filtered"))
        self.assertFalse(r["select_understood"])

    def test_fp04_avg_case_else_null_is_filtered(self):
        r = explain_select(
            "SELECT AVG(CASE WHEN phase = 'ACTUALS' THEN revenue ELSE NULL END) FROM t"
        )
        self.assertIsNotNone(step(r, "agg_filtered"))

    def test_fp05_share_requires_same_sum_argument(self):
        # SUM(revenue) / SUM(forecast) OVER () is NOT a share of total.
        r = explain_select("SELECT SUM(revenue) / SUM(forecast) OVER () FROM t GROUP BY c")
        self.assertIsNone(step(r, "calc_share"))
        self.assertIsNotNone(step(r, "calc_ratio"))

    def test_fp05_share_rejects_partitioned_total(self):
        r = explain_select(
            "SELECT SUM(rev) / SUM(SUM(rev)) OVER (PARTITION BY region) FROM t GROUP BY c"
        )
        self.assertIsNone(step(r, "calc_share"))

    def test_fp05_share_rejects_non_sum_window(self):
        r = explain_select("SELECT SUM(rev) / MAX(rev) OVER () FROM t GROUP BY c")
        self.assertIsNone(step(r, "calc_share"))

    def test_fp06_rename_with_homonymous_source_column_drills_the_right_one(self):
        # base renames region->r while the source table also has a column r:
        # the key must be the SOURCE column (region), never the outer alias.
        r = explain_select(
            "WITH base AS (SELECT region AS r, revenue FROM sales) "
            "SELECT r, SUM(revenue) FROM base GROUP BY r"
        )
        self.assertEqual(r["group_keys"], ["region"])

    def test_contract04_unmapped_conjuncts_are_listed_inline(self):
        r = explain_select(
            "SELECT a.x FROM t a JOIN u b ON a.id = b.id WHERE a.y + b.z > 10"
        )
        self.assertIsNotNone(step(r, "filter_unmapped"))
        self.assertFalse(r["where_complete"])


if __name__ == "__main__":
    unittest.main()
