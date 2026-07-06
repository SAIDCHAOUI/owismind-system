# Plugin/owismind/tests/test_sql_config.py
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
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
    """Minimal import-time stubs (NO install). Extends any sibling stub, never replaces."""
    dk = sys.modules.get("dataiku")
    if dk is None:
        dk = types.ModuleType("dataiku")
        sys.modules["dataiku"] = dk
    if not hasattr(dk, "SQLExecutor2"):
        dk.SQLExecutor2 = type("SQLExecutor2", (), {})
    if not hasattr(dk, "default_project_key"):
        dk.default_project_key = lambda: "OWISMIND_DEV"
    sql_mod = sys.modules.get("dataiku.sql")
    if sql_mod is None:
        sql_mod = types.ModuleType("dataiku.sql")
        sys.modules["dataiku.sql"] = sql_mod
    if not hasattr(sql_mod, "Constant"):
        sql_mod.Constant = lambda value: value
    if not hasattr(sql_mod, "toSQL"):
        sql_mod.toSQL = lambda constant, dialect=None: repr(constant)
    if not hasattr(sql_mod, "Dialects"):
        sql_mod.Dialects = type("Dialects", (), {"POSTGRES": "postgres"})
    dk.sql = sql_mod
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.ModuleType("pandas")


_ensure_dataiku_stub()

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


if __name__ == "__main__":
    unittest.main()
