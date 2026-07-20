# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_feedback_hub_storage.py
"""storage.feedback - PURE helpers + the parametrized INSERT shape, no live DSS runtime.

Feedback Hub (v1.3), general feedback tab: mirrors test_suggestions_storage.py. A minimal
dataiku stub lets the module import (sql_config wants dataiku at top level); the executor
is captured to assert the write is a single parametrized INSERT with COMMIT, and that an
unknown category degrades to 'other' rather than being rejected.
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

from owismind.storage import feedback  # noqa: E402


class HelperTests(unittest.TestCase):
    def test_cap_trims_and_bounds(self):
        self.assertEqual(feedback._cap("  hi  ", 10), "hi")
        self.assertEqual(feedback._cap("abcdef", 3), "abc")
        self.assertIsNone(feedback._cap("   ", 5))
        self.assertIsNone(feedback._cap(None, 5))

    def test_category_known_value_lowercased(self):
        self.assertEqual(feedback._category("BUG"), "bug")
        self.assertEqual(feedback._category("routing"), "routing")

    def test_category_unknown_falls_back_to_other(self):
        self.assertEqual(feedback._category("not_a_category"), "other")
        self.assertEqual(feedback._category(None), "other")
        self.assertEqual(feedback._category(123), "other")

    def test_category_closed_set(self):
        self.assertEqual(
            set(feedback._CATEGORIES),
            {"bug", "wrong", "feature", "ux", "perf", "data", "routing", "other"},
        )


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


class SaveFeedbackTests(unittest.TestCase):
    def setUp(self):
        _FakeExecutor.last = None
        self._orig_exec = feedback.new_executor
        self._orig_ensure = feedback.ensure_feedback_table
        feedback.new_executor = lambda: _FakeExecutor()
        feedback.ensure_feedback_table = lambda: None

    def tearDown(self):
        feedback.new_executor = self._orig_exec
        feedback.ensure_feedback_table = self._orig_ensure

    def test_insert_shape(self):
        fid = feedback.save_feedback("user.a", "bug", "It crashed", linked_session_id="s1")
        self.assertTrue(fid and isinstance(fid, str))
        rec = _FakeExecutor.last
        self.assertIsNotNone(rec)
        insert = rec["pre_queries"][-1]
        self.assertIn("INSERT INTO", insert)
        self.assertIn("'open'", insert)
        self.assertIn("now()", insert)
        self.assertIn("COMMIT", rec["post_queries"])
        # Values are escaped (quoted), never inlined raw.
        self.assertIn("'user.a'", insert)
        self.assertIn("'bug'", insert)
        self.assertIn("'It crashed'", insert)
        self.assertIn("'s1'", insert)

    def test_unknown_category_falls_back_to_other(self):
        feedback.save_feedback("user.b", "not_real", "hello")
        insert = _FakeExecutor.last["pre_queries"][-1]
        self.assertIn("'other'", insert)

    def test_no_linked_session_id_is_null(self):
        feedback.save_feedback("user.c", "ux", "message body")
        insert = _FakeExecutor.last["pre_queries"][-1]
        # NULL is a bare keyword, not a quoted string, right before the trailing 'open'.
        self.assertIn("NULL", insert)

    def test_message_is_capped(self):
        long_message = "x" * (feedback.MAX_MESSAGE_CHARS + 500)
        feedback.save_feedback("user.d", "perf", long_message)
        insert = _FakeExecutor.last["pre_queries"][-1]
        self.assertNotIn("x" * (feedback.MAX_MESSAGE_CHARS + 1), insert)

    def test_write_uses_statement_timeout(self):
        feedback.save_feedback("user.e", "data", "hi")
        rec = _FakeExecutor.last
        self.assertEqual(rec["pre_queries"][0], feedback._WRITE_TIMEOUT_PRE_QUERY)


class ListMyFeedbackTests(unittest.TestCase):
    def setUp(self):
        self._orig_exec = feedback.new_executor
        self._orig_ensure = feedback.ensure_feedback_table

    def tearDown(self):
        feedback.new_executor = self._orig_exec
        feedback.ensure_feedback_table = self._orig_ensure

    def test_never_raises_on_storage_error(self):
        feedback.ensure_feedback_table = lambda: None

        def _boom():
            raise RuntimeError("db down")

        feedback.new_executor = _boom
        rows = feedback.list_my_feedback("user.a")
        self.assertEqual(rows, [])

    def test_read_is_owner_scoped_and_read_only(self):
        feedback.ensure_feedback_table = lambda: None
        seen = {}

        class _Exec:
            def query_to_df(self, sql, pre_queries=None, post_queries=None):
                seen["sql"] = sql
                seen["pre_queries"] = list(pre_queries or [])
                return None

        feedback.new_executor = lambda: _Exec()
        feedback.list_my_feedback("user.a", limit=10)
        self.assertIn("'user.a'", seen["sql"])
        self.assertIn("LIMIT 10", seen["sql"])
        self.assertEqual(seen["pre_queries"], feedback._READ_PRE_QUERIES)

    def test_limit_is_clamped(self):
        feedback.ensure_feedback_table = lambda: None
        seen = {}

        class _Exec:
            def query_to_df(self, sql, pre_queries=None, post_queries=None):
                seen["sql"] = sql
                return None

        feedback.new_executor = lambda: _Exec()
        feedback.list_my_feedback("user.a", limit=99999)
        self.assertIn("LIMIT {}".format(feedback.MAX_MY_LIMIT), seen["sql"])


if __name__ == "__main__":
    unittest.main()
