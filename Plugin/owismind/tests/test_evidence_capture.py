# Plugin/owismind/tests/test_evidence_capture.py
"""evidence.capture: pure opportunistic result extraction + mirrored persistence caps.

No dataiku import (pure module). Locks the frozen trust-layer contract (spec §1):
candidate row keys probed in order, list-of-lists / list-of-dicts shapes, honest
``None`` on anything unrecognised, MIRROR re-caps at the write point (upstream caps
never trusted), the global serialized budget with last-success result preservation,
idempotence, and the never-raise guarantee of ``cap_sql_list``.
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.evidence.capture import (  # noqa: E402
    MAX_CELL_CHARS,
    MAX_PERSISTED_TEXT_CHARS,
    MAX_RESULT_COLS,
    MAX_RESULT_JSON_CHARS,
    MAX_RESULT_ROWS,
    MAX_SQL_ITEMS,
    cap_result,
    cap_sql_list,
    extract_result,
)


def make_big_result(n_rows=7, n_cols=50, cell_len=250):
    """A well-formed result whose serialized size is large but under the per-result cap."""
    return {
        "columns": ["col_{}".format(i + 1) for i in range(n_cols)],
        "rows": [["x" * cell_len] * n_cols for _ in range(n_rows)],
        "truncated": False,
    }


class FrozenCapsTests(unittest.TestCase):
    def test_contract_constants(self):
        # Frozen contract values (spec §1) - a silent change here must fail loudly.
        self.assertEqual(MAX_RESULT_ROWS, 200)
        self.assertEqual(MAX_RESULT_COLS, 50)
        self.assertEqual(MAX_CELL_CHARS, 256)
        self.assertEqual(MAX_RESULT_JSON_CHARS, 100_000)
        self.assertEqual(MAX_SQL_ITEMS, 20)
        self.assertEqual(MAX_PERSISTED_TEXT_CHARS, 262_144)


class ExtractListOfListsTests(unittest.TestCase):
    def test_with_explicit_columns_key(self):
        out = extract_result(
            {"columns": ["customer", "total"], "rows": [["Algerie Telecom", 1234.5]]}
        )
        self.assertEqual(
            out,
            {
                "columns": ["customer", "total"],
                "rows": [["Algerie Telecom", 1234.5]],
                "truncated": False,
            },
        )

    def test_column_names_and_headers_key_variants(self):
        self.assertEqual(
            extract_result({"rows": [[1]], "column_names": ["a"]})["columns"], ["a"]
        )
        self.assertEqual(
            extract_result({"rows": [[1]], "headers": ["h"]})["columns"], ["h"]
        )

    def test_without_columns_synthesizes_col_n_names(self):
        out = extract_result({"rows": [[1, 2], [3, 4, 5]]})
        # Width = widest row; shorter rows padded with None (not flagged truncated).
        self.assertEqual(out["columns"], ["col_1", "col_2", "col_3"])
        self.assertEqual(out["rows"], [[1, 2, None], [3, 4, 5]])
        self.assertFalse(out["truncated"])

    def test_explicit_columns_narrower_than_rows_cuts_and_flags(self):
        out = extract_result({"columns": ["a"], "rows": [[1, 2]]})
        self.assertEqual(out["columns"], ["a"])
        self.assertEqual(out["rows"], [[1]])
        self.assertTrue(out["truncated"])

    def test_column_names_stringified(self):
        out = extract_result({"columns": [1, None], "rows": [[10, 20]]})
        self.assertEqual(out["columns"], ["1", "None"])


class ExtractListOfDictsTests(unittest.TestCase):
    def test_columns_from_first_dict_in_stable_order(self):
        out = extract_result({"rows": [{"b": 2, "a": 1}, {"a": 3, "b": 4, "c": 5}]})
        # First dict's insertion order wins; later extra keys are silently projected out.
        self.assertEqual(out["columns"], ["b", "a"])
        self.assertEqual(out["rows"], [[2, 1], [4, 3]])
        self.assertFalse(out["truncated"])

    def test_missing_keys_become_none(self):
        out = extract_result({"records": [{"a": 1, "b": 2}, {"a": 3}]})
        self.assertEqual(out["rows"], [[1, 2], [3, None]])

    def test_column_cap_flags_truncated(self):
        wide = {"k{}".format(i): i for i in range(MAX_RESULT_COLS + 1)}
        out = extract_result({"rows": [wide]})
        self.assertEqual(len(out["columns"]), MAX_RESULT_COLS)
        self.assertTrue(out["truncated"])


class ExtractCandidateKeysTests(unittest.TestCase):
    def test_candidate_keys_probed_in_order(self):
        # 'rows' beats 'data' even when both are present and valid.
        out = extract_result({"data": [[1]], "rows": [[2]], "columns": ["c"]})
        self.assertEqual(out["rows"], [[2]])
        # 'records' beats 'values'.
        out = extract_result({"values": [[9]], "records": [{"a": 1}]})
        self.assertEqual(out["columns"], ["a"])

    def test_first_list_valued_candidate_wins(self):
        # A non-list value under an earlier candidate key is skipped, not fatal.
        out = extract_result({"rows": "not-a-list", "records": [[1]]})
        self.assertEqual(out["rows"], [[1]])

    def test_each_candidate_key_is_recognised(self):
        for key in ("rows", "records", "data", "result_rows", "values"):
            out = extract_result({key: [[1]]})
            self.assertEqual(out["rows"], [[1]], key)


class ExtractInvalidShapesTests(unittest.TestCase):
    def test_non_dict_outputs(self):
        for outputs in (None, "rows", [["a"]], 42):
            self.assertIsNone(extract_result(outputs), repr(outputs))

    def test_no_candidate_key(self):
        self.assertIsNone(extract_result({"sql": "SELECT 1", "success": True}))

    def test_unrecognised_row_shapes(self):
        self.assertIsNone(extract_result({"rows": [1, 2]}))          # scalars
        self.assertIsNone(extract_result({"rows": [{"a": 1}, [1]]}))  # mixed
        self.assertIsNone(extract_result({"rows": ["a", "b"]}))      # strings

    def test_empty_rows_only_captured_with_explicit_columns(self):
        out = extract_result({"rows": [], "columns": ["a", "b"]})
        self.assertEqual(out, {"columns": ["a", "b"], "rows": [], "truncated": False})
        self.assertIsNone(extract_result({"rows": []}))


class ExtractCellNormalizationTests(unittest.TestCase):
    def test_primitives_kept_as_is(self):
        out = extract_result({"rows": [[1, 2.5, True, False, None, "txt"]]})
        self.assertEqual(out["rows"], [[1, 2.5, True, False, None, "txt"]])
        # bool must survive as bool (bool is an int subclass - easy to degrade to 1/0).
        self.assertIs(out["rows"][0][2], True)

    def test_non_primitive_cells_stringified_and_capped(self):
        long_list = list(range(500))
        out = extract_result({"rows": [[{"k": 1}, long_list]]})
        self.assertEqual(out["rows"][0][0], str({"k": 1})[:MAX_CELL_CHARS])
        cell = out["rows"][0][1]
        self.assertIsInstance(cell, str)
        self.assertLessEqual(len(cell), MAX_CELL_CHARS)

    def test_non_finite_floats_stringified(self):
        out = extract_result({"rows": [[float("nan"), float("inf"), 1.0]]})
        self.assertEqual(out["rows"][0][0], "nan")
        self.assertEqual(out["rows"][0][1], "inf")
        self.assertEqual(out["rows"][0][2], 1.0)


class ExtractCapsTests(unittest.TestCase):
    def test_row_cap(self):
        out = extract_result({"rows": [[i] for i in range(MAX_RESULT_ROWS + 1)]})
        self.assertEqual(len(out["rows"]), MAX_RESULT_ROWS)
        self.assertTrue(out["truncated"])

    def test_synthesized_column_cap(self):
        out = extract_result({"rows": [list(range(MAX_RESULT_COLS + 10))]})
        self.assertEqual(len(out["columns"]), MAX_RESULT_COLS)
        self.assertEqual(len(out["rows"][0]), MAX_RESULT_COLS)
        self.assertTrue(out["truncated"])

    def test_result_json_budget_trims_rows(self):
        big = make_big_result(n_rows=10)  # ~127k chars serialized, over the 100k cap
        out = extract_result({"columns": big["columns"], "rows": big["rows"]})
        self.assertLessEqual(len(json.dumps(out)), MAX_RESULT_JSON_CHARS)
        self.assertLess(len(out["rows"]), 10)
        self.assertTrue(out["truncated"])


class CapResultTests(unittest.TestCase):
    def test_mirror_recaps_untrusted_input(self):
        # Upstream CLAIMS it capped (truncated False) but is over every bound: the
        # write-point mirror must re-cap everything regardless.
        result = {
            "columns": ["c{}".format(i) for i in range(MAX_RESULT_COLS + 5)],
            "rows": [
                list(range(MAX_RESULT_COLS + 5)) for _ in range(MAX_RESULT_ROWS + 5)
            ],
            "truncated": False,
        }
        out = cap_result(result)
        self.assertEqual(len(out["columns"]), MAX_RESULT_COLS)
        self.assertEqual(len(out["rows"]), MAX_RESULT_ROWS)
        self.assertTrue(all(len(r) == MAX_RESULT_COLS for r in out["rows"]))
        self.assertTrue(out["truncated"])

    def test_malformed_results_dropped(self):
        for bad in (
            None,
            "rows",
            {"rows": [[1]]},                      # missing columns
            {"columns": ["a"]},                    # missing rows
            {"columns": "a", "rows": [[1]]},       # columns not a list
            {"columns": ["a"], "rows": [[1], "x"]},  # one row not a list
        ):
            self.assertIsNone(cap_result(bad), repr(bad))

    def test_cells_normalized_and_rows_conformed(self):
        out = cap_result(
            {"columns": ["a", "b"], "rows": [[{"x": 1}], [1, 2, 3]], "truncated": False}
        )
        self.assertEqual(out["rows"][0], [str({"x": 1})[:MAX_CELL_CHARS], None])
        self.assertEqual(out["rows"][1], [1, 2])
        self.assertTrue(out["truncated"])  # second row was wider than the columns

    def test_budget_trim_and_idempotence(self):
        big = make_big_result(n_rows=10)
        once = cap_result(big)
        self.assertLessEqual(len(json.dumps(once)), MAX_RESULT_JSON_CHARS)
        self.assertTrue(once["truncated"])
        self.assertEqual(cap_result(once), once)

    def test_truncated_flag_preserved(self):
        out = cap_result({"columns": ["a"], "rows": [[1]], "truncated": True})
        self.assertTrue(out["truncated"])


class CapSqlListTests(unittest.TestCase):
    def test_legacy_items_without_result_pass_through(self):
        items = [
            {"sql": "SELECT 1", "success": True, "row_count": 1},
            {"sql": "SELECT 2", "success": None, "row_count": None},
        ]
        out = cap_sql_list(items)
        self.assertEqual(out, items)
        self.assertNotIn("result", out[0])

    def test_result_recapped_per_item(self):
        items = [
            {
                "sql": "SELECT *",
                "success": True,
                "row_count": 999,
                "result": {
                    "columns": ["a"],
                    "rows": [[i] for i in range(MAX_RESULT_ROWS + 50)],
                    "truncated": False,
                },
            }
        ]
        out = cap_sql_list(items)
        self.assertEqual(len(out[0]["result"]["rows"]), MAX_RESULT_ROWS)
        self.assertTrue(out[0]["result"]["truncated"])

    def test_uncappable_result_key_removed(self):
        items = [
            {"sql": "a", "success": True, "row_count": 1, "result": None},
            {"sql": "b", "success": True, "row_count": 1, "result": "bogus"},
            {"sql": "c", "success": True, "row_count": 1, "result": {"rows": [[1]]}},
        ]
        out = cap_sql_list(items)
        for item in out:
            self.assertNotIn("result", item)
        # The core keys survive the removal untouched.
        self.assertEqual(out[0]["sql"], "a")
        self.assertEqual(out[2]["row_count"], 1)

    def test_max_sql_items_drops_oldest(self):
        items = [
            {"sql": "q{}".format(i), "success": True, "row_count": i}
            for i in range(MAX_SQL_ITEMS + 5)
        ]
        out = cap_sql_list(items)
        self.assertEqual(len(out), MAX_SQL_ITEMS)
        self.assertEqual(out[0]["sql"], "q5")          # oldest five dropped
        self.assertEqual(out[-1]["sql"], "q24")        # newest kept

    def test_global_budget_drops_oldest_results_first(self):
        items = [
            {"sql": "q1", "success": False, "row_count": 1, "result": make_big_result()},
            {"sql": "q2", "success": True, "row_count": 2, "result": make_big_result()},
            {"sql": "q3", "success": False, "row_count": 3, "result": make_big_result()},
        ]
        # Premise: the list genuinely exceeds the global budget before capping.
        self.assertGreater(len(json.dumps(items)), MAX_PERSISTED_TEXT_CHARS)
        out = cap_sql_list(items)
        self.assertLessEqual(len(json.dumps(out)), MAX_PERSISTED_TEXT_CHARS)
        self.assertNotIn("result", out[0])   # oldest non-protected shed first
        self.assertIn("result", out[1])      # last successful item's result preserved
        self.assertIn("result", out[2])      # budget already met - newest untouched

    def test_last_success_result_preserved_even_when_oldest(self):
        items = [
            {"sql": "q1", "success": True, "row_count": 1, "result": make_big_result()},
            {"sql": "q2", "success": False, "row_count": 2, "result": make_big_result()},
            {"sql": "q3", "success": False, "row_count": 3, "result": make_big_result()},
        ]
        self.assertGreater(len(json.dumps(items)), MAX_PERSISTED_TEXT_CHARS)
        out = cap_sql_list(items)
        self.assertLessEqual(len(json.dumps(out)), MAX_PERSISTED_TEXT_CHARS)
        self.assertIn("result", out[0])      # protected: the only successful item
        self.assertNotIn("result", out[1])   # oldest non-protected shed instead
        self.assertIn("result", out[2])

    def test_global_budget_can_shed_several_results(self):
        items = [
            {"sql": "q{}".format(i), "success": i == 3, "row_count": i,
             "result": make_big_result()}
            for i in range(4)
        ]
        self.assertGreater(len(json.dumps(items)), MAX_PERSISTED_TEXT_CHARS)
        out = cap_sql_list(items)
        self.assertLessEqual(len(json.dumps(out)), MAX_PERSISTED_TEXT_CHARS)
        self.assertIn("result", out[3])      # last success always preserved here
        # sql/success/row_count survive on EVERY item, results or not.
        for i, item in enumerate(out):
            self.assertEqual(item["sql"], "q{}".format(i))
            self.assertIn("success", item)
            self.assertEqual(item["row_count"], i)

    def test_correlation_tags_never_removed(self):
        items = [
            {
                "sql": "q1", "success": True, "row_count": 5,
                "sql_id": "s1q1", "step_index": 1, "agent_key": "salesdrive",
                "result": make_big_result(),
            },
            {"sql": "q2", "success": True, "row_count": 6, "result": make_big_result()},
            {"sql": "q3", "success": True, "row_count": 7, "result": make_big_result()},
        ]
        self.assertGreater(len(json.dumps(items)), MAX_PERSISTED_TEXT_CHARS)
        out = cap_sql_list(items)
        self.assertNotIn("result", out[0])   # shed for the budget...
        self.assertEqual(out[0]["sql_id"], "s1q1")     # ...but tags stay intact
        self.assertEqual(out[0]["step_index"], 1)
        self.assertEqual(out[0]["agent_key"], "salesdrive")

    def test_idempotent(self):
        items = [
            {"sql": "q1", "success": False, "row_count": 1, "result": make_big_result()},
            {"sql": "q2", "success": True, "row_count": 2, "result": make_big_result()},
            {"sql": "q3", "success": True, "row_count": 3,
             "result": make_big_result(n_rows=10)},   # also needs a per-result trim
            {"sql": "legacy", "success": None, "row_count": None},
        ]
        once = cap_sql_list(items)
        self.assertEqual(cap_sql_list(once), once)

    def test_never_raises_on_garbage(self):
        self.assertEqual(cap_sql_list(None), [])
        self.assertEqual(cap_sql_list("nope"), [])
        self.assertEqual(cap_sql_list({"sql": "x"}), [])
        out = cap_sql_list(["junk", 42, {"sql": "ok", "success": True, "row_count": 0}])
        self.assertEqual(out, [{"sql": "ok", "success": True, "row_count": 0}])

    def test_never_raises_on_unserializable_extras(self):
        class Hostile(object):
            def __str__(self):
                raise RuntimeError("boom")

        items = [{"sql": "q", "success": True, "row_count": 1, "extra": Hostile()}]
        out = cap_sql_list(items)  # must not raise; fallback keeps the core keys
        self.assertEqual(out[0]["sql"], "q")
        self.assertNotIn("extra", out[0])

    def test_hostile_cells_stringified_safely(self):
        class Hostile(object):
            def __str__(self):
                raise RuntimeError("boom")

        out = extract_result({"rows": [[Hostile()]]})
        self.assertEqual(out["rows"][0][0], "<unprintable>")

    def test_output_json_round_trips(self):
        items = [
            {"sql": "q1", "success": True, "row_count": 2,
             "result": {"columns": ["a"], "rows": [[1], [None]], "truncated": False}},
            {"sql": "q2", "success": False, "row_count": None},
        ]
        out = cap_sql_list(items)
        self.assertEqual(json.loads(json.dumps(out)), out)

    def test_caller_list_never_mutated(self):
        items = [
            {"sql": "q1", "success": True, "row_count": 1,
             "result": make_big_result(n_rows=10)},
        ]
        before = json.dumps(items)
        cap_sql_list(items)
        self.assertEqual(json.dumps(items), before)


if __name__ == "__main__":
    unittest.main()


class ReviewRegressionCapsTests(unittest.TestCase):
    """Locks the adversarial-review structural caps (SQL-INST-01)."""

    def test_oversized_sql_text_is_structurally_truncated(self):
        big = "SELECT " + ("x" * 30000)
        out = cap_sql_list([{"sql": big, "success": True, "row_count": 1}])
        self.assertEqual(len(out[0]["sql"]), 20000)
        self.assertTrue(out[0]["sql_truncated"])
        # No text marker inside the SQL (structural flag only).
        self.assertNotIn("truncated", out[0]["sql"])

    def test_normal_sql_text_is_untouched(self):
        out = cap_sql_list([{"sql": "SELECT 1", "success": True, "row_count": 1}])
        self.assertEqual(out[0]["sql"], "SELECT 1")
        self.assertNotIn("sql_truncated", out[0])

    def test_oversized_correlation_tags_are_capped(self):
        out = cap_sql_list([{"sql": "SELECT 1", "success": True,
                             "row_count": 1, "agent_key": "k" * 500}])
        self.assertEqual(len(out[0]["agent_key"]), 300)

    def test_global_budget_holds_even_for_sql_texts_alone(self):
        # 20 items x 20k chars exceeds the 262_144 global budget: oldest items
        # are dropped so the serialized list always fits (the logged UPDATE
        # stays bounded - the hole the budget exists to close).
        items = [{"sql": "S" * 20000, "success": True, "row_count": i}
                 for i in range(20)]
        out = cap_sql_list(items)
        self.assertLessEqual(len(json.dumps(out, default=str)), 262_144)
        self.assertGreaterEqual(len(out), 1)
        # Newest item always survives.
        self.assertEqual(out[-1]["row_count"], 19)
