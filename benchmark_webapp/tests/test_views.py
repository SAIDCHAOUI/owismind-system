"""benchmark_webapp.views - pure shaping + config validation (no DSS runtime).

Run from the repo root: ``python3 -m unittest discover -s benchmark_webapp/tests``.
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _REPO)

from benchmark_webapp import views  # noqa: E402


class FormatTests(unittest.TestCase):
    def test_pct(self):
        self.assertEqual(views.fmt_pct(0.825), "82.5 %")
        self.assertEqual(views.fmt_pct(0), "0.0 %")
        self.assertEqual(views.fmt_pct(None), "-")
        self.assertEqual(views.fmt_pct("nope"), "-")

    def test_money(self):
        self.assertEqual(views.fmt_money(1.2345), "$1.2345")
        self.assertEqual(views.fmt_money2(12.5), "$12.50")
        self.assertEqual(views.fmt_money(None), "-")

    def test_secs(self):
        self.assertEqual(views.fmt_secs(1.43), "1.4 s")
        self.assertEqual(views.fmt_secs(None), "-")


class RunSelectorTests(unittest.TestCase):
    def test_latest_and_runs(self):
        rows = [
            {"run_id": "a", "run_timestamp": "2026-06-25T10:00:00"},
            {"run_id": "b", "run_timestamp": "2026-06-25T12:00:00"},
            {"run_id": "a", "run_timestamp": "2026-06-25T10:00:00"},
        ]
        self.assertEqual(views.latest_run_id(rows), "b")
        runs = views.runs_view(rows)
        self.assertEqual([r["run_id"] for r in runs], ["b", "a"])

    def test_empty(self):
        self.assertEqual(views.latest_run_id([]), "")
        self.assertEqual(views.runs_view(None), [])


class SummaryViewTests(unittest.TestCase):
    def _rows(self):
        return [
            {"run_id": "r1", "run_timestamp": "t", "agent_key": "orch", "agent_label": "Orch",
             "mode": "Smart", "n_questions": 10, "n_ok": 10, "n_error": 0, "error_rate": 0.0,
             "accuracy": 0.8, "mean_score": 4.2, "latency_p50_s": 1.0, "latency_p95_s": 2.0,
             "avg_cost_per_q": 0.01, "total_cost": 0.10, "needs_review_count": 1,
             "judge_total_cost": 0.02},
            {"run_id": "r1", "run_timestamp": "t", "agent_key": "orch", "agent_label": "Orch",
             "mode": "Claude", "n_questions": 10, "n_ok": 10, "n_error": 0, "error_rate": 0.0,
             "accuracy": 0.5, "mean_score": 3.0, "latency_p50_s": 4.0, "latency_p95_s": 8.0,
             "avg_cost_per_q": 0.05, "total_cost": 0.50, "needs_review_count": 2,
             "judge_total_cost": 0.03},
            # a row from another run, must be filtered out when run_id=r1
            {"run_id": "r0", "agent_label": "Orch", "mode": "Smart", "n_ok": 10, "accuracy": 1.0},
        ]

    def test_global_accuracy_weighted(self):
        out = views.summary_view(self._rows(), run_id="r1")
        # 8 correct + 5 correct over 20 ok = 0.65
        self.assertAlmostEqual(out["kpis"]["accuracy"], 0.65, places=6)
        self.assertEqual(out["kpis"]["accuracy_pct"], "65.0 %")
        self.assertEqual(out["kpis"]["n_questions"], 10)
        self.assertEqual(out["kpis"]["n_configs"], 2)
        self.assertEqual(out["kpis"]["needs_review"], 3)
        self.assertEqual(out["kpis"]["total_cost_str"], "$0.60")

    def test_rows_sorted_by_accuracy_desc(self):
        out = views.summary_view(self._rows(), run_id="r1")
        self.assertEqual([r["mode"] for r in out["rows"]], ["Smart", "Claude"])
        self.assertEqual(out["rows"][0]["accuracy_pct"], "80.0 %")

    def test_latest_when_no_run_id(self):
        # No run_id -> latest by timestamp; r1 has timestamp 't', r0 has none -> r1 wins.
        out = views.summary_view(self._rows())
        self.assertEqual(out["run_id"], "r1")


class BreakdownViewTests(unittest.TestCase):
    def test_shape(self):
        rows = [
            {"run_id": "r1", "agent_label": "Orch", "mode": "Smart", "dimension": "category",
             "bucket": "revenus", "n": 5, "accuracy": 0.8, "mean_score": 4.0},
            {"run_id": "r1", "agent_label": "Orch", "mode": "Smart", "dimension": "category",
             "bucket": "tickets", "n": 5, "accuracy": 0.4, "mean_score": 3.0},
        ]
        out = views.breakdown_view(rows, run_id="r1")
        self.assertEqual(len(out["rows"]), 2)
        self.assertEqual(out["rows"][0]["bucket"], "revenus")
        self.assertEqual(out["rows"][0]["accuracy_pct"], "80.0 %")


class DetailViewTests(unittest.TestCase):
    def _rows(self):
        return [
            {"run_id": "r1", "question_id": "Q1", "question": "q1", "agent_label": "Orch",
             "mode": "Smart", "status": "ok", "objective_match": "hit", "judge_score": 5,
             "judge_verdict": "correct", "correct": True, "needs_review": False,
             "answer_text": "a" * 500, "latency_total_s": 1.0, "estimated_cost": 0.01},
            {"run_id": "r1", "question_id": "Q2", "question": "q2", "agent_label": "Orch",
             "mode": "Smart", "status": "ok", "objective_match": "miss", "judge_score": 2,
             "judge_verdict": "incorrect", "correct": False, "needs_review": True,
             "answer_text": "b", "latency_total_s": 2.0, "estimated_cost": 0.02},
        ]

    def test_needs_review_first_and_preview_trimmed(self):
        out = views.detail_view(self._rows(), run_id="r1")
        self.assertEqual(out["count"], 2)
        # needs_review row sorts first
        self.assertEqual(out["rows"][0]["question_id"], "Q2")
        self.assertTrue(out["rows"][0]["needs_review"])
        # answer preview trimmed to the cap
        self.assertLessEqual(len(out["rows"][1]["answer_preview"]), 280)

    def test_only_needs_review_filter(self):
        out = views.detail_view(self._rows(), run_id="r1", only_needs_review=True)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["rows"][0]["question_id"], "Q2")

    def test_limit_keeps_needs_review_first(self):
        # Cap applies AFTER the needs-review-first sort, so the priority row survives the cap
        # even though it is second in raw order (regression: cap-before-sort dropped it).
        out = views.detail_view(self._rows(), run_id="r1", limit=1)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["rows"][0]["question_id"], "Q2")
        self.assertTrue(out["rows"][0]["needs_review"])


class ConfigValidationTests(unittest.TestCase):
    def test_valid_config_dict(self):
        ok, cfg, errors = views.validate_config({
            "agents": [{"agent_key": "orch", "project_key": "OWISMIND_DEV",
                        "agent_id": "agent:038G7mlF", "modes": True}],
            "modes": ["Smart", "Pro"],
        })
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        self.assertEqual(len(cfg["agents"]), 1)
        self.assertEqual(cfg["modes"], ["Smart", "Pro"])

    def test_valid_config_json_string(self):
        ok, cfg, errors = views.validate_config(
            '{"agents":[{"agent_key":"a","project_key":"P","agent_id":"agent:x"}]}'
        )
        self.assertTrue(ok, errors)

    def test_no_agents(self):
        ok, cfg, errors = views.validate_config({"agents": []})
        self.assertFalse(ok)
        self.assertTrue(any("agent" in e for e in errors))

    def test_bad_json(self):
        ok, cfg, errors = views.validate_config("{not json}")
        self.assertFalse(ok)
        self.assertIsNone(cfg)
        self.assertTrue(any("JSON" in e for e in errors))

    def test_non_object(self):
        ok, cfg, errors = views.validate_config(42)
        self.assertFalse(ok)

    def test_suggestions_block_resolved(self):
        ok, cfg, errors = views.validate_config({
            "agents": [{"agent_key": "a", "project_key": "P", "agent_id": "agent:x"}],
            "suggestions": {"connection": "SQL_owi",
                            "table": "OWISMIND_DEV_owismind_webapp_golden_suggestions_v1",
                            "promoted_dataset": "benchmark_suggestions_promoted"},
        })
        self.assertTrue(ok)
        cv = views.config_view(cfg)
        self.assertEqual(cv["suggestions"]["connection"], "SQL_owi")
        self.assertEqual(cv["suggestions"]["table"],
                         "OWISMIND_DEV_owismind_webapp_golden_suggestions_v1")


class PromotionTests(unittest.TestCase):
    def test_safe_table_name(self):
        self.assertEqual(
            views.safe_table_name("OWISMIND_DEV_owismind_webapp_golden_suggestions_v1"),
            "OWISMIND_DEV_owismind_webapp_golden_suggestions_v1",
        )
        self.assertIsNone(views.safe_table_name('x"; DROP TABLE y; --'))
        self.assertIsNone(views.safe_table_name(None))
        self.assertIsNone(views.safe_table_name("a b"))

    def test_suggestion_to_golden_requires_reference(self):
        self.assertIsNone(views.suggestion_to_golden(
            {"suggestion_id": "s1", "question": "q", "reference_answer": ""}))
        self.assertIsNone(views.suggestion_to_golden(
            {"suggestion_id": "s1", "question": "", "reference_answer": "r"}))

    def test_suggestion_to_golden_maps(self):
        g = views.suggestion_to_golden({
            "suggestion_id": "abc123def456", "question": "  Quel revenu ?  ",
            "reference_answer": "12345 EUR", "expected_value": "12345",
            "expected_value_type": "CURRENCY", "category": "revenus", "language": "EN",
            "source": "chat",
        })
        self.assertEqual(g["question"], "Quel revenu ?")
        self.assertEqual(g["reference_answer"], "12345 EUR")
        self.assertEqual(g["expected_value"], "12345")
        self.assertEqual(g["expected_value_type"], "currency")
        self.assertEqual(g["category"], "revenus")
        self.assertEqual(g["language"], "en")
        self.assertTrue(g["active"])
        self.assertTrue(g["question_id"].startswith("u_abc123def456"))

    def test_suggestion_to_golden_drops_value_without_valid_type(self):
        g = views.suggestion_to_golden({
            "suggestion_id": "s1", "question": "q", "reference_answer": "r",
            "expected_value": "12345", "expected_value_type": "money",
        })
        self.assertIsNone(g["expected_value"])
        self.assertIsNone(g["expected_value_type"])

    def test_promotable_filters_and_dedups(self):
        suggestions = [
            {"suggestion_id": "s1", "question": "q1", "reference_answer": "r1"},
            {"suggestion_id": "s2", "question": "q2", "reference_answer": ""},   # no ref -> skip
            {"suggestion_id": "s3", "question": "q3", "reference_answer": "r3"},
        ]
        rows, used = views.promotable_golden_rows(suggestions, already_promoted_ids=["s3"])
        self.assertEqual(used, ["s1"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question"], "q1")

    def test_suggestions_view_light(self):
        out = views.suggestions_view([
            {"suggestion_id": "s1", "user_id": "u", "source": "manual", "question": "q",
             "reference_answer": "r", "created_at": "2026-06-25T10:00:00"},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["suggestion_id"], "s1")


if __name__ == "__main__":
    unittest.main()
