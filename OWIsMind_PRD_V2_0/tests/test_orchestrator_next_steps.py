"""DSS-free tests for the orchestrator NEXT STEPS (proactivity) and the
product-owner answer rules of 2026-10-22.

Covered:
  - ``_ws_next_steps`` validates exactly like the backend ``suggestion_items``
    (trim, 8 to 120 chars, dropped never cut, case / whitespace dedupe, max 3)
    and the limits mirror the contract;
  - ``final_answer`` is exposed; delivered alone it IS the answer (no extra LLM
    call) and ONE ``suggest.set`` op goes out right BEFORE the answer text;
    delivered next to publish_widget it is handled after the widgets; next to a
    specialist call it is refused (the results are not read yet);
  - the one-time nudge: a data turn ending without next steps (final_answer
    without them, or a plain-text answer) is asked ONCE to re-deliver them;
    greetings, clarifications and an exhausted nudge never loop; an empty reply
    to the nudge keeps the first answer;
  - the LAZY auto plan (guard D4): none for a mini-Studio (one call, scope, KPIs,
    one chart); created on the FIRST of a second specialist call, a section text
    widget or a 4th non-kpi widget, with the earlier calls as closed steps and
    no step_id ever pointing at a step that does not exist yet;
  - replay fixes (2026-10-22): the duplicate guard also refuses a REPLACE that
    copies another widget and a plain re-publish after a replace (Python and the
    harness, the latter run with node when available); the specialists align
    comparison periods (UNDERSTAND, semantic question) and state the exact
    months of every figure in their [Scope] line;
  - the prompt rules (mini-Studio, follow-ups, aligned comparisons, chat brevity,
    titles, next steps) in the persona, the hub seed and the dev-harness mirror,
    plus the harness plumbing (final_answer next_steps, wsOp('suggest.set')).
"""

import os
import shutil
import subprocess
import unittest

from test_orchestrator_workspace import (  # noqa: F401 (shared fakes)
    GraphCase, Resp, call, orch, ws_protocol, REVENUE_ID, TICKETS_ID, REV_STREAM,
    TIX_STREAM)

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_MIRROR_DIR = os.path.dirname(_TESTS_DIR)
_HARNESS_PATH = os.path.join(_MIRROR_DIR, "dev-harness", "mock", "live", "agents.mjs")
_SEED_PATH = os.path.join(_MIRROR_DIR, "project-library", "python", "owismind_hub",
                          "prompts", "orchestrator_persona.md")

STEPS = ["Comparer 2026 au budget mois par mois",
         "Voir la repartition par offre"]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestNextStepsValidation(unittest.TestCase):
    CORPUS = (
        ["  Comparer 2026 au budget  ", "court", "x" * 121, "y" * 120],
        ["Voir le detail par offre", "voir le   DETAIL par offre", "Top 10 clients 2026",
         "Evolution mensuelle 2025", "Encore une autre idee"],
        "not a list",
        None,
        [12, None, {"a": 1}, "Comparer au budget 2026"],
        [],
        ["        ", "12345678"],
    )

    def test_limits_mirror_the_contract(self):
        self.assertEqual(orch.WS_SUGGESTIONS_MAX_ITEMS, ws_protocol.SUGGESTIONS_MAX_ITEMS)
        self.assertEqual(orch.WS_SUGGESTION_MIN_CHARS, ws_protocol.SUGGESTION_MIN_CHARS)
        self.assertEqual(orch.WS_SUGGESTION_MAX_CHARS, ws_protocol.SUGGESTION_MAX_CHARS)
        self.assertIn("suggest.set", orch.WS_OPS)

    def test_same_verdicts_as_the_backend(self):
        for value in self.CORPUS:
            self.assertEqual(orch._ws_next_steps(value),
                             ws_protocol.suggestion_items(value), value)

    def test_rules(self):
        self.assertEqual(
            orch._ws_next_steps(["  Comparer 2026 au budget  ", "court", "x" * 121]),
            ["Comparer 2026 au budget"])
        self.assertEqual(
            orch._ws_next_steps(["Voir le detail", "voir  le DETAIL", "Top 10 clients",
                                 "Evolution 2025", "Quatrieme idee"]),
            ["Voir le detail", "Top 10 clients", "Evolution 2025"])
        self.assertEqual(orch._ws_next_steps("Comparer au budget"), [])
        # The project bans en / em dashes: normalised before the length check.
        self.assertEqual(orch._ws_next_steps(["Comparer 2025 " + chr(0x2014) + " 2026"]),
                         ["Comparer 2025 - 2026"])

    def test_final_answer_is_exposed(self):
        specs, _t2c = orch.build_tool_specs(orch.get_capabilities())
        final = next(s["function"] for s in specs
                     if s["function"]["name"] == orch.FINAL_TOOL_NAME)
        props = final["parameters"]["properties"]
        self.assertEqual(final["parameters"]["required"], ["markdown"])
        self.assertEqual(props["next_steps"]["maxItems"], 3)
        self.assertIn("REPLY LANGUAGE", props["next_steps"]["description"])


class TestFinalAnswerGraph(GraphCase):
    ASK = call("c1", "ask_revenue_expert", task="CA 2026 de janvier a aout")

    def subs(self):
        return {REVENUE_ID: REV_STREAM}

    def texts(self, chunks):
        return [c["text"] for c in chunks if "text" in c and "type" not in c]

    def nudge_outputs(self):
        return [k for k, v in self.project.tool_outputs.items()
                if v == orch._STEPS_NUDGE_MSG]

    def nudge_messages(self):
        return [m for c in self.project.completions for (role, m) in c.messages
                if role == "user" and m == orch._STEPS_NUDGE_MSG]

    def test_final_answer_alone_emits_one_suggest_set_before_the_answer(self):
        sentinel = Resp("NEVER CONSUMED")
        chunks = self.run_turn("combien de CA cette annee ?", [
            Resp("", [self.ASK]),
            Resp("", [call("c2", "final_answer", markdown="Le CA 2026 est de 2 150 EUR.",
                           next_steps=STEPS + ["voir la REPARTITION  par offre"])]),
            sentinel,
        ], self.subs())
        ops = self.ws_ops(chunks)
        suggest = [o for o in ops if o["op"] == "suggest.set"]
        self.assertEqual(len(suggest), 1)
        self.assertEqual(suggest[0]["items"], STEPS)
        state = self.assert_contract(ops)
        self.assertEqual(state["suggestions"], STEPS)
        # Right before the answer text, and the answer is the markdown.
        idx_op = next(i for i, c in enumerate(chunks)
                      if c.get("eventKind") == "WORKSPACE"
                      and c["eventData"]["op"] == "suggest.set")
        idx_txt = next(i for i, c in enumerate(chunks)
                       if c.get("text") == "Le CA 2026 est de 2 150 EUR.")
        self.assertLess(idx_op, idx_txt)
        self.assertEqual(self.project.responses, [sentinel])   # no extra LLM call
        self.assertEqual(self.nudge_outputs(), [])

    def test_final_answer_next_to_widgets_is_handled_after_them(self):
        sentinel = Resp("NEVER CONSUMED")
        chunks = self.run_turn("combien de CA cette annee ?", [
            Resp("", [self.ASK]),
            Resp("", [call("c2", "publish_widget", kind="kpi", title="CA 2026",
                           result_id="s1q1", kpi_value="revenue"),
                      call("c3", "final_answer", markdown="CA 2026 : 2 150 EUR.",
                           next_steps=STEPS)]),
            sentinel,
        ], self.subs())
        ops = self.ws_ops(chunks)
        kinds = [o["op"] for o in ops]
        self.assertLess(kinds.index("widget.add"), kinds.index("suggest.set"))
        self.assertIn("CA 2026 : 2 150 EUR.", self.texts(chunks))
        self.assertEqual(self.project.tool_outputs["c3"], "Answer delivered.")
        self.assertEqual(self.project.responses, [sentinel])
        self.assert_contract(ops)

    def test_final_answer_next_to_a_specialist_call_is_refused(self):
        chunks = self.run_turn("combien de CA cette annee ?", [
            Resp("", [self.ASK, call("c2", "final_answer", markdown="Trop tot.",
                                     next_steps=STEPS)]),
            Resp("", [call("c3", "final_answer", markdown="CA 2026 : 2 150 EUR.",
                           next_steps=STEPS)]),
        ], self.subs())
        self.assertIn("NOT delivered", self.project.tool_outputs["c2"])
        self.assertIn("CA 2026 : 2 150 EUR.", self.texts(chunks))
        self.assertNotIn("Trop tot.", self.texts(chunks))

    def test_missing_next_steps_is_nudged_once(self):
        chunks = self.run_turn("combien de CA cette annee ?", [
            Resp("", [self.ASK]),
            Resp("", [call("c2", "final_answer", markdown="CA 2026 : 2 150 EUR.")]),
            Resp("", [call("c3", "final_answer", markdown="CA 2026 : 2 150 EUR.",
                           next_steps=STEPS)]),
        ], self.subs())
        self.assertEqual(self.nudge_outputs(), ["c2"])
        suggest = [o for o in self.ws_ops(chunks) if o["op"] == "suggest.set"]
        self.assertEqual([o["items"] for o in suggest], [STEPS])

    def test_the_nudge_never_loops(self):
        sentinel = Resp("NEVER CONSUMED")
        chunks = self.run_turn("combien de CA cette annee ?", [
            Resp("", [self.ASK]),
            Resp("", [call("c2", "final_answer", markdown="Premiere version.")]),
            Resp("", [call("c3", "final_answer", markdown="Seconde version.")]),
            sentinel,
        ], self.subs())
        self.assertEqual(self.nudge_outputs(), ["c2"])
        self.assertIn("Seconde version.", self.texts(chunks))
        self.assertEqual([o for o in self.ws_ops(chunks) if o["op"] == "suggest.set"], [])
        self.assertEqual(self.project.responses, [sentinel])

    def test_plain_text_answer_is_nudged_then_delivered(self):
        chunks = self.run_turn("combien de CA cette annee ?", [
            Resp("", [self.ASK]),
            Resp("CA 2026 : 2 150 EUR."),
            Resp("", [call("c3", "final_answer", markdown="CA 2026 : 2 150 EUR.",
                           next_steps=STEPS)]),
        ], self.subs())
        self.assertEqual(len(self.nudge_messages()), 1)
        suggest = [o for o in self.ws_ops(chunks) if o["op"] == "suggest.set"]
        self.assertEqual([o["items"] for o in suggest], [STEPS])
        self.assertEqual(self.texts(chunks).count("CA 2026 : 2 150 EUR."), 1)

    def test_empty_reply_to_the_nudge_keeps_the_first_answer(self):
        chunks = self.run_turn("combien de CA cette annee ?", [
            Resp("", [self.ASK]),
            Resp("CA 2026 : 2 150 EUR."),
            Resp(""),
        ], self.subs())
        self.assertIn("CA 2026 : 2 150 EUR.", self.texts(chunks))
        self.assertEqual([o for o in self.ws_ops(chunks) if o["op"] == "suggest.set"], [])

    def test_greeting_is_never_nudged(self):
        sentinel = Resp("NEVER CONSUMED")
        chunks = self.run_turn("bonjour", [Resp("Bonjour, que puis-je analyser ?"),
                                           sentinel])
        self.assertEqual(self.nudge_messages(), [])
        self.assertEqual(self.ws_ops(chunks), [])
        self.assertEqual(self.project.responses, [sentinel])

    def test_clarification_is_never_nudged(self):
        sentinel = Resp("NEVER CONSUMED")
        self.run_turn("le CA de HSBC", [
            Resp("", [self.ASK]),
            Resp("Parlez-vous de HSBC France ou de HSBC UK ?"),
            sentinel,
        ], self.subs())
        self.assertEqual(self.nudge_messages(), [])
        self.assertEqual(self.project.responses, [sentinel])


def _kpi(cid, title):
    return call(cid, "publish_widget", kind="kpi", title=title, result_id="s1q1",
                kpi_value="revenue")


def _chart(cid, title, rid="s1q1"):
    return call(cid, "publish_widget", kind="chart", title=title, result_id=rid,
                chart_type="bar", x="region", y=["revenue"])


SCOPE = call("sc", "publish_widget", kind="text", role="scope", title="Perimetre",
             text="CA 2026, janvier a aout.")


class TestLazyAutoPlan(GraphCase):
    ASK = call("c1", "ask_revenue_expert", task="CA 2026 de janvier a aout")
    FINAL = call("cf", "final_answer", markdown="CA 2026 : 2 150 EUR.", next_steps=STEPS)

    def plan_ops(self, ops):
        return [o for o in ops if o["op"] == "plan.set"]

    def assert_no_dangling_step(self, ops):
        known = set()
        for o in ops:
            if o["op"] == "plan.set":
                known = set(st["id"] for st in o["steps"])
            elif o.get("step_id") is not None:
                self.assertIn(o["step_id"], known, o)

    def test_mini_studio_gets_no_plan(self):
        chunks = self.run_turn("combien de CA cette annee ?", [
            Resp("", [self.ASK]),
            Resp("", [SCOPE, _kpi("k1", "CA 2026"), _kpi("k2", "CA 2025 meme periode"),
                      _kpi("k3", "Budget 2026"), _chart("g1", "CA mensuel 2026"),
                      self.FINAL]),
        ], {REVENUE_ID: REV_STREAM})
        ops = self.ws_ops(chunks)
        self.assertEqual(self.plan_ops(ops), [])
        self.assertEqual(len([o for o in ops if o["op"] == "widget.add"]), 5)
        state = self.assert_contract(ops)
        self.assertFalse(state.get("plan"))
        self.assertEqual(state["suggestions"], STEPS)

    def test_second_specialist_call_creates_the_plan(self):
        chunks = self.run_turn("CA puis tickets", [
            Resp("", [self.ASK]),
            Resp("", [call("c2", "ask_tickets_expert", task="Tickets ouverts 2026")]),
            Resp("", [self.FINAL]),
        ], {REVENUE_ID: REV_STREAM, TICKETS_ID: TIX_STREAM})
        ops = self.ws_ops(chunks)
        plans = self.plan_ops(ops)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["origin"], "auto")
        self.assertEqual(len(plans[0]["steps"]), 2)
        # Created after the first call ran, before the second one.
        kinds = [o["op"] for o in ops]
        prov = [i for i, o in enumerate(ops) if o["op"] == "prov.set"]
        self.assertLess(prov[0], kinds.index("plan.set"))
        self.assertLess(kinds.index("plan.set"), prov[1])
        self.assertNotIn("step_id", ops[prov[0]])            # planless first call
        self.assertEqual(ops[prov[1]]["step_id"], "p2")
        self.assertIn("PLAN AUTO-CREATED", self.project.tool_outputs["c2"])
        self.assert_no_dangling_step(ops)
        state = self.assert_contract(ops)
        self.assertEqual([st["status"] for st in state["plan"]["steps"]],
                         ["done", "done"])

    def test_two_calls_in_one_batch_plan_before_they_run(self):
        chunks = self.run_turn("CA et tickets", [
            Resp("", [self.ASK, call("c2", "ask_tickets_expert", task="Tickets 2026")]),
            Resp("", [self.FINAL]),
        ], {REVENUE_ID: REV_STREAM, TICKETS_ID: TIX_STREAM})
        ops = self.ws_ops(chunks)
        self.assertEqual(ops[0]["op"], "plan.set")
        self.assertEqual(ops[0]["origin"], "auto")
        kinds = self.kinds(chunks)
        self.assertLess(kinds.index("WORKSPACE"), kinds.index("CALLING_AGENT"))
        self.assert_no_dangling_step(ops)
        self.assert_contract(ops)

    def test_section_text_creates_the_plan(self):
        chunks = self.run_turn("analyse le CA 2026", [
            Resp("", [self.ASK]),
            Resp("", [SCOPE,
                      call("t1", "publish_widget", kind="text", title="Un debut solide",
                           text="**Le CA progresse.**"),
                      _chart("g1", "CA mensuel 2026"), self.FINAL]),
        ], {REVENUE_ID: REV_STREAM})
        ops = self.ws_ops(chunks)
        kinds = [o["op"] for o in ops]
        widgets = [i for i, o in enumerate(ops) if o["op"] == "widget.add"]
        self.assertEqual(len(self.plan_ops(ops)), 1)
        # After the scope, right before the section text.
        self.assertLess(widgets[0], kinds.index("plan.set"))
        self.assertLess(kinds.index("plan.set"), widgets[1])
        self.assertIn("PLAN AUTO-CREATED", self.project.tool_outputs["t1"])
        self.assertNotIn("PLAN AUTO-CREATED", self.project.tool_outputs["sc"])
        self.assert_no_dangling_step(ops)
        state = self.assert_contract(ops)
        self.assertEqual([st["status"] for st in state["plan"]["steps"]], ["done"])

    def test_fourth_non_kpi_widget_creates_the_plan(self):
        chunks = self.run_turn("montre le CA 2026", [
            Resp("", [self.ASK]),
            Resp("", [SCOPE, _kpi("k1", "CA 2026"), _kpi("k2", "CA 2025"),
                      _chart("g1", "CA par region"),
                      call("tb", "publish_widget", kind="table", title="Detail",
                           result_id="s1q1"),
                      _chart("g2", "CA par region (barres)"), self.FINAL]),
        ], {REVENUE_ID: REV_STREAM})
        ops = self.ws_ops(chunks)
        kinds = [o["op"] for o in ops]
        widgets = [i for i, o in enumerate(ops) if o["op"] == "widget.add"]
        self.assertEqual(len(widgets), 6)
        self.assertEqual(len(self.plan_ops(ops)), 1)
        # scope, chart, table = 3 non-kpi: the plan comes before the 4th (g2).
        self.assertLess(widgets[4], kinds.index("plan.set"))
        self.assertLess(kinds.index("plan.set"), widgets[5])
        self.assertIn("PLAN AUTO-CREATED", self.project.tool_outputs["g2"])
        self.assert_no_dangling_step(ops)
        self.assert_contract(ops)

    def test_write_plan_turn_never_gets_an_auto_plan(self):
        chunks = self.run_turn("analyse le CA 2026", [
            Resp("", [call("wp", "write_plan", mission="CA 2026",
                           steps=[{"label": "CA mensuel"}]), self.ASK]),
            Resp("", [call("t1", "publish_widget", kind="text", title="Tendance",
                           text="**Hausse.**"), _chart("g1", "CA mensuel 2026"),
                      self.FINAL]),
        ], {REVENUE_ID: REV_STREAM})
        plans = self.plan_ops(self.ws_ops(chunks))
        self.assertEqual([p["origin"] for p in plans], ["model"])


class TestDedupeAfterReplace(GraphCase):
    def test_replace_registers_the_signature_and_copies_are_refused(self):
        self.run_turn("CA 2026", [
            Resp("", [call("c1", "ask_revenue_expert", task="CA 2026")]),
            Resp("", [_kpi("k1", "CA 2026"), _kpi("k2", "CA 2025"), _kpi("k3", "Budget"),
                      # w1 replaced by a new KPI (-> w4), then the SAME KPI again.
                      call("r1", "publish_widget", kind="kpi", title="CA janv-aout 2025",
                           result_id="s1q1", kpi_value="revenue", replaces="w1"),
                      call("d1", "publish_widget", kind="kpi", title="CA janv-aout 2025",
                           result_id="s1q1", kpi_value="revenue"),
                      # Replacing w3 with a copy of w2 is a duplicate too.
                      call("r2", "publish_widget", kind="kpi", title="CA 2025",
                           result_id="s1q1", kpi_value="revenue", replaces="w3"),
                      # Re-publishing w2 in place is fine.
                      call("r3", "publish_widget", kind="kpi", title="CA 2025",
                           result_id="s1q1", kpi_value="revenue", replaces="w2"),
                      self.FINAL_CALL]),
        ], {REVENUE_ID: REV_STREAM})
        out = self.project.tool_outputs
        self.assertIn("Widget w4 published", out["r1"])
        self.assertIn("Widget w4 is already on the board", out["d1"])
        self.assertIn("Widget w2 already shows this", out["r2"])
        self.assertIn("in place of w2", out["r3"])

    FINAL_CALL = call("cf", "final_answer", markdown="CA 2026.", next_steps=STEPS)

    def test_harness_mirror_refuses_the_same_copies(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        script = """
import { LiveTurn } from %s
const ds = ['revenues', 'opportunities', 'tickets'].map((key) => ({ key, table: 't', dataset: 'd', rows: [], columns: [] }))
const t = new LiveTurn({ client: {}, model: 'stub', datasets: ds, message: 'q', history: [], lang: 'fr', emit: () => {}, signal: null })
t.sqlItems.push({ sql_id: 's1q1', success: true, result: { columns: ['revenue'], rows: [[1]] } })
const k = (title, replaces) => t.publishWidget({ kind: 'kpi', title, sql_id: 's1q1', kpi: { label: title, value: 'revenue' }, ...(replaces ? { replaces } : {}) }, (m) => ({ content: 'Error: ' + m }))
const out = [k('CA 2026'), k('CA 2025'), k('Budget'), k('CA janv-aout 2025', 'w1'), k('CA janv-aout 2025'), k('CA 2025', 'w3'), k('CA 2025', 'w2')]
console.log(JSON.stringify(out.map((o) => o.content)))
""" % repr("file://" + _HARNESS_PATH)
        res = subprocess.run([node, "--input-type=module", "-e", script],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        import json
        out = json.loads(res.stdout.strip().splitlines()[-1])
        self.assertIn("Widget w4 published", out[3])
        self.assertIn("Widget w4 is already on the board", out[4])
        self.assertIn("Widget w2 already shows this", out[5])
        self.assertIn("Widget w5 published", out[6])


class TestSpecialistPeriodAlignment(unittest.TestCase):
    """Both DSS specialists (revenue engine + tickets) carry the same generic
    period-alignment rules."""

    @classmethod
    def setUpClass(cls):
        import test_langgraph_agents as lg
        cls.mods = (lg.dx, lg.tx)
        cls.P = lg._align_profile()
        cls.u = staticmethod(lg._align_u)

    def test_understand_aligns_compared_periods(self):
        for mod in self.mods:
            prompt = mod.build_understand_prompt(self.P, "2026-10-22", "fr")
            self.assertIn("gives EVERY period the SAME months", prompt, mod.__name__)
            self.assertIn("never a full year against a partial one", prompt)

    def test_semantic_question_carries_the_alignment_note(self):
        for mod in self.mods:
            q = mod.build_semantic_question(self.u(instruction="CA 2026 vs meme periode 2025"),
                                            self.P, [])
            self.assertIn("PERIOD ALIGNMENT", q, mod.__name__)
            self.assertIn("alias each figure's column with the months it covers", q)

    def test_scope_line_states_the_months_of_every_figure(self):
        periods = [{"mode": "explicit", "start": "2026-01-01", "end": "2026-08-31",
                    "label": "2026"},
                   {"mode": "explicit", "start": "2025-01-01", "end": "2025-08-31",
                    "label": "2025"}]
        for mod in self.mods:
            note = mod.build_scope_note(self.u(intent="compare_periods", periods=periods),
                                        self.P, [], "fr")
            self.assertIn("2026 (du 2026-01-01 au 2026-08-31)", note, mod.__name__)
            self.assertIn("2025 (du 2025-01-01 au 2025-08-31)", note)
            single = mod.build_scope_note(
                self.u(period=dict(periods[0], label="YTD 2026")), self.P, [], "en")
            self.assertIn("YTD 2026 (from 2026-01-01 to 2026-08-31)", single)
            # A label already holding its dates is never doubled.
            fallback = mod.build_scope_note(
                self.u(period=dict(periods[0], label="2026-01-01 -> 2026-08-31")),
                self.P, [], "en")
            self.assertEqual(fallback.count("2026-01-01"), 1)

    def test_harness_experts_align_periods(self):
        harness = _read(_HARNESS_PATH)
        self.assertIn("COMPARISON PERIODS", harness)
        self.assertIn("states, per figure, the exact months it covers", harness)


_RULE_NEEDLES = (
    "MINI-STUDIO", "2 or 3 kpi widgets", "same period last year",
    "ONE chart when the figure is a period total",
    "No plan, no section text", "CONVERSATION",
    "FOLLOW-UPS", "corrects or extends the PREVIOUS request",
    "restate silently what the user now wants",
    "Never widen a period the user narrowed", "ask ONE short question",
    "the year of the Today date", "say that period explicitly",
    "COMPARISONS ALIGNED", "SAME months in both",
    "never a full year against a partial one",
    "CHAT BREVITY", "never list months or items one by one",
    "never its chart's title repeated", "names the measure, the scope and the period",
    "NEXT STEPS", "the 2 or 3 most useful next analyses",
    "a request the user can send as is", "never what is already on the board",
    "ONE short sentence inviting to go further",
    # Replay fixes (2026-10-22): scope faithful to the result, corrections, typos.
    "NEVER the scope of your own question", "and never call it", "same period",
    "quote a percentage change only when the result holds it",
    "corrects the previous answer: redo it with the stated constraint and nothing more",
    "restrict to exactly what follows", "never add years",
    "non que cette année", "-> keep ONLY 2026",
    "TYPOS: read them in context", "(but), not the month of May",
)


class TestAnswerRulesInPrompts(unittest.TestCase):
    def test_persona(self):
        for needle in _RULE_NEEDLES:
            self.assertIn(needle, orch.PERSONA_DEFAULT, needle)

    def test_hub_seed(self):
        seed = _read(_SEED_PATH)
        for needle in _RULE_NEEDLES:
            self.assertIn(needle, seed, needle)

    def test_harness_mirror(self):
        harness = _read(_HARNESS_PATH)
        for needle in _RULE_NEEDLES:
            self.assertIn(needle, harness, needle)

    def test_system_prompt_finishes_with_final_answer(self):
        prompt = orch.build_system_prompt(orch.CAPABILITIES, "fr")
        self.assertIn("call `final_answer` ALONE", prompt)
        self.assertIn("SIMPLE QUESTION -> CHAT + MINI-STUDIO", prompt)

    def test_harness_plumbing(self):
        harness = _read(_HARNESS_PATH)
        for needle in ("next_steps", "wsOp('suggest.set'", "nextSteps(",
                       "STEPS_NUDGE"):
            self.assertIn(needle, harness, needle)


if __name__ == "__main__":
    unittest.main()
