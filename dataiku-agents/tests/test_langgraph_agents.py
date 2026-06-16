"""DSS-free unit tests for the LangGraph agents:
  - agents/orchestrator_langgraph.py   (new agentic tool-calling orchestrator)
  - agents/dataset_expert_langgraph.py (sub-agent: LangGraph wrapper, same engine)

``dataiku`` AND ``langgraph`` are stubbed BEFORE the agent files load (importlib),
so only PURE logic is exercised — registry/tool specs, the honesty sources block,
trace SQL/usage extraction, artifact validation, language detection, and the frozen
cross-file event contract (anti-drift). The graph itself is NOT run (it needs DSS).

Run from the repo root:
    python3 -m unittest discover -s dataiku-agents/tests -v
"""

import importlib.util
import inspect
import os
import sys
import types
import unittest


def _install_stubs():
    # --- dataiku stub (mirrors test_dataset_expert) ---
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

    # --- langgraph stub (only the import surface; the graph is never run here) ---
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


def _load(mod_name, filename):
    path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "agents", filename))
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


orch = _load("orchestrator_under_test", "orchestrator_langgraph.py")
dx = _load("dataset_expert_lg_under_test", "dataset_expert_langgraph.py")


class TestModelIds(unittest.TestCase):
    def test_orchestrator_uses_gpt54mini(self):
        self.assertIn("gpt-5.4-mini", orch.ORCH_LLM_ID)

    def test_subagent_switched_to_gpt54mini(self):
        self.assertIn("gpt-5.4-mini", dx.UNDERSTAND_LLM_ID)
        self.assertIn("gpt-5.4-mini", dx.SQLGEN_LLM_ID)

    def test_subagent_understand_forces_json(self):
        # UNDERSTAND is a deterministic extraction -> forces native JSON for a
        # reliable parse (reasoning is not needed there; it stays on elsewhere).
        src = inspect.getsource(dx.MyLLM._call_json_llm)
        self.assertIn(".with_json_output(", src)


class TestRegistryAndTools(unittest.TestCase):
    def test_revenue_expert_enabled_only(self):
        caps = orch.get_capabilities()
        self.assertIn("revenue_expert", caps)
        self.assertTrue(caps["revenue_expert"]["enabled"])
        self.assertEqual(caps["revenue_expert"]["agent_id"], "agent:AKQaQ0Am")
        # Exactly one enabled revenue agent (rollback invariant).
        revenue = [k for k, v in caps.items()
                   if v.get("kind") == "agent" and v.get("domain") == "revenue"]
        self.assertEqual(revenue, ["revenue_expert"])

    def test_tool_specs_generated_from_registry(self):
        specs, t2c = orch.build_tool_specs(orch.get_capabilities())
        names = {s["function"]["name"] for s in specs}
        self.assertIn("ask_revenue_expert", names)
        self.assertIn("show_chart", names)
        self.assertIn("show_table", names)
        self.assertIn("current_date", names)
        self.assertEqual(t2c["ask_revenue_expert"], "revenue_expert")
        chart = next(s for s in specs if s["function"]["name"] == "show_chart")
        req = chart["function"]["parameters"]["required"]
        self.assertIn("chart_type", req)
        self.assertIn("x", req)
        self.assertIn("y", req)


class TestAntiDrift(unittest.TestCase):
    """The orchestrator's labels for the sub-agent MUST match the sub-agent's
    frozen block/tool ids, or the timeline mislabels / hides the wrong steps."""

    def test_block_labels_match_known_block_ids(self):
        labels = orch.CAPABILITIES["revenue_expert"]["block_labels"]
        self.assertEqual(set(labels.keys()), set(dx.KNOWN_BLOCK_IDS))

    def test_tool_labels_match_known_tool_names(self):
        labels = orch.CAPABILITIES["revenue_expert"]["tool_labels"]
        self.assertEqual(set(labels.keys()), set(dx.KNOWN_TOOL_NAMES))


class TestSourcesBlock(unittest.TestCase):
    def test_sources_emitted_only_when_data_consulted(self):
        ready = orch.sources_block(["revenue_expert"], ["ready"], "fr")
        self.assertIn("DRIVE_Revenues", ready)
        # A clarification / out-of-scope reply cites no dataset.
        self.assertEqual(orch.sources_block(["revenue_expert"], ["need_clarification"], "fr"), "")
        self.assertEqual(orch.sources_block([], [], "en"), "")


class TestTraceExtraction(unittest.TestCase):
    def _sub_trace(self):
        return {
            "name": "root",
            "children": [
                {"name": "dataset-expert:understand",
                 "usageMetadata": {"promptTokens": 10, "completionTokens": 4,
                                   "totalTokens": 14, "estimatedCost": 0.001}},
                {"name": "semantic-model-query",
                 "outputs": {"sql": "SELECT 1", "success": True, "row_count": 2,
                             "columns": ["year", "revenue"],
                             "rows": [["2024", 10], ["2025", 20]]},
                 "usageMetadata": {"promptTokens": 30, "completionTokens": 6,
                                   "totalTokens": 36, "estimatedCost": 0.003}},
            ],
        }

    def test_find_generated_sql(self):
        items = orch._find_generated_sql(self._sub_trace(), 1, "revenue_expert")
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["sql_id"], "s1q1")
        self.assertEqual(it["step_index"], 1)
        self.assertEqual(it["agent_key"], "revenue_expert")
        self.assertEqual(it["result"]["columns"], ["year", "revenue"])
        self.assertEqual(len(it["result"]["rows"]), 2)

    def test_find_usage_sums(self):
        usage = orch._find_usage(self._sub_trace())
        self.assertEqual(usage["promptTokens"], 40)
        self.assertEqual(usage["completionTokens"], 10)
        self.assertEqual(usage["totalTokens"], 50)
        self.assertAlmostEqual(usage["estimatedCost"], 0.004, places=6)

    def test_find_usage_empty_when_absent(self):
        self.assertEqual(orch._find_usage({"name": "x"}), {})

    def test_extract_result_from_span(self):
        res = orch._extract_result_from_span(
            {"columns": ["a", "b"], "rows": [[1, 2], [3, 4]]})
        self.assertEqual(res["columns"], ["a", "b"])
        self.assertEqual(res["rows"], [[1, 2], [3, 4]])
        self.assertFalse(res["truncated"])
        self.assertIsNone(orch._extract_result_from_span({"sql": "x"}))


class TestReducersAndArgs(unittest.TestCase):
    def test_sum_usage(self):
        out = orch._sum_usage({"promptTokens": 1, "estimatedCost": 0.5},
                              {"promptTokens": 2, "totalTokens": 3, "estimatedCost": 0.5})
        self.assertEqual(out["promptTokens"], 3)
        self.assertEqual(out["totalTokens"], 3)
        self.assertAlmostEqual(out["estimatedCost"], 1.0)

    def test_add_unique(self):
        self.assertEqual(orch._add_unique(["a"], ["a", "b"]), ["a", "b"])

    def test_parse_args(self):
        self.assertEqual(orch._parse_args('{"task": "x"}'), {"task": "x"})
        self.assertEqual(orch._parse_args("not json"), {})
        self.assertEqual(orch._parse_args({"a": 1}), {"a": 1})


class TestArtifactValidation(unittest.TestCase):
    def setUp(self):
        self.agent = orch.MyLLM()
        self.state = {"latest": {"columns": ["year", "revenue"],
                                 "rows": [["2024", 10], ["2025", 20]]}}

    def test_chart_valid(self):
        art, msg = self.agent._record_artifact(
            "show_chart",
            {"chart_type": "line", "title": "Revenue", "x": "Year", "y": ["Revenue"]},
            self.state)
        self.assertIsNotNone(art)
        self.assertEqual(art["kind"], "chart")
        self.assertEqual(art["chart"]["type"], "line")
        # case-insensitive resolution back to the real column casing
        self.assertEqual(art["chart"]["x"], "year")
        self.assertEqual(art["chart"]["y"], ["revenue"])

    def test_chart_unknown_column_rejected(self):
        art, msg = self.agent._record_artifact(
            "show_chart",
            {"chart_type": "bar", "x": "month", "y": ["revenue"]},
            self.state)
        self.assertIsNone(art)
        self.assertIn("year", msg)  # message lists the available columns

    def test_table_valid(self):
        art, msg = self.agent._record_artifact("show_table", {"title": "All rows"}, self.state)
        self.assertEqual(art["kind"], "table")
        self.assertIsNone(art["chart"])

    def test_no_result_yet(self):
        art, msg = self.agent._record_artifact("show_table", {}, {})
        self.assertIsNone(art)


class TestLanguageAndPrompt(unittest.TestCase):
    def test_detect_lang(self):
        self.assertEqual(orch._detect_lang("Quelle est l'évolution des revenus ?"), "fr")
        self.assertEqual(orch._detect_lang("What is the revenue trend?"), "en")

    def test_system_prompt_carries_identity_and_rules(self):
        sp = orch.build_system_prompt(orch.get_capabilities(), "fr")
        self.assertIn("Orange Wholesale International", sp)
        self.assertIn("ask_revenue_expert", sp)
        self.assertIn("language", sp.lower())
        self.assertIn("NEVER invent", sp)


class TestSubAgentEngineIntact(unittest.TestCase):
    """Spot-check that copying the engine into the LangGraph file kept behavior."""

    def test_langgraph_structure(self):
        # After the cleanup, the graph is the only path: no legacy fallback
        # method, no USE_LANGGRAPH flag, and the now-unused schema builder gone.
        self.assertTrue(hasattr(dx, "ExpertState"))
        self.assertFalse(hasattr(dx.MyLLM, "_legacy_process_stream"))
        self.assertFalse(hasattr(dx, "USE_LANGGRAPH"))
        self.assertTrue(hasattr(dx, "build_understand_schema"))

    def test_extract_semantic_payload_last_occurrence(self):
        raw = {"messages": [
            {"answer": "I'll start by exploring the schema..."},
            {"answer": "Total revenue is 123.", "rows": [["x", 1]],
             "columns": ["k", "v"], "row_count": 1}]}
        payload = dx.extract_semantic_payload(raw)
        self.assertEqual(payload["answer"], "Total revenue is 123.")
        self.assertEqual(payload["row_count"], 1)

    def test_verify_headline_rejects_unknown_number(self):
        allowed = dx.allowed_number_set({"rows": [[100]], "columns": ["v"]}, [])
        self.assertTrue(dx.verify_headline("The value is 100.", allowed))
        self.assertFalse(dx.verify_headline("The value is 999.", allowed))


# ==========================================================================
# Alignment with the semantic model (2026-06-15): commercial-hierarchy
# priority + transparency, and multi-column customer display.
# ==========================================================================
def _align_profile():
    """Minimal profile fixture exercising the offer hierarchy + diamond_id
    display (values invented — no business data in the repo)."""
    dataset_payload = {
        "profile_version": 1, "dataset_name": "DEMO", "row_count": 100,
        "description_en": "demo", "description_fr": "demo",
        "grain": "row", "default_metric": "revenue",
        "metrics": [{"name": "revenue", "agg": "SUM", "column": "amount_eur",
                     "format": "amount", "unit": "EUR",
                     "label_fr": "Revenu", "label_en": "Revenue",
                     "description": "Sum of amount_eur"}],
        "scenario": {"column": "Phase", "values": ["ACTUALS", "BUDGET"],
                     "default_values": ["ACTUALS"]},
        "time": {"column": "year_month", "format": "yyyy_mm_dd_str",
                 "min": "2024-01-01", "max": "2026-06-01"},
        "notes": [],
    }
    columns = {
        # Offer hierarchy with explicit priority Product<Solution<...<sirano.
        "Product": {"name": "Product", "role": "dimension", "groupable": True,
                    "indexed": True, "distinct_count": 42,
                    "ambiguity_priority": 0, "synonyms": [], "samples": []},
        "Solution": {"name": "Solution", "role": "dimension", "groupable": True,
                     "indexed": True, "distinct_count": 14,
                     "ambiguity_priority": 1, "synonyms": [], "samples": []},
        "sirano_product": {"name": "sirano_product", "role": "dimension",
                           "groupable": True, "indexed": True,
                           "distinct_count": 153, "ambiguity_priority": 3,
                           "synonyms": [], "samples": []},
        # Identifier with TWO human display columns; id must stay last.
        "diamond_id": {"name": "diamond_id", "role": "identifier",
                       "groupable": True, "indexed": True,
                       "distinct_count": 1200,
                       "display_columns": ["Account_name", "carrier_code"],
                       "synonyms": ["client"], "samples": []},
        "amount_eur": {"name": "amount_eur", "role": "measure",
                       "groupable": False, "indexed": False,
                       "distinct_count": 99, "synonyms": [], "samples": []},
    }
    return dx.Profile(dataset_payload, columns)


def _align_u(**kw):
    u = {"scope": "data", "language": "en", "instruction": "q",
         "intent": "total", "metric": "revenue", "scenarios": [],
         "period": {"mode": "all_available"}, "periods": [],
         "group_by": None, "list_column": None, "top_n": None,
         "order": "desc", "terms": [], "clarification": ""}
    u.update(kw)
    return u


class TestSemanticAlignment(unittest.TestCase):
    P = _align_profile()

    def test_priority_picks_product_over_sirano(self):
        # sirano_product has the MOST distinct values; explicit priority must
        # still pick Product (distinct_count heuristic would pick sirano).
        self.assertLess(self.P.column_priority("Product"),
                        self.P.column_priority("sirano_product"))
        self.assertLess(self.P.column_priority("Product"),
                        self.P.column_priority("Solution"))

    def test_refine_ambiguous_records_alt_columns(self):
        cands = [{"target_column": "Solution", "target_value": "IP Transit",
                  "display_value": "IP Transit", "score": 1.0},
                 {"target_column": "Product", "target_value": "IP Transit",
                  "display_value": "IP Transit", "score": 1.0}]
        verdict, data = dx.refine_ambiguous(self.P, "IP Transit", cands)
        self.assertEqual(verdict, "resolved")
        self.assertEqual(data["target_column"], "Product")   # most granular
        self.assertEqual(data.get("alt_columns"), ["Solution"])

    def test_filter_clauses_and_disclosure_note(self):
        res = [{"status": "resolved", "target_column": "Product",
                "target_value": "IP Transit", "alt_columns": ["Solution"]}]
        filters = dx.build_filter_clauses(res)
        self.assertEqual(filters[0]["column"], "Product")
        self.assertEqual(filters[0]["alt_columns"], ["Solution"])
        note_en = dx.build_disclosure_notes(filters, "en")
        self.assertIn("IP Transit", note_en)
        self.assertIn("Product", note_en)
        self.assertIn("Solution", note_en)
        # No disclosure when the value is unique to one column.
        self.assertEqual(dx.build_disclosure_notes(
            [{"column": "Product", "value": "EVPL"}], "fr"), "")

    def test_semantic_question_multi_display_keeps_id_last(self):
        u = _align_u(intent="breakdown", group_by="diamond_id")
        q = dx.build_semantic_question(u, self.P, [])
        self.assertIn("Group by diamond_id ONLY", q)
        self.assertIn("MAX(Account_name) AS Account_name", q)
        self.assertIn("MAX(carrier_code) AS carrier_code", q)
        self.assertIn("keep diamond_id as the LAST", q)
        self.assertIn("never group by Account_name or carrier_code", q)

    def test_semantic_question_ambiguous_term_not_pinned(self):
        # An ambiguous offer term must NOT be pinned to a column (defer to the
        # smart model) — even if the helper's best guess was sirano_product.
        u = _align_u(intent="total", instruction="revenus EVPL")
        q = dx.build_semantic_question(u, self.P, [
            {"column": "sirano_product", "value": "EVPL",
             "alt_columns": ["Product", "Solution"]}])
        self.assertIn("AMBIGUOUS OFFER TERM", q)
        self.assertIn("EVPL", q)
        self.assertIn("Product", q)
        self.assertNotIn("sirano_product = 'EVPL'", q)   # never a hard pin

    def test_semantic_question_confident_value_suggested(self):
        # A single-column value (e.g. a customer name) is suggested directly.
        u = _align_u(intent="total", instruction="revenue HALYS")
        q = dx.build_semantic_question(u, self.P, [
            {"column": "Account_name", "value": "HALYS"}])
        self.assertIn("HELPER FINDINGS", q)
        self.assertIn("Account_name = 'HALYS'", q)
        self.assertNotIn("AMBIGUOUS OFFER TERM", q)


class TestNativeArtifactFormatting(unittest.TestCase):
    """The orchestrator hands the model a NON-table view of a specialist result
    (headline + data + a LIGHT non-prescriptive render nudge), so it renders
    natively but freely picks the chart/columns (no forced type)."""

    def test_strip_markdown_tables(self):
        text = ("Top clients:\n\n| Client | Revenue |\n|---|---|\n"
                "| A | 10 |\n| B | 5 |\n\nB performed worst.")
        out = orch._strip_markdown_tables(text)
        self.assertNotIn("|", out)
        self.assertIn("Top clients:", out)
        self.assertIn("B performed worst.", out)

    def test_subagent_tool_output_strips_table_and_nudges(self):
        answer = "Total: 10.\n\n| Client | Revenue |\n|---|---|\n| A | 10 |"
        result = {"columns": ["Client", "Revenue"], "rows": [["A", 10]]}
        out = orch._subagent_tool_output(answer, result, "breakdown")
        self.assertNotIn("|", out.split("DATA")[0])   # headline carries no table
        self.assertIn("DATA", out)
        self.assertIn("DISPLAY", out)                 # light render nudge
        self.assertIn("show_chart", out)
        self.assertIn("Client, Revenue", out)         # exact columns offered
        # NON-prescriptive: it does NOT force a specific chart type / hint.
        self.assertNotIn("RENDERING HINT", out)

    def test_subagent_tool_output_passthrough_when_no_rows(self):
        # A clarification / out-of-scope reply (no rows) is passed through.
        out = orch._subagent_tool_output("Which EVPL did you mean?", None, None)
        self.assertEqual(out, "Which EVPL did you mean?")


class TestModelModeAndEscalation(unittest.TestCase):
    def test_parse_mode_extracts_and_strips(self):
        mode, clean = orch.parse_mode("revenus EVPL ⟦owi:mode=high⟧")
        self.assertEqual(mode, "high")
        self.assertEqual(clean, "revenus EVPL")

    def test_parse_mode_defaults_medium(self):
        mode, clean = orch.parse_mode("plain question")
        self.assertEqual(mode, "medium")
        self.assertEqual(clean, "plain question")

    def test_parse_mode_unknown_token_ignored(self):
        mode, _clean = orch.parse_mode("q ⟦owi:mode=turbo⟧")
        self.assertEqual(mode, "medium")

    def test_pick_loop_llm_policy(self):
        # Eco / Medium (simple) -> cheap; High -> strong; Medium + complex -> strong.
        self.assertIn("gpt-5.4-mini", orch.pick_loop_llm("eco", "revenus EVPL 2026"))
        self.assertIn("gpt-5.4-mini", orch.pick_loop_llm("medium", "revenus EVPL 2026"))
        self.assertEqual(orch.pick_loop_llm("high", "x"), orch.ESCALATION_LLM_ID)
        self.assertEqual(
            orch.pick_loop_llm("medium",
                               "compare EVPL revenue actuals vs budget and explain why"),
            orch.ESCALATION_LLM_ID)

    def test_complexity_heuristic_conservative(self):
        # A short single-domain lookup is NOT complex.
        self.assertFalse(orch.complexity_is_high("revenus EVPL 2026"))
        # A comparison/analysis question with several parts IS complex.
        self.assertTrue(orch.complexity_is_high(
            "compare EVPL revenue actuals vs budget and explain why it diverged"))


class TestKpiArtifact(unittest.TestCase):
    def test_show_kpi_records_value_column(self):
        llm = orch.MyLLM()
        state = {"latest": {"columns": ["Revenue_EUR", "delta_pct"],
                            "rows": [[1234, 5.2]]}}
        art, _msg = llm._record_artifact(
            "show_kpi", {"label": "Revenue YTD", "value": "Revenue_EUR",
                         "delta_pct": "delta_pct"}, state)
        self.assertIsNotNone(art)
        self.assertEqual(art["kind"], "kpi")
        self.assertEqual(art["kpi"]["value"], "Revenue_EUR")
        self.assertEqual(art["kpi"]["delta_pct"], "delta_pct")

    def test_show_kpi_unknown_column_rejected(self):
        llm = orch.MyLLM()
        state = {"latest": {"columns": ["Revenue_EUR"], "rows": [[1]]}}
        art, _msg = llm._record_artifact("show_kpi", {"value": "nope"}, state)
        self.assertIsNone(art)

    def test_show_kpi_tool_in_specs(self):
        specs, _t2c = orch.build_tool_specs(orch.get_capabilities())
        names = {s["function"]["name"] for s in specs}
        self.assertIn("show_kpi", names)


if __name__ == "__main__":
    unittest.main()
