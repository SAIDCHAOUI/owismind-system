"""DSS-free unit tests for salesdrive/salesdrive_agent.py (v2).

Same harness as orchestrator/tests: ``dataiku`` is stubbed in ``sys.modules``
BEFORE the Code Agent file is loaded via importlib. Only PURE functions are
tested (validation, semantic-question composition, clarification builders,
tool-output extraction, formatting, verified-headline gate). Anything touching
LLM Mesh / agent tools must be validated on the DSS instance.

Run from the repo root:
    python3 -m unittest discover -s salesdrive/tests -v
"""

import importlib.util
import os
import sys
import types
import unittest


def _install_dataiku_stub():
    dataiku_mod = types.ModuleType("dataiku")
    dataiku_mod.api_client = lambda: None

    llm_pkg = types.ModuleType("dataiku.llm")
    llm_python = types.ModuleType("dataiku.llm.python")

    class BaseLLM(object):
        """Empty stand-in for dataiku.llm.python.BaseLLM."""

    llm_python.BaseLLM = BaseLLM
    llm_pkg.python = llm_python
    dataiku_mod.llm = llm_pkg

    sys.modules.setdefault("dataiku", dataiku_mod)
    sys.modules.setdefault("dataiku.llm", llm_pkg)
    sys.modules.setdefault("dataiku.llm.python", llm_python)


_install_dataiku_stub()

_AGENT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "salesdrive_agent.py"))
_SPEC = importlib.util.spec_from_file_location("salesdrive_agent_under_test", _AGENT_PATH)
sd = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sd)

NBSP = " "
Q = "CA d'Algérie Télécom en 2025 ?"


def _valid(parsed, instruction=Q):
    return sd.validate_understanding(parsed, instruction)


# ==========================================================================
# validate_understanding
# ==========================================================================
class TestValidateUnderstanding(unittest.TestCase):

    def test_rejects_non_dict_and_unknown_scope(self):
        self.assertIsNone(_valid(None))
        self.assertIsNone(_valid("nope"))
        self.assertIsNone(_valid({"scope": "weird", "language": "fr"}))

    def test_out_of_scope_returns_defaults(self):
        u = _valid({"scope": "out_of_scope", "language": "en"})
        self.assertEqual(u["scope"], "out_of_scope")
        self.assertEqual(u["language"], "en")
        self.assertEqual(u["terms"], [])

    def test_language_defaults_to_fr(self):
        u = _valid({"scope": "revenue", "language": "de"})
        self.assertEqual(u["language"], "fr")

    def test_unknown_intent_degrades_to_generic(self):
        u = _valid({"scope": "revenue", "language": "fr", "intent": "magic"})
        self.assertEqual(u["intent"], "generic")

    def test_compare_phases_forces_actuals_budget(self):
        u = _valid({"scope": "revenue", "language": "fr",
                    "intent": "compare_phases", "phases": ["FORECAST"]})
        self.assertEqual(u["phases"], ["ACTUALS", "BUDGET"])

    def test_phases_filtered_deduped_defaulted(self):
        u = _valid({"scope": "revenue", "language": "fr", "intent": "total",
                    "phases": ["ACTUALS", "NOPE", "ACTUALS", "HLF"]})
        self.assertEqual(u["phases"], ["ACTUALS", "HLF"])
        u = _valid({"scope": "revenue", "language": "fr", "intent": "total"})
        self.assertEqual(u["phases"], ["ACTUALS"])

    def test_bad_period_degrades_to_all_available(self):
        for bad in (None, {"mode": "explicit"},
                    {"mode": "explicit", "start": "2025-1-1", "end": "2025-12-31"},
                    {"mode": "explicit", "start": "2025-12-31", "end": "2025-01-01"}):
            u = _valid({"scope": "revenue", "language": "fr", "period": bad})
            self.assertEqual(u["period"], {"mode": "all_available"})

    def test_explicit_period_kept_with_label(self):
        u = _valid({"scope": "revenue", "language": "fr",
                    "period": {"mode": "explicit", "start": "2025-01-01",
                               "end": "2025-12-31", "label": "2025"}})
        self.assertEqual(u["period"]["start"], "2025-01-01")
        self.assertEqual(u["period"]["label"], "2025")

    def test_compare_periods_needs_two_valid_periods(self):
        u = _valid({"scope": "revenue", "language": "fr", "intent": "compare_periods",
                    "periods": [{"start": "2024-01-01", "end": "2024-12-31"}]})
        self.assertEqual(u["intent"], "generic")
        u = _valid({"scope": "revenue", "language": "fr", "intent": "compare_periods",
                    "periods": [{"start": "2024-01-01", "end": "2024-12-31", "label": "2024"},
                                {"start": "2025-01-01", "end": "2025-12-31", "label": "2025"}]})
        self.assertEqual(u["intent"], "compare_periods")
        self.assertEqual(len(u["periods"]), 2)

    def test_top_n_defaults_and_clamps(self):
        u = _valid({"scope": "revenue", "language": "fr", "intent": "top_n"})
        self.assertEqual(u["top_n"], 10)
        self.assertEqual(u["group_by"], "customer")
        u = _valid({"scope": "revenue", "language": "fr", "intent": "top_n", "top_n": 999})
        self.assertEqual(u["top_n"], 10)

    def test_terms_stopwords_accents_dedupe_cap(self):
        u = _valid({"scope": "revenue", "language": "fr",
                    "terms": ["Algérie Télécom", "REVENUE", "Budget", "écart",
                              "algerie telecom", "", "EVPL"]})
        self.assertEqual(u["terms"], ["Algérie Télécom", "EVPL"])
        many = ["T%d" % i for i in range(20)]
        u = _valid({"scope": "revenue", "language": "fr", "terms": many})
        self.assertEqual(len(u["terms"]), sd.MAX_TERMS)

    def test_clarification_capped(self):
        u = _valid({"scope": "revenue", "language": "fr", "clarification": "x" * 900})
        self.assertEqual(len(u["clarification"]), 500)


# ==========================================================================
# build_semantic_question
# ==========================================================================
def _u(**over):
    base = {"scope": "revenue", "language": "fr", "instruction": Q,
            "intent": "total", "phases": ["ACTUALS"],
            "period": {"mode": "all_available"}, "periods": [],
            "group_by": None, "top_n": None, "terms": [], "clarification": ""}
    base.update(over)
    return base


class TestBuildSemanticQuestion(unittest.TestCase):

    GUARD = "Use the explicit filter values above. Do not fuzzy-match on Account_name."

    def test_total_all_available(self):
        sq = sd.build_semantic_question(_u(), [])
        self.assertIn("SUM(amount_eur)", sq)
        self.assertIn("Phase is in: ACTUALS.", sq)
        self.assertIn("Do not apply any filter on year_month.", sq)
        self.assertTrue(sq.endswith(self.GUARD))

    def test_total_explicit_period(self):
        sq = sd.build_semantic_question(_u(period={"mode": "explicit",
                                                   "start": "2025-01-01",
                                                   "end": "2025-12-31",
                                                   "label": "2025"}), [])
        self.assertIn("year_month between 2025-01-01 and 2025-12-31", sq)
        self.assertNotIn("Do not apply any filter", sq)

    def test_breakdown_customer_grouping_rule(self):
        sq = sd.build_semantic_question(_u(intent="breakdown", group_by="customer"), [])
        self.assertIn("broken down by diamond_id", sq)
        self.assertIn("Never group by Account_name.", sq)

    def test_top_n(self):
        sq = sd.build_semantic_question(_u(intent="top_n", group_by="product", top_n=5), [])
        self.assertIn("broken down by Product", sq)
        self.assertIn("keep only the top 5", sq)

    def test_compare_phases_frozen_text(self):
        sq = sd.build_semantic_question(_u(intent="compare_phases",
                                           phases=["ACTUALS", "BUDGET"]), [])
        self.assertIn("delta amount (ACTUALS minus BUDGET)", sq)
        self.assertIn("delta percentage versus BUDGET", sq)

    def test_compare_periods_embeds_periods(self):
        periods = [{"mode": "explicit", "start": "2024-01-01", "end": "2024-12-31", "label": "2024"},
                   {"mode": "explicit", "start": "2025-01-01", "end": "2025-12-31", "label": "2025"}]
        sq = sd.build_semantic_question(_u(intent="compare_periods", periods=periods), [])
        self.assertIn("2024: from 2024-01-01 to 2024-12-31", sq)
        self.assertIn("2025: from 2025-01-01 to 2025-12-31", sq)
        # period instruction is embedded per period, not appended globally
        self.assertNotIn("Do not apply any filter on year_month.", sq)

    def test_filters_appended_verbatim_with_and(self):
        clauses = ["diamond_id = 'D-123'", "distribution_type = 'Indirect_distribution/Resseler'"]
        sq = sd.build_semantic_question(_u(), clauses)
        self.assertIn("diamond_id = 'D-123' AND distribution_type = "
                      "'Indirect_distribution/Resseler'", sq)

    def test_generic_embeds_instruction(self):
        sq = sd.build_semantic_question(_u(intent="generic"), [])
        self.assertIn(Q, sq)
        self.assertTrue(sq.endswith(self.GUARD))


# ==========================================================================
# build_clarification / resolved_filters_summary
# ==========================================================================
class TestClarification(unittest.TestCase):

    def test_ambiguous_lists_candidates(self):
        res = [{"raw_value": "orange", "status": "ambiguous",
                "candidates": [
                    {"target_column": "Account_name", "target_value": "Orange Spain",
                     "display_value": "Orange Spain"},
                    {"target_column": "Parent_Group", "target_value": "ORANGE",
                     "display_value": "ORANGE"}]}]
        txt = sd.build_clarification(res, "fr")
        self.assertIn("« orange »", txt)
        self.assertIn("- Orange Spain (Account_name)", txt)
        self.assertIn("- ORANGE (Parent_Group)", txt)

    def test_unresolved_with_hint(self):
        res = [{"raw_value": "Telesta", "status": "unresolved",
                "best_candidate": {"target_column": "Account_name",
                                   "target_value": "Telesat Canada",
                                   "display_value": "Telesat Canada"}}]
        txt = sd.build_clarification(res, "en")
        self.assertIn("Telesta", txt)
        self.assertIn("Did you mean", txt)
        self.assertIn("Telesat Canada", txt)

    def test_resolved_summary(self):
        res = [{"raw_value": "EVPL", "status": "resolved", "target_column": "Product",
                "target_value": "EVPL", "display_value": "EVPL"},
               {"raw_value": "x", "status": "unresolved"}]
        out = sd.resolved_filters_summary(res)
        self.assertEqual(out, [{"column": "Product", "value": "EVPL",
                                "display": "EVPL", "raw": "EVPL"}])


# ==========================================================================
# disambiguation policy (the IPL loop fix)
# ==========================================================================
class TestDisambiguationPolicy(unittest.TestCase):

    IPL_CANDIDATES = [
        {"target_column": "Product", "target_value": "IPL", "display_value": "IPL"},
        {"target_column": "Solution", "target_value": "IPL", "display_value": "IPL"},
        {"target_column": "sirano_product", "target_value": "IPL", "display_value": "IPL"},
        {"target_column": "sirano_product", "target_value": "IPL +", "display_value": "IPL +"},
    ]

    def test_parse_qualified_term(self):
        self.assertEqual(sd.parse_qualified_term("IPL (Product)"), ("Product", "IPL"))
        self.assertEqual(sd.parse_qualified_term("ipl [sirano product]"),
                         ("sirano_product", "ipl"))
        self.assertEqual(sd.parse_qualified_term("'IPL' (Product)"), ("Product", "IPL"))
        self.assertIsNone(sd.parse_qualified_term("IPL"))
        self.assertIsNone(sd.parse_qualified_term("Vodafone (UK) Ltd"))
        self.assertIsNone(sd.parse_qualified_term("X (NotAColumn)"))
        self.assertIsNone(sd.parse_qualified_term(""))

    def test_exact_value_evicts_normalization_collisions(self):
        # 'IPL +' normalizes to 'ipl' in the catalog and pollutes the set —
        # strict exact-value preference removes it, column priority picks Product.
        verdict, data = sd.refine_ambiguous("IPL", self.IPL_CANDIDATES)
        self.assertEqual(verdict, "resolved")
        self.assertEqual(data["target_column"], "Product")
        self.assertEqual(data["target_value"], "IPL")

    def test_preferred_column_wins(self):
        verdict, data = sd.refine_ambiguous("IPL", self.IPL_CANDIDATES, "sirano_product")
        self.assertEqual(verdict, "resolved")
        self.assertEqual(data["target_column"], "sirano_product")
        self.assertEqual(data["target_value"], "IPL")

    def test_still_ambiguous_on_distinct_values(self):
        cands = [{"target_column": "Product", "target_value": "IPL"},
                 {"target_column": "sirano_product", "target_value": "IPL +"}]
        verdict, data = sd.refine_ambiguous("ipl plus", cands)
        self.assertEqual(verdict, "ambiguous")
        self.assertEqual(len(data), 2)

    def test_refine_resolutions_end_to_end(self):
        resolutions = [{"raw_value": "IPL", "status": "ambiguous",
                        "candidates": self.IPL_CANDIDATES}]
        refined = sd.refine_resolutions(resolutions, {"ipl": "Product"})
        self.assertEqual(refined[0]["status"], "resolved")
        self.assertEqual(refined[0]["method"], "ambiguity_policy")
        self.assertEqual(sd.build_filter_clauses(refined), ["Product = 'IPL'"])

    def test_build_filter_clauses_escapes_and_dedupes(self):
        rs = [{"status": "resolved", "target_column": "Account_name",
               "target_value": "L'Oréal"},
              {"status": "resolved", "target_column": "Account_name",
               "target_value": "L'Oréal"},
              {"status": "unresolved"}]
        self.assertEqual(sd.build_filter_clauses(rs), ["Account_name = 'L''Oréal'"])

    def test_clarification_includes_echo_hint_and_dedupes(self):
        res = [{"raw_value": "ipl plus", "status": "ambiguous",
                "candidates": [
                    {"target_column": "Product", "target_value": "IPL",
                     "display_value": "IPL"},
                    {"target_column": "Product", "target_value": "IPL",
                     "display_value": "IPL"},
                    {"target_column": "sirano_product", "target_value": "IPL +",
                     "display_value": "IPL +"}]}]
        txt = sd.build_clarification(res, "fr")
        self.assertIn("Répondez par exemple : « IPL (Product) »", txt)
        self.assertEqual(txt.count("- IPL (Product)"), 1)


# ==========================================================================
# extract_semantic_payload
# ==========================================================================
class TestExtractSemanticPayload(unittest.TestCase):

    def test_non_dict_is_empty(self):
        p = sd.extract_semantic_payload(None)
        self.assertEqual(p["sqls"], [])
        self.assertIsNone(p["result"])

    def test_rows_of_dicts_with_sql(self):
        raw = {"output": {"sql": "SELECT 1", "row_count": 2,
                          "rows": [{"Account_name": "A", "revenue": 10.5},
                                   {"Account_name": "B", "revenue": 20.0}]}}
        p = sd.extract_semantic_payload(raw)
        self.assertEqual(p["sqls"], ["SELECT 1"])
        self.assertEqual(p["result"]["columns"], ["Account_name", "revenue"])
        self.assertEqual(p["result"]["rows"], [["A", 10.5], ["B", 20.0]])
        self.assertEqual(p["row_count"], 2)
        self.assertIn("sql", p["shape_keys"])

    def test_rows_of_lists_with_columns(self):
        raw = {"output": {"queries": [{"query": "SELECT 2",
                                       "columns": ["m", "v"],
                                       "records": [["2025-01", 1], ["2025-02", 2]]}]}}
        p = sd.extract_semantic_payload(raw)
        self.assertEqual(p["sqls"], ["SELECT 2"])
        self.assertEqual(p["result"]["columns"], ["m", "v"])
        self.assertEqual(len(p["result"]["rows"]), 2)

    def test_answer_text_detected(self):
        p = sd.extract_semantic_payload({"output": {"answer": "Total: 42 EUR"}})
        self.assertEqual(p["answer"], "Total: 42 EUR")
        self.assertIsNone(p["result"])

    def test_row_cap_marks_truncated(self):
        rows = [{"c": i} for i in range(sd.MAX_RESULT_ROWS + 5)]
        p = sd.extract_semantic_payload({"output": {"sql": "S", "rows": rows}})
        self.assertEqual(len(p["result"]["rows"]), sd.MAX_RESULT_ROWS)
        self.assertTrue(p["result"]["truncated"])

    def test_row_count_falls_back_to_captured_rows(self):
        p = sd.extract_semantic_payload({"output": {"rows": [{"a": 1}]}})
        self.assertEqual(p["row_count"], 1)


# ==========================================================================
# pick_semantic_input_key
# ==========================================================================
class TestPickSemanticInputKey(unittest.TestCase):

    def test_prefers_known_candidates(self):
        d = {"inputSchema": {"properties": {"question": {"type": "string"},
                                            "limit": {"type": "integer"}}}}
        self.assertEqual(sd.pick_semantic_input_key(d), "question")
        d = {"inputSchema": {"properties": {"query": {"type": "string"}}}}
        self.assertEqual(sd.pick_semantic_input_key(d), "query")

    def test_single_string_property_fallback(self):
        d = {"inputSchema": {"properties": {"nl_request": {"type": "string"},
                                            "max_rows": {"type": "integer"}}}}
        self.assertEqual(sd.pick_semantic_input_key(d), "nl_request")

    def test_default_when_unknown_or_ambiguous(self):
        self.assertEqual(sd.pick_semantic_input_key(None), sd.SEMANTIC_QUESTION_KEY)
        self.assertEqual(sd.pick_semantic_input_key({}), sd.SEMANTIC_QUESTION_KEY)
        d = {"inputSchema": {"properties": {"a": {"type": "string"},
                                            "b": {"type": "string"}}}}
        self.assertEqual(sd.pick_semantic_input_key(d), sd.SEMANTIC_QUESTION_KEY)


# ==========================================================================
# formatting
# ==========================================================================
class TestFormatting(unittest.TestCase):

    def test_int_thousands_nbsp(self):
        self.assertEqual(sd.format_int_thousands(12345678), "12%s345%s678" % (NBSP, NBSP))
        self.assertEqual(sd.format_int_thousands(-1234), "-1%s234" % NBSP)
        self.assertEqual(sd.format_int_thousands(999), "999")

    def test_amount_and_pct(self):
        self.assertEqual(sd.format_amount(12345678.4),
                         "12%s345%s678%sEUR" % (NBSP, NBSP, NBSP))
        self.assertEqual(sd.format_pct(-3.2), "-3.2%s%%" % NBSP)
        self.assertEqual(sd.format_pct(10.0), "10%s%%" % NBSP)

    def test_format_cell_column_aware(self):
        self.assertEqual(sd.format_cell(1234.0, "amount_eur"),
                         "1%s234%sEUR" % (NBSP, NBSP))
        self.assertEqual(sd.format_cell(-3.25, "delta_pct"), sd.format_pct(-3.25))
        self.assertEqual(sd.format_cell("Algérie Télécom", "Account_name"),
                         "Algérie Télécom")
        self.assertEqual(sd.format_cell(None, "x"), "")

    def test_build_table_caps_and_notes(self):
        result = {"columns": ["Account_name", "revenue"],
                  "rows": [["A%d" % i, i * 1000.0] for i in range(15)],
                  "truncated": True}
        table = sd.build_table(result, "fr")
        self.assertEqual(table.count("\n| A"), sd.TABLE_MAX_ROWS)
        self.assertIn("5 ligne(s) supplémentaire(s)", table)
        self.assertIn("Résultat partiel", table)
        self.assertEqual(sd.build_table(None, "fr"), "")
        self.assertEqual(sd.build_table({"columns": [], "rows": []}, "fr"), "")


# ==========================================================================
# headline (fallback + verification gate)
# ==========================================================================
class TestHeadline(unittest.TestCase):

    RESULT = {"columns": ["total_revenue_eur"], "rows": [[12345678.4]], "truncated": False}

    def test_fallback_single_value_sentence(self):
        u = _u(period={"mode": "explicit", "start": "2025-01-01",
                       "end": "2025-12-31", "label": "2025"})
        h = sd.build_fallback_headline(u, self.RESULT, "fr")
        self.assertIn("Revenu total", h)
        self.assertIn("ACTUALS, 2025", h)
        self.assertIn("12%s345%s678%sEUR" % (NBSP, NBSP, NBSP), h)

    def test_fallback_multirow_generic(self):
        result = {"columns": ["a", "b"], "rows": [["x", 1], ["y", 2]], "truncated": False}
        h = sd.build_fallback_headline(_u(), result, "en")
        self.assertIn("Here are the results", h)

    def test_verify_accepts_exact_figures_and_years(self):
        allowed = sd.allowed_number_set(self.RESULT, [Q, "2025"])
        self.assertTrue(sd.verify_headline(
            "Le revenu 2025 s'élève à 12%s345%s678 EUR." % (NBSP, NBSP), allowed))

    def test_verify_rejects_invented_or_rounded_numbers(self):
        allowed = sd.allowed_number_set(self.RESULT, [Q])
        self.assertFalse(sd.verify_headline("Environ 12,3 millions d'EUR.", allowed))
        self.assertFalse(sd.verify_headline("Total : 99 EUR.", allowed))
        self.assertFalse(sd.verify_headline("", allowed))

    def test_verify_accepts_decimal_pct_from_cells(self):
        result = {"columns": ["delta_pct"], "rows": [[-3.2]], "truncated": False}
        allowed = sd.allowed_number_set(result, [])
        self.assertTrue(sd.verify_headline("Un écart de -3,2 % vs budget.", allowed))

    def test_verify_accepts_date_strings_from_cells(self):
        result = {"columns": ["month", "v"], "rows": [["2025-01", 5]], "truncated": False}
        allowed = sd.allowed_number_set(result, [])
        self.assertTrue(sd.verify_headline("Le mois 2025-01 ressort à 5.", allowed))


# ==========================================================================
# events dialect (frozen collaboration contract)
# ==========================================================================
class TestEvents(unittest.TestCase):

    def test_block_and_tool_events_match_visual_dialect(self):
        ev = sd._block("resolve")["chunk"]
        self.assertEqual(ev["eventKind"], "AGENT_BLOCK_START")
        self.assertEqual(ev["eventData"]["blockId"], "resolve")
        ev = sd._tool_start("revenue_semantic_query")["chunk"]
        self.assertEqual(ev["eventKind"], "AGENT_TOOL_START")
        self.assertEqual(ev["eventData"]["toolName"], "revenue_semantic_query")

    def test_agent_result_shape(self):
        u = _u(intent="total")
        ev = sd._agent_result("ready", u, resolved_filters=[{"column": "Product"}],
                              sql_count=1, row_count=3)["chunk"]
        self.assertEqual(ev["eventKind"], "AGENT_RESULT")
        data = ev["eventData"]
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["language"], "fr")
        self.assertEqual(data["intent"], "total")
        self.assertEqual(data["sqlCount"], 1)
        self.assertEqual(data["rowCount"], 3)

    def test_agent_result_survives_none_understanding(self):
        data = sd._agent_result("error", None)["chunk"]["eventData"]
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["language"], "fr")


# ==========================================================================
# conversation continuity (disambiguation answers understood by the LLM)
# ==========================================================================
class TestExtractInput(unittest.TestCase):

    def test_instruction_and_system_context(self):
        query = {"messages": [
            {"role": "system", "content": "CONVERSATION CONTEXT:\nPREVIOUS..."},
            {"role": "user", "content": "Top 10 clients pour IPL (Product)"},
        ]}
        instruction, context = sd.MyLLM._extract_input(query)
        self.assertEqual(instruction, "Top 10 clients pour IPL (Product)")
        self.assertIn("CONVERSATION CONTEXT", context)

    def test_no_context_is_empty(self):
        query = {"messages": [{"role": "user", "content": "CA 2025 ?"}]}
        instruction, context = sd.MyLLM._extract_input(query)
        self.assertEqual(instruction, "CA 2025 ?")
        self.assertEqual(context, "")
        self.assertEqual(sd.MyLLM._extract_input({}), ("", ""))

    def test_prompt_teaches_candidate_mapping(self):
        prompt = sd.build_understand_prompt("2026-06-11")
        self.assertIn("disambiguation question listing candidate values", prompt)
        self.assertIn("Never output a candidate that is not in the list", prompt)


if __name__ == "__main__":
    unittest.main()
