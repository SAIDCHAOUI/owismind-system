"""DSS-free graph tests for the orchestrator WORKSPACE tools (V2.0, phase 2).

The real agent graph (node_agent -> node_tools -> node_finish) is executed by a
small fake LangGraph runner, with a scripted LLM Mesh (loop model + sub-agents) and
a fake trace. Covered:
  - plan first: write_plan + specialist calls in one batch -> plan.set (origin
    model) BEFORE the sub-agent runs, steps running -> done around each call,
    prov.set per captured SQL (task, agent, step, row_count), result_ids handed
    to the model;
  - publish_widget binds to an EXPLICIT result_id; an unknown or missing id is
    refused with the list of available ids (never a "latest" fallback); a legacy
    ARTIFACT is still emitted for data widgets (D3);
  - auto plan (D4, lazy since 2026-10-22) when the model skips write_plan, and
    the auto-table safety net
    bound to the exact result id;
  - node_finish closes a step left 'running' (error + honest note);
  - recall: the recalled rows get their own result_id (s0q1), stamped on the
    evidence span, publishable as a widget;
  - EVERY emitted WORKSPACE op is accepted by the backend contract normalizer
    (plugin python-lib owismind.workspace.protocol) and reduces cleanly;
  - _Workspace caps (12 widgets, 30 notes, 10 steps, 80 events, 200 KB) and ids;
  - Studio continuity: ⟦owi:studio⟧ parse / strip, edit_studio exposed only with
    the token, the publish-before-decision guard (once), continue -> studio.continue
    (+ remove), ids allocated past the carried ones, replaces, widget.remove,
    refusal when the board would exceed 12 widgets, new mode.
"""

import importlib.util
import json
import os
import sys
import unittest

import _agent_stubs

_agent_stubs.install()

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_MIRROR_DIR = os.path.dirname(_TESTS_DIR)
sys.path.insert(0, os.path.join(_MIRROR_DIR, "plugin", "owismind", "python-lib"))

from owismind.workspace import protocol as ws_protocol  # noqa: E402
from owismind.workspace import reducer as ws_reducer    # noqa: E402


def _load(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


orch = _load("orchestrator_workspace_under_test",
             os.path.join(_MIRROR_DIR, "GenAI", "Agents", "OWIsMind_orchestrator.py"))

REVENUE_ID = orch.CAPABILITIES["revenue_expert"]["agent_id"]
TICKETS_ID = orch.CAPABILITIES["tickets_expert"]["agent_id"]


# =============================================================================
# Fakes: LLM Mesh, trace, LangGraph runner
# =============================================================================

class Resp(object):
    def __init__(self, text="", tool_calls=None):
        self.text = text
        self.tool_calls = tool_calls or []
        self.trace = None
        self.total_usage = {"promptTokens": 1, "completionTokens": 1,
                            "totalTokens": 2, "estimatedCost": 0.0}


def call(cid, name, **args):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


class _Chunk(object):
    def __init__(self, data):
        self.data = data


def _sub_stream(sql, columns, rows, answer="[Scope] ACTUALS 2025."):
    trace = {"name": "root", "children": [{
        "name": "semantic-model-query",
        "outputs": {"sql": sql, "success": True, "row_count": len(rows),
                    "columns": columns, "rows": rows}}]}
    return [{"type": "event", "eventKind": "AGENT_RESULT",
             "eventData": {"status": "ready", "intent": "breakdown"}},
            {"type": "text", "text": answer},
            {"type": "footer", "trace": trace}]


class FakeCompletion(object):
    def __init__(self, project, llm_id):
        self.project, self.llm_id = project, llm_id
        self.settings = {}
        self.messages = []
        project.completions.append(self)

    def with_message(self, content, role="user"):
        self.messages.append((role, content))
        return self

    def with_tool_calls(self, *a, **k):
        return self

    def with_tool_output(self, output, tool_call_id=None):
        self.project.tool_outputs[tool_call_id] = output
        return self

    def execute(self):
        return self.project.responses.pop(0) if self.project.responses else Resp("")

    def execute_streamed(self):
        for data in self.project.sub_streams.get(self.llm_id, []):
            yield _Chunk(data)


class FakeProject(object):
    def __init__(self, responses, sub_streams=None):
        self.responses = list(responses)
        self.sub_streams = sub_streams or {}
        self.tool_outputs = {}
        self.completions = []

    def get_llm(self, llm_id):
        project = self

        class _LLM(object):
            def new_completion(self_inner):
                return FakeCompletion(project, llm_id)
        return _LLM()


class FakeClient(object):
    def __init__(self, project):
        self._project = project

    def get_default_project(self):
        return self._project


class FakeSpan(object):
    def __init__(self, name, sink):
        self.name, self.outputs, self.attributes = name, {}, {}
        sink.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def append_trace(self, *a, **k):
        pass


class FakeTrace(object):
    def __init__(self):
        self.spans = []

    def subspan(self, name):
        return FakeSpan(name, self.spans)

    def append_trace(self, *a, **k):
        pass


class _Runner(object):
    """agent -> (tools -> agent)* -> finish, merging updates like OrchState."""

    def __init__(self, nodes, route):
        self.nodes, self.route = nodes, route

    def stream(self, initial, stream_mode=None, config=None):
        chunks = []
        previous = orch.get_stream_writer
        orch.get_stream_writer = lambda: chunks.append
        state = dict(initial)
        try:
            for _ in range(40):
                self._merge(state, self.nodes["agent"](state))
                if self.route(state) == "tools":
                    self._merge(state, self.nodes["tools"](state))
                    continue
                self.nodes["finish"](state)
                break
        finally:
            orch.get_stream_writer = previous
        return iter(chunks)

    @staticmethod
    def _merge(state, upd):
        for key, value in (upd or {}).items():
            if key in ("captured", "artifacts", "rendered", "statuses"):
                state[key] = list(state.get(key) or []) + list(value or [])
            elif key == "usage":
                state[key] = orch._sum_usage(state.get(key) or {}, value or {})
            elif key == "used_caps":
                state[key] = orch._add_unique(state.get(key) or [], value or [])
            else:
                state[key] = value


class _Graph(object):
    def __init__(self, *a, **k):
        self.nodes, self.route = {}, None

    def add_node(self, name, fn):
        self.nodes[name] = fn

    def add_edge(self, *a, **k):
        pass

    def add_conditional_edges(self, source, route, mapping):
        self.route = route

    def compile(self):
        return _Runner(self.nodes, self.route)


class GraphCase(unittest.TestCase):
    def setUp(self):
        self._saved = (orch.dataiku.api_client, orch.StateGraph, orch.get_stream_writer)
        orch.StateGraph = _Graph
        _agent_stubs.pin_models(orch)

    def tearDown(self):
        orch.dataiku.api_client, orch.StateGraph, orch.get_stream_writer = self._saved

    def run_turn(self, message, responses, sub_streams=None):
        project = FakeProject(responses, sub_streams)
        orch.dataiku.api_client = lambda: FakeClient(project)
        trace = FakeTrace()
        query = {"messages": [{"role": "user",
                               "content": message + " ⟦owi:mode=pro⟧⟦owi:lang=fr⟧"}]}
        chunks = list(orch.MyLLM().process_stream(query, {}, trace))
        self.project, self.trace = project, trace
        return [c["chunk"] for c in chunks]

    @staticmethod
    def ws_ops(chunks):
        return [c["eventData"] for c in chunks
                if c.get("type") == "event" and c.get("eventKind") == "WORKSPACE"]

    @staticmethod
    def kinds(chunks):
        return [c.get("eventKind") for c in chunks if c.get("type") == "event"]

    def assert_contract(self, ops):
        """Every op passes the backend normalizer unchanged (minus type) and the
        sequence is strictly increasing from 1."""
        self.assertEqual([o["seq"] for o in ops], list(range(1, len(ops) + 1)))
        events = []
        for op in ops:
            norm = ws_protocol.normalize_op(op)
            self.assertIsNotNone(norm, op)
            self.assertEqual({k: v for k, v in norm.items() if k != "type"}, op)
            events.append(norm)
        return ws_reducer.reduce_events(events)


REV_STREAM = _sub_stream("SELECT region, SUM(revenue) AS revenue FROM s GROUP BY region",
                         ["region", "revenue"], [["Nord", 1200], ["Sud", 950]])
TIX_STREAM = _sub_stream("SELECT region, COUNT(*) AS open_tickets FROM t GROUP BY region",
                         ["region", "open_tickets"], [["Nord", 41], ["Sud", 30]])


# =============================================================================
# Graph scenarios
# =============================================================================

class TestPlanFirstMultiFacet(GraphCase):
    def setUp(self):
        super().setUp()
        responses = [
            Resp("", [
                call("c1", "write_plan", mission="CA et tickets par region",
                     steps=[{"label": "CA par region", "total": 2, "unit": "regions"},
                            {"label": "Tickets ouverts par region"}]),
                call("c2", "ask_revenue_expert", task="CA 2025 par region", step="p1"),
                call("c3", "ask_tickets_expert", task="Tickets ouverts par region"),
            ]),
            Resp("", [
                call("c4", "publish_widget", kind="chart", title="CA 2025 par region",
                     result_id="s1q1", chart_type="bar", x="REGION", y=["revenue"],
                     unit="EUR", comment="Le Nord mene."),
                call("c5", "publish_widget", kind="table", title="Tickets",
                     result_id="s2q1"),
                call("c6", "publish_widget", kind="chart", title="Mauvais",
                     result_id="s9q9", chart_type="bar", x="region", y=["revenue"]),
                call("c7", "publish_widget", kind="kpi", title="Sans id",
                     kpi_value="revenue"),
                call("c8", "write_note", title="Le Nord mene", kind="find",
                     text="1 200 contre 950.", step="p1", result_id="s1q1"),
                call("c9", "publish_widget", kind="text", title="Synthese",
                     text="**Nord** en tete.", step="2"),
            ]),
            Resp("Bilan : le Nord mene."),
        ]
        self.chunks = self.run_turn("CA et tickets par region", responses,
                                    {REVENUE_ID: REV_STREAM, TICKETS_ID: TIX_STREAM})
        self.ops = self.ws_ops(self.chunks)

    def test_plan_emitted_before_any_specialist(self):
        kinds = self.kinds(self.chunks)
        first_ws = kinds.index("WORKSPACE")
        self.assertLess(first_ws, kinds.index("CALLING_AGENT"))
        plan = self.ops[0]
        self.assertEqual(plan["op"], "plan.set")
        self.assertEqual(plan["origin"], "model")
        self.assertEqual([s["id"] for s in plan["steps"]], ["p1", "p2"])
        self.assertEqual(plan["steps"][0]["total"], 2)

    def test_steps_run_then_done_and_provenance(self):
        step_ops = [(o["step_id"], o.get("status")) for o in self.ops if o["op"] == "plan.step"]
        self.assertIn(("p1", "running"), step_ops)
        self.assertIn(("p2", "running"), step_ops)
        self.assertIn(("p1", "done"), step_ops)
        self.assertIn(("p2", "done"), step_ops)
        prov = {o["sql_id"]: o for o in self.ops if o["op"] == "prov.set"}
        self.assertEqual(sorted(prov), ["s1q1", "s2q1"])
        self.assertEqual(prov["s1q1"]["agent_key"], "revenue_expert")
        self.assertEqual(prov["s1q1"]["task"], "CA 2025 par region")
        self.assertEqual(prov["s1q1"]["step_id"], "p1")
        self.assertEqual(prov["s2q1"]["step_id"], "p2")
        self.assertEqual(prov["s1q1"]["row_count"], 2)
        self.assertEqual(prov["s1q1"]["tool"], "semantic-model-query")

    def test_result_ids_handed_to_the_model(self):
        out = self.project.tool_outputs["c2"]
        self.assertTrue(out.startswith("STEP: p1"))
        self.assertIn("RESULT_IDS: s1q1 (2 rows; columns: region, revenue)", out)
        self.assertIn("publish_widget", out)
        self.assertIn("Plan written: p1 'CA par region'", self.project.tool_outputs["c1"])

    def test_widgets_bound_to_explicit_ids_never_latest(self):
        widgets = [o for o in self.ops if o["op"] == "widget.add"]
        self.assertEqual([(w["id"], w["kind"], w.get("sql_id")) for w in widgets],
                         [("w1", "chart", "s1q1"), ("w2", "table", "s2q1"),
                          ("w3", "text", None)])
        # Columns resolved to the EXACT result spelling; step from the result.
        self.assertEqual(widgets[0]["chart"]["x"], "region")
        self.assertEqual(widgets[0]["step_id"], "p1")
        self.assertEqual(widgets[1]["step_id"], "p2")
        self.assertEqual(widgets[2]["step_id"], "p2")       # step "2" -> p2
        self.assertIn("Unknown result_id 's9q9'", self.project.tool_outputs["c6"])
        self.assertIn("s1q1", self.project.tool_outputs["c6"])
        self.assertIn("result_id is REQUIRED", self.project.tool_outputs["c7"])

    def test_note_and_legacy_artifacts(self):
        notes = [o for o in self.ops if o["op"] == "note.add"]
        self.assertEqual(notes[0]["sql_id"], "s1q1")
        self.assertEqual(notes[0]["step_id"], "p1")
        artifacts = [c["eventData"] for c in self.chunks
                     if c.get("eventKind") == "ARTIFACT"]
        self.assertEqual([(a["kind"], a["sql_id"]) for a in artifacts],
                         [("chart", "s1q1"), ("table", "s2q1")])

    def test_every_op_matches_the_backend_contract(self):
        state = self.assert_contract(self.ops)
        self.assertEqual([s["status"] for s in state["plan"]["steps"]], ["done", "done"])
        self.assertEqual(len(state["widgets"]), 3)
        self.assertEqual(state["summary"]["sql_ids"], ["s1q1", "s2q1"])


class TestAutoPlanAndSafetyNet(GraphCase):
    def test_auto_plan_and_auto_table(self):
        chunks = self.run_turn("CA par region", [
            Resp("", [call("c1", "ask_revenue_expert", task="CA 2025 par region")]),
            Resp("Voici le CA."),
        ], {REVENUE_ID: REV_STREAM})
        ops = self.ws_ops(chunks)
        # Lazy D4: ONE specialist call and no section text -> no auto plan.
        self.assertNotIn("plan.set", [o["op"] for o in ops])
        self.assertNotIn("PLAN AUTO-CREATED", self.project.tool_outputs["c1"])
        # The model published nothing: the safety net adds a table bound to s1q1.
        widgets = [o for o in ops if o["op"] == "widget.add"]
        self.assertEqual(len(widgets), 1)
        self.assertEqual((widgets[0]["kind"], widgets[0]["sql_id"]), ("table", "s1q1"))
        self.assert_contract(ops)

    def test_no_data_turn_emits_no_workspace(self):
        chunks = self.run_turn("Bonjour", [Resp("Bonjour !")])
        self.assertEqual(self.ws_ops(chunks), [])


class TestFinishClosesRunningSteps(GraphCase):
    def test_running_step_without_result_closed_as_error(self):
        chunks = self.run_turn("Analyse", [
            Resp("", [call("c1", "write_plan", mission="Analyse",
                           steps=["Etape A", "Etape B"]),
                      call("c2", "update_plan", step="p2", status="running"),
                      call("c3", "update_plan", step="p9", status="done")]),
            Resp("Fini."),
        ])
        ops = self.ws_ops(chunks)
        self.assertIn("Unknown step 'p9'", self.project.tool_outputs["c3"])
        state = self.assert_contract(ops)
        self.assertEqual([s["status"] for s in state["plan"]["steps"]], ["todo", "error"])
        self.assertEqual(state["notes"][-1]["kind"], "done")
        self.assertEqual(state["notes"][-1]["step_id"], "p2")

    def test_update_plan_without_plan_refused(self):
        self.run_turn("x", [Resp("", [call("c1", "update_plan", step="p1",
                                           status="done")]), Resp("ok")])
        self.assertIn("call write_plan first", self.project.tool_outputs["c1"])


class TestRecallIsPublishable(GraphCase):
    def test_recalled_rows_get_their_own_result_id(self):
        prior = [{"question": "CA par region", "sql": "SELECT 1",
                  "columns": ["region", "revenue"], "rows": [["Nord", "1200"]],
                  "row_count": 1}]
        token = "⟦owi:prior=%s⟧" % json.dumps(prior)
        chunks = self.run_turn("Remontre le CA " + token, [
            Resp("", [call("c1", "recall_prior_result")]),
            Resp("", [call("c2", "publish_widget", kind="table", title="CA rappele",
                           result_id="s0q1")]),
            Resp("Le voici."),
        ])
        self.assertIn("RESULT_IDS: s0q1", self.project.tool_outputs["c1"])
        widgets = [o for o in self.ws_ops(chunks) if o["op"] == "widget.add"]
        self.assertEqual(widgets[0]["sql_id"], "s0q1")
        span = [s for s in self.trace.spans if s.name == "semantic-model-query"][0]
        self.assertEqual(span.outputs["sql_id"], "s0q1")
        self.assert_contract(self.ws_ops(chunks))


class TestStudioReport(GraphCase):
    """Studio-first analysis: the intro text widget published with write_plan is
    shown BEFORE the specialist runs; the theme text precedes its data widget; a
    text widget binds to a result only when that result exists in the run."""

    def setUp(self):
        super().setUp()
        self.chunks = self.run_turn("Analyse 360 du CA", [
            Resp("", [
                call("c1", "write_plan", mission="Analyse 360 du CA",
                     steps=["CA par region"]),
                call("c2", "publish_widget", kind="text", title="Perimetre",
                     text="CA ACTUALS 2025, toutes regions.", result_id="s1q1"),
                call("c3", "ask_revenue_expert", task="CA 2025 par region"),
            ]),
            Resp("", [
                call("c4", "publish_widget", kind="text", title="CA par region",
                     text="Le **Nord** mene avec 1 200 EUR.", result_id="s1q1",
                     step="p1"),
                call("c5", "publish_widget", kind="chart", title="CA 2025 par region",
                     result_id="s1q1", chart_type="bar", x="region", y=["revenue"]),
                call("c6", "publish_widget", kind="text", title="Synthese",
                     text="- Nord en tete"),
            ]),
            Resp("Le Nord mene. Le detail est dans le Studio."),
        ], {REVENUE_ID: REV_STREAM})
        self.ops = self.ws_ops(self.chunks)

    def test_intro_text_published_before_the_specialist_runs(self):
        events = [c for c in self.chunks if c.get("type") == "event"]
        intro_at = next(i for i, c in enumerate(events)
                        if c.get("eventKind") == "WORKSPACE"
                        and c["eventData"].get("op") == "widget.add")
        calling_at = next(i for i, c in enumerate(events)
                          if c.get("eventKind") == "CALLING_AGENT")
        self.assertLess(intro_at, calling_at)
        self.assertIn("Text block w1 published in the Studio",
                      self.project.tool_outputs["c2"])

    def test_reading_order_and_honest_text_binding(self):
        widgets = [o for o in self.ops if o["op"] == "widget.add"]
        self.assertEqual([(w["id"], w["kind"], w.get("sql_id")) for w in widgets],
                         [("w1", "text", None),          # s1q1 did not exist yet
                          ("w2", "text", "s1q1"),
                          ("w3", "chart", "s1q1"),
                          ("w4", "text", None)])
        self.assertIn("Do not repeat its rows in the chat",
                      self.project.tool_outputs["c5"])
        state = self.assert_contract(self.ops)
        self.assertEqual(len(state["widgets"]), 4)

    def test_batch_with_a_data_widget_keeps_its_order(self):
        chunks = self.run_turn("Analyse", [
            Resp("", [call("c1", "ask_revenue_expert", task="CA 2025 par region")]),
            Resp("", [
                call("c2", "publish_widget", kind="table", title="CA", result_id="s1q1"),
                call("c3", "publish_widget", kind="text", title="Lecture",
                     text="Le Nord mene."),
                call("c4", "ask_tickets_expert", task="Tickets ouverts par region"),
            ]),
            Resp("Fini."),
        ], {REVENUE_ID: REV_STREAM, TICKETS_ID: TIX_STREAM})
        widgets = [o for o in self.ws_ops(chunks) if o["op"] == "widget.add"]
        self.assertEqual([w["kind"] for w in widgets], ["table", "text"])

    def test_prompt_states_the_studio_first_contract(self):
        prompt = orch.build_system_prompt(orch.CAPABILITIES, "fr")
        self.assertIn("THE STUDIO REPORT", prompt)
        self.assertIn("Synthèse et points clés", prompt)
        self.assertIn("3 to 6 lines", prompt)
        self.assertIn("SIMPLE QUESTION", prompt)
        self.assertIn("at most %d widgets" % orch.WS_MAX_WIDGETS, orch.PERSONA_DEFAULT)
        for dash in ("\u2014", "\u2013"):
            self.assertNotIn(dash, prompt)

    def test_prompt_states_the_dashboard_layout_rules(self):
        prompt = orch.build_system_prompt(orch.CAPABILITIES, "fr")
        self.assertIn("DENSE DASHBOARD", prompt)
        self.assertIn("role 'scope'", prompt)
        self.assertIn("Studio HEADER", prompt)
        self.assertIn("ONE SECTION PER BUSINESS THEME", prompt)
        self.assertIn("IMMEDIATELY followed by its chart or table", prompt)
        self.assertIn("size 'wide'", prompt)
        self.assertIn("NEVER a table that duplicates a chart", prompt)
        self.assertIn("SPACE RULE", prompt)
        self.assertIn("never two texts in a row except the closing synthesis", prompt)
        self.assertIn("never compute a new one yourself", prompt)   # anti-calculation kept

    def test_tool_schema_exposes_size_and_role(self):
        spec = next(t["function"] for t in orch._ws_tool_specs()
                    if t["function"]["name"] == "publish_widget")
        props = spec["parameters"]["properties"]
        self.assertEqual(props["size"]["enum"], ["normal", "wide"])
        self.assertEqual(props["role"]["enum"], ["section", "scope"])
        self.assertEqual(list(orch.WS_WIDGET_SIZES), list(ws_protocol.WIDGET_SIZES))
        self.assertEqual(list(orch.WS_TEXT_ROLES), list(ws_protocol.TEXT_ROLES))
        self.assertEqual(list(orch.WS_SIZED_WIDGET_KINDS),
                         list(ws_protocol.SIZED_WIDGET_KINDS))


class TestStudioLayoutHints(GraphCase):
    """size / role pass through to widget.add; the scope widget is published
    BEFORE the specialists run, even when the batch also carries a data widget."""

    def test_scope_first_and_hints_pass_through(self):
        chunks = self.run_turn("Analyse 360", [
            Resp("", [call("c1", "ask_revenue_expert", task="CA 2025 par region")]),
            Resp("", [
                call("c2", "publish_widget", kind="text", title="CA par region",
                     text="Le Nord mene.", role="section", size="wide"),
                call("c3", "publish_widget", kind="chart", title="CA par region",
                     result_id="s1q1", chart_type="bar", x="region", y=["revenue"],
                     size="wide", role="scope"),
                call("c4", "publish_widget", kind="text", title="Perimetre",
                     text="CA et tickets 2025.", role="scope"),
                call("c5", "publish_widget", kind="kpi", title="CA total",
                     result_id="s1q1", kpi_value="revenue", size="wide"),
                call("c6", "ask_tickets_expert", task="Tickets ouverts par region"),
            ]),
            Resp("Fini."),
        ], {REVENUE_ID: REV_STREAM, TICKETS_ID: TIX_STREAM})
        events = [c for c in chunks if c.get("type") == "event"]
        widget_at = [(i, c["eventData"]) for i, c in enumerate(events)
                     if c.get("eventKind") == "WORKSPACE"
                     and c["eventData"].get("op") == "widget.add"]
        calling_at = [i for i, c in enumerate(events)
                      if c.get("eventKind") == "CALLING_AGENT"]
        widgets = [w for _, w in widget_at]
        # Scope first and before the second specialist starts; then board order.
        self.assertEqual([w["title"] for w in widgets],
                         ["Perimetre", "CA par region", "CA par region", "CA total"])
        self.assertLess(widget_at[0][0], calling_at[-1])
        self.assertGreater(widget_at[1][0], calling_at[-1])
        scope, text, chart, kpi = widgets
        self.assertEqual(scope.get("role"), "scope")
        self.assertEqual(text.get("role"), "section")
        self.assertNotIn("size", text)                  # size is chart / table only
        self.assertEqual(chart.get("size"), "wide")
        self.assertNotIn("role", chart)                 # role is text only
        self.assertNotIn("size", kpi)
        state = self.assert_contract(self.ws_ops(chunks))
        self.assertEqual(state["widgets"][0]["role"], "scope")
        self.assertEqual(state["widgets"][2]["size"], "wide")

    def test_invalid_hints_dropped(self):
        chunks = self.run_turn("Analyse", [
            Resp("", [call("c1", "ask_revenue_expert", task="CA 2025 par region")]),
            Resp("", [
                call("c2", "publish_widget", kind="text", title="Lecture",
                     text="Le Nord mene.", role="header"),
                call("c3", "publish_widget", kind="table", title="CA",
                     result_id="s1q1", size="huge"),
            ]),
            Resp("Fini."),
        ], {REVENUE_ID: REV_STREAM})
        widgets = [o for o in self.ws_ops(chunks) if o["op"] == "widget.add"]
        self.assertEqual(len(widgets), 2)
        self.assertNotIn("role", widgets[0])
        self.assertNotIn("size", widgets[1])


class TestDuplicateWidgetGuard(GraphCase):
    """The same widget published twice in ONE run is not duplicated: kind +
    normalised title + sql_id (or the same body for an unbound text). The model
    gets the existing id; replaces and genuinely different widgets still pass."""

    def setUp(self):
        super().setUp()
        self.chunks = self.run_turn("Revenue review", [
            Resp("", [call("c1", "ask_revenue_expert", task="Revenue 2025 by region")]),
            Resp("", [
                call("c2", "publish_widget", kind="text", title="Revenue mix by offer",
                     text="**North leads.** Body.", result_id="s1q1"),
                call("c3", "publish_widget", kind="chart", title="Revenue by region",
                     result_id="s1q1", chart_type="bar", x="region", y=["revenue"]),
                call("c4", "publish_widget", kind="text", title="Note",
                     text="Same  body"),
            ]),
            Resp("", [
                # Same kind + title (case / spaces differ) + sql_id: duplicate.
                call("c5", "publish_widget", kind="text",
                     title="  revenue MIX   by offer ", text="Other body.",
                     result_id="s1q1"),
                # Same chart again: duplicate.
                call("c6", "publish_widget", kind="chart", title="Revenue by region",
                     result_id="s1q1", chart_type="line", x="region", y=["revenue"]),
                # Unbound text with the same title and body: duplicate.
                call("c7", "publish_widget", kind="text", title="note",
                     text=" same body "),
                # Unbound text, same title, different body: published.
                call("c8", "publish_widget", kind="text", title="Note",
                     text="A different body."),
                # An explicit replacement is never treated as a duplicate.
                call("c9", "publish_widget", kind="chart", title="Revenue by region",
                     result_id="s1q1", chart_type="pie", x="region", y=["revenue"],
                     replaces="w2"),
            ]),
            Resp("Done. The detail is in the Studio."),
        ], {REVENUE_ID: REV_STREAM})
        self.ops = self.ws_ops(self.chunks)

    def test_duplicates_are_refused_with_the_existing_id(self):
        out = self.project.tool_outputs
        self.assertIn("Widget w1 is already on the board, not duplicated", out["c5"])
        self.assertIn("Widget w2 is already on the board, not duplicated", out["c6"])
        self.assertIn("Widget w3 is already on the board, not duplicated", out["c7"])
        self.assertIn("Text block w4 published", out["c8"])
        self.assertIn("published in the Studio", out["c9"])
        self.assertIn("in place of w2", out["c9"])

    def test_board_holds_each_widget_once(self):
        adds = [o for o in self.ops if o["op"] == "widget.add"]
        self.assertEqual([w["id"] for w in adds], ["w1", "w2", "w3", "w4", "w5"])
        self.assertEqual(adds[-1].get("replaces"), "w2")
        state = self.assert_contract(self.ops)
        self.assertEqual(len(state["widgets"]), 4)
        # Only the two real data widgets emitted a legacy ARTIFACT (no duplicate).
        artifacts = [c for c in self.chunks if c.get("type") == "event"
                     and c.get("eventKind") == "ARTIFACT"]
        self.assertEqual(len(artifacts), 2)

    def test_signature_is_case_and_space_insensitive(self):
        sig = orch._Workspace.widget_signature
        self.assertEqual(sig({"kind": "kpi", "title": "Total  2025", "sql_id": "s1q1"}),
                         sig({"kind": "kpi", "title": "total 2025 ", "sql_id": "s1q1"}))
        self.assertNotEqual(sig({"kind": "kpi", "title": "Total", "sql_id": "s1q1"}),
                            sig({"kind": "kpi", "title": "Total", "sql_id": "s1q2"}))
        self.assertNotEqual(sig({"kind": "text", "title": "A", "text": "x"}),
                            sig({"kind": "text", "title": "A", "text": "y"}))


# =============================================================================
# _Workspace unit tests (caps + ids)
# =============================================================================

class TestWorkspaceCaps(unittest.TestCase):
    def setUp(self):
        self.out = []
        self.ws = orch._Workspace()
        self.w = self.out.append

    def ops(self):
        return [c["chunk"]["eventData"] for c in self.out]

    def test_plan_capped_and_ids_continue_after_replacement(self):
        ids = self.ws.set_plan(self.w, "M", ["s%d" % i for i in range(15)], "model")
        self.assertEqual(len(ids), orch.WS_MAX_PLAN_STEPS)
        ids2 = self.ws.set_plan(self.w, "M2", ["a", "b"], "model")
        self.assertEqual(ids2, ["p11", "p12"])
        self.assertIsNone(self.ws.set_plan(self.w, "", ["a"], "model"))
        self.assertIsNone(self.ws.set_plan(self.w, "M", [], "model"))

    def test_widget_and_note_caps(self):
        for i in range(15):
            self.ws.add_widget(self.w, {"kind": "text", "title": "t", "text": "x"})
        self.assertEqual(len(self.ws.widgets), orch.WS_MAX_WIDGETS)
        for i in range(35):
            self.ws.add_note(self.w, "n%d" % i)
        self.assertEqual(len(self.ws.notes), orch.WS_MAX_NOTES)

    def test_event_cap(self):
        for i in range(100):
            self.ws.set_prov(self.w, {"sql_id": "s%dq1" % (i + 1), "agent_key": "a"},
                             "semantic-model-query", "t", None, 1)
        self.assertEqual(len(self.ws.prov), orch.WS_MAX_PROVENANCE)
        for i in range(100):
            self.ws.add_note(self.w, "n")
        self.assertLessEqual(self.ws.seq, orch.WS_MAX_EVENTS)
        self.assertEqual(len(self.out), self.ws.seq)

    def test_document_size_cap(self):
        big = "x" * 3990
        n = 0
        while self.ws.add_widget(self.w, {"kind": "text", "title": "t", "text": big}):
            n += 1
        self.assertLessEqual(self.ws.chars, orch.WS_MAX_DOC_CHARS)
        self.assertEqual(n, orch.WS_MAX_WIDGETS)   # 12 x 4 KB stays under 200 KB

    def test_invalid_sql_id_never_provenanced(self):
        self.assertFalse(self.ws.set_prov(self.w, {"sql_id": "latest"},
                                          "semantic-model-query", "", None, 0))
        self.assertIsNone(self.ws.register_result({"sql_id": "x", "result": {}}))

    def test_all_ops_valid_for_backend(self):
        self.ws.set_plan(self.w, "M", [{"label": "A", "total": 3, "unit": "u"}], "auto")
        self.ws.update_step(self.w, "p1", status="running", done=1,
                            add_step={"label": "B"})
        self.ws.add_note(self.w, "T", "x" * 5000, kind="weird", step_id="p1")
        for op in self.ops():
            self.assertIsNotNone(ws_protocol.normalize_op(op), op)

    def test_bounds(self):
        self.assertEqual(orch.MAX_TOOL_LOOPS, 10)
        self.assertEqual(orch.WS_MAX_EVENTS, ws_protocol.MAX_WORKSPACE_EVENTS_PER_RUN)
        self.assertEqual(orch.WS_MAX_DOC_CHARS, ws_protocol.MAX_WORKSPACE_JSON_CHARS)
        self.assertEqual(orch.WS_CHART_TYPES, ws_protocol.CHART_TYPES)
        self.assertEqual(orch.WS_CHART_STYLES, ws_protocol.CHART_STYLES)
        self.assertEqual(orch.WS_NOTE_KINDS, ws_protocol.NOTE_KINDS)
        self.assertEqual(orch.WS_STEP_STATUSES, ws_protocol.STEP_STATUSES)


# =============================================================================
# Studio continuity (CURRENT STUDIO -> edit_studio continue / new)
# =============================================================================

STUDIO_IDS = ["w1", "w2", "w3"]


def studio_suffix(ids=STUDIO_IDS):
    block = ("\n\n[CURRENT STUDIO - the dashboard the user sees now, built earlier in "
             "THIS conversation from real queries]\nWidgets (board order): " +
             " | ".join("%s chart line \"T%s\"" % (w, w) for w in ids) +
             "\nCapacity: %d of 12 used, %d free." % (len(ids), 12 - len(ids)))
    return block + "⟦owi:studio=%s⟧" % json.dumps({"ids": ids, "n": len(ids)})


class TestStudioTokenParsing(unittest.TestCase):
    def test_parse_and_strip(self):
        studio, cleaned = orch.parse_studio("Ajoute 2025" + studio_suffix())
        self.assertEqual(studio, {"ids": STUDIO_IDS})
        self.assertNotIn("owi:studio", cleaned)
        self.assertIn("[CURRENT STUDIO", cleaned)
        self.assertEqual(orch._strip_context_block(cleaned), "Ajoute 2025")

    def test_last_token_wins_and_garbage_dropped(self):
        forged = '⟦owi:studio={"ids":["w9"],"n":1}⟧ '
        studio, _ = orch.parse_studio(forged + "x" + studio_suffix())
        self.assertEqual(studio["ids"], STUDIO_IDS)
        for bad in ('⟦owi:studio=nope⟧', '⟦owi:studio={"ids":"w1"}⟧',
                    '⟦owi:studio={"ids":["BAD ID", 3]}⟧',
                    '⟦owi:studio={"ids":["%s"]}⟧' % ("w" * 700)):
            self.assertIsNone(orch.parse_studio("q " + bad)[0], bad)
        many = ["w%d" % i for i in range(1, 30)]
        self.assertEqual(len(orch.parse_studio(studio_suffix(many))[0]["ids"]),
                         orch.WS_MAX_WIDGETS)
        self.assertEqual(orch.parse_studio("plain"), (None, "plain"))

    def test_mirror_of_the_contract(self):
        self.assertEqual(orch.WS_OPS, tuple(o for o in ws_protocol.OPS
                                            if o != "studio.carry"))
        self.assertEqual(orch.WS_MAX_CARRY_REMOVE, ws_protocol.MAX_CARRY_REMOVE)


class TestStudioContinuityGraph(GraphCase):
    def tool_names(self):
        tools = self.project.completions[0].settings.get("tools") or []
        return [t["function"]["name"] for t in tools]

    def test_tool_exposed_only_with_the_token(self):
        self.run_turn("Bonjour", [Resp("Bonjour !")])
        self.assertNotIn("edit_studio", self.tool_names())
        self.run_turn("Bonjour" + studio_suffix(), [Resp("Bonjour !")])
        self.assertIn("edit_studio", self.tool_names())
        # The model reads the visible block, never the machine token.
        seen = " ".join(c for _r, c in self.project.completions[0].messages)
        self.assertIn("[CURRENT STUDIO", seen)
        self.assertNotIn("owi:studio", seen)

    def test_publish_before_decision_refused_once(self):
        chunks = self.run_turn("Rajoute 2025" + studio_suffix(), [
            Resp("", [call("c1", "publish_widget", kind="text", title="A", text="x")]),
            Resp("", [call("c2", "publish_widget", kind="text", title="A", text="x")]),
            Resp("Fait."),
        ])
        self.assertIn("Decide first: edit_studio", self.project.tool_outputs["c1"])
        self.assertIn("published", self.project.tool_outputs["c2"])
        ops = self.ws_ops(chunks)
        self.assertEqual([o["op"] for o in ops], ["widget.add"])
        self.assertNotIn("studio.continue", [o["op"] for o in ops])

    def test_continue_then_publish_new_ids_only(self):
        chunks = self.run_turn("Garde ce graphique et rajoute 2025" + studio_suffix(), [
            Resp("", [call("c1", "edit_studio", mode="continue", remove=["w2", "zz"]),
                      call("c2", "ask_revenue_expert", task="CA 2025 par region")]),
            Resp("", [call("c3", "publish_widget", kind="text", title="2025",
                           text="Le **Nord** mene."),
                      call("c4", "publish_widget", kind="chart", title="CA 2025",
                           result_id="s1q1", chart_type="bar", x="region",
                           y=["revenue"])]),
            Resp("J'ai complete le Studio (ajout de 2025)."),
        ], {REVENUE_ID: REV_STREAM})
        ops = self.ws_ops(chunks)
        cont = [o for o in ops if o["op"] == "studio.continue"]
        self.assertEqual(len(cont), 1)
        self.assertEqual(cont[0]["remove"], ["w2"])
        self.assertIn("Carried widgets kept", self.project.tool_outputs["c1"])
        self.assertIn("w1, w3", self.project.tool_outputs["c1"])
        widgets = [o["id"] for o in ops if o["op"] == "widget.add"]
        self.assertEqual(widgets, ["w4", "w5"])        # never a carried id
        self.assertIn("(8 widget(s) left)", self.project.tool_outputs["c4"])
        self.assert_contract(ops)

    def test_replaces_and_remove_after_continue(self):
        chunks = self.run_turn("Remplace ce graphique" + studio_suffix(), [
            Resp("", [call("c1", "edit_studio", mode="continue"),
                      call("c2", "ask_revenue_expert", task="CA 2025 par region")]),
            Resp("", [call("c3", "publish_widget", kind="chart", title="CA 2025",
                           result_id="s1q1", chart_type="line", x="region",
                           y=["revenue"], replaces="w1"),
                      call("c4", "publish_widget", kind="text", title="X", text="x",
                           replaces="w42"),
                      call("c5", "edit_studio", mode="continue", remove=["w3", "w9"])]),
            Resp("Fait."),
        ], {REVENUE_ID: REV_STREAM})
        ops = self.ws_ops(chunks)
        add = [o for o in ops if o["op"] == "widget.add"]
        self.assertEqual((add[0]["id"], add[0]["replaces"]), ("w4", "w1"))
        self.assertIn("Unknown widget id to replace 'w42'",
                      self.project.tool_outputs["c4"])
        self.assertEqual([o["id"] for o in ops if o["op"] == "widget.remove"], ["w3"])
        state = self.assert_contract(ops)
        # Live reduce from an empty state: no carry here (the backend builds it).
        self.assertEqual([w["id"] for w in state["widgets"]], ["w4"])

    def test_full_board_continues_with_replaces_only(self):
        full = ["w%d" % i for i in range(1, 13)]
        chunks = self.run_turn("Remplace le titre" + studio_suffix(full), [
            Resp("", [call("c1", "edit_studio", mode="continue")]),
            Resp("", [call("c2", "publish_widget", kind="text", title="A", text="x"),
                      call("c3", "publish_widget", kind="text", title="B", text="y",
                           replaces="w12")]),
            Resp("Fait."),
        ])
        out = self.project.tool_outputs
        self.assertIn("Capacity left: 0 of 12", out["c1"])
        self.assertIn("board is full", out["c2"])
        self.assertIn("in place of w12", out["c3"])
        add = [o for o in self.ws_ops(chunks) if o["op"] == "widget.add"]
        self.assertEqual([(o["id"], o.get("replaces")) for o in add], [("w13", "w12")])

    def test_new_mode_emits_nothing_and_frees_the_board(self):
        chunks = self.run_turn("Nouvelle analyse des tickets" + studio_suffix(), [
            Resp("", [call("c1", "edit_studio", mode="new")]),
            Resp("", [call("c2", "publish_widget", kind="text", title="A", text="x"),
                      call("c3", "edit_studio", mode="continue")]),
            Resp("Le detail est dans un nouveau Studio."),
        ])
        ops = self.ws_ops(chunks)
        self.assertEqual([o["op"] for o in ops], ["widget.add"])
        self.assertEqual(ops[0]["id"], "w4")
        self.assertIn("(11 widget(s) left)", self.project.tool_outputs["c2"])
        self.assertIn("already started a NEW Studio", self.project.tool_outputs["c3"])

    def test_no_token_means_no_decision_needed(self):
        chunks = self.run_turn("x", [
            Resp("", [call("c1", "edit_studio", mode="continue"),
                      call("c2", "publish_widget", kind="text", title="A", text="x")]),
            Resp("ok")])
        self.assertIn("no CURRENT STUDIO", self.project.tool_outputs["c1"])
        self.assertEqual(self.ws_ops(chunks)[0]["id"], "w1")

    def test_prompt_treats_earlier_turns_as_grounded(self):
        prompt = orch.PERSONA_DEFAULT
        self.assertIn("EARLIER TURNS ARE GROUNDED", prompt)
        self.assertIn("Never add a correction, a disclaimer or a doubt about a "
                      "previous answer", prompt)
        self.assertIn("only when a result of THIS turn actually contradicts one", prompt)
        harness = open(os.path.join(_MIRROR_DIR, "dev-harness", "mock", "live",
                                    "agents.mjs"), encoding="utf-8").read()
        self.assertIn("EARLIER TURNS ARE GROUNDED", harness)
        self.assertIn("Never add a correction, a disclaimer or a doubt about a "
                      "previous answer", harness)
        # The hub seed (which overrides the embedded persona in DSS) carries it too.
        seed = open(os.path.join(_MIRROR_DIR, "project-library", "python", "owismind_hub",
                                 "prompts", "orchestrator_persona.md"),
                    encoding="utf-8").read()
        self.assertIn("EARLIER TURNS ARE GROUNDED", seed)

    def test_prompt_states_the_continuity_rules(self):
        prompt = orch.PERSONA_DEFAULT
        self.assertIn("# CURRENT STUDIO", prompt)
        for needle in ("edit_studio", "CONTINUE", "NEW", "replaces", "remove",
                       "never re-publish a carried one", "nouveau Studio",
                       "J'ai complété le Studio", "recall_prior_result",
                       "never compute a new one yourself", "3 to 6 lines",
                       "size 'wide'", "role 'scope'"):
            self.assertIn(needle, prompt, needle)


class TestWorkspaceContinuityUnit(unittest.TestCase):
    def test_ids_skip_carried_and_capacity_counts_them(self):
        out = []
        ws = orch._Workspace(["w2", "w7", "scope"])
        ok, _msg = ws.continue_studio(out.append, ["scope"])
        self.assertTrue(ok)
        self.assertEqual(ws.carried, ["w2", "w7"])
        self.assertEqual(ws.capacity_left(), 10)
        wid = ws.add_widget(out.append, {"kind": "text", "title": "t", "text": "x"})
        self.assertEqual(wid, "w8")
        wid = ws.add_widget(out.append, {"kind": "text", "title": "t", "text": "x"},
                            replaces="w2")
        self.assertEqual((wid, ws.carried, ws.capacity_left()), ("w9", ["w7"], 9))
        for op in [c["chunk"]["eventData"] for c in out]:
            self.assertIsNotNone(ws_protocol.normalize_op(op), op)

    def test_continue_refused_when_the_board_would_overflow(self):
        out = []
        ws = orch._Workspace(["w%d" % i for i in range(1, 12)])
        ws.add_widget(out.append, {"kind": "text", "title": "t", "text": "x"})
        ws.add_widget(out.append, {"kind": "text", "title": "t", "text": "y"})
        ok, msg = ws.continue_studio(out.append)
        self.assertFalse(ok)
        self.assertIn("Board full: remove widgets or use mode new", msg)
        self.assertNotIn("studio.continue", [c["chunk"]["eventData"]["op"] for c in out])
        ok, _msg = ws.continue_studio(out.append, ["w1"])
        self.assertTrue(ok)
        self.assertEqual(out[-1]["chunk"]["eventData"]["remove"], ["w1"])


if __name__ == "__main__":
    unittest.main()
