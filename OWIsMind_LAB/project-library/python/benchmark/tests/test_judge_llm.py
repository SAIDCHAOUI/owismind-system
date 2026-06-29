"""Tests for the judge's structured payload coercion + prompt assembly (PURE, stdlib).

Covers the concise ``comment`` field (the small per-decision note surfaced as a column) and
the human ``notes`` strictness contract woven into the judge prompt. No DSS, no Mesh call.
"""

import unittest

from benchmark import judge


class TestCoerceComment(unittest.TestCase):
    def test_comment_kept_and_bounded(self):
        out = judge._coerce_judge_payload({
            "score": 5, "verdict": "correct", "justification": "ok",
            "comment": "x" * 1000, "hallucination": False,
        })
        self.assertIn("comment", out)
        self.assertLessEqual(len(out["comment"]), 200)
        self.assertTrue(out["comment"].startswith("x"))

    def test_comment_defaults_blank(self):
        out = judge._coerce_judge_payload({
            "score": 4, "verdict": "correct", "justification": "ok",
            "hallucination": False,
        })
        self.assertEqual(out["comment"], "")

    def test_safe_failure_has_blank_comment(self):
        out = judge._safe_failure("mesh down")
        self.assertEqual(out["comment"], "")
        self.assertEqual(out["error"], "mesh down")


class TestJudgePromptNotes(unittest.TestCase):
    def test_note_included_as_strictness_contract(self):
        prompt = judge.build_judge_prompt(
            "How much revenue?", "About 36 million.", "36 millions",
            "The total is 36456876.", notes="I want the exact figure to the unit.")
        self.assertIn("I want the exact figure to the unit.", prompt)
        # The section header makes clear the note governs strictness.
        self.assertIn("NOTE", prompt.upper())

    def test_no_note_section_when_blank(self):
        prompt = judge.build_judge_prompt(
            "How much revenue?", "About 36 million.", "36 millions",
            "The total is 36456876.", notes="")
        # No empty "HUMAN NOTE:" label dangling when there is no note.
        self.assertNotIn("HUMAN NOTE", prompt.upper())

    def test_prompt_backward_compatible_without_notes(self):
        # Calling without the new notes argument must still work (default None).
        prompt = judge.build_judge_prompt(
            "Q", "ref", "42", "answer is 42")
        self.assertIn("Q", prompt)
        self.assertIn("ref", prompt)


if __name__ == "__main__":
    unittest.main()
