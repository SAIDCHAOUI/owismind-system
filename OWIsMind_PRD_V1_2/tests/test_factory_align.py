"""DSS-free unit tests for owismind_factory.align (the clone aligner).

Only the PURE remap/scan helpers are covered here: the DSS-touching scan()/align()
need a live project. The pure functions (remap_dataset_ref, remap_sql,
find_foreign_keys, remap_raw) carry all the boundary-safety logic, so they are the
ones that must never corrupt a semantic-model config.

Run from the repo root:
    python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests -v
"""

import os
import sys
import unittest

_PKG_PARENT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "project-library", "python"))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

from owismind_factory import align   # noqa: E402

OLD = "OWISMIND_DEV"
NEW = "OWISMIND_PRD_V1_2"


class TestRemapSql(unittest.TestCase):
    def test_quoted_table_literal_replaced(self):
        self.assertEqual(
            align.remap_sql('SELECT * FROM "OWISMIND_DEV_drive_revenues"', OLD, NEW),
            'SELECT * FROM "OWISMIND_PRD_V1_2_drive_revenues"')

    def test_unquoted_table_literal_replaced(self):
        self.assertEqual(align.remap_sql("FROM OWISMIND_DEV_drive_revenues x", OLD, NEW),
                         "FROM OWISMIND_PRD_V1_2_drive_revenues x")

    def test_qualified_ref_replaced(self):
        self.assertEqual(align.remap_sql("OWISMIND_DEV.DRIVE_Revenues", OLD, NEW),
                         "OWISMIND_PRD_V1_2.DRIVE_Revenues")

    def test_substring_boundary_not_corrupted(self):
        # A larger identifier that merely CONTAINS the old key must be left alone.
        self.assertEqual(align.remap_sql("XOWISMIND_DEV_foo", OLD, NEW),
                         "XOWISMIND_DEV_foo")
        self.assertEqual(align.remap_sql("MY_OWISMIND_DEV_foo", OLD, NEW),
                         "MY_OWISMIND_DEV_foo")

    def test_bare_key_without_separator_untouched(self):
        # Only the "<KEY>." / "<KEY>_" prefixes are project references.
        self.assertEqual(align.remap_sql("mention OWISMIND_DEV please", OLD, NEW),
                         "mention OWISMIND_DEV please")

    def test_current_key_stays_when_it_is_the_target(self):
        # Remapping an already-aligned literal is a no-op (old == new prefix text).
        self.assertEqual(align.remap_sql('"OWISMIND_PRD_V1_2_x"', NEW, NEW),
                         '"OWISMIND_PRD_V1_2_x"')

    def test_non_string_passthrough(self):
        self.assertIsNone(align.remap_sql(None, OLD, NEW))
        self.assertEqual(align.remap_sql(12, OLD, NEW), 12)


class TestRemapDatasetRef(unittest.TestCase):
    def test_prefix_swapped(self):
        self.assertEqual(align.remap_dataset_ref("OWISMIND_DEV.DRIVE_Revenues", OLD, NEW),
                         "OWISMIND_PRD_V1_2.DRIVE_Revenues")

    def test_other_key_untouched(self):
        self.assertEqual(align.remap_dataset_ref("OTHER_PROJ.Dataset", OLD, NEW),
                         "OTHER_PROJ.Dataset")

    def test_no_dot_untouched(self):
        self.assertEqual(align.remap_dataset_ref("LocalDataset", OLD, NEW), "LocalDataset")


class TestFindForeignKeys(unittest.TestCase):
    RAW = {
        "name": "TroubleTickets_Semantic_Model",
        "entities": [
            {"name": "ticket", "datasetRef": "OWISMIND_DEV.TroubleTickets_year",
             "attributes": [{"column": "id"}]},
        ],
        "goldenQueries": [
            {"question": "how many",
             "generatedSql": 'SELECT count(*) FROM "OWISMIND_DEV_troubletickets_year"'},
        ],
    }

    def test_detects_foreign_key_from_ref_and_sql(self):
        self.assertEqual(align.find_foreign_keys(self.RAW, NEW), ["OWISMIND_DEV"])

    def test_current_key_not_flagged(self):
        raw = {"entities": [{"datasetRef": "%s.X" % NEW}],
               "goldenQueries": [{"generatedSql": 'FROM "%s_x"' % NEW}]}
        self.assertEqual(align.find_foreign_keys(raw, NEW), [])

    def test_empty_when_no_refs(self):
        self.assertEqual(align.find_foreign_keys({"a": 1, "b": "free text"}, NEW), [])

    def test_ordinary_alias_not_mistaken_for_key(self):
        # An "Alias_column"-style literal (single uppercase segment) is not a
        # project prefix, so the SQL scan must not flag it.
        raw = {"goldenQueries": [{"generatedSql": "SELECT Alias_column FROM t"}]}
        self.assertEqual(align.find_foreign_keys(raw, NEW), [])


class TestRemapRaw(unittest.TestCase):
    def test_deep_remap_ref_and_sql(self):
        raw = {
            "entities": [{"datasetRef": "OWISMIND_DEV.DRIVE_Revenues"}],
            "goldenQueries": [{"generatedSql": 'FROM "OWISMIND_DEV_drive_revenues"'}],
            "sqlGenerationConfig": {"instructions": "query OWISMIND_DEV_drive_revenues"},
        }
        out = align.remap_raw(raw, ["OWISMIND_DEV"], NEW)
        self.assertEqual(out["entities"][0]["datasetRef"],
                         "OWISMIND_PRD_V1_2.DRIVE_Revenues")
        self.assertIn("OWISMIND_PRD_V1_2_drive_revenues",
                      out["goldenQueries"][0]["generatedSql"])
        self.assertIn("OWISMIND_PRD_V1_2_drive_revenues",
                      out["sqlGenerationConfig"]["instructions"])

    def test_input_not_mutated(self):
        raw = {"entities": [{"datasetRef": "OWISMIND_DEV.DRIVE_Revenues"}]}
        align.remap_raw(raw, ["OWISMIND_DEV"], NEW)
        self.assertEqual(raw["entities"][0]["datasetRef"], "OWISMIND_DEV.DRIVE_Revenues")

    def test_skips_when_old_equals_new(self):
        raw = {"entities": [{"datasetRef": "%s.X" % NEW}]}
        out = align.remap_raw(raw, [NEW], NEW)
        self.assertEqual(out["entities"][0]["datasetRef"], "%s.X" % NEW)


if __name__ == "__main__":
    unittest.main()
