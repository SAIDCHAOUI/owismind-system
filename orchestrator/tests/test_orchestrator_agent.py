"""DSS-free unit tests for orchestrator/orchestrator_agent.py (v2.2).

The Code Agent file imports ``dataiku`` and ``dataiku.llm.python.BaseLLM`` at
module level. Those modules do not exist outside a DSS instance, so minimal
stubs are installed in ``sys.modules`` BEFORE the file is loaded via importlib.
Only PURE functions are tested here (no LLM call, no project, no streaming):
the deterministic plan validation, trace walkers, capture caps, label helpers
and text builders that the frozen Evidence trust-layer contract relies on.

Run from the repo root:
    python3 -m unittest discover -s orchestrator/tests -v
"""

import importlib.util
import json
import os
import sys
import types
import unittest


# --------------------------------------------------------------------------
# Stub dataiku BEFORE importing the agent file (it is meant to run inside DSS).
# --------------------------------------------------------------------------
def _install_dataiku_stub():
    dataiku_mod = types.ModuleType("dataiku")
    dataiku_mod.api_client = lambda: None  # never called by the pure functions

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
    os.path.join(os.path.dirname(__file__), "..", "orchestrator_agent.py"))
_SPEC = importlib.util.spec_from_file_location("orchestrator_agent_under_test", _AGENT_PATH)
orc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(orc)


# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------
# Minimal capabilities registry mirroring the real shape (agent + tool).
CAPS = {
    "rev": {
        "kind": "agent",
        "agent_id": "agent:TEST",
        "label_fr": "SalesDrive (revenus)",
        "label_en": "SalesDrive (revenue)",
        "planner_description": "Revenue questions.",
        "dataset_sources": ["https://intranet.example/DATASET/DRIVE_Revenues"],
        "dataset_label_fr": "Base des revenus clients",
        "dataset_label_en": "Customer revenue base",
        "dataset_ref": {"project_key": "P", "dataset_name": "DRIVE_Revenues"},
        "enabled": True,
    },
    "clock": {
        "kind": "tool",
        "label_fr": "Date du jour",
        "label_en": "Current date",
        "planner_description": "Returns today's date.",
        "enabled": True,
    },
}

# Sub-agent config used by the _sub_event_label tests.
SUB_CFG = {
    "label_fr": "SalesDrive (revenus)",
    "label_en": "SalesDrive (revenue)",
    "block_labels": {
        "resolve": {"fr": "analyse de la question", "en": "analyzing the question"},
        "routing": None,  # explicitly hidden technical block
    },
    "tool_labels": {
        "revenue_semantic_query": {"fr": "requête SQL", "en": "SQL query"},
    },
}


def _sql_span(outputs):
    """A trace span shaped like the semantic-model-query tool span."""
    merged = {"sql": "SELECT 1", "success": True, "row_count": 1}
    merged.update(outputs)
    return {"name": "semantic-model-query", "outputs": merged}


def _business_step(instruction="q", capability="rev", kind="agent"):
    return {"kind": kind, "capability": capability, "instruction": instruction}


# ==========================================================================
# _validate_plan
# ==========================================================================
class ValidatePlanTests(unittest.TestCase):

    def _validate(self, parsed):
        return orc.MyLLM._validate_plan(parsed, CAPS)

    def test_non_dict_rejected(self):
        self.assertIsNone(self._validate(None))
        self.assertIsNone(self._validate("BUSINESS"))
        self.assertIsNone(self._validate([1, 2]))

    def test_unknown_intent_rejected(self):
        self.assertIsNone(self._validate({"intent": "HACK", "language": "fr"}))

    def test_business_with_valid_agent_step(self):
        plan = self._validate({"intent": "BUSINESS", "language": "en",
                               "steps": [_business_step("revenue 2025?")]})
        self.assertIsNotNone(plan)
        self.assertEqual(plan["steps"],
                         [{"kind": "agent", "capability": "rev",
                           "instruction": "revenue 2025?"}])
        self.assertEqual(plan["language"], "en")

    def test_invented_capability_ignored_business_becomes_none(self):
        plan = self._validate({"intent": "BUSINESS", "language": "fr",
                               "steps": [_business_step(capability="made_up")]})
        self.assertIsNone(plan)  # no valid step left -> retry/fallback

    def test_kind_mismatch_ignored(self):
        # 'clock' is a tool: declaring it as an agent step is incoherent.
        plan = self._validate({"intent": "BUSINESS", "language": "fr",
                               "steps": [_business_step(capability="clock", kind="agent")]})
        self.assertIsNone(plan)

    def test_empty_instruction_ignored(self):
        plan = self._validate({"intent": "BUSINESS", "language": "fr",
                               "steps": [_business_step(instruction="   ")]})
        self.assertIsNone(plan)

    def test_duplicate_steps_deduplicated(self):
        plan = self._validate({"intent": "BUSINESS", "language": "fr",
                               "steps": [_business_step("same"), _business_step("same")]})
        self.assertEqual(len(plan["steps"]), 1)

    def test_max_steps_cap(self):
        steps = [_business_step("q%d" % i) for i in range(10)]
        plan = self._validate({"intent": "BUSINESS", "language": "fr", "steps": steps})
        self.assertEqual(len(plan["steps"]), orc.MAX_STEPS)

    def test_non_business_intent_purges_steps(self):
        # ORCH-10b: a GREETING plan that hallucinated steps must never execute them.
        plan = self._validate({"intent": "GREETING", "language": "fr",
                               "direct_answer": "Bonjour !",
                               "steps": [_business_step("revenue?")]})
        self.assertIsNotNone(plan)
        self.assertEqual(plan["steps"], [])

    def test_out_of_scope_purges_steps_too(self):
        plan = self._validate({"intent": "OUT_OF_SCOPE", "language": "en",
                               "steps": [_business_step()]})
        self.assertEqual(plan["steps"], [])

    def test_business_without_steps_is_none(self):
        self.assertIsNone(self._validate({"intent": "BUSINESS", "language": "fr"}))

    def test_first_name_trimmed_to_40_chars(self):
        plan = self._validate({"intent": "GREETING", "language": "fr",
                               "user_first_name": "  " + "x" * 100})
        self.assertEqual(plan["user_first_name"], "x" * 40)


# ==========================================================================
# _safe_json_parse
# ==========================================================================
class SafeJsonParseTests(unittest.TestCase):

    def test_plain_json(self):
        self.assertEqual(orc._safe_json_parse('{"a": 1}'), {"a": 1})

    def test_fenced_json(self):
        text = "```json\n{\"intent\": \"BUSINESS\"}\n```"
        self.assertEqual(orc._safe_json_parse(text), {"intent": "BUSINESS"})

    def test_embedded_json_in_prose(self):
        text = "Here is the plan: {\"a\": [1, 2]} hope it helps"
        self.assertEqual(orc._safe_json_parse(text), {"a": [1, 2]})

    def test_garbage_returns_none(self):
        self.assertIsNone(orc._safe_json_parse("not json at all"))

    def test_empty_and_none_return_none(self):
        self.assertIsNone(orc._safe_json_parse(""))
        self.assertIsNone(orc._safe_json_parse(None))


# ==========================================================================
# _find_generated_sql — extraction, result capture, caps, depth guard
# ==========================================================================
class FindGeneratedSqlTests(unittest.TestCase):

    def test_basic_extraction_nested(self):
        trace = {"children": [{"deep": [_sql_span({"sql": "SELECT a", "row_count": 3})]}]}
        found = orc._find_generated_sql(trace)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["sql"], "SELECT a")
        self.assertEqual(found[0]["row_count"], 3)
        self.assertTrue(found[0]["success"])
        self.assertNotIn("result", found[0])  # no rows in outputs -> no capture

    def test_no_sql_key_means_no_item(self):
        trace = {"name": "semantic-model-query", "outputs": {"success": True}}
        self.assertEqual(orc._find_generated_sql(trace), [])

    def test_result_from_list_of_dicts(self):
        span = _sql_span({"rows": [{"customer": "AT", "total": 5},
                                   {"customer": "MT", "total": 7.5}]})
        found = orc._find_generated_sql(span)
        result = found[0]["result"]
        self.assertEqual(result["columns"], ["customer", "total"])
        self.assertEqual(result["rows"], [["AT", 5], ["MT", 7.5]])
        self.assertFalse(result["truncated"])

    def test_result_from_list_of_lists_with_columns(self):
        span = _sql_span({"data": [["AT", 5]], "columns": ["customer", "total"]})
        result = orc._find_generated_sql(span)[0]["result"]
        self.assertEqual(result["columns"], ["customer", "total"])
        self.assertEqual(result["rows"], [["AT", 5]])

    def test_alternate_column_keys_accepted(self):
        for col_key in ("column_names", "headers"):
            span = _sql_span({"data": [[1]], col_key: ["c"]})
            result = orc._find_generated_sql(span)[0]["result"]
            self.assertEqual(result["columns"], ["c"], col_key)

    def test_list_of_lists_without_columns_not_captured(self):
        span = _sql_span({"data": [["AT", 5]]})
        self.assertNotIn("result", orc._find_generated_sql(span)[0])

    def test_mixed_shape_not_captured(self):
        span = _sql_span({"rows": [{"a": 1}, ["not", "a", "dict"]]})
        self.assertNotIn("result", orc._find_generated_sql(span)[0])

    def test_row_key_priority_rows_over_data(self):
        span = _sql_span({"rows": [{"from_rows": 1}],
                          "data": [["x"]], "columns": ["from_data"]})
        result = orc._find_generated_sql(span)[0]["result"]
        self.assertEqual(result["columns"], ["from_rows"])

    def test_records_key_accepted(self):
        span = _sql_span({"records": [{"k": "v"}]})
        result = orc._find_generated_sql(span)[0]["result"]
        self.assertEqual(result["rows"], [["v"]])

    def test_rows_capped_at_max_and_truncated(self):
        rows = [{"i": n} for n in range(orc.MAX_RESULT_ROWS + 10)]
        result = orc._find_generated_sql(_sql_span({"rows": rows}))[0]["result"]
        self.assertEqual(len(result["rows"]), orc.MAX_RESULT_ROWS)
        self.assertTrue(result["truncated"])

    def test_columns_capped_at_max_and_truncated(self):
        wide = {("c%03d" % n): n for n in range(orc.MAX_RESULT_COLS + 5)}
        result = orc._find_generated_sql(_sql_span({"rows": [wide]}))[0]["result"]
        self.assertEqual(len(result["columns"]), orc.MAX_RESULT_COLS)
        self.assertEqual(len(result["rows"][0]), orc.MAX_RESULT_COLS)
        self.assertTrue(result["truncated"])

    def test_cell_string_capped_at_256(self):
        result = orc._find_generated_sql(
            _sql_span({"rows": [{"c": "y" * 1000}]}))[0]["result"]
        self.assertEqual(len(result["rows"][0][0]), 256)

    def test_primitive_cells_kept_as_is(self):
        result = orc._find_generated_sql(
            _sql_span({"rows": [{"i": 7, "f": 1.5, "b": True, "n": None}]}))[0]["result"]
        self.assertEqual(result["rows"][0], [7, 1.5, True, None])

    def test_non_finite_float_stringified(self):
        result = orc._find_generated_sql(
            _sql_span({"rows": [{"f": float("inf")}]}))[0]["result"]
        cell = result["rows"][0][0]
        self.assertIsInstance(cell, str)
        # The whole captured result must be JSON-serializable (no NaN/Inf).
        json.dumps(result, allow_nan=False)

    def test_oversize_serialized_result_drops_rows(self):
        # 50 rows x 6 cols x ~250 chars per cell >> 64_000 chars serialized.
        rows = [{("c%d" % c): "z" * 250 for c in range(6)} for _ in range(50)]
        result = orc._find_generated_sql(_sql_span({"rows": rows}))[0]["result"]
        self.assertEqual(result["rows"], [])
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["columns"]), 6)  # shape stays honest

    def test_depth_250_no_recursion_error(self):
        node = _sql_span({})
        for _ in range(250):
            node = {"child": node}
        # Beyond _MAX_TRACE_DEPTH the walker stops cleanly: no crash, no find.
        self.assertEqual(orc._find_generated_sql(node), [])

    def test_within_depth_still_found(self):
        node = _sql_span({})
        for _ in range(50):
            node = {"child": node}
        self.assertEqual(len(orc._find_generated_sql(node)), 1)


# ==========================================================================
# _find_usage_metadata / _sum_usage / _acc_usage
# ==========================================================================
class UsageHelpersTests(unittest.TestCase):

    def test_find_usage_metadata_nested_and_depth_guarded(self):
        trace = {"a": [{"usageMetadata": {"totalTokens": 5}}],
                 "usageMetadata": {"totalTokens": 2}}
        self.assertEqual(len(orc._find_usage_metadata(trace)), 2)
        deep = {"usageMetadata": {"totalTokens": 1}}
        for _ in range(250):
            deep = {"child": deep}
        self.assertEqual(orc._find_usage_metadata(deep), [])  # guarded, no crash

    def test_sum_usage_tolerates_none_values(self):
        total = orc._sum_usage([
            {"promptTokens": 1, "completionTokens": 2, "totalTokens": 3, "estimatedCost": 0.5},
            {"promptTokens": None, "totalTokens": 4},
        ])
        self.assertEqual(total["promptTokens"], 1)
        self.assertEqual(total["totalTokens"], 7)
        self.assertAlmostEqual(total["estimatedCost"], 0.5)

    def test_acc_usage_accumulates_and_tolerates_none(self):
        total = {"promptTokens": 1, "completionTokens": 0, "totalTokens": 1, "estimatedCost": 0.0}
        orc._acc_usage(total, {"promptTokens": 2, "totalTokens": 2, "estimatedCost": 0.1})
        orc._acc_usage(total, None)  # must be a no-op, not a crash
        self.assertEqual(total["promptTokens"], 3)
        self.assertEqual(total["totalTokens"], 3)
        self.assertAlmostEqual(total["estimatedCost"], 0.1)


# ==========================================================================
# _sub_event_label
# ==========================================================================
class SubEventLabelTests(unittest.TestCase):

    def test_skipped_kinds_return_none(self):
        for kind in orc._SKIPPED_SUB_KINDS:
            self.assertIsNone(orc._sub_event_label(kind, {}, "fr", SUB_CFG))

    def test_thinking_label(self):
        label = orc._sub_event_label("SUB_AGENT_AGENT_THINKING", {}, "en", SUB_CFG)
        self.assertEqual(label, "SalesDrive (revenue) is thinking…")

    def test_tool_start_with_hex_suffix_uses_registry_label(self):
        ed = {"toolName": "revenue_semantic_query__f547e0"}
        label = orc._sub_event_label("SUB_AGENT_AGENT_TOOL_START", ed, "fr", SUB_CFG)
        self.assertIn("requête SQL", label)
        self.assertNotIn("__f547e0", label)

    def test_block_start_known_label(self):
        ed = {"blockId": "resolve"}
        label = orc._sub_event_label("SUB_AGENT_AGENT_BLOCK_START", ed, "fr", SUB_CFG)
        self.assertIn("analyse de la question", label)

    def test_block_start_none_label_is_masked(self):
        ed = {"blockId": "routing"}
        self.assertIsNone(orc._sub_event_label("SUB_AGENT_AGENT_BLOCK_START", ed, "fr", SUB_CFG))

    def test_unknown_kind_gets_generic_readable_label(self):
        label = orc._sub_event_label("SUB_AGENT_AGENT_SOMETHING_NEW", {}, "en", SUB_CFG)
        self.assertIn("something new", label)
        self.assertIn("SalesDrive (revenue)", label)


# ==========================================================================
# _sources_block — business labels only, never URLs (ORCH-05)
# ==========================================================================
class SourcesBlockTests(unittest.TestCase):

    def test_business_label_no_url(self):
        block = orc._sources_block([{"status": "ok", "capability": "rev"}], CAPS, "fr")
        self.assertIn("**Sources**", block)
        self.assertIn("Base des revenus clients", block)
        self.assertNotIn("http", block)
        self.assertNotIn("intraorange", block)

    def test_english_label(self):
        block = orc._sources_block([{"status": "ok", "capability": "rev"}], CAPS, "en")
        self.assertIn("Customer revenue base", block)

    def test_deduplicated_across_steps(self):
        results = [{"status": "ok", "capability": "rev"},
                   {"status": "ok", "capability": "rev"}]
        block = orc._sources_block(results, CAPS, "fr")
        self.assertEqual(block.count("Base des revenus clients"), 1)

    def test_failed_steps_excluded(self):
        results = [{"status": "error", "capability": "rev"},
                   {"status": "empty", "capability": "rev"}]
        self.assertEqual(orc._sources_block(results, CAPS, "fr"), "")

    def test_capability_without_dataset_label_contributes_nothing(self):
        self.assertEqual(
            orc._sources_block([{"status": "ok", "capability": "clock"}], CAPS, "fr"), "")

    def test_missing_lang_falls_back_to_fr(self):
        caps = {"rev": dict(CAPS["rev"])}
        caps["rev"].pop("dataset_label_en")
        block = orc._sources_block([{"status": "ok", "capability": "rev"}], caps, "en")
        self.assertIn("Base des revenus clients", block)


# ==========================================================================
# _build_capabilities_answer (deterministic fallback)
# ==========================================================================
class CapabilitiesAnswerTests(unittest.TestCase):

    def test_french_answer_lists_agents_and_tools(self):
        text = orc._build_capabilities_answer(CAPS, "fr")
        self.assertIn("SalesDrive (revenus)", text)
        self.assertIn("Date du jour", text)
        self.assertNotIn("http", text)

    def test_english_answer_uses_english_labels(self):
        text = orc._build_capabilities_answer(CAPS, "en")
        self.assertIn("SalesDrive (revenue)", text)
        self.assertIn("Current date", text)


# ==========================================================================
# Misc helpers: _clean_tool_suffix, _SafeDict, _ev_l, _is_footer
# ==========================================================================
class MiscHelpersTests(unittest.TestCase):

    def test_clean_tool_suffix(self):
        self.assertEqual(orc._clean_tool_suffix("my_tool__f547e0"), "my_tool")
        self.assertEqual(orc._clean_tool_suffix("my_tool"), "my_tool")
        self.assertEqual(orc._clean_tool_suffix(None), "")

    def test_safe_dict_missing_key_is_empty(self):
        self.assertEqual("a{x}b".format_map(orc._SafeDict()), "ab")

    def test_ev_l_known_kind_formats_label(self):
        ev = orc._ev_l("CALLING_AGENT", "fr", {"stepIndex": 1}, label="SalesDrive")
        chunk = ev["chunk"]
        self.assertEqual(chunk["type"], "event")
        self.assertEqual(chunk["eventKind"], "CALLING_AGENT")
        self.assertIn("SalesDrive", chunk["eventData"]["label"])
        self.assertEqual(chunk["eventData"]["stepIndex"], 1)

    def test_ev_l_missing_fmt_key_is_safe(self):
        ev = orc._ev_l("CALLING_AGENT", "fr")  # no 'label' fmt arg
        self.assertNotIn("{label}", ev["chunk"]["eventData"]["label"])

    def test_ev_l_unknown_kind_uses_kind_as_label(self):
        ev = orc._ev_l("BRAND_NEW_KIND", "en")
        self.assertEqual(ev["chunk"]["eventData"]["label"], "BRAND_NEW_KIND")

    def test_is_footer_by_payload_type(self):
        self.assertTrue(orc._is_footer(object(), {"type": "footer"}))
        self.assertFalse(orc._is_footer(object(), {"type": "event"}))
        self.assertFalse(orc._is_footer(object(), {}))

    def test_error_codes_are_stable_strings(self):
        # ORCH-03: codes are part of the frozen protocol — assert exact values.
        self.assertEqual(orc.ERROR_CODE_NO_USER_MESSAGE, "no_user_message")
        self.assertEqual(orc.ERROR_CODE_AGENT_STEP_FAILED, "agent_step_failed")
        self.assertEqual(orc.ERROR_CODE_SYNTHESIS_FAILED, "synthesis_failed")
        self.assertEqual(orc.ERROR_CODE_INTERNAL, "internal_error")

    def test_capture_caps_match_contract(self):
        self.assertEqual(orc.MAX_RESULT_ROWS, 50)
        self.assertEqual(orc.MAX_RESULT_COLS, 50)
        self.assertEqual(orc._MAX_TRACE_DEPTH, 200)


if __name__ == "__main__":
    unittest.main()
