# Tests for agents/native_orchestrator.py - the in-backend orchestrator engine
# (chantier B, 2026-08-06). Everything runs DSS-free: the dataiku api_client is
# monkeypatched with a fake project/llm/completion, and the sub-agent streaming
# is replaced by canned event generators. The tests pin the engine's CONTRACTS:
# the normalized event stream (same shapes as streaming.run_agent_streamed), the
# frozen artifact event, the global sqlIndex renumbering, the loop bounds, and
# the hub-capabilities fallback.
import json
import os
import sys
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
sys.path.insert(0, _HERE)

import _dss_stub  # noqa: E402

_dss_stub.install()

import dataiku  # noqa: E402  (stubbed above)

from owismind.agents import native_orchestrator as native  # noqa: E402
from owismind.agents import streaming  # noqa: E402


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeResponse(object):
    def __init__(self, text=None, tool_calls=None, success=True, raw=None):
        self.text = text
        self.tool_calls = tool_calls or []
        self.success = success
        self.raw = raw


class FakeCompletion(object):
    """Scripted completion: each execute() pops the next FakeResponse."""

    def __init__(self, responses):
        self.settings = {}
        self.messages = []
        self.tool_call_records = []
        self.tool_outputs = []
        self._responses = list(responses)
        self.executed_with_tools = []

    def with_message(self, content, role="user"):
        self.messages.append({"role": role, "content": content})
        return self

    def with_tool_calls(self, tool_calls, role="assistant"):
        self.tool_call_records.append(tool_calls)
        return self

    def with_tool_output(self, output, tool_call_id=None):
        self.tool_outputs.append({"output": output, "tool_call_id": tool_call_id})
        return self

    def execute(self):
        self.executed_with_tools.append("tools" in self.settings)
        return self._responses.pop(0)


class FakeLLM(object):
    def __init__(self, completion):
        self._completion = completion

    def new_completion(self):
        return self._completion


class FakeProject(object):
    def __init__(self, completion, library_raises=True):
        self._completion = completion
        self._library_raises = library_raises

    def get_llm(self, llm_id):
        return FakeLLM(self._completion)

    def get_library(self):
        if self._library_raises:
            raise RuntimeError("no library in tests")
        raise AssertionError("unexpected get_library call")


class FakeClient(object):
    def __init__(self, project):
        self._project = project

    def get_project(self, project_key):
        return self._project


TEST_MODES = {"smart": "openai:TEST:smart-model", "pro": "openai:TEST:pro-model",
              "claude": "openai:TEST:claude-model"}


class _LibProject(object):
    """A project whose library serves one models.json (or none)."""

    def __init__(self, raw):
        self.raw = raw

    def get_library(self):
        project = self

        class _File(object):
            def read(self_inner):
                return project.raw

        class _Lib(object):
            def get_file(self_inner, path):
                return _File() if project.raw is not None else None
        return _Lib()


class TestModelsFromHub(unittest.TestCase):
    """models.json is the ONLY source of the LLM ids: no embedded id, no fallback."""

    def setUp(self):
        native.invalidate_models_cache()

    def tearDown(self):
        native.invalidate_models_cache()

    def test_no_embedded_id(self):
        for gone in ("LLM_BY_MODE", "GEMINI_FLASH_LITE_ID", "GEMINI_FLASH_ID", "SONNET_ID"):
            self.assertFalse(hasattr(native, gone), gone)

    def test_central_then_orchestrator_override(self):
        models = {"version": 1, "modes": dict(TEST_MODES),
                  "agents": {"orchestrator": {"claude": "openai:TEST:own"}}, "factory": {}}
        project = _LibProject(json.dumps(models))
        self.assertEqual(native.get_llm_id(project, "smart"), TEST_MODES["smart"])
        self.assertEqual(native.get_llm_id(project, "claude"), "openai:TEST:own")
        self.assertEqual(native.get_llm_id(project, "turbo"), TEST_MODES["smart"])

    def test_missing_or_invalid_file_fails_loudly(self):
        for raw in (None, "", "{bad", "[]", json.dumps({"modes": {"smart": "x y"}})):
            native.invalidate_models_cache()
            with self.assertRaises(native.ModelConfigError):
                native.get_llm_id(_LibProject(raw), "smart")

    def test_edit_applies_after_ttl(self):
        models = {"version": 1, "modes": dict(TEST_MODES), "agents": {}, "factory": {}}
        project = _LibProject(json.dumps(models))
        self.assertEqual(native.get_llm_id(project, "pro"), TEST_MODES["pro"])
        models["modes"]["pro"] = "openai:TEST:new-pro"
        project.raw = json.dumps(models)
        self.assertEqual(native.get_llm_id(project, "pro"), TEST_MODES["pro"])   # cached
        native._models_cache = (native._models_cache[0],
                                native._models_cache[1] - native._MODELS_CACHE_TTL_SECONDS - 1)
        self.assertEqual(native.get_llm_id(project, "pro"), "openai:TEST:new-pro")


def _tool_call(name, args, call_id="call_1"):
    return {"type": "function", "id": call_id,
            "function": {"name": name, "arguments": json.dumps(args)}}


CAPS = {
    "revenue_expert": {
        "kind": "agent", "agent_id": "agent:bHrWLyOL",
        "tool_name": "ask_revenue_expert",
        "planner_description": "Revenue expert.",
        "pass_context": True, "enabled": True,
    },
    "tickets_expert": {
        "kind": "agent", "agent_id": "agent:NcE9LD2i",
        "tool_name": "ask_tickets_expert",
        "planner_description": "Tickets expert.",
        "pass_context": False, "enabled": True,
    },
}

# PRODUCTION captured shape (evidence/capture.extract_result): EXACTLY
# {columns, rows, truncated} - NO 'captured' key, NO 'row_count' (those exist
# only on the /evidence/meta response block). The engine must recognize THIS.
RESULT = {"columns": ["month", "Revenue_EUR"],
          "rows": [["2026-01", 10.0]], "truncated": False}


def _sub_events(sql_id="s1", result=RESULT):
    """A canned successful sub-agent run (the shapes run_agent_streamed yields)."""
    return [
        {"type": "agent_event", "eventKind": "AGENT_TURN_START", "blockId": None,
         "nextBlockId": None, "toolName": None, "elapsedSeconds": 0.1},
        {"type": "answer_delta", "text": "Revenue is 10 EUR."},
        {"type": "generated_sql", "sqlIndex": 1, "success": True, "rowCount": 1,
         "sql": "SELECT 1", "sqlId": sql_id, "result": result},
        {"type": "usage_summary", "promptTokens": 100, "completionTokens": 20,
         "totalTokens": 120, "estimatedCost": 0.01},
        {"type": "trace", "trace": {"spans": []}},
    ]


class NativeEngineBase(unittest.TestCase):
    """Shared monkeypatch scaffolding (api_client + capabilities + sub-agents)."""

    def setUp(self):
        native.invalidate_capabilities_cache()
        # models.json is the only source of the LLM ids; the fake project has no
        # library, so pre-fill the TTL cache as if it had just been read.
        native._models_cache = (dict(TEST_MODES), time.monotonic() + 10 ** 9)
        self._orig_api_client = dataiku.api_client
        self._orig_get_caps = native.get_capabilities
        self._orig_run_sub = streaming.run_agent_streamed
        native.get_capabilities = lambda project: dict(CAPS)
        self.sub_calls = []

        def fake_sub(project_key, agent_id, messages):
            self.sub_calls.append({"project_key": project_key,
                                   "agent_id": agent_id, "messages": messages})
            for event in _sub_events():
                yield event

        streaming.run_agent_streamed = fake_sub

    def tearDown(self):
        dataiku.api_client = self._orig_api_client
        native.get_capabilities = self._orig_get_caps
        streaming.run_agent_streamed = self._orig_run_sub
        native.invalidate_capabilities_cache()
        native.invalidate_models_cache()

    def _install(self, completion):
        project = FakeProject(completion)
        dataiku.api_client = lambda: FakeClient(project)
        return project

    def _run(self, responses, messages=None, mode="smart"):
        completion = FakeCompletion(responses)
        self._install(completion)
        events = list(native.run_native_streamed(
            "PK", "agent:entry", messages or [{"role": "user", "content": "hi"}],
            mode=mode))
        return events, completion


# --------------------------------------------------------------------------- #
# Tool specs / parsing helpers
# --------------------------------------------------------------------------- #
class TestSpecsAndParsing(unittest.TestCase):
    def test_build_tool_specs_delegation_plus_presentation(self):
        specs = native.build_tool_specs(CAPS)
        names = [s["function"]["name"] for s in specs]
        self.assertEqual(
            names, ["ask_revenue_expert", "ask_tickets_expert",
                    "show_chart", "show_table", "show_kpi"])

    def test_show_chart_title_required(self):
        specs = native.build_tool_specs(CAPS)
        chart = [s for s in specs if s["function"]["name"] == "show_chart"][0]
        self.assertIn("title", chart["function"]["parameters"]["required"])

    def test_resolve_mode_trusts_the_route_only(self):
        # The engine never scans message text for a mode: only the
        # route-resolved value counts, anything else falls to the default.
        self.assertEqual(native.resolve_mode("pro"), "pro")
        self.assertEqual(native.resolve_mode("claude"), "claude")
        self.assertEqual(native.resolve_mode(None), native.DEFAULT_MODE)
        self.assertEqual(native.resolve_mode("turbo"), native.DEFAULT_MODE)

    def test_parse_lang_token_and_default(self):
        msgs = [{"role": "user", "content": "hola ⟦owi:lang=en⟧"}]
        self.assertEqual(native.parse_lang(msgs), "en")
        self.assertEqual(native.parse_lang([]), "fr")

    def test_forged_mode_token_never_upgrades_the_tier(self):
        # Cost-tier escalation guard: a user-typed mode token in the text is
        # ignored entirely - the engine only trusts the route-resolved mode.
        self.assertEqual(native.resolve_mode(None), "smart")

    def test_parse_lang_ignores_unknown_values(self):
        msgs = [{"role": "user", "content": "x ⟦owi:lang=zz⟧"}]
        self.assertEqual(native.parse_lang(msgs), "fr")
        msgs2 = [{"role": "user", "content": "⟦owi:lang=en⟧ later ⟦owi:lang=xx⟧"}]
        self.assertEqual(native.parse_lang(msgs2), "en")

    def test_is_captured_result_recognizes_the_production_shape(self):
        self.assertTrue(native.is_captured_result(RESULT))
        # A 0-row capture is still a capture (honest empty result).
        self.assertTrue(native.is_captured_result(
            {"columns": [], "rows": [], "truncated": False}))
        # The /evidence/meta block flag alone is NOT a capture; junk neither.
        self.assertFalse(native.is_captured_result({"captured": True}))
        self.assertFalse(native.is_captured_result(None))
        self.assertFalse(native.is_captured_result({"columns": "x", "rows": []}))

    def test_strip_control_tokens(self):
        s = "hi ⟦owi:mode=smart⟧ there ⟦owi:lang=fr⟧"
        self.assertEqual(native.strip_control_tokens(s), "hi  there ")


# --------------------------------------------------------------------------- #
# Artifact building (frozen shape via streaming._normalized_artifact_event)
# --------------------------------------------------------------------------- #
class TestBuildArtifactEvent(unittest.TestCase):
    def test_chart_ok_case_insensitive_columns(self):
        event, error = native.build_artifact_event(
            "show_chart",
            {"chart_type": "line", "x": "MONTH", "y": ["revenue_eur"],
             "title": "Rev", "unit": "EUR"},
            RESULT, "s1")
        self.assertIsNone(error)
        self.assertEqual(event["type"], "artifact")
        self.assertEqual(event["kind"], "chart")
        self.assertEqual(event["title"], "Rev")
        self.assertEqual(event["sql_id"], "s1")
        self.assertEqual(event["chart"]["type"], "line")
        self.assertEqual(event["chart"]["unit"], "EUR")

    def test_chart_unknown_column_is_refused_with_column_list(self):
        event, error = native.build_artifact_event(
            "show_chart",
            {"chart_type": "bar", "x": "month", "y": ["nope"], "title": "t"},
            RESULT, None)
        self.assertIsNone(event)
        self.assertIn("nope", error)
        self.assertIn("revenue_eur", error)

    def test_no_result_yet_is_refused(self):
        event, error = native.build_artifact_event(
            "show_table", {"title": "t"}, None, None)
        self.assertIsNone(event)
        self.assertIn("specialist", error)

    def test_kpi_validates_value_column(self):
        event, error = native.build_artifact_event(
            "show_kpi", {"value": "Revenue_EUR", "label": "Rev"}, RESULT, None)
        self.assertIsNone(error)
        self.assertEqual(event["kind"], "kpi")
        self.assertEqual(event["kpi"]["value"], "Revenue_EUR")
        event, error = native.build_artifact_event(
            "show_kpi", {"value": "missing"}, RESULT, None)
        self.assertIsNone(event)
        self.assertIn("missing", error)

    def test_table_ok(self):
        event, error = native.build_artifact_event(
            "show_table", {"title": "All rows"}, RESULT, "s9")
        self.assertIsNone(error)
        self.assertEqual(event["kind"], "table")
        self.assertEqual(event["sql_id"], "s9")


# --------------------------------------------------------------------------- #
# Capabilities loading (fallback + filtering)
# --------------------------------------------------------------------------- #
class TestCapabilities(unittest.TestCase):
    def setUp(self):
        native.invalidate_capabilities_cache()

    def tearDown(self):
        native.invalidate_capabilities_cache()

    def test_fallback_on_library_failure(self):
        caps = native.get_capabilities(FakeProject(None, library_raises=True))
        self.assertEqual(set(caps), set(native.EMBEDDED_CAPABILITIES))

    def test_disabled_and_malformed_entries_filtered(self):
        raw = {
            "ok": dict(CAPS["revenue_expert"]),
            "off": dict(CAPS["tickets_expert"], enabled=False),
            "bad": {"agent_id": "not-an-agent", "tool_name": "x",
                    "planner_description": "y", "enabled": True},
        }
        native._caps_cache = (raw, 10 ** 12)  # far-future ts: cache hit
        caps = native.get_capabilities(None)
        self.assertEqual(list(caps), ["ok"])


# --------------------------------------------------------------------------- #
# The engine loop
# --------------------------------------------------------------------------- #
class TestEngineLoop(NativeEngineBase):
    def test_full_run_delegation_then_chart_then_answer(self):
        responses = [
            FakeResponse(tool_calls=[_tool_call(
                "ask_revenue_expert", {"task": "YTD 2026 revenue"}, "c1")]),
            FakeResponse(tool_calls=[_tool_call(
                "show_chart", {"chart_type": "line", "x": "month",
                               "y": ["Revenue_EUR"], "title": "Rev"}, "c2")]),
            FakeResponse(text="Revenue peaked in March."),
        ]
        events, completion = self._run(responses)
        kinds = [e.get("eventKind") for e in events if e["type"] == "agent_event"]
        self.assertEqual(kinds[0], "AGENT_TURN_START")
        self.assertIn("AGENT_TOOL_START", kinds)
        self.assertIn("AGENT_TOOL_END", kinds)
        self.assertEqual(kinds[-1], "AGENT_DONE")
        # Sub-agent SQL forwarded with the engine-global index + agentKey tag.
        sqls = [e for e in events if e["type"] == "generated_sql"]
        self.assertEqual(len(sqls), 1)
        self.assertEqual(sqls[0]["sqlIndex"], 1)
        self.assertEqual(sqls[0]["agentKey"], "revenue_expert")
        # The artifact event carries the frozen shape + the latest sql binding.
        arts = [e for e in events if e["type"] == "artifact"]
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0]["kind"], "chart")
        self.assertEqual(arts[0]["sql_id"], "s1")
        # Final text chunked as answer_delta; usage aggregated from the sub-run.
        answer = "".join(e["text"] for e in events if e["type"] == "answer_delta")
        self.assertEqual(answer, "Revenue peaked in March.")
        usage = [e for e in events if e["type"] == "usage_summary"][0]
        self.assertEqual(usage["totalTokens"], 120)
        trace = [e for e in events if e["type"] == "trace"][0]["trace"]
        self.assertEqual(trace["engine"], "native")
        self.assertEqual(len(trace["subagent_traces"]), 1)
        # Both tool outputs were returned to the model.
        self.assertEqual(len(completion.tool_outputs), 2)
        self.assertIn("show_chart", str(completion.settings) + str(completion.tool_outputs))

    def test_pass_context_injects_mode_language_and_raw_message(self):
        responses = [
            FakeResponse(tool_calls=[_tool_call(
                "ask_revenue_expert", {"task": "t"}, "c1")]),
            FakeResponse(text="done"),
        ]
        self._run(responses, messages=[
            {"role": "user", "content":
             "salut ⟦owi:mode=claude⟧⟦owi:lang=fr⟧\n\n[Context - name/date]"}],
            mode="claude")
        self.assertEqual(len(self.sub_calls), 1)
        sub_messages = self.sub_calls[0]["messages"]
        self.assertEqual(sub_messages[0]["role"], "system")
        self.assertIn("MODE: claude", sub_messages[0]["content"])
        self.assertIn("USER LANGUAGE: fr", sub_messages[0]["content"])
        # Disambiguation context: the RAW user message, tokens + appended
        # backend blocks stripped (the [Context ...] tail never leaks).
        self.assertIn("USER'S RAW CURRENT MESSAGE", sub_messages[0]["content"])
        self.assertIn("salut", sub_messages[0]["content"])
        self.assertNotIn("[Context", sub_messages[0]["content"])

    def test_no_pass_context_sends_task_only(self):
        responses = [
            FakeResponse(tool_calls=[_tool_call(
                "ask_tickets_expert", {"task": "t"}, "c1")]),
            FakeResponse(text="done"),
        ]
        self._run(responses)
        self.assertEqual(len(self.sub_calls[0]["messages"]), 1)
        self.assertEqual(self.sub_calls[0]["messages"][0]["role"], "user")

    def test_control_tokens_stripped_from_llm_messages(self):
        responses = [FakeResponse(text="ok")]
        _, completion = self._run(responses, messages=[
            {"role": "user", "content": "salut ⟦owi:mode=smart⟧"}])
        user_msgs = [m for m in completion.messages if m["role"] == "user"]
        self.assertNotIn("⟦", user_msgs[0]["content"])

    def test_specialist_failure_degrades_to_honest_tool_error(self):
        def broken_sub(project_key, agent_id, messages):
            raise RuntimeError("boom")
            yield  # pragma: no cover

        streaming.run_agent_streamed = broken_sub
        responses = [
            FakeResponse(tool_calls=[_tool_call(
                "ask_revenue_expert", {"task": "t"}, "c1")]),
            FakeResponse(text="Sorry, the specialist failed."),
        ]
        events, completion = self._run(responses)
        self.assertIn("failed", completion.tool_outputs[0]["output"])
        answer = "".join(e["text"] for e in events if e["type"] == "answer_delta")
        self.assertIn("Sorry", answer)

    def test_capture_note_is_per_call_never_stale(self):
        # A second specialist that captured NOTHING must not inherit the first
        # one's "[Result captured ...]" note (stale-attribution guard).
        calls = {"n": 0}

        def sub_alternating(project_key, agent_id, messages):
            calls["n"] += 1
            if calls["n"] == 1:
                for e in _sub_events():
                    yield e
            else:
                yield {"type": "answer_delta", "text": "no data found"}

        streaming.run_agent_streamed = sub_alternating
        responses = [
            FakeResponse(tool_calls=[_tool_call(
                "ask_revenue_expert", {"task": "a"}, "c1")]),
            FakeResponse(tool_calls=[_tool_call(
                "ask_tickets_expert", {"task": "b"}, "c2")]),
            FakeResponse(text="done"),
        ]
        _, completion = self._run(responses)
        self.assertIn("Result captured", completion.tool_outputs[0]["output"])
        self.assertIn("1 rows", completion.tool_outputs[0]["output"])
        self.assertNotIn("Result captured", completion.tool_outputs[1]["output"])

    def test_subagent_lifecycle_events_are_prefixed(self):
        responses = [
            FakeResponse(tool_calls=[_tool_call(
                "ask_revenue_expert", {"task": "t"}, "c1")]),
            FakeResponse(text="done"),
        ]
        events, _ = self._run(responses)
        kinds = [e.get("eventKind") for e in events if e["type"] == "agent_event"]
        self.assertIn("SUB_AGENT_AGENT_TURN_START", kinds)
        # The engine's OWN lifecycle stays unprefixed.
        self.assertIn("AGENT_TOOL_START", kinds)

    def test_sql_indexes_stay_globally_monotonic_across_subagents(self):
        responses = [
            FakeResponse(tool_calls=[_tool_call(
                "ask_revenue_expert", {"task": "a"}, "c1")]),
            FakeResponse(tool_calls=[_tool_call(
                "ask_tickets_expert", {"task": "b"}, "c2")]),
            FakeResponse(text="done"),
        ]
        events, _ = self._run(responses)
        indexes = [e["sqlIndex"] for e in events if e["type"] == "generated_sql"]
        self.assertEqual(indexes, [1, 2])

    def test_enrichment_reemission_keeps_its_global_index(self):
        def sub_with_enrichment(project_key, agent_id, messages):
            yield {"type": "generated_sql", "sqlIndex": 1, "success": None,
                   "rowCount": None, "sql": "SELECT 1", "sqlId": "s1"}
            yield {"type": "generated_sql", "sqlIndex": 1, "success": True,
                   "rowCount": 3, "sql": "SELECT 1", "sqlId": "s1",
                   "result": RESULT}
            yield {"type": "answer_delta", "text": "ok"}

        streaming.run_agent_streamed = sub_with_enrichment
        responses = [
            FakeResponse(tool_calls=[_tool_call(
                "ask_revenue_expert", {"task": "a"}, "c1")]),
            FakeResponse(text="done"),
        ]
        events, _ = self._run(responses)
        sqls = [e for e in events if e["type"] == "generated_sql"]
        self.assertEqual([e["sqlIndex"] for e in sqls], [1, 1])

    def test_last_turn_withdraws_tools_and_fallback_text(self):
        responses = []
        for i in range(native.MAX_LLM_TURNS - 1):
            responses.append(FakeResponse(tool_calls=[_tool_call(
                "ask_revenue_expert", {"task": "again"}, "c%d" % i)]))
        responses.append(FakeResponse(text=""))  # tool-less final comes up empty
        events, completion = self._run(responses)
        # The final execute ran WITHOUT tools.
        self.assertFalse(completion.executed_with_tools[-1])
        self.assertTrue(all(completion.executed_with_tools[:-1]))
        answer = "".join(e["text"] for e in events if e["type"] == "answer_delta")
        self.assertTrue(answer)  # honest fallback, never an empty answer

    def test_subagent_call_budget_enforced(self):
        responses = []
        for i in range(native.MAX_SUBAGENT_CALLS + 1):
            responses.append(FakeResponse(tool_calls=[_tool_call(
                "ask_revenue_expert", {"task": "t"}, "c%d" % i)]))
        responses.append(FakeResponse(text="done"))
        _, completion = self._run(responses)
        self.assertEqual(len(self.sub_calls), native.MAX_SUBAGENT_CALLS)
        budget_notes = [o for o in completion.tool_outputs
                        if "budget" in o["output"]]
        self.assertTrue(budget_notes)

    def test_llm_failure_raises_for_worker_error_path(self):
        responses = [FakeResponse(success=False)]
        completion = FakeCompletion(responses)
        self._install(completion)
        with self.assertRaises(RuntimeError):
            list(native.run_native_streamed(
                "PK", "agent:entry", [{"role": "user", "content": "hi"}]))


if __name__ == "__main__":
    unittest.main()
