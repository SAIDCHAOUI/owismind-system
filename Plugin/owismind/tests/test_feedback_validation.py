# Plugin/owismind/tests/test_feedback_validation.py
"""validate_feedback: bounded, reason-whitelisted, rating in {0,1,None}."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.security.validation import (  # noqa: E402
    ALLOWED_FEEDBACK_REASONS, validate_feedback, ValidationError,
)


class FeedbackValidationTests(unittest.TestCase):
    def test_allowed_reasons(self):
        self.assertEqual(set(ALLOWED_FEEDBACK_REASONS), {"incorrect", "incomplete", "off_topic", "other"})

    def test_thumb_up(self):
        ex, rating, reasons, comment = validate_feedback({"exchange_id": "e1", "rating": 1})
        self.assertEqual((ex, rating, reasons, comment), ("e1", 1, [], ""))

    def test_thumb_down_with_reasons_and_comment(self):
        ex, rating, reasons, comment = validate_feedback(
            {"exchange_id": "e1", "rating": 0, "reasons": ["incorrect", "other"], "comment": "wrong total"}
        )
        self.assertEqual(rating, 0)
        self.assertEqual(reasons, ["incorrect", "other"])
        self.assertEqual(comment, "wrong total")

    def test_clear_rating_none(self):
        _, rating, _, _ = validate_feedback({"exchange_id": "e1", "rating": None})
        self.assertIsNone(rating)

    def test_unknown_reasons_dropped_and_capped(self):
        _, _, reasons, _ = validate_feedback(
            {"exchange_id": "e1", "rating": 0, "reasons": ["incorrect", "bogus", "off_topic"]}
        )
        self.assertEqual(reasons, ["incorrect", "off_topic"])

    def test_bad_rating_rejected(self):
        with self.assertRaises(ValidationError):
            validate_feedback({"exchange_id": "e1", "rating": 5})

    def test_bool_rating_rejected(self):
        with self.assertRaises(ValidationError):
            validate_feedback({"exchange_id": "e1", "rating": True})

    def test_missing_exchange_id_rejected(self):
        with self.assertRaises(ValidationError):
            validate_feedback({"rating": 1})

    def test_comment_bounded(self):
        _, _, _, comment = validate_feedback({"exchange_id": "e1", "rating": 0, "comment": "x" * 5000})
        self.assertLessEqual(len(comment), 2000)

if __name__ == "__main__":
    unittest.main()
