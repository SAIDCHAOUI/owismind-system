# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_evidence_whitelist.py
"""evidence.whitelist: pure (schema, table) matching against admin candidates."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.evidence.whitelist import foreign_project_tables, match_whitelist  # noqa: E402

CANDS = [
    {"name": "rev", "table": "OWI_revenue", "schema": "public"},
    {"name": "tix", "table": "OWI_tickets", "schema": None},
]


class MatchTests(unittest.TestCase):
    def test_case_insensitive_table(self):
        self.assertEqual(match_whitelist("owi_REVENUE", "public", CANDS)["name"], "rev")

    def test_missing_schema_is_wildcard_both_ways(self):
        self.assertEqual(match_whitelist("OWI_revenue", None, CANDS)["name"], "rev")
        self.assertEqual(match_whitelist("OWI_tickets", "public", CANDS)["name"], "tix")

    def test_schema_mismatch_rejected(self):
        self.assertIsNone(match_whitelist("OWI_revenue", "other", CANDS))

    def test_unknown_table_rejected(self):
        self.assertIsNone(match_whitelist("SECRET_table", "public", CANDS))
        self.assertIsNone(match_whitelist(None, None, CANDS))
        self.assertIsNone(match_whitelist("OWI_revenue", "public", []))

    def test_empty_strings(self):
        # An empty-string table is rejected like None (nothing to match).
        self.assertIsNone(match_whitelist("", "public", CANDS))
        # An empty-string parsed schema behaves like None (wildcard).
        self.assertEqual(match_whitelist("OWI_revenue", "", CANDS)["name"], "rev")
        # An empty-string CANDIDATE schema behaves as wildcard too.
        cands = [{"name": "blank", "table": "OWI_blank", "schema": ""}]
        self.assertEqual(match_whitelist("OWI_blank", "public", cands)["name"], "blank")

    def test_first_match_wins(self):
        # Two candidates sharing the same physical table: the docstring promises
        # the FIRST match - deterministic, admin-controlled ordering.
        cands = [
            {"name": "first", "table": "DUP_table", "schema": None},
            {"name": "second", "table": "DUP_table", "schema": "public"},
        ]
        self.assertEqual(match_whitelist("DUP_table", "public", cands)["name"], "first")


if __name__ == "__main__":
    unittest.main()


class ForeignProjectTests(unittest.TestCase):
    """Clone residue detection: diagnostic only, never a remap."""

    KEY = "OWISMIND_PRD_V2_0"
    CANDS = [
        {"name": "DRIVE_Revenues", "table": "OWISMIND_PRD_V2_0_drive_revenues", "schema": "public"},
        {"name": "TroubleTickets", "table": "OWISMIND_PRD_V2_0_troubletickets", "schema": None},
    ]

    def _refs(self, *tables):
        return [{"table": t, "schema": "public"} for t in tables]

    def test_other_project_key_same_dataset_is_flagged(self):
        out = foreign_project_tables(
            self._refs("OWISMIND_PRD_V1_3_DEV_drive_revenues"), self.CANDS, self.KEY)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["dataset"], "DRIVE_Revenues")
        self.assertEqual(out[0]["foreign_key"], "owismind_prd_v1_3_dev")
        self.assertEqual(out[0]["table"], "OWISMIND_PRD_V1_3_DEV_drive_revenues")

    def test_case_insensitive(self):
        out = foreign_project_tables(self._refs("owismind_prd_v1_2_DRIVE_REVENUES"), self.CANDS, self.KEY)
        self.assertEqual([f["dataset"] for f in out], ["DRIVE_Revenues"])

    def test_same_project_key_is_never_flagged(self):
        # Exact-match territory (match_whitelist), not a residue.
        self.assertEqual(foreign_project_tables(
            self._refs("OWISMIND_PRD_V2_0_drive_revenues"), self.CANDS, self.KEY), [])

    def test_unknown_suffix_is_not_flagged(self):
        self.assertEqual(foreign_project_tables(
            self._refs("OWISMIND_PRD_V1_2_secret_table", "no_underscore_match"), self.CANDS, self.KEY), [])

    def test_blank_key_or_no_candidates(self):
        refs = self._refs("OWISMIND_PRD_V1_2_drive_revenues")
        self.assertEqual(foreign_project_tables(refs, self.CANDS, ""), [])
        self.assertEqual(foreign_project_tables(refs, self.CANDS, None), [])
        self.assertEqual(foreign_project_tables(refs, [], self.KEY), [])
        self.assertEqual(foreign_project_tables([], self.CANDS, self.KEY), [])

    def test_malformed_refs_never_raise(self):
        self.assertEqual(foreign_project_tables([None, {}, {"table": None}], self.CANDS, self.KEY), [])

    def test_mixed_tables_reports_only_foreign_ones(self):
        out = foreign_project_tables(
            self._refs("OWISMIND_PRD_V2_0_drive_revenues", "OWISMIND_PRD_V1_2_troubletickets"),
            self.CANDS, self.KEY)
        self.assertEqual([f["dataset"] for f in out], ["TroubleTickets"])
