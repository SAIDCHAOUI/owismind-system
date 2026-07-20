# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_workflow_gate.py
"""Deterministic complexity gate + workflow protocol builders (T3, pure functions).

Covers:
  - resolve_analysis_mode / should_plan: NEVER an LLM call, high-precision auto
    triggers (two matched domains, correlation phrasing), deep/direct overrides;
  - build_workflow_token: frozen grammar the agent-side strict parser accepts,
    loud ValueError on anything it would reject;
  - build_workflow_message: the LAYOUT CONTRACT (prose first, every token grouped
    at the tail, NOTHING after) - the anti-silent-degradation test;
  - build_progress_block: bounded recitation with restorable degradation.
"""
import os
import re
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.agents import context  # noqa: E402


_DOMAINS = {
    "revenue": ["revenus", "revenue", "chiffre d'affaires", "ca "],
    "tickets": ["ticket", "incident", "panne"],
}


class AnalysisModeTests(unittest.TestCase):
    def test_known_modes_pass_through(self):
        for m in ("auto", "deep", "direct"):
            self.assertEqual(context.resolve_analysis_mode(m), m)
        self.assertEqual(context.resolve_analysis_mode(" DEEP "), "deep")

    def test_unknown_or_missing_defaults_to_auto(self):
        for bad in (None, "", "yolo", 42, {"mode": "deep"}):
            self.assertEqual(context.resolve_analysis_mode(bad), "auto")


class ShouldPlanTests(unittest.TestCase):
    def test_deep_forces_true_direct_forces_false(self):
        self.assertTrue(context.should_plan("bonjour", {}, "deep"))
        self.assertFalse(context.should_plan(
            "correler revenus et tickets par client", _DOMAINS, "direct"))

    def test_simple_question_stays_direct(self):
        self.assertFalse(context.should_plan(
            "quels sont les revenus du client Orange en 2026 ?", _DOMAINS, "auto"))

    def test_two_matched_domains_trigger_planning(self):
        self.assertTrue(context.should_plan(
            "compare les revenus et les tickets du client X", _DOMAINS, "auto"))

    def test_correlation_phrasing_triggers_without_domains(self):
        self.assertTrue(context.should_plan(
            "peux-tu correler ces donnees avec les incidents ?", {}, "auto"))
        self.assertTrue(context.should_plan(
            "cross-reference the two datasets please", {}, "auto"))

    def test_compare_alone_is_not_enough(self):
        # Comparing two periods of ONE source is everyday simple traffic.
        self.assertFalse(context.should_plan(
            "compare les revenus 2025 et 2026", {}, "auto"))

    def test_empty_question_never_plans(self):
        self.assertFalse(context.should_plan("", _DOMAINS, "auto"))
        self.assertFalse(context.should_plan(None, _DOMAINS, "auto"))


class WorkflowTokenTests(unittest.TestCase):
    def test_full_token_round_trip_grammar(self):
        token = context.build_workflow_token(
            "execute", "run-1", step_id="S2", attempt_id="a1b2")
        self.assertEqual(
            token, "⟦owi:workflow=v1;command=execute;run=run-1;step=S2;attempt=a1b2⟧")

    def test_minimal_token_omits_optional_fields(self):
        token = context.build_workflow_token("plan", "abc123")
        self.assertEqual(token, "⟦owi:workflow=v1;command=plan;run=abc123⟧")

    def test_rejects_what_the_agent_parser_rejects(self):
        with self.assertRaises(ValueError):
            context.build_workflow_token("dance", "run-1")
        with self.assertRaises(ValueError):
            context.build_workflow_token("plan", "")
        with self.assertRaises(ValueError):
            context.build_workflow_token("plan", "run;evil")
        with self.assertRaises(ValueError):
            context.build_workflow_token("execute", "run-1", step_id="S⟧2")

    def test_wfstep_and_wfdone_tokens_are_ascii_json(self):
        step_tok = context.build_wfstep_token({"id": "S1", "kind": "render"})
        self.assertTrue(step_tok.startswith("⟦owi:wfstep={"))
        self.assertTrue(step_tok.endswith("}⟧"))
        done_tok = context.build_wfdone_token(["S1", None, 3, "S2"])
        self.assertEqual(done_tok, "⟦owi:wfdone=[\"S1\",\"S2\"]⟧")


class MessageLayoutTests(unittest.TestCase):
    """The anti-silent-degradation contract: prose, then the token block, END."""

    def test_tokens_grouped_at_tail_nothing_after(self):
        prose = "Question de l'utilisateur\n\n[WORKFLOW PROGRESS]\nGoal: x\n[/WORKFLOW PROGRESS]"
        tokens = [
            context.build_workflow_token("execute", "r1", "S1", "a1"),
            context.build_wfstep_token({"id": "S1"}),
        ]
        message = context.build_workflow_message(prose, tokens)
        # Everything after the FIRST token char must be tokens only.
        first = message.index("⟦")
        tail = message[first:]
        self.assertEqual(tail, "".join(tokens))
        # And stripping every control token leaves exactly the prose.
        stripped = re.sub(r"⟦owi:[a-z_]+=[^⟧]*⟧", "", message)
        self.assertEqual(stripped.rstrip(), prose.rstrip())

    def test_no_tokens_returns_bare_prose(self):
        self.assertEqual(context.build_workflow_message("hello", []), "hello")

    def test_empty_prose_still_carries_tokens(self):
        tok = context.build_workflow_token("plan", "r1")
        message = context.build_workflow_message("", [tok])
        self.assertTrue(message.endswith(tok))


class ProgressBlockTests(unittest.TestCase):
    def _ledger(self, n_steps=3, summary="Top 10 clients by revenue"):
        steps = []
        for i in range(1, n_steps + 1):
            steps.append({
                "step_id": "S%d" % i, "title": "Step %d" % i,
                "status": "completed" if i < n_steps else "pending",
                "result_summary": summary, "output_ref": "#S%d" % i,
                "result_schema_json": "[\"customer\",\"revenue\"]",
            })
        return {"run": {"final_intent": "Compare revenue and tickets"},
                "steps": steps}

    def test_block_carries_goal_statuses_and_refs(self):
        block = context.build_progress_block(self._ledger(), "smart")
        self.assertIn("[WORKFLOW PROGRESS]", block)
        self.assertIn("Goal: Compare revenue and tickets", block)
        self.assertIn("S1", block)
        self.assertIn("[completed]", block)
        self.assertIn("[pending]", block)
        self.assertIn("#S1", block)

    def test_budget_enforced_with_restorable_degradation(self):
        big = self._ledger(n_steps=12, summary="x" * 2000)
        block = context.build_progress_block(big, "smart")
        self.assertLessEqual(len(block), context.PROGRESS_BLOCK_MAX_CHARS["smart"])
        # Refs survive the degradation (never dropped).
        self.assertIn("S1", block)

    def test_empty_or_bad_ledger_yields_empty_block(self):
        self.assertEqual(context.build_progress_block(None, "smart"), "")
        self.assertEqual(context.build_progress_block("nope", "smart"), "")


if __name__ == "__main__":
    unittest.main()
