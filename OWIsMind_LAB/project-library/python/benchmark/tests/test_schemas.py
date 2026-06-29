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
        "language": "fr",
        "active": True,
        "notes": "",
    }


class TestEnums(unittest.TestCase):
    def test_enum_tuples(self):
        # schemas.MODES re-exports the canonical config.MODES (Smart/Pro/Claude), the values
        # actually stored in the 'mode' column - not the old pre-rename internal keys.
        self.assertEqual(schemas.MODES, ("Smart", "Pro", "Claude"))
        self.assertEqual(
            schemas.EXPECTED_VALUE_TYPES,
            ("numeric", "currency", "date", "string", "list"),
        )
        self.assertEqual(schemas.LANGUAGES, ("fr", "en"))


class TestColumnLists(unittest.TestCase):
    def test_golden_columns_present(self):
        for col in ("question_id", "question", "reference_answer",
                    "expected_value", "expected_value_type", "category",
                    "language", "active", "notes"):
            self.assertIn(col, schemas.GOLDEN_COLUMNS)
        # The over-engineered fields were deliberately dropped (lean schema).
        for col in ("answer_type", "difficulty", "expected_mode", "target_agent"):
            self.assertNotIn(col, schemas.GOLDEN_COLUMNS)

    def test_scored_extends_raw(self):
        # Every raw column is also a scored column (scored = detail table).
        for col in schemas.RAW_COLUMNS:
            self.assertIn(col, schemas.SCORED_COLUMNS)
        for col in ("objective_match", "judge_score", "judge_verdict",
                    "correct", "needs_review"):
            self.assertIn(col, schemas.SCORED_COLUMNS)

    def test_notes_in_raw(self):
        # The human strictness note travels with each run row so the judge can read it.
        self.assertIn("notes", schemas.RAW_COLUMNS)

    def test_judge_comment_and_human_override_columns(self):
        # The concise judge comment + the human override fields (survive re-runs in scored).
        for col in ("judge_comment", "human_verdict", "human_correct",
                    "human_comment", "reviewed_by", "reviewed_at"):
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
        row["language"] = "de"
        row["expected_value_type"] = "money"
        ok, errors = schemas.validate_golden_row(row)
        self.assertFalse(ok)
        self.assertEqual(len(errors), 2)

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


class TestEffectiveCorrect(unittest.TestCase):
    """The human override (human_verdict) wins over the machine `correct` at read time."""

    def test_no_override_mirrors_machine(self):
        out = schemas.effective_correct({"correct": True, "human_verdict": ""})
        self.assertTrue(out["correct"])
        self.assertFalse(out["overridden"])
        self.assertEqual(out["verdict"], "correct")

    def test_no_override_machine_incorrect(self):
        out = schemas.effective_correct({"correct": False, "human_verdict": None})
        self.assertFalse(out["correct"])
        self.assertFalse(out["overridden"])

    def test_human_correct_wins_over_machine_incorrect(self):
        out = schemas.effective_correct({"correct": False, "human_verdict": "correct"})
        self.assertTrue(out["correct"])
        self.assertTrue(out["overridden"])
        self.assertEqual(out["verdict"], "correct")

    def test_human_incorrect_wins_over_machine_correct(self):
        out = schemas.effective_correct({"correct": True, "human_verdict": "incorrect"})
        self.assertFalse(out["correct"])
        self.assertTrue(out["overridden"])

    def test_garbage_human_verdict_is_ignored(self):
        out = schemas.effective_correct({"correct": True, "human_verdict": "maybe"})
        self.assertTrue(out["correct"])
        self.assertFalse(out["overridden"])

    def test_never_raises_on_non_dict(self):
        out = schemas.effective_correct(None)
        self.assertFalse(out["correct"])
        self.assertFalse(out["overridden"])


class TestNormalizeGoldenRow(unittest.TestCase):
    def test_trim_and_defaults(self):
        row = {
            "question_id": "  q1  ",
            "question": " hi ",
            "reference_answer": "ans",
            "category": "c",
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

    def test_reference_sql_tool_columns(self):
        # v2: the reference SQL / tool are nullable golden columns, trimmed, blank -> None.
        self.assertIn("expected_sql", schemas.GOLDEN_COLUMNS)
        self.assertIn("expected_tool", schemas.GOLDEN_COLUMNS)
        out = schemas.normalize_golden_row({
            "question_id": "q1", "question": "q", "reference_answer": "a",
            "expected_sql": "  SELECT 1 ", "expected_tool": " show_chart ",
        })
        self.assertEqual(out["expected_sql"], "SELECT 1")
        self.assertEqual(out["expected_tool"], "show_chart")
        # blank -> None (still optional: validate_golden_row stays happy)
        out2 = schemas.normalize_golden_row({
            "question_id": "q1", "question": "q", "reference_answer": "a",
            "expected_sql": "   ", "expected_tool": None,
        })
        self.assertIsNone(out2["expected_sql"])
        self.assertIsNone(out2["expected_tool"])
        ok, errors = schemas.validate_golden_row(out2)
        self.assertTrue(ok, errors)

    def test_reference_columns_in_raw_and_scored(self):
        for col in ("benchmark_id", "benchmark_name", "attempt_no",
                    "expected_sql", "expected_tool", "actual_tools"):
            self.assertIn(col, schemas.RAW_COLUMNS)
            self.assertIn(col, schemas.SCORED_COLUMNS)

    def test_non_dict_returns_empty(self):
        self.assertEqual(schemas.normalize_golden_row(None), {})

    def test_nan_cells_become_none(self):
        # Pandas renders an empty cell as a float NaN; it must normalize to None
        # (not propagate into benchmark_runs_raw and crash the judge later).
        nan = float("nan")
        out = schemas.normalize_golden_row({
            "question_id": "q1", "question": "q", "reference_answer": "a",
            "expected_value": nan, "expected_value_type": nan, "category": nan,
        })
        self.assertIsNone(out["expected_value"])
        self.assertIsNone(out["expected_value_type"])
        self.assertIsNone(out["category"])
        # And a NaN expected_value no longer trips the "value without type" rule.
        ok, errors = schemas.validate_golden_row(out)
        self.assertTrue(ok, errors)


if __name__ == "__main__":
    unittest.main()
