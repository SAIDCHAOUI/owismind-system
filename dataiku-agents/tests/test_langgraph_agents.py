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

    def test_subagent_json_call_drops_native_json_mode(self):
        # Reasoning must stay on -> the native JSON-mode CALL must be gone (the
        # docstring may still mention the name to explain WHY it was removed).
        src = inspect.getsource(dx.MyLLM._call_json_llm)
        self.assertNotIn(".with_json_output(", src)


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
        self.assertFalse(hasattr(dx, "build_understand_schema"))

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


if __name__ == "__main__":
    unittest.main()
