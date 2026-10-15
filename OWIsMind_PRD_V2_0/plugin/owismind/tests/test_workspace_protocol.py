"""workspace.protocol - contract parity + strict normalization of one WORKSPACE op.

  - parity: every enum / pattern / cap embedded in protocol.py equals the shared
    contract ``contracts/workspace_protocol.v1.json`` read from disk (the zip ships
    python-lib without contracts/, hence the embedded mirror);
  - the shared normalization fixture (``contracts/fixtures/workspace_normalize_cases.json``)
    passes case by case;
  - normalization is idempotent and never raises on garbage.
Pure stdlib, no DSS runtime needed.
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.workspace import protocol as p  # noqa: E402

CONTRACTS = os.path.join(_HERE, "..", "contracts")
FIXTURES = os.path.join(CONTRACTS, "fixtures")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class ContractParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = _load(os.path.join(CONTRACTS, "workspace_protocol.v1.json"))

    def test_version(self):
        self.assertEqual(self.contract["version"], p.PROTOCOL_VERSION)

    def test_caps(self):
        self.assertEqual(self.contract["caps"], p.CAPS)

    def test_enums(self):
        self.assertEqual(self.contract["enums"], {k: list(v) for k, v in p.ENUMS.items()})

    def test_patterns(self):
        self.assertEqual(self.contract["patterns"], p.PATTERNS)
        defs = self.contract["$defs"]
        self.assertEqual(defs["slug"]["pattern"], p.SLUG_PATTERN)
        self.assertEqual(defs["sqlId"]["pattern"], p.SQL_ID_PATTERN)

    def test_def_level_caps(self):
        defs = self.contract["$defs"]
        self.assertEqual(defs["planStep"]["properties"]["unit"]["maxLength"], p.STEP_UNIT_CHARS)
        chart = defs["chartSpec"]["properties"]
        self.assertEqual(chart["x"]["maxLength"], p.CHART_COLUMN_CHARS)
        self.assertEqual(chart["y"]["maxItems"], p.MAX_Y_SERIES)
        self.assertEqual(chart["x_label"]["maxLength"], p.CHART_AXIS_LABEL_CHARS)
        self.assertEqual(chart["unit"]["maxLength"], p.UNIT_CHARS)
        self.assertEqual(chart["style"]["enum"], list(p.CHART_STYLES))
        kpi = defs["kpiSpec"]["properties"]
        self.assertEqual(kpi["label"]["maxLength"], p.KPI_LABEL_CHARS)
        self.assertEqual(kpi["value"]["maxLength"], p.KPI_COLUMN_CHARS)
        prov = self.contract["events"]["prov.set"]["properties"]
        self.assertEqual(prov["agent_key"]["maxLength"], p.AGENT_KEY_CHARS)
        self.assertEqual(prov["task"]["maxLength"], p.TASK_CHARS)

    def test_event_level_caps_match_caps_block(self):
        ev = self.contract["events"]
        self.assertEqual(ev["plan.set"]["properties"]["mission"]["maxLength"], p.MISSION_CHARS)
        self.assertEqual(ev["plan.set"]["properties"]["steps"]["maxItems"], p.MAX_PLAN_STEPS)
        self.assertEqual(ev["note.add"]["properties"]["text"]["maxLength"], p.NOTE_TEXT_CHARS)
        self.assertEqual(ev["widget.add"]["properties"]["text"]["maxLength"], p.WIDGET_TEXT_CHARS)
        self.assertEqual(ev["widget.add"]["properties"]["comment"]["maxLength"],
                         p.WIDGET_COMMENT_CHARS)
        self.assertEqual(sorted(ev), sorted(p.OPS))


class NormalizeFixtureTests(unittest.TestCase):
    def test_shared_cases(self):
        cases = _load(os.path.join(FIXTURES, "workspace_normalize_cases.json"))["cases"]
        self.assertGreater(len(cases), 40)
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertEqual(p.normalize_op(case["input"], case["default_ts"]),
                                 case["expected"])

    def test_idempotent_on_normalized_events(self):
        cases = _load(os.path.join(FIXTURES, "workspace_normalize_cases.json"))["cases"]
        for case in cases:
            if case["expected"] is not None:
                with self.subTest(case=case["name"]):
                    self.assertEqual(p.normalize_op(case["expected"]), case["expected"])

    def test_run_fixture_events_are_normalized_forms(self):
        for name in ("workspace_run_multi_facet", "workspace_run_stopped",
                     "workspace_run_orphan_widget"):
            fx = _load(os.path.join(FIXTURES, name + ".json"))
            raw = [c["eventData"] for c in fx["raw_chunks"] if c.get("eventKind") == "WORKSPACE"]
            with self.subTest(fixture=name):
                self.assertEqual([p.normalize_op(d, 99.0) for d in raw], fx["expected_events"])


class NormalizeRobustnessTests(unittest.TestCase):
    def test_garbage_never_raises(self):
        for junk in (None, 1, "x", [], {"v": 1}, {"v": 1, "op": "plan.set", "seq": 1,
                                                   "steps": "nope"},
                     {"v": 1, "op": "widget.add", "seq": 1, "id": "w", "kind": "chart",
                      "title": "t", "sql_id": "s1q1", "chart": {"type": "bar", "x": 1, "y": None}},
                     {"v": 1, "op": "prov.set", "seq": 1, "sql_id": "s" + "1" * 500 + "q1",
                      "agent_key": "a", "tool": "correlate", "success": True}):
            self.assertIsNone(p.normalize_op(junk))

    def test_nan_and_infinite_ts_replaced(self):
        base = {"v": 1, "op": "plan.step", "seq": 1, "step_id": "p1", "status": "done"}
        for bad in (float("nan"), float("inf"), True):
            self.assertEqual(p.normalize_op(dict(base, ts=bad), 2.5)["ts"], 2.5)

    def test_sql_id_formats(self):
        for good in ("s1q1", "s12q3", "s2lk1", "s3qc10"):
            self.assertEqual(p.sql_id(good), good)
        for bad in ("S1Q1", "s1", "q1", "s1q", "s1x1", " s1q1", "s1q1 ", 7, None):
            self.assertIsNone(p.sql_id(bad))


if __name__ == "__main__":
    unittest.main()
