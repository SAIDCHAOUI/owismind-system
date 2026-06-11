"""Anti-drift: the revenue manifest in the orchestrator registry MUST keep
advertising the sub-agent's real coverage (all phases + the main axes). If
someone shrinks the description back to "revenue only", this test fails — which
is exactly the bug that made the orchestrator deny "budget 2026". The phases and
axes are sourced from the sub-agent's OWN constants, never re-hardcoded here.

Run from the repo root:
    python3 -m unittest discover -s orchestrator/tests -v -k AntiDrift
"""
import importlib.util
import os
import sys
import types
import unittest


def _install_dataiku_stub():
    dataiku_mod = types.ModuleType("dataiku")
    dataiku_mod.api_client = lambda: None
    llm_pkg = types.ModuleType("dataiku.llm")
    llm_python = types.ModuleType("dataiku.llm.python")

    class BaseLLM(object):
        pass

    llm_python.BaseLLM = BaseLLM
    llm_pkg.python = llm_python
    dataiku_mod.llm = llm_pkg
    sys.modules.setdefault("dataiku", dataiku_mod)
    sys.modules.setdefault("dataiku.llm", llm_pkg)
    sys.modules.setdefault("dataiku.llm.python", llm_python)


def _load(name, relpath):
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), relpath))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_install_dataiku_stub()
orc = _load("orc_under_test", "../orchestrator_agent.py")
sd = _load("sd_under_test", "../../salesdrive/salesdrive_agent.py")


class AntiDriftTests(unittest.TestCase):

    def _revenue_manifests(self):
        return [v["planner_description"].lower()
                for v in orc.CAPABILITIES.values()
                if v.get("kind") == "agent" and v.get("domain") == "revenue"]

    def test_at_least_one_revenue_manifest_exists(self):
        self.assertTrue(self._revenue_manifests())

    def test_every_revenue_manifest_covers_all_known_phases(self):
        for desc in self._revenue_manifests():
            for phase in sd.KNOWN_PHASES:                  # ACTUALS,BUDGET,FORECAST,Q3F,HLF
                self.assertIn(phase.lower(), desc,
                              "manifest must advertise phase %r" % phase)

    def test_every_revenue_manifest_covers_main_axes(self):
        for desc in self._revenue_manifests():
            for axis in ("customer", "product", "solution", "month", "year"):
                self.assertIn(axis, desc, "manifest must advertise axis %r" % axis)


if __name__ == "__main__":
    unittest.main()
