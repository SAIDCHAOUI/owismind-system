# Plugin/owismind/tests/test_artifacts.py
"""Artifact plumbing — PURE validation layers, provable without a live DSS runtime:
  - storage.artifacts._sanitize : strict projection of chart/table specs (write+read);
  - agents.streaming._normalized_artifact_event : the ARTIFACT event normalizer.
A minimal dataiku stub lets the modules import (unittest discover shares sys.modules).
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
        sql_mod.toSQL = lambda constant, dialect=None: repr(constant)
    if not hasattr(sql_mod, "Dialects"):
        sql_mod.Dialects = type("Dialects", (), {"POSTGRES": "postgres"})
    dk.sql = sql_mod
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.ModuleType("pandas")


_ensure_dataiku_stub()

from owismind.storage import artifacts            # noqa: E402
from owismind.agents import streaming             # noqa: E402


class TestSanitize(unittest.TestCase):
    def test_valid_chart(self):
        out = artifacts._sanitize([
            {"kind": "chart", "title": "Revenue",
             "chart": {"type": "line", "x": "year", "y": ["revenue"]}}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["chart"], {"type": "line", "x": "year", "y": ["revenue"]})

    def test_chart_y_string_coerced(self):
        out = artifacts._sanitize([
            {"kind": "chart", "chart": {"type": "bar", "x": "p", "y": "rev"}}])
        self.assertEqual(out[0]["chart"]["y"], ["rev"])

    def test_chart_bad_type_dropped(self):
        self.assertEqual(artifacts._sanitize([
            {"kind": "chart", "chart": {"type": "scatter", "x": "a", "y": ["b"]}}]), [])

    def test_chart_missing_block_dropped(self):
        self.assertEqual(artifacts._sanitize([{"kind": "chart"}]), [])

    def test_table_kept(self):
        out = artifacts._sanitize([{"kind": "table", "title": "All"}])
        self.assertEqual(out[0]["kind"], "table")
        self.assertIsNone(out[0]["chart"])

    def test_unknown_kind_dropped(self):
        self.assertEqual(artifacts._sanitize([{"kind": "map"}]), [])

    def test_cap(self):
        many = [{"kind": "table"} for _ in range(50)]
        self.assertEqual(len(artifacts._sanitize(many)), artifacts.MAX_ARTIFACTS)

    def test_title_bounded(self):
        out = artifacts._sanitize([{"kind": "table", "title": "x" * 999}])
        self.assertLessEqual(len(out[0]["title"]), 200)


class TestNormalizedArtifactEvent(unittest.TestCase):
    def test_chart(self):
        ev = streaming._normalized_artifact_event(
            {"kind": "chart", "title": "T", "chart": {"type": "pie", "x": "p", "y": ["v"]}})
        self.assertEqual(ev["type"], "artifact")
        self.assertEqual(ev["kind"], "chart")
        self.assertEqual(ev["chart"], {"type": "pie", "x": "p", "y": ["v"]})

    def test_table(self):
        ev = streaming._normalized_artifact_event({"kind": "table", "title": "T"})
        self.assertEqual(ev["kind"], "table")
        self.assertIsNone(ev["chart"])

    def test_unknown_kind(self):
        self.assertIsNone(streaming._normalized_artifact_event({"kind": "x"}))

    def test_chart_bad_type(self):
        self.assertIsNone(streaming._normalized_artifact_event(
            {"kind": "chart", "chart": {"type": "scatter", "x": "a", "y": ["b"]}}))

    def test_non_dict(self):
        self.assertIsNone(streaming._normalized_artifact_event(None))


if __name__ == "__main__":
    unittest.main()
