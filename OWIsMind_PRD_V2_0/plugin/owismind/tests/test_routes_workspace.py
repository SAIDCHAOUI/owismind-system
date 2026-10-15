"""GET /workspace + ``has_workspace`` on /conversation (route handlers called directly).

  - /workspace: 400 on a bad exchange_id; 404 ``workspace_not_found`` when the
    owner-scoped read finds nothing (unknown, someone else's, or no workspace); the
    reads are made with the CALLER's user_id; the response joins the stored state
    with the captured SQL by sql_id (sql, filters, result, Chart.js / KPI payloads),
    an orphan widget gets an honest ``{ok: false, reason: orphan}``, a duplicated
    sql_id is never resolved, nothing is re-run;
  - /conversation: each row carries ``has_workspace`` from ONE owner-scoped lookup.
The flask + dataiku stubs of tests/_dss_stub.py make routes importable.
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

from owismind.workspace import resolve  # noqa: E402

FIXTURES = os.path.join(_HERE, "..", "contracts", "fixtures")
routes = None


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def _captured_items(fixture):
    """The generated_sql items a run persisted (as chat_v5 stores them)."""
    items = []
    for chunk in fixture["raw_chunks"]:
        if chunk.get("eventKind") == "AGENT_DONE":
            items.extend(chunk["eventData"]["generatedSql"])
    return items


class _Req(object):
    def __init__(self, args):
        self.headers = {}
        self.args = args
        self.method = "GET"

    def get_json(self, silent=False):
        return None


class _RouteBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Deferred import (see test_chat_screen_ctx): keeps the sibling route tests'
        # request binding intact in the full suite.
        global routes
        _dss_stub.install_flask()
        from owismind.api import routes as _routes
        routes = _routes

    def setUp(self):
        from owismind.evidence import throttle
        from owismind.security import impersonation
        from owismind.storage import sql_config
        self.calls = {"read": [], "items": [], "ids": []}
        self.state = None
        self.items = []
        self._mods = (throttle, impersonation, sql_config)
        self._orig = {
            "request": routes.request,
            "jsonify": routes.jsonify,
            "resolve_identity": routes.resolve_identity,
            "ensure_chat_table": routes.ensure_chat_table,
            "workspaces_storage": routes.workspaces_storage,
            "messages_for_session": routes.chat_v5.messages_for_session,
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

        class _Storage(object):
            @staticmethod
            def read_workspace(user_id, exchange_id):
                test.calls["read"].append((user_id, exchange_id))
                return test.state

            @staticmethod
            def read_exchange_sql_items(user_id, exchange_id):
                test.calls["items"].append((user_id, exchange_id))
                return test.items

            @staticmethod
            def workspace_exchange_ids(user_id, ids):
                test.calls["ids"].append((user_id, list(ids)))
                return {"e2"}

        routes.workspaces_storage = _Storage

    def tearDown(self):
        throttle, impersonation, sql_config = self._mods
        routes.request = self._orig["request"]
        routes.jsonify = self._orig["jsonify"]
        routes.resolve_identity = self._orig["resolve_identity"]
        routes.ensure_chat_table = self._orig["ensure_chat_table"]
        routes.workspaces_storage = self._orig["workspaces_storage"]
        routes.chat_v5.messages_for_session = self._orig["messages_for_session"]
        throttle.can_accept = self._orig["can_accept"]
        impersonation.effective_identity = self._orig["effective_identity"]
        sql_config.is_configured = self._orig["is_configured"]

    def _get(self, args):
        routes.request = _Req(args)
        return routes.workspace()


class WorkspaceRouteTests(_RouteBase):
    def test_invalid_exchange_id(self):
        body, status = self._get({})
        self.assertEqual((status, body["error"]), (400, "invalid_exchange_id"))
        body, status = self._get({"exchange_id": "x" * 500})
        self.assertEqual(status, 400)
        self.assertEqual(self.calls["read"], [])

    def test_not_found_is_404_and_owner_scoped(self):
        body, status = self._get({"exchange_id": "ex-someone-else"})
        self.assertEqual((status, body["error"]), (404, "workspace_not_found"))
        self.assertEqual(self.calls["read"], [("u.one", "ex-someone-else")])
        self.assertEqual(self.calls["items"], [])

    def test_multi_facet_resolution(self):
        fx = _load("workspace_run_multi_facet.json")
        self.state = _load(fx["expected_reduced"])["final"]
        self.items = _captured_items(fx)
        body = self._get({"exchange_id": fx["exchange_id"]})
        self.assertEqual(body["status"], "ok")
        self.assertIsNone(body["events"])
        self.assertEqual(body["workspace"], self.state)
        self.assertEqual(self.calls["items"], [("u.one", fx["exchange_id"])])
        self.assertEqual(sorted(body["resolved"]), ["s1q1", "s1q2", "s2q1"])
        s1 = body["resolved"]["s1q1"]
        self.assertTrue(s1["sql"].startswith("SELECT region"))
        self.assertEqual(s1["result"]["rows"][0], ["Nord", 1200])
        self.assertTrue(s1["result"]["captured"])
        self.assertEqual(s1["agent_key"], "revenue")
        self.assertIn({"kind": "filter_eq", "params": ["status", "open"]},
                      body["resolved"]["s2q1"]["filters"])
        data = body["widgets_data"]
        self.assertEqual(data["w1"]["labels"], ["Nord", "Sud", "Ouest"])
        self.assertEqual(data["w1"]["datasets"][0]["data"], [1200, 950, 700])
        self.assertEqual(data["w2"]["value"], 2850)
        self.assertEqual(data["w3"], {"ok": True})
        # Donut = pie payload (one slice per row).
        self.assertTrue(data["w4"]["ok"])
        self.assertEqual(data["w4"]["datasets"][0]["data"], [41, 30, 16])
        self.assertNotIn("w5", data)   # text widget: no data payload

    def test_orphan_widgets_get_honest_empty_payload(self):
        fx = _load("workspace_run_orphan_widget.json")
        self.state = _load(fx["expected_reduced"])["final"]
        self.items = _captured_items(fx)
        body = self._get({"exchange_id": fx["exchange_id"]})
        self.assertTrue(body["widgets_data"]["w1"]["ok"])
        self.assertEqual(body["widgets_data"]["w2"], {"ok": False, "reason": "orphan"})
        self.assertEqual(body["widgets_data"]["w3"], {"ok": False, "reason": "orphan"})
        self.assertEqual(sorted(body["resolved"]), ["s1q1"])


class ResolveRulesTests(unittest.TestCase):
    def test_duplicated_sql_id_is_never_resolved(self):
        state = _load("reduced/workspace_run_stopped.json")["final"]
        items = [{"sql": "SELECT 1", "sql_id": "s1q1"}, {"sql": "SELECT 2", "sql_id": "s1q1"}]
        resolved, data = resolve.build_resolution(state, items)
        self.assertEqual(resolved, {})
        self.assertEqual(data["w1"], {"ok": False, "reason": "no_data"})

    def test_garbage_never_raises(self):
        self.assertEqual(resolve.build_resolution(None, None), ({}, {}))
        self.assertEqual(resolve.build_resolution({"widgets": "x"}, [1, None]), ({}, {}))


class ConversationHasWorkspaceTests(_RouteBase):
    def test_rows_flagged_from_one_lookup(self):
        routes.chat_v5.messages_for_session = lambda uid, sid: [
            {"exchange_id": "e1"}, {"exchange_id": "e2"}]
        routes.request = _Req({"session_id": "sess-1"})
        body = routes.conversation()
        self.assertEqual([r["has_workspace"] for r in body["rows"]], [False, True])
        self.assertEqual(self.calls["ids"], [("u.one", ["e1", "e2"])])


if __name__ == "__main__":
    unittest.main()
