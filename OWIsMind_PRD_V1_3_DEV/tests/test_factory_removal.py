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


class TestSafeDelete(unittest.TestCase):
    class _Handle(object):
        def __init__(self):
            self.deleted = False

        def delete(self):
            self.deleted = True

    def test_deletes_when_name_matches(self):
        handle = self._Handle()
        removal.safe_delete(handle, "obj", lambda: "obj")
        self.assertTrue(handle.deleted)

    def test_refuses_on_name_mismatch(self):
        handle = self._Handle()
        with self.assertRaises(removal.RemovalRefused):
            removal.safe_delete(handle, "obj", lambda: "OTHER")
        self.assertFalse(handle.deleted)

    def test_fails_closed_when_name_unreadable(self):
        handle = self._Handle()

        def _boom():
            raise RuntimeError("api down")

        with self.assertRaises(removal.RemovalRefused):
            removal.safe_delete(handle, "obj", _boom)
        self.assertFalse(handle.deleted)

    def test_custom_deleter_is_used(self):
        handle = self._Handle()
        called = {}
        removal.safe_delete(handle, "obj", lambda: "obj",
                            deleter=lambda: called.setdefault("yes", True))
        self.assertFalse(handle.deleted)
        self.assertTrue(called.get("yes"))

    def test_probe_wording_preserved(self):
        """probes.py delegates here; its historical messages must not change."""
        handle = self._Handle()
        try:
            removal.safe_delete(handle, "zz_probe", lambda: None,
                                noun="probe object", hint=", clean zz_* by hand")
            self.fail("expected RemovalRefused")
        except removal.RemovalRefused as exc:
            self.assertIn("probe object", str(exc))
            self.assertIn("clean zz_* by hand", str(exc))


def _seed_full_domain(project):
    """A complete factory-created opportunities domain, plus foreign objects."""
    project.datasets |= {"DRIVE_Opportunities", "DRIVE_Opportunities_profile",
                         "DRIVE_Opportunities_value_index",
                         "DRIVE_Opportunities_value_catalog",
                         "OWIsMind_agent_catalog_v1", "DRIVE_Revenues"}
    project.recipes |= {"compute_DRIVE_Opportunities_profile",
                        "compute_DRIVE_Opportunities_value_index",
                        "compute_DRIVE_Opportunities_value_catalog",
                        "compute_DRIVE_Revenues_profile"}
    project.scenarios["sc1"] = "Refresh_Opportunities"
    project.agents["4Ghpi5hm"] = "Opportunities_expert"
    project.agents["038G7mlF"] = "OWIsMind_orchestrator"
    project.tools["iUR8wLX"] = {"name": "opportunities_semantic_query",
                                "params": {"semanticModelId": "mOdEl42"}}
    project.models["mOdEl42"] = "DRIVE_Opportunities_Semantic_Model"
    project.zones.append(_FakeZone(project, "Opportunities_Expert",
                                   items=["a", "b", "c", "d"]))
    project.library.files["/python/owismind_hub/wizard/opportunities-config.json"] = "{}"
    project.library.files["/python/owismind_hub/prompts/opportunities/understand_extra.md"] = "x"
    project.library.files["/python/owismind_hub/generated/Opportunities_expert.py"] = "# code"


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.project = _FakeProject()
        _seed_full_domain(self.project)
        self.entry = _entry()
        self.settings = dict(hub.DEFAULT_SETTINGS)

    def _build(self):
        return removal.build_inventory(
            self.project, "opportunities_expert", self.entry, self.settings)

    def test_finds_every_existing_artifact(self):
        inventory, problems = self._build()
        self.assertEqual(problems, [])
        stages = inventory["stages"]
        self.assertEqual([i["name"] for i in stages["delete_tool"]],
                         ["opportunities_semantic_query"])
        self.assertEqual(stages["delete_tool"][0]["id"], "iUR8wLX")
        self.assertEqual([i["name"] for i in stages["delete_agent"]],
                         ["Opportunities_expert"])
        self.assertEqual(stages["delete_agent"][0]["id"], "4Ghpi5hm")
        self.assertEqual(stages["delete_model"][0]["id"], "mOdEl42")
        self.assertEqual([i["name"] for i in stages["delete_scenario"]],
                         ["Refresh_Opportunities"])
        self.assertEqual(sorted(i["name"] for i in stages["delete_datasets"]),
                         ["DRIVE_Opportunities_profile",
                          "DRIVE_Opportunities_value_catalog",
                          "DRIVE_Opportunities_value_index"])
        self.assertEqual(sorted(i["name"] for i in stages["delete_recipes"]),
                         ["compute_DRIVE_Opportunities_profile",
                          "compute_DRIVE_Opportunities_value_catalog",
                          "compute_DRIVE_Opportunities_value_index"])
        self.assertEqual([i["name"] for i in stages["delete_zone"]],
                         ["Opportunities_Expert"])

    def test_source_dataset_is_protected_never_deletable(self):
        inventory, _problems = self._build()
        deletable = [i["name"] for items in inventory["stages"].values() for i in items]
        self.assertNotIn("DRIVE_Opportunities", deletable)
        self.assertEqual([i["name"] for i in inventory["protected"]],
                         ["DRIVE_Opportunities"])

    def test_absent_objects_land_in_notes_not_stages(self):
        self.project.tools.clear()
        self.project.scenarios.clear()
        inventory, problems = self._build()
        self.assertEqual(problems, [])
        self.assertEqual(inventory["stages"]["delete_tool"], [])
        self.assertEqual(inventory["stages"]["delete_scenario"], [])
        self.assertTrue(any("opportunities_semantic_query" in n
                            for n in inventory["notes"]))

    def test_founder_model_resolved_through_tool_params(self):
        """Founder names ignore conventions: the model resolves via the tool."""
        self.project.models.pop("mOdEl42")
        self.project.models["AHUh9hb"] = "Drive_Revenues_Semantic_Model"
        self.project.tools["iUR8wLX"]["params"] = {"semanticModelId": "AHUh9hb"}
        inventory, _problems = self._build()
        self.assertEqual(inventory["stages"]["delete_model"][0]["id"], "AHUh9hb")

    def test_listing_failure_is_a_problem_not_a_hole(self):
        self.project.fail_list.add("tools")
        _inventory, problems = self._build()
        self.assertTrue(any("tools" in p or "réessaie" in p for p in problems))

    def test_template_conflicts_detected(self):
        self.settings["template_semantic_tool_id"] = "iUR8wLX"
        self.settings["template_zone_recipes"] = {
            "profile": "compute_DRIVE_Opportunities_profile"}
        inventory, _problems = self._build()
        conflicts = inventory["template_conflicts"]
        self.assertEqual(len(conflicts), 2)
        self.assertTrue(any("iUR8wLX" in c for c in conflicts))

    def test_hub_paths_cover_wizard_prompts_generated(self):
        inventory, _problems = self._build()
        self.assertEqual(inventory["hub_paths"], [
            "/python/owismind_hub/wizard/opportunities-config.json",
            "/python/owismind_hub/prompts/opportunities",
            "/python/owismind_hub/generated/Opportunities_expert.py",
        ])


class TestExecutors(unittest.TestCase):
    def setUp(self):
        self.project = _FakeProject()
        _seed_full_domain(self.project)
        self.entry = _entry()
        self.settings = dict(hub.DEFAULT_SETTINGS)
        self.inventory, problems = removal.build_inventory(
            self.project, "opportunities_expert", self.entry, self.settings)
        self.assertEqual(problems, [])

    def _run(self, stage_key):
        items = self.inventory["stages"][stage_key]
        return removal.execute_delete_stage(self.project, stage_key, items,
                                            _ctx(self.project))

    def test_delete_tool_deletes_and_verifies(self):
        manual, problems = self._run("delete_tool")
        self.assertEqual((manual, problems), ([], []))
        self.assertNotIn("iUR8wLX", self.project.tools)

    def test_delete_agent_only_the_domain_agent(self):
        manual, problems = self._run("delete_agent")
        self.assertEqual((manual, problems), ([], []))
        self.assertNotIn("4Ghpi5hm", self.project.agents)
        self.assertIn("038G7mlF", self.project.agents)

    def test_delete_datasets_drops_data_and_spares_source(self):
        manual, problems = self._run("delete_datasets")
        self.assertEqual((manual, problems), ([], []))
        self.assertIn("DRIVE_Opportunities", self.project.datasets)
        self.assertNotIn("DRIVE_Opportunities_profile", self.project.datasets)
        drops = [kw for kind, _n, kw in self.project.deleted if kind == "dataset"]
        self.assertTrue(all(kw.get("drop_data") is True for kw in drops))

    def test_api_refusal_flips_to_manual_not_failure(self):
        self.project.fail_delete.add("agent")
        manual, problems = self._run("delete_agent")
        self.assertEqual(problems, [])
        self.assertEqual(len(manual), 1)
        self.assertIn("reason_fr", manual[0])
        self.assertIn("4Ghpi5hm", self.project.agents)

    def test_already_absent_is_idempotent(self):
        self.project.tools.clear()
        manual, problems = self._run("delete_tool")
        self.assertEqual((manual, problems), ([], []))

    def test_running_scenario_is_refused_to_manual(self):
        self.project.scenario_running["sc1"] = {"running": True}
        manual, problems = self._run("delete_scenario")
        self.assertEqual(problems, [])
        self.assertEqual(len(manual), 1)
        self.assertIn("sc1", self.project.scenarios)

    def test_zone_kept_when_not_empty_deleted_when_empty(self):
        manual, problems = self._run("delete_zone")
        self.assertEqual((manual, problems), ([], []))
        self.assertTrue(any(z.name == "Opportunities_Expert" for z in self.project.zones))
        self.project.zones[0].items = []
        manual, problems = self._run("delete_zone")
        self.assertEqual((manual, problems), ([], []))
        self.assertFalse(any(z.name == "Opportunities_Expert" for z in self.project.zones))

    def test_verify_stage_absent_reports_leftovers(self):
        items = self.inventory["stages"]["delete_tool"]
        leftovers, problems = removal.verify_stage_absent(
            self.project, "delete_tool", items)
        self.assertEqual(problems, [])
        self.assertEqual([i["name"] for i in leftovers],
                         ["opportunities_semantic_query"])
        self.project.tools.clear()
        leftovers, problems = removal.verify_stage_absent(
            self.project, "delete_tool", items)
        self.assertEqual((leftovers, problems), ([], []))

    def test_verify_zone_nonempty_is_not_a_leftover(self):
        items = self.inventory["stages"]["delete_zone"]
        leftovers, _problems = removal.verify_stage_absent(
            self.project, "delete_zone", items)
        self.assertEqual(leftovers, [])


class TestCatalogAndHubCleanup(unittest.TestCase):
    def setUp(self):
        self.project = _FakeProject()
        _seed_full_domain(self.project)

    def test_delete_catalog_rows_parametrized_delete_plus_commit(self):
        recorded = {}

        class _Executor(object):
            def query_to_df(self, query, pre_queries=None, post_queries=None):
                recorded["pre"] = list(pre_queries or [])
                recorded["post"] = list(post_queries or [])

        import owismind_factory.wizard as wizard_module
        original = wizard_module.get_physical_table
        wizard_module.get_physical_table = lambda p, d: "TESTKEY_owismind_agent_catalog_v1"
        try:
            status = removal.delete_catalog_rows(
                self.project, "SQL_owi", "opportunities_expert",
                executor_factory=lambda: _Executor())
        finally:
            wizard_module.get_physical_table = original
        self.assertEqual(status, "deleted")
        self.assertEqual(len(recorded["pre"]), 1)
        self.assertIn('DELETE FROM public."TESTKEY_owismind_agent_catalog_v1"',
                      recorded["pre"][0])
        self.assertIn("'opportunities_expert'", recorded["pre"][0])
        self.assertEqual(recorded["post"], ["COMMIT"])

    def test_delete_catalog_rows_no_dataset(self):
        self.project.datasets.discard("OWIsMind_agent_catalog_v1")
        status = removal.delete_catalog_rows(
            self.project, "SQL_owi", "opportunities_expert",
            executor_factory=lambda: None)
        self.assertEqual(status, "no_dataset")

    def test_cleanup_hub_deletes_paths_and_entry(self):
        _seed_capabilities(self.project, {
            "opportunities_expert": _entry(),
            "revenue_expert": _entry(domain="revenue", agent_id="agent:bHrWLyOL",
                                     lookup_dataset="DRIVE_Revenues",
                                     lookup_catalog="DRIVE_Revenues_Value_Catalog"),
        })
        paths = ["/python/owismind_hub/wizard/opportunities-config.json",
                 "/python/owismind_hub/prompts/opportunities",
                 "/python/owismind_hub/generated/Opportunities_expert.py"]
        manual, status = removal.cleanup_hub(
            self.project, "opportunities_expert", paths, _ctx(self.project))
        self.assertEqual(manual, [])
        self.assertEqual(status, "removed")
        for path in paths:
            self.assertIsNot(hub.path_exists(self.project, path), True)
        stored = json.loads(self.project.library.files[hub.CAPABILITIES_PATH])
        self.assertNotIn("opportunities_expert", stored)

    def test_cleanup_hub_last_entry_kept_disabled(self):
        _seed_capabilities(self.project, {"opportunities_expert": _entry(enabled=True)})
        _manual, status = removal.cleanup_hub(
            self.project, "opportunities_expert", [], _ctx(self.project))
        self.assertEqual(status, "kept_disabled")
