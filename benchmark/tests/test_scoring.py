"""Tests for benchmark.scoring (aggregation maths, percentiles, breakdowns).

Stdlib only, no DSS. Builds a small synthetic ``benchmark_runs_scored`` list
mixing correct / incorrect / errored rows across two modes and two categories,
then asserts the summary KPIs (accuracy, error rate, percentiles, score
distribution, costs, tokens, needs_review) and the breakdown buckets.
"""

import json
import unittest

from benchmark import scoring
from benchmark.schemas import SUMMARY_COLUMNS, BREAKDOWN_COLUMNS


def _row(**over):
    """A scored row with sensible defaults; override what each test needs."""
    base = {
        "run_id": "run1",
        "run_timestamp": "2026-06-24T10:00:00Z",
        "agent_key": "orchestrator",
        "agent_label": "OWIsMind orchestrator",
        "mode": "smart",
        "category": "revenus",
        "status": "ok",
        "judge_score": 5,
        "correct": True,
        "needs_review": False,
        "latency_total_s": 1.0,
        "time_to_first_token_s": 0.5,
        "estimated_cost": 0.01,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "judge_estimated_cost": 0.002,
    }
    base.update(over)
    return base


def _dataset():
    """Synthetic scored set: one run, two modes, two categories, mixed outcomes.

    smart mode (5 questions):
      - 3 correct (scores 5, 4, 4), 1 incorrect (score 2), 1 errored.
      categories: revenus x3 (2 ok-correct + 1 ok-incorrect), tickets x2
        (1 ok-correct + 1 errored).
    claude mode (2 questions):
      - 1 correct (score 5), 1 needs_review correct (score 3), both revenus.
    """
    return [
        # --- smart / revenus ---
        _row(mode="smart", category="revenus", judge_score=5, correct=True,
             latency_total_s=1.0, time_to_first_token_s=0.5,
             estimated_cost=0.01, prompt_tokens=100, completion_tokens=50,
             judge_estimated_cost=0.002),
        _row(mode="smart", category="revenus", judge_score=4, correct=True,
             latency_total_s=2.0, time_to_first_token_s=0.7,
             estimated_cost=0.02, prompt_tokens=200, completion_tokens=80,
             judge_estimated_cost=0.002),
        _row(mode="smart", category="revenus", judge_score=2, correct=False,
             latency_total_s=3.0, time_to_first_token_s=0.9,
             estimated_cost=0.03, prompt_tokens=300, completion_tokens=120,
             judge_estimated_cost=0.002),
        # --- smart / tickets ---
        _row(mode="smart", category="tickets", judge_score=4, correct=True,
             latency_total_s=4.0, time_to_first_token_s=1.1,
             estimated_cost=0.04, prompt_tokens=400, completion_tokens=200,
             judge_estimated_cost=0.002),
        # errored smart/tickets row: no score, no latency, still counted in n
        _row(mode="smart", category="tickets", status="error",
             judge_score=None, correct=False, needs_review=True,
             latency_total_s=None, time_to_first_token_s=None,
             estimated_cost=None, prompt_tokens=None, completion_tokens=None,
             judge_estimated_cost=0.0),
        # --- claude / revenus ---
        _row(mode="claude", category="revenus", judge_score=5, correct=True,
             latency_total_s=10.0, time_to_first_token_s=2.0,
             estimated_cost=0.50, prompt_tokens=1000, completion_tokens=400,
             judge_estimated_cost=0.01),
        _row(mode="claude", category="revenus", judge_score=3, correct=True,
             needs_review=True, latency_total_s=20.0, time_to_first_token_s=3.0,
             estimated_cost=0.70, prompt_tokens=1200, completion_tokens=500,
             judge_estimated_cost=0.01),
    ]


class TestPercentile(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(scoring.percentile([], 0.5), 0.0)

    def test_single_value(self):
        self.assertEqual(scoring.percentile([7.0], 0.95), 7.0)

    def test_median_odd(self):
        self.assertEqual(scoring.percentile([1, 2, 3], 0.5), 2.0)

    def test_median_even_interpolates(self):
        # linear (type-7): pos = 0.5 * 3 = 1.5 -> between 2 and 3 -> 2.5
        self.assertEqual(scoring.percentile([1, 2, 3, 4], 0.5), 2.5)

    def test_p95_interpolates(self):
        # 10 values 1..10: pos = 0.95 * 9 = 8.55 -> between 9 and 10 -> 9.55
        vals = list(range(1, 11))
        self.assertAlmostEqual(scoring.percentile(vals, 0.95), 9.55)

    def test_bounds_clamped(self):
        self.assertEqual(scoring.percentile([3, 1, 2], 0.0), 1.0)
        self.assertEqual(scoring.percentile([3, 1, 2], 1.0), 3.0)
        self.assertEqual(scoring.percentile([3, 1, 2], 5.0), 3.0)

    def test_drops_non_numeric(self):
        self.assertEqual(scoring.percentile([None, "x", 4, 6], 0.5), 5.0)


class TestSummarize(unittest.TestCase):
    def setUp(self):
        self.rows = scoring.summarize(_dataset())
        self.by_mode = {r["mode"]: r for r in self.rows}

    def test_one_row_per_mode(self):
        self.assertEqual(len(self.rows), 2)
        self.assertIn("smart", self.by_mode)
        self.assertIn("claude", self.by_mode)

    def test_columns_exact(self):
        for r in self.rows:
            self.assertEqual(list(r.keys()), list(SUMMARY_COLUMNS))

    def test_ordered_by_key(self):
        # claude < smart alphabetically on the mode part of the key (output is sorted).
        self.assertEqual([r["mode"] for r in self.rows], ["claude", "smart"])

    def test_smart_counts(self):
        smart = self.by_mode["smart"]
        self.assertEqual(smart["n_questions"], 5)
        self.assertEqual(smart["n_ok"], 4)
        self.assertEqual(smart["n_error"], 1)
        self.assertAlmostEqual(smart["error_rate"], 1 / 5.0)

    def test_smart_accuracy_over_scored_only(self):
        # 4 ok rows, 3 correct -> 0.75 (errored row excluded from denominator).
        smart = self.by_mode["smart"]
        self.assertAlmostEqual(smart["accuracy"], 0.75)

    def test_smart_mean_score(self):
        # ok scores: 5, 4, 2, 4 -> mean 3.75 (errored row has no score).
        smart = self.by_mode["smart"]
        self.assertAlmostEqual(smart["mean_score"], 3.75)

    def test_smart_score_dist(self):
        smart = self.by_mode["smart"]
        dist = json.loads(smart["score_dist_json"])
        self.assertEqual(dist, {"1": 0, "2": 1, "3": 0, "4": 2, "5": 1})

    def test_smart_latency_percentiles_exclude_errored(self):
        # ok latencies sorted: 1, 2, 3, 4.
        smart = self.by_mode["smart"]
        self.assertAlmostEqual(smart["latency_p50_s"], 2.5)   # mid of 2 and 3
        self.assertAlmostEqual(smart["latency_max_s"], 4.0)
        # p95: pos = 0.95 * 3 = 2.85 -> between 3 and 4 -> 3.85
        self.assertAlmostEqual(smart["latency_p95_s"], 3.85)

    def test_smart_ttft_p50(self):
        # ok ttfts sorted: 0.5, 0.7, 0.9, 1.1 -> p50 mid of 0.7 and 0.9 = 0.8
        smart = self.by_mode["smart"]
        self.assertAlmostEqual(smart["ttft_p50_s"], 0.8)

    def test_smart_costs_and_tokens(self):
        smart = self.by_mode["smart"]
        # ok costs: 0.01 + 0.02 + 0.03 + 0.04 = 0.10 over 4 -> 0.025 avg.
        self.assertAlmostEqual(smart["total_cost"], 0.10)
        self.assertAlmostEqual(smart["avg_cost_per_q"], 0.025)
        # ok input tokens: 100, 200, 300, 400 -> avg 250.
        self.assertAlmostEqual(smart["avg_input_tokens"], 250.0)
        # ok output tokens: 50, 80, 120, 200 -> avg 112.5.
        self.assertAlmostEqual(smart["avg_output_tokens"], 112.5)

    def test_smart_needs_review_and_judge_cost(self):
        smart = self.by_mode["smart"]
        # only the errored row has needs_review True.
        self.assertEqual(smart["needs_review_count"], 1)
        # judge cost summed over ALL rows (incl. errored 0.0): 4 * 0.002 + 0.0.
        self.assertAlmostEqual(smart["judge_total_cost"], 0.008)

    def test_high_counts_and_accuracy(self):
        claude = self.by_mode["claude"]
        self.assertEqual(claude["n_questions"], 2)
        self.assertEqual(claude["n_ok"], 2)
        self.assertEqual(claude["n_error"], 0)
        self.assertAlmostEqual(claude["error_rate"], 0.0)
        self.assertAlmostEqual(claude["accuracy"], 1.0)
        self.assertEqual(claude["needs_review_count"], 1)

    def test_high_total_cost(self):
        claude = self.by_mode["claude"]
        self.assertAlmostEqual(claude["total_cost"], 1.20)
        self.assertAlmostEqual(claude["latency_max_s"], 20.0)


class TestSummarizeEdgeCases(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(scoring.summarize([]), [])
        self.assertEqual(scoring.summarize(None), [])

    def test_all_errored_group(self):
        rows = [
            _row(status="error", judge_score=None, correct=False,
                 latency_total_s=None, estimated_cost=None),
            _row(status="timeout", judge_score=None, correct=False,
                 latency_total_s=None, estimated_cost=None),
        ]
        out = scoring.summarize(rows)
        self.assertEqual(len(out), 1)
        g = out[0]
        self.assertEqual(g["n_questions"], 2)
        self.assertEqual(g["n_ok"], 0)
        self.assertEqual(g["n_error"], 2)
        self.assertAlmostEqual(g["error_rate"], 1.0)
        # no scored rows -> accuracy / mean_score / latencies collapse to 0.0.
        self.assertEqual(g["accuracy"], 0.0)
        self.assertEqual(g["mean_score"], 0.0)
        self.assertEqual(g["latency_p50_s"], 0.0)
        self.assertEqual(g["latency_max_s"], 0.0)
        self.assertEqual(json.loads(g["score_dist_json"]),
                         {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0})

    def test_blank_status_counts_as_ok(self):
        rows = [_row(status="", judge_score=5, correct=True)]
        g = scoring.summarize(rows)[0]
        self.assertEqual(g["n_ok"], 1)
        self.assertEqual(g["n_error"], 0)

    def test_non_dict_rows_skipped(self):
        rows = [_row(), "garbage", None, 42]
        out = scoring.summarize(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["n_questions"], 1)

    def test_out_of_range_score_dropped(self):
        rows = [
            _row(judge_score=7, correct=True),   # invalid -> not in dist, no mean
            _row(judge_score=5, correct=True),
        ]
        g = scoring.summarize(rows)[0]
        dist = json.loads(g["score_dist_json"])
        self.assertEqual(dist, {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1})
        # mean over the one valid score only.
        self.assertAlmostEqual(g["mean_score"], 5.0)


class TestBreakdown(unittest.TestCase):
    def setUp(self):
        self.rows = scoring.breakdown(_dataset())

    def test_columns_exact(self):
        for r in self.rows:
            self.assertEqual(list(r.keys()), list(BREAKDOWN_COLUMNS))

    def _find(self, mode, dimension, bucket):
        for r in self.rows:
            if (r["mode"] == mode and r["dimension"] == dimension
                    and r["bucket"] == bucket):
                return r
        return None

    def test_dimensions_covered(self):
        # Lean schema: category is the single breakdown axis.
        dims = {r["dimension"] for r in self.rows}
        self.assertEqual(dims, {"category"})

    def test_smart_category_revenus(self):
        # smart/revenus ok rows: scores 5,4,2 ; correct True,True,False.
        r = self._find("smart", "category", "revenus")
        self.assertIsNotNone(r)
        self.assertEqual(r["n"], 3)
        self.assertAlmostEqual(r["accuracy"], 2 / 3.0)
        self.assertAlmostEqual(r["mean_score"], (5 + 4 + 2) / 3.0)

    def test_smart_category_tickets_excludes_errored(self):
        # smart/tickets: 1 ok-correct (score 4) + 1 errored (excluded).
        r = self._find("smart", "category", "tickets")
        self.assertIsNotNone(r)
        self.assertEqual(r["n"], 1)
        self.assertAlmostEqual(r["accuracy"], 1.0)
        self.assertAlmostEqual(r["mean_score"], 4.0)

    def test_high_category_revenus(self):
        r = self._find("claude", "category", "revenus")
        self.assertIsNotNone(r)
        self.assertEqual(r["n"], 2)
        self.assertAlmostEqual(r["accuracy"], 1.0)
        self.assertAlmostEqual(r["mean_score"], 4.0)

    def test_buckets_ordered(self):
        # within smart/category, buckets are alphabetical: revenus before tickets.
        smart_cat = [r["bucket"] for r in self.rows
                   if r["mode"] == "smart" and r["dimension"] == "category"]
        self.assertEqual(smart_cat, sorted(smart_cat))

    def test_blank_bucket_skipped(self):
        rows = [_row(category=None), _row(category="revenus")]
        out = scoring.breakdown(rows)
        cat_buckets = [r["bucket"] for r in out if r["dimension"] == "category"]
        self.assertEqual(cat_buckets, ["revenus"])

    def test_empty_input(self):
        self.assertEqual(scoring.breakdown([]), [])

    def test_meta_propagated(self):
        r = self._find("smart", "category", "revenus")
        self.assertEqual(r["run_id"], "run1")
        self.assertEqual(r["agent_key"], "orchestrator")
        self.assertEqual(r["agent_label"], "OWIsMind orchestrator")
        self.assertEqual(r["run_timestamp"], "2026-06-24T10:00:00Z")


if __name__ == "__main__":
    unittest.main()
