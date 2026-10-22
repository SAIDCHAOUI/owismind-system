"""workspace.reducer - pure state machine pinned by the SHARED fixtures.

The same JSON fixtures drive the frontend reducer tests (workspaceModel.js), so a
green run here and there means one semantics for live and restored workspaces:
  - run fixtures: expected_events folded -> reduced.live; finalize -> reduced.final;
  - edge-case fixture: replay / caps / duplicates / plan replacement / add_step;
  - finalize binds orphans; sanitize round-trips a stored document and rejects junk;
  - apply never mutates its input.
"""
import copy
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.workspace import reducer  # noqa: E402

FIXTURES = os.path.join(_HERE, "..", "contracts", "fixtures")
RUNS = ("workspace_run_multi_facet", "workspace_run_stopped", "workspace_run_orphan_widget")


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


class RunFixtureTests(unittest.TestCase):
    def test_live_and_final_states(self):
        for name in RUNS:
            fx = _load(name + ".json")
            expected = _load(fx["expected_reduced"])
            with self.subTest(fixture=name):
                live = reducer.reduce_events(fx["expected_events"])
                self.assertEqual(live, expected["live"])
                final = reducer.finalize(live, fx["terminal_status"], fx["exchange_id"],
                                         fx["known_sql_ids"])
                self.assertEqual(final, expected["final"])

    def test_final_states_survive_storage_round_trip(self):
        for name in RUNS:
            final = _load(_load(name + ".json")["expected_reduced"])["final"]
            with self.subTest(fixture=name):
                self.assertEqual(reducer.sanitize(json.loads(json.dumps(final))), final)

    def test_multi_facet_shape(self):
        final = _load("reduced/workspace_run_multi_facet.json")["final"]
        self.assertEqual(len(final["plan"]["steps"]), 3)
        self.assertEqual(len(final["notes"]), 4)
        self.assertEqual(sorted(w["kind"] for w in final["widgets"]),
                         ["chart", "chart", "kpi", "table", "text"])
        self.assertEqual(sorted(final["provenance"]), ["s1q1", "s1q2", "s2q1"])

    def test_orphan_binding_only_at_finalize(self):
        live = _load("reduced/workspace_run_orphan_widget.json")["live"]
        self.assertTrue(all(w["binding"] == "explicit" for w in live["widgets"]))
        final = reducer.finalize(live, "done", "x", ["s1q1"])
        self.assertEqual([w["binding"] for w in final["widgets"]],
                         ["explicit", "orphan", "orphan"])
        # Without known ids, bindings are left as they are.
        self.assertEqual(reducer.finalize(live, "done")["widgets"], live["widgets"])

    def test_text_widget_never_bound(self):
        final = _load("reduced/workspace_run_multi_facet.json")["final"]
        text = [w for w in final["widgets"] if w["kind"] == "text"][0]
        self.assertNotIn("binding", reducer.finalize(final, "done", "x", [])["widgets"][4])
        self.assertNotIn("binding", text)


class EdgeCaseFixtureTests(unittest.TestCase):
    def test_shared_edge_cases(self):
        for case in _load("workspace_reducer_edge_cases.json")["cases"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(reducer.reduce_events(case["events"]), case["expected"])


class PurityTests(unittest.TestCase):
    def test_apply_does_not_mutate_input(self):
        events = _load("workspace_run_multi_facet.json")["expected_events"]
        state = reducer.reduce_events(events[:5])
        snapshot = copy.deepcopy(state)
        reducer.apply(state, events[5])
        reducer.finalize(state, "done", "x", [])
        self.assertEqual(state, snapshot)

    def test_is_empty(self):
        self.assertTrue(reducer.is_empty(reducer.empty_state()))
        self.assertTrue(reducer.is_empty(None))
        events = _load("workspace_run_stopped.json")["expected_events"]
        self.assertFalse(reducer.is_empty(reducer.reduce_events(events[:1])))

    def test_finalize_ignores_unknown_status(self):
        state = reducer.finalize(reducer.empty_state(), "exploded")
        self.assertEqual(state["status"], "running")


class SanitizeTests(unittest.TestCase):
    def test_rejects_non_v1(self):
        for junk in (None, [], "x", {"v": 2}, {"v": True}, {}):
            self.assertIsNone(reducer.sanitize(junk))

    def test_reprojects_tampered_document(self):
        final = _load("reduced/workspace_run_multi_facet.json")["final"]
        doc = json.loads(json.dumps(final))
        doc["status"] = "hacked"
        doc["evil"] = "<script>"
        doc["widgets"][0]["chart"]["type"] = "scatter"      # invalid chart -> widget dropped
        doc["widgets"][1]["binding"] = "weird"                # invalid binding -> explicit
        doc["notes"][0]["text"] = "x" * 9999                  # re-capped
        doc["notes"].append({"id": "BAD ID", "kind": "note", "title": "t"})
        doc["provenance"]["latest"] = {"agent_key": "a", "tool": "semantic-model-query",
                                       "success": True}       # bad sql_id key -> dropped
        doc["plan"]["steps"][0]["status"] = "exploded"        # -> todo
        out = reducer.sanitize(doc)
        self.assertEqual(out["status"], "error")
        self.assertNotIn("evil", out)
        self.assertEqual([w["id"] for w in out["widgets"]], ["w2", "w3", "w4", "w5"])
        self.assertEqual(out["widgets"][0]["binding"], "explicit")
        self.assertEqual(len(out["notes"][0]["text"]), 1200)
        self.assertEqual(len(out["notes"]), 4)
        self.assertNotIn("latest", out["provenance"])
        self.assertEqual(out["plan"]["steps"][0]["status"], "todo")
        self.assertEqual(out["summary"]["widget_ids_by_step"]["p1"], ["w2"])


class LayoutHintTests(unittest.TestCase):
    def test_size_and_role_survive_reduce_and_sanitize(self):
        state = reducer.empty_state()
        events = [
            {"type": "workspace", "v": 1, "op": "widget.add", "seq": 1, "id": "w1",
             "kind": "text", "title": "Scope", "text": "What we analyse.", "role": "scope"},
            {"type": "workspace", "v": 1, "op": "widget.add", "seq": 2, "id": "w2",
             "kind": "chart", "title": "Trend", "sql_id": "s1q1", "size": "wide",
             "chart": {"type": "line", "x": "month", "y": ["revenue"]}},
        ]
        for event in events:
            state = reducer.apply(state, event)
        widgets = state["widgets"]
        self.assertEqual(widgets[0]["role"], "scope")
        self.assertEqual(widgets[1]["size"], "wide")
        doc = json.loads(json.dumps(state))
        doc["widgets"][1]["size"] = "huge"                   # invalid hint -> dropped
        doc["widgets"][1]["role"] = "scope"                  # role on a chart -> dropped
        doc["widgets"][0]["size"] = "wide"                   # size on a text -> dropped
        out = reducer.sanitize(doc)
        self.assertEqual(out["widgets"][0]["role"], "scope")
        self.assertNotIn("size", out["widgets"][1])
        self.assertNotIn("role", out["widgets"][1])
        self.assertNotIn("size", out["widgets"][0])
        self.assertEqual(len(out["widgets"]), 2)



class StudioContinuityReducerTests(unittest.TestCase):
    def test_shared_continuity_cases(self):
        for case in _load("workspace_continuity_cases.json")["reducer_cases"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(reducer.reduce_events(case["events"]), case["expected"])

    def _base(self):
        return {"v": 1, "status": "done", "plan": None, "notes": [], "provenance": {},
                "widgets": [
                    {"id": "w1", "kind": "chart", "title": "A", "sql_id": "s1q1",
                     "step_id": "p1", "ts": 3.0, "binding": "explicit",
                     "chart": {"type": "line", "x": "m", "y": ["v"]}},
                    {"id": "w2", "kind": "table", "title": "B", "sql_id": "s2q1",
                     "binding": "orphan"},
                    {"id": "w3", "kind": "kpi", "title": "C", "sql_id": "s1q1",
                     "kpi": {"label": "CA", "value": "v"}, "binding": "explicit",
                     "origin": "ex-root"}]}

    def test_build_carry_flattens_origin_and_drops_removed(self):
        carry = reducer.build_carry(self._base(), "ex-base", 4, remove=["w2", "w9"], ts=1.5)
        self.assertEqual((carry["op"], carry["seq"], carry["ts"]), ("studio.carry", 4, 1.5))
        self.assertEqual([(w["id"], w["origin"]) for w in carry["widgets"]],
                         [("w1", "ex-base"), ("w3", "ex-root")])     # never a chain
        self.assertNotIn("step_id", carry["widgets"][0])
        self.assertNotIn("ts", carry["widgets"][0])
        self.assertIsNone(reducer.build_carry(self._base(), "bad id!", 1))
        self.assertIsNone(reducer.build_carry(None, "ex-base", 1))

    def test_carry_then_finalize_keeps_carried_bindings(self):
        carry = reducer.build_carry(self._base(), "ex-base", 1)
        state = reducer.apply_carry(reducer.empty_state(), carry)
        state = reducer.apply(state, {"v": 1, "op": "widget.add", "seq": 2, "id": "w4",
                                      "kind": "table", "title": "N", "sql_id": "s1q1"})
        self.assertEqual(state["summary"]["sql_ids"], ["s1q1"])
        final = reducer.finalize(state, "done", "ex-new", known_sql_ids=[])
        self.assertEqual([w["binding"] for w in final["widgets"]],
                         ["explicit", "orphan", "explicit", "orphan"])
        self.assertEqual(final["base_exchange_id"], "ex-base")
        # Round trip: origin + base_exchange_id survive sanitize.
        self.assertEqual(reducer.sanitize(json.loads(json.dumps(final))), final)

    def test_sanitize_drops_invalid_origin_and_base(self):
        doc = reducer.finalize(reducer.empty_state(), "done")
        doc["base_exchange_id"] = "bad id"
        doc["widgets"] = [{"id": "w1", "kind": "text", "title": "T", "text": "x",
                           "origin": "../etc"}]
        out = reducer.sanitize(doc)
        self.assertNotIn("base_exchange_id", out)
        self.assertNotIn("origin", out["widgets"][0])

    def test_summary_by_step_skips_carried(self):
        doc = reducer.finalize(reducer.empty_state(), "done")
        doc["widgets"] = [{"id": "w1", "kind": "text", "title": "T", "text": "x",
                           "step_id": "p1", "origin": "ex-1"},
                          {"id": "w2", "kind": "text", "title": "T", "text": "y",
                           "step_id": "p1"}]
        self.assertEqual(reducer.sanitize(doc)["summary"]["widget_ids_by_step"],
                         {"p1": ["w2"]})

    def test_apply_carry_ignores_other_ops_and_agent_cannot_carry(self):
        state = reducer.empty_state()
        self.assertEqual(reducer.apply_carry(state, {"op": "widget.add"}), state)
        carry = reducer.build_carry(self._base(), "ex-base", 1)
        self.assertEqual(reducer.apply(state, dict(carry, op="studio.carry"))["widgets"][0]["id"], "w1")
        self.assertEqual(reducer.apply(state, dict(carry, widgets="x")), state)

if __name__ == "__main__":
    unittest.main()
