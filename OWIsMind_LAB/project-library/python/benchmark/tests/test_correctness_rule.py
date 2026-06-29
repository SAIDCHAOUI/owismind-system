"""Tests for benchmark.judge.final_correctness (PURE, stdlib only).

Covers every branch of the deterministic correctness rule (design section 6.3):
with-anchor (anchor is ground truth), without-anchor (lean on the judge), and the
needs_review disagreements (anchor vs judge) plus the agent-error case. No DSS.
"""

import unittest

from benchmark import judge


def _judge(verdict=None, score=None, error=None, hallucination=False):
    """Build a judge result dict like run_llm_judge returns."""
    return {
        "score": score,
        "verdict": verdict,
        "justification": "because",
        "missing_facts": [],
        "hallucination": hallucination,
        "usage": {"promptTokens": 0, "completionTokens": 0,
                  "totalTokens": 0, "estimatedCost": 0.0},
        "error": error,
    }


class TestWithAnchor(unittest.TestCase):
    """When the objective anchor is present it is the ground truth."""

    def test_hit_is_correct(self):
        out = judge.final_correctness(judge.HIT, _judge("correct", 5))
        self.assertTrue(out["correct"])
        self.assertFalse(out["needs_review"])

    def test_miss_is_incorrect(self):
        out = judge.final_correctness(judge.MISS, _judge("incorrect", 1))
        self.assertFalse(out["correct"])
        self.assertFalse(out["needs_review"])

    def test_hit_stays_correct_even_if_judge_says_incorrect(self):
        # Anchor wins on correctness, but the disagreement flags review.
        out = judge.final_correctness(judge.HIT, _judge("incorrect", 2))
        self.assertTrue(out["correct"])
        self.assertTrue(out["needs_review"])

    def test_miss_with_judge_correct_now_trusts_judge(self):
        # New contract: a MISS no longer FORCES incorrect. The contextual judge decides
        # (it can recognise an order-of-magnitude / rounded equivalence the anchor cannot).
        # correct verdict + score >= 4 -> correct True; the anchor/judge disagreement still
        # flags review so a human can confirm.
        out = judge.final_correctness(judge.MISS, _judge("correct", 5))
        self.assertTrue(out["correct"])
        self.assertTrue(out["needs_review"])

    def test_miss_with_judge_correct_low_score_not_correct(self):
        # A "correct" verdict but a low score (<4) is not confident enough -> not correct,
        # but the lean-correct judge still disagrees with the MISS -> review.
        out = judge.final_correctness(judge.MISS, _judge("correct", 3))
        self.assertFalse(out["correct"])
        self.assertTrue(out["needs_review"])

    def test_miss_with_judge_incorrect_agrees_no_review(self):
        # Anchor MISS and judge "incorrect" agree -> incorrect, no review needed.
        out = judge.final_correctness(judge.MISS, _judge("incorrect", 2))
        self.assertFalse(out["correct"])
        self.assertFalse(out["needs_review"])

    def test_miss_with_judge_error_flags_review(self):
        out = judge.final_correctness(judge.MISS, _judge(error="boom"))
        self.assertFalse(out["correct"])
        self.assertTrue(out["needs_review"])

    def test_miss_with_no_verdict_flags_review(self):
        out = judge.final_correctness(judge.MISS, _judge(verdict=None, score=None))
        self.assertFalse(out["correct"])
        self.assertTrue(out["needs_review"])

    def test_hit_with_failed_judge_flags_review(self):
        # Anchor still decides correctness; a judge error still flags review.
        out = judge.final_correctness(judge.HIT, _judge(error="boom"))
        self.assertTrue(out["correct"])
        self.assertTrue(out["needs_review"])

    def test_hit_with_agreeing_judge_no_review(self):
        out = judge.final_correctness(judge.HIT, _judge("correct", 4))
        self.assertTrue(out["correct"])
        self.assertFalse(out["needs_review"])


class TestWithoutAnchor(unittest.TestCase):
    """No anchor (n/a): correctness leans on the judge (verdict + score >= 4)."""

    def test_correct_and_high_score(self):
        out = judge.final_correctness(judge.NA, _judge("correct", 5))
        self.assertTrue(out["correct"])
        self.assertFalse(out["needs_review"])

    def test_correct_but_score_below_4_is_not_correct(self):
        out = judge.final_correctness(judge.NA, _judge("correct", 3))
        self.assertFalse(out["correct"])
        self.assertFalse(out["needs_review"])

    def test_incorrect_verdict_is_not_correct(self):
        out = judge.final_correctness(judge.NA, _judge("incorrect", 4))
        self.assertFalse(out["correct"])
        self.assertFalse(out["needs_review"])

    def test_score_4_boundary_is_correct(self):
        out = judge.final_correctness(judge.NA, _judge("correct", 4))
        self.assertTrue(out["correct"])

    def test_missing_verdict_flags_review_and_not_correct(self):
        out = judge.final_correctness(judge.NA, _judge(verdict=None, score=None))
        self.assertFalse(out["correct"])
        self.assertTrue(out["needs_review"])

    def test_judge_error_without_anchor_flags_review(self):
        out = judge.final_correctness(judge.NA, _judge(error="mesh down"))
        self.assertFalse(out["correct"])
        self.assertTrue(out["needs_review"])

    def test_verdict_without_score_flags_review(self):
        # The prompt-only judge fallback can return a verdict with no usable score; that
        # ambiguity must flag review, not be silently scored wrong.
        out = judge.final_correctness(judge.NA, _judge("correct", None))
        self.assertFalse(out["correct"])
        self.assertTrue(out["needs_review"])

    def test_none_anchor_treated_as_no_anchor(self):
        # A missing objective_match value behaves like n/a.
        out = judge.final_correctness(None, _judge("correct", 5))
        self.assertTrue(out["correct"])
        self.assertFalse(out["needs_review"])


class TestAgentError(unittest.TestCase):
    """An explicit agent error never passes and always needs review."""

    def test_error_anchor_never_correct(self):
        out = judge.final_correctness("error", _judge("correct", 5))
        self.assertFalse(out["correct"])
        self.assertTrue(out["needs_review"])


class TestRobustness(unittest.TestCase):
    def test_empty_judge_dict_no_anchor(self):
        out = judge.final_correctness(judge.NA, {})
        self.assertFalse(out["correct"])
        self.assertTrue(out["needs_review"])

    def test_none_judge_no_anchor(self):
        out = judge.final_correctness(judge.NA, None)
        self.assertFalse(out["correct"])
        self.assertTrue(out["needs_review"])

    def test_none_judge_with_hit_anchor(self):
        out = judge.final_correctness(judge.HIT, None)
        self.assertTrue(out["correct"])
        # No verdict to disagree with, no judge error -> no review.
        self.assertFalse(out["needs_review"])


if __name__ == "__main__":
    unittest.main()
