# Plugin/owismind/tests/test_suggestions_storage.py
"""storage.suggestions - PURE helpers + the parametrized INSERT shape, no live DSS runtime.

A minimal dataiku stub lets the module import (sql_config wants dataiku at top level); the
executor is captured to assert the write is a single parametrized INSERT with COMMIT, and that
the nullable boolean verdict is inlined as a bare SQL keyword (true/false/NULL), never quoted.
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
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
        # Quote strings like a real escaper would; keep it simple for assertions.
        sql_mod.toSQL = lambda constant, dialect=None: (
            "'" + str(constant).replace("'", "''") + "'" if isinstance(constant, str) else repr(constant)
        )
    if not hasattr(sql_mod, "Dialects"):
        sql_mod.Dialects = type("Dialects", (), {"POSTGRES": "postgres"})
    dk.sql = sql_mod
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.ModuleType("pandas")


_ensure_dataiku_stub()

from owismind.storage import suggestions  # noqa: E402
from owismind.storage import sql_config  # noqa: E402


class SafeIndexNameTests(unittest.TestCase):
    """The new length-safe index naming (regression: a long project key + prefix overflowed
    NAMEDATALEN and made pg_identifier RAISE, aborting the whole table creation)."""

    def test_short_name_is_readable(self):
        out = sql_config.safe_index_name("OWISMIND_DEV_owismind_webapp_golden_suggestions_v1", "uc_idx")
        self.assertEqual(out, '"OWISMIND_DEV_owismind_webapp_golden_suggestions_v1_uc_idx"')

    def test_overlong_name_falls_back_to_hash_and_fits(self):
        physical = "OWISMIND_PROD_V1_bidule-owismind_webapp_golden_suggestions_v1"
        out = sql_config.safe_index_name(physical, "uc_idx")
        # Hashed fallback, never raises, and the unquoted identifier fits NAMEDATALEN.
        self.assertTrue(out.startswith('"idx_uc_idx_'))
        self.assertLessEqual(len(out.strip('"').encode("utf-8")), 63)


class _FakeExecutor:
    """Records the pre/post queries instead of touching a database."""

    last = None

    def query_to_df(self, sql, pre_queries=None, post_queries=None):
        _FakeExecutor.last = {
            "sql": sql,
            "pre_queries": list(pre_queries or []),
            "post_queries": list(post_queries or []),
        }
        return None


class HelperTests(unittest.TestCase):
    def test_cap_trims_and_bounds(self):
        self.assertEqual(suggestions._cap("  hi  ", 10), "hi")
        self.assertEqual(suggestions._cap("abcdef", 3), "abc")
        self.assertIsNone(suggestions._cap("   ", 5))
        self.assertIsNone(suggestions._cap(None, 5))

    def test_enum(self):
        self.assertEqual(suggestions._enum("CURRENCY", suggestions._EXPECTED_VALUE_TYPES), "currency")
        self.assertIsNone(suggestions._enum("money", suggestions._EXPECTED_VALUE_TYPES))
        self.assertIsNone(suggestions._enum(123, suggestions._EXPECTED_VALUE_TYPES))

    def test_nullable_bool_literal(self):
        self.assertEqual(suggestions._nullable_bool_literal(None), "NULL")
        self.assertEqual(suggestions._nullable_bool_literal(True), "true")
        self.assertEqual(suggestions._nullable_bool_literal(False), "false")


class SaveSuggestionTests(unittest.TestCase):
    def setUp(self):
        _FakeExecutor.last = None
        self._orig_exec = suggestions.new_executor
        self._orig_ensure = suggestions.ensure_golden_suggestions_table
        suggestions.new_executor = lambda: _FakeExecutor()
        suggestions.ensure_golden_suggestions_table = lambda: None

    def tearDown(self):
        suggestions.new_executor = self._orig_exec
        suggestions.ensure_golden_suggestions_table = self._orig_ensure

    def test_manual_insert_shape(self):
        sid = suggestions.save_suggestion(
            "user.a", "manual", "What is the revenue?", "12345 EUR",
            expected_value="12345", expected_value_type="currency",
            category="revenus", language="en",
        )
        self.assertTrue(sid and isinstance(sid, str))
        rec = _FakeExecutor.last
        self.assertIsNotNone(rec)
        # The write is INSERT ... 'pending' ... now(), in pre_queries, with a COMMIT.
        insert = rec["pre_queries"][-1]
        self.assertIn("INSERT INTO", insert)
        self.assertIn("'pending'", insert)
        self.assertIn("now()", insert)
        self.assertIn("COMMIT", rec["post_queries"])
        # A manual suggestion has no verdict -> NULL bare keyword (not quoted).
        self.assertIn("NULL", insert)
        # The user id was escaped (quoted), not inlined raw.
        self.assertIn("'user.a'", insert)

    def test_chat_verdict_is_bare_keyword(self):
        suggestions.save_suggestion(
            "user.b", "chat", "Q", "agent answer",
            exchange_id="ex1", agent_key="ag_x", agent_answer="agent answer",
            answer_is_correct=True,
        )
        insert = _FakeExecutor.last["pre_queries"][-1]
        # True verdict -> bare lowercase 'true' keyword, never the repr 'True' (which would
        # mean it went through the value escaper instead of the boolean literal helper).
        self.assertIn("true", insert)
        self.assertNotIn("True", insert)

    def test_unknown_source_falls_back_manual(self):
        suggestions.save_suggestion("u", "weird", "Q", "R")
        insert = _FakeExecutor.last["pre_queries"][-1]
        self.assertIn("'manual'", insert)


if __name__ == "__main__":
    unittest.main()
