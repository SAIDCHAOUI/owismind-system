"""Unit tests for owismind.benchmark_view (pure consultation/aggregation - no DSS env).

Run:  python3 -m unittest discover -s Plugin/owismind/tests

The benchmark_view package is the plugin's READ side of the agent benchmark: it shapes the
scored table (read cross-project by lab_io, which is DSS-only and not tested here) into the
consultation view-model, validates the agent-profile benchmark block, and checks a candidate
table's schema against what the consultation needs.
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.benchmark_view import schemas, aggregate, agent_profile, schema_check  # noqa: E402


def _scored(**over):
    base = {
        "run_id": "r1", "run_timestamp": "2026-06-29T10:00:00Z",
        "question_id": "Q1", "question": "q", "category": "revenus",
        "agent_key": "owismind", "agent_label": "OWIsMind", "mode": "Smart",
        "status": "ok", "objective_match": "hit", "judge_score": 5,
        "judge_verdict": "correct", "judge_comment": "spot on", "correct": True,
        "needs_review": False, "reference_answer": "36 millions",
        "answer_text": "36456876", "notes": "", "expected_value": "36 millions",
        "expected_value_type": "numeric", "human_verdict": "", "human_correct": None,
        "human_comment": "", "reviewed_by": "", "reviewed_at": "",
        "latency_total_s": 1.2, "estimated_cost": 0.01,
    }
    base.update(over)
    return base


class EffectiveCorrectTests(unittest.TestCase):
    def test_no_override_mirrors_machine(self):
        out = schemas.effective_correct({"correct": True, "human_verdict": ""})
        self.assertTrue(out["correct"])
        self.assertFalse(out["overridden"])

    def test_human_override_wins(self):
        out = schemas.effective_correct({"correct": False, "human_verdict": "correct"})
        self.assertTrue(out["correct"])
        self.assertTrue(out["overridden"])

    def test_never_raises(self):
        self.assertFalse(schemas.effective_correct(None)["correct"])


class ResultsViewTests(unittest.TestCase):
    def _rows(self):
        return [
            _scored(question_id="Q1", correct=True, category="revenus"),
            _scored(question_id="Q2", correct=False, category="revenus", judge_score=2,
                    judge_verdict="incorrect", needs_review=True, objective_match="miss"),
            _scored(question_id="Q3", correct=False, category="tickets",
                    human_verdict="correct"),  # human override flips to correct
            _scored(question_id="Q4", mode="Pro", status="error", correct=False,
                    category="tickets"),
        ]

    def test_kpis_use_effective_verdict(self):
        out = aggregate.results_view(self._rows(), run_id="r1")
        k = out["kpis"]
        # Scored ok rows: Q1 (correct), Q2 (incorrect), Q3 (override->correct). Q4 errored.
        self.assertEqual(k["n_scored"], 3)
        self.assertEqual(k["n_correct"], 2)
        self.assertAlmostEqual(k["accuracy"], 2.0 / 3.0, places=4)
        self.assertIn(k["band"], ("high", "medium", "low"))

    def test_configs_per_agent_mode(self):
        out = aggregate.results_view(self._rows(), run_id="r1")
        # two configs: owismind/Smart (3 q) and owismind/Pro (1 q, errored)
        labels = {(c["agent_label"], c["mode"]) for c in out["configs"]}
        self.assertIn(("OWIsMind", "Smart"), labels)
        self.assertIn(("OWIsMind", "Pro"), labels)

    def test_categories_breakdown_effective(self):
        out = aggregate.results_view(self._rows(), run_id="r1")
        buckets = {c["bucket"]: c for c in out["categories"]}
        # tickets bucket has Q3 (override correct); Q4 errored excluded -> accuracy 1.0
        self.assertIn("tickets", buckets)
        self.assertEqual(buckets["tickets"]["accuracy"], 1.0)

    def test_detail_carries_override_and_comment_fields(self):
        out = aggregate.results_view(self._rows(), run_id="r1")
        row = next(r for r in out["detail"] if r["question_id"] == "Q3")
        for key in ("agent_key", "judge_comment", "human_verdict", "effective_verdict",
                    "overridden", "notes", "expected_value"):
            self.assertIn(key, row)
        self.assertTrue(row["overridden"])
        self.assertEqual(row["effective_verdict"], "correct")

    def test_runs_listed_newest_first(self):
        rows = self._rows() + [_scored(run_id="r0", run_timestamp="2026-06-01T00:00:00Z")]
        out = aggregate.results_view(rows, run_id="r1")
        self.assertEqual(out["runs"][0]["run_id"], "r1")

    def test_empty_is_safe(self):
        out = aggregate.results_view([], run_id=None)
        self.assertEqual(out["kpis"]["n_scored"], 0)
        self.assertEqual(out["detail"], [])


class OverrideTests(unittest.TestCase):
    def test_validate_requires_key_and_verdict(self):
        ok, _ = aggregate.validate_override({"run_id": "", "question_id": "Q1",
                                             "agent_key": "a", "verdict": "correct"})
        self.assertFalse(ok)
        ok, _ = aggregate.validate_override({"run_id": "r1", "question_id": "Q1",
                                             "agent_key": "a", "verdict": "nope"})
        self.assertFalse(ok)
        ok, _ = aggregate.validate_override({"run_id": "r1", "question_id": "Q1",
                                             "agent_key": "a", "mode": "Smart",
                                             "verdict": "correct"})
        self.assertTrue(ok)


class AgentProfileBenchmarkTests(unittest.TestCase):
    def test_defaults_when_absent(self):
        out = agent_profile.validate_benchmark_block(None)
        self.assertFalse(out["enabled"])
        self.assertEqual(out["table"], "")
        self.assertEqual(out["connection"], "SQL_owi")

    def test_valid_block(self):
        out = agent_profile.validate_benchmark_block({
            "enabled": True, "connection": "SQL_owi",
            "table": "OWISMIND_LAB_benchmark_runs_scored", "agent_key": "owismind",
        })
        self.assertTrue(out["enabled"])
        self.assertEqual(out["table"], "OWISMIND_LAB_benchmark_runs_scored")
        self.assertEqual(out["agent_key"], "owismind")

    def test_invalid_table_blanked(self):
        out = agent_profile.validate_benchmark_block({
            "enabled": True, "table": "bad table; DROP TABLE x", "agent_key": "a"})
        self.assertEqual(out["table"], "")

    def test_never_raises_on_garbage(self):
        out = agent_profile.validate_benchmark_block({"enabled": "yes", "table": 123})
        self.assertIn("enabled", out)
        self.assertEqual(out["table"], "")


class SchemaCheckTests(unittest.TestCase):
    def test_all_required_present(self):
        cols = list(schema_check.REQUIRED_COLUMNS)
        out = schema_check.check_columns(cols)
        self.assertTrue(out["ok"])
        self.assertEqual(out["missing"], [])

    def test_missing_columns_reported(self):
        cols = [c for c in schema_check.REQUIRED_COLUMNS if c not in ("judge_comment", "human_verdict")]
        out = schema_check.check_columns(cols)
        self.assertFalse(out["ok"])
        self.assertIn("judge_comment", out["missing"])
        self.assertIn("human_verdict", out["missing"])

    def test_case_insensitive_and_extra_ignored(self):
        cols = [c.upper() for c in schema_check.REQUIRED_COLUMNS] + ["some_extra"]
        out = schema_check.check_columns(cols)
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
