# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_agent_requests_storage.py
"""storage.agent_requests - PURE helpers + the parametrized INSERT/SELECT shape, no live
DSS runtime. Feedback Hub (v1.3), "Demander un agent" tab: mirrors test_suggestions_storage.py.
A minimal dataiku stub lets the module import (sql_config wants dataiku at top level); the
executor is captured to assert the write is a single parametrized INSERT with COMMIT, the
``datasets`` list is bounded + JSON-serialized, and the read re-parses ``datasets_json``
back into a list.
"""
import json
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
        sql_mod.toSQL = lambda constant, dialect=None: (
            "'" + str(constant).replace("'", "''") + "'" if isinstance(constant, str) else repr(constant)
        )
    if not hasattr(sql_mod, "Dialects"):
        sql_mod.Dialects = type("Dialects", (), {"POSTGRES": "postgres"})
    dk.sql = sql_mod
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.ModuleType("pandas")


_ensure_dataiku_stub()

from owismind.storage import agent_requests  # noqa: E402


class HelperTests(unittest.TestCase):
    def test_cap_trims_and_bounds(self):
        self.assertEqual(agent_requests._cap("  hi  ", 10), "hi")
        self.assertIsNone(agent_requests._cap("   ", 5))
        self.assertIsNone(agent_requests._cap(None, 5))

    def test_cap_dataset_entry_requires_dataset_name(self):
        self.assertIsNone(agent_requests._cap_dataset_entry({"table": "t", "connection": "c"}))
        self.assertIsNone(agent_requests._cap_dataset_entry("not a dict"))
        self.assertIsNone(agent_requests._cap_dataset_entry(None))

    def test_cap_dataset_entry_shape(self):
        out = agent_requests._cap_dataset_entry(
            {"dataset": "DS1", "table": "t1", "connection": "SQL_owi", "extra": "ignored"}
        )
        self.assertEqual(out, {"dataset": "DS1", "table": "t1", "connection": "SQL_owi"})

    def test_serialize_datasets_empty_or_bad_input(self):
        self.assertIsNone(agent_requests._serialize_datasets(None))
        self.assertIsNone(agent_requests._serialize_datasets([]))
        self.assertIsNone(agent_requests._serialize_datasets("not a list"))
        self.assertIsNone(agent_requests._serialize_datasets([{"table": "t"}]))  # no dataset name

    def test_serialize_datasets_bounded_count(self):
        many = [{"dataset": "ds{}".format(i)} for i in range(agent_requests.MAX_DATASETS + 20)]
        blob = agent_requests._serialize_datasets(many)
        decoded = json.loads(blob)
        self.assertEqual(len(decoded), agent_requests.MAX_DATASETS)

    def test_serialize_datasets_valid_shape(self):
        blob = agent_requests._serialize_datasets(
            [{"dataset": "DS1", "table": "t1", "connection": "SQL_owi"}]
        )
        decoded = json.loads(blob)
        self.assertEqual(decoded, [{"dataset": "DS1", "table": "t1", "connection": "SQL_owi"}])


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


class SaveAgentRequestTests(unittest.TestCase):
    def setUp(self):
        _FakeExecutor.last = None
        self._orig_exec = agent_requests.new_executor
        self._orig_ensure = agent_requests.ensure_agent_requests_table
        agent_requests.new_executor = lambda: _FakeExecutor()
        agent_requests.ensure_agent_requests_table = lambda: None

    def tearDown(self):
        agent_requests.new_executor = self._orig_exec
        agent_requests.ensure_agent_requests_table = self._orig_ensure

    def test_insert_shape(self):
        rid = agent_requests.save_agent_request(
            "user.a", "PROJ_KEY", "My Project",
            [{"dataset": "DS1", "table": "t1", "connection": "SQL_owi"}],
            "We need revenue insights", "daily reporting", "high",
        )
        self.assertTrue(rid and isinstance(rid, str))
        rec = _FakeExecutor.last
        self.assertIsNotNone(rec)
        insert = rec["pre_queries"][-1]
        self.assertIn("INSERT INTO", insert)
        self.assertIn("'open'", insert)
        self.assertIn("now()", insert)
        self.assertIn("COMMIT", rec["post_queries"])
        self.assertIn("'user.a'", insert)
        self.assertIn("'PROJ_KEY'", insert)
        self.assertIn("'My Project'", insert)
        self.assertIn("'We need revenue insights'", insert)
        # The serialized datasets JSON is inlined (escaped), not a raw f-string.
        self.assertIn("DS1", insert)

    def test_no_datasets_is_null(self):
        agent_requests.save_agent_request(
            "user.b", "PROJ", "Label", None, "business case text", None, None,
        )
        insert = _FakeExecutor.last["pre_queries"][-1]
        self.assertIn("NULL", insert)

    def test_write_uses_statement_timeout(self):
        agent_requests.save_agent_request("user.c", "P", "L", [], "case", "", "")
        rec = _FakeExecutor.last
        self.assertEqual(rec["pre_queries"][0], agent_requests._WRITE_TIMEOUT_PRE_QUERY)


class ListMyAgentRequestsTests(unittest.TestCase):
    def setUp(self):
        self._orig_exec = agent_requests.new_executor
        self._orig_ensure = agent_requests.ensure_agent_requests_table

    def tearDown(self):
        agent_requests.new_executor = self._orig_exec
        agent_requests.ensure_agent_requests_table = self._orig_ensure

    def test_never_raises_on_storage_error(self):
        agent_requests.ensure_agent_requests_table = lambda: None

        def _boom():
            raise RuntimeError("db down")

        agent_requests.new_executor = _boom
        rows = agent_requests.list_my_agent_requests("user.a")
        self.assertEqual(rows, [])

    def test_read_is_owner_scoped_and_read_only(self):
        agent_requests.ensure_agent_requests_table = lambda: None
        seen = {}

        class _Exec:
            def query_to_df(self, sql, pre_queries=None, post_queries=None):
                seen["sql"] = sql
                seen["pre_queries"] = list(pre_queries or [])
                return None

        agent_requests.new_executor = lambda: _Exec()
        agent_requests.list_my_agent_requests("user.a", limit=10)
        self.assertIn("'user.a'", seen["sql"])
        self.assertIn("LIMIT 10", seen["sql"])
        self.assertEqual(seen["pre_queries"], agent_requests._READ_PRE_QUERIES)

    def test_datasets_json_reparsed_into_list(self):
        agent_requests.ensure_agent_requests_table = lambda: None

        class _FakeDf:
            empty = False

            def copy(self):
                return self

            def select_dtypes(self, include=None):
                return types.SimpleNamespace(columns=[])

            def notna(self):
                return self

            def astype(self, _t):
                return self

            def where(self, *_a, **_k):
                return self

            def to_dict(self, orient=None):
                return [{
                    "request_id": "r1",
                    "datasets_json": json.dumps([{"dataset": "DS1", "table": "t1", "connection": "c1"}]),
                }]

        class _Exec:
            def query_to_df(self, sql, pre_queries=None, post_queries=None):
                return _FakeDf()

        agent_requests.new_executor = lambda: _Exec()
        rows = agent_requests.list_my_agent_requests("user.a")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("datasets_json", rows[0])
        self.assertEqual(
            rows[0]["datasets"], [{"dataset": "DS1", "table": "t1", "connection": "c1"}]
        )

    def test_malformed_datasets_json_degrades_to_empty_list(self):
        agent_requests.ensure_agent_requests_table = lambda: None

        class _FakeDf:
            empty = False

            def copy(self):
                return self

            def select_dtypes(self, include=None):
                return types.SimpleNamespace(columns=[])

            def notna(self):
                return self

            def astype(self, _t):
                return self

            def where(self, *_a, **_k):
                return self

            def to_dict(self, orient=None):
                return [{"request_id": "r1", "datasets_json": "not valid json"}]

        class _Exec:
            def query_to_df(self, sql, pre_queries=None, post_queries=None):
                return _FakeDf()

        agent_requests.new_executor = lambda: _Exec()
        rows = agent_requests.list_my_agent_requests("user.a")
        self.assertEqual(rows[0]["datasets"], [])


if __name__ == "__main__":
    unittest.main()
