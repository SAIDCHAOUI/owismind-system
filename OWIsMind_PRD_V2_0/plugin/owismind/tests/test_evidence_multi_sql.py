"""V2.0 multi-SQL Evidence: an optional ``sql_id`` selects WHICH query of an exchange
the Evidence routes describe (chips, source rows, distinct, aggregate, explainer,
result rows).

  - service: ``_load_sql_item`` resolves the UNIQUE item carrying the sql_id, owner
    scoped; an unknown or ambiguous id is a 404 ``sql_id_not_found`` (never the
    latest SQL); without sql_id the legacy active-item rule is unchanged;
  - ``_context`` refuses an explicitly selected FAILED query (no_successful_sql);
  - ``evidence_meta`` propagates the 404, and its degraded shape now lists every
    query (``queries`` + ``sql_id``) so the client can switch;
  - ``summarize_queries`` adds ``sql_id`` + ``active`` (only when an active index
    is given: the legacy shape is unchanged);
  - ``evidence_result_rows`` with an unknown explicit sql_id -> 404;
  - routes: ``sql_id`` from the query string (or the POST body), 400 on a malformed
    id, forwarded to the service; /evidence/meta attaches the widgets bound to each
    query (workspace first, legacy artifacts otherwise).
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

from owismind.evidence import service  # noqa: E402
from owismind.evidence.query_builders import EvidenceError  # noqa: E402

ITEMS = [
    {"sql": "SELECT 1", "success": True, "row_count": 3, "sql_id": "s1q1",
     "step_index": 1, "agent_key": "revenue_expert",
     "result": {"columns": ["a"], "rows": [[1]]}},
    {"sql": "SELECT 2", "success": False, "row_count": None, "sql_id": "s1q2"},
    {"sql": "SELECT 3", "success": True, "row_count": 7, "sql_id": "s2q1",
     "step_index": 2, "agent_key": "tickets_expert"},
    {"sql": "SELECT 4", "success": True, "sql_id": "dup"},
    {"sql": "SELECT 5", "success": True, "sql_id": "dup"},
]


class _ServiceBase(unittest.TestCase):
    def setUp(self):
        self._orig = {k: getattr(service, k) for k in
                      ("new_executor", "rows_to_json_safe", "full_table")}
        self.queries = []
        test = self

        class _Exec(object):
            def query_to_df(self, sql, **_k):
                test.queries.append(sql)
                return "df"

        service.new_executor = lambda: _Exec()
        service.full_table = lambda logical: 'public."T"'
        self.rows = [{"generated_sql": json.dumps(ITEMS)}]
        service.rows_to_json_safe = lambda df: self.rows

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(service, k, v)


class LoadSqlItemTests(_ServiceBase):
    def test_legacy_active_item_unchanged(self):
        item, items, idx = service._load_sql_item("u", "e")
        self.assertEqual(idx, 0)            # last successful WITH a captured result
        self.assertEqual(len(items), 5)

    def test_explicit_sql_id_selects_that_item(self):
        item, _items, idx = service._load_sql_item("u", "e", "s2q1")
        self.assertEqual((item["sql"], idx), ("SELECT 3", 2))
        self.assertIn("user_id = 'u'", self.queries[0])   # owner-scoped read

    def test_unknown_or_ambiguous_sql_id_is_404(self):
        for bad in ("s9q9", "dup"):
            with self.assertRaises(EvidenceError) as ctx:
                service._load_sql_item("u", "e", bad)
            self.assertEqual((ctx.exception.code, ctx.exception.status),
                             ("sql_id_not_found", 404))

    def test_sql_id_on_exchange_without_sql_is_404(self):
        self.rows = [{"generated_sql": None}]
        with self.assertRaises(EvidenceError) as ctx:
            service._load_sql_item("u", "e", "s1q1")
        self.assertEqual(ctx.exception.status, 404)

    def test_foreign_exchange_still_404(self):
        self.rows = []
        with self.assertRaises(EvidenceError) as ctx:
            service._load_sql_item("u", "e", "s1q1")
        self.assertEqual(ctx.exception.code, "exchange_not_found")

    def test_explicit_failed_query_refused_by_context(self):
        with self.assertRaises(EvidenceError) as ctx:
            service._context("u", "e", sql_id="s1q2")
        self.assertEqual(ctx.exception.code, "no_successful_sql")


class MetaTests(_ServiceBase):
    def test_unknown_sql_id_propagates_404(self):
        with self.assertRaises(EvidenceError) as ctx:
            service.evidence_meta("u", "e", "s9q9")
        self.assertEqual(ctx.exception.status, 404)

    def test_degraded_meta_lists_queries(self):
        out = service.evidence_meta("u", "e", "s1q2")   # failed query -> degraded
        self.assertFalse(out["available"])
        self.assertEqual(out["reason"], "no_successful_sql")
        self.assertEqual(out["sql"], "SELECT 2")
        self.assertEqual(out["sql_id"], "s1q2")
        self.assertEqual([q.get("sql_id") for q in out["queries"]],
                         ["s1q1", "s1q2", "s2q1", "dup", "dup"])
        self.assertEqual([q["active"] for q in out["queries"]],
                         [False, True, False, False, False])

    def test_summarize_queries_active_and_sql_id(self):
        out = service.summarize_queries(ITEMS[:3], [True, False, True], 2)
        self.assertEqual(out[2]["sql_id"], "s2q1")
        self.assertTrue(out[2]["active"])
        self.assertFalse(out[0]["active"])
        self.assertNotIn("active", service.summarize_queries(ITEMS[:1], [True])[0])


class ResultRowsTests(_ServiceBase):
    def test_unknown_explicit_sql_id_is_404(self):
        with self.assertRaises(EvidenceError) as ctx:
            service.evidence_result_rows("u", "e", "s9q9", 50, 0)
        self.assertEqual((ctx.exception.code, ctx.exception.status),
                         ("sql_id_not_found", 404))


class _Req(object):
    def __init__(self, args=None, body=None):
        self.headers, self.args, self.method = {}, args or {}, "GET"
        self._body = body

    def get_json(self, silent=False):
        return self._body


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global routes
        _dss_stub.install_flask()
        from owismind.api import routes as _routes
        routes = _routes

    def setUp(self):
        from owismind.evidence import throttle
        from owismind.security import impersonation
        from owismind.storage import sql_config
        self._mods = (throttle, impersonation, sql_config)
        self.calls = {}
        self.workspace = None
        self._orig = {
            "request": routes.request, "jsonify": routes.jsonify,
            "resolve_identity": routes.resolve_identity,
            "ensure_chat_table": routes.ensure_chat_table,
            "evidence_service": routes.evidence_service,
            "artifacts_storage": routes.artifacts_storage,
            "workspaces_storage": routes.workspaces_storage,
            "can_accept": throttle.can_accept,
            "effective_identity": impersonation.effective_identity,
            "is_configured": sql_config.is_configured,
        }
        routes.jsonify = lambda payload: payload
        routes.resolve_identity = lambda headers: {"user_id": "u.one", "groups": []}
        routes.ensure_chat_table = lambda: None
        throttle.can_accept = lambda uid: True
        impersonation.effective_identity = lambda ident: dict(ident, impersonating=False)
        sql_config.is_configured = lambda: True
        test = self

        class _Service(object):
            EvidenceError = EvidenceError

            @staticmethod
            def evidence_meta(user_id, exchange_id, sql_id=None):
                test.calls["meta"] = (user_id, exchange_id, sql_id)
                if sql_id == "s9q9":
                    raise EvidenceError("sql_id_not_found", 404)
                return {"available": True, "sql_id": sql_id or "s2q1", "result": None,
                        "queries": [{"index": 1, "sql_id": "s1q1"},
                                    {"index": 2, "sql_id": "s2q1"},
                                    {"index": 3}]}

            @staticmethod
            def evidence_rows(*args, **kwargs):
                test.calls["rows"] = kwargs.get("sql_id")
                return {"rows": [], "has_more": False, "offset": 0}

        class _Arts(object):
            @staticmethod
            def read_artifacts(user_id, exchange_id):
                return [{"kind": "table", "title": "Legacy", "sql_id": "s1q1"}]

        class _Ws(object):
            @staticmethod
            def read_workspace(user_id, exchange_id):
                return test.workspace

        routes.evidence_service = _Service
        routes.artifacts_storage = _Arts
        routes.workspaces_storage = _Ws

    def tearDown(self):
        throttle, impersonation, sql_config = self._mods
        for k in ("request", "jsonify", "resolve_identity", "ensure_chat_table",
                  "evidence_service", "artifacts_storage", "workspaces_storage"):
            setattr(routes, k, self._orig[k])
        throttle.can_accept = self._orig["can_accept"]
        impersonation.effective_identity = self._orig["effective_identity"]
        sql_config.is_configured = self._orig["is_configured"]

    def _meta(self, args):
        routes.request = _Req(args)
        return routes.evidence_meta()

    def test_meta_without_sql_id_unchanged_call(self):
        body = self._meta({"exchange_id": "e1"})
        self.assertEqual(self.calls["meta"], ("u.one", "e1", None))
        self.assertEqual(body["status"], "ok")

    def test_meta_forwards_sql_id_and_404(self):
        self._meta({"exchange_id": "e1", "sql_id": "s1q1"})
        self.assertEqual(self.calls["meta"][2], "s1q1")
        body, status = self._meta({"exchange_id": "e1", "sql_id": "s9q9"})
        self.assertEqual((status, body["error"]), (404, "sql_id_not_found"))

    def test_meta_rejects_malformed_sql_id(self):
        body, status = self._meta({"exchange_id": "e1", "sql_id": "latest"})
        self.assertEqual((status, body["error"]), (400, "invalid_sql_id"))
        self.assertNotIn("meta", self.calls)

    def test_widgets_from_workspace_first(self):
        self.workspace = {"widgets": [
            {"id": "w1", "kind": "chart", "title": "CA", "sql_id": "s2q1"},
            {"id": "w2", "kind": "text", "title": "Synthese"}]}
        body = self._meta({"exchange_id": "e1"})
        widgets = {q["index"]: q["widgets"] for q in body["queries"]}
        self.assertEqual(widgets[2], [{"id": "w1", "kind": "chart", "title": "CA",
                                       "source": "workspace"}])
        self.assertEqual(widgets[1], [])     # legacy artifact ignored: workspace wins
        self.assertEqual(widgets[3], [])

    def test_widgets_fall_back_to_legacy_artifacts(self):
        body = self._meta({"exchange_id": "e1"})
        self.assertEqual(body["queries"][0]["widgets"],
                         [{"id": "a1", "kind": "table", "title": "Legacy",
                           "source": "artifact"}])

    def test_rows_take_sql_id_from_query_or_body(self):
        base = {"exchange_id": "e1"}
        routes.request = _Req({"sql_id": "s2q1"}, dict(base))
        routes.evidence_rows()
        self.assertEqual(self.calls["rows"], "s2q1")
        routes.request = _Req({}, dict(base, sql_id="s1lk2"))
        routes.evidence_rows()
        self.assertEqual(self.calls["rows"], "s1lk2")
        routes.request = _Req({}, dict(base))
        routes.evidence_rows()
        self.assertIsNone(self.calls["rows"])


routes = None

if __name__ == "__main__":
    unittest.main()
