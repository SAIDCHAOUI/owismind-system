"""Capability removal tests (DSS-free).

Covers owismind_factory.removal (safe delete, probe-based inventory, deletion
executors) plus the hub helpers and the guided REMOVAL machine.

Run from the repo root:
    python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -v
"""

import json
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_PARENT = os.path.abspath(os.path.join(_HERE, "..", "project-library", "python"))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)


def _install_dataiku_sql_stub():
    """dataiku + dataiku.sql stubs so _sql_value works without DSS."""
    mod = sys.modules.get("dataiku")
    if mod is None:
        mod = types.ModuleType("dataiku")
        sys.modules["dataiku"] = mod
    sql_mod = types.ModuleType("dataiku.sql")

    class Constant(object):
        def __init__(self, value):
            self.value = value

    class Dialects(object):
        POSTGRES = "postgres"

    def toSQL(node, dialect=None):
        assert isinstance(node, Constant), "values MUST go through Constant"
        return "'" + str(node.value).replace("'", "''") + "'"

    sql_mod.Constant = Constant
    sql_mod.Dialects = Dialects
    sql_mod.toSQL = toSQL
    sys.modules["dataiku.sql"] = sql_mod
    mod.sql = sql_mod
    return mod


_install_dataiku_sql_stub()

from owismind_factory import guided, hub, removal  # noqa: E402
from owismind_factory.fctx import FactoryContext  # noqa: E402


# ------------------------------------------------------------------ fakes

class _FakeLibFile(object):
    def __init__(self, tree, path):
        self._tree, self._path = tree, path

    def read(self):
        return self._tree[self._path]

    def write(self, content):
        self._tree[self._path] = content

    def delete(self):
        self._tree.pop(self._path, None)


class _FakeFolder(object):
    def __init__(self, library, path):
        self._library, self._path = library, path

    def add_folder(self, name):
        base = self._path.rstrip("/")
        return _FakeFolder(self._library, base + "/" + name)

    def add_file(self, name):
        full = self._path.rstrip("/") + "/" + name
        self._library.files[full] = ""
        return _FakeLibFile(self._library.files, full)

    def delete(self):
        prefix = self._path.rstrip("/") + "/"
        for key in [p for p in self._library.files if p.startswith(prefix)]:
            self._library.files.pop(key)


class _FakeLibrary(object):
    """dict-backed project library: files = {absolute path: text}."""

    def __init__(self, files=None):
        self.files = dict(files or {})
        self.root = _FakeFolder(self, "")

    def get_file(self, path):
        return _FakeLibFile(self.files, path) if path in self.files else None

    def get_folder(self, path):
        if path in ("", "/"):
            return self.root
        prefix = path.rstrip("/") + "/"
        if any(p.startswith(prefix) for p in self.files):
            return _FakeFolder(self, path)
        return None


class _Listed(object):
    def __init__(self, obj_id, name):
        self.id = obj_id
        self.name = name


class _FakeZone(object):
    def __init__(self, project, name, items=None):
        self._project = project
        self.name = name
        self.items = list(items or [])

    def delete(self):
        if "zone" in self._project.fail_delete:
            raise RuntimeError("zone delete refused")
        self._project.deleted.append(("zone", self.name, {}))
        self._project.zones = [z for z in self._project.zones if z.name != self.name]


class _FakeFlow(object):
    def __init__(self, project):
        self._project = project

    def list_zones(self):
        return list(self._project.zones)


class _FakeScenario(object):
    def __init__(self, project, scenario_id):
        self._project, self._id = project, scenario_id

    def get_current_run(self):
        return self._project.scenario_running.get(self._id)

    def delete(self):
        if "scenario" in self._project.fail_delete:
            raise RuntimeError("scenario delete refused")
        name = self._project.scenarios.pop(self._id, None)
        self._project.deleted.append(("scenario", name, {}))


class _FakeProject(object):
    """One dict per object family; delete() mutates the dicts so read-back
    verification sees the disappearance, exactly like DSS."""

    project_key = "TESTKEY"

    def __init__(self):
        self.datasets = set()
        self.recipes = set()
        self.scenarios = {}          # id -> name
        self.scenario_running = {}   # id -> truthy run marker
        self.agents = {}             # id -> name
        self.tools = {}              # id -> {"name":..., "params": {...}}
        self.models = {}             # id -> name
        self.zones = []
        self.library = _FakeLibrary()
        self.deleted = []            # (kind, name, kwargs) journal
        self.fail_delete = set()     # kinds whose delete() raises
        self.fail_list = set()       # families whose list_*() raises

    # --- datasets / recipes
    def list_datasets(self):
        if "datasets" in self.fail_list:
            raise RuntimeError("boom")
        return [{"name": n} for n in sorted(self.datasets)]

    def get_dataset(self, name):
        project = self

        class _DS(object):
            def delete(self, **kwargs):
                if "dataset" in project.fail_delete:
                    raise RuntimeError("dataset delete refused")
                project.deleted.append(("dataset", name, dict(kwargs)))
                project.datasets.discard(name)

        return _DS()

    def list_recipes(self):
        if "recipes" in self.fail_list:
            raise RuntimeError("boom")
        return [{"name": n} for n in sorted(self.recipes)]

    def get_recipe(self, name):
        project = self

        class _R(object):
            def delete(self):
                if "recipe" in project.fail_delete:
                    raise RuntimeError("recipe delete refused")
                project.deleted.append(("recipe", name, {}))
                project.recipes.discard(name)

        return _R()

    # --- scenarios
    def list_scenarios(self):
        if "scenarios" in self.fail_list:
            raise RuntimeError("boom")
        return [{"id": i, "name": n} for i, n in sorted(self.scenarios.items())]

    def get_scenario(self, scenario_id):
        return _FakeScenario(self, scenario_id)

    # --- agents / tools / models
    def list_agents(self):
        if "agents" in self.fail_list:
            raise RuntimeError("boom")
        return [_Listed(i, n) for i, n in sorted(self.agents.items())]

    def get_agent(self, agent_id):
        project = self

        class _A(object):
            def delete(self):
                if "agent" in project.fail_delete:
                    raise RuntimeError("agent delete refused")
                name = project.agents.pop(agent_id, None)
                project.deleted.append(("agent", name, {}))

        return _A()

    def list_agent_tools(self):
        if "tools" in self.fail_list:
            raise RuntimeError("boom")
        return [_Listed(i, t["name"]) for i, t in sorted(self.tools.items())]

    def get_agent_tool(self, tool_id):
        project = self

        class _Settings(object):
            def get_raw(self):
                return {"params": project.tools.get(tool_id, {}).get("params", {})}

        class _T(object):
            def get_settings(self):
                return _Settings()

            def delete(self):
                if "tool" in project.fail_delete:
                    raise RuntimeError("tool delete refused")
                entry = project.tools.pop(tool_id, None)
                project.deleted.append(("tool", (entry or {}).get("name"), {}))

        return _T()

    def list_semantic_models(self):
        if "models" in self.fail_list:
            raise RuntimeError("boom")
        return [_Listed(i, n) for i, n in sorted(self.models.items())]

    def get_semantic_model(self, model_id):
        project = self

        class _M(object):
            def delete(self):
                if "model" in project.fail_delete:
                    raise RuntimeError("model delete refused")
                name = project.models.pop(model_id, None)
                project.deleted.append(("model", name, {}))

        return _M()

    # --- flow / library
    def get_flow(self):
        return _FakeFlow(self)

    def get_library(self):
        return self.library


def _ctx(project):
    return FactoryContext(project=project, dry_run=False, abort_on_failure=False)


def _entry(domain="opportunities", agent_id="agent:4Ghpi5hm", enabled=True,
           lookup_dataset="DRIVE_Opportunities",
           lookup_catalog="DRIVE_Opportunities_value_catalog"):
    """A minimal but VALID capability entry (mirrors registry.capability_entry)."""
    from owismind_factory.registry import KNOWN_BLOCK_IDS, KNOWN_TOOL_NAMES
    return {
        "kind": "agent", "agent_id": agent_id, "domain": domain,
        "label_fr": "Expert opportunités", "label_en": "Opportunities expert",
        "tool_name": "ask_%s_expert" % domain,
        "planner_description": "routing text",
        "block_labels": {k: {"fr": "x", "en": "x"} for k in KNOWN_BLOCK_IDS},
        "tool_labels": {k: {"fr": "x", "en": "x"} for k in KNOWN_TOOL_NAMES},
        "dataset_label_fr": "Base", "dataset_label_en": "Base",
        "source_url": "", "lookup_dataset": lookup_dataset,
        "lookup_catalog": lookup_catalog, "lookup_search_columns": [],
        "pass_context": True, "enabled": enabled,
    }


def _seed_capabilities(project, entries):
    project.library.files[hub.CAPABILITIES_PATH] = json.dumps(entries)


# ------------------------------------------------------------------ Task 1 tests

class TestHubRemovalHelpers(unittest.TestCase):
    def setUp(self):
        self.project = _FakeProject()

    def test_set_capability_enabled_flips_and_backs_up(self):
        _seed_capabilities(self.project, {"opportunities_expert": _entry(enabled=True)})
        caps = hub.set_capability_enabled(self.project, "opportunities_expert", False)
        self.assertFalse(caps["opportunities_expert"]["enabled"])
        stored = json.loads(self.project.library.files[hub.CAPABILITIES_PATH])
        self.assertFalse(stored["opportunities_expert"]["enabled"])
        backups = [p for p in self.project.library.files if "/backups/" in p]
        self.assertTrue(backups, "previous capabilities.json must be backed up")

    def test_set_capability_enabled_unknown_key_raises(self):
        _seed_capabilities(self.project, {"opportunities_expert": _entry()})
        with self.assertRaises(KeyError):
            hub.set_capability_enabled(self.project, "nope", True)

    def test_remove_capability_removes_when_not_last(self):
        _seed_capabilities(self.project, {
            "opportunities_expert": _entry(),
            "revenue_expert": _entry(domain="revenue", agent_id="agent:bHrWLyOL",
                                     lookup_dataset="DRIVE_Revenues",
                                     lookup_catalog="DRIVE_Revenues_Value_Catalog"),
        })
        status, caps = hub.remove_capability(self.project, "opportunities_expert")
        self.assertEqual(status, "removed")
        self.assertNotIn("opportunities_expert", caps)
        stored = json.loads(self.project.library.files[hub.CAPABILITIES_PATH])
        self.assertNotIn("opportunities_expert", stored)

    def test_remove_capability_keeps_last_entry_disabled(self):
        _seed_capabilities(self.project, {"opportunities_expert": _entry(enabled=True)})
        status, caps = hub.remove_capability(self.project, "opportunities_expert")
        self.assertEqual(status, "kept_disabled")
        self.assertIn("opportunities_expert", caps)
        self.assertFalse(caps["opportunities_expert"]["enabled"])

    def test_remove_capability_absent_is_noop(self):
        _seed_capabilities(self.project, {"opportunities_expert": _entry()})
        status, _caps = hub.remove_capability(self.project, "nope")
        self.assertEqual(status, "absent")

    def test_path_exists_and_delete_path(self):
        self.project.library.files["/python/owismind_hub/wizard/opportunities-config.json"] = "{}"
        self.project.library.files["/python/owismind_hub/prompts/opportunities/understand_extra.md"] = "x"
        self.assertTrue(hub.path_exists(
            self.project, "/python/owismind_hub/wizard/opportunities-config.json"))
        self.assertTrue(hub.path_exists(
            self.project, "/python/owismind_hub/prompts/opportunities"))
        self.assertFalse(hub.path_exists(self.project, "/python/owismind_hub/nope.json"))
        self.assertTrue(hub.delete_path(
            self.project, "/python/owismind_hub/wizard/opportunities-config.json"))
        self.assertTrue(hub.delete_path(
            self.project, "/python/owismind_hub/prompts/opportunities"))
        self.assertFalse(hub.delete_path(self.project, "/python/owismind_hub/nope.json"))
        self.assertFalse(hub.path_exists(
            self.project, "/python/owismind_hub/prompts/opportunities"))


if __name__ == "__main__":
    unittest.main()
