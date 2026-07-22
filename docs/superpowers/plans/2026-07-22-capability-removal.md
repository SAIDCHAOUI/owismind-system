# Capability Removal + Disable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the factory console a guided REMOVAL run (delete everything a capability owns, one confirmed stage at a time) plus an immediate disable/re-enable action, per the approved spec `docs/superpowers/specs/2026-07-22-capability-removal-design.md`.

**Architecture:** A new `run_type: removal` inside the existing guided state machine (`owismind_factory/guided.py`), backed by a new `owismind_factory/removal.py` module (probe-based inventory + safe deletion executors), two new console routes, and overview-card actions in the console frontend. The frontend stepper is data-driven (`state.stage_order`), so the removal run renders with near-zero frontend change.

**Tech Stack:** Python 3.9-compatible (DSS webapp backend), dataikuapi public client (via the `project` handle), ES5 JavaScript (Standard webapp console), unittest (DSS-free).

## Global Constraints

- Code and comments in ENGLISH; all operator-facing strings in FRENCH (project rule 7).
- NEVER use U+2014 or U+2013 anywhere, including French UI strings (project rule 9). Use `-`, `:`, `,` or parentheses.
- Frontend contract FROZEN: stage statuses are exactly `pending / ready / running / waiting_user / done / failed`; no new status, no new event kind.
- The SOURCE dataset (capability `lookup_dataset`) is NEVER deletable (user decision 2026-07-22).
- Identity check before EVERY `delete()`: re-read the live name, match it, refuse on mismatch (probes.py pattern).
- A deletion that cannot be VERIFIED absent never advances the run.
- All new SQL is parameterized (`dataiku.sql` Constant/toSQL via `guided_store._sql_value`), identifiers pass `guided_store.quote_table`, every write ends with COMMIT.
- Tests are DSS-free: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests` from the repo root. NEVER install anything.
- Do not edit `resource/owismind-app/` or `ready-for-dataiku/` (generated); this feature lives in `project-library/` + `Standard-webapps/` (no plugin zip impact).
- Any styling addition follows the Orange charter (`docs/cadrage/CHARTE_ORANGE_UI.md`): square geometry, tokens, no new colors, no shadows/gradients.
- Commit after each task (message prefix below); never push.

---

### Task 1: hub.py capability + path helpers

**Files:**
- Modify: `OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/hub.py` (append after `append_capability`, line 273)
- Test: `OWIsMind_PRD_V1_3_DEV/tests/test_factory_removal.py` (NEW file)

**Interfaces:**
- Produces: `hub.set_capability_enabled(project, key, enabled) -> dict` (raises `KeyError` on unknown key, `ValueError` on validation failure), `hub.remove_capability(project, key) -> (status, caps)` with status in `"removed" | "kept_disabled" | "absent"`, `hub.path_exists(project, path) -> True | False | None`, `hub.delete_path(project, path) -> bool` (True deleted, False absent, raises on API failure). Tasks 4, 5, 6 consume all four.

- [ ] **Step 1: Create the test file with shared fakes and the hub tests**

Create `OWIsMind_PRD_V1_3_DEV/tests/test_factory_removal.py`. This file also carries the fakes reused by Tasks 2-5 (write them now, complete):

```python
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
```

- [ ] **Step 2: Run the new tests, verify they fail on the missing helpers**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_factory_removal.py -v`
Expected: FAIL / ERROR with `ImportError` (`removal` module) or `AttributeError: module ... has no attribute 'set_capability_enabled'`. Create an EMPTY `OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/removal.py` (docstring only, filled in Task 2) so the import error narrows to the hub helpers.

- [ ] **Step 3: Implement the four hub helpers**

Append to `hub.py` after `append_capability` (English comments, same style):

```python
def set_capability_enabled(project, key, enabled):
    """Flip one capability's ``enabled`` flag (validated, backed-up write).

    Raises ``KeyError`` when the key is unknown and ``ValueError`` when the
    resulting registry would be invalid (e.g. two enabled capabilities on the
    same domain): the caller surfaces both as-is.
    """
    with _CAPABILITIES_WRITE_LOCK:
        capabilities = read_capabilities(project)
        if not isinstance(capabilities, dict) or key not in capabilities:
            raise KeyError(key)
        capabilities[key]["enabled"] = bool(enabled)
        write_capabilities(project, capabilities)
        return capabilities


def remove_capability(project, key):
    """Remove one capability entry. Returns ``(status, capabilities)``.

    status is ``"removed"``, ``"absent"``, or ``"kept_disabled"``: the LAST
    entry is never removed, only disabled, because an empty capabilities.json
    is invalid and would make the orchestrator fall back to its embedded
    defaults (the removed expert could then silently REAPPEAR).
    """
    with _CAPABILITIES_WRITE_LOCK:
        capabilities = read_capabilities(project) or {}
        if key not in capabilities:
            return "absent", capabilities
        if len(capabilities) == 1:
            capabilities[key]["enabled"] = False
            write_capabilities(project, capabilities)
            return "kept_disabled", capabilities
        del capabilities[key]
        write_capabilities(project, capabilities)
        return "removed", capabilities


def path_exists(project, path):
    """True/False when the library file or folder provably exists/does not,
    None when the library itself cannot be read (callers treat None as
    "unknown", never as a verdict)."""
    try:
        library = _library(project)
        if library.get_file(path) is not None:
            return True
        return library.get_folder(path) is not None
    except Exception:
        return None


def delete_path(project, path):
    """Delete a library file or folder. True when something was deleted,
    False when already absent. API refusals raise (caller flips to manual)."""
    library = _library(project)
    f = library.get_file(path)
    if f is not None:
        f.delete()
        return True
    folder = library.get_folder(path)
    if folder is not None:
        folder.delete()
        return True
    return False
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_factory_removal.py -v`
Expected: `TestHubRemovalHelpers` all PASS.

- [ ] **Step 5: Full suite green, then commit**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests`
Expected: OK (692 existing + 6 new).

```bash
git add OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/hub.py \
        OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/removal.py \
        OWIsMind_PRD_V1_3_DEV/tests/test_factory_removal.py
git commit -m "feat(removal): hub capability disable/remove + library path helpers"
```

---

### Task 2: removal.py safe_delete + probes delegation

**Files:**
- Modify: `OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/removal.py`
- Modify: `OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/probes.py:30-49`
- Test: `OWIsMind_PRD_V1_3_DEV/tests/test_factory_removal.py`

**Interfaces:**
- Produces: `removal.RemovalRefused(RuntimeError)`, `removal.safe_delete(handle, expected_name, getter, noun="object", hint="", deleter=None)`. Tasks 4 consumes; probes.py delegates to it with EXACTLY its historical messages preserved (noun `"probe object"`, hint `", clean zz_* by hand"`).

- [ ] **Step 1: Add the safe_delete tests**

Append to `test_factory_removal.py`:

```python
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
```

- [ ] **Step 2: Run, verify failure**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_factory_removal.py -v`
Expected: FAIL with `AttributeError: ... 'safe_delete'`.

- [ ] **Step 3: Implement safe_delete in removal.py**

Replace the placeholder `removal.py` content with:

```python
"""Capability removal: probe-based inventory + safe deletion executors.

The guided REMOVAL run (guided.py) deletes everything a capability owns, one
confirmed stage at a time. This module owns the two delicate halves:

- ``build_inventory``: resolve what the capability ACTUALLY owns by probing
  DSS (capability entry + naming conventions + live listings). Nothing is
  assumed from conventions alone: an object enters the inventory only when
  its existence is CONFIRMED. The SOURCE dataset (entry ``lookup_dataset``)
  is listed as PROTECTED and never deletable (user decision 2026-07-22).
- the deletion executors: delete one stage's objects with the identity gate
  (re-read the live name, match it, only then delete), verify disappearance
  by read-back, and report objects the API refused so the guided stage can
  flip to manual instructions.

No persistence and no HTTP here; guided.py drives and persists.
"""

import json

from . import hub

# Stage keys carrying deletable inventory items. catalog_cleanup and
# hub_cleanup have dedicated executors and are not item-based.
DELETE_STAGE_KEYS = ("delete_tool", "delete_agent", "delete_model",
                     "delete_scenario", "delete_recipes", "delete_datasets",
                     "delete_zone")


class RemovalRefused(RuntimeError):
    """The identity/safety gate refused a deletion (never a DSS API error)."""


def safe_delete(handle, expected_name, getter, noun="object", hint="", deleter=None):
    """Delete ``handle`` ONLY after re-reading its live name and matching it.

    Pattern extracted from probes.py (the factory's historical single deletion
    site): a wrong handle must never delete a real object. ``deleter`` lets a
    caller pass extra flags (e.g. ``delete(drop_data=True)`` for datasets).
    """
    live_name = None
    try:
        live_name = getter()
    except Exception:
        pass
    if live_name is None:
        # FAIL-CLOSED: no proof the handle still points at the expected
        # object, so the deletion must not happen.
        raise RemovalRefused(
            "could not re-read the live name of the %s (expected %r): "
            "refusing to delete%s" % (noun, expected_name, hint))
    if live_name != expected_name:
        raise RemovalRefused("refusing to delete %r: expected %s %r"
                             % (live_name, noun, expected_name))
    if deleter is not None:
        deleter()
    else:
        handle.delete()
```

- [ ] **Step 4: Delegate probes._delete_probe_object to safe_delete**

In `probes.py`, replace the BODY of `_delete_probe_object` (keep its docstring, lines 30-49):

```python
def _delete_probe_object(handle, expected_name, getter):
    """Delete a probe object ONLY after re-reading its name and matching it
    against the probe constant (defense in depth around the factory's single
    deletion site: a wrong handle must never delete a real object)."""
    from .removal import safe_delete
    safe_delete(handle, expected_name, getter,
                noun="probe object", hint=", clean zz_* by hand")
```

`RemovalRefused` subclasses `RuntimeError`, so existing `except RuntimeError` / message assertions in probe tests keep passing (the noun/hint parameters reproduce the historical wording byte for byte).

- [ ] **Step 5: Run removal tests AND the probe tests**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_factory_removal.py -v`
Expected: PASS.
Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests`
Expected: OK, zero regression (the probe suite exercises `_delete_probe_object`).

- [ ] **Step 6: Commit**

```bash
git add OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/removal.py \
        OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/probes.py \
        OWIsMind_PRD_V1_3_DEV/tests/test_factory_removal.py
git commit -m "feat(removal): safe_delete identity gate, probes delegate to it"
```

---

### Task 3: removal.py probe-based inventory

**Files:**
- Modify: `OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/removal.py`
- Test: `OWIsMind_PRD_V1_3_DEV/tests/test_factory_removal.py`

**Interfaces:**
- Consumes: `flow_builder.dataset_exists/recipe_exists/scenario_id_by_name/_zone_by_name`, `tool_builder.tool_exists/describe_existing_tool`, `semantic_builder.find_model_by_name`, `spec.DomainSpec`.
- Produces: `removal.build_inventory(project, capability_key, entry, settings) -> (inventory, problems)` where inventory = `{"stages": {stage_key: [item]}, "protected": [item], "notes": [str], "template_conflicts": [str], "capability_key": str, "domain": str, "hub_paths": [str], "catalog": {"dataset": str, "capability_key": str}}` and item = `{"kind_fr", "name", "id", "where_fr", "note_fr"}`. Also `removal.agent_name_by_id / tool_name_by_id / model_name_by_id` (raise `flow_builder.ExistenceCheckError` on listing failure). Task 5 consumes.

- [ ] **Step 1: Add the inventory tests**

Append to `test_factory_removal.py`:

```python
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
```

- [ ] **Step 2: Run, verify failure**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_factory_removal.py -v`
Expected: FAIL with `AttributeError: ... 'build_inventory'`.

- [ ] **Step 3: Implement the inventory in removal.py**

Append to `removal.py`:

```python
# ------------------------------------------------------------------ inventory

def _item(kind_fr, name, where_fr, obj_id="", note_fr=""):
    return {"kind_fr": kind_fr, "name": str(name or ""), "id": str(obj_id or ""),
            "where_fr": where_fr, "note_fr": note_fr}


def conventional_spec(entry):
    """Best-effort DomainSpec derived from a capability entry (None when the
    entry cannot yield a legal spec, e.g. exotic founder fields)."""
    from .spec import DomainSpec, SpecError
    try:
        return DomainSpec(domain=entry.get("domain"),
                          base_dataset=entry.get("lookup_dataset"),
                          label_fr=entry.get("label_fr") or "domaine",
                          label_en=entry.get("label_en") or "domain")
    except SpecError:
        return None


def _listed_name_by_id(items, wanted_id):
    for item in items:
        item_id = item.id if hasattr(item, "id") else item.get("id")
        if item_id == wanted_id:
            return item.name if hasattr(item, "name") else item.get("name")
    return None


def agent_name_by_id(project, agent_id):
    from .flow_builder import ExistenceCheckError
    try:
        return _listed_name_by_id(project.list_agents(), agent_id)
    except Exception as exc:
        raise ExistenceCheckError("could not list agents: %s" % exc)


def tool_name_by_id(project, tool_id):
    from .flow_builder import ExistenceCheckError
    try:
        return _listed_name_by_id(project.list_agent_tools(), tool_id)
    except Exception as exc:
        raise ExistenceCheckError("could not list agent tools: %s" % exc)


def model_name_by_id(project, model_id):
    from .flow_builder import ExistenceCheckError
    try:
        return _listed_name_by_id(project.list_semantic_models(), model_id)
    except Exception as exc:
        raise ExistenceCheckError("could not list semantic models: %s" % exc)


def resolve_model(project, spec, tool_id):
    """(model_id, model_name): convention name first, then the tool's params
    (founder models predate the naming conventions; their semantic-query tool
    knows the real model id)."""
    from . import semantic_builder, tool_builder
    if spec is not None:
        model = semantic_builder.find_model_by_name(project, spec.semantic_model_name)
        if model is not None:
            model_id = getattr(model, "id", None) or getattr(model, "semantic_model_id", None)
            if model_id:
                return model_id, spec.semantic_model_name
    if tool_id:
        try:
            info = tool_builder.describe_existing_tool(project, tool_id)
            blob = json.dumps(info.get("params") or {})
            for item in project.list_semantic_models():
                item_id = item.id if hasattr(item, "id") else item.get("id")
                if item_id and str(item_id) in blob:
                    name = item.name if hasattr(item, "name") else item.get("name")
                    return item_id, name
        except Exception:
            pass
    return None, None


def hub_paths(entry, spec, agent_name):
    """Hub files/folders the domain owns (existence re-checked at cleanup)."""
    domain = str(entry.get("domain") or "")
    file_agent = (spec.agent_name if spec is not None else "") or agent_name or ""
    paths = ["%s/wizard/%s-config.json" % (hub.HUB_ROOT, domain),
             "%s/prompts/%s" % (hub.HUB_ROOT, domain)]
    if file_agent:
        paths.append("%s/generated/%s.py" % (hub.HUB_ROOT, file_agent))
    return paths


def template_conflicts(settings, stages):
    """French warnings when the domain's objects serve as factory templates."""
    conflicts = []
    settings = settings or {}
    tool_ids = [i["id"] for i in stages.get("delete_tool", [])]
    model_ids = [i["id"] for i in stages.get("delete_model", [])]
    recipe_names = [i["name"] for i in stages.get("delete_recipes", [])]
    template_tool = str(settings.get("template_semantic_tool_id") or "")
    template_model = str(settings.get("template_semantic_model_id") or "")
    if template_tool and template_tool in tool_ids:
        conflicts.append(
            "le tool %s est le TEMPLATE tool de l'usine "
            "(factory_settings.json : template_semantic_tool_id)" % template_tool)
    if template_model and template_model in model_ids:
        conflicts.append(
            "le modèle %s est le TEMPLATE de modèle sémantique de l'usine "
            "(factory_settings.json : template_semantic_model_id)" % template_model)
    for label, recipe in sorted((settings.get("template_zone_recipes") or {}).items()):
        if recipe in recipe_names:
            conflicts.append(
                "la recette %s est la recette TEMPLATE %r de l'usine "
                "(factory_settings.json : template_zone_recipes)" % (recipe, label))
    return conflicts


def build_inventory(project, capability_key, entry, settings):
    """Probe what the capability ACTUALLY owns. Returns (inventory, problems).

    problems non-empty means a LISTING failed: the inventory is partial and
    the caller must fail its stage (deleting on a partial inventory is
    forbidden). Absent candidates never enter ``stages``; they land in
    ``notes`` so the operator sees "déjà absent" instead of a silent hole.
    """
    from . import flow_builder, tool_builder
    from .catalog import CATALOG_DATASET_NAME
    from .flow_builder import ExistenceCheckError

    problems, notes = [], []
    stages = {key: [] for key in DELETE_STAGE_KEYS}
    spec = conventional_spec(entry)
    domain = str(entry.get("domain") or "")
    base_dataset = str(entry.get("lookup_dataset") or "")
    zone_name = spec.zone_name if spec is not None else ""
    where_flow = "Flow%s" % ((", zone %s" % zone_name) if zone_name else "")

    # Tool (the <domain>_semantic_query convention holds for founders too).
    tool_name = "%s_semantic_query" % domain
    tool_id = None
    try:
        tool_id = tool_builder.tool_exists(project, tool_name)
    except ExistenceCheckError as exc:
        problems.append("Impossible de lister les tools (%s) : réessaie." % exc)
    if tool_id:
        stages["delete_tool"].append(_item(
            "Tool Semantic Model Query", tool_name,
            "Agents & GenAI Models > Tools", tool_id))
    else:
        notes.append("Tool %s : déjà absent." % tool_name)

    # Code Agent (id from the entry, live name from the listing).
    agent_ref = str(entry.get("agent_id") or "")
    agent_id = agent_ref.split(":", 1)[1] if ":" in agent_ref else agent_ref
    agent_name = None
    if agent_id:
        try:
            agent_name = agent_name_by_id(project, agent_id)
        except ExistenceCheckError as exc:
            problems.append("Impossible de lister les agents (%s) : réessaie." % exc)
    if agent_name:
        stages["delete_agent"].append(_item(
            "Code Agent", agent_name, "Agents & GenAI Models > Agents", agent_id))
    else:
        notes.append("Code Agent %s : déjà absent." % (agent_id or "(id inconnu)"))

    # Semantic model (convention name, else resolved through the tool params).
    model_id, model_name = resolve_model(project, spec, tool_id)
    if model_id:
        stages["delete_model"].append(_item(
            "Modèle sémantique", model_name or model_id,
            "Agents & GenAI Models > Semantic models", model_id))
    else:
        notes.append("Modèle sémantique : introuvable (déjà absent, ou nom hors "
                     "convention sans tool pour le retrouver).")

    # Refresh scenario (Refresh_<Domain> convention).
    if spec is not None:
        scenario_id = None
        try:
            scenario_id = flow_builder.scenario_id_by_name(project, spec.scenario_name)
        except ExistenceCheckError as exc:
            problems.append("Impossible de lister les scénarios (%s) : réessaie." % exc)
        if scenario_id:
            stages["delete_scenario"].append(_item(
                "Scénario", spec.scenario_name, "Scenarios", scenario_id))
        else:
            notes.append("Scénario %s : déjà absent." % spec.scenario_name)

    # Knowledge datasets: profile + value_index by convention, catalog from the
    # entry (it carries the REAL name, founders included). The SOURCE dataset
    # (lookup_dataset) is PROTECTED: never deletable (user decision 2026-07-22).
    candidates = []
    if spec is not None:
        candidates = [spec.profile_dataset, spec.value_index_dataset]
    lookup_catalog = str(entry.get("lookup_catalog") or "")
    if lookup_catalog and lookup_catalog not in candidates:
        candidates.append(lookup_catalog)
    for name in candidates:
        if name == base_dataset:
            continue  # belt and braces: the source is never a candidate
        try:
            found = flow_builder.dataset_exists(project, name)
        except ExistenceCheckError as exc:
            problems.append("Impossible de lister les datasets (%s) : réessaie." % exc)
            continue
        if found:
            stages["delete_datasets"].append(_item(
                "Dataset de connaissance", name, where_flow,
                note_fr="sa table SQL dérivée sera supprimée (reconstructible)"))
            recipe = "compute_%s" % name
            try:
                if flow_builder.recipe_exists(project, recipe):
                    stages["delete_recipes"].append(_item(
                        "Recette Python", recipe, where_flow))
                else:
                    notes.append("Recette %s : déjà absente." % recipe)
            except ExistenceCheckError as exc:
                problems.append("Impossible de lister les recettes (%s) : réessaie." % exc)
        else:
            notes.append("Dataset %s : déjà absent." % name)

    # Flow zone (deleted only if EMPTY at its stage's turn).
    if zone_name:
        zone = None
        try:
            zone = flow_builder._zone_by_name(project.get_flow(), zone_name)
        except Exception:
            zone = None
        if zone is not None:
            stages["delete_zone"].append(_item(
                "Zone du Flow", zone_name, "Flow",
                note_fr="supprimée SEULEMENT si vide (le dataset source, jamais "
                        "touché, peut la garder en vie)"))
        else:
            notes.append("Zone %s : déjà absente." % zone_name)

    protected = []
    if base_dataset:
        protected.append(_item("Dataset SOURCE (protégé)", base_dataset, "Flow",
                               note_fr="JAMAIS supprimé par ce run"))

    inventory = {
        "stages": stages,
        "protected": protected,
        "notes": notes,
        "template_conflicts": template_conflicts(settings, stages),
        "capability_key": capability_key,
        "domain": domain,
        "hub_paths": hub_paths(entry, spec, agent_name),
        "catalog": {"dataset": CATALOG_DATASET_NAME, "capability_key": capability_key},
    }
    return inventory, problems
```

- [ ] **Step 4: Run, verify pass, commit**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_factory_removal.py -v`
Expected: PASS.

```bash
git add OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/removal.py \
        OWIsMind_PRD_V1_3_DEV/tests/test_factory_removal.py
git commit -m "feat(removal): probe-based capability inventory (source dataset protected)"
```

---

### Task 4: removal.py deletion executors + verification + catalog/hub cleanup

**Files:**
- Modify: `OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/removal.py`
- Test: `OWIsMind_PRD_V1_3_DEV/tests/test_factory_removal.py`

**Interfaces:**
- Consumes: Task 1 hub helpers, Task 2 `safe_delete`, Task 3 resolvers, `guided_store.quote_table/_sql_value`, `wizard.get_physical_table`, `fctx` action methods (`ctx.act/done/skip/fail`).
- Produces (Task 5 consumes):
  - `removal.execute_delete_stage(project, stage_key, items, ctx) -> (manual_items, problems)` (manual item = inventory item + `reason_fr`);
  - `removal.verify_stage_absent(project, stage_key, items) -> (leftovers, problems)`;
  - `removal.scenario_is_running(project, scenario_id) -> True | False | None`;
  - `removal.delete_catalog_rows(project, connection, capability_key, executor_factory=None) -> "deleted" | "no_dataset" | "unknown_table"`;
  - `removal.cleanup_hub(project, capability_key, paths, ctx) -> (manual_paths, capability_status)` with manual_paths = `[{"path", "reason_fr"}]` and capability_status from `hub.remove_capability`.

- [ ] **Step 1: Add the executor tests**

Append to `test_factory_removal.py`:

```python
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
```

- [ ] **Step 2: Run, verify failure**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_factory_removal.py -v`
Expected: FAIL with `AttributeError: ... 'execute_delete_stage'`.

- [ ] **Step 3: Implement the executors in removal.py**

Append to `removal.py`:

```python
# ------------------------------------------------------------------ executors

def scenario_is_running(project, scenario_id):
    """True/False when provable, None when unknown (never a verdict)."""
    try:
        return project.get_scenario(scenario_id).get_current_run() is not None
    except Exception:
        return None


def _delete_tool_item(project, item):
    from . import tool_builder
    if not tool_builder.tool_exists(project, item["name"]):
        return "absent"
    handle = project.get_agent_tool(item["id"])
    safe_delete(handle, item["name"],
                lambda: tool_name_by_id(project, item["id"]), noun="tool")
    return "deleted" if not tool_builder.tool_exists(project, item["name"]) \
        else "still_there"


def _delete_agent_item(project, item):
    if agent_name_by_id(project, item["id"]) is None:
        return "absent"
    handle = project.get_agent(item["id"])
    safe_delete(handle, item["name"],
                lambda: agent_name_by_id(project, item["id"]), noun="agent")
    return "deleted" if agent_name_by_id(project, item["id"]) is None \
        else "still_there"


def _delete_model_item(project, item):
    if model_name_by_id(project, item["id"]) is None:
        return "absent"
    handle = project.get_semantic_model(item["id"])
    safe_delete(handle, item["name"],
                lambda: model_name_by_id(project, item["id"]),
                noun="semantic model")
    return "deleted" if model_name_by_id(project, item["id"]) is None \
        else "still_there"


def _delete_scenario_item(project, item):
    from . import flow_builder
    if flow_builder.scenario_id_by_name(project, item["name"]) is None:
        return "absent"
    if scenario_is_running(project, item["id"]) is True:
        raise RemovalRefused("le scénario tourne en ce moment : attends la fin "
                             "de son run avant de le supprimer")
    handle = project.get_scenario(item["id"])

    def _live_name():
        listed = flow_builder.scenario_id_by_name(project, item["name"])
        return item["name"] if listed == item["id"] else None

    safe_delete(handle, item["name"], _live_name, noun="scenario")
    return "deleted" \
        if flow_builder.scenario_id_by_name(project, item["name"]) is None \
        else "still_there"


def _delete_recipe_item(project, item):
    from . import flow_builder
    if not flow_builder.recipe_exists(project, item["name"]):
        return "absent"
    handle = project.get_recipe(item["name"])
    safe_delete(handle, item["name"],
                lambda: item["name"]
                if flow_builder.recipe_exists(project, item["name"]) else None,
                noun="recipe")
    return "deleted" if not flow_builder.recipe_exists(project, item["name"]) \
        else "still_there"


def _delete_dataset_item(project, item):
    from . import flow_builder
    if not flow_builder.dataset_exists(project, item["name"]):
        return "absent"
    handle = project.get_dataset(item["name"])
    safe_delete(handle, item["name"],
                lambda: item["name"]
                if flow_builder.dataset_exists(project, item["name"]) else None,
                noun="dataset",
                deleter=lambda: handle.delete(drop_data=True))
    return "deleted" if not flow_builder.dataset_exists(project, item["name"]) \
        else "still_there"


def _delete_zone_item(project, item):
    from . import flow_builder
    zone = flow_builder._zone_by_name(project.get_flow(), item["name"])
    if zone is None:
        return "absent"
    contents = getattr(zone, "items", None)
    if contents is None:
        raise RemovalRefused("impossible de lire le contenu de la zone : "
                             "vide-la et supprime-la à la main si tu la veux partie")
    if len(contents) > 0:
        return "kept"
    zone.delete()
    return "deleted" \
        if flow_builder._zone_by_name(project.get_flow(), item["name"]) is None \
        else "still_there"


_STAGE_EXECUTORS = {
    "delete_tool": _delete_tool_item,
    "delete_agent": _delete_agent_item,
    "delete_model": _delete_model_item,
    "delete_scenario": _delete_scenario_item,
    "delete_recipes": _delete_recipe_item,
    "delete_datasets": _delete_dataset_item,
    "delete_zone": _delete_zone_item,
}


def execute_delete_stage(project, stage_key, items, ctx):
    """Delete one stage's confirmed items. Returns (manual_items, problems).

    - already-absent items are journaled and skipped (idempotent relaunch);
    - a deletion the API (or the identity gate) refuses lands in manual_items:
      the guided stage flips to manual instructions;
    - a deletion that seems to succeed but whose object is STILL listed after
      is a problem: never advance on an unverified deletion.
    """
    executor = _STAGE_EXECUTORS[stage_key]
    manual, problems = [], []
    for item in items:
        try:
            status = executor(project, item)
        except Exception as exc:  # noqa: BLE001 refusal -> manual fallback
            manual.append(dict(item, reason_fr=str(exc)[:200]))
            ctx.skip(stage_key, "%s %s: refused (%s), manual fallback"
                     % (item["kind_fr"], item["name"], exc))
            continue
        if status == "absent":
            ctx.skip(stage_key, "%s %s already absent"
                     % (item["kind_fr"], item["name"]))
        elif status == "deleted":
            ctx.done(stage_key, "deleted %s %s (verified absent)"
                     % (item["kind_fr"], item["name"]))
        elif status == "kept":
            ctx.skip(stage_key, "%s %s kept (not empty)"
                     % (item["kind_fr"], item["name"]))
        else:
            problems.append("%s %s toujours présent après la suppression : "
                            "réessaie." % (item["kind_fr"], item["name"]))
    return manual, problems


# --------------------------------------------------------------- verification

def _tool_leftover(project, item):
    from . import tool_builder
    return bool(tool_builder.tool_exists(project, item["name"]))


def _agent_leftover(project, item):
    return agent_name_by_id(project, item["id"]) is not None


def _model_leftover(project, item):
    return model_name_by_id(project, item["id"]) is not None


def _scenario_leftover(project, item):
    from . import flow_builder
    return flow_builder.scenario_id_by_name(project, item["name"]) is not None


def _recipe_leftover(project, item):
    from . import flow_builder
    return flow_builder.recipe_exists(project, item["name"])


def _dataset_leftover(project, item):
    from . import flow_builder
    return flow_builder.dataset_exists(project, item["name"])


def _zone_leftover(project, item):
    """A zone kept because it is NOT empty is a decision, not a leftover."""
    from . import flow_builder
    zone = flow_builder._zone_by_name(project.get_flow(), item["name"])
    if zone is None:
        return False
    contents = getattr(zone, "items", None) or []
    return len(contents) == 0


_STAGE_LEFTOVER_CHECKS = {
    "delete_tool": _tool_leftover,
    "delete_agent": _agent_leftover,
    "delete_model": _model_leftover,
    "delete_scenario": _scenario_leftover,
    "delete_recipes": _recipe_leftover,
    "delete_datasets": _dataset_leftover,
    "delete_zone": _zone_leftover,
}


def verify_stage_absent(project, stage_key, items):
    """Re-probe one stage's items. Returns (leftovers, problems)."""
    check = _STAGE_LEFTOVER_CHECKS[stage_key]
    leftovers, problems = [], []
    for item in items:
        try:
            if check(project, item):
                leftovers.append(item)
        except Exception as exc:  # noqa: BLE001 listing error -> retryable
            problems.append("Vérification impossible pour %s %s (%s) : réessaie."
                            % (item["kind_fr"], item["name"], exc))
    return leftovers, problems


# ------------------------------------------------------- catalog + hub cleanup

def delete_catalog_rows(project, connection, capability_key, executor_factory=None):
    """Parametrized DELETE of the capability's shared-catalog rows + COMMIT.

    Returns "deleted", "no_dataset" (nothing to clean) or "unknown_table"
    (physical table unreadable: surfaced as a note, cleanup by hand).
    """
    from . import flow_builder, guided_store, wizard
    from .catalog import CATALOG_DATASET_NAME
    try:
        if not flow_builder.dataset_exists(project, CATALOG_DATASET_NAME):
            return "no_dataset"
    except flow_builder.ExistenceCheckError:
        return "unknown_table"
    table = None
    try:
        table = wizard.get_physical_table(project, CATALOG_DATASET_NAME)
    except Exception:
        table = None
    if not table:
        return "unknown_table"
    statement = "DELETE FROM %s WHERE capability_key = %s" % (
        guided_store.quote_table(table), guided_store._sql_value(capability_key))
    if executor_factory is not None:
        executor = executor_factory()
    else:
        import dataiku
        executor = dataiku.SQLExecutor2(connection=connection)
    executor.query_to_df("SELECT 1 AS ok",
                         pre_queries=[statement], post_queries=["COMMIT"])
    return "deleted"


def cleanup_hub(project, capability_key, paths, ctx):
    """Delete the domain's hub files then its capabilities.json entry.

    Returns (manual_paths, capability_status): manual_paths lists files the
    API refused (guided flips to manual); capability_status comes from
    hub.remove_capability ("removed" / "kept_disabled" / "absent").
    """
    manual = []
    for path in paths:
        try:
            existed = hub.delete_path(project, path)
        except Exception as exc:  # noqa: BLE001 refusal -> manual fallback
            manual.append({"path": path, "reason_fr": str(exc)[:200]})
            ctx.skip("hub_cleanup", "%s: refused (%s), manual fallback" % (path, exc))
            continue
        if existed:
            ctx.done("hub_cleanup", "deleted %s" % path)
        else:
            ctx.skip("hub_cleanup", "%s already absent" % path)
    status, _caps = hub.remove_capability(project, capability_key)
    ctx.done("hub_cleanup", "capability entry %s: %s" % (capability_key, status))
    return manual, status
```

- [ ] **Step 4: Run, verify pass, commit**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_factory_removal.py -v`
Expected: PASS (all classes).

```bash
git add OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/removal.py \
        OWIsMind_PRD_V1_3_DEV/tests/test_factory_removal.py
git commit -m "feat(removal): deletion executors with verify-absence + catalog/hub cleanup"
```

---

### Task 5: guided.py removal machine

**Files:**
- Modify: `OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/guided.py`
- Test: `OWIsMind_PRD_V1_3_DEV/tests/test_factory_removal.py`

**Interfaces:**
- Consumes: everything Tasks 1-4 produced.
- Produces (Task 6 consumes): `guided.start_removal_run(project, capability_key, settings=None, executor_factory=None, run_id=None, ctx=None) -> run` (raises `ValueError("unknown capability: ...")`), `guided.is_removal(run) -> bool`, `guided.REMOVAL_STAGE_ORDER`. The removal marker lives in `state["removal"]` (NOT on the run dict: `guided_store` only persists `run_id/domain/status/current_stage/state_json`).

- [ ] **Step 1: Add the machine tests**

Append to `test_factory_removal.py`:

```python
class _StubSettings(dict):
    pass


def _machine_settings():
    s = dict(hub.DEFAULT_SETTINGS)
    s["sql_connection"] = "SQL_owi"
    return s


def _start_removal(project, key="opportunities_expert"):
    return guided.start_removal_run(project, key, settings=_machine_settings())


def _run_stage(project, run):
    return guided.run_current_stage(project, run, settings=_machine_settings())


def _verify_stage(project, run):
    return guided.verify_current_stage(project, run, settings=_machine_settings())


class TestRemovalMachine(unittest.TestCase):
    def setUp(self):
        self.project = _FakeProject()
        _seed_full_domain(self.project)
        _seed_capabilities(self.project, {
            "opportunities_expert": _entry(enabled=True),
            "revenue_expert": _entry(domain="revenue", agent_id="agent:bHrWLyOL",
                                     lookup_dataset="DRIVE_Revenues",
                                     lookup_catalog="DRIVE_Revenues_Value_Catalog"),
        })

    def test_start_builds_a_removal_run_and_runs_inventory(self):
        run = _start_removal(self.project)
        self.assertTrue(guided.is_removal(run))
        self.assertEqual(run["state"]["stage_order"], list(guided.REMOVAL_STAGE_ORDER))
        self.assertEqual(run["domain"], "opportunities")
        self.assertEqual(run["state"]["stages"]["inventory"]["status"], "done")
        self.assertEqual(run["current_stage"], "disable")
        inventory = run["state"]["removal"]["inventory"]
        self.assertTrue(inventory["stages"]["delete_tool"])

    def test_start_unknown_capability_raises(self):
        with self.assertRaises(ValueError):
            guided.start_removal_run(self.project, "nope",
                                     settings=_machine_settings())

    def test_orchestrator_capability_is_refused(self):
        caps = json.loads(self.project.library.files[hub.CAPABILITIES_PATH])
        caps["opportunities_expert"]["agent_id"] = "agent:038G7mlF"
        _seed_capabilities(self.project, caps)
        run = _start_removal(self.project)
        self.assertEqual(run["state"]["stages"]["inventory"]["status"], "failed")

    def test_start_refused_while_the_domain_scenario_runs(self):
        """Spec safety rail: never start a removal over a live refresh run."""
        self.project.scenario_running["sc1"] = {"running": True}
        run = _start_removal(self.project)
        stage = run["state"]["stages"]["inventory"]
        self.assertEqual(stage["status"], "failed")
        self.assertTrue(any("scénario" in p.lower() for p in stage["problems"]))

    def test_heal_interrupted_covers_removal_stages(self):
        run = _start_removal(self.project)
        run["state"]["stages"]["disable"]["status"] = "running"
        self.assertTrue(guided.heal_interrupted(run))
        self.assertEqual(run["state"]["stages"]["disable"]["status"], "failed")

    def test_inventory_waits_on_template_conflict_then_acknowledges(self):
        settings = _machine_settings()
        settings["template_semantic_tool_id"] = "iUR8wLX"
        run = guided.start_removal_run(self.project, "opportunities_expert",
                                       settings=settings)
        stage = run["state"]["stages"]["inventory"]
        self.assertEqual(stage["status"], "waiting_user")
        self.assertIn("TEMPLATE", stage["instructions_fr"])
        run = _verify_stage(self.project, run)
        self.assertEqual(run["state"]["stages"]["inventory"]["status"], "done")
        self.assertEqual(run["current_stage"], "disable")

    def test_inventory_writes_the_stage_cards(self):
        run = _start_removal(self.project)
        detail = run["state"]["stages"]["delete_tool"]["detail_fr"]
        self.assertIn("opportunities_semantic_query", detail)
        self.assertIn("iUR8wLX", detail)
        detail_ds = run["state"]["stages"]["delete_datasets"]["detail_fr"]
        self.assertIn("PROTÉGÉ", detail_ds)
        self.assertIn("DRIVE_Opportunities", detail_ds)

    def _advance_to(self, run, stage_key):
        while run["current_stage"] != stage_key:
            self.assertEqual(run["status"], "active")
            run = _run_stage(self.project, run)
            self.assertNotEqual(
                run["state"]["stages"][run["current_stage"]]["status"], "failed",
                "unexpected failure on %s: %s" % (
                    run["current_stage"],
                    run["state"]["stages"][run["current_stage"]]["problems"]))
        return run

    def test_disable_flips_the_flag_before_any_deletion(self):
        run = _start_removal(self.project)
        self.assertEqual(run["current_stage"], "disable")
        run = _run_stage(self.project, run)
        caps = json.loads(self.project.library.files[hub.CAPABILITIES_PATH])
        self.assertFalse(caps["opportunities_expert"]["enabled"])
        self.assertEqual(run["current_stage"], "delete_tool")
        self.assertEqual(self.project.deleted, [])

    def test_full_removal_walk_deletes_everything_and_completes(self):
        self.project.zones[0].items = []  # empty zone: deletable
        run = _start_removal(self.project)
        guard = 0
        while run["status"] == "active" and guard < 20:
            guard += 1
            stage = run["state"]["stages"][run["current_stage"]]
            self.assertIn(stage["status"], ("ready", "waiting_user"))
            if stage["status"] == "ready":
                run = _run_stage(self.project, run)
            else:
                run = _verify_stage(self.project, run)
        self.assertEqual(run["status"], "done")
        self.assertNotIn("iUR8wLX", self.project.tools)
        self.assertNotIn("4Ghpi5hm", self.project.agents)
        self.assertNotIn("mOdEl42", self.project.models)
        self.assertEqual(self.project.scenarios, {})
        self.assertNotIn("DRIVE_Opportunities_profile", self.project.datasets)
        self.assertIn("DRIVE_Opportunities", self.project.datasets)
        caps = json.loads(self.project.library.files[hub.CAPABILITIES_PATH])
        self.assertNotIn("opportunities_expert", caps)
        self.assertIn("revenue_expert", caps)

    def test_api_refusal_flips_stage_to_manual_then_verify_gates(self):
        self.project.fail_delete.add("agent")
        run = _start_removal(self.project)
        run = self._advance_to(run, "delete_agent")
        run = _run_stage(self.project, run)
        stage = run["state"]["stages"]["delete_agent"]
        self.assertEqual(stage["status"], "waiting_user")
        self.assertIn("à la main", stage["instructions_fr"])
        # "C'est fait" without the manual deletion: must NOT advance.
        run = _verify_stage(self.project, run)
        self.assertEqual(run["state"]["stages"]["delete_agent"]["status"],
                         "waiting_user")
        self.assertTrue(run["state"]["stages"]["delete_agent"]["problems"])
        # The operator deletes in DSS, then verifies: advances.
        self.project.agents.pop("4Ghpi5hm")
        run = _verify_stage(self.project, run)
        self.assertEqual(run["state"]["stages"]["delete_agent"]["status"], "done")

    def test_relaunch_after_partial_failure_is_idempotent(self):
        self.project.fail_delete.add("dataset")
        run = _start_removal(self.project)
        run = self._advance_to(run, "delete_datasets")
        run = _run_stage(self.project, run)
        self.assertEqual(run["state"]["stages"]["delete_datasets"]["status"],
                         "waiting_user")
        self.project.fail_delete.discard("dataset")
        # heal path: the operator deletes one by hand, the rest verify absent
        # after a relaunch of the stage through verify (manual gate).
        for name in ("DRIVE_Opportunities_profile",
                     "DRIVE_Opportunities_value_index",
                     "DRIVE_Opportunities_value_catalog"):
            self.project.datasets.discard(name)
        run = _verify_stage(self.project, run)
        self.assertEqual(run["state"]["stages"]["delete_datasets"]["status"], "done")

    def test_creation_run_still_works_untouched(self):
        """Anti-regression: the creation machine keeps its frozen contract."""
        self.assertEqual(guided.STAGE_ORDER[0], "preflight")
        state = guided.new_state(__import__(
            "owismind_factory.spec", fromlist=["DomainSpec"]).DomainSpec(
                domain="x_domain", base_dataset="X_Base",
                label_fr="X", label_en="X"))
        self.assertNotIn("removal", state)
        self.assertEqual(state["stage_order"], list(guided.STAGE_ORDER))
```

- [ ] **Step 2: Run, verify failure**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_factory_removal.py -v`
Expected: FAIL with `AttributeError: ... 'start_removal_run'`.

- [ ] **Step 3: Implement the removal machine in guided.py**

3a. Import the module: line 29-31 block gains `removal`:

```python
from . import agent_builder, flow_builder, hub, pipeline, registry, removal, semantic_builder
```

3b. After the creation `_STAGE_META` (line 93), add the removal order + meta:

```python
# ----------------------------------------------------------- REMOVAL run type
# A removal run walks the operator through deleting everything one capability
# owns, one CONFIRMED stage at a time (spec 2026-07-22). Safety order: detach
# first (disable), then leaves before trunks. The marker lives in
# state["removal"] because guided_store only persists the state_json.

REMOVAL_STAGE_ORDER = [
    "inventory", "disable", "delete_tool", "delete_agent", "delete_model",
    "delete_scenario", "delete_recipes", "delete_datasets", "delete_zone",
    "catalog_cleanup", "hub_cleanup", "final_check",
]

_REMOVAL_STAGE_META = {
    "inventory": ("auto", "Inventaire de la capacité",
                  "Sonde ce qui existe réellement (datasets, recettes, scénario, "
                  "modèle, tool, agent, hub). Rien n'est supprimé à cette étape."),
    "disable": ("auto", "Désactivation de la capability",
                "Coupe le routage de l'orchestrateur vers cet expert avant toute "
                "suppression."),
    "delete_tool": ("auto", "Suppression du tool",
                    "Supprime le tool Semantic Model Query du domaine."),
    "delete_agent": ("auto", "Suppression du Code Agent",
                     "Supprime le Code Agent du domaine."),
    "delete_model": ("auto", "Suppression du modèle sémantique",
                     "Supprime le modèle sémantique du domaine."),
    "delete_scenario": ("auto", "Suppression du scénario",
                        "Supprime le scénario de refresh du domaine."),
    "delete_recipes": ("auto", "Suppression des recettes",
                       "Supprime les recettes de connaissance du domaine."),
    "delete_datasets": ("auto", "Suppression des datasets de connaissance",
                        "Supprime les datasets dérivés et leurs tables SQL "
                        "(reconstructibles). Le dataset SOURCE n'est JAMAIS touché."),
    "delete_zone": ("auto", "Suppression de la zone Flow",
                    "Supprime la zone du domaine si elle est vide, sinon la "
                    "laisse en place."),
    "catalog_cleanup": ("auto", "Nettoyage du catalogue partagé",
                        "Supprime les lignes de cette capability dans le dataset "
                        "catalogue commun (SQL paramétré + COMMIT)."),
    "hub_cleanup": ("auto", "Nettoyage du hub",
                    "Supprime la config wizard, les prompts, le code généré, puis "
                    "l'entrée de capabilities.json (backup automatique)."),
    "final_check": ("auto", "Vérification finale",
                    "Re-sonde l'absence de tout et rappelle le re-save de "
                    "l'orchestrateur."),
}

_ALL_STAGE_META = dict(_STAGE_META)
_ALL_STAGE_META.update(_REMOVAL_STAGE_META)
```

3c. In `heal_interrupted` (line 933), replace `_STAGE_META[key]` with `_ALL_STAGE_META[key]`.

3d. After the creation stage functions (after `_precheck_wizard`, line 709), add the removal stage handlers:

```python
# ------------------------------------------------------------ removal stages

def _removal_info(state):
    return state.get("removal") or {}


def _removal_items(state, stage_key):
    inventory = _removal_info(state).get("inventory") or {}
    return (inventory.get("stages") or {}).get(stage_key) or []


def _apply_removal_inventory_cards(state):
    """Rewrite each deletion stage's card so the operator sees EXACTLY what a
    confirmed click will delete (kind, name, id, location) BEFORE launching."""
    inventory = _removal_info(state).get("inventory") or {}
    for stage_key in removal.DELETE_STAGE_KEYS:
        entry = state["stages"].get(stage_key)
        if not entry:
            continue
        _kind, _title, base_detail = _REMOVAL_STAGE_META[stage_key]
        items = (inventory.get("stages") or {}).get(stage_key) or []
        if not items:
            entry["detail_fr"] = base_detail + "\nRien à supprimer : déjà absent."
            continue
        lines = [base_detail]
        for item in items:
            line = "SUPPRIMER : %s %s" % (item["kind_fr"], item["name"])
            if item.get("id"):
                line += " [id %s]" % item["id"]
            line += " (%s)" % item["where_fr"]
            lines.append(line)
            if item.get("note_fr"):
                lines.append("  " + item["note_fr"])
        entry["detail_fr"] = "\n".join(lines)
    protected = inventory.get("protected") or []
    if protected and state["stages"].get("delete_datasets"):
        for item in protected:
            state["stages"]["delete_datasets"]["detail_fr"] += (
                "\nPROTÉGÉ (jamais supprimé) : %s" % item["name"])


def _run_removal_inventory(env, state, ctx):
    info = state["removal"]
    key = info.get("capability_key")
    caps = hub.read_capabilities(env.project) or {}
    entry = caps.get(key) or info.get("entry") or {}
    info["entry"] = entry
    orchestrator_id = str(env.settings.get("orchestrator_agent_id") or "").strip()
    if orchestrator_id and str(entry.get("agent_id") or "") == "agent:%s" % orchestrator_id:
        return _OUT_FAILED, ["Cette capability pointe l'orchestrateur lui-même : "
                             "suppression refusée."]
    inventory, problems = removal.build_inventory(env.project, key, entry,
                                                  env.settings)
    info["inventory"] = inventory
    _apply_removal_inventory_cards(state)
    for note in inventory.get("notes") or []:
        ctx.skip("inventory", note)
    for stage_key in removal.DELETE_STAGE_KEYS:
        for item in (inventory.get("stages") or {}).get(stage_key) or []:
            ctx.done("inventory", "à supprimer (%s) : %s %s"
                     % (stage_key, item["kind_fr"], item["name"]))
    # Spec safety rail: never start a removal over a live refresh run.
    for item in (inventory.get("stages") or {}).get("delete_scenario") or []:
        if removal.scenario_is_running(env.project, item["id"]) is True:
            problems.append("Le scénario %s est en cours d'exécution : attends "
                            "la fin de son run puis relance cette étape."
                            % item["name"])
    if problems:
        return _OUT_FAILED, problems
    if inventory.get("template_conflicts"):
        return _OUT_WAITING, []
    return _OUT_DONE, []


def _check_removal_inventory(env, state):
    # The "C'est fait" click IS the acknowledgment of the template conflicts.
    return True, []


def _instr_removal_inventory(env, state):
    conflicts = (_removal_info(state).get("inventory") or {}) \
        .get("template_conflicts") or []
    lines = ["ATTENTION : des objets de ce domaine servent de TEMPLATES à l'usine :"]
    lines += ["- %s" % c for c in conflicts]
    lines.append(
        "Tant que ces templates ne seront pas repointés dans factory_settings.json "
        "(project library), l'usine ne pourra PLUS créer de nouveau domaine. La "
        "suppression reste possible : clique sur C'est fait pour acquitter et "
        "continuer.")
    return "\n".join(lines)


def _run_removal_disable(env, state, ctx):
    key = _removal_info(state).get("capability_key")
    caps = hub.read_capabilities(env.project) or {}
    entry = caps.get(key)
    if entry is None:
        ctx.skip("disable", "capability %s already gone from the hub" % key)
        return _OUT_DONE, []
    if not entry.get("enabled"):
        ctx.skip("disable", "capability %s already disabled" % key)
        return _OUT_DONE, []

    def _write():
        hub.set_capability_enabled(env.project, key, False)
        return True

    try:
        result = ctx.act("disable",
                         "disable capability %s (the orchestrator stops routing "
                         "to this expert)" % key, _write)
    except (KeyError, ValueError) as exc:
        return _OUT_FAILED, [str(exc)]
    if not result:
        failures = [a for a in ctx.actions
                    if a["status"] == FAILED and a["step"] == "disable"]
        return _OUT_FAILED, [a["detail"][:300] for a in failures] or \
            ["Désactivation impossible (voir le journal)."]
    return _OUT_DONE, []


def _make_removal_delete_runner(stage_key):
    def _run(env, state, ctx):
        items = _removal_items(state, stage_key)
        if not items:
            ctx.skip(stage_key, "rien à supprimer pour cette étape")
            return _OUT_DONE, []
        manual, problems = removal.execute_delete_stage(
            env.project, stage_key, items, ctx)
        _removal_info(state).setdefault("manual", {})[stage_key] = manual
        if problems:
            return _OUT_FAILED, problems
        if manual:
            return _OUT_WAITING, []
        return _OUT_DONE, []
    return _run


def _make_removal_absent_checker(stage_key):
    def _check(env, state):
        items = _removal_items(state, stage_key)
        leftovers, problems = removal.verify_stage_absent(
            env.project, stage_key, items)
        if problems:
            return False, problems
        if leftovers:
            return False, ["Toujours présent dans DSS : %s. Supprime puis "
                           "re-vérifie." % ", ".join(i["name"] for i in leftovers)]
        return True, []
    return _check


def _make_instr_removal_manual(stage_key):
    def _instr(env, state):
        manual = (_removal_info(state).get("manual") or {}).get(stage_key) or []
        lines = ["La suppression automatique a été refusée pour :"]
        for item in manual:
            line = "- %s %s (%s)" % (item.get("kind_fr", "objet"),
                                     item.get("name", "?"),
                                     item.get("where_fr", "DSS"))
            if item.get("reason_fr"):
                line += " : " + item["reason_fr"]
            lines.append(line)
        lines.append("Supprime ces objets à la main dans DSS, puis clique sur "
                     "C'est fait : je vérifie leur absence avant de continuer.")
        return "\n".join(lines)
    return _instr


def _run_removal_catalog(env, state, ctx):
    key = _removal_info(state).get("capability_key")
    connection = env.settings.get("sql_connection") or "SQL_owi"

    def _clean():
        return removal.delete_catalog_rows(
            env.project, connection, key, executor_factory=env.executor_factory)

    status = ctx.act("catalog_cleanup",
                     "delete shared-catalog rows of capability %s "
                     "(parametrized SQL + COMMIT)" % key, _clean)
    if status is None:
        failures = [a for a in ctx.actions
                    if a["status"] == FAILED and a["step"] == "catalog_cleanup"]
        return _OUT_FAILED, [a["detail"][:300] for a in failures] or \
            ["Nettoyage du catalogue impossible (voir le journal)."]
    if status == "no_dataset":
        ctx.skip("catalog_cleanup", "no shared catalog dataset: nothing to clean")
    elif status == "unknown_table":
        ctx.skip("catalog_cleanup",
                 "table physique du catalogue illisible : supprime les lignes "
                 "capability_key=%s à la main si besoin" % key)
    return _OUT_DONE, []


def _run_removal_hub(env, state, ctx):
    info = _removal_info(state)
    key = info.get("capability_key")
    paths = (info.get("inventory") or {}).get("hub_paths") or []
    try:
        manual, status = removal.cleanup_hub(env.project, key, paths, ctx)
    except ValueError as exc:
        return _OUT_FAILED, [str(exc)]
    info.setdefault("manual", {})["hub_cleanup"] = [
        {"kind_fr": "Fichier du hub", "name": m["path"],
         "where_fr": "project library", "reason_fr": m.get("reason_fr", ""),
         "id": "", "note_fr": ""}
        for m in manual]
    info["capability_entry_status"] = status
    if status == "kept_disabled":
        ctx.skip("hub_cleanup",
                 "dernière capability du registre : l'entrée est conservée "
                 "DÉSACTIVÉE (un capabilities.json vide ferait retomber "
                 "l'orchestrateur sur ses valeurs embarquées)")
    if manual:
        return _OUT_WAITING, []
    return _OUT_DONE, []


def _check_removal_hub(env, state):
    info = _removal_info(state)
    paths = (info.get("inventory") or {}).get("hub_paths") or []
    leftovers = [p for p in paths if hub.path_exists(env.project, p) is True]
    if leftovers:
        return False, ["Toujours présent dans la project library : %s"
                       % ", ".join(leftovers)]
    return True, []


def _run_removal_final(env, state, ctx):
    info = _removal_info(state)
    problems = []
    for stage_key in removal.DELETE_STAGE_KEYS:
        items = _removal_items(state, stage_key)
        if not items:
            continue
        leftovers, check_problems = removal.verify_stage_absent(
            env.project, stage_key, items)
        problems.extend(check_problems)
        for item in leftovers:
            problems.append("%s %s existe toujours (étape %s) : supprime-le "
                            "puis relance cette vérification."
                            % (item["kind_fr"], item["name"], stage_key))
    key = info.get("capability_key")
    caps = hub.read_capabilities(env.project) or {}
    if key in caps and info.get("capability_entry_status") != "kept_disabled":
        problems.append("L'entrée %s existe encore dans capabilities.json." % key)
    if problems:
        return _OUT_FAILED, problems
    ctx.done("final_check", "tout est supprimé côté DSS (inventaire re-sondé)")
    ctx.done("final_check",
             "RAPPEL : re-sauvegarde l'orchestrateur dans DSS puis ouvre une "
             "NOUVELLE conversation (le registre des capabilities est chargé au "
             "démarrage du process, piège L168)")
    ctx.done("final_check",
             "l'historique de ce run de suppression reste consultable dans le "
             "store SQL de l'assistant")
    return _OUT_DONE, []
```

3e. Extend the stage registries (right after the existing `_PRECHECKS` dict, line 751; NO removal key ever enters `_PRECHECK_STAGES`: a deletion is never auto-skipped):

```python
_RUNNERS.update({
    "inventory": _run_removal_inventory,
    "disable": _run_removal_disable,
    "delete_tool": _make_removal_delete_runner("delete_tool"),
    "delete_agent": _make_removal_delete_runner("delete_agent"),
    "delete_model": _make_removal_delete_runner("delete_model"),
    "delete_scenario": _make_removal_delete_runner("delete_scenario"),
    "delete_recipes": _make_removal_delete_runner("delete_recipes"),
    "delete_datasets": _make_removal_delete_runner("delete_datasets"),
    "delete_zone": _make_removal_delete_runner("delete_zone"),
    "catalog_cleanup": _run_removal_catalog,
    "hub_cleanup": _run_removal_hub,
    "final_check": _run_removal_final,
})
_CHECKERS.update({
    "inventory": _check_removal_inventory,
    "delete_tool": _make_removal_absent_checker("delete_tool"),
    "delete_agent": _make_removal_absent_checker("delete_agent"),
    "delete_model": _make_removal_absent_checker("delete_model"),
    "delete_scenario": _make_removal_absent_checker("delete_scenario"),
    "delete_recipes": _make_removal_absent_checker("delete_recipes"),
    "delete_datasets": _make_removal_absent_checker("delete_datasets"),
    "delete_zone": _make_removal_absent_checker("delete_zone"),
    "hub_cleanup": _check_removal_hub,
})
_INSTRUCTIONS.update({
    "inventory": _instr_removal_inventory,
    "delete_tool": _make_instr_removal_manual("delete_tool"),
    "delete_agent": _make_instr_removal_manual("delete_agent"),
    "delete_model": _make_instr_removal_manual("delete_model"),
    "delete_scenario": _make_instr_removal_manual("delete_scenario"),
    "delete_recipes": _make_instr_removal_manual("delete_recipes"),
    "delete_datasets": _make_instr_removal_manual("delete_datasets"),
    "delete_zone": _make_instr_removal_manual("delete_zone"),
    "hub_cleanup": _make_instr_removal_manual("hub_cleanup"),
})
```

3f. After `new_state` (line 777), add the removal state + entry points:

```python
def new_removal_state(capability_key, entry):
    stages = {}
    for key in REMOVAL_STAGE_ORDER:
        kind, title_fr, detail_fr = _REMOVAL_STAGE_META[key]
        stages[key] = {"kind": kind, "title_fr": title_fr, "detail_fr": detail_fr,
                       "status": PENDING, "journal": [], "problems": [],
                       "instructions_fr": ""}
    stages[REMOVAL_STAGE_ORDER[0]]["status"] = READY
    return {
        "version": STATE_VERSION,
        "removal": {"capability_key": capability_key, "entry": entry,
                    "inventory": None},
        "stage_order": list(REMOVAL_STAGE_ORDER),
        "stages": stages,
        "captured": {},
    }


def is_removal(run):
    """True for a REMOVAL run. The marker lives in the persisted state (the
    store only persists run_id/domain/status/current_stage/state_json)."""
    return bool((run.get("state") or {}).get("removal"))


def start_removal_run(project, capability_key, settings=None,
                      executor_factory=None, run_id=None, ctx=None):
    """Create a removal run and execute its inventory synchronously.
    Caller persists. Raises ValueError on an unknown capability."""
    settings = settings if settings is not None else hub.get_settings(project)
    caps = hub.read_capabilities(project) or {}
    entry = caps.get(capability_key)
    if not isinstance(entry, dict):
        raise ValueError("unknown capability: %s" % capability_key)
    env = _Env(project, settings, executor_factory)
    run = {
        "run_id": run_id or uuid.uuid4().hex,
        "domain": str(entry.get("domain") or capability_key),
        "status": RUN_ACTIVE,
        "current_stage": REMOVAL_STAGE_ORDER[0],
        "state": new_removal_state(capability_key, entry),
    }
    ctx = ctx or FactoryContext(project=project, dry_run=False,
                                abort_on_failure=False)
    return _execute_current(env, run, ctx)
```

- [ ] **Step 4: Run, verify pass**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_factory_removal.py -v`
Expected: PASS. If `test_full_removal_walk...` loops, print the failing stage's `problems` (the assert message includes them).

- [ ] **Step 5: Full suite + commit**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests`
Expected: OK, zero regression on the creation machine tests.

```bash
git add OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/guided.py \
        OWIsMind_PRD_V1_3_DEV/tests/test_factory_removal.py
git commit -m "feat(guided): removal run type (12 confirmed stages, manual fallback)"
```

---

### Task 6: console backend routes

**Files:**
- Modify: `OWIsMind_PRD_V1_3_DEV/Standard-webapps/agent-factory-console/backend.py` (after `api_hub_capabilities_post`, line 495, and after `api_guided_start`, line 557)
- Test: `OWIsMind_PRD_V1_3_DEV/tests/test_console_guided.py`

**Interfaces:**
- Consumes: `hub.set_capability_enabled`, `hub.read_capabilities`, `guided.start_removal_run`, the existing `_confirmed/_err/_project/_guided_store_for` helpers.
- Produces: `POST /api/capability/enable` (body `{confirm, capability_key, enabled}`) and `POST /api/guided/start-removal` (body `{confirm, capability_key, domain_typed}`; server-side typed-name check). The existing `/api/guided/run|verify|current|abandon` serve removal runs UNCHANGED.

- [ ] **Step 1: Read the harness, then add the route tests**

Read `OWIsMind_PRD_V1_3_DEV/tests/test_console_guided.py` fully first (it defines `_load_backend`, `_FakeProject`, `_FakeStore`, `_Patcher`, `_GuidedRoutesBase` with the request/response plumbing). Then append, reusing its base class exactly as `TestStart` does (adapt ONLY the plumbing call names if they differ from this sketch, keeping every assertion):

```python
class TestCapabilityEnable(_GuidedRoutesBase):
    def test_requires_confirm(self):
        status, body = self._post("api_capability_enable",
                                  {"capability_key": "opportunities_expert",
                                   "enabled": False})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "confirmation_required")

    def test_unknown_capability_404(self):
        status, body = self._post("api_capability_enable",
                                  {"confirm": True, "capability_key": "nope",
                                   "enabled": False})
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "unknown_capability")

    def test_flips_and_returns_capabilities(self):
        status, body = self._post("api_capability_enable",
                                  {"confirm": True,
                                   "capability_key": "opportunities_expert",
                                   "enabled": False})
        self.assertEqual(status, 200)
        self.assertFalse(body["capabilities"]["opportunities_expert"]["enabled"])


class TestStartRemoval(_GuidedRoutesBase):
    def test_typed_name_mismatch_rejected(self):
        status, body = self._post("api_guided_start_removal",
                                  {"confirm": True,
                                   "capability_key": "opportunities_expert",
                                   "domain_typed": "WRONG"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "domain_mismatch")

    def test_active_run_blocks(self):
        self.store.state.active = {"run_id": "r1", "status": "active"}
        status, body = self._post("api_guided_start_removal",
                                  {"confirm": True,
                                   "capability_key": "opportunities_expert",
                                   "domain_typed": "opportunities"})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "active_run_exists")

    def test_creates_and_persists_a_removal_run(self):
        status, body = self._post("api_guided_start_removal",
                                  {"confirm": True,
                                   "capability_key": "opportunities_expert",
                                   "domain_typed": "opportunities"})
        self.assertEqual(status, 200)
        run = body["run"]
        self.assertTrue(run["state"].get("removal"))
        self.assertEqual(run["state"]["stage_order"][0], "inventory")
        self.assertTrue(self.store.state.saved, "the run must be persisted")
```

The base fixture must seed `capabilities.json` in its fake project library with `{"opportunities_expert": <valid entry>}` (reuse the `_entry()` builder pattern from `test_factory_removal.py` or the harness's own capability fixture if it already has one).

- [ ] **Step 2: Run, verify failure**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_console_guided.py -v`
Expected: the new tests FAIL (`AttributeError` on the missing route functions); every pre-existing test still PASSES.

- [ ] **Step 3: Implement the two routes in backend.py**

After `api_hub_capabilities_post` (line 495):

```python
@app.route("/api/capability/enable", methods=["POST"])
@_safe
def api_capability_enable():
    """Flip one capability's enabled flag (validated, backed-up hub write).
    Requires confirm. The UI reminds the operator to re-save the orchestrator
    (the registry is loaded at process start, lesson L168)."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    key = str(body.get("capability_key") or "").strip()
    if not key:
        return _err("capability_key_required", 400)
    project = _project()
    try:
        caps = hub.set_capability_enabled(project, key, bool(body.get("enabled")))
    except KeyError:
        return _err("unknown_capability", 404)
    except ValueError as exc:
        return _err("invalid_capabilities", 400, {"problems": [str(exc)]})
    return jsonify({"status": "ok", "capabilities": caps})
```

After `api_guided_start` (line 557):

```python
@app.route("/api/guided/start-removal", methods=["POST"])
@_safe
def api_guided_start_removal():
    """Create a guided REMOVAL run (its inventory runs synchronously; nothing
    is deleted before the operator confirms each stage). Requires confirm AND
    the domain name TYPED by the operator (server-side check: a spoofed client
    cannot skip it). One active run at a time."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    key = str(body.get("capability_key") or "").strip()
    if not key:
        return _err("capability_key_required", 400)
    project = _project()
    caps = hub.read_capabilities(project) or {}
    entry = caps.get(key)
    if not isinstance(entry, dict):
        return _err("unknown_capability", 404)
    typed = str(body.get("domain_typed") or "").strip()
    if not typed or typed != str(entry.get("domain") or ""):
        return _err("domain_mismatch", 400)
    settings = hub.get_settings(project)
    try:
        store = _guided_store_for(project, settings)
        active = store.load_active()
        if active is not None:
            return _err("active_run_exists", 409, {"run_id": active.get("run_id")})
        run = guided.start_removal_run(project, key, settings=settings)
        store.save(run)
    except guided_store.GuidedStoreError as exc:
        return _err("storage_not_configured", 500, {"messages": [str(exc)]})
    return jsonify({"status": "ok", "run": run})
```

- [ ] **Step 4: Run, verify pass, commit**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -p test_console_guided.py -v`
Expected: PASS.
Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests`
Expected: OK.

```bash
git add OWIsMind_PRD_V1_3_DEV/Standard-webapps/agent-factory-console/backend.py \
        OWIsMind_PRD_V1_3_DEV/tests/test_console_guided.py
git commit -m "feat(console): capability enable route + guided start-removal route"
```

---

### Task 7: console frontend (overview actions + typed confirmation)

**Files:**
- Modify: `OWIsMind_PRD_V1_3_DEV/Standard-webapps/agent-factory-console/script.js` (renderOverview around line 907-929, renderGuided detail around line 545)
- Modify: `OWIsMind_PRD_V1_3_DEV/Standard-webapps/agent-factory-console/style.css`

ES5 only (frozen console constraint), French texts, Orange charter (square, ghost buttons, existing tokens; NO new colors).

- [ ] **Step 1: Render multi-line stage details**

Line 545 currently renders `detail_fr` flat. Change:

```javascript
    if (stage.detail_fr) { html += '<p class="gd-detail">' + esc(stage.detail_fr).replace(/\n/g, "<br>") + '</p>'; }
```

(The inventory writes multi-line "SUPPRIMER : ..." cards into `detail_fr`; without this they collapse to one line.)

- [ ] **Step 2: Add the capability card actions in renderOverview**

Inside the `capKeys.forEach` card builder (line 912-918), append an actions row before the closing `</div>`:

```javascript
        html += '<div class="afc-cap-card">' +
          '<span class="afc-cap-domain">' + esc(c.domain || k) + '</span>' +
          '<span class="afc-cap-label">' + esc(c.label_fr || "") + '</span>' +
          '<span class="afc-cap-id">' + esc(c.agent_id || "-") + '</span>' +
          '<div class="afc-cap-foot">' + enChip +
          '<span class="afc-cap-label mono">' + esc(c.tool_name || "") + '</span></div>' +
          '<div class="afc-cap-actions">' +
          '<button class="afc-btn afc-btn--ghost afc-btn--sm" data-cap-toggle="' + esc(k) + '">' +
          (c.enabled ? "Désactiver" : "Activer") + '</button>' +
          '<button class="afc-btn afc-btn--ghost afc-btn--sm" data-cap-remove="' + esc(k) + '">' +
          'Supprimer...</button>' +
          '</div></div>';
```

If `S.overview.flash` is set, render it as a note right above the grid, then clear it:

```javascript
    if (S.overview.flash) {
      html += '<div class="afc-note afc-note--error">' + esc(S.overview.flash) + '</div>';
      S.overview.flash = null;
    }
```

After `setMain(html)` (line 926), wire the buttons:

```javascript
    Array.prototype.forEach.call(document.querySelectorAll("[data-cap-toggle]"), function (btn) {
      btn.onclick = function () { confirmCapabilityToggle(btn.getAttribute("data-cap-toggle")); };
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-cap-remove]"), function (btn) {
      btn.onclick = function () { openCapabilityRemoval(btn.getAttribute("data-cap-remove")); };
    });
```

- [ ] **Step 3: Add the two handlers (new functions next to renderOverview)**

```javascript
  function confirmCapabilityToggle(key) {
    var caps = (S.overview.data || {}).capabilities || {};
    var c = caps[key] || {};
    var next = !c.enabled;
    openConfirm({
      title: next ? "Activer cette capacité ?" : "Désactiver cette capacité ?",
      bodyHtml: "La capacité <b class=\"mono\">" + esc(key) + "</b> passera à <b>" +
        (next ? "ACTIF" : "INACTIF") + "</b> dans capabilities.json (sauvegarde " +
        "automatique du fichier précédent). L'architecture du domaine n'est pas modifiée." +
        "<br><br>RAPPEL : re-sauvegarde l'orchestrateur dans DSS puis ouvre une " +
        "NOUVELLE conversation pour que le registre soit rechargé (il est lu au " +
        "démarrage du process).",
      confirmLabel: next ? "Activer" : "Désactiver",
      onConfirm: function () {
        callApi("POST", "capability/enable", {
          confirm: true, capability_key: key, enabled: next
        }).then(function (r) {
          if (!r.data || r.data.status !== "ok") {
            S.overview.flash = "Bascule impossible (" +
              ((r.data && r.data.error) || "erreur") + ").";
            renderOverview();
            return;
          }
          S.overview.loaded = false;
          loadOverview();
        });
      }
    });
  }

  function openCapabilityRemoval(key) {
    var caps = (S.overview.data || {}).capabilities || {};
    var c = caps[key] || {};
    var domain = c.domain || key;
    openConfirm({
      title: "Supprimer le domaine " + domain + " ?",
      danger: true,
      bodyHtml: "Un run guidé de SUPPRESSION sera créé pour <b class=\"mono\">" +
        esc(key) + "</b>. Rien n'est supprimé maintenant : l'assistant fait " +
        "d'abord l'inventaire, puis chaque suppression est affichée et confirmée " +
        "UNE PAR UNE. Le dataset source n'est JAMAIS touché." +
        "<br><br>Pour confirmer, tape le nom exact du domaine " +
        "(<b class=\"mono\">" + esc(domain) + "</b>) :" +
        "<br><input type=\"text\" id=\"capRemoveTyped\" autocomplete=\"off\">",
      confirmLabel: "Créer le run de suppression",
      onConfirm: function () {
        var field = byId("capRemoveTyped");
        var typed = (field ? field.value : "").trim();
        callApi("POST", "guided/start-removal", {
          confirm: true, capability_key: key, domain_typed: typed
        }).then(function (r) {
          if (!r.data || r.data.status !== "ok") {
            var code = (r.data && r.data.error) || "erreur";
            S.overview.flash = code === "domain_mismatch"
              ? "Le nom tapé ne correspond pas au domaine : run NON créé."
              : (code === "active_run_exists"
                ? "Un run guidé est déjà actif : termine-le ou abandonne-le d'abord."
                : "Création impossible (" + code + ").");
            renderOverview();
            return;
          }
          S.guided.loaded = false;
          selectTab("guided");
        });
      }
    });
  }
```

Before writing, grep the input styling used by the guided start form (`gdDomain`) and reuse the same class/markup on `capRemoveTyped` so the modal input matches the charter.

- [ ] **Step 4: style.css addition**

Append (square geometry, tokens only, no new colors, matching the existing `afc-cap-card` block):

```css
.afc-cap-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
```

- [ ] **Step 5: Syntax check + review gates**

Run: `node --check OWIsMind_PRD_V1_3_DEV/Standard-webapps/agent-factory-console/script.js`
Expected: no output (exit 0).
Then dispatch the `charte-orange-reviewer` agent on the `script.js` + `style.css` diff (project rule 10).

- [ ] **Step 6: Commit**

```bash
git add OWIsMind_PRD_V1_3_DEV/Standard-webapps/agent-factory-console/script.js \
        OWIsMind_PRD_V1_3_DEV/Standard-webapps/agent-factory-console/style.css
git commit -m "feat(console-ui): capability disable/enable + removal run entry points"
```

---

### Task 8: docs + final verification

**Files:**
- Modify: `OWIsMind_PRD_V1_3_DEV/docs/AGENT_FACTORY.md` (add a "Suppression d'une capacité" section: the 12 removal stages, the source-dataset protection, the last-entry rule, the manual fallback, the L168 re-save reminder)
- Modify: `OWIsMind_PRD_V1_3_DEV/Standard-webapps/agent-factory-console/README.md` (mention the two overview actions and the removal run)

- [ ] **Step 1: Write both doc sections** (French, factual, no U+2014/2013; mirror the stage table from the spec `docs/superpowers/specs/2026-07-22-capability-removal-design.md`).

- [ ] **Step 2: Full-suite gate**

Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests`
Expected: OK (target: 692 pre-existing + roughly 40 new, zero failures).
Run: `node --check OWIsMind_PRD_V1_3_DEV/Standard-webapps/agent-factory-console/script.js`
Expected: exit 0.

- [ ] **Step 3: Adversarial review**

Dispatch the `adversarial-reviewer` agent on the full diff vs the spec (`docs/superpowers/specs/2026-07-22-capability-removal-design.md`), with special attention to: a deletion path reachable WITHOUT a confirmed stage launch, the source dataset ever entering a deletable list, and an unverified deletion advancing the run.

- [ ] **Step 4: Final commit**

```bash
git add OWIsMind_PRD_V1_3_DEV/docs/AGENT_FACTORY.md \
        OWIsMind_PRD_V1_3_DEV/Standard-webapps/agent-factory-console/README.md
git commit -m "docs(removal): capability removal run + console actions documented"
```

---

## Post-plan notes for the operator (not tasks)

- DSS deployment is repo-then-paste as usual: re-paste `owismind_factory` package files (`removal.py` NEW, `guided.py`, `hub.py`, `probes.py`) into the project library, then `backend.py` / `script.js` / `style.css` into the Standard webapp, restart the webapp backend. No plugin zip impact.
- `project.get_semantic_model(id).delete()` and `hub file/folder .delete()` are NOT probe-confirmed on the instance: if the live API lacks them, the stage flips to manual instructions BY DESIGN (that path is tested). No blocker.
- First real-world removal candidate: the aborted `opportunities` objects of 2026-07-21 (user backlog item), an ideal controlled test.
