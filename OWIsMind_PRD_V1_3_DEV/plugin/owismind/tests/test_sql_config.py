# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_sql_config.py
"""storage.sql_config pure helpers - the shared read-only pre-query builder.

``readonly_pre_queries`` is the single source of truth for the transaction-scoped
pre-queries every dataset READ runs under (Evidence, Source Data, artifacts, settings,
budget, suggestions, the LAB benchmark reader). This proves the exact contract those
sites depend on: the two SET LOCAL strings in order, and a FRESH list per call so a
caller mutating one result can never corrupt the shared definition.

A minimal dataiku stub lets sql_config import (it wants dataiku at top level); the
helper under test never touches the DB.
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
sys.path.insert(0, _HERE)

import _dss_stub  # noqa: E402


_dss_stub.install()

from owismind.storage import sql_config  # noqa: E402

_EXPECTED = [
    "SET LOCAL statement_timeout TO '30000'",
    "SET LOCAL transaction_read_only TO on",
]


class ReadonlyPreQueriesTest(unittest.TestCase):
    def test_returns_exact_strings_in_order(self):
        self.assertEqual(sql_config.readonly_pre_queries(), _EXPECTED)

    def test_returns_a_fresh_list_each_call(self):
        a = sql_config.readonly_pre_queries()
        b = sql_config.readonly_pre_queries()
        # Equal contents but distinct objects, so mutating one leaves the other (and any
        # module-level constant built from it) intact.
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a.append("SET LOCAL statement_timeout TO '1'")
        self.assertEqual(sql_config.readonly_pre_queries(), _EXPECTED)


class TestPgIdentifier(unittest.TestCase):
    """The identifier gate's two raise paths were never executed by the suite
    (audit 2026-08-05, TS-08): every caller passed valid names. These lock the
    refusal contract of a SECURITY primitive (rule #3: identifiers only ever
    come from controlled constants, and a bad one must fail loudly)."""

    def test_valid_identifier_is_double_quoted(self):
        self.assertEqual(sql_config.pg_identifier("Account_name"),
                         '"Account_name"')

    def test_invalid_characters_are_refused(self):
        for bad in ('a"b', "a;b", "a b", "a'b", "", "1leading", "a\\b"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                sql_config.pg_identifier(bad)

    def test_identifier_longer_than_63_bytes_is_refused(self):
        with self.assertRaises(ValueError):
            sql_config.pg_identifier("a" * 64)
        # 63 bytes exactly still passes (the cap is the PostgreSQL limit).
        self.assertEqual(sql_config.pg_identifier("a" * 63),
                         '"' + "a" * 63 + '"')


if __name__ == "__main__":
    unittest.main()
