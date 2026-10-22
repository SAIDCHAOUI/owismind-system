"""GET /workspace + ``has_workspace`` on /conversation (route handlers called directly).

  - /workspace: 400 on a bad exchange_id; 404 ``workspace_not_found`` when the
    owner-scoped read finds nothing (unknown, someone else's, or no workspace); the
    reads are made with the CALLER's user_id; the response joins the stored state
    with the captured SQL by sql_id (sql, filters, result, Chart.js / KPI payloads),
    an orphan widget gets an honest ``{ok: false, reason: orphan}``, a duplicated
    sql_id is never resolved, nothing is re-run;
  - /conversation: each row carries ``has_workspace`` (plan or widgets: a Studio) and
    its stored ``suggestions`` from ONE owner-scoped lookup;
  - Studio continuity: carried widgets (``origin``) resolve against their ORIGIN
    exchange (``origins`` block, owner-scoped reads only when such widgets exist),
    never against this exchange's same-named sql_id; a missing / foreign origin is
    ``orphan``; /evidence/meta query widgets skip carried widgets.
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
        self.calls = {"read": [], "items": [], "ids": [], "origin_items": [],
                      "origin_ws": []}
        self.state = None
        self.items = []
        self.origin_items = {}
        self.origin_prov = {}
        self.flags = {"e2": {"studio": True, "suggestions": []}}
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
            def read_exchanges_sql_items(user_id, ids):
                test.calls["origin_items"].append((user_id, list(ids)))
                return {k: v for k, v in test.origin_items.items() if k in ids}

            @staticmethod
            def read_workspaces(user_id, ids):
                test.calls["origin_ws"].append((user_id, list(ids)))
                return {k: v for k, v in test.origin_prov.items() if k in ids}

            @staticmethod
            def workspace_flags(user_id, ids):
                test.calls["ids"].append((user_id, list(ids)))
                return {k: v for k, v in test.flags.items() if k in ids}

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


_CHART = {"type": "bar", "x": "region", "y": ["revenue"]}


def _carried_state():
    """A continued Studio: two carried widgets (one origin read, one missing) on
    top of this run's own chart, all three bound to the SAME sql_id s1q1."""
    return {
        "v": 1, "status": "done", "exchange_id": "ex-new", "base_exchange_id": "ex-base",
        "plan": None, "notes": [], "provenance": {"s1q1": {
            "agent_key": "revenue", "tool": "semantic-model-query", "success": True}},
        "widgets": [
            {"id": "w1", "kind": "chart", "title": "Base", "sql_id": "s1q1",
             "chart": _CHART, "binding": "explicit", "origin": "ex-base"},
            {"id": "w2", "kind": "kpi", "title": "Gone", "sql_id": "s1q1",
             "kpi": {"label": "CA", "value": "revenue"}, "binding": "explicit",
             "origin": "ex-gone"},
            {"id": "w3", "kind": "chart", "title": "New", "sql_id": "s1q1",
             "chart": _CHART, "binding": "explicit"},
        ],
        "summary": {"widget_ids_by_step": {}, "sql_ids": ["s1q1"]},
    }


def _item(rows):
    return {"sql": "SELECT region, revenue FROM t", "success": True, "sql_id": "s1q1",
            "row_count": len(rows),
            "result": {"columns": ["region", "revenue"], "rows": rows, "truncated": False}}


class CarriedWidgetRouteTests(_RouteBase):
    def test_carried_widgets_resolve_against_their_origin(self):
        self.state = _carried_state()
        self.items = [_item([["Nord", 10]])]
        self.origin_items = {"ex-base": [_item([["Est", 7], ["Ouest", 3]])]}
        self.origin_prov = {"ex-base": {
            "s1q1": {"agent_key": "revenue", "tool": "semantic-model-query",
                     "success": True, "task": "CA 2025"},
            "s9q9": {"agent_key": "x", "tool": "semantic-model-query", "success": True}}}
        body = self._get({"exchange_id": "ex-new"})
        data = body["widgets_data"]
        self.assertEqual(data["w3"]["labels"], ["Nord"])           # this exchange
        self.assertEqual(data["w1"]["labels"], ["Est", "Ouest"])   # its origin
        self.assertEqual(data["w2"], {"ok": False, "reason": "orphan"})
        self.assertEqual(body["resolved"]["s1q1"]["result"]["rows"], [["Nord", 10]])
        self.assertEqual(sorted(body["origins"]), ["ex-base"])
        origin = body["origins"]["ex-base"]
        self.assertEqual(origin["resolved"]["s1q1"]["result"]["rows"][0], ["Est", 7])
        self.assertEqual(sorted(origin["provenance"]), ["s1q1"])
        # Owner-scoped origin reads, with the caller's user id, bounded ids.
        self.assertEqual(self.calls["origin_items"], [("u.one", ["ex-base", "ex-gone"])])
        self.assertEqual(self.calls["origin_ws"], [("u.one", ["ex-base", "ex-gone"])])

    def test_no_carried_widget_no_origin_read(self):
        fx = _load("workspace_run_multi_facet.json")
        self.state = _load(fx["expected_reduced"])["final"]
        self.items = _captured_items(fx)
        body = self._get({"exchange_id": fx["exchange_id"]})
        self.assertEqual(body["origins"], {})
        self.assertEqual(self.calls["origin_items"], [])
        self.assertEqual(self.calls["origin_ws"], [])

    def test_query_widgets_skip_carried(self):
        self.state = _carried_state()
        meta = {"queries": [{"sql_id": "s1q1"}]}
        routes._attach_query_widgets(meta, "u.one", "ex-new", [])
        self.assertEqual([w["id"] for w in meta["queries"][0]["widgets"]], ["w3"])


class ResolveRulesTests(unittest.TestCase):
    def test_carried_widget_without_origin_data_is_orphan(self):
        resolved, data = resolve.build_resolution(_carried_state(), [_item([["N", 1]])])
        self.assertEqual(data["w1"], {"ok": False, "reason": "orphan"})
        self.assertEqual(data["w2"], {"ok": False, "reason": "orphan"})
        self.assertNotEqual(data["w3"].get("reason"), "orphan")   # own SQL, no block fn
        self.assertEqual(sorted(resolved), ["s1q1"])

    def test_origin_ids_bounded_and_unique(self):
        state = {"widgets": [{"id": "w%d" % i, "origin": "ex-%d" % (i % 20)}
                             for i in range(40)] + [{"id": "x"}, "junk"]}
        ids = resolve.origin_exchange_ids(state)
        self.assertEqual(len(ids), 12)
        self.assertEqual(len(set(ids)), 12)
        self.assertEqual(resolve.resolve_workspace(None, None), ({}, {}, {}))

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
        self.assertNotIn("suggestions", body["rows"][1])

    def test_suggestions_only_doc_is_no_studio_but_replays_its_chips(self):
        self.flags = {"e1": {"studio": False, "suggestions": ["Voir la suite par pays"]},
                      "e2": {"studio": True, "suggestions": ["Comparer au budget 2026"]}}
        routes.chat_v5.messages_for_session = lambda uid, sid: [
            {"exchange_id": "e1"}, {"exchange_id": "e2"}, {"exchange_id": "e3"}]
        routes.request = _Req({"session_id": "sess-1"})
        rows = routes.conversation()["rows"]
        self.assertEqual([r["has_workspace"] for r in rows], [False, True, False])
        self.assertEqual([r.get("suggestions") for r in rows],
                         [["Voir la suite par pays"], ["Comparer au budget 2026"], None])
        self.assertEqual(len(self.calls["ids"]), 1)                # one lookup, not N


if __name__ == "__main__":
    unittest.main()
