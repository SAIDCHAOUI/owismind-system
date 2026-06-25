"""Tests for benchmark.schemas (golden validation + column lists + caps).

Stdlib only, no DSS. Proves the enum tuples, the column-list contracts, golden
validation (required fields, enums, expected_value pairing), normalization, and
that the caps are mirrored from the capture layer.
"""

import unittest

from benchmark import schemas


def _valid_golden_row():
    return {
        "question_id": "q001",
        "question": "Quel est le revenu reel du compte Maroc Telecom ?",
        "reference_answer": "1 234 567,89 EUR",
        "expected_value": "1234567.89",
        "expected_value_type": "currency",
        "category": "revenus",
        "answer_type": "number",
        "difficulty": "medium",
        "expected_mode": "eco",
        "target_agent": "revenue_expert",
        "language": "fr",
        "active": True,
        "notes": "",
    }


class TestEnums(unittest.TestCase):
    def test_enum_tuples(self):
        self.assertEqual(schemas.MODES, ("eco", "medium", "high"))
        self.assertEqual(
            schemas.EXPECTED_VALUE_TYPES,
            ("numeric", "currency", "date", "string", "list"),
        )
        self.assertEqual(
            schemas.ANSWER_TYPES, ("number", "fact", "list", "explanation")
        )
        self.assertEqual(schemas.DIFFICULTIES, ("easy", "medium", "hard"))
        self.assertEqual(schemas.LANGUAGES, ("fr", "en"))


class TestColumnLists(unittest.TestCase):
    def test_golden_columns_present(self):
        for col in ("question_id", "question", "reference_answer",
                    "expected_value", "expected_value_type", "category",
                    "answer_type", "difficulty", "language", "active"):
            self.assertIn(col, schemas.GOLDEN_COLUMNS)

    def test_scored_extends_raw(self):
        # Every raw column is also a scored column (scored = detail table).
        for col in schemas.RAW_COLUMNS:
            self.assertIn(col, schemas.SCORED_COLUMNS)
        for col in ("objective_match", "judge_score", "judge_verdict",
                    "correct", "needs_review"):
            self.assertIn(col, schemas.SCORED_COLUMNS)

    def test_full_answer_in_raw(self):
        # The complete answer (judge input) and the proof SQL must be persisted.
        self.assertIn("full_answer", schemas.RAW_COLUMNS)
        self.assertIn("generated_sql_json", schemas.RAW_COLUMNS)

    def test_summary_and_breakdown_columns(self):
        for col in ("accuracy", "mean_score", "score_dist_json",
                    "latency_p50_s", "latency_p95_s", "latency_max_s",
                    "ttft_p50_s", "avg_cost_per_q", "total_cost",
                    "error_rate", "needs_review_count", "judge_total_cost"):
            self.assertIn(col, schemas.SUMMARY_COLUMNS)
        for col in ("dimension", "bucket", "n", "accuracy", "mean_score"):
            self.assertIn(col, schemas.BREAKDOWN_COLUMNS)

    def test_breakdown_dimensions_are_golden_columns(self):
        for dim in schemas.BREAKDOWN_DIMENSIONS:
            self.assertIn(dim, schemas.GOLDEN_COLUMNS)


class TestCapsMirrored(unittest.TestCase):
    def test_caps_match_capture(self):
        from benchmark import agent_capture as cap
        self.assertEqual(schemas.MAX_RESULT_ROWS, cap.MAX_RESULT_ROWS)
        self.assertEqual(schemas.MAX_RESULT_COLS, cap.MAX_RESULT_COLS)
        self.assertEqual(schemas.MAX_CELL_CHARS, cap.MAX_CELL_CHARS)
        self.assertEqual(schemas.MAX_SQL_ITEMS, cap.MAX_SQL_ITEMS)
        self.assertEqual(schemas.MAX_ITEM_SQL_CHARS, cap.MAX_ITEM_SQL_CHARS)


class TestValidateGoldenRow(unittest.TestCase):
    def test_valid_row(self):
        ok, errors = schemas.validate_golden_row(_valid_golden_row())
        self.assertTrue(ok, errors)
        self.assertEqual(errors, [])

    def test_missing_required(self):
        row = _valid_golden_row()
        del row["question"]
        ok, errors = schemas.validate_golden_row(row)
        self.assertFalse(ok)
        self.assertTrue(any("question" in e for e in errors))

    def test_blank_required_is_invalid(self):
        row = _valid_golden_row()
        row["reference_answer"] = "   "
        ok, errors = schemas.validate_golden_row(row)
        self.assertFalse(ok)

    def test_invalid_enums(self):
        row = _valid_golden_row()
        row["answer_type"] = "essay"
        row["difficulty"] = "trivial"
        row["language"] = "de"
        row["expected_value_type"] = "money"
        row["expected_mode"] = "turbo"
        ok, errors = schemas.validate_golden_row(row)
        self.assertFalse(ok)
        self.assertEqual(len(errors), 5)

    def test_expected_value_requires_type(self):
        row = _valid_golden_row()
        row["expected_value"] = "42"
        row["expected_value_type"] = None
        ok, errors = schemas.validate_golden_row(row)
        self.assertFalse(ok)
        self.assertTrue(any("expected_value_type" in e for e in errors))

    def test_no_expected_value_is_ok(self):
        row = _valid_golden_row()
        row["expected_value"] = None
        row["expected_value_type"] = None
        ok, errors = schemas.validate_golden_row(row)
        self.assertTrue(ok, errors)

    def test_non_dict_row(self):
        ok, errors = schemas.validate_golden_row("not a row")
        self.assertFalse(ok)


class TestNormalizeGoldenRow(unittest.TestCase):
    def test_trim_and_defaults(self):
        row = {
            "question_id": "  q1  ",
            "question": " hi ",
            "reference_answer": "ans",
            "category": "c",
            "answer_type": "fact",
            "difficulty": "easy",
            # language omitted -> default 'fr'
            # active omitted -> default True
            "notes": "   ",
        }
        out = schemas.normalize_golden_row(row)
        self.assertEqual(out["question_id"], "q1")
        self.assertEqual(out["question"], "hi")
        self.assertEqual(out["language"], "fr")
        self.assertTrue(out["active"])
        self.assertIsNone(out["notes"])  # blank -> None

    def test_active_coercion(self):
        out = schemas.normalize_golden_row({"active": "false"})
        self.assertFalse(out["active"])
        out = schemas.normalize_golden_row({"active": 0})
        self.assertFalse(out["active"])
        out = schemas.normalize_golden_row({"active": "yes"})
        self.assertTrue(out["active"])

    def test_keys_are_full_golden_schema(self):
        out = schemas.normalize_golden_row(_valid_golden_row())
        self.assertEqual(set(out.keys()), set(schemas.GOLDEN_COLUMNS))

    def test_non_dict_returns_empty(self):
        self.assertEqual(schemas.normalize_golden_row(None), {})


if __name__ == "__main__":
    unittest.main()
