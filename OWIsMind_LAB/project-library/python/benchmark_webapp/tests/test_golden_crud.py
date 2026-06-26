"""Tests for the golden-question management view helpers (pure). Stdlib only, no DSS."""

import unittest

from benchmark_webapp import views


class TestGoldenView(unittest.TestCase):
    def test_shapes_and_defaults(self):
        rows = [{
            "question_id": "a_x", "question": " Q ", "reference_answer": "R",
            "expected_value": "42", "expected_value_type": "numeric",
            "category": "revenue", "language": None, "active": None, "notes": "n",
        }]
        out = views.golden_view(rows)
        self.assertEqual(len(out), 1)
        g = out[0]
        self.assertEqual(g["language"], "fr")     # default when absent
        self.assertTrue(g["active"])              # default True when absent
        self.assertEqual(g["expected_value"], "42")

    def test_skips_rows_without_id(self):
        out = views.golden_view([{"question": "Q", "reference_answer": "R"}])
        self.assertEqual(out, [])

    def test_active_false_string_is_false(self):
        out = views.golden_view([{"question_id": "a", "active": "false"}])
        self.assertFalse(out[0]["active"])

    def test_sorted_by_category_then_id(self):
        rows = [
            {"question_id": "z", "category": "b"},
            {"question_id": "a", "category": "b"},
            {"question_id": "m", "category": "a"},
        ]
        out = views.golden_view(rows)
        self.assertEqual([g["question_id"] for g in out], ["m", "a", "z"])

    def test_never_raises_on_garbage(self):
        self.assertEqual(views.golden_view(None), [])
        self.assertEqual(views.golden_view("nope"), [])


class TestMintAdminId(unittest.TestCase):
    def test_stable_and_prefixed(self):
        a = views.mint_admin_question_id("How much revenue?", [])
        b = views.mint_admin_question_id("How much revenue?", [])
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("a_"))

    def test_collision_suffix(self):
        first = views.mint_admin_question_id("Q", [])
        second = views.mint_admin_question_id("Q", [first])
        self.assertNotEqual(first, second)
        self.assertTrue(second.startswith(first + "_"))

    def test_distinct_from_user_prefix(self):
        self.assertFalse(views.mint_admin_question_id("Q", []).startswith("u_"))


class TestPrepareGoldenSave(unittest.TestCase):
    def test_create_mints_id(self):
        row, errors, is_new = views.prepare_golden_save(
            {"question": "Q?", "reference_answer": "A."}, [])
        self.assertTrue(is_new)
        self.assertEqual(errors, [])
        self.assertTrue(row["question_id"].startswith("a_"))
        self.assertEqual(row["language"], "fr")
        self.assertTrue(row["active"])

    def test_update_keeps_id(self):
        row, errors, is_new = views.prepare_golden_save(
            {"question_id": "a_keep", "question": "Q", "reference_answer": "A"}, ["a_keep"])
        self.assertFalse(is_new)
        self.assertEqual(row["question_id"], "a_keep")
        self.assertEqual(errors, [])

    def test_missing_question_or_reference_errors(self):
        _row, errors, _new = views.prepare_golden_save({"question": "Q"}, [])
        self.assertTrue(errors)
        _row2, errors2, _new2 = views.prepare_golden_save({"reference_answer": "A"}, [])
        self.assertTrue(errors2)

    def test_expected_value_needs_type(self):
        _row, errors, _new = views.prepare_golden_save(
            {"question": "Q", "reference_answer": "A", "expected_value": "5"}, [])
        self.assertTrue(any("expected_value_type" in e for e in errors))

    def test_bad_type_rejected(self):
        _row, errors, _new = views.prepare_golden_save(
            {"question": "Q", "reference_answer": "A",
             "expected_value": "5", "expected_value_type": "banana"}, [])
        self.assertTrue(errors)

    def test_active_false_preserved(self):
        row, errors, _new = views.prepare_golden_save(
            {"question": "Q", "reference_answer": "A", "active": False}, [])
        self.assertEqual(errors, [])
        self.assertFalse(row["active"])


class TestApplyGolden(unittest.TestCase):
    def test_upsert_inserts_new(self):
        out = views.apply_golden_upsert([{"question_id": "a"}], {"question_id": "b", "question": "Q"})
        self.assertEqual([r["question_id"] for r in out], ["a", "b"])

    def test_upsert_replaces_and_preserves_extra_columns(self):
        existing = [{"question_id": "a", "question": "old", "import_batch": "2026"}]
        clean = {"question_id": "a", "question": "new", "reference_answer": "R"}
        out = views.apply_golden_upsert(existing, clean)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["question"], "new")
        self.assertEqual(out[0]["import_batch"], "2026")   # extra column survives the edit

    def test_delete_removes(self):
        out = views.apply_golden_delete([{"question_id": "a"}, {"question_id": "b"}], "a")
        self.assertEqual([r["question_id"] for r in out], ["b"])

    def test_delete_absent_is_noop(self):
        rows = [{"question_id": "a"}]
        self.assertEqual(views.apply_golden_delete(rows, "zzz"), rows)

    def test_delete_blank_is_noop(self):
        rows = [{"question_id": "a"}]
        self.assertEqual(views.apply_golden_delete(rows, "  "), rows)


if __name__ == "__main__":
    unittest.main()
