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


if __name__ == "__main__":
    unittest.main()
