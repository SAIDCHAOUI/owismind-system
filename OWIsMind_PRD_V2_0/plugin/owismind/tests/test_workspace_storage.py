"""storage.workspaces + the webapp_workspaces_v1 DDL (fake executor, no database).

  - DDL: CREATE TABLE IF NOT EXISTS only (no ALTER / DROP), registered in the managed
    inventory, exact column set of the V2 spec;
  - save_workspace: one owner-guarded UPSERT under statement_timeout + COMMIT, values
    escaped, skipped when empty / oversize, never raises;
  - read_workspace: owner-scoped PK read, read-only pre-queries, sanitized, None on
    any failure;
  - workspace_exchange_ids: one bounded owner-scoped IN lookup, empty set on failure;
  - read_exchange_sql_items: owner-scoped chat_v5 read, [] on failure.
The shared dataiku stub (tests/_dss_stub.py) lets the modules import.
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
sys.path.insert(0, _HERE)

import _dss_stub  # noqa: E402

_dss_stub.install()

from owismind.storage import migrations, sql_config, workspaces  # noqa: E402

FIXTURES = os.path.join(_HERE, "..", "contracts", "fixtures")


def _final_state():
    with open(os.path.join(FIXTURES, "reduced", "workspace_run_multi_facet.json"),
              encoding="utf-8") as f:
        return json.load(f)["final"]


class _Col(object):
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return list(self._values)


class _Row(dict):
    pass


class _FakeDF(object):
    """Just enough of a DataFrame: len(), .iloc[0][col], df[col].tolist()."""

    def __init__(self, rows):
        self._rows = rows
        self.iloc = self

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, key):
        if isinstance(key, int):
            return _Row(self._rows[key])
        return _Col([r.get(key) for r in self._rows])


class _FakeExec(object):
    def __init__(self, sink, rows=None, boom=False):
        self.sink, self.rows, self.boom = sink, rows or [], boom

    def query_to_df(self, sql, pre_queries=None, post_queries=None):
        self.sink.append({"sql": sql, "pre": list(pre_queries or []),
                          "post": list(post_queries or [])})
        if self.boom:
            raise RuntimeError("db down")
        return _FakeDF(self.rows)


class _Base(unittest.TestCase):
    rows = None
    boom = False

    def setUp(self):
        self.calls = []
        self._orig = {
            "new_executor": workspaces.new_executor,
            "full_table": workspaces.full_table,
            "ensure": workspaces.ensure_workspaces_table,
        }
        workspaces.new_executor = lambda: _FakeExec(self.calls, self.rows, self.boom)
        workspaces.full_table = lambda logical: 'public."T_%s"' % logical
        workspaces.ensure_workspaces_table = lambda: None

    def tearDown(self):
        workspaces.new_executor = self._orig["new_executor"]
        workspaces.full_table = self._orig["full_table"]
        workspaces.ensure_workspaces_table = self._orig["ensure"]


class DDLTests(unittest.TestCase):
    def test_table_registered_and_inventoried(self):
        self.assertIn(migrations.WORKSPACES_V1_LOGICAL, migrations._DDL_BY_LOGICAL)
        roles = {r["logical"]: r["role"] for r in migrations.managed_tables()}
        self.assertEqual(roles["webapp_workspaces_v1"], "workspaces")

    def test_ddl_is_create_if_not_exists_only(self):
        ddl = migrations._WORKSPACES_V1_DDL
        self.assertIn("CREATE TABLE IF NOT EXISTS", ddl)
        for banned in ("ALTER", "DROP", "TRUNCATE", "DELETE"):
            self.assertNotIn(banned, ddl.upper())
        for col in ("exchange_id       TEXT      PRIMARY KEY", "user_id", "session_id",
                    "protocol_version  SMALLINT  NOT NULL DEFAULT 1", "status",
                    "workspace", "created_at"):
            self.assertIn(col, ddl)

    def test_storage_status_lists_physical_name(self):
        self.assertTrue(sql_config.storage_status()["tables"]["workspaces"]
                        .endswith("webapp_workspaces_v1"))


class SaveTests(_Base):
    def test_upsert_owner_guarded_with_timeout_and_commit(self):
        ok = workspaces.save_workspace("ex-1", "u.one", "sess-1", _final_state())
        self.assertTrue(ok)
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call["post"], ["COMMIT"])
        self.assertIn("statement_timeout", call["pre"][0])
        upsert = call["pre"][1]
        self.assertIn('INSERT INTO public."T_webapp_workspaces_v1" AS ws', upsert)
        self.assertIn("ON CONFLICT (exchange_id) DO UPDATE", upsert)
        self.assertIn("WHERE ws.user_id = EXCLUDED.user_id", upsert)
        self.assertIn("'ex-1'", upsert)
        self.assertIn("'u.one'", upsert)
        self.assertIn("'sess-1'", upsert)
        self.assertIn("'done'", upsert)
        # Apostrophes from the document are escaped (doubled), never raw.
        self.assertIn("Chiffre d''affaires", upsert)

    def test_null_session(self):
        workspaces.save_workspace("ex-1", "u.one", None, _final_state())
        self.assertIn("'u.one', NULL, 1,", self.calls[0]["pre"][1])

    def test_empty_state_not_written(self):
        from owismind.workspace import reducer
        self.assertFalse(workspaces.save_workspace("ex-1", "u", "s", reducer.empty_state()))
        self.assertFalse(workspaces.save_workspace("ex-1", "u", "s", {"junk": 1}))
        self.assertEqual(self.calls, [])

    def test_oversize_document_skipped(self):
        original = workspaces.MAX_WORKSPACE_JSON_CHARS
        workspaces.MAX_WORKSPACE_JSON_CHARS = 500
        try:
            self.assertFalse(workspaces.save_workspace("ex-1", "u", "s", _final_state()))
        finally:
            workspaces.MAX_WORKSPACE_JSON_CHARS = original
        self.assertEqual(self.calls, [])


class SaveFailureTests(_Base):
    boom = True

    def test_db_failure_swallowed(self):
        self.assertFalse(workspaces.save_workspace("ex-1", "u", "s", _final_state()))

    def test_reads_degrade(self):
        self.assertIsNone(workspaces.read_workspace("u", "ex-1"))
        self.assertEqual(workspaces.workspace_exchange_ids("u", ["ex-1"]), set())
        self.assertEqual(workspaces.read_exchange_sql_items("u", "ex-1"), [])


class ReadTests(_Base):
    def test_owner_scoped_read_only_and_sanitized(self):
        doc = _final_state()
        doc["junk"] = "x"
        self.rows = [{"workspace": json.dumps(doc)}]
        out = workspaces.read_workspace("u.one", "ex-1")
        self.assertEqual(out, _final_state())
        call = self.calls[0]
        self.assertIn("exchange_id = 'ex-1' AND user_id = 'u.one'", call["sql"])
        self.assertIn("SET LOCAL transaction_read_only TO on", call["pre"])
        self.assertEqual(call["post"], [])

    def test_missing_row_and_bad_json(self):
        self.assertIsNone(workspaces.read_workspace("u", "ex-1"))
        self.rows = [{"workspace": "{not json"}]
        self.assertIsNone(workspaces.read_workspace("u", "ex-1"))

    def test_exchange_ids_lookup(self):
        self.rows = [{"exchange_id": "e2"}]
        out = workspaces.workspace_exchange_ids("u.one", ["e1", "e2", "e2", None, 5])
        self.assertEqual(out, {"e2"})
        sql = self.calls[0]["sql"]
        self.assertIn("user_id = 'u.one' AND exchange_id IN ('e1', 'e2')", sql)
        self.assertIn("SET LOCAL transaction_read_only TO on", self.calls[0]["pre"])

    def test_exchange_ids_lookup_bounded_and_skipped_when_empty(self):
        self.assertEqual(workspaces.workspace_exchange_ids("u", []), set())
        self.assertEqual(self.calls, [])
        workspaces.workspace_exchange_ids("u", ["e%d" % i for i in range(900)])
        self.assertEqual(self.calls[0]["sql"].count("'e"), workspaces.MAX_LOOKUP_IDS)

    def test_exchange_sql_items(self):
        items = [{"sql": "SELECT 1", "sql_id": "s1q1"}, {"no": "sql"}]
        self.rows = [{"generated_sql": json.dumps(items)}]
        self.assertEqual(workspaces.read_exchange_sql_items("u.one", "ex-1"), items[:1])
        self.assertIn("user_id = 'u.one'", self.calls[0]["sql"])
        self.assertIn("SET LOCAL transaction_read_only TO on", self.calls[0]["pre"])



class ContinuityReadTests(_Base):
    def test_meta_returns_doc_and_session(self):
        self.rows = [{"workspace": json.dumps(_final_state()), "session_id": "sess-1"}]
        doc, session = workspaces.read_workspace_meta("u.one", "ex-1")
        self.assertEqual((doc, session), (_final_state(), "sess-1"))
        call = self.calls[0]
        self.assertIn("exchange_id = 'ex-1' AND user_id = 'u.one'", call["sql"])
        self.assertIn("SET LOCAL transaction_read_only TO on", call["pre"])

    def test_meta_degrades(self):
        self.assertEqual(workspaces.read_workspace_meta("u", "ex-1"), (None, None))
        self.assertEqual(workspaces.read_workspace_meta("u", "bad id'; --"), (None, None))
        self.assertEqual(len(self.calls), 1)            # a forged id never queries
        self.rows = [{"workspace": "{bad", "session_id": "s"}]
        self.assertEqual(workspaces.read_workspace_meta("u", "ex-1"), (None, None))

    def test_origin_reads_bounded_and_owner_scoped(self):
        ids = ["ex-%d" % i for i in range(30)] + ["bad id", "ex-1"]
        self.rows = [{"exchange_id": "ex-1", "workspace": json.dumps(_final_state()),
                      "generated_sql": json.dumps([{"sql": "SELECT 1", "sql_id": "s1q1"},
                                                   {"no": "sql"}])},
                     {"exchange_id": "ex-99", "workspace": json.dumps(_final_state()),
                      "generated_sql": "[]"}]
        prov = workspaces.read_workspaces("u.one", ids)
        self.assertEqual(sorted(prov), ["ex-1"])          # unrequested id ignored
        self.assertEqual(prov["ex-1"], _final_state()["provenance"])
        items = workspaces.read_exchanges_sql_items("u.one", ids)
        self.assertEqual(items, {"ex-1": [{"sql": "SELECT 1", "sql_id": "s1q1"}]})
        for call in self.calls:
            self.assertIn("user_id = 'u.one' AND exchange_id IN (", call["sql"])
            self.assertEqual(call["sql"].count("'ex-"), workspaces.MAX_ORIGIN_IDS)
            self.assertNotIn("bad id", call["sql"])
            self.assertIn("SET LOCAL transaction_read_only TO on", call["pre"])
            self.assertEqual(call["post"], [])

    def test_origin_reads_skip_empty_and_degrade(self):
        self.assertEqual(workspaces.read_workspaces("u", []), {})
        self.assertEqual(workspaces.read_exchanges_sql_items("u", [None]), {})
        self.assertEqual(self.calls, [])
        self.boom = True
        self.assertEqual(workspaces.read_workspaces("u", ["ex-1"]), {})
        self.assertEqual(workspaces.read_exchanges_sql_items("u", ["ex-1"]), {})

if __name__ == "__main__":
    unittest.main()
