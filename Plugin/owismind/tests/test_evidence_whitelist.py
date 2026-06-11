# Plugin/owismind/tests/test_evidence_whitelist.py
"""evidence.whitelist: pure (schema, table) matching against admin candidates."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.evidence.whitelist import match_whitelist  # noqa: E402

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
        # the FIRST match — deterministic, admin-controlled ordering.
        cands = [
            {"name": "first", "table": "DUP_table", "schema": None},
            {"name": "second", "table": "DUP_table", "schema": "public"},
        ]
        self.assertEqual(match_whitelist("DUP_table", "public", cands)["name"], "first")


if __name__ == "__main__":
    unittest.main()
