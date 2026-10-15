"""Failure-mode hardening tests (2026-07-12 night review wave 1).

Locks the fixes from the adversarial reviews: existence checks that refuse to
guess on API errors, post-import verification, downstream step blocking, the
no-placeholder capability rule, explicit-empty apply_config semantics, the
scenario trigger as its own action, reindex gating on a confirmed save, the
probe-only deletion guard, and hub append serialization.

DSS-free: everything runs on fakes.
"""

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "project-library", "python"))

from owismind_factory import (agent_builder, align, doctor, flow_builder, hub,  # noqa: E402
                              pipeline, probes, semantic_builder, tool_builder)
from owismind_factory.fctx import FactoryContext, BLOCKED, FAILED, MANUAL, PLANNED  # noqa: E402
from owismind_factory.spec import DomainSpec  # noqa: E402


def make_spec(**overrides):
    kwargs = dict(domain="satisfaction", base_dataset="CX_Surveys",
                  label_fr="Satisfaction", label_en="Satisfaction")
    kwargs.update(overrides)
    return DomainSpec(**kwargs)


def statuses(ctx):
    return {a["step"]: a["status"] for a in ctx.actions}


class _BrokenListingProject(object):
    """Every list_* call raises, creation methods record any (forbidden) call."""

    def __init__(self):
        self.created = []

    def list_datasets(self):
        raise RuntimeError("HTTP 403 forbidden")

    def list_recipes(self):
        raise RuntimeError("HTTP 502 bad gateway")

    def list_scenarios(self):
        raise RuntimeError("timeout")

    def new_managed_dataset(self, name):
        self.created.append(name)
        raise AssertionError("creation attempted after failed existence check")

    def init_tables_import(self):
        self.created.append("import")
        raise AssertionError("import attempted after failed existence check")

    def create_scenario(self, *a, **k):
        self.created.append("scenario")
        raise AssertionError("scenario created after failed existence check")


class TestExistenceChecks(unittest.TestCase):
    def test_listing_error_is_not_absent(self):
        project = _BrokenListingProject()
        with self.assertRaises(flow_builder.ExistenceCheckError):
            flow_builder.dataset_exists(project, "X")
        with self.assertRaises(flow_builder.ExistenceCheckError):
            flow_builder.recipe_exists(project, "X")
        with self.assertRaises(flow_builder.ExistenceCheckError):
            flow_builder.scenario_exists(project, "X")

    def test_source_dataset_fails_without_creating(self):
        project = _BrokenListingProject()
        ctx = FactoryContext(project=project, dry_run=False)
        result = flow_builder.ensure_source_dataset(ctx, make_spec())
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["source_dataset"], FAILED)
        self.assertEqual(project.created, [])

    def test_knowledge_datasets_fail_without_creating(self):
        project = _BrokenListingProject()
        ctx = FactoryContext(project=project, dry_run=False)
        created = flow_builder.ensure_knowledge_datasets(ctx, make_spec(), "SQL_owi")
        self.assertEqual(created, [])
        self.assertEqual(project.created, [])
        self.assertTrue(all(s == FAILED for s in statuses(ctx).values()))

    def test_scenario_fails_without_creating(self):
        project = _BrokenListingProject()
        ctx = FactoryContext(project=project, dry_run=False)
        flow_builder.ensure_refresh_scenario(ctx, make_spec())
        self.assertEqual(statuses(ctx)["scenario"], FAILED)
        self.assertEqual(project.created, [])

    def test_tool_and_agent_exists_follow_the_same_contract(self):
        class _Broken(object):
            def list_agent_tools(self):
                raise RuntimeError("HTTP 502")

            def list_agents(self):
                raise RuntimeError("HTTP 502")

            def new_agent_tool(self, *a, **k):
                raise AssertionError("tool creation attempted after failed check")

            def create_agent(self, *a, **k):
                raise AssertionError("agent creation attempted after failed check")

        project = _Broken()
        with self.assertRaises(flow_builder.ExistenceCheckError):
            tool_builder.tool_exists(project, "X")
        with self.assertRaises(flow_builder.ExistenceCheckError):
            agent_builder.agent_exists(project, "X")

        ctx = FactoryContext(project=project, dry_run=False)
        result = tool_builder.create_semantic_query_tool_like(
            ctx, make_spec(), "model1",
            {"type": "T", "params_template": {}})
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["semantic_tool"], FAILED)

        ctx2 = FactoryContext(project=project, dry_run=False)
        result2 = agent_builder.create_code_agent(
            ctx2, make_spec(), "# code",
            {"internal_key": "pythonAgentSettings", "code_key": "code"})
        self.assertIsNone(result2)
        self.assertEqual(statuses(ctx2)["code_agent"], FAILED)


class _FakePrepared(object):
    def __init__(self, candidates, project):
        self.candidates = candidates
        self._project = project

    def execute(self):
        class _F(object):
            @staticmethod
            def wait_for_result():
                return None
        return _F()


class _ImportProject(object):
    """Import path fake: candidates use the sqlImportCandidates envelope."""

    def __init__(self, dataset_appears=True):
        self.dataset_appears = dataset_appears
        self.candidates = {"sqlImportCandidates": [
            {"datasetName": "revenues", "table": "REVENUES"}]}
        self._imported = False

    def list_datasets(self):
        if self._imported and self.dataset_appears:
            return [{"name": self.candidates["sqlImportCandidates"][0]["datasetName"]}]
        return []

    def init_tables_import(self):
        project = self

        class _Def(object):
            @staticmethod
            def add_sql_table(*a, **k):
                return None

            @staticmethod
            def prepare():
                project._imported = True
                return _FakePrepared(project.candidates, project)
        return _Def()


class TestSourceImport(unittest.TestCase):
    def test_rename_covers_any_dict_envelope(self):
        project = _ImportProject()
        ctx = FactoryContext(project=project, dry_run=False)
        spec = make_spec(base_dataset="CX_Surveys",
                         source={"connection": "SQL_owi", "table": "REVENUES"})
        result = flow_builder.ensure_source_dataset(ctx, spec)
        self.assertEqual(result, "CX_Surveys")
        self.assertEqual(
            project.candidates["sqlImportCandidates"][0]["datasetName"], "CX_Surveys")

    def test_import_without_landed_dataset_fails(self):
        project = _ImportProject(dataset_appears=False)
        ctx = FactoryContext(project=project, dry_run=False)
        spec = make_spec(source={"connection": "SQL_owi", "table": "REVENUES"})
        result = flow_builder.ensure_source_dataset(ctx, spec)
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["source_dataset"], FAILED)


class _ScenarioSettings(object):
    """Settings fake: raw_steps echoes the creation definition (read-back) and
    the trigger API can be broken independently of the creation."""

    def __init__(self, steps, trigger_raises=False):
        self.active = None
        self.triggers = []
        self.saved_state = "NOT SAVED"
        self.raw_steps = steps
        self._trigger_raises = trigger_raises

    def add_daily_trigger(self, hour, minute):
        if self._trigger_raises:
            raise RuntimeError("trigger API broke")
        self.triggers.append((hour, minute))

    def save(self):
        self.saved_state = self.active


class _ScenarioProject(object):
    """Captures create_scenario args; get_settings echoes the definition."""

    def __init__(self, trigger_raises=False, steps_vanish=False):
        self.created = None
        self.settings = None
        self._trigger_raises = trigger_raises
        self._steps_vanish = steps_vanish

    @staticmethod
    def list_scenarios():
        return []

    def create_scenario(self, name, scenario_type, definition=None):
        self.created = {"name": name, "type": scenario_type,
                        "definition": definition or {}}
        steps = list(((definition or {}).get("params") or {}).get("steps") or [])
        if self._steps_vanish:
            steps = []
        self.settings = _ScenarioSettings(steps, trigger_raises=self._trigger_raises)
        outer = self

        class _Scenario(object):
            def get_settings(self_inner):
                return outer.settings

        return _Scenario()


class TestScenarioCreation(unittest.TestCase):
    """The refresh scenario is STEP-BASED: one build_flowitem step per
    knowledge dataset, verified by raw_steps read-back after creation."""

    def test_step_based_scenario_one_build_step_per_dataset(self):
        project = _ScenarioProject()
        ctx = FactoryContext(project=project, dry_run=False)
        flow_builder.ensure_refresh_scenario(ctx, make_spec())
        self.assertEqual(statuses(ctx)["scenario"], "DONE")
        self.assertEqual(project.created["type"], "step_based")
        spec = make_spec()
        steps = project.created["definition"]["params"]["steps"]
        self.assertEqual([s["params"]["builds"][0]["itemId"] for s in steps],
                         spec.knowledge_datasets)
        for step in steps:
            self.assertEqual(step["type"], "build_flowitem")
            self.assertEqual(step["params"]["jobType"], "RECURSIVE_BUILD")
            self.assertEqual(step["params"]["builds"][0]["type"], "DATASET")
            self.assertEqual(step["params"]["builds"][0]["partitionsSpec"], "")
            self.assertTrue(step["id"])
            self.assertTrue(step["name"])

    def test_steps_missing_after_creation_fail_loudly(self):
        project = _ScenarioProject(steps_vanish=True)
        ctx = FactoryContext(project=project, dry_run=False)
        flow_builder.ensure_refresh_scenario(ctx, make_spec())
        self.assertEqual(statuses(ctx)["scenario"], FAILED)


class TestScenarioTrigger(unittest.TestCase):
    def test_trigger_failure_is_its_own_failed_action(self):
        project = _ScenarioProject(trigger_raises=True)
        ctx = FactoryContext(project=project, dry_run=False)
        flow_builder.ensure_refresh_scenario(ctx, make_spec())
        st = statuses(ctx)
        self.assertEqual(st["scenario"], "DONE")
        self.assertEqual(st["scenario_trigger"], FAILED)

    def test_dry_run_plans_scenario_and_trigger(self):
        class _Project(object):
            @staticmethod
            def list_scenarios():
                return []

        ctx = FactoryContext(project=_Project(), dry_run=True)
        flow_builder.ensure_refresh_scenario(ctx, make_spec())
        st = statuses(ctx)
        self.assertEqual(st["scenario"], PLANNED)
        self.assertEqual(st["scenario_trigger"], PLANNED)

    def test_trigger_step_forces_scenario_inactive_before_save(self):
        # The INACTIVE promise must be explicit: active=False has to be set on
        # the same settings object that defines the trigger, before save().
        project = _ScenarioProject()
        ctx = FactoryContext(project=project, dry_run=False)
        flow_builder.ensure_refresh_scenario(ctx, make_spec(), hour=3)
        st = statuses(ctx)
        self.assertEqual(st["scenario"], "DONE")
        self.assertEqual(st["scenario_trigger"], "DONE")
        self.assertIs(project.settings.saved_state, False)
        self.assertEqual(project.settings.triggers, [(3, 0)])


# ------------------------------------------------------- scenario run and wait

class _FakeRunDetails(object):
    def __init__(self, first_error=None, steps=None):
        self._first_error = first_error
        self.steps = steps or []

    @property
    def first_error_details(self):
        # The real property raises when the run carries no serialized error.
        if self._first_error is None:
            raise ValueError("No error found")
        return self._first_error


class _FakeScenarioRun(object):
    def __init__(self, outcome="SUCCESS", running_polls=0, details=None):
        self._outcome = outcome
        self._remaining = running_polls
        self._details = details

    @property
    def running(self):
        return self._remaining > 0

    def refresh(self):
        if self._remaining > 0:
            self._remaining -= 1

    @property
    def outcome(self):
        return self._outcome

    def get_details(self):
        if self._details is None:
            raise RuntimeError("no details available")
        return self._details


class _RunWaitScenario(object):
    def __init__(self, run=None, current_run=None, fire_cancelled=False):
        self._run = run
        self._current = current_run
        self._fire_cancelled = fire_cancelled
        self.run_calls = 0

    def get_current_run(self):
        return self._current

    def run(self):
        self.run_calls += 1
        outer = self

        class _Fire(object):
            def wait_for_scenario_run(self_inner, no_fail=False):
                return None if outer._fire_cancelled else outer._run

        return _Fire()


class _RunWaitProject(object):
    def __init__(self, scenario, name):
        self._scenario = scenario
        self._name = name

    def list_scenarios(self):
        return [{"id": "SC_1", "name": self._name}]

    def get_scenario(self, scenario_id):
        assert scenario_id == "SC_1", "must resolve the id from the listing"
        return self._scenario


class TestRunScenarioAndWait(unittest.TestCase):
    """run_scenario_and_wait: bounded wait, outcome + error surfacing,
    re-attach to an in-progress run, loud synthetic outcomes."""

    def _spec(self):
        return make_spec()

    def _go(self, scenario, **kwargs):
        project = _RunWaitProject(scenario, self._spec().scenario_name)
        ctx = FactoryContext(project=project, dry_run=False)
        result = flow_builder.run_scenario_and_wait(
            ctx, self._spec(), poll_seconds=0, **kwargs)
        return result, ctx

    def test_success_after_polling(self):
        run = _FakeScenarioRun(outcome="SUCCESS", running_polls=3)
        result, ctx = self._go(_RunWaitScenario(run=run))
        self.assertEqual(result, {"outcome": "SUCCESS", "error": None})
        st = statuses(ctx)
        self.assertEqual(st["scenario_run_start"], "DONE")
        self.assertEqual(st["scenario_run"], "DONE")

    def test_warning_outcome_counts_as_green(self):
        run = _FakeScenarioRun(outcome="WARNING")
        result, _ctx = self._go(_RunWaitScenario(run=run))
        self.assertEqual(result["outcome"], "WARNING")
        self.assertIsNone(result["error"])

    def test_failed_outcome_surfaces_first_error_details(self):
        details = _FakeRunDetails(first_error={"message": "Dataset is partitioned"})
        run = _FakeScenarioRun(outcome="FAILED", details=details)
        result, ctx = self._go(_RunWaitScenario(run=run))
        self.assertEqual(result["outcome"], "FAILED")
        self.assertEqual(result["error"], "Dataset is partitioned")
        self.assertEqual(statuses(ctx)["scenario_run"], FAILED)

    def test_failed_outcome_falls_back_to_step_error(self):
        step = _FakeRunDetails(first_error={"title": "Job failed on recipe"})
        details = _FakeRunDetails(first_error=None, steps=[step])
        run = _FakeScenarioRun(outcome="FAILED", details=details)
        result, _ctx = self._go(_RunWaitScenario(run=run))
        self.assertEqual(result["error"], "Job failed on recipe")

    def test_failed_outcome_without_details_keeps_the_outcome(self):
        run = _FakeScenarioRun(outcome="ABORTED", details=None)
        result, _ctx = self._go(_RunWaitScenario(run=run))
        self.assertEqual(result["outcome"], "ABORTED")
        self.assertIsNone(result["error"])

    def test_timeout_is_bounded_and_explicit(self):
        run = _FakeScenarioRun(outcome="SUCCESS", running_polls=10 ** 6)
        result, ctx = self._go(_RunWaitScenario(run=run), timeout_seconds=3)
        self.assertEqual(result["outcome"], "TIMEOUT")
        self.assertIn("re-attach", result["error"])
        self.assertEqual(statuses(ctx)["scenario_run"], FAILED)

    def test_attaches_to_an_in_progress_run_without_firing(self):
        current = _FakeScenarioRun(outcome="SUCCESS", running_polls=1)
        scenario = _RunWaitScenario(current_run=current)
        result, ctx = self._go(scenario)
        self.assertEqual(result["outcome"], "SUCCESS")
        self.assertEqual(scenario.run_calls, 0, "must NOT fire a second run")
        self.assertIn("attaching", statuses_detail(ctx, "scenario_run_start"))

    def test_missing_scenario_is_not_found(self):
        class _EmptyProject(object):
            @staticmethod
            def list_scenarios():
                return []

        ctx = FactoryContext(project=_EmptyProject(), dry_run=False)
        result = flow_builder.run_scenario_and_wait(ctx, self._spec(), poll_seconds=0)
        self.assertEqual(result["outcome"], "NOT_FOUND")
        self.assertEqual(statuses(ctx)["scenario_run"], FAILED)

    def test_cancelled_fire_is_not_started(self):
        result, ctx = self._go(_RunWaitScenario(run=None, fire_cancelled=True))
        self.assertEqual(result["outcome"], "NOT_STARTED")
        self.assertEqual(statuses(ctx)["scenario_run_start"], FAILED)


def statuses_detail(ctx, step):
    """Concatenated details of a step's actions (assert helper)."""
    return " | ".join(a["detail"] for a in ctx.actions if a["step"] == step)


class _MemHubLibrary(object):
    """Dict-backed fake of the DSS project library (read + write + folders)."""

    def __init__(self, files=None):
        self.files = dict(files or {})

    class _File(object):
        def __init__(self, lib, path):
            self.lib, self.path = lib, path

        def read(self):
            return self.lib.files[self.path]

        def write(self, content):
            self.lib.files[self.path] = content

    class _Folder(object):
        def __init__(self, lib, path):
            self.lib, self.path = lib, path

        def add_folder(self, name):
            return _MemHubLibrary._Folder(self.lib, self.path.rstrip("/") + "/" + name)

        def add_file(self, name):
            path = self.path.rstrip("/") + "/" + name
            self.lib.files[path] = ""
            return _MemHubLibrary._File(self.lib, path)

    @property
    def root(self):
        return self._Folder(self, "")

    def get_file(self, path):
        return self._File(self, path) if path in self.files else None

    def get_folder(self, path):
        prefix = path.rstrip("/") + "/"
        if any(p.startswith(prefix) for p in self.files):
            return self._Folder(self, path)
        return None


class _MemHubProject(object):
    def __init__(self, files=None):
        self.library = _MemHubLibrary(files)

    def get_library(self):
        return self.library


class TestPromptBackup(unittest.TestCase):
    PERSONA = "/python/owismind_hub/prompts/orchestrator_persona.md"

    def test_write_prompt_backs_up_previous_version(self):
        project = _MemHubProject({self.PERSONA: "OLD PERSONA"})
        hub.write_prompt(project, self.PERSONA, "NEW PERSONA")
        files = project.library.files
        self.assertEqual(files[self.PERSONA], "NEW PERSONA")
        self.assertEqual(
            files["/python/owismind_hub/backups/prompts-orchestrator_persona.md-1"],
            "OLD PERSONA")

    def test_write_prompt_backups_do_not_overwrite_each_other(self):
        project = _MemHubProject({self.PERSONA: "V1"})
        hub.write_prompt(project, self.PERSONA, "V2")
        hub.write_prompt(project, self.PERSONA, "V3")
        files = project.library.files
        self.assertEqual(files[self.PERSONA], "V3")
        self.assertEqual(
            files["/python/owismind_hub/backups/prompts-orchestrator_persona.md-1"], "V1")
        self.assertEqual(
            files["/python/owismind_hub/backups/prompts-orchestrator_persona.md-2"], "V2")

    def test_write_prompt_without_previous_version_makes_no_backup(self):
        project = _MemHubProject()
        hub.write_prompt(project, self.PERSONA, "NEW")
        files = project.library.files
        self.assertEqual(files[self.PERSONA], "NEW")
        self.assertFalse(any("/backups/" in p for p in files))


class TestPipelineBlocking(unittest.TestCase):
    def _settings(self):
        return {"sql_connection": "SQL_owi", "code_env_311": "",
                "template_zone_recipes": {}}

    def test_failed_source_blocks_dependent_steps(self):
        project = _BrokenListingProject()
        ctx = FactoryContext(project=project, dry_run=False)
        pipeline.create_domain(ctx, make_spec(), settings=self._settings(),
                               steps=["source_dataset", "recipes", "semantic_model",
                                      "capability"])
        st = statuses(ctx)
        self.assertEqual(st["source_dataset"], FAILED)
        self.assertEqual(st["recipes"], BLOCKED)
        self.assertEqual(st["semantic_model"], BLOCKED)
        # No verified agent id: the capability is a manual step, never FILL_ME.
        self.assertEqual(st["capability"], MANUAL)
        self.assertEqual(project.created, [])

    def test_capability_never_written_with_placeholder(self):
        ctx = FactoryContext(project=object(), dry_run=False)
        pipeline.create_domain(ctx, make_spec(), settings=self._settings(),
                               steps=["capability"])
        st = statuses(ctx)
        self.assertEqual(st["capability"], MANUAL)
        joined = " ".join(a["detail"] for a in ctx.actions)
        self.assertNotIn("FILL_ME", joined)

    def test_dry_run_still_plans_capability(self):
        ctx = FactoryContext(project=object(), dry_run=True)
        pipeline.create_domain(ctx, make_spec(), settings=self._settings(),
                               steps=["capability"])
        self.assertEqual(statuses(ctx)["capability"], PLANNED)


class _FakeVersionSettings(object):
    def __init__(self, raw):
        self._raw = raw
        self.saved = False

    def get_raw(self):
        return self._raw

    def save(self):
        self.saved = True


class _FakeModelProject(object):
    def __init__(self, raw):
        self.settings = _FakeVersionSettings(raw)
        project = self

        class _Version(object):
            @staticmethod
            def get_settings():
                return project.settings

        class _Model(object):
            @staticmethod
            def get_active_version_id():
                return "v1"

            @staticmethod
            def get_version(vid):
                return _Version()
        self._model = _Model()

    def get_semantic_model(self, model_id):
        return self._model


class TestApplyConfigExplicitEmpty(unittest.TestCase):
    def _raw(self):
        return {"entities": [{
            "name": "e", "attributes": [],
            "metrics": [{"name": "old_metric"}],
            "filters": [{"name": "old_filter"}],
        }],
            "goldenQueries": [{"name": "old_gq"}],
            "glossaryTerms": [{"term": "old"}],
            "sqlGenerationConfig": {"instructions": "OLD"}}

    def test_explicit_empty_clears(self):
        # created_this_run=True: this test covers the explicit-empty semantics
        # on a just-created model, not the pre-existing-model guard (which has
        # its own suite in test_security_semantic_guard.py).
        raw = self._raw()
        ctx = FactoryContext(project=_FakeModelProject(raw), dry_run=False)
        semantic_builder.apply_config(ctx, "m1", {
            "metrics": [], "filters": [], "instructions": "",
            "glossary": [], "golden_queries": []}, created_this_run=True)
        entity = raw["entities"][0]
        self.assertEqual(entity["metrics"], [])
        self.assertEqual(entity["filters"], [])
        self.assertEqual(raw["goldenQueries"], [])
        self.assertEqual(raw["glossaryTerms"], [])
        self.assertEqual(raw["sqlGenerationConfig"]["instructions"], "")

    def test_absent_keys_leave_model_untouched(self):
        # created_this_run=True so the absent-key semantics are what is tested,
        # not the pre-existing-model guard (which would also leave it untouched).
        raw = self._raw()
        ctx = FactoryContext(project=_FakeModelProject(raw), dry_run=False)
        semantic_builder.apply_config(ctx, "m1", {"entity_description": "new"},
                                      created_this_run=True)
        entity = raw["entities"][0]
        self.assertEqual(entity["metrics"], [{"name": "old_metric"}])
        self.assertEqual(raw["sqlGenerationConfig"]["instructions"], "OLD")
        self.assertEqual(raw["goldenQueries"], [{"name": "old_gq"}])


class TestAlignReindexGating(unittest.TestCase):
    def test_reindex_blocked_when_save_fails(self):
        class _Settings(object):
            @staticmethod
            def get_raw():
                return {"name": "M", "entities": [
                    {"datasetRef": "OLDKEY.Data", "attributes": []}]}

            @staticmethod
            def save():
                raise RuntimeError("save exploded")

        class _Version(object):
            @staticmethod
            def get_settings():
                return _Settings()

            @staticmethod
            def start_update_distinct_values():
                raise AssertionError("reindex must not run after a failed save")

        class _Model(object):
            id = "m1"

            @staticmethod
            def get_active_version_id():
                return "v1"

            @staticmethod
            def get_version(vid):
                return _Version()

        class _Project(object):
            project_key = "NEWKEY"

            @staticmethod
            def list_semantic_models():
                return [_Model()]

        original = align._iter_models
        align._iter_models = lambda project: [_Model()]
        try:
            ctx = FactoryContext(project=_Project(), dry_run=False)
            # OLDKEY is explicitly allowlisted: this test covers the reindex
            # gating on a failed save, not the discovery mode (which remaps
            # nothing and is covered by test_security_align.py).
            align.align(_Project(), ctx, reindex=True,
                        expected_source_keys=["OLDKEY"])
        finally:
            align._iter_models = original
        by_suffix = {a["step"].rsplit(".", 1)[-1]: a["status"] for a in ctx.actions}
        self.assertEqual(by_suffix.get("save"), FAILED)
        self.assertEqual(by_suffix.get("reindex"), BLOCKED)


class TestDoctorRecency(unittest.TestCase):
    def test_rows_sorted_by_timestamp_desc(self):
        rows = [{"ts": "2026-01-01", "input": "old"},
                {"ts": "2026-07-01", "input": "new"},
                {"ts": "2026-03-01", "input": "mid"}]

        class _FakeDataset(object):
            @staticmethod
            def read_schema():
                return [{"name": "ts"}, {"name": "input"}]

            @staticmethod
            def iter_rows():
                return iter(rows)

        class _FakeDataikuModule(object):
            @staticmethod
            def Dataset(name):
                return _FakeDataset()

        sys.modules["dataiku"] = _FakeDataikuModule()
        try:
            out = doctor.collect_interactions(object(), "traces", limit=2)
        finally:
            del sys.modules["dataiku"]
        self.assertEqual([i["ts"] for i in out], ["2026-07-01", "2026-03-01"])


class TestDeletionConfinement(unittest.TestCase):
    _PACKAGE = os.path.join(os.path.dirname(__file__), "..",
                            "project-library", "python", "owismind_factory")

    # Sanctioned deletion sites (spec 2026-07-22, capability removal): probes.py
    # cleans its own throwaway objects; removal.py is THE deletion engine (every
    # object delete goes through its safe_delete identity gate); hub.py deletes
    # library files/folders in delete_path only. Everything else stays zero-delete.
    _DELETE_WHITELIST = ("probes.py", "removal.py", "hub.py")

    def test_delete_calls_only_in_sanctioned_modules(self):
        offenders = []
        for name in sorted(os.listdir(self._PACKAGE)):
            if not name.endswith(".py") or name in self._DELETE_WHITELIST:
                continue
            with open(os.path.join(self._PACKAGE, name)) as fh:
                if ".delete(" in fh.read():
                    offenders.append(name)
        self.assertEqual(offenders, [],
                         "deletion outside the sanctioned modules (%s) violates "
                         "the deletion-confinement rule" % ", ".join(self._DELETE_WHITELIST))

    def test_probe_delete_guard_refuses_wrong_name(self):
        class _Handle(object):
            deleted = False

            def delete(self):
                self.deleted = True

        handle = _Handle()
        with self.assertRaises(RuntimeError):
            probes._delete_probe_object(handle, "zz_factory_probe",
                                        lambda: "REAL_PRODUCTION_AGENT")
        self.assertFalse(handle.deleted)

    def test_probe_delete_guard_allows_probe_name(self):
        class _Handle(object):
            deleted = False

            def delete(self):
                self.deleted = True

        handle = _Handle()
        probes._delete_probe_object(handle, "zz_factory_probe",
                                    lambda: "zz_factory_probe")
        self.assertTrue(handle.deleted)


class TestPlaceholderAgentIdRejected(unittest.TestCase):
    """Both validators must refuse placeholder agent ids (agent:FILL_ME)."""

    def _valid_caps(self):
        import json as _json
        seed_path = os.path.join(os.path.dirname(__file__), "..",
                                 "project-library", "python", "owismind_hub", "capabilities.json")
        with open(seed_path) as fh:
            return _json.load(fh)

    def test_factory_validator_rejects_placeholder(self):
        caps = self._valid_caps()
        key = next(k for k, c in caps.items() if c.get("kind") == "agent")
        self.assertEqual(hub.validate_capabilities(caps), [])
        caps[key]["agent_id"] = "agent:FILL_ME"
        self.assertTrue(any("not a real DSS id" in p
                            for p in hub.validate_capabilities(caps)))
        caps[key]["agent_id"] = "agent:"
        self.assertTrue(hub.validate_capabilities(caps))


class TestRegistryLabelsMatchLiveCapabilities(unittest.TestCase):
    """registry.py label constants must equal the live accented labels.

    The hub capabilities seed is byte-equal to the orchestrator's embedded
    CAPABILITIES (existing equivalence test), so comparing against the seed
    pins factory-generated entries to the exact live label strings (accents
    included).
    """

    def test_block_and_tool_labels_match_seed(self):
        import json as _json
        from owismind_factory import registry as reg
        seed_path = os.path.join(os.path.dirname(__file__), "..",
                                 "project-library", "python", "owismind_hub", "capabilities.json")
        with open(seed_path) as fh:
            seed = _json.load(fh)
        agent_caps = [c for c in seed.values() if c.get("kind") == "agent"]
        self.assertTrue(agent_caps)
        for cap in agent_caps:
            self.assertEqual(cap["block_labels"],
                             {k: (dict(v) if isinstance(v, dict) else v)
                              for k, v in reg._BLOCK_LABELS.items()})
            self.assertEqual(cap["tool_labels"],
                             {k: dict(v) for k, v in reg._TOOL_LABELS.items()})


class TestFactorySettingsSeedEquivalence(unittest.TestCase):
    """project-library/python/owismind_hub/factory_settings.json seed must equal DEFAULT_SETTINGS.

    Same anti-drift rule as the capabilities/persona seeds: a silent divergence
    on sql_connection or the template ids would change factory behavior
    depending on whether the hub was pushed.
    """

    def test_seed_equals_embedded_defaults(self):
        import json as _json
        seed_path = os.path.join(os.path.dirname(__file__), "..",
                                 "project-library", "python", "owismind_hub", "factory_settings.json")
        with open(seed_path) as fh:
            seed = _json.load(fh)
        self.assertEqual(seed, hub.DEFAULT_SETTINGS)


class TestHubAppendSerialization(unittest.TestCase):
    def test_concurrent_appends_keep_both_entries(self):
        files = {}
        originals = (hub.read_text, hub.write_text)

        def fake_read_text(project, path):
            return files.get(path)

        def fake_write_text(project, path, content):
            files[path] = content
            return path

        hub.read_text, hub.write_text = fake_read_text, fake_write_text
        try:
            import json as _json
            seed = _json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                                "project-library", "python", "owismind_hub", "capabilities.json")))
            first_key = sorted(seed.keys())[0]
            entry = seed[first_key]
            barrier = threading.Barrier(2)
            errors = []

            def worker(key):
                try:
                    barrier.wait(timeout=5)
                    e = dict(entry)
                    e["enabled"] = False
                    hub.append_capability(object(), key, e)
                except Exception as exc:  # pragma: no cover - surfaced below
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=("cap_a",)),
                       threading.Thread(target=worker, args=("cap_b",))]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
            self.assertEqual(errors, [])
            final = _json.loads(files[hub.CAPABILITIES_PATH])
            self.assertIn("cap_a", final)
            self.assertIn("cap_b", final)
        finally:
            hub.read_text, hub.write_text = originals


if __name__ == "__main__":
    unittest.main()
