# Plugin/owismind/tests/test_suggestion_validation.py
"""validate_suggestion_manual / validate_suggestion_from_chat: bounds, enums, verdict rules.

Pure (validation.py imports only stdlib math) - no DSS runtime needed.
"""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.security.validation import (  # noqa: E402
    ValidationError,
    validate_suggestion_manual,
    validate_suggestion_from_chat,
    MAX_SUGGEST_TEXT_CHARS,
    MAX_SUGGEST_CATEGORY_CHARS,
)


class ManualSuggestionTests(unittest.TestCase):
    def test_minimal_ok(self):
        out = validate_suggestion_manual(
            {"question": "  Quel est le revenu reel de X ?  ", "reference_answer": "12 345 EUR"}
        )
        self.assertEqual(out["question"], "Quel est le revenu reel de X ?")
        self.assertEqual(out["reference_answer"], "12 345 EUR")
        self.assertIsNone(out["expected_value"])
        self.assertIsNone(out["expected_value_type"])
        self.assertIsNone(out["category"])
        self.assertEqual(out["language"], "fr")

    def test_non_dict(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_suggestion_manual("nope")
        self.assertEqual(ctx.exception.code, "invalid_payload")

    def test_missing_question(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_suggestion_manual({"reference_answer": "x"})
        self.assertEqual(ctx.exception.code, "invalid_question")

    def test_blank_question(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_suggestion_manual({"question": "   ", "reference_answer": "x"})
        self.assertEqual(ctx.exception.code, "invalid_question")

    def test_missing_reference(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_suggestion_manual({"question": "q"})
        self.assertEqual(ctx.exception.code, "invalid_reference")

    def test_question_too_long(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_suggestion_manual(
                {"question": "a" * (MAX_SUGGEST_TEXT_CHARS + 1), "reference_answer": "x"}
            )
        self.assertEqual(ctx.exception.code, "invalid_question")

    def test_expected_value_requires_type(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_suggestion_manual(
                {"question": "q", "reference_answer": "r", "expected_value": "12345"}
            )
        self.assertEqual(ctx.exception.code, "missing_expected_type")

    def test_expected_value_bad_type(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_suggestion_manual(
                {"question": "q", "reference_answer": "r",
                 "expected_value": "12345", "expected_value_type": "money"}
            )
        self.assertEqual(ctx.exception.code, "invalid_expected_type")

    def test_expected_value_with_type_ok(self):
        out = validate_suggestion_manual(
            {"question": "q", "reference_answer": "r",
             "expected_value": "12345", "expected_value_type": "CURRENCY"}
        )
        self.assertEqual(out["expected_value"], "12345")
        self.assertEqual(out["expected_value_type"], "currency")

    def test_type_without_value_is_dropped(self):
        # A type alone (no value) is harmless: value stays None, type set but unused.
        out = validate_suggestion_manual(
            {"question": "q", "reference_answer": "r", "expected_value_type": "numeric"}
        )
        self.assertIsNone(out["expected_value"])
        self.assertEqual(out["expected_value_type"], "numeric")

    def test_category_and_language(self):
        out = validate_suggestion_manual(
            {"question": "q", "reference_answer": "r",
             "category": "  Revenus  ", "language": "EN"}
        )
        self.assertEqual(out["category"], "Revenus")
        self.assertEqual(out["language"], "en")

    def test_bad_language_defaults_fr(self):
        out = validate_suggestion_manual(
            {"question": "q", "reference_answer": "r", "language": "de"}
        )
        self.assertEqual(out["language"], "fr")

    def test_category_capped(self):
        out = validate_suggestion_manual(
            {"question": "q", "reference_answer": "r", "category": "c" * (MAX_SUGGEST_CATEGORY_CHARS + 50)}
        )
        self.assertEqual(len(out["category"]), MAX_SUGGEST_CATEGORY_CHARS)


class FromChatSuggestionTests(unittest.TestCase):
    def test_yes_no_reference_needed(self):
        out = validate_suggestion_from_chat(
            {"exchange_id": "e1", "answer_is_correct": True}
        )
        self.assertEqual(out["exchange_id"], "e1")
        self.assertTrue(out["answer_is_correct"])
        self.assertIsNone(out["reference_answer"])

    def test_no_requires_reference(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_suggestion_from_chat(
                {"exchange_id": "e1", "answer_is_correct": False}
            )
        self.assertEqual(ctx.exception.code, "missing_reference")

    def test_no_with_reference_ok(self):
        out = validate_suggestion_from_chat(
            {"exchange_id": "e1", "answer_is_correct": False,
             "reference_answer": "Le bon total est 9 999 EUR",
             "missing_explanation": "il a oublie le filtre annee", "category": "revenus"}
        )
        self.assertFalse(out["answer_is_correct"])
        self.assertEqual(out["reference_answer"], "Le bon total est 9 999 EUR")
        self.assertEqual(out["missing_explanation"], "il a oublie le filtre annee")
        self.assertEqual(out["category"], "revenus")

    def test_verdict_must_be_bool(self):
        # int 1 is NOT a bool (isinstance(1, bool) is False) -> rejected.
        for bad in (1, 0, "yes", "true", None):
            with self.assertRaises(ValidationError) as ctx:
                validate_suggestion_from_chat({"exchange_id": "e1", "answer_is_correct": bad})
            self.assertEqual(ctx.exception.code, "invalid_verdict")

    def test_missing_exchange_id(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_suggestion_from_chat({"answer_is_correct": True})
        self.assertEqual(ctx.exception.code, "invalid_exchange_id")

    def test_non_dict(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_suggestion_from_chat(None)
        self.assertEqual(ctx.exception.code, "invalid_payload")

    def test_yes_optional_note_kept(self):
        out = validate_suggestion_from_chat(
            {"exchange_id": "e1", "answer_is_correct": True,
             "reference_answer": "  meme reponse, parfaite  "}
        )
        # A "Yes" may still carry a confirming reference text (kept, trimmed).
        self.assertEqual(out["reference_answer"], "meme reponse, parfaite")


if __name__ == "__main__":
    unittest.main()
