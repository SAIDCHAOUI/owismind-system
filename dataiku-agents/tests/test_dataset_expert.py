"""DSS-free unit tests for the revenue Dataset Expert (now the LangGraph agent
``dataiku-agents/agents/SalesDrive_revenue_expert.py``).

``dataiku`` AND ``langgraph`` are stubbed BEFORE the agent file is loaded via
importlib. Only PURE functions are tested (profile parsing, understanding
validation, SQL builders, SQL guard, grounding policy, shaping, formatting,
verified headline, about-data card) — these are byte-identical to the retired
linear ``dataset_expert_agent.py``, so coverage is preserved on the ACTIVE file.
Anything touching LLM Mesh / SQLExecutor2 must be validated on the DSS instance.

Run from the repo root:
    python3 -m unittest discover -s dataiku-agents/tests -v
"""

import importlib.util
import os
import sys
import types
import unittest


def _install_stubs():
    dataiku_mod = types.ModuleType("dataiku")
    dataiku_mod.api_client = lambda: None
    dataiku_mod.Dataset = lambda *a, **k: None
    dataiku_mod.SQLExecutor2 = lambda *a, **k: None

    llm_pkg = types.ModuleType("dataiku.llm")
    llm_python = types.ModuleType("dataiku.llm.python")

    class BaseLLM(object):
        pass

    llm_python.BaseLLM = BaseLLM
    llm_pkg.python = llm_python
    dataiku_mod.llm = llm_pkg

    sys.modules.setdefault("dataiku", dataiku_mod)
    sys.modules.setdefault("dataiku.llm", llm_pkg)
    sys.modules.setdefault("dataiku.llm.python", llm_python)

    # langgraph stub (import surface only; the graph is never run in these tests).
    lg = types.ModuleType("langgraph")
    lg_graph = types.ModuleType("langgraph.graph")

    class _Sentinel(str):
        pass

    lg_graph.START = _Sentinel("__start__")
    lg_graph.END = _Sentinel("__end__")

    class _StateGraph(object):
        def __init__(self, *a, **k):
            pass

        def add_node(self, *a, **k):
            pass

        def add_edge(self, *a, **k):
            pass

        def add_conditional_edges(self, *a, **k):
            pass

        def compile(self, *a, **k):
            return self

        def stream(self, *a, **k):
            return iter(())

    lg_graph.StateGraph = _StateGraph
    lg_config = types.ModuleType("langgraph.config")
    lg_config.get_stream_writer = lambda: (lambda *a, **k: None)
    lg.graph = lg_graph
    lg.config = lg_config
    sys.modules.setdefault("langgraph", lg)
    sys.modules.setdefault("langgraph.graph", lg_graph)
    sys.modules.setdefault("langgraph.config", lg_config)


_install_stubs()

_AGENT_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "agents", "SalesDrive_revenue_expert.py"))
_SPEC = importlib.util.spec_from_file_location("dataset_expert_under_test",
                                               _AGENT_PATH)
dx = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dx)

TABLE = '"public"."SALES_DEMO"'
NBSP = " "


def make_profile():
    """Synthetic profile fixture (structure identical to the real contract,
    values invented — no business data in the repo)."""
    dataset_payload = {
        "profile_version": 1, "dataset_name": "SALES_DEMO",
        "row_count": 170000,
        "description_en": "Demo revenue lines by month, customer and product",
        "description_fr": "Lignes de revenus démo par mois, client et produit",
        "grain": "one row = revenue per month/customer/product/phase",
        "default_metric": "revenue",
        "metrics": [{"name": "revenue", "agg": "SUM", "column": "amount_eur",
                     "format": "amount", "unit": "EUR",
                     "label_fr": "Revenu total", "label_en": "Total revenue",
                     "description": "Sum of amount_eur"}],
        "scenario": {"column": "Phase",
                     "values": ["ACTUALS", "BUDGET", "FORECAST"],
                     "default_values": ["ACTUALS"]},
        "time": {"column": "year_month", "format": "yyyy_mm_dd_str",
                 "min": "2024-01-01", "max": "2026-06-01"},
        "notes": [],
    }
    columns = {
        "Phase": {"name": "Phase", "dss_type": "string", "role": "scenario",
                  "groupable": True, "is_enum": True, "distinct_count": 3,
                  "values": [{"v": "ACTUALS", "n": 100}, {"v": "BUDGET", "n": 50},
                             {"v": "FORECAST", "n": 20}],
                  "indexed": False, "synonyms": ["scenario"], "samples": []},
        "year_month": {"name": "year_month", "dss_type": "string",
                       "role": "time", "groupable": True, "is_enum": False,
                       "distinct_count": 30, "indexed": False,
                       "synonyms": ["mois", "month"], "samples": ["2026-01-01"]},
        "customer_id": {"name": "customer_id", "dss_type": "string",
                        "role": "identifier", "groupable": True,
                        "is_enum": False, "distinct_count": 1200,
                        "display_column": "customer_name", "indexed": True,
                        "synonyms": ["client", "customer"], "samples": []},
        "customer_name": {"name": "customer_name", "dss_type": "string",
                          "role": "dimension", "groupable": True,
                          "is_enum": False, "distinct_count": 1190,
                          "indexed": True, "synonyms": [], "samples": []},
        "Product": {"name": "Product", "dss_type": "string",
                    "role": "dimension", "groupable": True, "is_enum": False,
                    "distinct_count": 80, "indexed": True,
                    "ambiguity_priority": 1, "synonyms": ["produit"],
                    "samples": []},
        "Solution": {"name": "Solution", "dss_type": "string",
                     "role": "dimension", "groupable": True, "is_enum": False,
                     "distinct_count": 40, "indexed": True, "synonyms": [],
                     "samples": []},
        "amount_eur": {"name": "amount_eur", "dss_type": "double",
                       "role": "measure", "groupable": False,
                       "is_enum": False, "distinct_count": 9999,
                       "indexed": False, "synonyms": ["montant"], "samples": []},
        "comment": {"name": "comment", "dss_type": "string",
                    "role": "free_text", "groupable": False, "is_enum": False,
                    "distinct_count": 5000, "indexed": False, "synonyms": [],
                    "samples": []},
    }
    return dx.Profile(dataset_payload, columns)


def make_u(**kw):
    u = {"scope": "data", "language": "fr", "instruction": "q",
         "intent": "total", "metric": "revenue", "scenarios": [],
         "period": {"mode": "all_available"}, "periods": [],
         "group_by": None, "list_column": None, "top_n": None,
         "order": "desc", "terms": [], "clarification": ""}
    u.update(kw)
    return u


P = make_profile()


# ==========================================================================
# Profile parsing + accessors
# ==========================================================================
class TestProfile(unittest.TestCase):

    def test_parse_profile_rows(self):
        import json
        rows = [{"key": "__dataset__", "payload": json.dumps(P.raw)},
                {"key": "Phase", "payload": json.dumps(P.columns["Phase"])},
                {"key": "bad", "payload": "{not json"}]
        prof = dx.parse_profile_rows(rows)
        self.assertIsNotNone(prof)
        self.assertEqual(prof.dataset_name, "SALES_DEMO")
        self.assertIn("Phase", prof.columns)
        self.assertNotIn("bad", prof.columns)

    def test_parse_profile_rows_missing_dataset_row(self):
        self.assertIsNone(dx.parse_profile_rows(
            [{"key": "Phase", "payload": "{}"}]))
        self.assertIsNone(dx.parse_profile_rows([]))

    def test_accessors(self):
        self.assertEqual(P.default_metric["name"], "revenue")
        self.assertEqual(P.scenario["column"], "Phase")
        self.assertEqual(P.time["format"], "yyyy_mm_dd_str")
        self.assertIn("customer_id", P.groupable_columns())
        self.assertNotIn("amount_eur", P.groupable_columns())
        self.assertNotIn("comment", P.groupable_columns())
        self.assertEqual(sorted(P.indexed_columns()),
                         ["Product", "Solution", "customer_id", "customer_name"])

    def test_match_column(self):
        self.assertEqual(P.match_column("Product"), "Product")
        self.assertEqual(P.match_column("produit"), "Product")
        self.assertEqual(P.match_column("client"), "customer_id")
        self.assertEqual(P.match_column("CUSTOMER_NAME"), "customer_name")
        self.assertEqual(P.match_column("customer name"), "customer_name")
        self.assertIsNone(P.match_column("ghost"))
        self.assertIsNone(P.match_column(""))

    def test_column_priority_explicit_beats_distinct(self):
        # Product has ambiguity_priority=1 -> (0, 1) < any (1, -n)
        self.assertLess(P.column_priority("Product"),
                        P.column_priority("customer_name"))
        # Without explicit priority, larger distinct_count (more specific) wins.
        self.assertLess(P.column_priority("customer_name"),
                        P.column_priority("Solution"))


# ==========================================================================
# validate_understanding
# ==========================================================================
class TestValidateUnderstanding(unittest.TestCase):

    def test_rejects_unusable(self):
        self.assertIsNone(dx.validate_understanding(None, P, "q"))
        self.assertIsNone(dx.validate_understanding({"scope": "??"}, P, "q"))
        self.assertIsNone(dx.validate_understanding({}, P, "q"))

    def test_out_of_scope_short_circuit(self):
        u = dx.validate_understanding({"scope": "out_of_scope",
                                       "language": "en"}, P, "q")
        self.assertEqual(u["scope"], "out_of_scope")
        self.assertEqual(u["language"], "en")

    def test_defaults_and_degradations(self):
        u = dx.validate_understanding({"scope": "data", "language": "fr",
                                       "intent": "alien",
                                       "metric": "ghost_metric",
                                       "scenarios": ["GHOST", "BUDGET"],
                                       "top_n": 999}, P, "q")
        self.assertEqual(u["intent"], "custom")
        self.assertEqual(u["metric"], "revenue")        # default metric
        self.assertEqual(u["scenarios"], ["BUDGET"])    # unknown dropped
        self.assertIsNone(u["top_n"])                   # out of range

    def test_top_n_defaults_to_10(self):
        u = dx.validate_understanding({"scope": "data", "language": "fr",
                                       "intent": "top_n",
                                       "group_by": "customer_id"}, P, "q")
        self.assertEqual(u["top_n"], 10)
        self.assertEqual(u["group_by"], "customer_id")

    def test_group_by_synonym_mapping(self):
        u = dx.validate_understanding({"scope": "data", "language": "fr",
                                       "intent": "breakdown",
                                       "group_by": "produit"}, P, "q")
        self.assertEqual(u["group_by"], "Product")

    def test_breakdown_without_axis_degrades_to_custom(self):
        u = dx.validate_understanding({"scope": "data", "language": "fr",
                                       "intent": "breakdown"}, P, "q")
        self.assertEqual(u["intent"], "custom")

    def test_compare_scenarios_prepends_default(self):
        u = dx.validate_understanding({"scope": "data", "language": "fr",
                                       "intent": "compare_scenarios",
                                       "scenarios": ["BUDGET"]}, P, "q")
        self.assertEqual(u["scenarios"], ["ACTUALS", "BUDGET"])
        self.assertEqual(u["intent"], "compare_scenarios")

    def test_compare_periods_needs_two(self):
        u = dx.validate_understanding({"scope": "data", "language": "fr",
                                       "intent": "compare_periods",
                                       "periods": [{"start": "2025-01-01",
                                                    "end": "2025-12-31"}]},
                                      P, "q")
        self.assertEqual(u["intent"], "custom")
        u = dx.validate_understanding({"scope": "data", "language": "fr",
                                       "intent": "compare_periods",
                                       "periods": [
                                           {"start": "2025-01-01", "end": "2025-12-31",
                                            "label": "2025"},
                                           {"start": "2026-01-01", "end": "2026-12-31",
                                            "label": "2026"}]}, P, "q")
        self.assertEqual(len(u["periods"]), 2)

    def test_list_values_falls_back_to_group_by(self):
        u = dx.validate_understanding({"scope": "data", "language": "fr",
                                       "intent": "list_values",
                                       "group_by": "Product"}, P, "q")
        self.assertEqual(u["list_column"], "Product")

    def test_terms_stopwords_are_profile_driven(self):
        u = dx.validate_understanding({"scope": "data", "language": "fr",
                                       "intent": "total",
                                       "terms": ["ACTUALS", "revenu total",
                                                 "produit", "HALYS",
                                                 "montant", "halys"]}, P, "q")
        # scenario value, metric label, column synonym -> dropped; dedupe norm
        self.assertEqual(u["terms"], ["HALYS"])

    def test_qualified_term_survives(self):
        u = dx.validate_understanding({"scope": "data", "language": "fr",
                                       "intent": "total",
                                       "terms": ["IPL (Product)"]}, P, "q")
        self.assertEqual(u["terms"], ["IPL (Product)"])

    def test_invalid_period_degrades(self):
        u = dx.validate_understanding({"scope": "data", "language": "fr",
                                       "period": {"mode": "explicit",
                                                  "start": "garbage",
                                                  "end": "2026-12-31"}}, P, "q")
        self.assertEqual(u["period"], {"mode": "all_available"})


# ==========================================================================
# Grounding: qualified terms, ranking, ambiguity policy, clarifications
# ==========================================================================
class TestGrounding(unittest.TestCase):

    def test_parse_qualified_term(self):
        self.assertEqual(dx.parse_qualified_term("IPL (Product)", P),
                         ("Product", "IPL"))
        self.assertEqual(dx.parse_qualified_term("IPL [produit]", P),
                         ("Product", "IPL"))
        self.assertIsNone(dx.parse_qualified_term("IPL (Ghost)", P))
        self.assertIsNone(dx.parse_qualified_term("just a value", P))

    def test_rank_candidates(self):
        rows = [{"column_name": "customer_name", "value": "HALYS",
                 "value_norm": "halys", "occurrences": 50},
                {"column_name": "Product", "value": "Halys Premium",
                 "value_norm": "halys premium", "occurrences": 10}]
        cands = dx.rank_candidates("halys", rows)
        self.assertEqual(cands[0]["target_value"], "HALYS")
        self.assertGreaterEqual(cands[0]["score"], cands[1]["score"])

    def test_refine_ambiguous_exact_eviction(self):
        cands = [{"target_column": "Product", "target_value": "IPL",
                  "display_value": "IPL"},
                 {"target_column": "Product", "target_value": "IPL +",
                  "display_value": "IPL +"}]
        verdict, data = dx.refine_ambiguous(P, "IPL", cands)
        self.assertEqual(verdict, "resolved")
        self.assertEqual(data["target_value"], "IPL")

    def test_refine_ambiguous_preferred_column(self):
        cands = [{"target_column": "Product", "target_value": "IPL",
                  "display_value": "IPL"},
                 {"target_column": "Solution", "target_value": "IPL",
                  "display_value": "IPL"}]
        verdict, data = dx.refine_ambiguous(P, "ipl", cands,
                                            preferred_column="Solution")
        self.assertEqual(verdict, "resolved")
        self.assertEqual(data["target_column"], "Solution")

    def test_refine_ambiguous_priority_pick_same_value(self):
        cands = [{"target_column": "Solution", "target_value": "IPL",
                  "display_value": "IPL"},
                 {"target_column": "Product", "target_value": "IPL",
                  "display_value": "IPL"}]
        verdict, data = dx.refine_ambiguous(P, "ipl", cands)
        self.assertEqual(verdict, "resolved")
        self.assertEqual(data["target_column"], "Product")   # explicit priority

    def test_refine_ambiguous_real_business_choice_stays(self):
        cands = [{"target_column": "Product", "target_value": "IPL",
                  "display_value": "IPL"},
                 {"target_column": "Product", "target_value": "IPL +",
                  "display_value": "IPL +"}]
        verdict, data = dx.refine_ambiguous(P, "ipl machin", cands)
        self.assertEqual(verdict, "ambiguous")
        self.assertEqual(len(data), 2)

    def test_build_filter_clauses_dedup(self):
        res = [{"status": "resolved", "target_column": "Product",
                "target_value": "IPL"},
               {"status": "resolved", "target_column": "Product",
                "target_value": "IPL"},
               {"status": "unresolved"}]
        self.assertEqual(dx.build_filter_clauses(res),
                         [{"column": "Product", "value": "IPL"}])

    def test_build_clarification_teaches_echo_format(self):
        res = [{"raw_value": "ipl", "status": "ambiguous", "candidates": [
            {"target_column": "Product", "target_value": "IPL",
             "display_value": "IPL"},
            {"target_column": "Product", "target_value": "IPL +",
             "display_value": "IPL +"}]}]
        text = dx.build_clarification(res, "fr")
        self.assertIn("IPL (Product)", text)
        self.assertIn("IPL +", text)
        self.assertIn("Répondez par exemple", text)

    def test_build_clarification_unresolved_hint(self):
        res = [{"raw_value": "halis", "status": "unresolved",
                "best_candidate": {"display_value": "HALYS"}}]
        text = dx.build_clarification(res, "en")
        self.assertIn("halis", text)
        self.assertIn("HALYS", text)


# ==========================================================================
# SQL building blocks
# ==========================================================================
class TestSqlPrimitives(unittest.TestCase):

    def test_qident(self):
        self.assertEqual(dx.qident("Product"), '"Product"')
        self.assertEqual(dx.qident("year_month"), '"year_month"')
        with self.assertRaises(ValueError):
            dx.qident('x"; DROP TABLE t; --')
        with self.assertRaises(ValueError):
            dx.qident("1starts_with_digit")

    def test_metric_expr(self):
        self.assertEqual(dx.metric_expr({"agg": "SUM", "column": "amount_eur"}),
                         'SUM("amount_eur")')
        self.assertEqual(dx.metric_expr({"agg": "COUNT", "column": None}),
                         "COUNT(*)")
        self.assertEqual(dx.metric_expr({"agg": "COUNT_DISTINCT",
                                         "column": "customer_id"}),
                         'COUNT(DISTINCT "customer_id")')

    def test_period_predicate_per_format(self):
        f = dx.period_predicate
        self.assertEqual(
            f({"column": "d", "format": "date"}, "2025-01-01", "2025-12-31"),
            "(\"d\" >= DATE '2025-01-01' AND \"d\" < (DATE '2025-12-31' + INTERVAL '1 day'))")
        self.assertEqual(
            f({"column": "ym", "format": "yyyy_mm_dd_str"}, "2025-01-01", "2025-12-31"),
            "(LEFT(CAST(\"ym\" AS text), 10) >= '2025-01-01'"
            " AND LEFT(CAST(\"ym\" AS text), 10) <= '2025-12-31')")
        self.assertEqual(
            f({"column": "ym", "format": "yyyy_mm_str"}, "2025-01-01", "2025-12-31"),
            "(LEFT(CAST(\"ym\" AS text), 7) >= '2025-01'"
            " AND LEFT(CAST(\"ym\" AS text), 7) <= '2025-12')")
        self.assertEqual(
            f({"column": "ym", "format": "yyyymm_int"}, "2025-01-01", "2025-12-31"),
            '("ym" >= 202501 AND "ym" <= 202512)')
        self.assertEqual(
            f({"column": "y", "format": "year_int"}, "2025-01-01", "2026-12-31"),
            '("y" >= 2025 AND "y" <= 2026)')
        with self.assertRaises(ValueError):
            f({"column": "x", "format": "alien"}, "2025-01-01", "2025-12-31")

    def test_month_bucket_expr(self):
        self.assertEqual(dx.month_bucket_expr({"column": "d", "format": "date"}),
                         "TO_CHAR(\"d\", 'YYYY-MM')")
        self.assertEqual(dx.month_bucket_expr({"column": "ym",
                                               "format": "yyyy_mm_dd_str"}),
                         'LEFT(CAST("ym" AS text), 7)')
        self.assertEqual(dx.month_bucket_expr({"column": "ym",
                                               "format": "yyyymm_int"}), '"ym"')


class TestBuildSql(unittest.TestCase):

    def test_total_applies_default_scenario(self):
        sql, meta = dx.build_sql(make_u(), P, [], TABLE)
        self.assertEqual(sql,
                         'SELECT SUM("amount_eur") AS "revenue" FROM %s'
                         ' WHERE "Phase" IN (\'ACTUALS\') LIMIT 500' % TABLE)
        self.assertEqual(meta["format_map"]["revenue"], "amount")
        self.assertEqual(meta["unit"], "EUR")

    def test_total_with_period_and_filters(self):
        u = make_u(period={"mode": "explicit", "start": "2025-01-01",
                           "end": "2025-12-31", "label": "2025"})
        sql, _ = dx.build_sql(u, P, [{"column": "customer_name",
                                      "value": "HALYS"}], TABLE)
        self.assertIn('"Phase" IN (\'ACTUALS\')', sql)
        self.assertIn("LEFT(CAST(\"year_month\" AS text), 10) >= '2025-01-01'", sql)
        self.assertIn('"customer_name" = \'HALYS\'', sql)

    def test_literal_escaping(self):
        u = make_u()
        sql, _ = dx.build_sql(u, P, [{"column": "customer_name",
                                      "value": "L'Operateur"}], TABLE)
        self.assertIn("'L''Operateur'", sql)

    def test_top_n_with_display_pair(self):
        u = make_u(intent="top_n", group_by="customer_id", top_n=5)
        sql, _ = dx.build_sql(u, P, [], TABLE)
        self.assertIn('SELECT "customer_id", MAX("customer_name") AS "customer_name"', sql)
        self.assertIn('GROUP BY "customer_id"', sql)
        self.assertIn('ORDER BY "revenue" DESC LIMIT 5', sql)

    def test_bottom_ranking_asc(self):
        u = make_u(intent="top_n", group_by="Product", top_n=3, order="asc")
        sql, _ = dx.build_sql(u, P, [], TABLE)
        self.assertIn('ORDER BY "revenue" ASC LIMIT 3', sql)

    def test_share_of_total(self):
        u = make_u(intent="share_of_total", group_by="Product", top_n=20)
        sql, meta = dx.build_sql(u, P, [], TABLE)
        self.assertIn('SUM(SUM("amount_eur")) OVER ()', sql)
        self.assertIn('AS "share_pct"', sql)
        self.assertEqual(meta["format_map"]["share_pct"], "percent")

    def test_compare_scenarios_pivot_with_delta(self):
        u = make_u(intent="compare_scenarios", scenarios=["ACTUALS", "BUDGET"])
        sql, meta = dx.build_sql(u, P, [], TABLE)
        self.assertIn("SUM(CASE WHEN \"Phase\" = 'ACTUALS' THEN \"amount_eur\" ELSE 0 END) AS \"ACTUALS\"", sql)
        self.assertIn('AS "delta"', sql)
        self.assertIn('AS "delta_pct"', sql)
        self.assertIn("\"Phase\" IN ('ACTUALS', 'BUDGET')", sql)
        self.assertEqual(meta["format_map"]["delta_pct"], "percent")
        self.assertEqual(meta["format_map"]["ACTUALS"], "amount")

    def test_compare_scenarios_grouped(self):
        u = make_u(intent="compare_scenarios", scenarios=["ACTUALS", "BUDGET"],
                   group_by="customer_id", top_n=10)
        sql, _ = dx.build_sql(u, P, [], TABLE)
        self.assertIn('GROUP BY "customer_id"', sql)
        self.assertIn('ORDER BY "ACTUALS" DESC LIMIT 10', sql)

    def test_compare_periods_pivot(self):
        u = make_u(intent="compare_periods",
                   periods=[{"start": "2025-01-01", "end": "2025-12-31",
                             "label": "2025"},
                            {"start": "2026-01-01", "end": "2026-12-31",
                             "label": "2026"}])
        sql, meta = dx.build_sql(u, P, [], TABLE)
        self.assertIn('AS "2025"', sql)
        self.assertIn('AS "2026"', sql)
        self.assertIn('AS "delta"', sql)
        self.assertIn(" OR ", sql)
        self.assertIn("\"Phase\" IN ('ACTUALS')", sql)

    def test_trend_monthly(self):
        u = make_u(intent="trend")
        sql, _ = dx.build_sql(u, P, [], TABLE)
        self.assertIn('SELECT LEFT(CAST("year_month" AS text), 7) AS "month"', sql)
        self.assertIn("GROUP BY 1 ORDER BY 1", sql)

    def test_list_values_ignores_scenario(self):
        u = make_u(intent="list_values", list_column="Product")
        sql, _ = dx.build_sql(u, P, [], TABLE)
        self.assertEqual(sql, 'SELECT DISTINCT "Product" FROM %s'
                              ' ORDER BY 1 LIMIT 200' % TABLE)

    def test_count_distinct(self):
        u = make_u(intent="count_distinct", list_column="customer_id")
        sql, meta = dx.build_sql(u, P, [], TABLE)
        self.assertIn('COUNT(DISTINCT "customer_id") AS "count"', sql)
        self.assertEqual(meta["format_map"]["count"], "count")

    def test_compare_scenarios_without_scenario_column_raises(self):
        no_scen = dx.Profile(dict(P.raw, scenario=None), P.columns)
        u = make_u(intent="compare_scenarios", scenarios=["A", "B"])
        with self.assertRaises(ValueError):
            dx.build_sql(u, no_scen, [], TABLE)

    def test_custom_intent_has_no_builder(self):
        with self.assertRaises(ValueError):
            dx.build_sql(make_u(intent="custom"), P, [], TABLE)


# ==========================================================================
# Custom SQL guard
# ==========================================================================
class TestGuardCustomSql(unittest.TestCase):

    def test_valid_select_gets_limit(self):
        sql, reason = dx.guard_custom_sql(
            'SELECT "Product", SUM("amount_eur") FROM %s GROUP BY 1' % TABLE,
            TABLE)
        self.assertIsNone(reason)
        self.assertTrue(sql.endswith("LIMIT 500"))

    def test_fences_and_comments_stripped(self):
        sql, reason = dx.guard_custom_sql(
            "```sql\nSELECT 1 FROM %s -- comment\n```" % TABLE, TABLE)
        self.assertIsNone(reason)
        self.assertNotIn("```", sql)
        self.assertNotIn("--", sql)

    def test_limit_capped(self):
        sql, reason = dx.guard_custom_sql(
            "SELECT 1 FROM %s LIMIT 99999" % TABLE, TABLE)
        self.assertIsNone(reason)
        self.assertTrue(sql.endswith("LIMIT 500"))

    def test_existing_small_limit_kept(self):
        sql, reason = dx.guard_custom_sql(
            "SELECT 1 FROM %s LIMIT 7" % TABLE, TABLE)
        self.assertIsNone(reason)
        self.assertTrue(sql.endswith("LIMIT 7"))

    def test_rejects_dml_and_ddl(self):
        for bad in ("DELETE FROM %s" % TABLE,
                    "DROP TABLE %s" % TABLE,
                    "SELECT 1 FROM %s; DELETE FROM x" % TABLE,
                    "UPDATE %s SET a=1" % TABLE,
                    "SELECT * INTO copy FROM %s" % TABLE,
                    "set lock_timeout='1s'"):
            sql, reason = dx.guard_custom_sql(bad, TABLE)
            self.assertIsNone(sql, msg=bad)

    def test_rejects_other_table(self):
        sql, reason = dx.guard_custom_sql(
            'SELECT * FROM "public"."OTHER_TABLE"', TABLE)
        self.assertIsNone(sql)
        self.assertTrue(reason.startswith("table_not_allowed"))
        sql, reason = dx.guard_custom_sql(
            'SELECT * FROM %s JOIN "secrets" USING (id)' % TABLE, TABLE)
        self.assertIsNone(sql)

    def test_accepts_table_spelling_variants(self):
        for spelling in (TABLE, '"SALES_DEMO"', "SALES_DEMO", "sales_demo",
                         "public.SALES_DEMO"):
            sql, reason = dx.guard_custom_sql(
                "SELECT 1 FROM %s" % spelling, TABLE)
            self.assertIsNotNone(sql, msg=spelling)

    def test_accepts_cte_and_self_join_and_subquery(self):
        q = ('WITH base AS (SELECT * FROM %s) '
             "SELECT a.* FROM base a JOIN base b ON a.x = b.x" % TABLE)
        sql, reason = dx.guard_custom_sql(q, TABLE)
        self.assertIsNone(reason)
        q2 = "SELECT * FROM (SELECT 1 FROM %s) sub" % TABLE
        sql2, reason2 = dx.guard_custom_sql(q2, TABLE)
        self.assertIsNone(reason2)

    def test_rejects_non_select(self):
        sql, reason = dx.guard_custom_sql("EXPLAIN SELECT 1", TABLE)
        self.assertIsNone(sql)
        sql, reason = dx.guard_custom_sql("", TABLE)
        self.assertEqual(reason, "empty")


# ==========================================================================
# Result shaping + rendering
# ==========================================================================
class TestShapingAndRendering(unittest.TestCase):

    def test_shape_result_caps_rows(self):
        cols = ["a", "b"]
        rows = [(i, "x" * 500) for i in range(60)]
        result = dx.shape_result(cols, rows)
        self.assertEqual(len(result["rows"]), 50)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["rows"][0][1]), 256)

    def test_shape_result_small_is_untruncated(self):
        result = dx.shape_result(["a"], [(1,), (2,)])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["rows"], [[1], [2]])

    def test_format_number(self):
        self.assertEqual(dx.format_number(1234567, "amount", "EUR"),
                         "1" + NBSP + "234" + NBSP + "567" + NBSP + "EUR")
        self.assertEqual(dx.format_number(12.345, "percent"),
                         "12.3" + NBSP + "%")
        self.assertEqual(dx.format_number(42, "count"), "42")
        self.assertEqual(dx.format_number(3.14159, "number"), "3.14")

    def test_format_cell_uses_fmt_map_then_heuristics(self):
        self.assertEqual(dx.format_cell(1000, "revenue",
                                        {"revenue": "amount"}, P, "EUR"),
                         "1" + NBSP + "000" + NBSP + "EUR")
        self.assertEqual(dx.format_cell(12.3, "share_pct", {}, P),
                         "12.3" + NBSP + "%")
        self.assertEqual(dx.format_cell("HALYS", "customer_name", {}, P),
                         "HALYS")

    def test_build_table_truncation_notes(self):
        result = {"columns": ["c"], "rows": [[i] for i in range(15)],
                  "truncated": True}
        table = dx.build_table(result, "fr", {}, P)
        self.assertIn("| c |", table)
        self.assertIn("3 ligne(s) supplémentaire(s)", table)
        self.assertIn("Résultat partiel", table)

    def test_fallback_headline_single_value(self):
        u = make_u(scenarios=["ACTUALS"],
                   period={"mode": "explicit", "start": "2025-01-01",
                           "end": "2025-12-31", "label": "2025"})
        result = {"columns": ["revenue"], "rows": [[1234567]],
                  "truncated": False}
        text = dx.build_fallback_headline(u, P, result, "fr",
                                          {"revenue": "amount"}, "EUR")
        self.assertIn("Revenu total", text)
        self.assertIn("ACTUALS, 2025", text)
        self.assertIn("1" + NBSP + "234" + NBSP + "567", text)

    def test_fallback_headline_multi_row_neutral(self):
        u = make_u()
        result = {"columns": ["a", "b"], "rows": [[1, 2], [3, 4]],
                  "truncated": False}
        text = dx.build_fallback_headline(u, P, result, "en", {}, None)
        self.assertIn("Here are the results", text)

    def test_verify_headline(self):
        result = {"columns": ["revenue"], "rows": [[1234567]],
                  "truncated": False}
        allowed = dx.allowed_number_set(result, ["question 2025"])
        self.assertTrue(dx.verify_headline(
            "Le revenu 2025 est de 1 234 567 EUR.", allowed))
        self.assertFalse(dx.verify_headline(
            "Le revenu 2025 est de 9 999 999 EUR.", allowed))
        self.assertFalse(dx.verify_headline("", allowed))


# ==========================================================================
# about_data + prompts + dataset card
# ==========================================================================
class TestKnowledgeSurfaces(unittest.TestCase):

    def test_about_answer_is_grounded(self):
        text = dx.build_about_answer(P, "fr")
        self.assertIn("SALES_DEMO", text)
        self.assertIn("Revenu total", text)
        self.assertIn("ACTUALS, BUDGET, FORECAST", text)
        self.assertIn("2024-01-01", text)
        self.assertIn("Product", text)
        self.assertIn("170" + NBSP + "000", text)

    def test_understand_prompt_contains_profile_facts(self):
        prompt = dx.build_understand_prompt(P, "2026-06-12")
        for token in ("SALES_DEMO", "revenue", "ACTUALS", "BUDGET",
                      "customer_id", "produit", "2026-06-12",
                      "VALUE (Column)", "about_data"):
            self.assertIn(token, prompt)

    def test_understand_schema_enums(self):
        schema = dx.build_understand_schema(P)
        self.assertEqual(schema["properties"]["scenarios"]["items"]["enum"],
                         ["ACTUALS", "BUDGET", "FORECAST"])
        self.assertIn("custom", schema["properties"]["intent"]["enum"])

    def test_dataset_card_contains_columns_and_metrics(self):
        card = dx.build_dataset_card(P, TABLE)
        self.assertIn(TABLE, card)
        self.assertIn('"Phase"', card)
        self.assertIn("'ACTUALS'", card)
        self.assertIn('revenue = SUM("amount_eur")', card)
        self.assertIn("yyyy_mm_dd_str", card)


# ==========================================================================
# Semantic-tool engine: question composer + tool-output extraction
# ==========================================================================
class TestSemanticEngine(unittest.TestCase):

    def test_default_engine_is_semantic_tool(self):
        self.assertEqual(dx.SQL_ENGINE, "semantic_tool")
        self.assertTrue(dx.FALLBACK_TO_DIRECT)

    def test_total_question_grounded_and_contextualized(self):
        u = make_u(instruction="CA de HALYS en 2025 ?",
                   scenarios=["ACTUALS"],
                   period={"mode": "explicit", "start": "2025-01-01",
                           "end": "2025-12-31", "label": "2025"})
        q = dx.build_semantic_question(
            u, P, [{"column": "customer_name", "value": "HALYS"}])
        self.assertIn('"CA de HALYS en 2025 ?"', q)        # the user question leads
        self.assertIn('revenue (SUM("amount_eur"))', q)
        self.assertIn("Phase is in: ACTUALS", q)
        self.assertIn("year_month between 2025-01-01 and 2025-12-31", q)
        self.assertIn("customer_name = 'HALYS'", q)
        self.assertIn("HELPER FINDINGS", q)        # grounded values are HINTS (L058)
        self.assertIn("read by another LLM", q)   # destination context

    def test_default_scenario_applied_when_unspecified(self):
        q = dx.build_semantic_question(make_u(), P, [])
        self.assertIn("Phase is in: ACTUALS", q)
        self.assertIn("do not apply any filter on year_month", q)

    def test_enumeration_groups_same_column_as_in(self):
        # 'budget for Roaming Hub, Roaming Sponsor, IPX' shape: 2 values on
        # one column + 1 on another -> IN per column + OR/one-row-per-item rule
        filters = [{"column": "Product", "value": "Roaming Hub"},
                   {"column": "Product", "value": "Roaming Sponsor"},
                   {"column": "Solution", "value": "IPX"}]
        q = dx.build_semantic_question(make_u(scenarios=["BUDGET"]), P, filters)
        self.assertIn("Product IN ('Roaming Hub', 'Roaming Sponsor')", q)
        self.assertIn("Solution = 'IPX'", q)
        self.assertNotIn("Product = 'Roaming Hub' AND", q)
        self.assertIn("ONE ROW PER ITEM", q)
        self.assertIn("Phase is in: BUDGET", q)

    def test_single_filter_has_no_enumeration_rule(self):
        q = dx.build_semantic_question(
            make_u(), P, [{"column": "Product", "value": "EVPL"}])
        self.assertNotIn("ONE ROW PER ITEM", q)

    def test_top_n_question_carries_display_rule(self):
        u = make_u(intent="top_n", group_by="customer_id", top_n=5)
        q = dx.build_semantic_question(u, P, [])
        self.assertIn("broken down by customer_id", q)
        self.assertIn("Group by customer_id ONLY", q)
        self.assertIn("MAX(customer_name)", q)
        self.assertIn("top 5", q)

    def test_compare_scenarios_question(self):
        u = make_u(intent="compare_scenarios", scenarios=["ACTUALS", "BUDGET"])
        q = dx.build_semantic_question(u, P, [])
        self.assertIn("ACTUALS and BUDGET", q)
        self.assertIn("delta", q)
        self.assertIn("Phase is in: ACTUALS, BUDGET", q)

    def test_list_values_and_custom_questions(self):
        u = make_u(intent="list_values", list_column="Product")
        self.assertIn("distinct values of Product",
                      dx.build_semantic_question(u, P, []))
        u = make_u(intent="custom", instruction="ratio onnet/offnet ?")
        q = dx.build_semantic_question(u, P, [])
        self.assertIn('"ratio onnet/offnet ?"', q)   # custom: the question leads
        self.assertNotIn("WHAT IS EXPECTED", q)

    def test_literal_escaping_in_filters(self):
        q = dx.build_semantic_question(
            make_u(), P, [{"column": "customer_name", "value": "L'Op"}])
        self.assertIn("customer_name = 'L''Op'", q)

    def test_extract_semantic_payload(self):
        raw = {"output": {
            "sql": "SELECT 1",
            "row_count": 2,
            "records": [{"diamond_id": "5373", "total_revenue": 1234.5},
                        {"diamond_id": "9999", "total_revenue": 10.0}],
            "answer": "Voici le résultat.",
            "nested": {"generated_sql": "SELECT 2"},
        }}
        p = dx.extract_semantic_payload(raw)
        self.assertEqual(p["sqls"], ["SELECT 1", "SELECT 2"])
        self.assertEqual(p["row_count"], 2)
        self.assertEqual(p["result"]["columns"], ["diamond_id", "total_revenue"])
        self.assertEqual(p["answer"], "Voici le résultat.")
        self.assertIn("sql", p["shape_keys"])

    def test_extract_semantic_payload_defensive(self):
        self.assertEqual(dx.extract_semantic_payload("nope")["sqls"], [])
        p = dx.extract_semantic_payload({"output": {"weird": True}})
        self.assertIsNone(p["result"])
        self.assertIsNone(p["row_count"])

    def test_agent_mode_answer_is_last_text_not_preamble(self):
        # Agent-mode transcript: the reasoning preamble must NOT be relayed
        # (live DSS failure 2026-06-12: "I'll start by exploring the schema...")
        raw = {"output": {"messages": [
            {"text": "I'll start by exploring the schema."},
            {"text": "Running a probe query..."},
            {"text": "Here is the Budget 2026 breakdown: 12345 EUR total."},
        ]}}
        p = dx.extract_semantic_payload(raw)
        self.assertIn("Budget 2026 breakdown", p["answer"])

    def test_agent_mode_priority_keys_beat_generic_text(self):
        raw = {"output": {"text": "preamble thinking",
                          "final": {"answer": "the real answer"}}}
        p = dx.extract_semantic_payload(raw)
        self.assertEqual(p["answer"], "the real answer")

    def test_agent_mode_last_tabular_wins(self):
        # probe-query records first, final result set last -> last wins
        raw = {"output": {"steps": [
            {"records": [{"probe": 1}]},
            {"records": [{"diamond_id": "5373", "total_revenue": 99.0}],
             "row_count": 1},
        ]}}
        p = dx.extract_semantic_payload(raw)
        self.assertEqual(p["result"]["columns"], ["diamond_id", "total_revenue"])
        self.assertEqual(p["row_count"], 1)

    def test_extract_tabular_node_list_of_lists(self):
        node = {"rows": [[1, "a"], [2, "b"]], "columns": ["n", "s"]}
        r = dx.extract_tabular_node(node)
        self.assertEqual(r["columns"], ["n", "s"])
        self.assertEqual(r["rows"], [[1, "a"], [2, "b"]])

    def test_pick_semantic_input_key(self):
        self.assertEqual(dx.pick_semantic_input_key(
            {"inputSchema": {"properties": {"question": {"type": "string"}}}}),
            "question")
        self.assertEqual(dx.pick_semantic_input_key(
            {"inputSchema": {"properties": {"nl_request": {"type": "string"}}}}),
            "nl_request")
        self.assertEqual(dx.pick_semantic_input_key({}), "question")
        self.assertEqual(dx.pick_semantic_input_key(None), "question")

    def test_semantic_alias_formats(self):
        # free-form aliases from the semantic tool get amount formatting when
        # the profile default metric is an amount
        self.assertEqual(dx.format_cell(1234567, "total_revenue", {}, P, "EUR"),
                         "1" + NBSP + "234" + NBSP + "567" + NBSP + "EUR")
        self.assertEqual(dx.format_cell(100, "ACTUALS", {}, P, "EUR"),
                         "100" + NBSP + "EUR")
        self.assertEqual(dx.format_cell(12.3, "share_pct", {}, P),
                         "12.3" + NBSP + "%")


# ==========================================================================
# Events contract
# ==========================================================================
class TestEvents(unittest.TestCase):

    def test_agent_result_shape(self):
        ev = dx._agent_result("ready", make_u(), sql_count=2, row_count=5,
                              attempts=2)
        data = ev["chunk"]["eventData"]
        self.assertEqual(ev["chunk"]["eventKind"], "AGENT_RESULT")
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["sqlCount"], 2)
        self.assertEqual(data["attempts"], 2)

    def test_block_and_tool_events(self):
        self.assertEqual(dx._block("run_sql")["chunk"]["eventData"]["blockId"],
                         "run_sql")
        self.assertEqual(
            dx._tool_start("dataset_sql_query")["chunk"]["eventData"]["toolName"],
            "dataset_sql_query")

    def test_known_ids_declared(self):
        self.assertIn("about_data", dx.KNOWN_BLOCK_IDS)
        self.assertIn("dataset_sql_query", dx.KNOWN_TOOL_NAMES)
        # The Dataset Lookup path declares its own block + tool ids.
        self.assertIn("lookup", dx.KNOWN_BLOCK_IDS)
        self.assertIn("dataset_lookup", dx.KNOWN_TOOL_NAMES)


# ==========================================================================
# Dataset Lookup — simple value retrieval (no SQL)
# ==========================================================================
class TestLiveSchemaAttributes(unittest.TestCase):
    def test_attribute_columns_include_live_only_columns(self):
        p = make_profile()
        p.live_columns = ["customer_name", "account_manager"]  # not in the profile
        cols = p.attribute_columns()
        self.assertIn("account_manager", cols)     # reachable though profile-absent
        self.assertIn("Product", cols)             # profiled column still present
        self.assertEqual(len(cols), len(set(cols)))  # de-duplicated

    def test_match_attribute_resolves_live_only_column(self):
        p = make_profile()
        p.live_columns = ["account_manager"]
        self.assertEqual(p.match_attribute("account manager"), "account_manager")
        self.assertEqual(p.match_attribute("Product"), "Product")
        self.assertIsNone(p.match_attribute("totally unknown col"))


class TestLookupFilter(unittest.TestCase):
    def test_single_equals(self):
        f = dx.build_lookup_filter([{"column": "customer_name", "value": "Acme"}])
        self.assertEqual(f, {"operator": "EQUALS", "column": "customer_name",
                             "value": "Acme"})

    def test_or_for_several_values_same_column(self):
        f = dx.build_lookup_filter([{"column": "c", "value": "A"},
                                    {"column": "c", "value": "B"}])
        self.assertEqual(f["operator"], "OR")
        self.assertEqual({c["value"] for c in f["clauses"]}, {"A", "B"})

    def test_and_across_columns(self):
        f = dx.build_lookup_filter([{"column": "c1", "value": "A"},
                                    {"column": "c2", "value": "B"}])
        self.assertEqual(f["operator"], "AND")
        self.assertEqual(len(f["clauses"]), 2)

    def test_empty_is_none(self):
        self.assertIsNone(dx.build_lookup_filter([]))
        self.assertIsNone(dx.build_lookup_filter([{"column": "", "value": None}]))

    def test_dedupes_repeated_value(self):
        f = dx.build_lookup_filter([{"column": "c", "value": "A"},
                                    {"column": "c", "value": "A"}])
        self.assertEqual(f, {"operator": "EQUALS", "column": "c", "value": "A"})


class TestExtractLookupRows(unittest.TestCase):
    def test_dict_rows_nested_output(self):
        raw = {"output": {"output": {"rows": [
            {"customer_name": "Acme", "account_manager": "Jo"}]}}}
        self.assertEqual(dx.extract_lookup_rows(raw)[0]["account_manager"], "Jo")

    def test_columns_and_list_rows(self):
        raw = {"output": {"columns": ["customer_name", "account_manager"],
                          "rows": [["Acme", "Jo"]]}}
        self.assertEqual(dx.extract_lookup_rows(raw),
                         [{"customer_name": "Acme", "account_manager": "Jo"}])

    def test_empty_and_none(self):
        self.assertEqual(dx.extract_lookup_rows({"output": {"rows": []}}), [])
        self.assertEqual(dx.extract_lookup_rows(None), [])

    def test_lookup_note_is_honest_and_lists_columns(self):
        flt = {"operator": "OR", "clauses": [
            {"operator": "EQUALS", "column": "customer_name", "value": "A"},
            {"operator": "EQUALS", "column": "customer_name", "value": "B"}]}
        note = dx.lookup_note(flt, ["account_manager"])
        self.assertIn("Dataset Lookup", note)
        self.assertIn("account_manager", note)
        self.assertIn("customer_name", note)


class TestLookupRows(unittest.TestCase):
    class _Tool(object):
        def __init__(self, rows):
            self._rows = rows
        def get_descriptor(self):
            return {}
        def run(self, payload):
            return {"output": {"output": {"rows": self._rows}}}

    class _Project(object):
        def __init__(self, tool):
            self._tool = tool
        def get_agent_tool(self, _id):
            return self._tool

    def test_projects_filter_cols_plus_attrs_and_dedupes(self):
        rows = [{"customer_name": "Acme", "account_manager": "Jo", "x": 1},
                {"customer_name": "Acme", "account_manager": "Jo", "x": 2},
                {"customer_name": "Beta", "account_manager": "Mi", "x": 3}]
        sa = dx.MyLLM()
        proj = self._Project(self._Tool(rows))
        filters = [{"column": "customer_name", "value": "Acme"},
                   {"column": "customer_name", "value": "Beta"}]
        flt = dx.build_lookup_filter(filters)
        res = sa._lookup_rows(proj, flt, filters, ["account_manager"])
        self.assertEqual(res["columns"], ["customer_name", "account_manager"])
        self.assertEqual(len(res["rows"]), 2)        # two Acme rows collapse to one

    def test_no_rows_returns_none(self):
        sa = dx.MyLLM()
        proj = self._Project(self._Tool([]))
        flt = dx.build_lookup_filter([{"column": "c", "value": "X"}])
        self.assertIsNone(sa._lookup_rows(proj, flt,
                                          [{"column": "c", "value": "X"}], []))


class TestLookupUnderstanding(unittest.TestCase):
    def test_lookup_intent_with_terms_and_attributes(self):
        p = make_profile()
        p.live_columns = ["customer_name", "account_manager"]
        parsed = {"scope": "data", "language": "fr", "intent": "lookup",
                  "terms": ["Acme"], "attributes": ["account manager"]}
        u = dx.validate_understanding(parsed, p, "qui gère Acme ?")
        self.assertEqual(u["intent"], "lookup")
        self.assertEqual(u["attributes"], ["account_manager"])
        self.assertEqual(u["terms"], ["Acme"])

    def test_lookup_without_terms_demotes_to_custom(self):
        p = make_profile()
        parsed = {"scope": "data", "language": "fr", "intent": "lookup",
                  "terms": [], "attributes": ["customer_name"]}
        u = dx.validate_understanding(parsed, p, "liste")
        self.assertEqual(u["intent"], "custom")

    def test_lookup_demotes_when_disabled(self):
        p = make_profile()
        parsed = {"scope": "data", "language": "fr", "intent": "lookup",
                  "terms": ["Acme"], "attributes": []}
        orig = dx.DATASET_LOOKUP_ENABLED
        dx.DATASET_LOOKUP_ENABLED = False
        try:
            u = dx.validate_understanding(parsed, p, "q")
            self.assertEqual(u["intent"], "custom")
        finally:
            dx.DATASET_LOOKUP_ENABLED = orig

    def test_lookup_headline_is_dedicated(self):
        p = make_profile()
        u = make_u(intent="lookup", attributes=["account_manager"])
        res = {"columns": ["customer_name", "account_manager"],
               "rows": [["Acme", "Jo"]]}
        headline = dx.build_fallback_headline(u, p, res, "fr", {}, None)
        self.assertEqual(headline, dx.HEADLINE_LOOKUP["fr"])


class TestModePropagation(unittest.TestCase):
    """The sub-agent mirrors the orchestrator's mode (eco=mini, medium=Gemini,
    high=Sonnet), read from the injected context the orchestrator builds."""

    def test_forced_mode_parses_injected_context(self):
        ctx = "MODE: high\nUSER LANGUAGE: fr — write any message…"
        self.assertEqual(dx.forced_mode(ctx), "high")
        self.assertEqual(dx.forced_mode("MODE: eco\n…"), "eco")

    def test_forced_mode_absent_is_none(self):
        self.assertIsNone(dx.forced_mode("USER LANGUAGE: fr — …"))
        self.assertIsNone(dx.forced_mode(""))

    def test_pick_subagent_llm_per_mode(self):
        self.assertEqual(dx.pick_subagent_llm("eco"), dx.GEMINI_FLASH_LITE_ID)
        self.assertEqual(dx.pick_subagent_llm("medium"), dx.GEMINI_FLASH_ID)
        self.assertEqual(dx.pick_subagent_llm("high"), dx.SONNET_ID)

    def test_semantic_tool_id_per_mode_defaults_shared(self):
        # All modes share the one tool id until a Sonnet-backed tool exists for high.
        self.assertEqual(dx.pick_semantic_tool_id("eco"), dx.SEMANTIC_TOOL_ID)
        self.assertEqual(dx.pick_semantic_tool_id("high"), dx.SEMANTIC_TOOL_ID)


class TestRunParallel(unittest.TestCase):
    """Bounded parallel helper for independent tool/query calls (instance-safe)."""

    def test_preserves_input_order(self):
        tasks = [(lambda n=n: n * 10) for n in range(6)]
        self.assertEqual(dx.run_parallel(tasks), [0, 10, 20, 30, 40, 50])

    def test_failure_becomes_none(self):
        def boom():
            raise ValueError("x")
        self.assertEqual(dx.run_parallel([lambda: 1, boom, lambda: 3]), [1, None, 3])

    def test_empty_and_single(self):
        self.assertEqual(dx.run_parallel([]), [])
        self.assertEqual(dx.run_parallel([lambda: 42]), [42])


class TestGuardSubqueryAndCommaJoin(unittest.TestCase):
    """The SQL guard must validate EVERY table source, not just the first."""

    def test_comma_join_unknown_table_rejected(self):
        sql, reason = dx.guard_custom_sql(
            'SELECT * FROM "SALES_DEMO", secret_table', TABLE)
        self.assertIsNone(sql)
        self.assertIn("table_not_allowed", reason)

    def test_subquery_inner_unknown_table_rejected(self):
        sql, reason = dx.guard_custom_sql(
            'SELECT * FROM (SELECT x FROM secret_t) s', TABLE)
        self.assertIsNone(sql)
        self.assertIn("table_not_allowed", reason)

    def test_legit_subquery_on_allowed_table_ok(self):
        sql, reason = dx.guard_custom_sql(
            'SELECT * FROM (SELECT * FROM "SALES_DEMO") s', TABLE)
        self.assertIsNotNone(sql)
        self.assertIsNone(reason)

    def test_spaceless_quoted_table_cannot_bypass(self):
        # `FROM"x"` (valid Postgres, no space) must NOT escape the table scan.
        sql, reason = dx.guard_custom_sql('SELECT * FROM"other_t"', TABLE)
        self.assertIsNone(sql)
        sql2, reason2 = dx.guard_custom_sql('SELECT * FROM"pg_user"', TABLE)
        self.assertIsNone(sql2)

    def test_system_catalogs_rejected(self):
        for q in ('SELECT * FROM information_schema.columns',
                  'SELECT * FROM pg_catalog.pg_tables',
                  'SELECT * FROM pg_user'):
            sql, reason = dx.guard_custom_sql(q, TABLE)
            self.assertIsNone(sql, q)

    def test_keyword_inside_string_literal_not_rejected(self):
        # 'a set of' contains the word "set" only INSIDE a literal -> must be allowed.
        sql, reason = dx.guard_custom_sql(
            "SELECT * FROM \"SALES_DEMO\" WHERE comment = 'a set of items'", TABLE)
        self.assertIsNotNone(sql)
        self.assertIsNone(reason)

    def test_with_recursive_cte_not_falsely_rejected(self):
        # `WITH RECURSIVE t AS (...)` must register `t` as a CTE so `FROM t` passes.
        sql, reason = dx.guard_custom_sql(
            'WITH RECURSIVE t AS (SELECT 1 AS n) SELECT * FROM t', TABLE)
        self.assertIsNotNone(sql, reason)
        self.assertIsNone(reason)

    def test_plain_cte_still_ok(self):
        sql, reason = dx.guard_custom_sql(
            'WITH t AS (SELECT * FROM "SALES_DEMO") SELECT * FROM t', TABLE)
        self.assertIsNotNone(sql, reason)


class TestLookupFilterAmbiguousColumns(unittest.TestCase):
    def test_alt_columns_become_or_over_columns(self):
        f = dx.build_lookup_filter([
            {"column": "Product", "value": "IP", "alt_columns": ["Solution"]}])
        self.assertEqual(f["operator"], "OR")
        cols = {c["column"] for c in f["clauses"]}
        self.assertEqual(cols, {"Product", "Solution"})
        self.assertTrue(all(c["value"] == "IP" for c in f["clauses"]))


class TestAmbiguityColumnPriority(unittest.TestCase):
    """A value spread across columns of different priority resolves to the dominant
    column (e.g. an account NAME over a group) + discloses the rest, rather than asking."""

    def test_dominant_column_resolves_and_discloses(self):
        p = make_profile()   # customer_name (1190 distinct) >> Solution (40)
        cands = [
            {"target_column": "customer_name", "target_value": "Algerie Telecom",
             "display_value": "Algerie Telecom", "score": 0.80, "occurrences": 50},
            {"target_column": "Solution", "target_value": "Algerie Sat",
             "display_value": "Algerie Sat", "score": 0.66, "occurrences": 9},
        ]
        verdict, data = dx.refine_ambiguous(p, "algerie", cands)
        self.assertEqual(verdict, "resolved")
        self.assertEqual(data["target_column"], "customer_name")   # name primes
        self.assertIn("Solution", data.get("alt_columns", []))      # alternative disclosed

    def test_true_within_column_tie_still_asks(self):
        p = make_profile()
        cands = [
            {"target_column": "customer_name", "target_value": "Orange France",
             "display_value": "Orange France", "score": 0.7, "occurrences": 5},
            {"target_column": "customer_name", "target_value": "Orange Spain",
             "display_value": "Orange Spain", "score": 0.7, "occurrences": 5},
        ]
        verdict, _ = dx.refine_ambiguous(p, "orange", cands)
        self.assertEqual(verdict, "ambiguous")


class TestColumnFormatCountGuard(unittest.TestCase):
    def test_total_customers_is_not_amount(self):
        p = make_profile()           # default metric is an amount
        self.assertNotEqual(dx._column_format("total_customers", {}, p), "amount")

    def test_total_revenue_still_amount(self):
        p = make_profile()
        self.assertEqual(dx._column_format("total_revenue", {}, p), "amount")


class TestIntentDegradationVisibility(unittest.TestCase):
    """A demoted intent must stay observable (original_intent) — not silently lost."""

    def test_original_intent_preserved_on_comparison_demotion(self):
        p = make_profile()
        # "compare" but only one scenario resolvable -> demoted to total, yet the
        # ORIGINAL classification is retained for transparency.
        parsed = {"scope": "data", "language": "fr", "intent": "compare_scenarios",
                  "scenarios": [], "terms": []}
        u = dx.validate_understanding(parsed, p, "compare X")
        self.assertEqual(u["original_intent"], "compare_scenarios")
        self.assertNotEqual(u["intent"], "compare_scenarios")  # demoted

    def test_original_intent_equals_intent_when_not_degraded(self):
        p = make_profile()
        parsed = {"scope": "data", "language": "fr", "intent": "total"}
        u = dx.validate_understanding(parsed, p, "total")
        self.assertEqual(u["original_intent"], "total")
        self.assertEqual(u["intent"], "total")


if __name__ == "__main__":
    unittest.main()
