"""Unit tests for owismind.benchmark_view (pure consultation/aggregation - no DSS env).

Run:  python3 -m unittest discover -s Plugin/owismind/tests

The benchmark_view package is the plugin's READ side of the agent benchmark: it shapes the
scored table (read cross-project by lab_io, which is DSS-only and not tested here) into the
consultation view-model, validates the agent-profile benchmark block, and checks a candidate
table's schema against what the consultation needs.
"""

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.benchmark_view import schemas, aggregate, agent_profile, schema_check  # noqa: E402


def _scored(**over):
    base = {
        "run_id": "r1", "run_timestamp": "2026-06-29T10:00:00Z",
        "benchmark_id": "B1", "benchmark_name": "bench one", "attempt_no": 1,
        "question_id": "Q1", "question": "q", "category": "revenus",
        "agent_key": "owismind", "agent_label": "OWIsMind", "mode": "Smart",
        "status": "ok", "objective_match": "hit", "judge_score": 5,
        "judge_verdict": "correct", "judge_comment": "spot on", "correct": True,
        "needs_review": False, "reference_answer": "36 millions",
        "answer_text": "36456876", "notes": "", "expected_value": "36 millions",
        "expected_value_type": "numeric", "human_verdict": "", "human_correct": None,
        "human_comment": "", "reviewed_by": "", "reviewed_at": "",
        "latency_total_s": 1.2, "estimated_cost": 0.01,
        "expected_sql": "SELECT 1", "expected_tool": "show_table", "actual_tools": "table",
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
        out = aggregate.results_view(self._rows())
        k = out["kpis"]
        # Scored ok rows: Q1 (correct), Q2 (incorrect), Q3 (override->correct). Q4 errored.
        self.assertEqual(k["n_scored"], 3)
        self.assertEqual(k["n_correct"], 2)
        self.assertAlmostEqual(k["accuracy"], 2.0 / 3.0, places=4)
        self.assertIn(k["band"], ("high", "medium", "low"))
        self.assertEqual(out["benchmark_id"], "B1")
        self.assertEqual(out["benchmark_name"], "bench one")

    def test_configs_per_agent_mode(self):
        out = aggregate.results_view(self._rows())
        # two configs: owismind/Smart (3 q) and owismind/Pro (1 q, errored)
        labels = {(c["agent_label"], c["mode"]) for c in out["configs"]}
        self.assertIn(("OWIsMind", "Smart"), labels)
        self.assertIn(("OWIsMind", "Pro"), labels)

    def test_categories_breakdown_effective(self):
        out = aggregate.results_view(self._rows())
        buckets = {c["bucket"]: c for c in out["categories"]}
        # tickets bucket has Q3 (override correct); Q4 errored excluded -> accuracy 1.0
        self.assertIn("tickets", buckets)
        self.assertEqual(buckets["tickets"]["accuracy"], 1.0)

    def test_detail_carries_override_and_reference_fields(self):
        out = aggregate.results_view(self._rows())
        row = next(r for r in out["detail"] if r["question_id"] == "Q3")
        for key in ("agent_key", "run_id", "judge_comment", "human_verdict", "effective_verdict",
                    "overridden", "notes", "expected_value", "expected_sql", "expected_tool",
                    "actual_tools", "attempt_no", "n_attempts", "delta", "attempts"):
            self.assertIn(key, row)
        self.assertTrue(row["overridden"])
        self.assertEqual(row["effective_verdict"], "correct")

    def test_benchmarks_selector(self):
        rows = self._rows() + [
            _scored(benchmark_id="B2", benchmark_name="bench two", question_id="Q9",
                    run_timestamp="2026-06-30T10:00:00Z"),
        ]
        out = aggregate.results_view(rows)
        ids = {b["benchmark_id"] for b in out["benchmarks"]}
        self.assertEqual(ids, {"B1", "B2"})
        # Default selection = most recent benchmark (B2's row is newer).
        self.assertEqual(out["benchmark_id"], "B2")
        # Explicit selection honored.
        out_b1 = aggregate.results_view(rows, benchmark_id="B1")
        self.assertEqual(out_b1["benchmark_id"], "B1")

    def test_evolution_in_detail(self):
        rows = [
            _scored(question_id="Q1", attempt_no=1, correct=False, judge_score=2,
                    judge_verdict="incorrect", run_id="r1", run_timestamp="2026-06-29T10:00:00Z"),
            _scored(question_id="Q1", attempt_no=2, correct=True, judge_score=5,
                    run_id="r2", run_timestamp="2026-06-30T10:00:00Z"),
        ]
        out = aggregate.results_view(rows, benchmark_id="B1")
        # latest attempt wins -> 1 question, correct
        self.assertEqual(out["kpis"]["n_questions"], 1)
        self.assertEqual(out["kpis"]["n_correct"], 1)
        row = out["detail"][0]
        self.assertEqual(row["attempt_no"], 2)
        self.assertEqual(row["n_attempts"], 2)
        self.assertEqual(row["delta"], "improved")
        self.assertEqual([a["attempt_no"] for a in row["attempts"]], [1, 2])

    def test_empty_is_safe(self):
        out = aggregate.results_view([])
        self.assertEqual(out["kpis"]["n_scored"], 0)
        self.assertEqual(out["detail"], [])
        self.assertEqual(out["benchmarks"], [])


class FullDetailViewTests(unittest.TestCase):
    def _row(self, **over):
        items = [{"sql": "SELECT SUM(amount_eur) FROM drive_revenues WHERE phase='ACTUALS'",
                  "success": True, "row_count": 2,
                  "result": {"columns": ["client", "rev"],
                             "rows": [["Orange", 1200], ["Maroc Telecom", 900]], "truncated": False}}]
        row = {"run_id": "r1", "question_id": "Q1", "agent_key": "038G7mlF", "mode": "Smart",
               "status": "ok", "answer_text": "Top client Orange with 1200 EUR.",
               "actual_tools": "table", "n_sql": 1, "total_rows": 2,
               "generated_sql_json": json.dumps(items)}
        row.update(over)
        return row

    def test_parses_generated_sql_and_full_answer(self):
        out = aggregate.full_detail_view(self._row())
        self.assertTrue(out["found"])
        self.assertEqual(out["answer_text"], "Top client Orange with 1200 EUR.")
        self.assertEqual(len(out["sql_items"]), 1)
        item = out["sql_items"][0]
        self.assertIn("SELECT SUM(amount_eur)", item["sql"])
        self.assertTrue(item["success"])
        self.assertEqual(item["result"]["columns"], ["client", "rev"])
        self.assertEqual(item["result"]["rows"][0], ["Orange", 1200])

    def test_none_row_not_found(self):
        self.assertEqual(aggregate.full_detail_view(None), {"found": False})

    def test_malformed_json_degrades(self):
        out = aggregate.full_detail_view(self._row(generated_sql_json="{bad"))
        self.assertTrue(out["found"])
        self.assertEqual(out["sql_items"], [])

    def test_answer_capped_and_rows_capped(self):
        out = aggregate.full_detail_view(self._row(answer_text="x" * 50000))
        self.assertLessEqual(len(out["answer_text"]), 20000)
        big = {"columns": ["n"], "rows": [[i] for i in range(500)], "truncated": False}
        items = [{"sql": "SELECT n", "success": True, "row_count": 500, "result": big}]
        out2 = aggregate.full_detail_view(self._row(generated_sql_json=json.dumps(items)))
        self.assertLessEqual(len(out2["sql_items"][0]["result"]["rows"]), 200)
        self.assertTrue(out2["sql_items"][0]["result"]["truncated"])


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
